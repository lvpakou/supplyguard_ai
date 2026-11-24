"""The impact step passes role 2's data warnings into the case (chat and report show them)."""

from conftest import config

from supplyguard_ai import nodes
from supplyguard_ai.graph import build_graph
from supplyguard_ai.state import CaseState, IncidentFacts


def test_a_stale_inventory_count_reaches_the_case_warnings():
    # MC-246 at W-LYO was last counted 2025-12-19: more than 180 days before the scenario.
    state = CaseState(case_id="w1", raw_text="x",
                      facts=IncidentFacts(supplier_id="S001", component_id="MC-246", delay_days=5))
    result = nodes.impact(state)
    assert result["impact"].component_id == "MC-246"
    assert any("MC-246 at W-LYO: last counted" in w for w in result["warnings"])


def test_warnings_are_not_repeated_when_the_step_runs_again():
    state = CaseState(case_id="w2", raw_text="x",
                      facts=IncidentFacts(supplier_id="S001", component_id="MC-246", delay_days=5))
    first = nodes.impact(state)
    again = nodes.impact(state.model_copy(update={"warnings": first["warnings"]}))
    assert again["warnings"] == first["warnings"]


def test_mc17_has_no_data_warnings(fake_llm):
    fake_llm(IncidentFacts(supplier_name="Atlas Components", component_id="MC-17", delay_days=12))
    result = build_graph().invoke({"case_id": "w3", "raw_text": "MC-17 late"}, config("w3"))
    assert not any("last counted" in w for w in result["warnings"])
