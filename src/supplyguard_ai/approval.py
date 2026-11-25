"""APPROVAL: what the human approves, bound to the exact payload. OWNER: role 5.

- payload_hash covers every action payload: if supplier, quantity, price or date changes,
  the hash changes and a NEW approval is required (policies.json approval_binds_to_payload).
- approver_role comes from the approval tiers in policies.json. "a + b" means BOTH roles
  must approve (e.g. the EUR 30k reference plan: procurement manager AND finance controller).
- Every decision is an audit row in Postgres (approval_decisions): requested / approve /
  reject / change, with who, when and the payload_hash. A sign-off only counts for the
  payload_hash it was given for, and a reject or change starts the sign-offs over.
"""

import hashlib
import json

import psycopg
from psycopg.rows import dict_row

from supplyguard_ai.config import policies, require
from supplyguard_ai.state import Action, ApprovalRequest, Recommendation


def payload_hash(recommendation: Recommendation, change: dict | None = None) -> str:
    payloads = [
        {"operation": a.operation, "payload": a.payload}
        for option in recommendation.options for a in option.actions
    ]
    if change:  # a change at the approval always needs a NEW approval, even if the plan comes out the same
        payloads.append({"requested_change": change})
    return hashlib.sha256(json.dumps(payloads, sort_keys=True).encode()).hexdigest()[:16]


def approver_for(total_cost_eur: float) -> str:
    for tier in policies()["approval_tiers_eur"]:
        if total_cost_eur <= tier["up_to"]:
            return tier["approver"]
    return "not allowed: above every approval tier"


def build_request(case_id: str, recommendation: Recommendation,
                  change: dict | None = None) -> ApprovalRequest:
    digest = payload_hash(recommendation, change)
    return ApprovalRequest(
        approval_id=f"APR-{case_id[:8]}-{digest[:6]}",
        payload_hash=digest,
        total_cost_eur=recommendation.total_cost_eur,
        approver_role=approver_for(recommendation.total_cost_eur),
    )


# ---------------------------------------------------------------------------
# Who may decide
# ---------------------------------------------------------------------------
def required_roles(approver_role: str) -> list[str]:
    """'procurement_manager + finance_controller' -> both. Above every tier -> nobody."""
    if approver_role.startswith("not allowed"):
        return []
    return [role.strip() for role in approver_role.split("+")]


def can_decide(user_role: str, request: ApprovalRequest, decision: str) -> bool:
    """Approve: only a role of this request's tier. Reject / change spend nothing:
    any role that approves in some tier may do it (also for a plan above every tier)."""
    if decision == "approve":
        return user_role in required_roles(request.approver_role)
    tier_roles = {r for tier in policies()["approval_tiers_eur"] for r in required_roles(tier["approver"])}
    return user_role in tier_roles


def missing_signoffs(request: ApprovalRequest, decisions: list[dict]) -> list[str]:
    """Roles that still have to approve this exact payload (decisions oldest first)."""
    signed = set()
    for d in decisions:
        if d["payload_hash"] != request.payload_hash:
            continue
        if d["decision"] == "approve":
            signed.add(d["user_role"])
        elif d["decision"] in ("reject", "change"):
            signed.clear()
    return [role for role in required_roles(request.approver_role) if role not in signed]


_DESCRIPTIONS = {
    "create_purchase_order": "Purchase order: {qty} x {component_id} from {supplier_id} "
                             "at EUR {unit_price_eur}/unit, delivery {requested_delivery_date}",
    "expedite_purchase_order": "Expedite {po_id}: {days_gain} days earlier, fee {fee_pct}%",
    "request_stock_transfer": "Transfer {qty} x {component_id} from {from_location} to {to_location}",
    "update_production_schedule": "Production plan: {planned_units} units of {product_id}, week of {week_start}",
}


def describe(action: Action) -> str:
    """One line a manager can check: exactly what will be done (raw payload if it does not fit)."""
    try:
        return _DESCRIPTIONS[action.operation].format(**action.payload)
    except (KeyError, ValueError):
        return f"{action.operation} {json.dumps(action.payload, sort_keys=True)}"


# ---------------------------------------------------------------------------
# Audit records (Postgres)
# ---------------------------------------------------------------------------
_TABLE = """
CREATE TABLE IF NOT EXISTS approval_decisions (
    id             bigserial PRIMARY KEY,
    case_id        text NOT NULL,
    approval_id    text NOT NULL,
    payload_hash   text NOT NULL,
    approver_role  text NOT NULL,
    total_cost_eur numeric NOT NULL,
    user_id        text NOT NULL,
    user_role      text NOT NULL,
    decision       text NOT NULL,  -- requested / approve / reject / change
    note           text,           -- what the user asked to change
    decided_at     timestamptz NOT NULL DEFAULT now()
)"""


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(require("DATABASE_URL")["DATABASE_URL"], autocommit=True, row_factory=dict_row)
    conn.execute(_TABLE)
    return conn


def record(case_id: str, request: ApprovalRequest, user_id: str, user_role: str,
           decision: str, note: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO approval_decisions (case_id, approval_id, payload_hash, approver_role, total_cost_eur,"
            " user_id, user_role, decision, note) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (case_id, request.approval_id, request.payload_hash, request.approver_role,
             request.total_cost_eur, user_id, user_role, decision, note),
        )


def decisions(approval_id: str) -> list[dict]:
    with _connect() as conn:
        return conn.execute("SELECT * FROM approval_decisions WHERE approval_id = %s ORDER BY id",
                            (approval_id,)).fetchall()


def cases_for_role(user_role: str) -> list[str]:
    """Cases that asked this role for approval. The chat checks which are still waiting."""
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT case_id, approver_role FROM approval_decisions"
                            " WHERE decision = 'requested'").fetchall()
    return sorted({r["case_id"] for r in rows if user_role in required_roles(r["approver_role"])})
