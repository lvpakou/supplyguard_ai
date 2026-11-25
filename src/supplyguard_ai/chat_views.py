"""WHAT THE CHAT SHOWS, as short markdown. OWNER: role 5.

Plain functions: the case values in, markdown out (no Chainlit), so they are easy to test.
Every message has the same shape: a heading with the takeaway, a few short facts, and one
line in italics that says what it means or what happens next. Long material (the documents,
supplier details, the Deep Agent's notes, the full report) goes to the side panel: the
message names it and one click opens it, so nothing is lost.
Nothing here calculates or retrieves: it only shows what the case state already holds.
"""

from supplyguard_ai.approval import describe   # the exact action text, as in the audit
from supplyguard_ai.config import policies
from supplyguard_ai.state import ApprovalRequest, Evidence

# The workflow steps, in words a procurement manager understands (shown while the case runs).
STEPS = {
    "intake": "Read your message: supplier, component, delay, budget",
    "impact": "Impact on stock, products and customer orders",
    "evidence": "Documents, past incidents and contracts",
    "dependencies": "Alternative suppliers and their upstream risks",
    "options": "Recovery options, costed",
    "challenge": "Plan checked against the policies",
    "execute": "Approved actions sent to the procurement system",
    "report": "Incident report written",
}
_TYPES = {"contract": "Contracts", "qualification": "Certificates", "supplier_notice": "Supplier notices",
          "email": "E-mails", "procedure": "Procedures", "incident_report": "Incident reports",
          "incident_memory": "Similar past cases", "finance": "Finance"}
_OPERATIONS = {"request_stock_transfer": "Stock transfer", "expedite_purchase_order": "Expedite order",
               "create_purchase_order": "New purchase order", "update_production_schedule": "Production plan"}
SUPPLIER_DETAILS, AGENT_NOTES, CONTRACT_NOTES, REPORT = (
    "Supplier details", "Deep Agent notes", "Contract agent notes", "Incident report")


def _cell(value) -> str:
    """Text that is safe inside a markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _num(value, fmt: str = ",.0f") -> str:
    return "–" if value is None else format(value, fmt)


def _source(path: str) -> str:
    """structured/inventory.csv -> inventory"""
    return path.removeprefix("structured/").removesuffix(".csv")


def documents(values: dict) -> list[Evidence]:
    """The case's evidence, once per source: the first item, i.e. the retrieved document itself,
    not a later summary of it (a contract finding or a contract-agent note with the same source)."""
    first: dict[str, Evidence] = {}
    for e in values.get("evidence", []):
        first.setdefault(e.source_id, e)
    return list(first.values())


def side_panels(values: dict) -> dict[str, str]:
    """Long material for the side panel, by the name a message uses for it."""
    panels = {e.source_id: e.claim for e in documents(values)}
    checks = values.get("supplier_checks", [])
    if checks:
        panels[SUPPLIER_DETAILS] = "\n\n".join(
            f"**{c.supplier_id} {c.name}**\n" + ("\n".join(f"- {n}" for n in c.notes + c.risk_alerts) or "- no notes")
            for c in checks)
    notes = [n for n in values.get("investigation_notes", []) if n.startswith("[Deep Agent]")]
    if notes:
        panels[AGENT_NOTES] = "\n\n".join(f"- {n.removeprefix('[Deep Agent] ')}" for n in notes)
    contract_notes = [e.claim for e in values.get("evidence", []) if e.doc_type == "contract_agent_note"]
    if contract_notes:
        panels[CONTRACT_NOTES] = "\n\n".join(f"- {n.removeprefix('Contract agent, ')}" for n in contract_notes)
    if values.get("report"):
        panels[REPORT] = values["report"]
    return panels


def progress_view(started: list[str], finished: bool = False) -> str:
    """One checklist that grows while the case runs: done steps ✓, the running one ⏳."""
    lines = []
    for index, step in enumerate(started):
        running = index == len(started) - 1 and not finished
        lines.append(f"- {'⏳' if running else '✓'} {STEPS.get(step, step)}{'…' if running else ''}")
    return "\n".join(lines)


def impact_view(values: dict) -> str:
    i = values.get("impact")
    if not i:
        return ""
    # "F2 (W-KAT)": 4.0  ->  "W-KAT": ("F2", 4.0); the warehouse that runs out first comes first
    cover = {plant.split("(")[-1].rstrip(")"): (plant.split(" (")[0], days) for plant, days in i.days_of_cover.items()}
    rows = sorted(i.usable_by_location.items(), key=lambda item: cover.get(item[0], ("", float("inf")))[1])
    lines = ["### 📊 Impact",
             f"**{i.usable:,} of {i.on_hand:,} {i.component_id} units are usable.** "
             f"{i.reserved:,} are reserved for customer orders, {i.quarantined:,} are quarantined.", "",
             "| Warehouse | Usable units | Runs out in |", "|---|---:|---:|"]
    for location, units in rows:
        plant, days = cover.get(location, ("hub, for transfers", None))
        lines.append(f"| {location} ({plant}) | {units:,} | {'–' if days is None else f'{days:.1f} days'} |")
    stockout = f"day {i.first_stockout_day}" if i.first_stockout_day is not None else "none before the delivery"
    lines += ["",
              f"- **Shortfall: {i.shortfall_units:,} units** until the delayed delivery arrives "
              f"(demand {i.daily_demand:,} units/day; first stockout: {stockout}).",
              f"- **At risk: {i.open_orders_at_risk} open customer orders** on {len(i.affected_products)} products "
              f"({', '.join(i.affected_products)}).",
              f"- **Revenue at risk: EUR {_num(i.revenue_at_risk_eur)}**: what is exposed if nothing is done. "
              "It is not a cost and is never added to the recovery cost.",
              "", f"_Calculated from: {', '.join(_source(s) for s in i.source_ids)}._"]
    return "\n".join(lines)


def evidence_view(values: dict) -> str:
    conflicts, warnings, docs = values.get("conflicts", []), values.get("warnings", []), documents(values)
    notes = [e for e in values.get("evidence", []) if e.doc_type == "contract_agent_note"]
    if not (conflicts or warnings or docs):
        return ""
    lines = ["### 📄 Evidence"]
    if conflicts:
        rule = " > ".join(policies()["source_precedence"])
        count = f"{len(conflicts)} conflict{'s' if len(conflicts) != 1 else ''}"
        lines += [f"**{count} between sources**, settled by the precedence rule: {rule}.", ""]
        for c in conflicts:
            said = " · ".join(f"{source}: {value}" for source, value in c.values.items())
            lines.append(f"- **{c.topic}:** we use **{c.chosen}** ({said}). _{c.reason}_")
    if notes:
        lines += ["", f"_The contract agent read each supplier's contract, certificate and messages "
                      f"({len(notes)} note{'s' if len(notes) != 1 else ''}): see **{CONTRACT_NOTES}**._"]
    if warnings:
        lines += ["", "**Warnings:**", ""] + [f"- ⚠️ {w}" for w in warnings]
    if docs:
        by_type: dict[str, list[str]] = {}
        for e in docs:
            by_type.setdefault(_TYPES.get(e.doc_type, e.doc_type), []).append(e.source_id)
        lines += ["", f"**Read {len(docs)} sources**, filtered by your role (click one to open it):", ""]
        lines += [f"- {kind}: {' · '.join(ids)}" for kind, ids in by_type.items()]
    return "\n".join(lines)


def options_view(values: dict) -> str:
    options, rec, facts = values.get("options", []), values.get("recommendation"), values.get("facts")
    if not options:
        return ""
    in_plan = {o.title for o in rec.options} if rec else set()
    lines = ["### ⚖️ Recovery options", "",
             "| | Option | Cost (EUR) | Covers (units) | Verdict |", "|---|---|---:|---:|---|"]
    for o in options:
        if o.title in in_plan:
            verdict = "✅ in the plan"
        elif not o.feasible:
            verdict = f"❌ {o.rejected_because or 'not feasible'}"
        else:
            verdict = "➖ possible, not needed"
        cost = _num(o.cost_eur) if o.feasible else "–"
        lines.append(f"| {o.strategy} | {_cell(o.title)} | {cost} | {o.covered_units:,} | {_cell(verdict)} |")
    if rec:
        cap = f" (budget EUR {facts.spending_cap_eur:,.0f})" if facts else ""
        uncovered = (f" · **Still uncovered:** {rec.residual_handling or f'{rec.uncovered_units:,} units'}"
                     if rec.uncovered_units else "")
        lines += ["", f"**Plan: EUR {rec.total_cost_eur:,.0f}**{cap}{uncovered}"]

    checks = values.get("supplier_checks", [])
    if checks:
        lines += ["", f"**Alternative suppliers** (graph and risk feed; full notes in **{SUPPLIER_DETAILS}**):", "",
                  "| Supplier | EUR/unit | Lead time | Certificate | Watch out |", "|---|---:|---:|---|---|"]
        for c in checks:
            watch = [f"same upstream as {', '.join(c.shared_upstream_with)}"] if c.shared_upstream_with else []
            lines.append(f"| {c.supplier_id} {_cell(c.name)} | {_num(c.unit_price_eur, '.2f')} | "
                         f"{_num(c.lead_time_days)} days | {'valid' if c.certification_valid else '❌ not valid'} | "
                         f"{_cell('; '.join(watch + c.risk_alerts)) or '–'} |")
    notes = values.get("investigation_notes", [])
    alerts = [n for n in notes if not n.startswith("[Deep Agent]")]
    if alerts:
        lines += ["", "**External risk alerts:**", ""] + [f"- 🌐 {a}" for a in alerts]
    if len(alerts) < len(notes):
        lines += ["", f"_The Deep Agent followed each supplier to its upstream manufacturer and that country's "
                      f"risk alerts: see **{AGENT_NOTES}**._"]
    return "\n".join(lines)


def approval_view(values: dict, request: ApprovalRequest, roles: list[str], missing: list[str]) -> str:
    """The exact actions the human approves, what is left open, and who still has to sign."""
    rec, facts = values["recommendation"], values.get("facts")
    actions = [a for option in rec.options for a in option.actions]
    cap = f" · budget EUR {facts.spending_cap_eur:,.0f}" if facts else ""
    lines = [f"### ✍️ Approval needed: EUR {request.total_cost_eur:,.0f}{cap}",
             "These exact actions run only after approval:", "",
             "| # | Action | Cost (EUR) |", "|---|---|---:|"]
    lines += [f"| {n} | {_cell(describe(a))} | {a.cost_eur:,.2f} |" for n, a in enumerate(actions, 1)]
    lines += [f"| | **Total** | **{request.total_cost_eur:,.2f}** |", ""]
    if values.get("critique"):   # the challenge step's findings (incl. uncovered units): read before approving
        lines += ["**Before you approve:**", ""] + [f"- 🔎 {finding}" for finding in values["critique"]] + [""]
    evidence = sorted({_source(e) for option in rec.options for e in option.evidence_ids})
    if evidence:
        lines.append("- **Based on:** " + ", ".join(evidence))
    signoff = " · ".join(f"{r} {'⏳' if r in missing else '✅'}" for r in roles) or "nobody: above every approval tier"
    lines += [f"- **Sign-off:** {signoff}", "",
              "_Nothing is ordered until everyone above has approved. A change makes a new plan that needs a "
              f"new approval. Approval `{request.approval_id}` · payload `{request.payload_hash}`._"]
    return "\n".join(lines)


def closing_view(values: dict) -> str:
    """What was decided and done, with the full report in the side panel."""
    approval, executions = values.get("approval"), values.get("executions", [])
    if approval and approval.status == "approved":
        lines = ["### ✅ Approved and executed"]
    elif approval:
        lines = [f"### ❌ {approval.status.capitalize()}: nothing was executed"]
    else:
        lines = ["### 📄 Case closed without a plan"]
    if approval:
        lines.append(f"Approval `{approval.approval_id}` · EUR {approval.total_cost_eur:,.0f}")
    if executions:
        lines += ["", "| Action | Result | Reference |", "|---|---|---|"]
        lines += [f"| {_OPERATIONS.get(e.operation, e.operation)} | {e.status} | {_cell(e.reference or e.message)} |"
                  for e in executions]
    lines += ["", f"The full **{REPORT}** is in the side panel.", "",
              "_Ask a follow-up, e.g. “Why did you reject Helios?” or “What if the budget were EUR 90,000?”, "
              "or type **new** for a new case._"]
    return "\n".join(lines)
