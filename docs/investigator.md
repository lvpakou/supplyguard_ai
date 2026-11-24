# Deep Agent investigator

Code: `src/supplyguard_ai/agents/investigator.py` · tests: `tests/test_investigator.py`.
Called by the `dependencies` step; its notes appear in the chat under "External risk alerts and
investigation notes", in the follow-up case file and in the report.

## The question
Do the alternative suppliers really reduce the risk of the delay? For every supplier (the delayed
one first) the agent follows the supplier to its **upstream manufacturer** (Neo4j, new query
`graph_queries.upstream_makers`) and that manufacturer's **country** to the **external risk alerts**,
and compares it with the delayed supplier.

## What the Deep Agent uses (`deepagents.create_deep_agent`)
| Capability | Here |
|---|---|
| Planning | `write_todos`: one todo per supplier |
| Files | A sandboxed in-memory file system (`StateBackend`: never the real disk, no shell). It holds `/case.md` (the suppliers) and the skill; the agent writes its notes to `/findings.md` |
| Skill | `/skills/dependency-check/SKILL.md`: how to check one supplier |
| Delegated subtasks | Subagent `supplier-checker`, one `task` per supplier, all at once |
| Tools (read-only) | `upstream_of(supplier_id)` (Neo4j), `risk_alerts(country)` (risk MCP / HTTP) |

## Guardrails
- A note is kept only if every source id it cites (`U01`, `SRC-…`, `risk-feed:TW`) was returned by a tool,
  for a supplier of the case, and passes the injection guard.
- The tools only answer for suppliers of the case.
- No model, no network or too many steps: the same check runs in code, so every supplier still gets a note.
  Neo4j down: no notes, no crash.

## MC-17 result (Azure, about 30 s, all 5 notes written by the agent)
- Atlas (S001) and **Delta (S005) share U01 Veltro Semiconductor (TW)**, where a **high** wafer-supply alert
  is active: Delta is no real diversification.
- Borealis (S003) sources from Sweden, where a **medium** alert (Gothenburg port strike) is active.
- Helios (S002, Turkey) and Cordillera (S004, Czech Republic) have independent upstreams without warnings.
