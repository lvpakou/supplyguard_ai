"""IMPACT: which products, orders and plants a delay hits, and the shortfall. OWNER: role 2.

STUB: golden MC-17 numbers. Real version: BOM (bill_of_materials.csv) -> products,
customer_orders.csv (open, due within 60 days) -> orders at risk, production_schedule.csv
-> daily demand, usable_stock() -> days of cover and shortfall. Keep the signature.
"""

from supplyguard_ai.config import golden_scenario
from supplyguard_ai.state import ImpactSummary, IncidentFacts
from supplyguard_ai.tools.inventory import usable_stock


def assess_impact(facts: IncidentFacts) -> ImpactSummary:
    gold = golden_scenario()
    stock = usable_stock(facts.component_id)
    return ImpactSummary(
        component_id=facts.component_id,
        on_hand=stock["on_hand"],
        reserved=stock["reserved"],
        quarantined=stock["quarantined"],
        usable=stock["usable"],
        usable_by_location=stock["by_location"],
        daily_demand=gold["daily_mc17_demand"],
        days_of_cover={k: v for k, v in gold["days_of_cover_at_own_plant"].items() if k.startswith("F")},
        first_stockout_day=gold["first_stockout_day_without_action"],
        shortfall_units=gold["expected_shortfall_units"],
        affected_products=gold["affected_products"],
        open_orders_at_risk=gold["open_orders_due_within_60d_on_affected_products"],
        revenue_at_risk_eur=None,  # role 2: from customer orders, separately from recovery cost
        source_ids=["STUB:golden_scenario.json"],
    )
