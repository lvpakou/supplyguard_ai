"""CHAINLIT CHAT. OWNER: role 5.

    uv run chainlit run src/supplyguard_ai/chat_app.py

Login: user_id from data/config/users.csv (e.g. u-pm-01) + DEMO_PASSWORD from .env.
Every new case carries the user's id and role, so retrieval only shows the documents
that role may see. Needs CHAINLIT_AUTH_SECRET in .env (create it with `chainlit create-secret`).

Still to come (role 5): evidence display, options table, Approve / Reject / Change, follow-ups.
"""

import hmac
import os
import uuid

import chainlit as cl
from langgraph.types import Command

from supplyguard_ai.auth import document_scopes, users
from supplyguard_ai.config import database_url
from supplyguard_ai.graph import build_graph, make_async_checkpointer

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
    return {"configurable": {"thread_id": thread_id}}


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


@cl.on_chat_start
async def greet() -> None:
    user = cl.user_session.get("user")
    scopes = ", ".join(document_scopes(user.identifier))
    await cl.Message(f"Signed in as **{user.metadata['name']}** ({user.metadata['role']}). "
                     f"Documents you can see: {scopes}.\n\nDescribe the supply disruption.").send()


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


@cl.on_message
async def on_message(message: cl.Message) -> None:
    thread_id, graph_input, reply = route_message(cl.user_session.get("thread_id"), message.content)
    cl.user_session.set("thread_id", thread_id)
    if reply:
        await cl.Message(reply).send()
    if isinstance(graph_input, dict):  # a new case
        graph_input = with_user(graph_input, cl.user_session.get("user"))
    if graph_input is not None:
        await run(graph_input, thread_id)


@cl.action_callback("decide")
async def on_decide(action: cl.Action) -> None:
    await action.remove()
    await cl.Message(action.payload["decision"].capitalize(), type="user_message").send()
    await run(Command(resume=action.payload["decision"]), action.payload["thread_id"])


async def run(graph_input, thread_id: str) -> None:
    graph = await get_graph()
    config = _config(thread_id)
    async for event in graph.astream(graph_input, config, stream_mode="tasks"):
        if "input" in event and event["name"] not in {"clarify", "approval", "followup"}:
            await cl.Message(f"_{event['name']}..._").send()
    snapshot = await graph.aget_state(config)
    await show(snapshot.values, snapshot.interrupts, thread_id)


async def show(values: dict, interrupts, thread_id: str) -> None:
    payload = interrupts[0].value if interrupts else None
    if payload is None:
        return
    if payload["type"] == "clarification":
        await cl.Message(payload["question"]).send()
    elif payload["type"] == "approval":
        impact, rec, request = values.get("impact"), values["recommendation"], payload["request"]
        lines = ["### Recommendation", rec.summary, ""]
        if impact:
            lines.append(f"Usable stock {impact.usable} · shortfall {impact.shortfall_units} units · "
                         f"{impact.open_orders_at_risk} orders at risk")
        lines += [f"**Total cost:** EUR {request['total_cost_eur']:,.2f} · approver: {request['approver_role']}",
                  f"Approval {request['approval_id']} (payload {request['payload_hash']})"]
        for warning in values.get("warnings", []):
            lines.append(f"⚠️ {warning}")
        actions = [cl.Action(name="decide", label=label, payload={"decision": d, "thread_id": thread_id})
                   for d, label in (("approve", "✅ Approve"), ("reject", "❌ Reject"))]
        await cl.Message("\n".join(lines), actions=actions).send()
    elif payload["type"] == "followup":
        if values.get("followups"):
            await cl.Message(values["followups"][-1].answer).send()
        elif values.get("report"):
            await cl.Message(values["report"] + "\n\n_Ask a follow-up question, or type **new**._").send()
