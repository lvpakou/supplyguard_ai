# Architecture

OWNER: role 1. How SupplyGuard AI is built, why, and how it handles the traps in the data.

## 1. In one paragraph
A procurement manager describes a supply disruption in a Chainlit chat. A **LangGraph** workflow
turns the message into facts (LLM, structured output), asks when something is ambiguous,
calculates the impact with **deterministic Python**, gathers evidence from documents
(**pgvector / ChromaDB**) and the dependency graph (**Neo4j**), builds and costs recovery options,
challenges its own recommendation, and **stops for human approval** of the exact payload. Only
after approval does it execute on a simulated procurement system (**MCP**), each action exactly
once, then writes an incident report. Every case is saved after every step (**Postgres
checkpointer**), so it survives a restart and can be resumed the next day. **LangSmith** traces
every run, and the trainer's 105 cases score it.

Principle: **the LLM understands and explains; Python decides and calculates.** Numbers, costs,
approval tiers and policy checks are code, so the same input always gives the same answer.

## 2. The workflow (`src/supplyguard_ai/graph.py`, nodes in `nodes.py`)
```
START → intake ──(unclear?)──► clarify ⏸ ──► intake
          │
          ▼
        impact → evidence → dependencies → options → challenge → approval ⏸ ◄─┐
                                              ▲                    │  │ question│
                                              └──── changed ───────┤  └─────────┘
                                   report ◄──── rejected ──────────┤
                                   report ◄── execute ◄── approved ┘
                                     │
                                     ▼
                                  followup ⏸ (loops)
```
⏸ = `interrupt()`: the graph pauses, the state is saved, and it continues with `Command(resume=...)`.

| Step | What it does | Owner of the logic |
|---|---|---|
| **intake** | LLM extracts supplier, component, delay, spending cap (structured output). Python checks the IDs against the data: "Atlas" → asks (S001 or S006), "mc17" → MC-17, unknown component → asks | role 1 |
| **clarify** ⏸ | asks the user, at most 2 rounds (3 for unrealistic answers) | role 1 |
| **impact** | usable stock = on hand − reserved − quarantined; affected products (BOM), open orders due within 60 days, demand/day, days of cover, shortfall, revenue at risk; data warnings (stale counts) | role 2 |
| **evidence** | one general search + one search per supplier of the component; newest version only; role-based access; every text through the injection guard; conflicts resolved by source precedence | roles 3, 5 (guard), 1 (node) |
| **dependencies** | alternative suppliers, shared upstream manufacturers, certification, external risk alerts; Deep Agent investigation | role 4 |
| **options** | strategies A–E (transfer, expedite, buy, reallocate, reschedule) with exact action payloads and costs; applies a requested change | role 2 |
| **challenge** | deterministic checks: cap, certification, capacity, uncovered units | role 2 |
| **approval** ⏸ | builds the request (payload hash, approver tier) and waits; approve / reject / change / question | roles 1, 5 |
| **execute** | each approved action once on the procurement system (idempotency key `case_id:step:operation`) | roles 1, 4 |
| **report** | incident report; approved summary saved as a memory for future cases | roles 2, 3 |
| **followup** ⏸ | answers questions from the saved case, recomputing numbers where needed | role 5 |

## 3. Technology responsibilities (as required by the brief)
| Component | Responsibility in SupplyGuard AI | Where |
|---|---|---|
| **Chainlit** | chat, login (users.csv roles), progress, approval card with exact actions, Approve / Reject / Change, resume saved cases | `chat_app.py` |
| **Application service layer** | identity and access (`auth.py`), approval rules and audit (`approval.py`), procurement client (`integrations/`) | `src/supplyguard_ai/` |
| **LangGraph** | lifecycle, routing, interrupts, persistent execution, recovery | `graph.py`, `nodes.py` |
| **LangChain Core** | prompts, messages, model interface, structured output, tools | `llm.py`, `nodes.py` |
| **LLM** | Azure OpenAI through `AzureChatOpenAI`, configurable in `.env`, every call traced | `llm.py` |
| **create_agent** | bounded contract specialist (which version applies, fees, capacity) | `agents/contract_agent.py` |
| **Deep Agents** | extended investigation of alternative suppliers with planning and subagents | `agents/investigator.py` |
| **PostgreSQL** | operational tables, checkpoints, approval audit (`approval_decisions`) | `scripts/load_postgres.py`, `graph.py`, `approval.py` |
| **pgvector** | document search (newest version, role filter) and incident memories | `tools/retrieval.py`, `memory.py` |
| **ChromaDB** | second vector index with the same embeddings, for the retrieval benchmark and hybrid search | `scripts/index_documents.py` |
| **Neo4j** | supplier → upstream, supplier → component → product → factory → customer graph | `scripts/load_graph.py`, `tools/graph_queries.py` |
| **MCP** | simulated procurement system (read free, write needs approval_id, idempotent) and the external risk service | `mcp_servers/`, `integrations/` |
| **LangSmith** | tracing (`run_config`: name, tags, thread_id) and the 105-case evaluation | `tracing.py`, `evaluation.py` |

## 4. Shared data model (`state.py`)
`CaseState` is the notebook of one case; every role reads and returns these classes, which is
what lets five people work in parallel: `IncidentFacts`, `ImpactSummary`, `Evidence`, `Conflict`,
`SupplierCheck`, `Action`, `Option`, `Recommendation`, `ApprovalRequest`, `ExecutionResult`,
`FollowUp`, plus `requested_change` (`{"qty", "supplier_id", "spending_cap_eur", "note"}`).

## 5. How each trap in the data is handled
| Trap (brief §02, data README) | How SupplyGuard handles it |
|---|---|
| Stock in several locations | usable stock per location; hub stock transferred to the plants that run out first (Katowice 4.0, Lyon 3.3 days) |
| Reserved / quarantined stock | usable = 5,200 − 1,400 reserved − 600 quarantined (lot LOT-KAT-0932) = **3,200** |
| MC-17 in several BOMs | BOM → 6 products, 2 per plant → 77 open orders due within 60 days |
| Different lead times and capacities | options are costed with lead time and monthly capacity; Helios (21 days, 1,500/month) cannot prevent the gap |
| Shared upstream manufacturer | Atlas and Delta both source from Veltro (U01) → Delta is weak diversification; TW risk alert |
| Expired certification | Borealis' ISO 9001 expired 2026-09-30 → not allowed, even though it is the fastest |
| Conflicting contracts and e-mails | source precedence from policies.json: notice 12 d over e-mail 16 d (16 d as a risk), contract 6% over e-mail 10%, Atlas contract v3 over v2; Helios plans with the 1,500 the supplier states |
| Malicious document | `DOC-NOT-HELIOS-PRICE` is flagged by the guard, reported as a warning and never passed to the LLM |
| Restart while approval is pending | state in the Postgres checkpointer; a new app resumes with the same payload hash; idempotency keys prevent duplicate writes |
| Ambiguous names, wrong IDs | "Atlas" → asks S001 or S006; "mc17" → MC-17; unknown component → asks |
| Data-quality problems | loader reports them against the manifest; stale counts become warnings in the case |

## 6. Human approval
- **Nothing is written before approval.** Read operations are free; every write needs an `approval_id`.
- **Bound to the payload:** a SHA-256 hash of every action payload. If supplier, quantity, price
  or date changes, the hash changes and a new approval is required; a decision made on an older
  plan is ignored (checked in the chat and again in the graph).
- **Approval tiers** from policies.json: ≤ €25k procurement manager; ≤ €75k procurement manager
  **and** finance controller (two sign-offs); ≤ €90k finance director. The €30,378 reference plan
  needs both sign-offs.
- **Audit:** every request and decision (who, role, when, payload hash) in `approval_decisions`.
- **Exactly once:** idempotency key `case_id:step:operation`; a repeated key returns the first result.

## 7. Memory and recovery
- Every step is checkpointed in Postgres (`PostgresSaver` / `AsyncPostgresSaver`), keyed by `thread_id` = case id.
- "Resume the case I was reviewing yesterday": `recent_cases()` lists the user's saved cases,
  newest first, with where each one stopped; the chat reopens one exactly where it paused.
- Approved resolutions are kept as incident memories for future cases.

## 8. Quality
- **Tests:** fast tests with a fake LLM and a fake search (no Azure, no Docker), plus tests on the real stores.
- **Evaluation:** `scripts/run_evaluation.py` runs the trainer's 105 cases (impact, ambiguity,
  injection, restart, follow-ups, policy) with deterministic checks and an LLM-as-judge;
  results in `docs/evaluation.md` and as LangSmith experiments.

## 9. Limitations (honest list for the demo)
- The procurement system is simulated; no real ERP.
- The LLM-as-judge uses the same model family as the app; its verdicts are indicative.
- Conflict detection reads a fixed set of facts (lead time, capacity, expedite fee, delay) with patterns tuned to the provided documents.
- Demo login uses one shared password; there is no real identity provider.
- Revenue at risk is exposure (orders due within 60 days), not an expected loss.
- `users.csv` has a `factory_access` column, but the app does not filter by plant: every role sees the
  impact for all plants. Access control covers documents (`document_scopes`, tested per role and search
  mode in `scripts/eval_rag_safety.py`) and approvals (tiers), not plant data.
- **resume** lists only the cases you started: an approver (e.g. the finance controller) reaches a case
  through **Open** on the waiting request, and cannot reopen it after it is decided.
- A message typed with no open case always starts a new case: a question such as "Why not Helios?"
  gets a clarification ("which supplier, component, delay?") instead of "open a case first".
- Follow-up answers come from the LLM over the saved case: they can add an unsupported guess (e.g. which
  plant makes a product) or repeat a role the user claims; nothing is approved or revealed that the role
  may not see, because approval needs the buttons and documents are filtered before the LLM reads them.
