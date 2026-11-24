"""SIMULATED PROCUREMENT SYSTEM client (the graph calls this to execute). OWNER: role 4.

Real version: talk to the MCP server in mcp_servers/procurement/ (langchain-mcp-adapters),
which implements data/config/procurement_system_operations.json on top of Postgres.

STUB: an in-memory fake with the same rules, so the flow can be tested today:
  - every write needs an approval_id;
  - the same idempotency_key returns the first result and creates nothing new.
"""

from supplyguard_ai.state import Action, ExecutionResult

_DONE: dict[str, ExecutionResult] = {}   # idempotency_key -> first result (stub storage)


def execute(action: Action, approval_id: str | None, idempotency_key: str) -> ExecutionResult:
    if idempotency_key in _DONE:
        first = _DONE[idempotency_key]
        return first.model_copy(update={"status": "already_done"})
    if not approval_id:
        return ExecutionResult(operation=action.operation, idempotency_key=idempotency_key,
                               status="refused", message="write operations require an approval_id")
    result = ExecutionResult(operation=action.operation, idempotency_key=idempotency_key, status="done",
                             reference=f"SIM-{len(_DONE) + 1:04d}", message="STUB: simulated")
    _DONE[idempotency_key] = result
    return result
