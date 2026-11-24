"""The intake writes supplier and component IDs exactly as the data does."""

import pytest
from conftest import MC17_MESSAGE, config

from supplyguard_ai.graph import build_graph, pending
from supplyguard_ai.nodes import resolve_component, resolve_supplier
from supplyguard_ai.state import IncidentFacts


@pytest.mark.parametrize("written", ["MC-17", "mc-17", "mc17", "Mc 17", "MC-017"])
def test_component_is_written_like_the_data(written):
    assert resolve_component(IncidentFacts(component_id=written)).component_id == "MC-17"


def test_unknown_component_is_not_used_and_the_user_is_asked():
    facts = resolve_component(IncidentFacts(component_id="MC-999"))
    assert facts.component_id is None
    assert any("MC-999" in a for a in facts.ambiguities)


def test_lowercase_component_still_gets_the_impact(fake_llm):
    # The bug seen in the chat: "mc-17" -> impact stub found nothing.
    fake_llm(IncidentFacts(supplier_name="Atlas Components", component_id="mc-17", delay_days=12))
    result = build_graph().invoke({"case_id": "c-low", "raw_text": MC17_MESSAGE}, config("c-low"))
    assert result["impact"].usable == 3200
    assert pending(result)["type"] == "approval"


def test_atlas_is_asked_once_even_if_the_llm_also_flags_it():
    facts = IncidentFacts(supplier_name="Atlas", ambiguities=["'Atlas' could be Atlas Components or Atlas Logistik"])
    resolved = resolve_supplier(facts)
    assert len([a for a in resolved.ambiguities if "Atlas" in a]) == 1
    assert "S006" in resolved.ambiguities[0]
