"""NODES: the steps of the incident workflow. OWNER: role 1.

A node takes the CaseState and returns a dict with only the fields it changes.
Nodes stay thin: the real work lives in each role's module (tools/, agents/,
integrations/, approval.py, report.py ...). Other roles change THEIR modules,
not this file.

interrupt() rule (same as HelpDesk Lite): when the graph resumes, the node runs again
from the top, so nothing before interrupt() may have side effects.
"""

import csv
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from supplyguard_ai import approval as approval_rules
from supplyguard_ai import followup as followup_answers
from supplyguard_ai.agents.contract_agent import analyze_contracts
from supplyguard_ai.agents.investigator import investigate
from supplyguard_ai.config import data_dir
from supplyguard_ai.integrations import procurement, risk
from supplyguard_ai.llm import get_llm
from supplyguard_ai.memory import save_resolution
from supplyguard_ai.report import build_report
from supplyguard_ai.state import CaseState, Clarification, FollowUp, IncidentFacts
from supplyguard_ai.tools import critic, guards
from supplyguard_ai.tools.graph_queries import alternatives
from supplyguard_ai.tools.impact import assess_impact
from supplyguard_ai.tools.options import build_options
from supplyguard_ai.tools.retrieval import find_conflicts, search_documents

INTAKE_PROMPT = """\
You are the intake step of SupplyGuard AI, used by procurement managers of a European \
manufacturer. Extract the facts of the supply disruption from the user's message into \
the schema. The text may also contain our clarification questions and the user's answers; \
treat the answers as facts, the latest answer wins.
Rules: use only what is written; never guess IDs; leave unknown fields null. \
If the spending limit is stated, put it in spending_cap_eur (EUR)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@lru_cache
def _suppliers() -> list[dict]:
    with (data_dir() / "structured" / "suppliers.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def resolve_supplier(facts: IncidentFacts) -> IncidentFacts:
    """Turn the supplier name into an ID with suppliers.csv; flag ambiguous names.

    'Atlas Components' -> S001. 'Atlas' alone matches S001 and S006 (Atlas Logistik): ask.
    """
    if facts.supplier_id or not facts.supplier_name:
        return facts
    name = facts.supplier_name.strip().lower()
    exact = [s for s in _suppliers() if s["name"].lower() == name]
    matches = exact or [s for s in _suppliers() if name in s["name"].lower()]
    if len(matches) == 1:
        return facts.model_copy(update={"supplier_id": matches[0]["supplier_id"]})
    if len(matches) > 1:
        names = " or ".join(f"{s['name']} ({s['supplier_id']})" for s in matches)
        return facts.model_copy(update={"ambiguities": facts.ambiguities + [f"'{facts.supplier_name}' could be {names}"]})
    return facts


def _text_for_intake(state: CaseState) -> str:
    if not state.clarifications:
        return state.raw_text
    lines = ["Original message:", state.raw_text, "", "Clarifications:"]
    for item in state.clarifications:
        lines += [f"Q: {item.question}", f"A: {item.answer}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def intake(state: CaseState) -> dict:
    """Extract the facts (LLM, structured output) and decide what is still unclear."""
    extractor = get_llm().with_structured_output(IncidentFacts)
    facts = extractor.invoke([SystemMessage(INTAKE_PROMPT), HumanMessage(_text_for_intake(state))])
    facts = resolve_supplier(facts)
    unclear = list(facts.ambiguities)
    if not facts.supplier_id and not unclear:
        unclear.append("Which supplier is affected (name or ID)?")
    if not facts.component_id:
        unclear.append("Which component is delayed (e.g. MC-17)?")
    if facts.delay_days is None:
        unclear.append("How many days is the delay?")
    return {"facts": facts, "needs_clarification": unclear}


def clarify(state: CaseState) -> dict:
    """Pause and ask the user; the answer goes back to intake."""
    question = "Before I investigate, please clarify:\n" + "\n".join(f"- {q}" for q in state.needs_clarification)
    answer = interrupt({"type": "clarification", "question": question})
    return {"clarifications": state.clarifications + [Clarification(question=question, answer=str(answer))]}


def impact(state: CaseState) -> dict:
    try:
        return {"impact": assess_impact(state.facts)}
    except NotImplementedError as error:  # a stub that only knows MC-17
        return {"warnings": state.warnings + [f"Impact not calculated: {error}"]}


def evidence(state: CaseState) -> dict:
    """Documents (role 3) + injection guard (role 5) + contract agent (role 3)."""
    facts = state.facts
    query = f"{facts.supplier_name or ''} {facts.component_id or ''} delay contract capacity certification"
    found, warnings = [], list(state.warnings)
    for item in search_documents(query, state.user_role):
        reason = guards.check_injection(item.claim)
        if reason:  # reported and ignored, never followed
            warnings.append(f"Ignored {item.source_id}: {reason}")
        else:
            found.append(item)
    supplier_ids = [s for s in [facts.supplier_id] if s]
    found += analyze_contracts(facts, supplier_ids, state.user_role)
    return {"evidence": found, "conflicts": find_conflicts(found), "warnings": warnings}


def dependencies(state: CaseState) -> dict:
    """Alternatives from the graph (role 4), external risk alerts, Deep Agent notes."""
    checks = alternatives(state.facts.component_id, exclude_supplier=state.facts.supplier_id)
    alerts = [f"[{a['region']}] {a['text']}" for a in risk.get_alerts() if a.get("severity") == "high"]
    notes = investigate(state.facts, checks) + alerts
    return {"supplier_checks": checks, "investigation_notes": notes}


def options(state: CaseState) -> dict:
    all_options, recommendation = build_options(state)
    return {"options": all_options, "recommendation": recommendation}


def challenge(state: CaseState) -> dict:
    return {"critique": critic.review(state)}


APPROVE_WORDS = {"approve", "approved", "yes", "ok"}
REJECT_WORDS = {"reject", "rejected", "no"}


def approval(state: CaseState) -> dict:
    """Pause for the human decision on the EXACT payload (no purchase before this).

    What the chat may send back (role 5):
      "approve" / "reject"                          -> the decision
      {"decision": "change", "qty": 6000, ...}      -> keep the change in requested_change and
      "change ..." (free text)                         go back to options: new plan, new hash,
                                                       new approval (approval binds to the payload)
      anything else, e.g. "Why not Helios?"         -> a question: answered, and we keep waiting
                                                       (a question must never count as a reject)
    """
    request = approval_rules.build_request(state.case_id, state.recommendation)
    decision = interrupt({"type": "approval", "request": request.model_dump(),
                          "summary": state.recommendation.summary})

    if isinstance(decision, dict):
        text = str(decision.get("decision", "")).strip()
        details = {k: v for k, v in decision.items() if k != "decision"}
    else:
        text, details = str(decision).strip(), {}
    word = text.lower().strip(".!")

    def decided(status: str, change: dict | None = None) -> dict:
        return {"approval": request.model_copy(update={"status": status, "decided_by": state.user_id}),
                "requested_change": change}

    if word in APPROVE_WORDS:
        return decided("approved")
    if word in REJECT_WORDS:
        return decided("rejected")
    if word.startswith("change"):
        return decided("changed", details or {"note": text})
    # A question about the proposal: answer it and wait for the decision again.
    answer = followup_answers.answer(state, text)
    return {"approval": request, "followups": state.followups + [FollowUp(question=text, answer=answer)]}


def execute(state: CaseState) -> dict:
    """Run the approved actions on the procurement system, each once (idempotency key)."""
    results = []
    actions = [a for option in state.recommendation.options for a in option.actions]
    for step, action in enumerate(actions):
        key = f"{state.case_id}:{step}:{action.operation}"
        results.append(procurement.execute(action, state.approval.approval_id, key))
    return {"executions": results}


def report(state: CaseState) -> dict:
    if state.approval and state.approval.status == "approved":
        save_resolution(state)
    return {"report": build_report(state)}


def followup(state: CaseState) -> dict:
    question = interrupt({"type": "followup"})
    text = str(question).strip()
    return {"followups": state.followups + [FollowUp(question=text, answer=followup_answers.answer(state, text))]}
