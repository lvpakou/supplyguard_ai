#!/usr/bin/env python3
"""
Independent external information service.

Endpoints:
    GET /health
    GET /alerts               -> JSON list of all risk alerts
    GET /alerts?region=TW     -> JSON list of the alerts for one region

The response is a plain JSON list, like the trainer's original service
(data/external_service/), because the app (integrations/risk.py) and the risk
MCP server (mcp_servers/risk_info/server.py) read a list.

The feed is the trainer's data/external_service/risk_feed.json (not a copy).
RISK_FEED_PATH points elsewhere, e.g. the file mounted into the container.

Run:
    python external_info_service.py 8099
"""

import json
import logging
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
FEED_PATH = Path(os.environ.get("RISK_FEED_PATH") or BASE_DIR.parent / "external_service" / "risk_feed.json")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_feed():
    """Load risk information from the JSON feed."""

    with open(FEED_PATH, "r", encoding="utf-8") as file:
        feed = json.load(file)

    if not isinstance(feed, dict) or not isinstance(feed.get("alerts"), list):
        raise ValueError("Invalid risk feed: alerts must be a list")
    # The app and the MCP server read region, severity and text of every alert.
    if not all(isinstance(alert, dict) and all(isinstance(alert.get(key), str) for key in ("region", "severity", "text"))
               for alert in feed["alerts"]):
        raise ValueError("Invalid risk feed: every alert needs region, severity and text")

    logger.info(
        "Loaded %d alerts (generated: %s)",
        len(feed["alerts"]),
        feed.get("generated")
    )

    return feed


FEED = load_feed()


class ExternalInfoHandler(BaseHTTPRequestHandler):

    def send_json(self, status, data):
        response = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()

        self.wfile.write(response)

    def do_GET(self):

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"   # "/alerts/" works like "/alerts"

        # Health check
        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        # Alerts endpoint
        if path != "/alerts":
            self.send_json(404, {"error": "Endpoint not found"})
            return

        # keep_blank_values: "?region=" must be rejected, not read as "no filter"
        params = parse_qs(parsed.query, keep_blank_values=True)
        regions = params.get("region", [])

        if len(regions) > 1:
            self.send_json(
                400,
                {"error": "Provide region only once"}
            )
            return

        region = regions[0].strip().upper() if regions else None

        if region == "":
            self.send_json(
                400,
                {"error": "Region cannot be empty"}
            )
            return

        alerts = FEED["alerts"]

        # Optional region filtering
        if region:
            alerts = [
                alert for alert in alerts
                if alert["region"].upper() == region
            ]

        self.send_json(200, alerts)

    def log_message(self, format, *args):
        logger.info(
            "%s - %s",
            self.client_address[0],
            format % args
        )


def stop(signum, frame):
    """docker stop sends SIGTERM: shut down cleanly instead of waiting to be killed."""
    raise KeyboardInterrupt


def main():

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        ExternalInfoHandler
    )
    signal.signal(signal.SIGTERM, stop)

    logger.info(
        "External information service running on port %s",
        PORT
    )

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        logger.info("Shutting down service")

    finally:
        server.server_close()


if __name__ == "__main__":
    main()
