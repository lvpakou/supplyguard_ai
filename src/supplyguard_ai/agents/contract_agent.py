"""CONTRACT AGENT: a bounded specialist built with create_agent. OWNER: role 3.

Real version: langchain.agents.create_agent(model=get_llm(), tools=[search_documents...],
system_prompt=...) that answers: which contract version applies, expedite fee, capacity,
penalties - always with source_id and effective date.

STUB: no findings yet. Keep the signature.
"""

from supplyguard_ai.state import Evidence, IncidentFacts


def analyze_contracts(facts: IncidentFacts, supplier_ids: list[str], user_role: str) -> list[Evidence]:
    return []
