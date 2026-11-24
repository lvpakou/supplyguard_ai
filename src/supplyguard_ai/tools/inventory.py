"""INVENTORY: how much stock is really usable. OWNER: role 2 (calculations).

STUB: returns the trainer's golden numbers for MC-17 (data/evaluation/golden_scenario.json).
Replace with a real calculation over structured/inventory.csv, reservations.csv and
quarantine_lots.csv (loaded into Postgres by scripts/load_postgres.py). Keep the signature.
"""

from supplyguard_ai.config import golden_scenario


def usable_stock(component_id: str) -> dict:
    """{"on_hand", "reserved", "quarantined", "usable", "by_location": {location: usable}}."""
    gold = golden_scenario()
    if component_id != gold["facts"]["component"]:
        raise NotImplementedError(f"STUB: only {gold['facts']['component']} until role 2 builds it")
    inv = gold["mc17_inventory"]
    return {**inv, "by_location": gold["usable_by_location"]}
