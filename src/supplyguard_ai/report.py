"""INCIDENT REPORT (markdown). OWNER: role 2.

FIRST VERSION: a short summary. Role 2 completes it (timeline, evidence table, costs,
revenue at risk separately, decision and approver).
"""

from supplyguard_ai.state import CaseState


def build_report(state: CaseState) -> str:
    lines = [f"# Incident report {state.case_id}", "", f"**Request:** {state.raw_text}", ""]
    if state.impact:
        i = state.impact
        lines += ["## Impact",
                  f"- Usable stock {i.usable} of {i.on_hand} (reserved {i.reserved}, quarantined {i.quarantined})",
                  f"- Shortfall {i.shortfall_units} units · {len(i.affected_products)} products · "
                  f"{i.open_orders_at_risk} open orders at risk", ""]
    if state.recommendation:
        r = state.recommendation
        lines += ["## Recommendation", r.summary, f"- Total cost EUR {r.total_cost_eur:,.2f}", ""]
    if state.approval:
        lines += ["## Decision", f"- {state.approval.status} ({state.approval.approver_role})", ""]
    if state.executions:
        lines += ["## Executed"] + [f"- {e.operation}: {e.status} {e.reference or ''}" for e in state.executions]
    if state.warnings:
        lines += ["", "## Warnings"] + [f"- {w}" for w in state.warnings]
    return "\n".join(lines)
