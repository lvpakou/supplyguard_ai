# Simulated procurement system (MCP server) — OWNER: role 4

Implements `data/config/procurement_system_operations.json`:
- read operations: free;
- write operations (`create_purchase_order`, `expedite_purchase_order`, `request_stock_transfer`,
  `update_production_schedule`): require an `approval_id` bound to the exact payload;
- idempotency: the same `idempotency_key` (case_id + step) returns the first result, creates nothing new.

The app calls it through `src/supplyguard_ai/integrations/procurement.py` (today an in-memory stub
with the same rules). When the server exists, add it to docker-compose.yml (role 1).
