"""IMPACT: which products, orders and plants a delay hits, and the shortfall. OWNER: role 2.

The chain, all in plain Python (no LLM):

  1. affected products   bill_of_materials: every product whose BOM contains the component
  2. orders at risk      customer_orders: OPEN orders for those products, due within 60 days
  3. daily demand        production_schedule (the scenario week) x qty_per_unit, per plant
  4. days of cover       usable stock at each plant's own warehouse / that plant's demand
  5. the delayed delivery purchase_orders: the open PO of this supplier for this component,
                          promised date + announced delay
  6. shortfall           demand between the ORIGINAL and the DELAYED arrival that the
                          usable stock cannot cover (all usable stock pooled, no action taken)
  7. revenue at risk     revenue of the orders at risk. This is EXPOSURE, not an expected
                          loss, and it is reported separately from any recovery cost.

"Day N" means N days after the scenario date in policies.json (2026-10-19).
"""

import math

import pandas as pd

from supplyguard_ai.config import policies
from supplyguard_ai.state import ImpactSummary, IncidentFacts
from supplyguard_ai.tools.inventory import usable_stock
from supplyguard_ai.tools.tables import table

AT_RISK_WINDOW_DAYS = 60  # "at risk" = open orders due within 60 days (data/README, eval cases)


def scenario_day() -> pd.Timestamp:
    return pd.Timestamp(policies()["scenario_date"])


# ---------------------------------------------------------------------------
# 1-2. Products and customer orders
# ---------------------------------------------------------------------------
def affected_products(component_id: str) -> pd.DataFrame:
    """BOM lines of the products that use the component: product_id, qty_per_unit."""
    bom = table("bill_of_materials")
    return bom[bom["component_id"] == component_id][["product_id", "qty_per_unit"]]


def orders_at_risk(product_ids: list[str]) -> pd.DataFrame:
    """Open customer orders for these products, due within the next 60 days."""
    orders = table("customer_orders")
    day = scenario_day()
    return orders[
        orders["product_id"].isin(product_ids)
        & (orders["status"] == "open")
        & (orders["due_date"] <= day + pd.Timedelta(days=AT_RISK_WINDOW_DAYS))
    ]


# ---------------------------------------------------------------------------
# 3. How many units of the component each plant uses per day
# ---------------------------------------------------------------------------
def daily_demand_per_factory(bom_lines: pd.DataFrame) -> dict[str, float]:
    """{"F1": 150.0, ...}: component units per day, from the scenario week's plan.

    A product needing 3 units of the component (qty_per_unit = 3) counts three times.
    """
    schedule = table("production_schedule")
    day = scenario_day()
    week = schedule[(schedule["week_start"] <= day) & (day < schedule["week_start"] + pd.Timedelta(days=7))]
    plan = week.merge(bom_lines, on="product_id")
    plan["component_units"] = plan["planned_units"] * plan["qty_per_unit"]
    per_week = plan.groupby("factory_id")["component_units"].sum()
    return {factory: units / 7 for factory, units in per_week.items()}


# ---------------------------------------------------------------------------
# 5. When the delayed delivery arrives
# ---------------------------------------------------------------------------
def delayed_delivery(supplier_id: str | None, component_id: str, delay_days: int) -> dict:
    """The open PO hit by the delay, and its original and new arrival day.

    If we can't find the PO, we assume the delivery was due today (day 0): the
    shortfall then covers the whole delay, and a warning says why.
    """
    pos = table("purchase_orders")
    open_po = pos[
        (pos["component_id"] == component_id)
        & (pos["supplier_id"] == supplier_id)
        & (pos["status"] != "delivered")
    ].sort_values("promised_date")
    day = scenario_day()
    if open_po.empty:
        return {"po_id": None, "original_day": 0, "delayed_day": delay_days,
                "warning": f"No open purchase order of {supplier_id} for {component_id}: "
                           f"assumed the delivery was due today."}
    po = open_po.iloc[0]
    original_day = max(0, (po["promised_date"] - day).days)
    return {"po_id": po["po_id"], "original_day": original_day,
            "delayed_day": original_day + delay_days, "warning": None}


# ---------------------------------------------------------------------------
# The whole assessment
# ---------------------------------------------------------------------------
def assess_impact(facts: IncidentFacts) -> ImpactSummary:
    component = facts.component_id.strip().upper()
    stock = usable_stock(component)

    bom_lines = affected_products(component)
    products = sorted(bom_lines["product_id"])
    orders = orders_at_risk(products)

    per_factory = daily_demand_per_factory(bom_lines)
    daily = sum(per_factory.values())

    # 4. Days of cover at each plant's OWN warehouse (the hub belongs to no plant).
    locations = table("locations").dropna(subset=["factory_id"])
    warehouse_of = dict(zip(locations["factory_id"], locations["location_id"]))
    days_of_cover = {
        f"{factory} ({warehouse_of[factory]})":
            round(stock["by_location"].get(warehouse_of[factory], 0) / demand, 1)
        for factory, demand in sorted(per_factory.items())
        if demand > 0 and factory in warehouse_of
    }

    # 5-6. Shortfall caused by the delay, with all usable stock pooled.
    delivery = delayed_delivery(facts.supplier_id, component, facts.delay_days or 0)
    if daily > 0:
        first_stockout_day = math.floor(stock["usable"] / daily)
        stock_at_original_arrival = max(0.0, stock["usable"] - daily * delivery["original_day"])
        gap_days = delivery["delayed_day"] - delivery["original_day"]
        shortfall = max(0, round(daily * gap_days - stock_at_original_arrival))
    else:  # the component is in no planned product: nothing runs out
        first_stockout_day, shortfall = None, 0

    sources = ["structured/bill_of_materials.csv", "structured/customer_orders.csv",
               "structured/production_schedule.csv", "structured/purchase_orders.csv",
               *stock["source_ids"]]
    if delivery["po_id"]:
        sources.append(delivery["po_id"])

    return ImpactSummary(
        component_id=component,
        on_hand=stock["on_hand"],
        reserved=stock["reserved"],
        quarantined=stock["quarantined"],
        usable=stock["usable"],
        usable_by_location=stock["by_location"],
        daily_demand=round(daily),
        days_of_cover=days_of_cover,
        first_stockout_day=first_stockout_day,
        shortfall_units=shortfall,
        affected_products=products,
        open_orders_at_risk=len(orders),
        revenue_at_risk_eur=round(float(orders["revenue_eur"].sum()), 2),
        source_ids=sources,
    )