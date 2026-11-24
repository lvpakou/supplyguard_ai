"""tools/options.py against the golden scenario, and the change at the approval (EV-0096). OWNER: role 2."""

import json

import pytest

from supplyguard_ai.config import data_dir, golden_scenario
from supplyguard_ai.state import CaseState, IncidentFacts
from supplyguard_ai.tools.impact import assess_impact
from supplyguard_ai.tools.options import build_options, read_change

FACTS = IncidentFacts(supplier_name="Atlas Components", supplier_id="S001", component_id="MC-17",
                      delay_days=12, spending_cap_eur=75000)


def case(change: dict | None = None) -> CaseState:
    return CaseState(case_id="test", raw_text="MC-17", facts=FACTS, impact=assess_impact(FACTS),
                     requested_change=change)


@pytest.fixture(scope="module")
def plan():
    return build_options(case())


def by_title(options, text):
    return next(o for o in options if text in o.title)


# ---------------------------------------------------------------------------
# The golden reference plans
# ---------------------------------------------------------------------------
def test_plan_1_costs_match_the_golden_breakdown(plan):
    options, rec = plan
    gold = golden_scenario()["feasible_reference_plans"]["plan_1_without_shared_upstream"]
    costs = {o.strategy: o.cost_eur for o in rec.options}
    assert costs == {"A": gold["cost_breakdown"]["transfers"],                      # 96
                     "B": gold["cost_breakdown"]["expedite_fee_6pct_contract"],     # 882
                     "C": gold["cost_breakdown"]["cordillera_purchase"]}            # 29,400
    assert rec.total_cost_eur == gold["cost_eur"] == 30378
    assert rec.uncovered_units == gold["uncovered_units"] == 850


def test_plan_2_with_delta_covers_the_rest(plan):
    options, rec = plan
    delta = by_title(options, "Delta")
    gold = golden_scenario()["feasible_reference_plans"]["plan_2_with_delta"]
    assert rec.total_cost_eur + delta.cost_eur == gold["cost_eur"] == 39218
    assert delta.covered_units == 850
    assert "shares upstream U01" in delta.title                # weak diversification is said
    assert delta not in rec.options                            # offered, not recommended


def test_rejected_suppliers_and_why(plan):
    options, _ = plan
    helios, borealis = by_title(options, "Helios"), by_title(options, "Borealis")
    assert not helios.feasible and "Too slow" in helios.rejected_because
    assert not borealis.feasible and "expired 2026-09-30" in borealis.rejected_because


def test_hub_stock_goes_to_the_plants_that_run_out_first(plan):
    _, rec = plan
    transfers = {a.payload["to_location"]: a.payload["qty"] for a in rec.options[0].actions}
    assert set(transfers) == {"W-KAT", "W-LYO"}                # Stuttgart (8.7 days) needs none
    assert sum(transfers.values()) == 800
    assert transfers["W-LYO"] > transfers["W-KAT"]             # Lyon runs out first


def test_at_least_three_strategies_are_compared(plan):
    options, _ = plan
    assert {o.strategy for o in options} >= {"A", "B", "C", "D", "E"}


def test_every_payload_matches_the_procurement_contract(plan):
    contract = json.loads((data_dir() / "config" / "procurement_system_operations.json").read_text())
    _, rec = plan
    for option in rec.options:
        for action in option.actions:
            assert set(action.payload) == set(contract["write_operations"][action.operation]["payload"])


# ---------------------------------------------------------------------------
# A change at the approval (EV-0096: "change quantity to 6,000")
# ---------------------------------------------------------------------------
def test_change_quantity_builds_a_new_plan_and_flags_the_capacity():
    _, rec = build_options(case({"qty": 6000}))
    purchase = by_title(rec.options, "Cordillera")
    assert purchase.actions[0].payload["qty"] == 6000          # new payload -> new hash -> new approval
    assert purchase.covered_units == 3000                       # only the monthly capacity counts
    assert not purchase.feasible and "exceed the monthly capacity" in purchase.rejected_because
    assert rec.total_cost_eur == pytest.approx(96 + 882 + 6000 * 9.80)
    assert "Changed at the approval" in rec.summary


def test_quantity_typed_in_the_note_is_understood():
    assert read_change({"note": "Change the quantity to 6,000"})["qty"] == 6000
    assert "qty" not in read_change({"note": "use a cheaper supplier"})


def test_change_supplier_to_borealis_is_built_but_not_allowed():
    _, rec = build_options(case({"supplier_id": "S003"}))
    purchase = by_title(rec.options, "Borealis")
    assert not purchase.feasible and "certification" in purchase.rejected_because


def test_lower_cap_is_reported():
    _, rec = build_options(case({"spending_cap_eur": 20000}))
    assert "exceeds the cap of EUR 20,000" in rec.summary
