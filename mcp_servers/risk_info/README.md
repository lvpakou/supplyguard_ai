# External risk information (MCP server) — OWNER: role 4

Wraps the trainer's `data/external_service/external_info_service.py`, which already runs in
docker compose as `risk-info` (http://localhost:8099/alerts?region=TW).
The app reads it today through `src/supplyguard_ai/integrations/risk.py`.
