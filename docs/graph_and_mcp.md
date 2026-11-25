# graph_and_mcp

OWNER: role 4. The dependency graph (Neo4j) and the two MCP servers: the simulated procurement
system and the external risk service.

## 1. The dependency graph (Neo4j)
Loaded from the trainer's `data/graph/` (CSV files + `load.cypher`) with:
```bash
docker compose up -d neo4j
uv run python scripts/load_graph.py      # runs load.cypher statement by statement, prints node counts
```
`load.cypher` uses `MERGE`, so loading again is safe. Browser: http://localhost:7475 (`neo4j` / `supplyguard-password`).

| Nodes | Count | Key properties |
|---|---:|---|
| Supplier | 60 | name, country, erpStatus, certificationExpiry |
| Upstream (manufacturer) | 8 | name, country |
| Component | 300 | description |
| Product | 80 | name |
| Factory | 3 | name |
| Customer | 25 | name, priorityTier |

| Relationship | Count | Properties |
|---|---:|---|
| `(Supplier)-[:SUPPLIES]->(Component)` | 876 | leadTimeDays, unitPriceEur |
| `(Supplier)-[:SOURCES_FROM]->(Upstream)` | 59 | — |
| `(Component)-[:USED_IN]->(Product)` | 616 | qtyPerUnit |
| `(Product)-[:PRODUCED_AT]->(Factory)` | 80 | — |
| `(Product)-[:ORDERED_BY]->(Customer)` | 900 | openOrders |

**Provenance:** every node and relationship carries `sourceId` and `effectiveDate`.

### Queries (`src/supplyguard_ai/tools/graph_queries.py`, read-only)
| Function | Answers | Used by |
|---|---|---|
| `alternatives(component, exclude_supplier)` | Approved suppliers of a component: price, lead time, certificate valid on the effective date, suppliers sharing an upstream | `dependencies` step → `supplier_checks` |
| `upstream_makers(supplier)` | A supplier's upstream manufacturers with country and link source | Deep Agent investigator |
| `shared_upstream(supplier)` | Other suppliers with the same upstream manufacturer | — |
| `affected_by(component)` | Products, factories and customers that depend on a component | — |
| `orphan_nodes()` | Suppliers that supply nothing, components no product uses (planted data-quality problems) | — |

### What the graph shows for MC-17
| Supplier | Upstream | Country | Risk alert |
|---|---|---|---|
| S001 Atlas (delayed) | U01 Veltro Semiconductor | TW | high: wafer fab maintenance |
| S002 Helios | U03 Kappa Alloys | TR | — |
| S003 Borealis | U04 Nordlicht Polymers | SE | medium: Gothenburg port strike |
| S004 Cordillera | U02 Ostrava Precision | CZ | — |
| S005 Delta | **U01 Veltro Semiconductor** | TW | high: same as Atlas |

Delta looks like a second source, but it shares Atlas's upstream, so it is **no real
diversification**. The Deep Agent writes this finding: `docs/investigator.md`.

## 2. MCP servers (Streamable HTTP, started by `docker compose up -d`)
| Server | Address | Tools |
|---|---|---|
| Procurement (`mcp_servers/procurement/`) | http://localhost:8002/mcp | **Read:** `get_inventory`, `get_open_purchase_orders`, `get_supplier`, `get_supplier_catalog`, `get_customer_orders`, `get_production_schedule`, `get_shipment_updates`<br>**Write:** `create_purchase_order`, `expedite_purchase_order`, `request_stock_transfer`, `update_production_schedule` |
| Risk (`mcp_servers/risk_info/`) | http://localhost:8003/mcp | `get_risk_alerts(region)`, `get_risk_report(region)` |

The risk MCP server wraps the external risk service `risk-info`
(http://localhost:8099/alerts?region=TW). That service is `data/external_info_service/`, which serves
the trainer's feed `data/external_service/risk_feed.json`. It has a healthcheck, and the chat and
`risk-mcp` wait until it is healthy.

### The procurement system's rules (`data/config/procurement_system_operations.json`)
- **Every write needs an `approval_id`** that matches an approved record for the **exact** operation
  and payload: a SHA-256 of the key-sorted JSON, kept in `procurement_approvals`.
- **Idempotency:** the same `idempotency_key` (case id + step) returns the first result and creates
  nothing new; reusing a key for a different action is refused (`procurement_idempotency`).
- Every write is audited (`procurement_action_audit`) and changes the operational tables in Postgres.
  Before a demo, `scripts/reset_demo.py --yes` and `scripts/load_postgres.py` restore them.

### How the app uses them
| App code | MCP mode (docker compose, the demo) | Fallback |
|---|---|---|
| `integrations/procurement.py` (`execute` step) | `PROCUREMENT_MCP_URL` set: registers each approved action, then calls the write tool | Empty (tests, evaluation): in-memory fake with the same rules |
| `integrations/risk.py` (`dependencies` step, Deep Agent) | `RISK_MCP_URL` set: tool `get_risk_alerts` | Empty: plain HTTP to `RISK_SERVICE_URL`; unreachable → no alerts |

`integrations/mcp_client.py` calls one tool synchronously, because the graph nodes are plain functions.
It works inside Chainlit's running event loop by using a worker thread.

## 3. Tests
`tests/test_graph_queries.py` and `tests/test_investigator.py`. The procurement rules (approval_id,
each action once) are exercised through the in-memory fake by `tests/test_smoke.py` and
`tests/test_restart.py`. Graph tests that would need Azure use fakes (`tests/conftest.py`).
