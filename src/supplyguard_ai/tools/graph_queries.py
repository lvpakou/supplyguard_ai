"""DEPENDENCY GRAPH: Neo4j queries. OWNER: role 4.

Real version: Neo4j loaded with data/graph/load.cypher (scripts/load_graph.py).
Queries: products/plants/customers using a component, alternative suppliers with price,
lead time and certification, shared upstream manufacturers (Atlas and Delta -> Veltro),
disconnected entities (S058-S060, MC-296..MC-300).

STUB: the golden alternatives for MC-17. Keep the signatures.
"""

from supplyguard_ai.state import SupplierCheck


def alternatives(component_id: str, exclude_supplier: str | None = None) -> list[SupplierCheck]:
    return [
        SupplierCheck(supplier_id="S002", name="Helios Supply", unit_price_eur=7.20, lead_time_days=21,
                      monthly_capacity=1500, notes=["STUB: real capacity 1,500 (e-mail) vs 4,000 (contract)"]),
        SupplierCheck(supplier_id="S003", name="Borealis", lead_time_days=6, certification_valid=False,
                      notes=["STUB: ISO 9001 expired 2026-09-30"]),
        SupplierCheck(supplier_id="S004", name="Cordillera", unit_price_eur=9.80, lead_time_days=9,
                      monthly_capacity=3000),
        SupplierCheck(supplier_id="S005", name="Delta", unit_price_eur=10.40, lead_time_days=8,
                      monthly_capacity=2500, shared_upstream_with=["S001"],
                      notes=["STUB: shares upstream U01 (Veltro) with Atlas"]),
    ]


def shared_upstream(supplier_id: str) -> list[str]:
    """Other suppliers that buy from the same upstream manufacturer."""
    return ["S005"] if supplier_id == "S001" else []


def affected_by(component_id: str) -> dict:
    """{"products": [...], "factories": [...], "customers": [...]} that depend on the component."""
    return {"products": [], "factories": [], "customers": []}
