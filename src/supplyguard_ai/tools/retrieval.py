"""DOCUMENT RETRIEVAL: pgvector, ChromaDB and hybrid search. OWNER: role 3.

Rules for the real version:
  - filter by the user's role (users.csv document_scopes): a viewer only sees 'public';
    only finance_controller sees 'finance-confidential';
  - only the newest version of a document (Atlas contract v3, not v2);
  - every retrieved text goes through guards.check_injection() before an LLM sees it.

STUB: returns no documents and the four golden conflicts. Keep the signatures.
"""

from supplyguard_ai.state import Conflict, Evidence


def search_documents(query: str, user_role: str, filters: dict | None = None, k: int = 5) -> list[Evidence]:
    return []


def find_conflicts(evidence: list[Evidence]) -> list[Conflict]:
    """Sources that disagree, resolved with policies.json source_precedence."""
    return [
        Conflict(topic="Atlas delay", values={"supplier notice": "12 days", "supplier e-mail": "16 days"},
                 chosen="12 days", reason="STUB: supplier notice outranks supplier e-mail"),
        Conflict(topic="Helios capacity", values={"contract": "4,000/month", "e-mail": "1,500/month"},
                 chosen="1,500/month", reason="STUB: role 3 decides with source precedence and recency"),
        Conflict(topic="Cordillera expedite fee", values={"contract": "6%", "e-mail": "10%"},
                 chosen="6%", reason="STUB: contract outranks e-mail"),
        Conflict(topic="Atlas contract version", values={"v2": "10 days", "v3": "14 days"},
                 chosen="v3", reason="STUB: v2 is superseded"),
    ]
