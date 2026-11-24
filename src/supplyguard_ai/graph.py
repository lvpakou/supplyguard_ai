r"""THE INCIDENT WORKFLOW (LangGraph). OWNER: role 1.

    START -> intake --(unclear)--> clarify --> intake
               |
               v
             impact -> evidence -> dependencies -> options -> challenge -> approval (pause)
                                                     ^                       |
                                                     +------ changed --------+
                                                                             | approved
                                                     report <-- rejected ----+--> execute -> report
                                                       |
                                                       v
                                                    followup (pause, loops)

State is saved after every step (checkpointer): in Postgres when DATABASE_URL is set,
so a case paused at the approval survives a restart and resumes without duplicate actions.
"""

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
    return {"approved": "execute", "changed": "options"}.get(state.approval.status, "report")


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
                                  {"execute": "execute", "options": "options", "report": "report"})
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
