"""tools/critic.py: the challenge step finds policy violations, infeasible actions, risks and
weak assumptions, with numbers. OWNER: role 2."""

import pytest

from supplyguard_ai.state import CaseState, Conflict, IncidentFacts, SupplierCheck
from supplyguard_ai.tools.critic import review
from supplyguard_ai.tools.impact import assess_impact
from supplyguard_ai.tools.options import build_options

FACTS = IncidentFacts(supplier_name="Atlas Components", supplier_id="S001", component_id="MC-17",
                      delay_days=12, spending_cap_eur=75000)

# The four MC-17 conflicts, in the format role 3's find_conflicts() returns.
CONFLICTS = [
    Conflict(topic="Atlas Components (S001) delay MC-17",
             values={"DOC-NOT-ATLAS-MC17": "12 days", "DOC-EM-ATLAS-01": "16 days"}, chosen="12 days",
             reason="supplier notice outranks supplier e-mail"),
    Conflict(topic="Cordillera Industrial (S004) expedite fee",
             values={"DOC-CON-S004-v1": "6%", "DOC-EM-CORDILLERA-01": "10%"}, chosen="6%",
             reason="contract (latest version) outranks supplier e-mail"),
    Conflict(topic="Helios Supply (S002) monthly capacity",
             values={"DOC-CON-S002-v1": "4,000/month", "DOC-EM-HELIOS-01": "1,500/month"},
             chosen="1,500/month for planning", reason="the supplier states it in writing"),
    Conflict(topic="Atlas Components (S001) contract version",
             values={"DOC-CON-S001-v2": "v2", "DOC-CON-S001-v3": "v3"}, chosen="DOC-CON-S001-v3",
             reason="v2 is superseded"),
]


def reviewed(change: dict | None = None, **extra) -> list[str]:
    state = CaseState(case_id="test", raw_text="MC-17", facts=FACTS, impact=assess_impact(FACTS),
                      conflicts=CONFLICTS, requested_change=change, **extra)
    options, recommendation = build_options(state)
    state = state.model_copy(update={"options": options, "recommendation": recommendation})
    return review(state)


@pytest.fixture(scope="module")
def mc17():
    return reviewed()


def has(findings: list[str], *words: str) -> bool:
    return any(all(word in f for word in words) for f in findings)


def test_two_approvers_are_needed_for_30k(mc17):
    assert has(mc17, "30,378", "BOTH", "procurement_manager", "finance_controller")


def test_longer_atlas_delay_is_challenged_with_its_effect(mc17):
    # e-mail says 16 days, notice 12: 4 more days x 450/day
    assert has(mc17, "delay MC-17", "16 days", "1,800 more units")


def test_expedite_fee_conflict_shows_the_other_cost(mc17):
    # golden cost_sensitivity: EUR 1,470 if the e-mail's 10% were right
    assert has(mc17, "expedite fee", "10%", "EUR 1,470", "EUR 882")


def test_conflicts_of_suppliers_not_in_the_plan_or_settled_are_left_out(mc17):
    assert not has(mc17, "Helios")            # Helios is not in the plan
    assert not has(mc17, "contract version")  # the superseded v2 is simply not used


def test_uncovered_units_are_reported(mc17):
    assert has(mc17, "850 units stay uncovered")


def test_plan_1_has_no_policy_or_feasibility_objection(mc17):
    for word in ("exceed", "certification", "below the minimum", "not before", "same upstream"):
        assert not has(mc17, word), word


def test_quantity_above_capacity_is_reported_and_left_out():
    findings = reviewed({"qty": 6000})
    assert has(findings, "S004", "6,000 units exceed the monthly capacity of 3,000")
    assert has(findings, "Left out of the plan", "Buy 6,000 from Cordillera")


def test_uncertified_supplier_is_reported_and_left_out():
    findings = reviewed({"supplier_id": "S003"})
    assert has(findings, "S003", "certification expired")
    assert has(findings, "Left out of the plan", "Borealis")


def test_lower_cap():
    assert has(reviewed({"spending_cap_eur": 20000}), "exceeds the cap of EUR 20,000")


def test_shared_upstream_and_risk_alerts_from_role_4():
    checks = [SupplierCheck(supplier_id="S005", name="Delta", risk_alerts=["TW wafer supply (high)"])]
    findings = reviewed({"supplier_id": "S005"}, supplier_checks=checks)
    assert has(findings, "S005", "same upstream manufacturer (U01)")
    assert has(findings, "S005", "TW wafer supply")


def test_no_recommendation():
    assert review(CaseState(case_id="x", raw_text="x")) == ["No recommendation to review."]
