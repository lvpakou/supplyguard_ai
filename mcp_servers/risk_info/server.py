"""MCP wrapper for SupplyGuard's external regional risk-alert service.

The underlying trainer-provided HTTP service exposes GET /alerts?region=XX.
It currently contains regional operational disruption alerts, not company-level
credit checks, sanctions screening, or adverse-media search.

Run from the repository root:
    RISK_SERVICE_URL=http://localhost:8099 uv run python mcp_servers/risk_info/server.py
"""

from __future__ import annotations

import json
import os
from collections import Counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# DNS-rebinding protection stays on, but also accepts the Docker service name (the chat container
# calls http://risk-mcp:8000/mcp). FastMCP's default allows only localhost, and setting
# mcp.settings.host later does not change that, so the chat silently got no risk alerts.
ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*", "risk-mcp:*"]
mcp = FastMCP("supplyguard-risk-info", transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True, allowed_hosts=ALLOWED_HOSTS,
    allowed_origins=[f"http://{host}" for host in ALLOWED_HOSTS]))
RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://localhost:8099").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("RISK_SERVICE_TIMEOUT_SECONDS", "5"))


def _fetch_alerts(region: str | None = None) -> list[dict[str, Any]]:
    """Fetch alerts from the trainer-provided HTTP service."""
    query = f"?{urlencode({'region': region})}" if region else ""
    url = f"{RISK_SERVICE_URL}/alerts{query}"

    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Risk service returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            f"Risk service is unavailable at {RISK_SERVICE_URL}: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Risk service returned invalid JSON") from exc

    if not isinstance(payload, list):
        raise RuntimeError("Risk service response must be a JSON list")

    # Validate the minimum contract before exposing external data to the agent.
    alerts: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not all(key in item for key in ("region", "severity", "text")):
            continue
        alerts.append(item)
    return alerts


@mcp.tool()
def get_risk_alerts(region: str | None = None) -> list[dict[str, Any]]:
    """Get regional supply-chain disruption alerts.

    Args:
        region: Optional two-letter region/country code, e.g. TW, RO, CZ, SE, NL.

    Each alert contains region, topic, severity and text. This is regional
    operational intelligence; it is not a company-level due-diligence check.
    """
    normalized_region = region.strip().upper() if region and region.strip() else None
    return _fetch_alerts(normalized_region)


@mcp.tool()
def get_risk_report(region: str) -> dict[str, Any]:
    """Summarize regional disruption alerts by severity for one region."""
    normalized_region = region.strip().upper()
    if not normalized_region:
        raise ValueError("region must be a non-empty region code")

    alerts = _fetch_alerts(normalized_region)
    counts = Counter(str(alert.get("severity", "unknown")).lower() for alert in alerts)
    highest = next(
        (level for level in ("critical", "high", "medium", "low") if counts[level]),
        "none",
    )
    return {
        "region": normalized_region,
        "alert_count": len(alerts),
        "highest_severity": highest,
        "severity_counts": dict(counts),
        "alerts": alerts,
        "source": "trainer-provided regional risk feed",
        "limitations": [
            "The feed reports regional operational disruptions only.",
            "It does not provide company-level financial risk, sanctions screening, or adverse-media results.",
        ],
    }


if __name__ == "__main__":
    mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.getenv("MCP_PORT", "8003"))
    mcp.run(transport=os.getenv("MCP_TRANSPORT", "streamable-http"))
