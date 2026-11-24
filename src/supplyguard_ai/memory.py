"""INCIDENT MEMORIES (pgvector, separate table). OWNER: role 3.

similar_cases(): approved past resolutions similar to this incident (structured/approved_incident_memories.jsonl).
save_resolution(): store the approved summary of a closed case for future cases.

STUB: does nothing yet. Keep the signatures.
"""

from supplyguard_ai.state import CaseState


def similar_cases(text: str, k: int = 3) -> list[dict]:
    return []


def save_resolution(state: CaseState) -> None:
    return None
