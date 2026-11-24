"""scripts/load_postgres.py: every CSV becomes a table, and our data-quality checks
find the trainer's planted problems. OWNER: role 2. Needs Postgres (docker compose up -d)."""

import importlib.util
import os
from pathlib import Path

import psycopg
import pytest

from supplyguard_ai.config import data_dir, policies

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_postgres.py"


def _load_script():
    """Import scripts/load_postgres.py as a module (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("load_postgres", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def loaded():
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("needs Postgres: docker compose up -d postgres")
    try:
        conn = psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("needs Postgres: docker compose up -d postgres")
    script = _load_script()
    with conn:
        for path in sorted((data_dir() / "structured").glob("*.csv")):
            script.load_csv(conn, path)
        conn.commit()
        yield conn, script


@pytest.mark.parametrize("table, rows", [
    ("inventory", 1000), ("purchase_orders", 2000), ("customer_orders", 1500),
    ("bill_of_materials", 616), ("suppliers", 60), ("reservations", 6), ("quarantine_lots", 1),
])
def test_every_row_is_loaded(loaded, table, rows):
    conn, _ = loaded
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == rows


def test_dates_and_numbers_get_real_types(loaded):
    conn, _ = loaded
    types = dict(conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'purchase_orders'"
    ).fetchall())
    assert types["order_date"] == "date"
    assert types["qty"] == "bigint"
    assert types["unit_price_eur"] == "double precision"


def test_our_checks_find_at_least_every_planted_problem(loaded):
    conn, script = loaded
    day = policies()["scenario_date"]
    for label, (query, issue, file) in script.OWN_CHECKS.items():
        found = conn.execute(query, {"day": day}).fetchone()[0]
        expected = conn.execute(
            "SELECT count(*) FROM data_quality_manifest WHERE issue_type = %s AND file = %s", (issue, file)
        ).fetchone()[0]
        assert found >= expected, label
