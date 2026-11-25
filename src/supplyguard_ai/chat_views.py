"""WHAT THE CHAT SHOWS, as short markdown. OWNER: role 5.

Plain functions: the case values in, markdown out (no Chainlit), so they are easy to test.
Each message is a heading plus 2-4 short lines with what matters for the decision. Nothing is
lost: every detail is in the incident report (attached as a file when the case closes), and
the user can ask for any detail; the follow-up answers read the whole saved case.
Nothing here calculates or retrieves: it only shows what the case state already holds.
"""

import re

from supplyguard_ai.approval import describe   # the exact action text, as in the audit
from supplyguard_ai.state import ApprovalRequest, Evidence

# The workflow steps: what the user sees while a step runs, and once it is done.
STEPS = {
    "intake": ("Reading your message", "message read"),
    "impact": ("Calculating the impact", "impact"),
    "evidence": ("Reading documents and contracts", "documents"),
    "dependencies": ("Checking alternative suppliers", "suppliers"),
    "options": ("Costing recovery options", "options"),
    "challenge": ("Checking the plan against the policies", "policy check"),
    "execute": ("Sending the approved actions", "actions executed"),
    "report": ("Writing the incident report", "report written"),
}
_TYPES = {"contract": "contracts", "qualification": "certificates", "supplier_notice": "notices",
          "email": "e-mails", "procedure": "procedures", "incident_report": "incident reports",
          "incident_memory": "past cases", "finance": "finance"}
_OPERATIONS = {"request_stock_transfer": "Stock transfer", "expedite_purchase_order": "Expedite order",
               "create_purchase_order": "New purchase order", "update_production_schedule": "Production plan"}
REPORT_FILE = "incident-report.md"


def _cell(value) -> str:
    """Text that is safe inside a markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _role(role: str) -> str:
    return role.replace("_", " ")


def _count(n: int, word: str) -> str:
    """2 sources, 1 source"""
    return f"{n} {word if n == 1 else word + 's'}"


def documents(values: dict) -> list[Evidence]:
    """The case's evidence, once per source (a contract and the agent's note on it count once)."""
    first: dict[str, Evidence] = {}
    for e in values.get("evidence", []):
        first.setdefault(e.source_id, e)
    return list(first.values())


def progress_view(started: list[str], finished: bool = False) -> str:
    """One line, updated in place: the running step, then a summary of what was done."""
    if finished:
        return "✓ " + " · ".join(STEPS.get(s, (s, s))[1] for s in started)
    return f"⏳ {STEPS.get(started[-1], (started[-1], ''))[0]}…"


def impact_view(values: dict) -> str:
    i = values.get("impact")
    if not i:
        return ""
    # "F3 (W-LYO)": 3.3 -> the warehouse that runs out first comes first
    first = sorted(i.days_of_cover.items(), key=lambda item: item[1])
    runs_out = " · ".join(f"{plant.split('(')[-1].rstrip(')')} in {days:.1f} days" for plant, days in first)
    stockout = f" (first stockout: day {i.first_stockout_day})" if i.first_stockout_day is not None else ""
    return "\n".join([
        "### 📊 Impact",
        f"- **{i.usable:,} of {i.on_hand:,} {i.component_id} units are usable** "
        f"({i.reserved:,} reserved for orders, {i.quarantined:,} quarantined).",
        f"- **Shortfall: {i.shortfall_units:,} units** before the delayed delivery{stockout}. "
        f"Runs out: {runs_out}.",
        f"- **{i.open_orders_at_risk} customer orders at risk** on {len(i.affected_products)} products; "
        f"revenue exposed: EUR {i.revenue_at_risk_eur or 0:,.0f} (not a cost).",
    ])


def evidence_view(values: dict) -> str:
    conflicts, warnings, docs = values.get("conflicts", []), values.get("warnings", []), documents(values)
    if not (conflicts or warnings or docs):
        return ""
    lines = ["### 📄 Evidence"]
    if docs:
        counts: dict[str, int] = {}
        for e in docs:
            kind = _TYPES.get(e.doc_type, e.doc_type)
            counts[kind] = counts.get(kind, 0) + 1
        lines.append(f"- **{_count(len(docs), 'source')} read**, filtered by your role: "
                     + ", ".join(f"{n} {kind}" for kind, n in counts.items()) + ".")
    if conflicts:
        settled = " · ".join(f"{c.topic}: **{c.chosen}**" for c in conflicts)
        lines.append(f"- **{_count(len(conflicts), 'conflict')} between sources settled** (contract > certificate > notice > "
                     f"e-mail): {settled}.")
    lines += [f"- ⚠️ {_warning(w)}" for w in warnings]
    return "\n".join(lines)


def _warning(w: str) -> str:
    """A warning without the quoted injected words (never repeat them), brackets balanced:
    "Ignored DOC-X: suspicious instruction (overrides our instructions): 'ignore all ...'"
    -> "Ignored DOC-X: suspicious instruction (overrides our instructions)" """
    short = re.sub(r":\s*'.*'\)*$", "", w)
    return short + ")" * (short.count("(") - short.count(")"))


def options_view(values: dict) -> str:
    options, rec, facts = values.get("options", []), values.get("recommendation"), values.get("facts")
    if not options or not rec:
        return ""
    budget = f" (budget EUR {facts.spending_cap_eur:,.0f})" if facts else ""
    lines = ["### ⚖️ Recovery options",
             f"- **Plan: EUR {rec.total_cost_eur:,.0f}**{budget}, combining {len(rec.options)} of "
             f"{len(options)} options. The exact actions are in the approval below."]
    if rec.uncovered_units:
        lines.append(f"- **Still uncovered:** {rec.residual_handling or f'{rec.uncovered_units:,} units'}")
    lines += [f"- ❌ {o.title.removeprefix('Buy from ')}: {o.rejected_because}"
              for o in options if not o.feasible and o.rejected_because]
    lines += [f"- ⚠️ {c.name} ({c.supplier_id}) shares an upstream manufacturer with "
              f"{', '.join(c.shared_upstream_with)}: no real diversification."
              for c in values.get("supplier_checks", []) if c.shared_upstream_with]
    lines += [f"- 🌐 Risk alert {n}" for n in values.get("investigation_notes", []) if not n.startswith("[Deep Agent]")]
    return "\n".join(lines)


def approval_view(values: dict, request: ApprovalRequest, roles: list[str], missing: list[str]) -> str:
    """The exact actions the human approves, the policy checks, and who still has to sign."""
    rec, facts = values["recommendation"], values.get("facts")
    actions = [a for option in rec.options for a in option.actions]
    budget = f" (budget EUR {facts.spending_cap_eur:,.0f})" if facts else ""
    lines = [f"### ✍️ Approve EUR {request.total_cost_eur:,.0f}?",
             "| # | Action | EUR |", "|---|---|---:|"]
    lines += [f"| {n} | {_cell(describe(a))} | {a.cost_eur:,.0f} |" for n, a in enumerate(actions, 1)]
    lines += [f"| | **Total**{budget} | **{request.total_cost_eur:,.0f}** |", ""]
    # The policy check's findings, without the two already on screen (sign-off below, uncovered units above).
    risks = [f for f in values.get("critique", []) if "needs BOTH" not in f and "stay uncovered" not in f]
    if risks:
        lines += ["**Risks you accept by approving:**"] + [f"- 🔎 {finding}" for finding in risks] + [""]
    signoff = " · ".join(f"{_role(r)} {'⏳' if r in missing else '✅'}" for r in roles) or "nobody: above every tier"
    lines += [f"- **Sign-off:** {signoff}", "",
              "_Nothing is ordered until everyone has approved; a change needs a new approval. Ask me anything "
              f"first, e.g. “Why not Helios?”. Approval `{request.approval_id}`._"]
    return "\n".join(lines)


def closing_view(values: dict) -> str:
    """What was decided and done; the full report is attached as a file."""
    approval, executions = values.get("approval"), values.get("executions", [])
    if approval and approval.status == "approved":
        lines = [f"### ✅ Approved and executed: EUR {approval.total_cost_eur:,.0f}"]
    elif approval:
        lines = [f"### ❌ {approval.status.capitalize()}: nothing was executed"]
    else:
        lines = ["### 📄 Case closed without a plan"]
    lines += [f"- {_OPERATIONS.get(e.operation, e.operation)}: {e.status} ({e.reference or e.message})"
              for e in executions]
    lines += ["", f"📎 The full incident report is attached ({REPORT_FILE}). "
                  "_Ask a follow-up, or type **new** for a new case._"]
    return "\n".join(lines)
