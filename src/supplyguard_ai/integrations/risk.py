"""EXTERNAL RISK SERVICE client. OWNER: role 4.

The trainer's external_info_service.py runs in docker compose (service "risk-info", port 8099),
and Christos's MCP server (mcp_servers/risk_info/) wraps it.
  - RISK_MCP_URL set (docker compose, the demo): ask the MCP server (tool get_risk_alerts).
  - otherwise: ask the HTTP service directly (RISK_SERVICE_URL).
Either way an unreachable service gives [] (the investigation goes on without alerts).
"""

import json
import os
import urllib.parse
import urllib.request


def get_alerts(region: str | None = None) -> list[dict]:
    """Risk alerts, e.g. [{"region": "TW", "severity": "high", "text": "..."}]. [] if unreachable."""
    mcp_url = os.getenv("RISK_MCP_URL")
    if mcp_url:
        from supplyguard_ai.integrations.mcp_client import call_tool

        try:
            alerts = call_tool(mcp_url, "get_risk_alerts", {"region": region} if region else {})
            return alerts if isinstance(alerts, list) else []
        except Exception:
            return []
    base = os.getenv("RISK_SERVICE_URL", "http://localhost:8099")
    url = f"{base}/alerts" + (f"?{urllib.parse.urlencode({'region': region})}" if region else "")
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read())
    except OSError:
        return []
