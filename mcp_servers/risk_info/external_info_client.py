import json
import os

from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import URLError


EXTERNAL_INFO_URL = os.getenv(
    "EXTERNAL_INFO_URL",
    "http://external-info:8099"
)


def get_external_alerts(region: str | None = None):

    query = ""

    if region:
        query = "?" + urlencode({"region": region})

    url = f"{EXTERNAL_INFO_URL}/alerts{query}"

    try:
        with urlopen(url, timeout=5) as response:
            return json.loads(
                response.read().decode("utf-8")
            )

    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Failed to retrieve external alerts: {exc}"
        ) from exc
