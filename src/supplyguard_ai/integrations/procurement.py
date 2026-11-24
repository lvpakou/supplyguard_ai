"""SIMULATED PROCUREMENT SYSTEM client: the graph's execute step calls execute(). OWNER: role 4.

Two modes:
  - PROCUREMENT_MCP_URL set (docker compose, the demo): every write goes to the MCP server in
    mcp_servers/procurement/ (Christos), which changes the operational tables in Postgres.
  - not set (fast tests, the evaluation): an in-memory fake with the same rules.

Rules in both modes (data/config/procurement_system_operations.json):
  - every write needs an approval_id;
  - the same idempotency_key returns the first result and creates nothing new;
  - reusing a key for a different action is refused.

The approval hand-off (mcp_servers/procurement/README.md): the server only executes an action
that has an 'approved' row in procurement_approvals for its exact operation and payload hash.
This client is the trusted application side: the human approved the whole plan in the graph,
so before each write it registers that one action under the plan's approval_id.
"""

import hashlib
import json
import os

import psycopg

from supplyguard_ai.config import database_url
from supplyguard_ai.state import Action, ExecutionResult

# In-memory fake (and a record of what this process executed, used by the evaluation).
_DONE: dict[str, tuple[Action, ExecutionResult]] = {}

# The MCP tools' argument types: the server hashes the payload after type conversion,
# so we convert the same way before hashing (6 and 6.0 must give the same hash).
_INT_FIELDS = {"qty", "days_gain", "planned_units"}
_FLOAT_FIELDS = {"unit_price_eur", "fee_pct"}


def _typed(payload: dict) -> dict:
    return {key: int(value) if key in _INT_FIELDS else float(value) if key in _FLOAT_FIELDS else value
            for key, value in payload.items()}


def payload_hash(operation: str, payload: dict) -> str:
    """The server's canonical hash: SHA-256 of compact, key-sorted {operation, payload} JSON."""
    raw = json.dumps({"operation": operation, "payload": _typed(payload)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _refused(action: Action, key: str, message: str) -> ExecutionResult:
    return ExecutionResult(operation=action.operation, idempotency_key=key, status="refused", message=message)


def execute(action: Action, approval_id: str | None, idempotency_key: str) -> ExecutionResult:
    if not idempotency_key:
        return _refused(action, idempotency_key, "idempotency_key is required")
    if idempotency_key in _DONE:
        previous_action, first = _DONE[idempotency_key]
        if previous_action != action:
            return _refused(action, idempotency_key, "idempotency key was already used for a different action")
        return first.model_copy(update={"status": "already_done"})
    if not approval_id:
        return _refused(action, idempotency_key, "write operations require an approval_id")

    url = os.getenv("PROCUREMENT_MCP_URL")
    result = _execute_mcp(url, action, approval_id, idempotency_key) if url else ExecutionResult(
        operation=action.operation, idempotency_key=idempotency_key, status="done",
        reference=f"SIM-{len(_DONE) + 1:04d}", message="in-memory simulation")
    if result.status in ("done", "already_done"):
        _DONE[idempotency_key] = (action, result)
    return result


def _register_approval(approval_id: str, action: Action) -> None:
    """Trusted side of the hand-off: this exact action is covered by the human approval."""
    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO procurement_approvals (approval_id, operation, payload_hash, status) "
            "VALUES (%s, %s, %s, 'approved') ON CONFLICT DO NOTHING",
            (approval_id, action.operation, payload_hash(action.operation, action.payload)),
        )


def _execute_mcp(url: str, action: Action, approval_id: str, idempotency_key: str) -> ExecutionResult:
    from supplyguard_ai.integrations.mcp_client import call_tool

    try:
        _register_approval(approval_id, action)
        answer = call_tool(url, action.operation, {**_typed(action.payload), "approval_id": approval_id,
                                                   "idempotency_key": idempotency_key})
    except Exception as error:  # server down, database down, ...: refuse, never pretend it ran
        return _refused(action, idempotency_key, f"procurement system unavailable: {error}")
    return ExecutionResult(
        operation=action.operation, idempotency_key=idempotency_key,
        status=answer.get("status", "refused") if answer.get("status") in ("done", "already_done", "refused") else "refused",
        reference=answer.get("reference"), message=answer.get("message", ""),
    )
