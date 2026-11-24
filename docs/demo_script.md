# Demo script (MC-17 incident)

OWNER: role 1. About 10 minutes. Rehearse twice; know who says what.

## Before the demo (10 minutes earlier)
```bash
docker compose up -d                         # databases + the two MCP servers
uv run python scripts/reset_demo.py --yes    # forget old cases, approvals, procurement records
uv run python scripts/load_postgres.py       # restore the operational data (approved actions change it)
uv run python scripts/index_documents.py
uv run python scripts/load_graph.py
uv run chainlit run src/supplyguard_ai/chat_app.py
```
Open two browser windows: one normal (Maria), one private (Paul). Open LangSmith → project
`supplyguard-ai` → Threads. Have `docs/evaluation.md` ready.

## The story
| # | Who | Do | Show / say |
|---|---|---|---|
| 1 | Role 1 | Sign in as **u-pm-01** (Maria Keller, procurement manager) | "Every user has a role from users.csv; it decides which documents the case may use." |
| 2 | Role 1 | Paste the incoming message from the brief (below) | progress: intake → impact → evidence → dependencies → options → challenge |
| 3 | Role 2 | Point at the numbers | **3,200 usable** of 5,200 (1,400 reserved, 600 quarantined), **6 products, 77 orders**, Katowice 4.0 / Lyon 3.3 days of cover, **shortfall 5,350** — all calculated in Python from the data |
| 4 | Role 3 | Point at evidence and warnings | conflicts resolved by precedence: notice **12 d** over e-mail 16 d, contract **6%** over e-mail 10%, Atlas contract **v3** over v2, Helios planned at **1,500**; **DOC-NOT-HELIOS-PRICE ignored** (hidden instruction) |
| 5 | Role 4 | Point at the rejected options | Helios too slow (21 d, 1,500/month), **Borealis certificate expired**, **Delta shares upstream Veltro** with Atlas (+ TW risk alert) |
| 6 | Role 2 | The approval card | exact actions: 2 transfers, expedite PO-2026-9002 (6%), 3,000 units from Cordillera → **€30,378**, under the €75,000 cap; 850 units → reschedule / reallocate; revenue at risk shown separately |
| 7 | Role 5 | Click **Approve** as Maria | "Still needed: finance_controller" — **nothing is ordered yet** |
| 8 | Role 5 | Private window: sign in as **u-fc-01** (Paul Novak) → Open the waiting request → **Approve** | execute → report: 4 actions done once |
| 9 | Role 1 | Stop Chainlit (Ctrl+C), start it again, sign in as Maria, type **resume** → Open | the case is still there after the restart, nothing executed twice |
| 10 | Role 5 | Ask: *Why did you reject Supplier Helios?* · *What changes if we increase the spending limit to €90,000?* | answers from the saved case, numbers recomputed |
| 11 | Role 1 | LangSmith Threads | the whole case step by step; evaluation score per category (`docs/evaluation.md`) |
| 12 | Role 5 | Optional: Postgres `approval_decisions` | audit trail: who approved what, when, for which payload hash |

### The incoming message
> Supplier Atlas Components has announced a 12-day delay for component MC-17. Determine which customer commitments are at risk, investigate alternative sources, and recommend a recovery plan. Additional spending must not exceed €75,000. Do not create a purchase order without approval.

### If there is time: short extras
- Type **Atlas says the motor board is late.** → it asks which Atlas (S001 or S006) instead of guessing.
- On the approval card click **Change** → "make the quantity 6,000" → a new plan and a new approval.
- Sign in as **u-ro-01** (viewer): fewer documents, cannot approve.

## Limitations to mention (30 seconds)
Simulated procurement system; one shared demo password; LLM-as-judge is indicative; conflict
detection tuned to the provided documents. See `docs/architecture.md` §9.

## If something breaks live
| Problem | Fix |
|---|---|
| Chat does not open / login fails | `.env` needs `CHAINLIT_AUTH_SECRET` and `DEMO_PASSWORD` |
| "document index does not exist" | `uv run python scripts/index_documents.py` |
| Connection refused | `docker compose up -d`; `.env` points to ports 5433 / 7688 / 8001 |
| Old cases in "resume" | `uv run python scripts/reset_demo.py --yes` |
| Azure slow | wait; the steps show progress. Backup: the LangSmith trace of the rehearsal |
