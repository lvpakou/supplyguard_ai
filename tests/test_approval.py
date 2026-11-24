"""Approval rules (role 5): tiers, who may decide, sign-offs bound to the payload, audit records."""

import os
import uuid

import psycopg
import pytest
from conftest import MC17_FACTS, MC17_MESSAGE, config
from langgraph.types import Command

from supplyguard_ai import approval as approvals
from supplyguard_ai.graph import build_graph, pending
from supplyguard_ai.state import Action, ApprovalRequest

URL = os.getenv("TEST_DATABASE_URL", "postgresql://supplyguard:supplyguard@localhost:5433/supplyguard")


def request(total: float, payload_hash: str = "hash-1") -> ApprovalRequest:
    return ApprovalRequest(approval_id=f"APR-{uuid.uuid4().hex[:8]}", payload_hash=payload_hash,
                           total_cost_eur=total, approver_role=approvals.approver_for(total))


def row(role: str, decision: str, payload_hash: str = "hash-1") -> dict:
    return {"user_role": role, "decision": decision, "payload_hash": payload_hash}


# --- who may decide ---------------------------------------------------------
def test_the_tiers_name_the_roles_that_must_approve():
    assert approvals.required_roles(approvals.approver_for(20_000)) == ["procurement_manager"]
    assert approvals.required_roles(approvals.approver_for(30_378)) == ["procurement_manager", "finance_controller"]
    assert approvals.required_roles(approvals.approver_for(80_000)) == ["finance_director"]
    assert approvals.required_roles(approvals.approver_for(100_000)) == []


def test_only_a_role_of_the_tier_may_approve():
    plan = request(30_378)
    assert approvals.can_decide("procurement_manager", plan, "approve")
    assert approvals.can_decide("finance_controller", plan, "approve")
    assert not approvals.can_decide("operations_analyst", plan, "approve")
    assert not approvals.can_decide("viewer", plan, "approve")
    assert not approvals.can_decide("finance_controller", request(20_000), "approve")


def test_nobody_approves_above_every_tier_but_it_can_be_rejected_or_changed():
    too_big = request(100_000)
    assert not approvals.can_decide("finance_director", too_big, "approve")
    assert approvals.can_decide("procurement_manager", too_big, "reject")
    assert approvals.can_decide("procurement_manager", too_big, "change")
    assert not approvals.can_decide("viewer", too_big, "reject")


# --- sign-offs --------------------------------------------------------------
def test_two_role_tier_needs_both_signoffs():
    plan = request(30_378)
    assert approvals.missing_signoffs(plan, []) == ["procurement_manager", "finance_controller"]
    assert approvals.missing_signoffs(plan, [row("procurement_manager", "approve")]) == ["finance_controller"]
    both = [row("procurement_manager", "approve"), row("finance_controller", "approve")]
    assert approvals.missing_signoffs(plan, both) == []


def test_a_signoff_counts_only_for_the_payload_it_was_given_for():
    plan = request(30_378, payload_hash="hash-2")
    old = [row("procurement_manager", "approve", "hash-1"), row("finance_controller", "approve", "hash-1")]
    assert approvals.missing_signoffs(plan, old) == ["procurement_manager", "finance_controller"]


def test_a_change_or_reject_starts_the_signoffs_over():
    plan = request(30_378)
    history = [row("procurement_manager", "approve"), row("finance_controller", "change"),
               row("finance_controller", "approve")]
    assert approvals.missing_signoffs(plan, history) == ["procurement_manager"]


def test_actions_are_described_exactly():
    buy = Action(operation="create_purchase_order", payload={
        "supplier_id": "S004", "component_id": "MC-17", "qty": 3000, "unit_price_eur": 9.8,
        "requested_delivery_date": "2026-10-28"})
    assert approvals.describe(buy) == ("Purchase order: 3000 x MC-17 from S004 at EUR 9.8/unit, "
                                       "delivery 2026-10-28")
    odd = Action(operation="request_stock_transfer", payload={"qty": 5})  # missing fields: show raw
    assert approvals.describe(odd) == 'request_stock_transfer {"qty": 5}'


# --- the chat's decision reaches the graph (role 1's approval node) ----------
def test_change_asks_again_and_approve_executes(fake_llm):
    fake_llm(MC17_FACTS)
    app = build_graph()
    first = app.invoke({"case_id": "case-decide", "raw_text": MC17_MESSAGE}, config("case-decide"))
    who = {"user_id": "u-fc-01", "user_role": "finance_controller",
           "payload_hash": pending(first)["request"]["payload_hash"]}

    # 2,500 fits Cordillera's capacity, so the new plan keeps its 4 actions (6,000 would be left out).
    changed = app.invoke(Command(resume={"decision": "change", "change": "qty 2500", **who}), config("case-decide"))
    assert pending(changed)["type"] == "approval"           # a change needs a new approval
    assert changed.get("executions", []) == []

    # The change built a new plan, so approve the NEW payload (the old hash no longer counts).
    who["payload_hash"] = pending(changed)["request"]["payload_hash"]
    approved = app.invoke(Command(resume={"decision": "approve", "change": None, **who}), config("case-decide"))
    assert approved["approval"].status == "approved"
    assert [e.status for e in approved["executions"]] == ["done"] * 4


# --- audit records in Postgres ----------------------------------------------
@pytest.fixture
def postgres(monkeypatch):
    try:
        psycopg.connect(URL, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("needs Postgres: docker compose up -d postgres")
    monkeypatch.setenv("DATABASE_URL", URL)
    case_id = f"test-{uuid.uuid4()}"
    yield case_id
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DELETE FROM approval_decisions WHERE case_id = %s", (case_id,))


def test_decisions_are_stored_and_the_second_approver_finds_the_case(postgres):
    plan = request(30_378)
    approvals.record(postgres, plan, "u-pm-01", "procurement_manager", "requested")
    approvals.record(postgres, plan, "u-pm-01", "procurement_manager", "approve")

    history = approvals.decisions(plan.approval_id)
    assert [(r["user_id"], r["decision"]) for r in history] == [("u-pm-01", "requested"), ("u-pm-01", "approve")]
    assert approvals.missing_signoffs(plan, history) == ["finance_controller"]
    assert postgres in approvals.cases_for_role("finance_controller")
    assert postgres not in approvals.cases_for_role("viewer")
