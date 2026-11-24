"""tools/impact.py against the trainer's answers. OWNER: role 2.

1. MC-17: every number of the golden scenario.
2. The 64 'extraction_and_impact' evaluation cases: affected products and orders at risk
   for 64 different components (the facts are given, so this tests only OUR calculation,
   not the LLM's extraction).
"""

import json

import pytest

from supplyguard_ai.config import data_dir, golden_scenario
from supplyguard_ai.state import IncidentFacts
from supplyguard_ai.tools.impact import assess_impact, delayed_delivery

MC17 = IncidentFacts(supplier_name="Atlas Components", supplier_id="S001",
                     component_id="MC-17", delay_days=12)


@pytest.fixture(scope="module")
def mc17():
    return assess_impact(MC17)


def test_mc17_products_and_orders(mc17):
    gold = golden_scenario()
    assert mc17.affected_products == sorted(gold["affected_products"])     # 6 products
    assert mc17.open_orders_at_risk == gold["open_orders_due_within_60d_on_affected_products"]  # 77


def test_mc17_demand_and_days_of_cover(mc17):
    gold = golden_scenario()
    assert mc17.daily_demand == gold["daily_mc17_demand"] == 450
    assert mc17.days_of_cover == {"F1 (W-STU)": 8.7, "F2 (W-KAT)": 4.0, "F3 (W-LYO)": 3.3}
    # Lyon and Katowice run out first
    assert sorted(mc17.days_of_cover, key=mc17.days_of_cover.get)[:2] == ["F3 (W-LYO)", "F2 (W-KAT)"]


def test_mc17_delayed_po_and_shortfall(mc17):
    gold = golden_scenario()
    delivery = delayed_delivery("S001", "MC-17", 12)
    assert delivery["po_id"] == gold["facts"]["affected_po"] == "PO-2026-9001"
    assert (delivery["original_day"], delivery["delayed_day"]) == (7, 19)
    assert mc17.first_stockout_day == gold["first_stockout_day_without_action"] == 7
    assert mc17.shortfall_units == gold["expected_shortfall_units"] == 5350


def test_mc17_revenue_at_risk_is_reported_and_sourced(mc17):
    assert mc17.revenue_at_risk_eur > 0
    assert "PO-2026-9001" in mc17.source_ids


def _eval_cases():
    path = data_dir() / "evaluation" / "eval_cases.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return [r for r in rows if r["category"] == "extraction_and_impact"]


@pytest.mark.parametrize("case", _eval_cases(), ids=lambda c: c["id"])
def test_evaluation_case_impact(case):
    expected = case["expected"]
    facts = IncidentFacts(supplier_id=expected["supplier_id"], component_id=expected["component_id"],
                          delay_days=expected["delay_days"])
    impact = assess_impact(facts)
    assert impact.affected_products == sorted(expected["affected_products"])
    assert impact.open_orders_at_risk == expected["open_orders_due_within_60d"]
