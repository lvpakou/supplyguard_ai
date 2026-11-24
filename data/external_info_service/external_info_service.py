
#!/usr/bin/env python3

"""
Independent external information service.

Endpoints:
    GET /health
    GET /alerts
    GET /alerts?region=TW

Run:
    python external_info_service.py
"""

import json
import os
import logging

from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


BASE_DIR = Path(__file__).resolve().parent
FEED_PATH = BASE_DIR / "risk_feed.json"

PORT = int(os.environ.get("PORT", 8099))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_feed():
    """Load risk information from the JSON feed."""

    with open(FEED_PATH, "r", encoding="utf-8") as file:
        feed = json.load(file)

    if not isinstance(feed.get("alerts"), list):
        raise ValueError("Invalid risk feed: alerts must be a list")

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
        path = parsed.path

        # Health check
        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return

        # Alerts endpoint
        if path != "/alerts":
            self.send_json(404, {"error": "Endpoint not found"})
            return

        params = parse_qs(parsed.query)
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

        self.send_json(
            200,
            {
                "generated": FEED.get("generated"),
                "count": len(alerts),
                "alerts": alerts
            }
        )

    def log_message(self, format, *args):
        logger.info(
            "%s - %s",
            self.client_address[0],
            format % args
        )


def main():

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        ExternalInfoHandler
    )

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