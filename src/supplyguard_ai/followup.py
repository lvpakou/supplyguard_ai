"""FOLLOW-UP QUESTIONS after the decision. OWNER: role 5.

Real version (like HelpDesk Lite's followup.py): the LLM answers from a case file built
from the saved state, and recomputes numbers with role 2's tools (e.g. a EUR 90,000 cap).

STUB: a fixed answer. Keep the signature.
"""

from supplyguard_ai.state import CaseState


def answer(state: CaseState, question: str) -> str:
    return f"(stub) I will answer '{question}' from the saved case {state.case_id}."
