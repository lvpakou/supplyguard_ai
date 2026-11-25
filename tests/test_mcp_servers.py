"""The MCP servers accept calls from the chat container. OWNER: role 4.

In Docker the chat calls http://procurement-mcp:8000/mcp and http://risk-mcp:8000/mcp. FastMCP's default
protection only accepts localhost, so every approved action was refused ("Invalid Host header") and the
risk alerts were silently empty. The protection stays on for any other host.
"""

import importlib.util
from pathlib import Path

import pytest
from mcp.server.transport_security import TransportSecurityMiddleware

SERVERS = Path(__file__).resolve().parents[1] / "mcp_servers"


def _load(folder: str):
    spec = importlib.util.spec_from_file_location(f"mcp_server_{folder}", SERVERS / folder / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)   # defines the tools only: no database or network at import
    return module


@pytest.mark.parametrize("folder, service", [("procurement", "procurement-mcp"), ("risk_info", "risk-mcp")])
def test_server_accepts_its_docker_name_and_localhost(folder, service):
    guard = TransportSecurityMiddleware(_load(folder).mcp.settings.transport_security)
    assert guard.settings.enable_dns_rebinding_protection
    for host in (f"{service}:8000", "localhost:8002", "127.0.0.1:8003"):
        assert guard._validate_host(host), host
    assert not guard._validate_host("evil.example.com:8000")
