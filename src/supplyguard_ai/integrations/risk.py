"""EXTERNAL RISK SERVICE client. OWNER: role 4.

The trainer's external_info_service.py runs in docker compose (service "risk-info", port 8099).
Role 4 also wraps it as an MCP server (mcp_servers/risk_info/). This client works already.
"""

import json
import os
import urllib.parse
import urllib.request


def get_alerts(region: str | None = None) -> list[dict]:
    """Risk alerts, e.g. [{"region": "TW", "severity": "high", "text": "..."}]. [] if unreachable."""
    base = os.getenv("RISK_SERVICE_URL", "http://localhost:8099")
    url = f"{base}/alerts" + (f"?{urllib.parse.urlencode({'region': region})}" if region else "")
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read())
    except OSError:
        return []
