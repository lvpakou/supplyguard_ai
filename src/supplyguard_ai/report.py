"""INCIDENT REPORT (markdown). OWNER: role 2.

Written when the case closes (approved, or rejected). Everything in it comes from the
case state, so every number has the same source as in the chat:

  summary · the incident · clarifications · impact (revenue at risk SEPARATE from cost)
  · options compared, with why each was taken or rejected · the approved plan, action by
  action · challenge findings · conflicting sources · evidence · approval and who signed
  · what was executed · warnings
"""

import csv

from supplyguard_ai import approval as approvals
from supplyguard_ai.config import data_dir, policies
from supplyguard_ai.state import CaseState

STRATEGY_NAMES = {"A": "Transfer", "B": "Expedite", "C": "Buy alternative", "D": "Reallocate", "E": "Reschedule"}


def short_id(case_id: str) -> str:
    """'3f2a9c1e-5b7d-...' -> 'INC-3F2A9C1E' (case ids that already look short stay as they are)."""
    return case_id if len(case_id) <= 12 else f"INC-{case_id.replace('-', '')[:8].upper()}"


def _user_names() -> dict[str, str]:
    with (data_dir() / "config" / "users.csv").open(newline="", encoding="utf-8") as f:
        return {row["user_id"]: f"{row['name']} ({row['role']})" for row in csv.DictReader(f)}


def _signoffs(approval_id: str) -> list[dict]:
    """Who decided, from the audit table of role 5. [] without Postgres."""
    try:
        return approvals.decisions(approval_id)
    except Exception:  # no DATABASE_URL, or Postgres not running: the report still works
        return []


def _eur(value: float | None) -> str:
    return "–" if value is None else f"EUR {value:,.0f}"


def build_report(state: CaseState) -> str:
    facts, impact, rec, approval = state.facts, state.impact, state.recommendation, state.approval
    names = _user_names()
    lines = [f"# Incident report {short_id(state.case_id)}", ""]

    # --- summary ------------------------------------------------------------------
    status = approval.status if approval else "open"
    if rec:
        lines += [f"**Decision:** {status} · **Recovery cost:** {_eur(rec.total_cost_eur)} "
                  f"(cap {_eur(facts.spending_cap_eur if facts else None)}) · "
                  f"**Units still uncovered:** {rec.uncovered_units:,}"]
        if impact and impact.revenue_at_risk_eur is not None:
            lines += [f"**Revenue at risk (exposure, not an expected loss):** {_eur(impact.revenue_at_risk_eur)}"]
        lines += [""]

    # --- the incident ---------------------------------------------------------------
    lines += ["## Incident", f"> {state.raw_text}", ""]
    if facts:
        lines += [f"- Supplier: {facts.supplier_name or '–'} ({facts.supplier_id or 'unresolved'})",
                  f"- Component: {facts.component_id or '–'} · announced delay: {facts.delay_days} days",
                  f"- Scenario date: {policies()['scenario_date']} · opened by {names.get(state.user_id, state.user_id)}",
                  ""]
    if state.clarifications:
        lines += ["## Clarifications"] + [f"- **Q:** {c.question}  \n  **A:** {c.answer}" for c in state.clarifications]
        lines += [""]

    # --- impact -----------------------------------------------------------------------
    if impact:
        lines += ["## Impact",
                  "| Measure | Value |", "|---|---|",
                  f"| Stock on hand | {impact.on_hand:,} |",
                  f"| Reserved for customer orders | {impact.reserved:,} |",
                  f"| Quarantined | {impact.quarantined:,} |",
                  f"| **Usable** | **{impact.usable:,}** "
                  f"({', '.join(f'{k} {v:,}' for k, v in impact.usable_by_location.items())}) |",
                  f"| Demand | {impact.daily_demand:,} units/day |",
                  f"| Days of cover per plant | {', '.join(f'{k} {v}' for k, v in impact.days_of_cover.items())} |",
                  f"| First stockout (no action) | day {impact.first_stockout_day} |",
                  f"| **Shortfall** | **{impact.shortfall_units:,} units** |",
                  f"| Affected products | {len(impact.affected_products)} ({', '.join(impact.affected_products)}) |",
                  f"| Open orders due within 60 days | {impact.open_orders_at_risk} |",
                  f"| Revenue at risk (exposure) | {_eur(impact.revenue_at_risk_eur)} |",
                  "", f"Sources: {', '.join(impact.source_ids)}", ""]

    # --- options ------------------------------------------------------------------------
    if state.options:
        chosen = {id(o) for o in (rec.options if rec else [])}
        chosen_titles = {o.title for o in (rec.options if rec else [])}
        lines += ["## Options compared", "| | Option | Cost | Covers | Verdict |", "|---|---|---|---|---|"]
        for o in state.options:
            if o.title in chosen_titles or id(o) in chosen:
                verdict = "**in the plan**"
            elif not o.feasible:
                verdict = f"rejected: {o.rejected_because}"
            elif o.strategy in "DE":
                verdict = "for the uncovered units"
            else:
                verdict = "alternative, not chosen"
            lines.append(f"| {o.strategy} {STRATEGY_NAMES[o.strategy]} | {o.title} | {_eur(o.cost_eur)} | "
                         f"{o.covered_units:,} | {verdict} |")
        lines += [""]

    # --- the plan --------------------------------------------------------------------------
    if rec:
        lines += ["## Recommended plan", rec.summary, ""]
        for option in rec.options:
            for action in option.actions:
                lines.append(f"- {approvals.describe(action)} · {_eur(action.cost_eur)}")
        lines += [f"- **Total {_eur(rec.total_cost_eur)}**"]
        if rec.residual_handling:
            lines += [f"- Uncovered: {rec.residual_handling}"]
        lines += [""]

    if state.critique:
        lines += ["## Challenge findings"] + [f"- {finding}" for finding in state.critique] + [""]

    if state.conflicts:
        lines += ["## Conflicting sources", "| Topic | Sources | Used | Why |", "|---|---|---|---|"]
        for c in state.conflicts:
            sources = "; ".join(f"{sid}: {value}" for sid, value in c.values.items())
            lines.append(f"| {c.topic} | {sources} | {c.chosen} | {c.reason} |")
        lines += [""]

    if state.evidence:
        lines += ["## Evidence"]
        seen = set()
        for e in state.evidence:
            if e.source_id in seen:
                continue
            seen.add(e.source_id)
            version = f" v{e.version}" if e.version else ""
            date = f", effective {e.effective_date}" if e.effective_date else ""
            lines.append(f"- `{e.source_id}`{version} ({e.doc_type or 'document'}{date}, {e.access_scope})")
        lines += [""]

    # --- approval and execution ---------------------------------------------------------------
    if approval:
        lines += ["## Approval",
                  f"- Status: **{approval.status}** · approval id `{approval.approval_id}` · "
                  f"payload hash `{approval.payload_hash[:12]}`",
                  f"- Required approvers: {approval.approver_role} (total {_eur(approval.total_cost_eur)})"]
        signoffs = [d for d in _signoffs(approval.approval_id) if d["decision"] != "requested"]
        if signoffs:
            for d in signoffs:
                when = d["decided_at"].strftime("%Y-%m-%d %H:%M") if d.get("decided_at") else ""
                note = f" ({d['note']})" if d.get("note") else ""
                lines.append(f"- {d['decision']} by {names.get(d['user_id'], d['user_id'])} {when}{note}")
        elif approval.decided_by:
            lines.append(f"- Decided by {names.get(approval.decided_by, approval.decided_by)}")
        lines += [""]

    if state.executions:
        lines += ["## Executed in the procurement system", "| Operation | Status | Reference | Idempotency key |",
                  "|---|---|---|---|"]
        lines += [f"| {e.operation} | {e.status} | {e.reference or '–'} | `{e.idempotency_key}` |"
                  for e in state.executions]
        lines += [""]
    elif approval and approval.status != "approved":
        lines += ["## Executed in the procurement system", "Nothing was executed.", ""]

    if state.warnings:
        lines += ["## Warnings"] + [f"- {w}" for w in state.warnings] + [""]

    return "\n".join(lines).rstrip() + "\n"
