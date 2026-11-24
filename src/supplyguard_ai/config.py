"""Settings from .env and the trainer's config files (data/config/).

Functions instead of module-level constants: importing the package never fails,
so the tests run on a laptop without a .env.
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """The trainer's data package (data/ in the repo unless DATA_DIR says otherwise)."""
    path = Path(os.getenv("DATA_DIR", "data"))
    return path if path.is_absolute() else REPO_ROOT / path


@lru_cache
def policies() -> dict:
    """data/config/policies.json: spending cap, approval tiers, source precedence, ..."""
    return json.loads((data_dir() / "config" / "policies.json").read_text())


@lru_cache
def golden_scenario() -> dict:
    """data/evaluation/golden_scenario.json: the expected answer for the MC-17 case.
    The stubs return these numbers until each role builds the real calculation."""
    return json.loads((data_dir() / "evaluation" / "golden_scenario.json").read_text())


def database_url() -> str | None:
    """Postgres address, or None (then the graph keeps its state in memory)."""
    return os.getenv("DATABASE_URL") or None


def require(*names: str) -> dict[str, str]:
    """Read required settings, failing with a clear message if any is missing."""
    missing = [name for name in names if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing settings: {', '.join(missing)}. Copy .env.example to .env.")
    return {name: os.environ[name] for name in names}
