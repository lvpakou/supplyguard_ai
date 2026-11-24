"""CHALLENGE: check the recommendation before asking for approval. OWNER: role 2.

The assignment (§03 step 7): challenge the proposal "for missing evidence, policy violations,
and weak assumptions". Deterministic checks, no LLM, each from the data or policies.json:

  Policy        spending cap · valid certification · who must approve (approval tiers)
  Feasibility   monthly capacity · minimum order quantity · arrives before the delayed delivery
                · enough usable stock at the transfer's source · expedite allowed
  Risk          shared upstream manufacturer · external risk alerts (role 4)
  Assumptions   conflicting sources (role 3): what changes if the other source is right
                · stale stock counts · units still uncovered
  Evidence      every action cites a source

Returns short, human-readable findings (shown in the chat under "Challenge findings").
An empty list means "no objections".
"""

import re

from supplyguard_ai.config import policies
from supplyguard_ai.state import Action, CaseState
from supplyguard_ai.tools.impact import delayed_delivery
from supplyguard_ai.tools.tables import table


def review(state: CaseState) -> list[str]:
    rec = state.recommendation
    if rec is None:
        return ["No recommendation to review."]
    facts, impact = state.facts, state.impact
    findings: list[str] = []
    actions = [a for option in rec.options for a in option.actions]

    findings += _policy(state, rec.total_cost_eur)
    delayed_day = (delayed_delivery(facts.supplier_id, impact.component_id, facts.delay_days or 0)["delayed_day"]
                   if impact is not None else 0)
    for option in rec.options:
        specific = [f for action in option.actions for f in _feasibility(action, state, delayed_day)]
        if not option.feasible and not specific:  # the option knows why; no specific check said it
            specific = [f"Not feasible as proposed: {option.title} - {option.rejected_because}"]
        findings += specific
    # An option the user asked for that could not go into the plan (e.g. qty above capacity).
    for option in state.options:
        if not option.feasible and "the user's change" in option.title:
            specific = [f for action in option.actions for f in _feasibility(action, state, delayed_day)]
            findings += specific or [f"Requested change not possible: {option.rejected_because}"]
            findings.append(f"Left out of the plan: {option.title}.")
    findings += _risk(actions, state)
    findings += _assumptions(actions, state)
    findings += [f"No source cited for: {o.title}" for o in rec.options if o.actions and not o.evidence_ids]
    if rec.uncovered_units:
        findings.append(f"{rec.uncovered_units:,} units stay uncovered: "
                        f"{rec.residual_handling or 'a decision is needed (reallocate or reschedule)'}.")
    return list(dict.fromkeys(findings))  # same finding once, order kept


# ---------------------------------------------------------------------------
# Policy: cap, certification, approvers
# ---------------------------------------------------------------------------
def _cap(state: CaseState) -> float:
    change = state.requested_change or {}
    return float(change.get("spending_cap_eur") or (state.facts.spending_cap_eur if state.facts else
                                                     policies()["incident_spending_cap_eur"]))


def _policy(state: CaseState, total: float) -> list[str]:
    rules, cap = policies(), _cap(state)
    findings = []
    if total > cap:
        raised = rules["raised_cap_eur_with_finance_director_approval"]
        hint = " (up to EUR {:,.0f} only with the finance director)".format(raised) if total <= raised else ""
        findings.append(f"Total cost EUR {total:,.0f} exceeds the cap of EUR {cap:,.0f}{hint}.")
    tier = next((t for t in rules["approval_tiers_eur"] if total <= t["up_to"]), None)
    if tier is None:
        findings.append(f"EUR {total:,.0f} is above every approval tier: nobody may approve it.")
    elif "+" in tier["approver"]:
        findings.append(f"EUR {total:,.0f} needs BOTH {tier['approver'].replace(' + ', ' and ')} to approve.")
    return findings


# ---------------------------------------------------------------------------
# Feasibility of each action
# ---------------------------------------------------------------------------
def _offer(supplier_id: str, component_id: str):
    offers = table("supplier_components")
    rows = offers[(offers["supplier_id"] == supplier_id) & (offers["component_id"] == component_id)]
    return None if rows.empty else rows.iloc[0]


def _feasibility(action: Action, state: CaseState, delayed_day: int) -> list[str]:
    p, findings = action.payload, []
    if action.operation == "create_purchase_order":
        supplier, offer = p["supplier_id"], _offer(p["supplier_id"], p["component_id"])
        if offer is None:
            return [f"{supplier} has no offer for {p['component_id']} (supplier_components)."]
        capacity = int(offer["monthly_capacity_units"])
        for check in state.supplier_checks:  # role 4 may know a lower real capacity
            if check.supplier_id == supplier and check.monthly_capacity:
                capacity = min(capacity, check.monthly_capacity)
        if p["qty"] > capacity:
            findings.append(f"{supplier}: {p['qty']:,} units exceed the monthly capacity of {capacity:,}.")
        if p["qty"] < offer["moq_units"]:
            findings.append(f"{supplier}: {p['qty']:,} units are below the minimum order of {offer['moq_units']:,}.")
        if offer["lead_time_days"] >= delayed_day:
            findings.append(f"{supplier}: arrives day {offer['lead_time_days']}, not before the delayed "
                            f"delivery (day {delayed_day}), so it does not prevent the disruption.")
        suppliers = table("suppliers").set_index("supplier_id")
        if supplier in suppliers.index and suppliers.loc[supplier, "certification_status"] != "valid":
            findings.append(f"{supplier}: certification {suppliers.loc[supplier, 'certification_status']} "
                            f"(expiry {suppliers.loc[supplier, 'certification_expiry']:%Y-%m-%d}); "
                            "policy requires a valid one.")
        if supplier in {c.supplier_id for c in state.supplier_checks if not c.certification_valid}:
            findings.append(f"{supplier}: the graph check (role 4) reports no valid certification.")
    elif action.operation == "request_stock_transfer":
        available = state.impact.usable_by_location.get(p["from_location"], 0) if state.impact else 0
        if p["qty"] > available:
            findings.append(f"Transfer of {p['qty']:,} from {p['from_location']}: only {available:,} usable there.")
        days = policies()["transfer_days"]
        warehouse = p["to_location"]
        for key, cover in (state.impact.days_of_cover if state.impact else {}).items():
            if f"({warehouse})" in key and cover < days:
                findings.append(f"{warehouse} runs out in {cover} days but a transfer takes {days}: "
                                "it arrives too late for the first days.")
    elif action.operation == "expedite_purchase_order":
        pos = table("purchase_orders")
        po = pos[pos["po_id"] == p["po_id"]]
        if po.empty:
            findings.append(f"{p['po_id']} does not exist.")
        elif po.iloc[0]["expedite_allowed"] != "yes":
            findings.append(f"{p['po_id']}: the contract does not allow expediting.")
    return findings


# ---------------------------------------------------------------------------
# Risk: shared upstream manufacturer, external alerts
# ---------------------------------------------------------------------------
def _risk(actions: list[Action], state: CaseState) -> list[str]:
    suppliers = table("suppliers").set_index("supplier_id")
    delayed = state.facts.supplier_id if state.facts else None
    upstream = suppliers["upstream_manufacturer_id"].get(delayed) if delayed in suppliers.index else None
    findings = []
    for action in actions:
        supplier = action.payload.get("supplier_id")
        if not supplier or supplier not in suppliers.index:
            continue
        if upstream and suppliers.loc[supplier, "upstream_manufacturer_id"] == upstream:
            findings.append(f"{supplier} buys from the same upstream manufacturer ({upstream}) as {delayed}: "
                            "weak diversification.")
        for check in state.supplier_checks:
            if check.supplier_id == supplier:
                findings += [f"{supplier}: external risk alert - {alert}" for alert in check.risk_alerts]
    return findings


# ---------------------------------------------------------------------------
# Assumptions: conflicting sources, stale data
# ---------------------------------------------------------------------------
def _number(text: str) -> float | None:
    found = re.search(r"\d[\d,]*\.?\d*", text)
    return float(found.group().replace(",", "")) if found else None


def _assumptions(actions: list[Action], state: CaseState) -> list[str]:
    findings = []
    in_plan = {a.payload.get("supplier_id") for a in actions}
    pos = table("purchase_orders").set_index("po_id")
    for action in actions:  # an expedited PO belongs to its supplier too
        if action.operation == "expedite_purchase_order" and action.payload["po_id"] in pos.index:
            in_plan.add(pos.loc[action.payload["po_id"], "supplier_id"])
    delayed = state.facts.supplier_id if state.facts else None
    daily = state.impact.daily_demand if state.impact else 0

    for conflict in state.conflicts:
        supplier = re.search(r"\((S\d+)\)", conflict.topic)
        supplier = supplier.group(1) if supplier else None
        if supplier not in in_plan and supplier != delayed:
            continue
        if "contract version" in conflict.topic:
            continue  # already settled: the superseded version is simply not used
        others = [v for v in conflict.values.values() if v != conflict.chosen and conflict.chosen not in v]
        if not others:
            continue
        chosen, other = _number(conflict.chosen), _number(others[0])
        effect = ""
        if "expedite fee" in conflict.topic and chosen is not None and other is not None:
            for action in actions:
                if action.operation == "expedite_purchase_order" and action.payload["fee_pct"] == chosen:
                    effect = f" -> fee EUR {action.cost_eur * other / chosen:,.0f} instead of EUR {action.cost_eur:,.0f}"
        elif "delay" in conflict.topic and chosen is not None and other is not None and daily:
            effect = (f" -> {other - chosen:+.0f} days = about {(other - chosen) * daily:,.0f} more units "
                      "uncovered if the longer figure is right")
        findings.append(f"Assumption: {conflict.topic} = {conflict.chosen} ({conflict.reason}); "
                        f"other source says {others[0]}{effect}.")

    for warning in state.warnings:
        if "last counted" in warning:
            findings.append(f"Stale data: {warning}")
    return findings
