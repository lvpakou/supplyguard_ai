"""tools/inventory.py: usable stock for MC-17 must match the trainer's golden scenario. OWNER: role 2.

Runs without Docker (reads the CSVs). With Postgres running and loaded, the same tests
also run against the database (DATABASE_URL in .env).
"""

import pandas as pd
import pytest

from supplyguard_ai.config import golden_scenario
from supplyguard_ai.tools import tables
from supplyguard_ai.tools.inventory import usable_stock


@pytest.fixture(params=["csv", "postgres"])
def source(request, monkeypatch):
    """Run every test twice: once reading the CSVs, once reading Postgres (if it is there)."""
    if request.param == "csv":
        monkeypatch.delenv("DATABASE_URL", raising=False)
    elif tables._from_postgres("inventory") is None:
        pytest.skip("needs Postgres loaded: docker compose up -d, then scripts/load_postgres.py")
    return request.param


def test_mc17_totals_match_the_golden_scenario(source):
    gold = golden_scenario()["mc17_inventory"]
    stock = usable_stock("MC-17")
    assert stock["on_hand"] == gold["on_hand"] == 5200
    assert stock["reserved"] == gold["reserved"] == 1400
    assert stock["quarantined"] == gold["quarantined"] == 600
    assert stock["usable"] == gold["usable"] == 3200


def test_mc17_usable_per_location(source):
    assert usable_stock("MC-17")["by_location"] == golden_scenario()["usable_by_location"]


def test_mc17_explains_reserved_and_quarantined_stock(source):
    stock = usable_stock("MC-17")
    assert len(stock["reserved_for"]) == 6                    # six tier-1 customer orders
    assert sum(r["qty"] for r in stock["reserved_for"]) == 1400
    assert [lot["lot_id"] for lot in stock["quarantine_lots"]] == ["LOT-KAT-0932"]
    assert stock["warnings"] == []                            # detail tables agree, counts are recent


def test_component_id_is_normalised(source):
    assert usable_stock(" mc-17 ")["usable"] == 3200


def test_unknown_component_gives_zero_and_a_warning(source):
    stock = usable_stock("MC-99999")
    assert stock["usable"] == 0 and stock["by_location"] == {}
    assert stock["warnings"] == ["No inventory records for MC-99999."]


def test_stale_counts_are_flagged(source):
    # MC-282 at W-KAT is in the trainer's manifest: counted more than 180 days ago.
    assert any("W-KAT" in w and "180 days" in w for w in usable_stock("MC-282")["warnings"])


def test_usable_formula_holds_for_every_component(monkeypatch):
    """Our formula reproduces the inventory's own 'usable' column for all 300 components.
    CSV only: 300 calls against Postgres take ~15 s and test nothing more."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    expected = tables.table("inventory").groupby("component_id")["usable"].sum()
    for component, units in expected.items():
        assert usable_stock(component)["usable"] == units, component
