"""What the chat shows of an investigation (role 5): impact, evidence and conflicts, options."""

from types import SimpleNamespace

import pytest
from conftest import MC17_FACTS, MC17_MESSAGE, config

from supplyguard_ai import chat_views as views
from supplyguard_ai.graph import build_graph
from supplyguard_ai.state import Conflict, Evidence, Option, Recommendation, SupplierCheck


@pytest.fixture
def values(fake_llm) -> dict:
    """The MC-17 case at the approval: real impact (role 2) and options, no document search."""
    fake_llm(MC17_FACTS)
    return build_graph().invoke({"case_id": "case-views", "raw_text": MC17_MESSAGE}, config("case-views"))


def test_impact_shows_usable_stock_cover_and_shortfall(values):
    text = views.impact_view(values)
    assert "**MC-17: 3,200 of 5,200 units are usable** (1,400 reserved for customer orders, 600 quarantined)" in text
    assert "| W-KAT | 600 | F2 (W-KAT) | 4.0 |" in text
    assert "| W-LYO | 500 | F3 (W-LYO) | 3.3 |" in text
    assert "| W-HUB | 800 | hub (for transfers) | – |" in text
    assert "first stockout: **day 7**" in text and "**shortfall 5,350 units**" in text
    assert "6 products affected" in text and "**77 open customer orders at risk**" in text
    assert "never added to the recovery cost" in text
    assert "_Sources: structured/bill_of_materials.csv" in text


def test_options_show_the_plan_the_rejections_and_the_suppliers():
    # Built here, not taken from the graph: roles 2 and 4 are still replacing their stubs.
    transfer = Option(strategy="A", title="Transfer hub stock", cost_eur=96, covered_units=800)
    values = {
        "options": [transfer, Option(strategy="C", title="Buy from S003 Borealis", feasible=False,
                                     rejected_because="ISO 9001 expired 2026-09-30")],
        "recommendation": Recommendation(summary="Transfer", options=[transfer], total_cost_eur=96, uncovered_units=850),
        "supplier_checks": [
            SupplierCheck(supplier_id="S003", name="Borealis Parts", lead_time_days=6, certification_valid=False),
            SupplierCheck(supplier_id="S005", name="Delta Micro Systems", unit_price_eur=10.4, lead_time_days=8,
                          monthly_capacity=2500, shared_upstream_with=["S001"], risk_alerts=["TW wafer alert"]),
        ],
        "investigation_notes": ["[TW] Wafer fab maintenance"],
        "impact": SimpleNamespace(revenue_at_risk_eur=37983380.43),
    }
    text = views.options_view(values)
    assert "| A | Transfer hub stock | 96 | 800 | ✅ in the plan |" in text
    assert "| C | Buy from S003 Borealis | – | 0 | ❌ ISO 9001 expired 2026-09-30 |" in text
    assert "| S003 Borealis Parts | – | 6 | – | ❌ not valid | – |  |" in text
    assert "| S005 Delta Micro Systems | 10.40 | 8 | 2,500 | valid | S001 | TW wafer alert |" in text
    assert "- [TW] Wafer fab maintenance" in text
    assert ("**Recovery cost of the plan: EUR 96.00** · 850 units still uncovered. "
            "Shown separately: revenue at risk EUR 37,983,380 (exposure, not a cost).") in text


def test_the_real_mc17_options_are_shown_with_the_plan_marked(values):
    text = views.options_view(values)
    assert text.count("✅ in the plan") == len(values["recommendation"].options)
    assert f"EUR {values['recommendation'].total_cost_eur:,.2f}" in text


def test_evidence_shows_conflicts_warnings_and_each_document_once():
    notice = Evidence(claim="Supplier notice - Atlas\n12 days", source_id="DOC-NOT-ATLAS-MC17",
                      doc_type="supplier_notice", version="1", effective_date="2026-10-19")
    values = {
        "conflicts": [Conflict(topic="Atlas delay", values={"DOC-NOT-ATLAS-MC17": "12 days", "DOC-EM-ATLAS-01": "16 days"},
                               chosen="12 days", reason="notice | outranks e-mail")],
        "warnings": ["Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction"],
        "evidence": [notice, notice],
    }
    text = views.evidence_view(values)
    assert ("| Atlas delay | DOC-NOT-ATLAS-MC17: 12 days; DOC-EM-ATLAS-01: 16 days | **12 days** | "
            "notice \\| outranks e-mail |") in text                         # a | inside a cell is escaped
    assert "- ⚠️ Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction" in text
    assert text.count("- DOC-NOT-ATLAS-MC17 · supplier_notice v1 · 2026-10-19 · Supplier notice - Atlas") == 1
    assert len(views.documents(values)) == 1


def test_nothing_to_show_gives_empty_text():
    assert views.impact_view({}) == views.evidence_view({}) == views.options_view({}) == ""
