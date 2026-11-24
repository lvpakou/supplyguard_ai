"""The skeleton works end to end with the stubs (and keeps working as roles fill them in)."""

from conftest import MC17_FACTS, MC17_MESSAGE, config
from langgraph.types import Command

from supplyguard_ai.graph import build_graph, pending
from supplyguard_ai.state import IncidentFacts


def start(fake_llm, *answers, thread="case-test"):
    fake_llm(*answers)
    app = build_graph()
    return app, app.invoke({"case_id": thread, "raw_text": MC17_MESSAGE}, config(thread))


def test_mc17_reaches_the_approval_with_the_golden_numbers(fake_llm):
    _, result = start(fake_llm, MC17_FACTS)

    assert result["facts"].supplier_id == "S001"          # resolved from suppliers.csv
    assert result["impact"].usable == 3200
    assert result["impact"].shortfall_units == 5350
    assert result["recommendation"].total_cost_eur == 30378
    payload = pending(result)
    assert payload["type"] == "approval"                  # nothing executed before approval
    assert payload["request"]["approver_role"] == "procurement_manager + finance_controller"
    assert result.get("executions", []) == []


def test_approve_executes_each_action_once_then_reports(fake_llm):
    app, _ = start(fake_llm, MC17_FACTS, thread="case-approve")

    result = app.invoke(Command(resume="approve"), config("case-approve"))

    assert result["approval"].status == "approved"
    assert [e.status for e in result["executions"]] == ["done"] * 4  # 2 transfers, expedite, PO
    assert "Incident report" in result["report"]
    assert pending(result)["type"] == "followup"


def test_reject_executes_nothing(fake_llm):
    app, _ = start(fake_llm, MC17_FACTS, thread="case-reject")

    result = app.invoke(Command(resume="reject"), config("case-reject"))

    assert result["approval"].status == "rejected"
    assert result.get("executions", []) == []


def test_ambiguous_atlas_asks_instead_of_guessing(fake_llm):
    vague = IncidentFacts(supplier_name="Atlas", component_id="MC-17", delay_days=12)
    _, result = start(fake_llm, vague, thread="case-atlas")

    payload = pending(result)
    assert payload["type"] == "clarification"
    assert "Atlas Components (S001)" in payload["question"]
    assert "Atlas Logistik GmbH (S006)" in payload["question"]


def test_same_payload_gives_the_same_approval_hash(fake_llm):
    # Restart safety: rebuilding the request for the same plan gives the same hash.
    _, first = start(fake_llm, MC17_FACTS, thread="case-h1")
    _, second = start(fake_llm, MC17_FACTS, thread="case-h1b")
    assert pending(first)["request"]["payload_hash"] == pending(second)["request"]["payload_hash"]
