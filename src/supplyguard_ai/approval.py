"""APPROVAL: what the human approves, bound to the exact payload. OWNER: role 5.

- payload_hash covers every action payload: if supplier, quantity, price or date changes,
  the hash changes and a NEW approval is required (policies.json approval_binds_to_payload).
- approver_role comes from the approval tiers in policies.json.
"""

import hashlib
import json

from supplyguard_ai.config import policies
from supplyguard_ai.state import ApprovalRequest, Recommendation


def payload_hash(recommendation: Recommendation) -> str:
    payloads = [
        {"operation": a.operation, "payload": a.payload}
        for option in recommendation.options for a in option.actions
    ]
    return hashlib.sha256(json.dumps(payloads, sort_keys=True).encode()).hexdigest()[:16]


def approver_for(total_cost_eur: float) -> str:
    for tier in policies()["approval_tiers_eur"]:
        if total_cost_eur <= tier["up_to"]:
            return tier["approver"]
    return "not allowed: above every approval tier"


def build_request(case_id: str, recommendation: Recommendation) -> ApprovalRequest:
    digest = payload_hash(recommendation)
    return ApprovalRequest(
        approval_id=f"APR-{case_id[:8]}-{digest[:6]}",
        payload_hash=digest,
        total_cost_eur=recommendation.total_cost_eur,
        approver_role=approver_for(recommendation.total_cost_eur),
    )
