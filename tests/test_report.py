"""report.py: the incident report after a real MC-17 run (approve and reject). OWNER: role 2."""

import uuid

import pytest
from conftest import MC17_FACTS, MC17_MESSAGE, config
from langgraph.types import Command

from supplyguard_ai.graph import build_graph
from supplyguard_ai.report import short_id


def closed_case(fake_llm, decision: str, thread: str) -> str:
    fake_llm(MC17_FACTS)
    app = build_graph()
    # A new case id each time: the simulated procurement system remembers idempotency keys,
    # so re-running the same case would (correctly) report "already_done".
    case_id = f"3f2a9c1e-{uuid.uuid4()}"
    app.invoke({"case_id": case_id, "raw_text": MC17_MESSAGE}, config(thread))
    return app.invoke(Command(resume=decision), config(thread))["report"]


@pytest.fixture
def approved(fake_llm):
    return closed_case(fake_llm, "approve", "report-approve")


def test_short_case_id():
    assert short_id("3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90") == "INC-3F2A9C1E"
    assert short_id("EV-0001-ab12") == "EV-0001-ab12"


def test_report_has_every_section(approved):
    for heading in ("# Incident report INC-3F2A9C1E", "## Incident", "## Impact", "## Options compared",
                    "## Recommended plan", "## Challenge findings", "## Approval",
                    "## Executed in the procurement system"):
        assert heading in approved, heading


def test_report_numbers(approved):
    for text in ("**3,200**", "**5,350 units**", "| Open orders due within 60 days | 77 |",
                 "**Total EUR 30,378**", "EUR 37,983,380"):
        assert text in approved, text


def test_revenue_at_risk_is_separate_from_the_cost(approved):
    assert "Recovery cost:** EUR 30,378" in approved
    assert "Revenue at risk (exposure, not an expected loss)" in approved


def test_rejected_options_say_why(approved):
    assert "rejected: Too slow" in approved                    # Helios
    assert "rejected: ISO 9001:2015 expired" in approved       # Borealis


def test_who_approved_and_what_ran(approved):
    assert "procurement_manager + finance_controller" in approved
    assert "Maria Keller (procurement_manager)" in approved
    assert approved.count("| done | SIM-") == 4


def test_rejected_case_executes_nothing(fake_llm):
    report = closed_case(fake_llm, "reject", "report-reject")
    assert "**Decision:** rejected" in report
    assert "Nothing was executed." in report
