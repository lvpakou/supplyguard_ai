"""CHAINLIT CHAT. OWNER: role 5 (this is a minimal first version from role 1).

    uv run chainlit run src/supplyguard_ai/chat_app.py

Role 5 adds: login with users.csv roles, evidence display, options table,
Approve / Reject / Change, follow-up buttons (see HelpDesk Lite's chat_app.py).
"""

import uuid

import chainlit as cl
from langgraph.types import Command

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


@cl.on_message
async def on_message(message: cl.Message) -> None:
    thread_id = cl.user_session.get("thread_id")
    if thread_id is None or message.content.strip().lower() == "new":
        thread_id = str(uuid.uuid4())
        cl.user_session.set("thread_id", thread_id)
        if message.content.strip().lower() == "new":
            await cl.Message("OK, describe the next disruption.").send()
            return
        graph_input = {"case_id": thread_id, "raw_text": message.content}
    else:
        graph_input = Command(resume=message.content)
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
