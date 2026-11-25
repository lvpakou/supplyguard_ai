"""What the chat shows (role 5): short messages that keep every fact, long material in the side panel."""

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


def test_progress_is_one_checklist_in_plain_words():
    assert views.progress_view(["intake", "impact"]) == (
        "- ✓ Read your message: supplier, component, delay, budget\n"
        "- ⏳ Impact on stock, products and customer orders…")
    assert "⏳" not in views.progress_view(["intake", "impact"], finished=True)


def test_impact_keeps_every_number_and_puts_the_first_to_run_out_on_top(values):
    text = views.impact_view(values)
    assert "**3,200 of 5,200 MC-17 units are usable.** 1,400 are reserved for customer orders, 600 are quarantined." in text
    rows = [line for line in text.splitlines() if line.startswith("| W-")]
    assert rows == ["| W-LYO (F3) | 500 | 3.3 days |", "| W-KAT (F2) | 600 | 4.0 days |",
                    "| W-STU (F1) | 1,300 | 8.7 days |", "| W-HUB (hub, for transfers) | 800 | – |"]
    assert "**Shortfall: 5,350 units**" in text and "first stockout: day 7" in text
    assert "**At risk: 77 open customer orders** on 6 products" in text
    assert "It is not a cost and is never added to the recovery cost." in text
    assert "_Calculated from: bill_of_materials, customer_orders" in text


def test_evidence_explains_conflicts_and_groups_the_sources():
    notice = Evidence(claim="Supplier notice - Atlas\n12 days", source_id="DOC-NOT-ATLAS-MC17", doc_type="supplier_notice")
    note = Evidence(claim="Contract agent, Atlas (S001): v3 applies.", source_id="DOC-CON-S001-v3",
                    doc_type="contract_agent_note")
    values = {
        "conflicts": [Conflict(topic="Atlas delay", values={"DOC-NOT-ATLAS-MC17": "12 days", "DOC-EM-ATLAS-01": "16 days"},
                               chosen="12 days", reason="notice outranks e-mail")],
        "warnings": ["Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction"],
        "evidence": [notice, notice, note],
    }
    text = views.evidence_view(values)
    assert "**1 conflict between sources**, settled by the precedence rule: contract (latest version) > " in text
    assert ("- **Atlas delay:** we use **12 days** (DOC-NOT-ATLAS-MC17: 12 days · DOC-EM-ATLAS-01: 16 days). "
            "_notice outranks e-mail_") in text
    assert "(1 note): see **Contract agent notes**" in text             # the notes are one click away
    assert views.side_panels(values)["Contract agent notes"] == "- Atlas (S001): v3 applies."
    assert "- ⚠️ Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction" in text
    assert "**Read 2 sources**" in text and "- Supplier notices: DOC-NOT-ATLAS-MC17" in text


def test_options_show_the_plan_the_rejections_and_the_supplier_risks():
    transfer = Option(strategy="A", title="Transfer hub stock", cost_eur=96, covered_units=800)
    values = {
        "options": [transfer, Option(strategy="C", title="Buy from S003 Borealis", feasible=False,
                                     rejected_because="ISO 9001 expired 2026-09-30")],
        "recommendation": Recommendation(summary="Transfer", options=[transfer], total_cost_eur=96,
                                         uncovered_units=850, residual_handling="reschedule"),
        "facts": MC17_FACTS,
        "supplier_checks": [SupplierCheck(supplier_id="S005", name="Delta Micro Systems", unit_price_eur=10.4,
                                          lead_time_days=8, shared_upstream_with=["S001"], notes=["Cert until 2027"])],
        "investigation_notes": ["[Deep Agent] Delta (S005): shares Veltro with Atlas.", "[TW] Wafer fab maintenance"],
    }
    text = views.options_view(values)
    assert "| A | Transfer hub stock | 96 | 800 | ✅ in the plan |" in text
    assert "| C | Buy from S003 Borealis | – | 0 | ❌ ISO 9001 expired 2026-09-30 |" in text
    assert "**Plan: EUR 96** (budget EUR 75,000) · **Still uncovered:** reschedule" in text
    assert "| S005 Delta Micro Systems | 10.40 | 8 days | valid | same upstream as S001 |" in text
    assert "- 🌐 [TW] Wafer fab maintenance" in text and "**Deep Agent notes**" in text
    panels = views.side_panels(values)                                # nothing lost: the details are one click away
    assert "Cert until 2027" in panels["Supplier details"]
    assert "Delta (S005): shares Veltro with Atlas." in panels["Deep Agent notes"]


def test_the_real_mc17_options_mark_the_plan(values):
    text = views.options_view(values)
    assert text.count("✅ in the plan") == len(values["recommendation"].options)


def test_approval_shows_the_exact_actions_and_who_still_signs(values):
    request = ApprovalRequest(approval_id="APR-1", payload_hash="abc", total_cost_eur=30378,
                              approver_role="procurement_manager + finance_controller")
    text = views.approval_view(values, request, ["procurement_manager", "finance_controller"], ["finance_controller"])
    assert text.startswith("### ✍️ Approval needed: EUR 30,378 · budget EUR 75,000")
    assert "| **Total** | **30,378.00** |" in text and "Purchase order: 3000 x MC-17 from S004" in text
    assert "**Before you approve:**" in text and "- 🔎 850 units stay uncovered" in text   # the challenge step
    assert "- **Sign-off:** procurement_manager ✅ · finance_controller ⏳" in text
    assert "Approval `APR-1` · payload `abc`" in text


def test_closing_lists_what_was_done_and_puts_the_report_on_the_side():
    values = {"approval": ApprovalRequest(approval_id="APR-1", payload_hash="abc", total_cost_eur=30378,
                                          approver_role="x", status="approved"),
              "executions": [ExecutionResult(operation="create_purchase_order", idempotency_key="k", status="done",
                                             reference="PO-MCP-00001")],
              "report": "# Incident report\nfull text"}
    text = views.closing_view(values)
    assert text.startswith("### ✅ Approved and executed")
    assert "| New purchase order | done | PO-MCP-00001 |" in text and "**Incident report**" in text
    assert views.side_panels(values)["Incident report"] == "# Incident report\nfull text"


def test_the_side_panel_shows_the_document_not_a_later_note_about_it():
    contract = Evidence(claim="Supply contract - Atlas\nfull text", source_id="DOC-CON-S001-v3", doc_type="contract")
    note = Evidence(claim="Contract agent, Atlas: v3 applies", source_id="DOC-CON-S001-v3",
                    doc_type="contract_agent_note")
    assert views.documents({"evidence": [contract, note]}) == [contract]


def test_nothing_to_show_gives_empty_text():
    assert views.impact_view({}) == views.evidence_view({}) == views.options_view({}) == ""
    assert views.side_panels({}) == {}
