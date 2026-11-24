"""CHAINLIT CHAT. OWNER: role 5.

    uv run chainlit run src/supplyguard_ai/chat_app.py

Login: user_id from data/config/users.csv (e.g. u-pm-01) + DEMO_PASSWORD from .env.
Every new case carries the user's id and role, so retrieval only shows the documents
that role may see. Needs CHAINLIT_AUTH_SECRET in .env (create it with `chainlit create-secret`).

Approval: the request shows the exact actions; Approve / Reject / Change are checked on the
server (role, current payload_hash, case from the session, never from the button). A tier with
two roles needs both sign-offs; the second approver finds the case in their greeting, also
after a restart. Typed text never decides an approval.

Follow-ups: a question typed while the approval waits, or after the decision, is answered from
the saved case (followup.py); the answer is shown and the case keeps waiting where it was.

Investigation: before each new approval request, three messages show the impact, the evidence
with clickable sources and resolved conflicts, and the recovery options compared (chat_views.py).
"""

import hmac
import os
import uuid

import chainlit as cl
from langgraph.types import Command

from supplyguard_ai import approval as approvals
from supplyguard_ai import chat_views as views
from supplyguard_ai.auth import document_scopes, users
from supplyguard_ai.config import database_url
from supplyguard_ai.graph import arecent_cases, build_graph, is_resume_request, make_async_checkpointer
from supplyguard_ai.nodes import APPROVE_WORDS, REJECT_WORDS
from supplyguard_ai.state import ApprovalRequest
from supplyguard_ai.tracing import run_config

DECISIONS = (("approve", "✅ Approve"), ("reject", "❌ Reject"), ("change", "✏️ Change"))

_graph = None


async def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph(await make_async_checkpointer(database_url()))
    return _graph


@cl.data_layer
def no_chainlit_history():
    """Chainlit would use DATABASE_URL for its own history; the checkpointer already saves cases."""
    return None


def _config(thread_id: str) -> dict:
    # thread_id + the run name, tag and metadata LangSmith shows (tracing.py)
    return run_config(thread_id, "chat")


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@cl.password_auth_callback
async def login(username: str, password: str) -> cl.User | None:
    """Known user_id + the demo password -> signed in with the role from users.csv.

    users.csv is trainer data without passwords, so the demo shares one password (DEMO_PASSWORD).
    If it is not set, nobody can sign in.
    """
    user = users().get(username.strip().lower())
    expected = os.getenv("DEMO_PASSWORD", "")
    if not user or not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        return None
    return cl.User(identifier=user["user_id"], display_name=user["name"],
                   metadata={"name": user["name"], "role": user["role"]})


def with_user(case_start: dict, user: cl.User) -> dict:
    """A new case runs as the signed-in user: their role decides which documents it may use."""
    return {**case_start, "user_id": user.identifier, "user_role": user.metadata["role"]}


def _user() -> tuple[str, str]:
    user = cl.user_session.get("user")
    return user.identifier, user.metadata["role"]


@cl.on_chat_start
async def greet() -> None:
    user = cl.user_session.get("user")
    scopes = ", ".join(document_scopes(user.identifier))
    await cl.Message(f"Signed in as **{user.metadata['name']}** ({user.metadata['role']}). "
                     f"Documents you can see: {scopes}.\n\nDescribe the supply disruption.").send()
    waiting = await open_approvals(user.metadata["role"]) if database_url() else []
    if waiting:
        lines = ["**Approval requests waiting for your role:**"]
        lines += [f"- {r.approval_id}: EUR {r.total_cost_eur:,.2f} (needs {r.approver_role})" for _, r in waiting]
        buttons = [cl.Action(name="open_case", label=f"Open {r.approval_id}", payload={"case_id": case_id})
                   for case_id, r in waiting]
        await cl.Message("\n".join(lines), actions=buttons).send()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def route_message(thread_id: str | None, text: str) -> tuple[str | None, object | None, str | None]:
    """Decide what one chat message means: (thread_id to keep, graph input, reply).

    - "new"            -> forget the open case; the NEXT message starts a new one
    - no open case     -> this message starts a new case
    - an open case     -> this message answers the paused step (resume)
    """
    if text.strip().lower() == "new":
        return None, None, "OK, describe the next disruption."
    if thread_id is None:
        thread_id = str(uuid.uuid4())
        return thread_id, {"case_id": thread_id, "raw_text": text}, None
    return thread_id, Command(resume=text), None


def is_decision(text: str) -> bool:
    """Would the approval node read this text as approve / reject / change? (same rule as nodes.approval)"""
    word = text.strip().lower().strip(".!")
    return word in APPROVE_WORDS or word in REJECT_WORDS or word.startswith("change")


@cl.on_message
async def on_message(message: cl.Message) -> None:
    if is_resume_request(message.content):  # "Resume the case I was reviewing yesterday"
        await show_saved_cases()
        return
    thread_id, graph_input, reply = route_message(cl.user_session.get("thread_id"), message.content)
    cl.user_session.set("thread_id", thread_id)
    if reply:
        await cl.Message(reply).send()
    if isinstance(graph_input, dict):  # a new case
        graph_input = with_user(graph_input, cl.user_session.get("user"))
    elif graph_input is not None and is_decision(message.content) and await pending_approval(thread_id):
        # Typed text never decides an approval: only the checked buttons can. Questions go through.
        await cl.Message("This case is waiting for an approval decision: please use the buttons.").send()
        await show_case(thread_id)
        return
    if graph_input is not None:
        await run(graph_input, thread_id)


# ---------------------------------------------------------------------------
# Resuming a saved case (role 1: graph.recent_cases). Cases are in the Postgres
# checkpointer, so this also works the next day and after a restart.
# ---------------------------------------------------------------------------
async def show_saved_cases() -> None:
    user_id, _ = _user()
    cases = await arecent_cases(await get_graph(), user_id=user_id)
    if not cases:
        await cl.Message("You have no saved cases yet. Describe a supply disruption to start one.").send()
        return
    lines = ["**Your recent cases** (newest first):"]
    lines += [f"- {c['updated']} · {c['request']} · _{c['status']}_" for c in cases]
    buttons = [cl.Action(name="resume_case", label=f"Open {c['case_id'][:8]}", payload={"case_id": c["case_id"]})
               for c in cases]
    await cl.Message("\n".join(lines), actions=buttons).send()


@cl.action_callback("resume_case")
async def on_resume_case(action: cl.Action) -> None:
    user_id, _ = _user()
    case_id = action.payload["case_id"]
    if case_id not in [c["case_id"] for c in await arecent_cases(await get_graph(), user_id=user_id)]:
        await cl.Message("That case is not one of yours.").send()   # never trust the button
        return
    cl.user_session.set("thread_id", case_id)
    snapshot = await (await get_graph()).aget_state(_config(case_id))
    await cl.Message(f"Resumed case {case_id[:8]}: {snapshot.values.get('raw_text', '')}").send()
    await show_case(case_id)


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------
async def pending_approval(case_id: str) -> ApprovalRequest | None:
    """The approval request the case is paused at, or None."""
    snapshot = await (await get_graph()).aget_state(_config(case_id))
    payload = snapshot.interrupts[0].value if snapshot.interrupts else None
    return ApprovalRequest(**payload["request"]) if payload and payload["type"] == "approval" else None


async def open_approvals(user_role: str) -> list[tuple[str, ApprovalRequest]]:
    """Cases still paused at an approval that this role must sign (survives a restart)."""
    found = []
    for case_id in await cl.make_async(approvals.cases_for_role)(user_role):
        request = await pending_approval(case_id)
        if request:
            found.append((case_id, request))
    return found


@cl.action_callback("open_case")
async def on_open_case(action: cl.Action) -> None:
    _, role = _user()
    case_id = action.payload["case_id"]
    if case_id not in [c for c, _ in await open_approvals(role)]:  # never trust the button
        await cl.Message("That case is not waiting for your role any more.").send()
        return
    cl.user_session.set("thread_id", case_id)
    await show_case(case_id, details=True)  # the second approver sees the whole investigation


@cl.action_callback("decide")
async def on_decide(action: cl.Action) -> None:
    thread_id = cl.user_session.get("thread_id")  # the case comes from the session, not the button
    user_id, role = _user()
    decision = action.payload["decision"]
    request = await pending_approval(thread_id) if thread_id else None
    if request is None:
        await cl.Message("There is no approval waiting in this case.").send()
        return
    if request.payload_hash != action.payload["payload_hash"]:
        await cl.Message("The plan changed since you saw it. Please review the new request.").send()
        await show_case(thread_id)
        return
    if not approvals.can_decide(role, request, decision):
        await cl.Message(f"Your role ({role}) may not {decision} this request "
                         f"(it needs {request.approver_role}).").send()
        return

    await action.remove()
    note = None
    if decision == "change":
        answer = await cl.AskUserMessage("What should change (supplier, quantity, price, date...)?",
                                         timeout=600).send()
        if not answer:
            await show_case(thread_id)
            return
        note = answer["output"]
    else:
        await cl.Message(decision.capitalize(), type="user_message").send()

    await cl.make_async(approvals.record)(thread_id, request, user_id, role, decision, note)
    if decision == "approve":
        missing = approvals.missing_signoffs(request, await cl.make_async(approvals.decisions)(request.approval_id))
        if missing:
            await cl.Message(f"Your approval is recorded. Still needed: **{' and '.join(missing)}**. "
                             "They will find this request when they sign in.").send()
            return
    await run(Command(resume={"decision": decision, "change": note, "user_id": user_id,
                              "user_role": role, "payload_hash": request.payload_hash}), thread_id)


# ---------------------------------------------------------------------------
# Running the graph and showing where it stopped
# ---------------------------------------------------------------------------
async def run(graph_input, thread_id: str) -> None:
    graph = await get_graph()
    asked = len((await graph.aget_state(_config(thread_id))).values.get("followups", []))
    waiting = await pending_approval(thread_id)
    async for event in graph.astream(graph_input, _config(thread_id), stream_mode="tasks"):
        if "input" in event and event["name"] not in {"clarify", "approval", "followup"}:
            await cl.Message(f"_{event['name']}..._").send()
    request = await pending_approval(thread_id)
    if request and request != waiting:  # a new approval round: audit it, and let approvers find it
        user_id, role = _user()
        await cl.make_async(approvals.record)(thread_id, request, user_id, role, "requested")

    snapshot = await graph.aget_state(_config(thread_id))
    followups = snapshot.values.get("followups", [])
    if len(followups) > asked:  # a question was answered: show the answer, the case stays where it was
        note = "\n\n_The approval request above is still waiting for a decision._" if request else ""
        await cl.Message(followups[-1].answer + note).send()
        return
    await show(snapshot.values, snapshot.interrupts, details=request is not None and request != waiting)


async def show_case(thread_id: str, details: bool = False) -> None:
    snapshot = await (await get_graph()).aget_state(_config(thread_id))
    await show(snapshot.values, snapshot.interrupts, details)


async def show(values: dict, interrupts, details: bool = False) -> None:
    """Where the case stopped. details: also the investigation before an approval request."""
    payload = interrupts[0].value if interrupts else None
    if payload is None:
        return
    if payload["type"] == "clarification":
        await cl.Message(payload["question"]).send()
    elif payload["type"] == "approval":
        if details:
            await show_investigation(values)
        await show_approval(values, ApprovalRequest(**payload["request"]))
    elif payload["type"] == "followup" and values.get("report"):
        # Answers are shown by run() as they come; here the case is closed: show its report.
        await cl.Message(values["report"] + "\n\n_Ask a follow-up question, or type **new**._").send()


async def show_investigation(values: dict) -> None:
    """Impact, evidence (each source opens its document in the side panel), options compared."""
    documents = [cl.Text(name=e.source_id, content=e.claim, display="side") for e in views.documents(values)]
    for text, elements in ((views.impact_view(values), []), (views.evidence_view(values), documents),
                           (views.options_view(values), [])):
        if text:
            await cl.Message(text, elements=elements).send()


async def show_approval(values: dict, request: ApprovalRequest) -> None:
    """The exact actions, quantities, prices and costs the human approves, with evidence."""
    rec, impact, facts = values["recommendation"], values.get("impact"), values.get("facts")
    _, role = _user()
    lines = [f"### Approval request {request.approval_id}", rec.summary, ""]
    if impact:
        lines += [f"Usable stock {impact.usable} · shortfall {impact.shortfall_units} units · "
                  f"{impact.open_orders_at_risk} orders at risk", ""]
    lines += ["| # | Exact action | Cost (EUR) |", "|---|---|---:|"]
    actions = [a for option in rec.options for a in option.actions]
    lines += [f"| {i} | {approvals.describe(a)} | {a.cost_eur:,.2f} |" for i, a in enumerate(actions, 1)]
    lines += [f"| | **Total** | **{request.total_cost_eur:,.2f}** |", ""]
    # One bullet per line: markdown would join plain consecutive lines into one paragraph.
    if facts:
        lines.append(f"- Spending cap: EUR {facts.spending_cap_eur:,.0f}")
    if rec.uncovered_units:
        lines.append(f"- Not covered by this plan: {rec.uncovered_units} units")
    evidence = sorted({e for option in rec.options for e in option.evidence_ids})
    if evidence:
        lines.append("- Evidence: " + ", ".join(evidence))
    if values.get("critique"):
        lines += ["", "**Challenge findings:**", ""] + [f"- 🔎 {finding}" for finding in values["critique"]]
    if values.get("warnings"):
        lines += ["", "**Warnings:**", ""] + [f"- ⚠️ {warning}" for warning in values["warnings"]]

    roles = approvals.required_roles(request.approver_role)
    missing = approvals.missing_signoffs(request, await cl.make_async(approvals.decisions)(request.approval_id))
    lines += ["", "- **Approval needed from:** " + (" and ".join(roles) or "nobody: above every approval tier")]
    if roles and len(missing) < len(roles):
        lines.append("- Already approved by: " + ", ".join(r for r in roles if r not in missing))
    lines += ["", f"_Payload {request.payload_hash}. Nothing is ordered before approval; "
                  "any change needs a new approval._"]

    buttons = [cl.Action(name="decide", label=label, payload={"decision": d, "payload_hash": request.payload_hash})
               for d, label in DECISIONS if approvals.can_decide(role, request, d)]
    if not buttons:
        lines += ["", f"_Your role ({role}) cannot decide this request._"]
    await cl.Message("\n".join(lines), actions=buttons).send()
