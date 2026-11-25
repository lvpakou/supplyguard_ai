"""What the chat shows (role 5): a heading plus a few lines with what matters for the decision."""

import pytest
from conftest import MC17_FACTS, MC17_MESSAGE, config

from supplyguard_ai import chat_views as views
from supplyguard_ai.graph import build_graph
from supplyguard_ai.state import (ApprovalRequest, Conflict, Evidence, ExecutionResult, Option, Recommendation,
                                  SupplierCheck)


@pytest.fixture
def values(fake_llm) -> dict:
    """The MC-17 case at the approval: real impact (role 2) and options, no document search."""
    fake_llm(MC17_FACTS)
    return build_graph().invoke({"case_id": "case-views", "raw_text": MC17_MESSAGE}, config("case-views"))


def test_progress_is_one_line():
    assert views.progress_view(["intake", "impact"]) == "⏳ Calculating the impact…"
    assert views.progress_view(["intake", "impact"], finished=True) == "✓ message read · impact"


def test_impact_in_three_lines(values):
    text = views.impact_view(values)
    assert len(text.splitlines()) == 4                                  # heading + 3 lines
    assert "**3,200 of 5,200 MC-17 units are usable** (1,400 reserved for orders, 600 quarantined)" in text
    assert "**Shortfall: 5,350 units** before the delayed delivery (first stockout: day 7)" in text
    assert "Runs out: W-LYO in 3.3 days · W-KAT in 4.0 days · W-STU in 8.7 days." in text   # first to run out first
    assert "**77 customer orders at risk** on 6 products" in text and "(not a cost)" in text


def test_evidence_counts_sources_and_names_what_each_conflict_settled():
    notice = Evidence(claim="...", source_id="DOC-NOT-ATLAS-MC17", doc_type="supplier_notice")
    note = Evidence(claim="...", source_id="DOC-NOT-ATLAS-MC17", doc_type="contract_agent_note")
    values = {
        "conflicts": [Conflict(topic="Atlas delay", values={"DOC-NOT-ATLAS-MC17": "12 days", "DOC-EM-ATLAS-01": "16 days"},
                               chosen="12 days", reason="notice outranks e-mail")],
        "warnings": ["Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction (overrides our instructions): 'ignore all'",
                     "Security finding: ignored an instruction in the user's message "
                     "(suspicious instruction (pretends to be a system message): 'SYSTEM:')"],
        "evidence": [notice, note],
    }
    text = views.evidence_view(values)
    assert "- **1 source read**, filtered by your role: 1 notices." in text       # the note counts with its document
    assert "- **1 conflict between sources settled** (contract > certificate > notice > e-mail): Atlas delay: **12 days**." in text
    assert "- ⚠️ Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction (overrides our instructions)\n" in text
    assert ("- ⚠️ Security finding: ignored an instruction in the user's message (suspicious instruction "
            "(pretends to be a system message))") in text
    assert "ignore all" not in text and "SYSTEM:" not in text                   # injected words never repeated


def test_options_show_the_plan_the_rejections_and_the_risks():
    transfer = Option(strategy="A", title="Transfer hub stock", cost_eur=96, covered_units=800)
    values = {
        "options": [transfer, Option(strategy="C", title="Buy from Borealis Parts (S003)", feasible=False,
                                     rejected_because="ISO 9001 expired 2026-09-30.")],
        "recommendation": Recommendation(summary="Transfer", options=[transfer], total_cost_eur=96,
                                         uncovered_units=850, residual_handling="850 units: reschedule"),
        "facts": MC17_FACTS,
        "supplier_checks": [SupplierCheck(supplier_id="S005", name="Delta Micro Systems", shared_upstream_with=["S001"])],
        "investigation_notes": ["[Deep Agent] Delta (S005): shares Veltro with Atlas.", "[TW] Wafer fab maintenance"],
    }
    text = views.options_view(values)
    assert "- **Plan: EUR 96** (budget EUR 75,000), combining 1 of 2 options." in text
    assert "- **Still uncovered:** 850 units: reschedule" in text
    assert "- ❌ Borealis Parts (S003): ISO 9001 expired 2026-09-30." in text
    assert "- ⚠️ Delta Micro Systems (S005) shares an upstream manufacturer with S001" in text
    assert "- 🌐 Risk alert [TW] Wafer fab maintenance" in text and "Deep Agent" not in text


def test_approval_shows_the_exact_actions_the_checks_and_who_signs(values):
    request = ApprovalRequest(approval_id="APR-1", payload_hash="abc", total_cost_eur=30378,
                              approver_role="procurement_manager + finance_controller")
    values = {**values, "critique": ["EUR 30,378 needs BOTH procurement_manager and finance_controller to approve.",
                                     "Assumption: Atlas Components (S001) delay MC-17 = 12 days (...)",
                                     "850 units stay uncovered: reschedule."]}
    text = views.approval_view(values, request, ["procurement_manager", "finance_controller"], ["finance_controller"])
    assert text.startswith("### ✍️ Approve EUR 30,378?")
    assert "Purchase order: 3000 x MC-17 from S004" in text and "| | **Total** (budget EUR 75,000) | **30,378** |" in text
    assert "**Risks you accept by approving:**" in text and "- 🔎 Assumption: Atlas Components (S001) delay" in text
    assert "stay uncovered" not in text and "needs BOTH" not in text                 # already on screen elsewhere
    assert "- **Sign-off:** procurement manager ✅ · finance controller ⏳" in text
    assert "Approval `APR-1`" in text


def test_closing_lists_what_was_done():
    values = {"approval": ApprovalRequest(approval_id="APR-1", payload_hash="abc", total_cost_eur=30378,
                                          approver_role="x", status="approved"),
              "executions": [ExecutionResult(operation="create_purchase_order", idempotency_key="k", status="done",
                                             reference="PO-MCP-00001")]}
    text = views.closing_view(values)
    assert text.startswith("### ✅ Approved and executed: EUR 30,378")
    assert "- New purchase order: done (PO-MCP-00001)" in text and "incident-report.md" in text


def test_nothing_to_show_gives_empty_text():
    assert views.impact_view({}) == views.evidence_view({}) == views.options_view({}) == ""
