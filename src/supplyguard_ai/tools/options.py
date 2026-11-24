"""RECOVERY OPTIONS: strategies A-E, fully costed, in plain Python. OWNER: role 2.

  A transfer inventory · B expedite an existing order · C buy from an approved alternative
  D reallocate across customer orders · E reschedule production

STUB: returns the golden reference plan 1 (about EUR 30,378) and the golden rejections.
Real version: compute from impact, supplier checks (role 4), contract terms (role 3) and
policies.json (transfer cost 0.12/unit, cap). Every Action payload must match
data/config/procurement_system_operations.json. Keep the signature.
"""

from datetime import date, timedelta

from supplyguard_ai.config import golden_scenario, policies
from supplyguard_ai.state import Action, CaseState, Option, Recommendation


def build_options(state: CaseState) -> tuple[list[Option], Recommendation]:
    gold = golden_scenario()
    plan = gold["feasible_reference_plans"]["plan_1_without_shared_upstream"]
    costs = plan["cost_breakdown"]
    day0 = date.fromisoformat(policies()["scenario_date"])
    component = state.facts.component_id

    transfer = Option(
        strategy="A", title="Transfer hub stock to Katowice and Lyon (they run out first)",
        actions=[
            Action(operation="request_stock_transfer", cost_eur=48.0,
                   payload={"component_id": component, "from_location": "W-HUB", "to_location": "W-KAT", "qty": 400}),
            Action(operation="request_stock_transfer", cost_eur=48.0,
                   payload={"component_id": component, "from_location": "W-HUB", "to_location": "W-LYO", "qty": 400}),
        ],
        cost_eur=costs["transfers"], covered_units=800,
    )
    expedite = Option(
        strategy="B", title="Expedite Cordillera PO-2026-9002 (1,500 units, +7 days, 6% per contract)",
        actions=[Action(operation="expedite_purchase_order", cost_eur=costs["expedite_fee_6pct_contract"],
                        payload={"po_id": "PO-2026-9002", "days_gain": 7, "fee_pct": 6})],
        cost_eur=costs["expedite_fee_6pct_contract"], covered_units=1500,
    )
    buy = Option(
        strategy="C", title="Buy 3,000 units from Cordillera (S004), EUR 9.80, 9 days",
        actions=[Action(operation="create_purchase_order", cost_eur=costs["cordillera_purchase"],
                        payload={"supplier_id": "S004", "component_id": component, "qty": 3000,
                                 "unit_price_eur": 9.80,
                                 "requested_delivery_date": str(day0 + timedelta(days=9))})],
        cost_eur=costs["cordillera_purchase"], covered_units=3000,
    )
    rejected = [
        Option(strategy="C", title=f"Buy from {name}", feasible=False, rejected_because=why)
        for name, why in gold["alternatives"].items()
        if not name.startswith("S004")
    ]
    options = [transfer, expedite, buy, *rejected]
    chosen = [transfer, expedite, buy]
    recommendation = Recommendation(
        summary="Transfer hub stock, expedite PO-2026-9002 and buy 3,000 units from Cordillera.",
        options=chosen,
        total_cost_eur=round(sum(o.cost_eur for o in chosen), 2),
        uncovered_units=plan["uncovered_units"],
        residual_handling=plan["residual_handling"],
    )
    return options, recommendation
