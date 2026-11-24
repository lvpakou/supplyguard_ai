# Business value

OWNER: role 2. Every number below is computed from the trainer's data (`data/`), with the
deterministic tools in `src/supplyguard_ai/tools/`. Where we have no data, we say so.

## In one sentence

For the MC-17 incident SupplyGuard AI turns a supplier e-mail into an approved, sourced
recovery plan costing **EUR 30,378**, which protects customer orders worth
**EUR 27.8M–38.0M** of revenue exposure. It also catches the traps that, according to
the company's own history, caused trouble in past incidents.

## 1. The MC-17 case in numbers

| | Value | Source |
|---|---|---|
| Usable stock | 3,200 of 5,200 (1,400 reserved for 6 tier-1 orders, 600 quarantined) | `tools/inventory.py` |
| First stockout without action | day 7 (Lyon after 3.3 days, Katowice after 4.0) | `tools/impact.py` |
| Shortfall until Atlas delivers (day 19) | 5,350 units | `tools/impact.py` |
| Open customer orders at risk (due within 60 days) | 77 on 6 products | `tools/impact.py` |
| **Recovery cost, recommended plan** | **EUR 30,378**: transfers 96 + expedite 882 + Cordillera 29,400 | `tools/options.py` |
| Units still uncovered | 850 (~1.9 days of demand): reallocate (D) or reschedule (E) | `tools/options.py` |
| Fully covered alternative (with Delta) | EUR 39,218, but Delta shares Atlas's upstream manufacturer | `tools/options.py` |

### Revenue at risk is reported separately from the cost

The assignment says revenue exposure is not an expected loss, and penalties must not be
counted twice. So we report three figures side by side, never added together:

| Measure | Value | What it means |
|---|---|---|
| Revenue of the 77 orders at risk | EUR 37,983,380 | Exposure: these orders depend on MC-17 |
| … of which due before Atlas delivers (48 orders, 22 of them tier-1) | EUR 27,810,869 | The orders the delay can actually make late |
| One week of contractual late penalties on those 48 orders | EUR 304,837 | Penalty of 0–2 % per week, capped at 5 %. An order is either lost (revenue) or late (penalty), never both, so this is NOT added to the revenue |

**Recovery cost / one week of penalties avoided ≈ 1 : 10.** One week of avoided
penalties alone (EUR 304,837) is about ten times the cost of the plan (EUR 30,378),
before counting lost sales or customer relationships.

## 2. The traps it catches are the company's own lessons

The 300 historical disruptions (`historical_disruption_cases.csv`, May 2024 – Sep 2026,
about **10 a month**) record a lesson learned for each case. The most frequent lessons are
exactly what the system now checks automatically, before anyone approves:

| Lesson in past cases | Times | What SupplyGuard AI does now |
|---|---|---|
| "Alternative supplier needed qualification check first." | 62 | Rejects a supplier with an expired certification (Borealis) before proposing it |
| "Early transfer avoided line stop." | 52 | Sends hub stock first to the plants that run out first (Lyon, Katowice) |
| "Reserved stock had to be reallocated for tier-1 order." | 50 | Counts reserved stock as unusable and names the 6 orders holding it |
| "Expedite fee lower than expected penalty." | 49 | Costs the expedite (EUR 882) and shows the fee from the other source (EUR 1,470 at 10 %) |
| "Shared upstream manufacturer caused second delay." | 48 | Flags Delta: same upstream (Veltro, U01) as Atlas |
| "Stale e-mail figures misled the first estimate." | 39 | Uses source precedence (contract > notice > e-mail) and states what changes if the e-mail is right (+1,800 units if the delay is 16 days) |

17 % of the past cases (51 of 300) ended only **partially resolved**, and they cost more on
average: **EUR 46,403** against EUR 34,555 for resolved ones (all cases: EUR 36,569).
A check that prevents a wrong first plan is therefore worth more than the plan itself.

## 3. Control and auditability

- **Nothing is bought without approval**, and the approval binds to the exact payload: a
  change (e.g. quantity 6,000) builds a new plan, which needs a new approval (EV-0096).
- **The right people approve:** EUR 30,378 needs both the procurement manager and the
  finance controller (approval tiers in `policies.json`).
- **Every number has a source** (tables, purchase orders, documents), and the incident
  report lists the options rejected and why, the challenge findings and who signed.
- **Each action runs once**, even after a restart (idempotency keys).

## 4. What we cannot claim (limitations)

- **Time saved:** the data has no record of how long a manual investigation takes, so we
  do not put a number on it. To measure: time from the supplier notice to an approved plan,
  before and after.
- **Model:** the shortfall uses the trainer's pooled-stock model (no day-by-day simulation);
  a transfer is assumed to arrive in 2 days at EUR 0.12 per unit.
- **Revenue figures are exposure**, not forecast losses: whether an order is really lost
  depends on the customer.
- The figures are for the synthetic data of the exercise; all companies and amounts are fictional.