# Regional risk information MCP server — OWNER: role 4

This MCP server wraps the trainer-provided external HTTP service. It exposes
regional supply-chain disruption alerts to MCP clients without inventing
company-level due-diligence data.

## Available tools

- `get_risk_alerts(region?)`: returns the alerts from `GET /alerts`, optionally
  filtered by a two-letter region code (for example `TW`, `RO`, `CZ`, `SE`, `NL`).
- `get_risk_report(region)`: returns the alerts for one region plus severity counts
  and the highest severity.

The current source feed contains regional operational disruption alerts only.
It does **not** provide company-level financial risk, sanctions screening, or
adverse-media search. Do not interpret an empty result as a clean sanctions or
financial-risk check.

## Run locally (PowerShell)

Start the HTTP source service first:

```powershell
docker compose up -d risk-info
```

In a second terminal, from the repository root:

```powershell
$env:RISK_SERVICE_URL="http://localhost:8099"
$env:MCP_HOST="0.0.0.0"
$env:MCP_PORT="8003"
$env:MCP_TRANSPORT="streamable-http"
uv run python mcp_servers/risk_info/server.py
```

The MCP endpoint is `http://localhost:8003/mcp`. Keep this terminal running.

## Connect with MCP Inspector

```powershell
npx -y @modelcontextprotocol/inspector
```

Choose **Streamable HTTP**, enter `http://localhost:8003/mcp`, and connect.
Try `get_risk_alerts` with `region=TW`, then `get_risk_report` with `region=TW`.

## Docker networking

The Dockerfile defaults `RISK_SERVICE_URL` to `http://risk-info:8099`, which is
the Compose service name on the Compose network. If you add this MCP server as a
Compose service, expose container port 8000 on a free host port (for example
8003) and make it depend on `risk-info`. The existing Compose file is owned by
role 1, so this implementation does not modify it.
