# Simulated procurement system (MCP server) — OWNER: role 4

This service exposes the simulated procurement system over MCP (Streamable HTTP).
It uses the shared PostgreSQL database populated from `data/structured/*.csv` by
role 2. It does not call a real ERP or supplier system.

## Tools

**Read-only:** `get_inventory`, `get_open_purchase_orders`, `get_supplier`,
`get_supplier_catalog`, `get_customer_orders`, `get_production_schedule`,
`get_shipment_updates`.

**Writes:** `create_purchase_order`, `expedite_purchase_order`,
`request_stock_transfer`, `update_production_schedule`. Every write requires an
`approval_id` matching an approved record for the exact operation and canonical
payload, plus an `idempotency_key`. A repeated key returns the first result;
reusing a key with a different payload is refused. Writes and their results are
recorded in `procurement_action_audit`.

## Approval hand-off

The MCP service creates three service-owned tables on startup:

- `procurement_approvals`: approvals registered by the trusted application after
  its human approval step;
- `procurement_idempotency`: durable idempotency results;
- `procurement_action_audit`: an audit trail of simulated writes.

Before invoking a write, the trusted application must register an approval row
for each exact action. `payload_hash` is SHA-256 of compact, key-sorted JSON for
`{"operation": operation, "payload": payload}`. For example:

```python
import hashlib, json

def procurement_payload_hash(operation: str, payload: dict) -> str:
    encoded = json.dumps(
        {"operation": operation, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

After the user approves the action, the trusted app inserts the corresponding
row with `status='approved'` into `procurement_approvals`. The server consumes
that approval on successful execution. Do not expose approval registration to
an untrusted agent/tool caller. The existing graph-level approval hash covers
all actions in a recommendation; the integration layer must explicitly bridge
that approved recommendation to per-action records before calling this server.

## Run locally

From the repository root, with PostgreSQL running and the structured CSV tables
loaded:

```powershell
$env:DATABASE_URL="postgresql://supplyguard:supplyguard@localhost:5433/supplyguard"
uv run python mcp_servers/procurement/server.py
```

The default MCP endpoint is `http://localhost:8000/mcp`.

## Docker

The `procurement-mcp` service can be enabled in the root `docker-compose.yml`:

```yaml
  procurement-mcp:
    build: ./mcp_servers/procurement
    environment:
      DATABASE_URL: postgresql://supplyguard:supplyguard@postgres:5432/supplyguard
      MCP_HOST: 0.0.0.0
      MCP_PORT: "8000"
      MCP_TRANSPORT: streamable-http
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8002:8000"
```

The service assumes role 2 has created and populated the source tables. It does
not create or alter those shared seed tables.
