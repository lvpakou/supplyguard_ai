r"""THE INCIDENT WORKFLOW (LangGraph). OWNER: role 1.

    START -> intake --(unclear)--> clarify --> intake
               |
               v
             impact -> evidence -> dependencies -> options -> challenge -> approval (pause) <-+
                                                     ^                       |   | question |
                                                     +------ changed --------+   +----------+
                                                                             | approved
                                                     report <-- rejected ----+--> execute -> report
                                                       |
                                                       v
                                                    followup (pause, loops)

State is saved after every step (checkpointer): in Postgres when DATABASE_URL is set,
so a case paused at the approval survives a restart and resumes without duplicate actions.
"""

import re

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import START, StateGraph
from psycopg import AsyncConnection, Connection
from psycopg.rows import dict_row

from supplyguard_ai import nodes, state as state_module
from supplyguard_ai.state import CaseState

MAX_CLARIFICATION_ROUNDS = 2


# ---------------------------------------------------------------------------
# Routing (reads the state, never changes it)
# ---------------------------------------------------------------------------
def route_after_intake(state: CaseState) -> str:
    if state.needs_clarification and len(state.clarifications) < MAX_CLARIFICATION_ROUNDS:
        return "clarify"
    if not state.facts or not state.facts.component_id:
        return "give_up"  # still no component after asking: nothing to investigate
    return "investigate"


def route_after_approval(state: CaseState) -> str:
    """approved -> execute · changed -> options (new plan) · rejected -> report ·
    still pending (the user asked a question) -> wait for the decision again."""
    return {"approved": "execute", "changed": "options", "pending": "approval"}.get(
        state.approval.status, "report")


# ---------------------------------------------------------------------------
# Checkpointer
# ---------------------------------------------------------------------------
def _serializer() -> JsonPlusSerializer:
    """Allow our Pydantic classes to be saved and loaded back."""
    ours = [obj for obj in vars(state_module).values()
            if isinstance(obj, type) and obj.__module__ == state_module.__name__]
    return JsonPlusSerializer(allowed_msgpack_modules=[(c.__module__, c.__name__) for c in ours])


_PG_OPTIONS = {"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}


def make_checkpointer(database_url: str | None = None):
    """In memory (tests) or Postgres (DATABASE_URL), for graph.invoke."""
    if database_url is None:
        return InMemorySaver(serde=_serializer())
    saver = PostgresSaver(Connection.connect(database_url, **_PG_OPTIONS), serde=_serializer())
    saver.setup()
    return saver


async def make_async_checkpointer(database_url: str | None):
    """The same for the async Chainlit app (graph.astream)."""
    if database_url is None:
        return InMemorySaver(serde=_serializer())
    saver = AsyncPostgresSaver(await AsyncConnection.connect(database_url, **_PG_OPTIONS), serde=_serializer())
    await saver.setup()
    return saver


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------
def build_graph(checkpointer=None, interrupt_before=None, interrupt_after=None):
    """The compiled workflow. interrupt_before/after are only used by the evaluation, to
    "kill" the app at a given step and test that it resumes (restart_recovery cases)."""
    builder = StateGraph(CaseState)
    for name in ["intake", "clarify", "impact", "evidence", "dependencies", "options",
                 "challenge", "approval", "execute", "report", "followup"]:
        builder.add_node(name, getattr(nodes, name))

    builder.add_edge(START, "intake")
    builder.add_conditional_edges("intake", route_after_intake,
                                  {"clarify": "clarify", "investigate": "impact", "give_up": "report"})
    builder.add_edge("clarify", "intake")
    builder.add_edge("impact", "evidence")
    builder.add_edge("evidence", "dependencies")
    builder.add_edge("dependencies", "options")
    builder.add_edge("options", "challenge")
    builder.add_edge("challenge", "approval")
    builder.add_conditional_edges("approval", route_after_approval,
                                  {"execute": "execute", "options": "options", "report": "report",
                                   "approval": "approval"})
    builder.add_edge("execute", "report")
    builder.add_edge("report", "followup")
    builder.add_edge("followup", "followup")
    return builder.compile(
        checkpointer=checkpointer or make_checkpointer(),
        interrupt_before=interrupt_before,
        interrupt_after=interrupt_after,
    )


def pending(result: dict) -> dict | None:
    """What the graph is paused for (the dict given to interrupt()), or None."""
    interrupts = result.get("__interrupt__")
    return interrupts[0].value if interrupts else None


# ---------------------------------------------------------------------------
# Resuming a saved case ("Resume the case I was reviewing yesterday")
# ---------------------------------------------------------------------------
_RESUME = re.compile(r"^\s*(resume|continue)\b|case i was (reviewing|working on)|yesterday'?s case",
                     re.IGNORECASE)


def is_resume_request(text: str) -> bool:
    """'resume', 'Continue my case', 'Resume the case I was reviewing yesterday' -> True."""
    text = text.strip()
    return bool(_RESUME.search(text)) and (len(text) < 100 or "case" in text.lower())


def case_status(interrupts) -> str:
    """Where a saved case stopped, in words for the user."""
    kind = interrupts[0].value.get("type") if interrupts else None
    return {"clarification": "waiting for your answer", "approval": "waiting for approval",
            "followup": "decided (you can ask follow-up questions)"}.get(kind, "in progress")


def _summary(snapshot) -> dict | None:
    values = snapshot.values
    if not values or "case_id" not in values:
        return None
    # A field nobody wrote is not saved: fall back to CaseState's default (e.g. user_id).
    user_id = values.get("user_id", CaseState.model_fields["user_id"].default)
    return {"case_id": values["case_id"], "user_id": user_id,
            "request": values.get("raw_text", "")[:90], "status": case_status(snapshot.interrupts),
            "updated": (snapshot.created_at or "")[:16].replace("T", " ")}


def _newest_threads(checkpoints) -> list[str]:
    """Thread ids, most recently saved first (each checkpoint has a timestamp "ts")."""
    newest: dict[str, str] = {}
    for item in checkpoints:
        thread = item.config["configurable"]["thread_id"]
        newest[thread] = max(newest.get(thread, ""), item.checkpoint["ts"])
    return sorted(newest, key=newest.get, reverse=True)


def recent_cases(app, user_id: str | None = None, limit: int = 5) -> list[dict]:
    """The saved cases (newest first) of this user, read from the checkpointer: they survive
    a restart when the checkpointer is Postgres."""
    found = []
    for thread in _newest_threads(app.checkpointer.list(None)):
        summary = _summary(app.get_state({"configurable": {"thread_id": thread}}))
        if summary and (user_id is None or summary["user_id"] == user_id):
            found.append(summary)
        if len(found) == limit:
            break
    return found


async def arecent_cases(app, user_id: str | None = None, limit: int = 5) -> list[dict]:
    """The same for the async chat."""
    found = []
    for thread in _newest_threads([c async for c in app.checkpointer.alist(None)]):
        summary = _summary(await app.aget_state({"configurable": {"thread_id": thread}}))
        if summary and (user_id is None or summary["user_id"] == user_id):
            found.append(summary)
        if len(found) == limit:
            break
    return found
