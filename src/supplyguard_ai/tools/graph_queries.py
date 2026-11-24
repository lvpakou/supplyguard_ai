"""DEPENDENCY GRAPH: Neo4j queries. OWNER: role 4.

The graph is loaded from ``data/graph/load.cypher``.  This module contains
read-only queries over that graph; it does not create or modify graph data.
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase

from supplyguard_ai.state import SupplierCheck


# The training data describes the scenario as of this date.  Using the graph's
# effectiveDate for certification checks avoids comparing it with today's date.

def _run_query(query: str, **parameters: Any) -> list[dict[str, Any]]:
    """Run a read-only Cypher query and return its records as dictionaries."""
    load_dotenv()

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7688")
    username = os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD")
    if not password:
        raise RuntimeError(
            "NEO4J_PASSWORD is not set. Add the Neo4j credentials to your .env file."
        )

    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        records, _, _ = driver.execute_query(
            query,
            parameters_=parameters,
            database_=os.getenv("NEO4J_DATABASE", "neo4j"),
        )
        return [record.data() for record in records]


def alternatives(
    component_id: str, exclude_supplier: str | None = None
) -> list[SupplierCheck]:
    """Return approved suppliers that can supply a component.

    Prices and lead times come from SUPPLIES relationships.  Certification
    validity is evaluated against each supplier node's effectiveDate.  The
    graph does not contain monthly capacity, so that field remains None and
    must be obtained from another project source.
    """
    query = """
    MATCH (s:Supplier)-[supply:SUPPLIES]->(c:Component {componentId: $component_id})
    WHERE s.erpStatus = 'approved'
      AND ($exclude_supplier IS NULL OR s.supplierId <> $exclude_supplier)
    OPTIONAL MATCH (s)-[:SOURCES_FROM]->(upstream:Upstream)<-[:SOURCES_FROM]-(other:Supplier)
    WHERE other.supplierId <> s.supplierId
    RETURN s.supplierId AS supplier_id,
           s.name AS name,
           supply.unitPriceEur AS unit_price_eur,
           supply.leadTimeDays AS lead_time_days,
           s.certificationExpiry >= s.effectiveDate AS certification_valid,
           collect(DISTINCT other.supplierId) AS shared_upstream_with,
           s.certificationExpiry AS certification_expiry
    ORDER BY supply.unitPriceEur ASC, supply.leadTimeDays ASC, s.supplierId ASC
    """
    rows = _run_query(
        query,
        component_id=component_id,
        exclude_supplier=exclude_supplier,
    )

    return [
        SupplierCheck(
            supplier_id=row["supplier_id"],
            name=row["name"],
            unit_price_eur=row["unit_price_eur"],
            lead_time_days=row["lead_time_days"],
            monthly_capacity=None,  # Not represented in the Neo4j graph.
            certification_valid=bool(row["certification_valid"]),
            shared_upstream_with=row["shared_upstream_with"] or [],
            notes=(
                [f"Certification expires on {row['certification_expiry']}."]
                if row["certification_expiry"] is not None
                else ["No certification expiry date is recorded in the graph."]
            ),
        )
        for row in rows
    ]


def shared_upstream(supplier_id: str) -> list[str]:
    """Return IDs of other suppliers using any of the same upstream makers."""
    query = """
    MATCH (supplier:Supplier {supplierId: $supplier_id})-[:SOURCES_FROM]->(u:Upstream)
          <-[:SOURCES_FROM]-(other:Supplier)
    WHERE other.supplierId <> supplier.supplierId
    RETURN DISTINCT other.supplierId AS supplier_id
    ORDER BY supplier_id
    """
    rows = _run_query(query, supplier_id=supplier_id)
    return [row["supplier_id"] for row in rows]


def affected_by(component_id: str) -> dict[str, list[str]]:
    """Return product, factory and customer IDs that depend on a component."""
    query = """
    MATCH (component:Component {componentId: $component_id})
    OPTIONAL MATCH (component)-[:USED_IN]->(product:Product)
    OPTIONAL MATCH (product)-[:PRODUCED_AT]->(factory:Factory)
    OPTIONAL MATCH (product)-[:ORDERED_BY]->(customer:Customer)
    RETURN collect(DISTINCT product.productId) AS products,
           collect(DISTINCT factory.factoryId) AS factories,
           collect(DISTINCT customer.customerId) AS customers
    """
    rows = _run_query(query, component_id=component_id)
    if not rows:
        return {"products": [], "factories": [], "customers": []}

    row = rows[0]
    return {
        "products": sorted(value for value in (row["products"] or []) if value),
        "factories": sorted(value for value in (row["factories"] or []) if value),
        "customers": sorted(value for value in (row["customers"] or []) if value),
    }


def orphan_nodes() -> dict[str, list[str]]:
    """Return suppliers with no SUPPLIES edge and components used by no product.

    A component may still have suppliers; it is an orphan for the product
    dependency graph when no product uses it.
    """
    query = """
    MATCH (n)
    WHERE (n:Supplier AND NOT (n)-[:SUPPLIES]-())
       OR (n:Component AND NOT (n)-[:USED_IN]->())
    RETURN labels(n) AS labels,
           coalesce(n.supplierId, n.componentId) AS node_id
    ORDER BY labels, node_id
    """
    rows = _run_query(query)
    result: dict[str, list[str]] = {"suppliers": [], "components": []}
    for row in rows:
        if "Supplier" in row["labels"]:
            result["suppliers"].append(row["node_id"])
        elif "Component" in row["labels"]:
            result["components"].append(row["node_id"])
    return result
