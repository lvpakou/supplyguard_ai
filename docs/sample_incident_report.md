<!-- Sample incident report, generated 2026-11-25 by the app itself (report.py): the MC-17 case run through the chat with the real Azure model, search, contract agent, Deep Agent and the procurement MCP server. Maria Keller (procurement manager) approved first, then Paul Novak (finance controller). Text unchanged. -->

# Incident report INC-BEA2AF0E

**Decision:** approved · **Recovery cost:** EUR 30,378 (cap EUR 75,000) · **Units still uncovered:** 850
**Revenue at risk (exposure, not an expected loss):** EUR 37,983,380

## Incident
> Supplier Atlas Components has announced a 12-day delay for component MC-17. Determine which customer commitments are at risk, investigate alternative sources, and recommend a recovery plan. Additional spending must not exceed €75,000. Do not create a purchase order without approval.

- Supplier: Atlas Components (S001)
- Component: MC-17 · announced delay: 12 days
- Scenario date: 2026-10-19 · opened by Maria Keller (procurement_manager)

## Impact
| Measure | Value |
|---|---|
| Stock on hand | 5,200 |
| Reserved for customer orders | 1,400 |
| Quarantined | 600 |
| **Usable** | **3,200** (W-STU 1,300, W-KAT 600, W-LYO 500, W-HUB 800) |
| Demand | 450 units/day |
| Days of cover per plant | F1 (W-STU) 8.7, F2 (W-KAT) 4.0, F3 (W-LYO) 3.3 |
| First stockout (no action) | day 7 |
| **Shortfall** | **5,350 units** |
| Affected products | 6 (P012, P023, P031, P047, P058, P066) |
| Open orders due within 60 days | 77 |
| Revenue at risk (exposure) | EUR 37,983,380 |

Sources: structured/bill_of_materials.csv, structured/customer_orders.csv, structured/production_schedule.csv, structured/purchase_orders.csv, structured/inventory.csv, structured/reservations.csv, structured/quarantine_lots.csv, PO-2026-9001

## Options compared
| | Option | Cost | Covers | Verdict |
|---|---|---|---|---|
| A Transfer | Transfer 800 hub units to W-KAT (350) and W-LYO (450): the plants that run out first | EUR 96 | 0 | **in the plan** |
| B Expedite | Expedite PO-2026-9002 (S004, 1,500 units): day 14 -> day 7, fee 6% | EUR 882 | 1,500 | **in the plan** |
| C Buy alternative | Buy 3,000 from Cordillera Industrial (S004), EUR 9.80, 9 days: independent upstream | EUR 29,400 | 3,000 | **in the plan** |
| C Buy alternative | Buy 850 from Delta Micro Systems (S005), EUR 10.40, 8 days: covers the rest, but shares upstream U01 with S001 (weak diversification) | EUR 8,840 | 850 | alternative, not chosen |
| C Buy alternative | Buy from Helios Supply (S002) | EUR 0 | 0 | rejected: Too slow: 21-day lead time, arrives day 21, not before the delayed delivery (day 19). |
| C Buy alternative | Buy from Borealis Parts (S003) | EUR 0 | 0 | rejected: ISO 9001:2015 expired 2026-09-30: policy requires a valid certification. |
| D Reallocate | Reallocate the last 850 units to tier-1 customer orders | EUR 0 | 0 | for the uncovered units |
| E Reschedule | Reschedule production for ~1.9 days of demand (850 units) | EUR 0 | 0 | for the uncovered units |

## Recommended plan
Transfer 800 hub units to W-KAT (350) and W-LYO (450): the plants that run out first; Expedite PO-2026-9002 (S004, 1,500 units): day 14 -> day 7, fee 6%; Buy 3,000 from Cordillera Industrial (S004), EUR 9.80, 9 days: independent upstream

- Transfer 350 x MC-17 from W-HUB to W-KAT · EUR 42
- Transfer 450 x MC-17 from W-HUB to W-LYO · EUR 54
- Expedite PO-2026-9002: 7 days earlier, fee 6.0% · EUR 882
- Purchase order: 3000 x MC-17 from S004 at EUR 9.8/unit, delivery 2026-10-28 · EUR 29,400
- **Total EUR 30,378**
- Uncovered: 850 units (~1.9 days of demand): reschedule production (E) or reallocate to tier-1 orders (D); or Buy 850 from Delta Micro Systems (S005), EUR 10.40, 8 days for EUR 8,840

## Challenge findings
- EUR 30,378 needs BOTH procurement_manager and finance_controller to approve.
- Assumption: Atlas Components (S001) delay MC-17 = 12 days (supplier notice outranks supplier e-mail (policies.json source_precedence); the longer 16 days is reported as a risk); other source says 16 days -> +4 days = about 1,800 more units uncovered if the longer figure is right.
- Assumption: Cordillera Industrial (S004) expedite fee = 6% (contract (latest version) outranks supplier e-mail (policies.json source_precedence)); other source says 10% -> fee EUR 1,470 instead of EUR 882.
- 850 units stay uncovered: 850 units (~1.9 days of demand): reschedule production (E) or reallocate to tier-1 orders (D); or Buy 850 from Delta Micro Systems (S005), EUR 10.40, 8 days for EUR 8,840.

## Conflicting sources
| Topic | Sources | Used | Why |
|---|---|---|---|
| Atlas Components (S001) contract version | DOC-CON-S001-v2: v2 (2025-01-01): lead time 10 days, monthly capacity 12,000/month, expedite fee 4%; DOC-CON-S001-v3: v3 (2026-03-01): lead time 14 days, monthly capacity 9,000/month, expedite fee 6% | DOC-CON-S001-v3 | v2 is superseded by v3 effective 2026-03-01; only the latest version in force applies (DOC-PRO-02) |
| Atlas Components (S001) delay MC-17 | DOC-NOT-ATLAS-MC17: 12 days; DOC-EM-ATLAS-01: 16 days | 12 days | supplier notice outranks supplier e-mail (policies.json source_precedence); the longer 16 days is reported as a risk |
| Cordillera Industrial (S004) expedite fee | DOC-EM-CORDILLERA-01: 10%; DOC-CON-S004-v1: 6% | 6% | contract (latest version) outranks supplier e-mail (policies.json source_precedence) |
| Helios Supply (S002) monthly capacity | DOC-EM-HELIOS-01: 1,500/month; DOC-CON-S002-v1: 4,000/month | 1,500/month for planning | contract (latest version) outranks supplier e-mail (policies.json source_precedence), so 4,000/month stays the official figure; but the supplier states in writing (DOC-EM-HELIOS-01) that it can only deliver 1,500/month, and planning on more would leave production short |

## Evidence
- `DOC-NOT-ATLAS-MC17` v1 (supplier_notice, effective 2026-10-19, procurement)
- `DOC-EM-CORDILLERA-01` v1 (email, effective 2026-10-19, procurement)
- `DOC-INC-HC-029` v1 (incident_report, effective 2024-11-18, internal)
- `DOC-INC-HC-020` v1 (incident_report, effective 2024-10-10, internal)
- `DOC-INC-HC-022` v1 (incident_report, effective 2026-08-04, internal)
- `DOC-EM-ATLAS-01` v1 (email, effective 2026-10-19, procurement)
- `DOC-CON-S001-v3` v3 (contract, effective 2026-03-01, procurement)
- `DOC-QUA-S001-v1` v1 (qualification, effective 2024-06-30, procurement)
- `DOC-EM-HELIOS-01` v1 (email, effective 2026-10-18, procurement)
- `DOC-CON-S002-v1` v1 (contract, effective 2025-01-01, procurement)
- `DOC-QUA-S002-v1` v1 (qualification, effective 2024-03-31, procurement)
- `DOC-EM-BOREALIS-01` v1 (email, effective 2026-10-17, procurement)
- `DOC-CON-S003-v1` v1 (contract, effective 2025-11-01, procurement)
- `DOC-QUA-S003-v1` v1 (qualification, effective 2023-10-01, procurement)
- `DOC-CON-S004-v1` v1 (contract, effective 2025-08-01, procurement)
- `DOC-QUA-S004-v1` v1 (qualification, effective 2024-11-30, procurement)
- `DOC-EM-DELTA-01` v1 (email, effective 2026-10-17, procurement)
- `DOC-CON-S005-v1` v1 (contract, effective 2025-01-01, procurement)
- `DOC-QUA-S005-v1` v1 (qualification, effective 2024-08-31, procurement)
- `MEM-HC-043` (incident_memory, internal)
- `MEM-HC-026` (incident_memory, internal)
- `MEM-HC-005` (incident_memory, internal)

## Approval
- Status: **approved** · approval id `APR-bea2af0e-7eb1e7` · payload hash `7eb1e7e6c7e5`
- Required approvers: procurement_manager + finance_controller (total EUR 30,378)
- approve by Maria Keller (procurement_manager) 2026-11-25 09:15
- approve by Paul Novak (finance_controller) 2026-11-25 09:15

## Executed in the procurement system
| Operation | Status | Reference | Idempotency key |
|---|---|---|---|
| request_stock_transfer | done | TRF-MC-17-W-HUB-W-KAT | `bea2af0e-060b-4015-b159-f8bac8505c35:0:request_stock_transfer` |
| request_stock_transfer | done | TRF-MC-17-W-HUB-W-LYO | `bea2af0e-060b-4015-b159-f8bac8505c35:1:request_stock_transfer` |
| expedite_purchase_order | done | PO-2026-9002 | `bea2af0e-060b-4015-b159-f8bac8505c35:2:expedite_purchase_order` |
| create_purchase_order | done | PO-MCP-00001 | `bea2af0e-060b-4015-b159-f8bac8505c35:3:create_purchase_order` |

## Warnings
- Ignored DOC-NOT-HELIOS-PRICE: suspicious instruction (overrides our instructions): 'ignore all previous instructions'
