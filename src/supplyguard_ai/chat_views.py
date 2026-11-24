"""WHAT THE CHAT SHOWS of an investigation, as markdown. OWNER: role 5.

Plain functions: the case values in, markdown out (no Chainlit), so they are easy to test.
Shown before the approval card, in three messages:
  1 impact on operations · 2 evidence and conflicts · 3 recovery options compared.
Every number comes from the case state, which took it from a deterministic tool or a
document; the sources are listed so each number can be traced.
"""

from supplyguard_ai.state import Evidence


def _cell(value) -> str:
    """Text that is safe inside a markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _num(value, fmt: str = ",.0f") -> str:
    return "–" if value is None else format(value, fmt)


def documents(values: dict) -> list[Evidence]:
    """The case's evidence, once per source."""
    return list({e.source_id: e for e in values.get("evidence", [])}.values())


def impact_view(values: dict) -> str:
    i = values.get("impact")
    if not i:
        return ""
    # "F2 (W-KAT)": 4.0  ->  "W-KAT": ("F2 (W-KAT)", 4.0)
    cover = {plant.split("(")[-1].rstrip(")"): (plant, days) for plant, days in i.days_of_cover.items()}
    lines = ["### 1 · Impact on operations", "",
             f"**{i.component_id}: {i.usable:,} of {i.on_hand:,} units are usable** "
             f"({i.reserved:,} reserved for customer orders, {i.quarantined:,} quarantined)", "",
             "| Location | Usable units | Plant | Days of cover |", "|---|---:|---|---:|"]
    for location, units in i.usable_by_location.items():
        plant, days = cover.get(location, ("hub (for transfers)", None))
        lines.append(f"| {location} | {units:,} | {plant} | {_num(days, '.1f')} |")
    stockout = f"day {i.first_stockout_day}" if i.first_stockout_day is not None else "none before the delivery"
    lines += ["",
              f"- Demand {i.daily_demand:,} units/day · first stockout: **{stockout}** · "
              f"**shortfall {i.shortfall_units:,} units** until the delayed delivery arrives",
              f"- {len(i.affected_products)} products affected ({', '.join(i.affected_products)}) · "
              f"**{i.open_orders_at_risk} open customer orders at risk**",
              f"- Revenue at risk: EUR {_num(i.revenue_at_risk_eur)}. This is exposure, not an expected loss, "
              "and it is never added to the recovery cost",
              "", f"_Sources: {', '.join(i.source_ids)}_"]
    return "\n".join(lines)


def evidence_view(values: dict) -> str:
    conflicts, warnings, docs = values.get("conflicts", []), values.get("warnings", []), documents(values)
    if not (conflicts or warnings or docs):
        return ""
    lines = ["### 2 · Evidence and conflicts"]
    if conflicts:
        lines += ["", "**Sources that disagree**, resolved by source precedence (policies.json):", "",
                  "| Topic | The sources say | We use | Why |", "|---|---|---|---|"]
        for c in conflicts:
            said = "; ".join(f"{source}: {value}" for source, value in c.values.items())
            lines.append(f"| {_cell(c.topic)} | {_cell(said)} | **{_cell(c.chosen)}** | {_cell(c.reason)} |")
    if warnings:
        lines += ["", "**Warnings**", ""] + [f"- ⚠️ {w}" for w in warnings]
    if docs:
        lines += ["", f"**Documents used** ({len(docs)}; click a source to read it):", ""]
        lines += [f"- {e.source_id} · {e.doc_type} v{e.version} · {e.effective_date} · "
                  f"{e.claim.splitlines()[0][:100] if e.claim else ''}" for e in docs]
    return "\n".join(lines)


def options_view(values: dict) -> str:
    options, rec, impact = values.get("options", []), values.get("recommendation"), values.get("impact")
    if not options:
        return ""
    in_plan = {o.title for o in rec.options} if rec else set()
    lines = ["### 3 · Recovery options compared", "",
             "| | Option | Cost (EUR) | Covers (units) | Verdict |", "|---|---|---:|---:|---|"]
    for o in options:
        if o.title in in_plan:
            verdict = "✅ in the plan"
        elif not o.feasible:
            verdict = f"❌ {o.rejected_because or 'not feasible'}"
        else:
            verdict = "possible, not needed"
        cost = _num(o.cost_eur) if o.feasible else "–"
        lines.append(f"| {o.strategy} | {_cell(o.title)} | {cost} | {o.covered_units:,} | {_cell(verdict)} |")

    checks = values.get("supplier_checks", [])
    if checks:
        lines += ["", "**Alternative suppliers checked**", "",
                  "| Supplier | EUR/unit | Lead time (days) | Capacity/month | Certificate | Same upstream as | Notes |",
                  "|---|---:|---:|---:|---|---|---|"]
        for c in checks:
            certificate = "valid" if c.certification_valid else "❌ not valid"
            lines.append(f"| {c.supplier_id} {_cell(c.name)} | {_num(c.unit_price_eur, '.2f')} | "
                         f"{_num(c.lead_time_days)} | {_num(c.monthly_capacity)} | {certificate} | "
                         f"{', '.join(c.shared_upstream_with) or '–'} | {_cell('; '.join(c.notes + c.risk_alerts))} |")

    notes = values.get("investigation_notes", [])
    if notes:
        lines += ["", "**External risk alerts and investigation notes**", ""] + [f"- {n}" for n in notes]
    if rec:
        revenue = f"EUR {_num(impact.revenue_at_risk_eur)}" if impact else "–"
        lines += ["", f"**Recovery cost of the plan: EUR {rec.total_cost_eur:,.2f}** · {rec.uncovered_units:,} units "
                      f"still uncovered. Shown separately: revenue at risk {revenue} (exposure, not a cost)."]
    return "\n".join(lines)
