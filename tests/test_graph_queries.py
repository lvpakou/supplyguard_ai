from supplyguard_ai.tools.graph_queries import (
    alternatives,
    shared_upstream,
    affected_by,
    orphan_nodes,
)

print(alternatives("MC-17", exclude_supplier="S001"))

print(shared_upstream("S001"))

print(affected_by("MC-17"))

print(orphan_nodes())