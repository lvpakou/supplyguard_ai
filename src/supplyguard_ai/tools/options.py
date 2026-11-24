"""RECOVERY OPTIONS: strategies A-E, fully costed, in plain Python. OWNER: role 2.

  A transfer inventory · B expedite an existing order · C buy from an approved alternative
  D reallocate across customer orders · E reschedule production

Every number comes from the data, not from the LLM:
  - suppliers, prices, lead times, capacities  structured/supplier_components.csv
  - certification and upstream manufacturer    structured/suppliers.csv
  - open orders that can be expedited          structured/purchase_orders.csv
  - transfer cost and the spending cap         config/policies.json

The model (the trainer's definition of the shortfall):
  - The shortfall is the demand the usable stock can't cover between the original and the
    delayed arrival (impact.py). Every option that delivers BEFORE the delayed arrival
    covers its units of it; uncovered = shortfall - covered.
  - A transfer adds no units: it moves the hub stock to the plants that run out first.
  - Limit: this is not a day-by-day simulation; it is the trainer's pooled-stock model.

The plan we recommend (golden "plan 1"): transfer the hub stock, expedite an open order,
buy from the cheapest valid supplier that does NOT share an upstream manufacturer with the
delayed supplier. A supplier that shares one (Delta) is offered separately (golden "plan 2").

A change asked at the approval (state.requested_change: qty / supplier_id /
spending_cap_eur / note) is applied here, so the new plan gets a new payload hash and
a new approval.
"""

import re
from datetime import timedelta

import pandas as pd

from supplyguard_ai.config import policies
from supplyguard_ai.state import Action, CaseState, Option, Recommendation
from supplyguard_ai.tools.impact import delayed_delivery, scenario_day
from supplyguard_ai.tools.tables import table


# ---------------------------------------------------------------------------
# The change asked at the approval
# ---------------------------------------------------------------------------
def read_change(change: dict | None) -> dict:
    """The agreed keys of requested_change, plus a quantity typed in the note.

    "Change the quantity to 6,000" -> {"qty": 6000, ...}
    """
    change = dict(change or {})
    note = str(change.get("note") or "")
    if not change.get("qty") and re.search(r"\b(qty|quantity|units)\b", note, re.I):
        number = re.search(r"\d[\d,.]*", note)
        if number:
            change["qty"] = int(re.sub(r"[,.]", "", number.group()))
    return change


# ---------------------------------------------------------------------------
# A: transfer the hub stock to the plants that run out first
# ---------------------------------------------------------------------------
def transfer_option(component: str, state: CaseState) -> Option:
    """Send the hub stock, 50 units at a time, to the plant with the fewest days of cover.

    For MC-17: Lyon (3.3 days) and Katowice (4.0) get it, Stuttgart (8.7) needs none.
    """
    impact = state.impact
    locations = table("locations")
    hubs = set(locations[locations["factory_id"].isna()]["location_id"])
    plant_warehouse = dict(zip(locations["factory_id"], locations["location_id"]))
    hub_units = sum(units for loc, units in impact.usable_by_location.items() if loc in hubs)
    hub = next(iter(hubs), "W-HUB")

    # days of cover per warehouse, from impact.days_of_cover = {"F2 (W-KAT)": 4.0, ...}
    daily = {plant_warehouse[key.split()[0]]: impact.usable_by_location.get(plant_warehouse[key.split()[0]], 0) / cover
             for key, cover in impact.days_of_cover.items() if cover > 0}
    stock = {warehouse: impact.usable_by_location.get(warehouse, 0) for warehouse in daily}
    sent = {warehouse: 0 for warehouse in daily}
    for _ in range(hub_units // 50):
        neediest = min(stock, key=lambda w: (stock[w] + sent[w]) / daily[w])
        sent[neediest] += 50

    cost_per_unit = policies()["transfer_cost_eur_per_unit"]
    actions = [
        Action(operation="request_stock_transfer", cost_eur=round(qty * cost_per_unit, 2),
               payload={"component_id": component, "from_location": hub, "to_location": warehouse, "qty": qty})
        for warehouse, qty in sorted(sent.items()) if qty > 0
    ]
    targets = " and ".join(f"{a.payload['to_location']} ({a.payload['qty']})" for a in actions)
    return Option(
        strategy="A",
        title=f"Transfer {hub_units:,} hub units to {targets}: the plants that run out first",
        actions=actions,
        cost_eur=round(sum(a.cost_eur for a in actions), 2),
        covered_units=0,  # moves stock between plants, adds none: the shortfall is pooled
        feasible=bool(actions),
        rejected_because=None if actions else "No hub stock to transfer.",
        evidence_ids=["structured/inventory.csv", "config/policies.json"],
    )


# ---------------------------------------------------------------------------
# B: expedite an open order of another supplier
# ---------------------------------------------------------------------------
def expedite_options(component: str, delayed_supplier: str, delayed_day: int) -> list[Option]:
    pos = table("purchase_orders")
    open_pos = pos[(pos["component_id"] == component) & (pos["status"] == "open")
                   & (pos["supplier_id"] != delayed_supplier)]
    options = []
    for po in open_pos.itertuples():
        promised_day = (po.promised_date - scenario_day()).days
        if po.expedite_allowed != "yes" or not po.expedite_days_gain:
            options.append(Option(strategy="B", title=f"Expedite {po.po_id}", feasible=False,
                                  rejected_because=f"{po.po_id} cannot be expedited.", evidence_ids=[po.po_id]))
            continue
        new_day = max(0, promised_day - int(po.expedite_days_gain))
        fee = round(po.qty * po.unit_price_eur * po.expedite_fee_pct / 100, 2)
        options.append(Option(
            strategy="B",
            title=(f"Expedite {po.po_id} ({po.supplier_id}, {po.qty:,} units): day {promised_day} -> day {new_day}, "
                   f"fee {po.expedite_fee_pct:g}%"),
            actions=[Action(operation="expedite_purchase_order", cost_eur=fee,
                            payload={"po_id": po.po_id, "days_gain": int(po.expedite_days_gain),
                                     "fee_pct": float(po.expedite_fee_pct)})],
            cost_eur=fee,
            covered_units=int(po.qty) if new_day < delayed_day else 0,
            evidence_ids=[po.po_id, "structured/purchase_orders.csv"],
        ))
    return options


# ---------------------------------------------------------------------------
# C: buy from an alternative supplier
# ---------------------------------------------------------------------------
def supplier_candidates(component: str, delayed_supplier: str, delayed_day: int) -> pd.DataFrame:
    """Every other supplier of the component, with the checks that decide if we may use it."""
    offers = table("supplier_components")
    offers = offers[(offers["component_id"] == component) & (offers["supplier_id"] != delayed_supplier)]
    suppliers = table("suppliers").set_index("supplier_id")
    day = scenario_day()
    upstream_of_delayed = suppliers["upstream_manufacturer_id"].get(delayed_supplier)

    rows = []
    for offer in offers.itertuples():
        s = suppliers.loc[offer.supplier_id]
        cert_ok = s["certification_status"] == "valid" and pd.notna(s["certification_expiry"]) \
            and s["certification_expiry"] >= day
        shares = pd.notna(upstream_of_delayed) and s["upstream_manufacturer_id"] == upstream_of_delayed
        reason = None
        if not cert_ok:
            reason = (f"{s['certification']} expired {s['certification_expiry']:%Y-%m-%d}: "
                      "policy requires a valid certification.")
        elif offer.lead_time_days >= delayed_day:
            reason = (f"Too slow: {offer.lead_time_days}-day lead time, arrives day {offer.lead_time_days}, "
                      f"not before the delayed delivery (day {delayed_day}).")
        rows.append({
            "supplier_id": offer.supplier_id, "name": s["name"], "price": float(offer.unit_price_eur),
            "lead_time": int(offer.lead_time_days), "capacity": int(offer.monthly_capacity_units),
            "moq": int(offer.moq_units), "shares_upstream": bool(shares),
            "upstream": s["upstream_manufacturer_id"], "rejected_because": reason,
        })
    return pd.DataFrame(rows)


def capacity_from_checks(state: CaseState, supplier_id: str, capacity: int) -> int:
    """Use the lower capacity if role 4's checks found one (e.g. Helios: 1,500 in the e-mail)."""
    for check in state.supplier_checks:
        if check.supplier_id == supplier_id and check.monthly_capacity:
            capacity = min(capacity, check.monthly_capacity)
    return capacity


def purchase_option(component: str, supplier: dict, qty: int, capacity: int, why: str) -> Option:
    delivery = scenario_day() + timedelta(days=supplier["lead_time"])
    cost = round(qty * supplier["price"], 2)
    over = qty > capacity
    return Option(
        strategy="C",
        title=(f"Buy {qty:,} from {supplier['name']} ({supplier['supplier_id']}), EUR {supplier['price']:.2f}, "
               f"{supplier['lead_time']} days{why}"),
        actions=[Action(operation="create_purchase_order", cost_eur=cost,
                        payload={"supplier_id": supplier["supplier_id"], "component_id": component, "qty": qty,
                                 "unit_price_eur": supplier["price"],
                                 "requested_delivery_date": delivery.strftime("%Y-%m-%d")})],
        cost_eur=cost,
        covered_units=min(qty, capacity),
        feasible=not over,
        rejected_because=f"{qty:,} units exceed the monthly capacity of {capacity:,}." if over else None,
        evidence_ids=[supplier["supplier_id"], "structured/supplier_components.csv", "structured/suppliers.csv"],
    )


# ---------------------------------------------------------------------------
# The whole comparison
# ---------------------------------------------------------------------------
def build_options(state: CaseState) -> tuple[list[Option], Recommendation]:
    facts, impact = state.facts, state.impact
    component = facts.component_id.strip().upper()
    change = read_change(state.requested_change)
    delivery = delayed_delivery(facts.supplier_id, component, facts.delay_days or 0)
    delayed_day = delivery["delayed_day"]

    # A and B
    transfer = transfer_option(component, state)
    expedites = expedite_options(component, facts.supplier_id, delayed_day)
    best_expedite = max((o for o in expedites if o.feasible and o.covered_units),
                        key=lambda o: o.covered_units, default=None)

    # C: rejected suppliers, valid independent ones, valid ones sharing the upstream
    candidates = supplier_candidates(component, facts.supplier_id, delayed_day)
    rejected = [
        Option(strategy="C", title=f"Buy from {c['name']} ({c['supplier_id']})", feasible=False,
               rejected_because=c["rejected_because"], evidence_ids=[c["supplier_id"]])
        for c in candidates.to_dict("records") if isinstance(c["rejected_because"], str)
    ]
    valid = candidates[candidates["rejected_because"].isna()] if len(candidates) else candidates
    independent = valid[~valid["shares_upstream"]].sort_values("price") if len(valid) else valid
    sharing = valid[valid["shares_upstream"]].sort_values("price") if len(valid) else valid

    remaining = impact.shortfall_units - (best_expedite.covered_units if best_expedite else 0)

    # The main purchase: the cheapest independent supplier, or the one the user asked for.
    pool = valid if change.get("supplier_id") else independent
    if change.get("supplier_id"):
        pool = candidates[candidates["supplier_id"] == change["supplier_id"]]
    purchases: list[Option] = []
    if len(pool) and remaining > 0:
        main = pool.iloc[0].to_dict()
        capacity = capacity_from_checks(state, main["supplier_id"], main["capacity"])
        qty = int(change.get("qty") or max(main["moq"], min(remaining, capacity)))
        purchase = purchase_option(component, main, qty, capacity,
                                   ": the user's change" if change else ": independent upstream")
        if isinstance(main.get("rejected_because"), str):
            purchase.feasible, purchase.rejected_because = False, main["rejected_because"]
        purchases.append(purchase)
        remaining -= purchase.covered_units

    # Golden "plan 2": cover the rest from a supplier that shares the upstream (weak diversification).
    shared_option = None
    if remaining > 0 and len(sharing):
        other = sharing.iloc[0].to_dict()
        qty = max(other["moq"], min(remaining, capacity_from_checks(state, other["supplier_id"], other["capacity"])))
        shared_option = purchase_option(component, other, qty, other["capacity"],
                                        f": covers the rest, but shares upstream {other['upstream']} "
                                        f"with {facts.supplier_id} (weak diversification)")

    # D and E: what to do with units nobody can deliver in time (no purchase, no cost)
    uncovered = max(0, remaining)
    residual = []
    if uncovered:
        days = uncovered / impact.daily_demand if impact.daily_demand else 0
        residual = [
            Option(strategy="D", title=f"Reallocate the last {uncovered:,} units to tier-1 customer orders",
                   uncovered_units=uncovered, evidence_ids=["structured/customer_orders.csv"]),
            Option(strategy="E", title=f"Reschedule production for ~{days:.1f} days of demand ({uncovered:,} units)",
                   uncovered_units=uncovered, evidence_ids=["structured/production_schedule.csv"]),
        ]

    chosen = [o for o in [transfer, best_expedite, *purchases] if o is not None and o.actions]
    total = round(sum(o.cost_eur for o in chosen), 2)
    cap = change.get("spending_cap_eur") or facts.spending_cap_eur
    summary = "; ".join(o.title for o in chosen) or "No feasible action found."
    if change:
        summary += f". Changed at the approval: {change}."
    recommendation = Recommendation(
        summary=summary,
        options=chosen,
        total_cost_eur=total,
        uncovered_units=uncovered,
        residual_handling=(f"{uncovered:,} units (~{uncovered / impact.daily_demand:.1f} days of demand): "
                           "reschedule production (E) or reallocate to tier-1 orders (D)"
                           + (f"; or {shared_option.title.split(':')[0]} for EUR {shared_option.cost_eur:,.0f}"
                              if shared_option else "")) if uncovered else None,
    )
    if total > cap:
        recommendation.summary += f" WARNING: EUR {total:,.0f} exceeds the cap of EUR {cap:,.0f}."

    all_options = [transfer, *expedites, *purchases, *([shared_option] if shared_option else []),
                   *rejected, *residual]
    return all_options, recommendation