"""CHALLENGE: check the recommendation before asking for approval. OWNER: role 2.

Deterministic checks (no LLM): spending cap, certification, capacity, uncovered units,
shared upstream. Returns human-readable findings; an empty list means "no objections".
"""

from supplyguard_ai.state import CaseState


def review(state: CaseState) -> list[str]:
    findings = []
    rec = state.recommendation
    if rec is None:
        return ["No recommendation to review."]
    cap = state.facts.spending_cap_eur if state.facts else 75000
    if rec.total_cost_eur > cap:
        findings.append(f"Total cost EUR {rec.total_cost_eur:,.0f} exceeds the cap EUR {cap:,.0f}.")
    if rec.uncovered_units:
        findings.append(
            f"{rec.uncovered_units} units stay uncovered: {rec.residual_handling or 'needs a decision'}."
        )
    blocked = {c.supplier_id for c in state.supplier_checks if not c.certification_valid}
    for option in rec.options:
        for action in option.actions:
            if action.payload.get("supplier_id") in blocked:
                findings.append(f"{action.payload['supplier_id']} has no valid certification.")
    return findings
