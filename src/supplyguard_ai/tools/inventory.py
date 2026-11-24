"""INVENTORY: how much stock is really usable. OWNER: role 2 (calculations).

Physical stock is not usable stock (the trap in the assignment):
    usable = on_hand - reserved - quarantined          per location, then summed

  - The NUMBERS come from inventory (columns on_hand, reserved, quarantined), which has
    them for every component and location.
  - The REASONS come from reservations (which customer order holds the stock) and
    quarantine_lots (which lot failed inspection). Those two tables only have rows for
    some components (today: MC-17). Where they exist, we also check that they agree
    with the inventory columns, and warn if they don't.

Plain Python, no LLM: the same input always gives the same numbers.
"""

import pandas as pd

from supplyguard_ai.config import policies
from supplyguard_ai.tools.tables import table

STALE_AFTER_DAYS = 180  # an inventory count older than this is not trusted blindly


def usable_stock(component_id: str) -> dict:
    """How much of a component we can really use, and why the rest is not usable.

    Returns (keys used by impact.py, plus explanations):
      on_hand, reserved, quarantined, usable     totals over all locations
      by_location        {"W-STU": 1300, ...}    usable units per location
      reserved_for       [{"customer_order_id", "location_id", "qty"}]
      quarantine_lots    [{"lot_id", "location_id", "qty", "reason"}]
      warnings           data problems found (stale counts, disagreeing tables)
      source_ids         where the numbers come from
    """
    component_id = component_id.strip().upper()
    inventory = table("inventory")
    rows = inventory[inventory["component_id"] == component_id]
    warnings: list[str] = []

    if rows.empty:
        warnings.append(f"No inventory records for {component_id}.")

    # 1. Usable per location: what is physically there minus what we may not touch.
    #    clip(lower=0): never count negative stock, even if a row is inconsistent.
    usable_per_row = (rows["on_hand"] - rows["reserved"] - rows["quarantined"]).clip(lower=0)
    by_location = {
        location: int(units) for location, units in zip(rows["location_id"], usable_per_row)
    }

    # 2. Why stock is reserved: the customer orders holding it.
    reservations = table("reservations")
    reservations = reservations[reservations["component_id"] == component_id]
    reserved_for = [
        {"customer_order_id": r.customer_order_id, "location_id": r.location_id, "qty": int(r.reserved_qty)}
        for r in reservations.itertuples()
    ]

    # 3. Why stock is quarantined: the lots that failed inspection.
    lots = table("quarantine_lots")
    lots = lots[lots["component_id"] == component_id]
    quarantine_lots = [
        {"lot_id": r.lot_id, "location_id": r.location_id, "qty": int(r.qty), "reason": r.reason}
        for r in lots.itertuples()
    ]

    # 4. Cross-checks: the detail tables must agree with the inventory columns.
    warnings += _compare("reserved", rows, reservations, "reserved_qty")
    warnings += _compare("quarantined", rows, lots, "qty")

    # 5. Stale counts: measured from the scenario date in policies.json.
    day = pd.Timestamp(policies()["scenario_date"])
    stale = rows[rows["last_counted_date"] < day - pd.Timedelta(days=STALE_AFTER_DAYS)]
    for r in stale.itertuples():
        warnings.append(
            f"{component_id} at {r.location_id}: last counted {r.last_counted_date:%Y-%m-%d}, "
            f"more than {STALE_AFTER_DAYS} days ago; the stock figure may be wrong."
        )

    return {
        "on_hand": int(rows["on_hand"].sum()),
        "reserved": int(rows["reserved"].sum()),
        "quarantined": int(rows["quarantined"].sum()),
        "usable": int(usable_per_row.sum()),
        "by_location": by_location,
        "reserved_for": reserved_for,
        "quarantine_lots": quarantine_lots,
        "warnings": warnings,
        "source_ids": ["structured/inventory.csv", "structured/reservations.csv",
                       "structured/quarantine_lots.csv"],
    }


def _compare(what: str, rows: pd.DataFrame, details: pd.DataFrame, qty_column: str) -> list[str]:
    """Warn where a detail table (reservations / quarantine_lots) disagrees with inventory.

    Only for locations the detail table mentions: for most components it has no rows,
    and then there is nothing to compare.
    """
    if details.empty:
        return []
    detail_per_location = details.groupby("location_id")[qty_column].sum()
    column_per_location = rows.set_index("location_id")[what]
    warnings = []
    for location, detail_qty in detail_per_location.items():
        column_qty = int(column_per_location.get(location, 0))
        if int(detail_qty) != column_qty:
            warnings.append(
                f"{location}: inventory says {column_qty} {what}, the detail table says {int(detail_qty)}."
            )
    return warnings