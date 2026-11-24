# Contract agent

OWNER: role 3 (`src/supplyguard_ai/agents/contract_agent.py`).

For every supplier of the component (MC-17: Atlas + 4 alternatives) it answers the questions
procurement asks about contracts: which contract version applies, lead time, committed monthly
capacity, expedite fee, late-delivery penalty, and whether the ISO 9001 certificate is valid,
always with `source_id` and effective date. Called by the evidence step:
`analyze_contracts(facts, supplier_ids, user_role) -> list[Evidence]`.

## Who does what
| Part | Does | Why |
|---|---|---|
| **Tools** (code) | read the documents and extract the numbers | numbers never come from the LLM |
| **Agent** (`create_agent`: one model, three tools) | decides what to open, reads notices/e-mails when they could change a term, writes one note per supplier | judgement and explanation |
| **Code around it** | guarantees coverage and checks every source the agent cites | the agent cannot skip a supplier or invent a source |

### The three tools
- `get_contract_terms(supplier_id)`: the contract in force, terms extracted by code (same patterns
  as `find_conflicts`, plus the penalty). Newest version first, then the role filter: Atlas → v3
  ("supersedes 1 older version"); a role that may not read the newest version gets nothing.
- `get_certification(supplier_id)`: the ISO 9001 certificate. The code compares the expiry date with
  the scenario date (2026-10-19); it does not trust the text. Borealis → "EXPIRED on 2026-09-30 …
  no new orders (PRO-04)".
- `search_supplier_documents(supplier_id, question)`: the supplier's notices and e-mails, through the
  hybrid search (filtered by supplier and by role).

Every text the model sees goes through `guards.check_injection()` and `guards.wrap_untrusted()`.
A flagged document reaches the model only as "withheld: flagged as a prompt injection", without
the injected words. The tools refuse suppliers that are not in the case.

## What it returns (MC-17, procurement manager)
**10 findings from the tools**, one per document, e.g.:
> `DOC-CON-S004-v1` Cordillera Industrial (S004) contract v1 in force since 2025-08-01: lead time 9 days;
> committed capacity 3,000 units/month; expedite fee 6% of PO value; late penalty 0.5% per day, capped at 10%.
>
> `DOC-QUA-S003-v1` Borealis Parts (S003) ISO 9001 certificate EXPIRED on 2026-09-30 (checked on 2026-10-19):
> no new orders until a renewed certificate is on file (PRO-04).

**Plus one note per supplier from the agent** (real run with Azure), e.g.:
> Contract agent, Cordillera Industrial (S004): Contract v1 applies: 9-day lead time, 3,000 units/month
> capacity, 6% expedite fee, 0.5% daily late penalty capped at 10%; e-mail claims expedite fee 10%
> (conflicts with contract, contract prevails); ISO 9001 valid. Watch for expedite fee discrepancy.
> (sources: DOC-CON-S004-v1, DOC-QUA-S004-v1, DOC-EM-CORDILLERA-01)

In that run the agent found all three source conflicts by itself (Atlas 12 vs 16 days, Helios 4,000
vs 1,500, Cordillera 6% vs 10%) and the expired Borealis certificate. A viewer gets nothing
(contracts are `procurement` scope).

## How we stop the agent from inventing things
- **Sources are checked.** The agent must end with `NOTE <supplier_id> | <sentence> | <source_ids>`.
  A note is kept only if the supplier is in the case and **every** cited `source_id` was returned to
  the agent by a tool. Invented sources, real sources it never opened, and unknown suppliers are dropped.
- **Coverage.** After the agent, the code adds the contract and certificate findings of every supplier,
  also one the agent skipped.
- **Fallback.** No model, a network error or too many steps (`MAX_STEPS = 40`): the findings come from
  the tools alone, with a warning in the log. The case never stops.
- **Scope.** A note keeps the strictest access scope of its sources, so the follow-ups filter it by role.
- **Rules in the prompt** (same as `find_conflicts`): the latest contract version applies; contract >
  qualification record > notice > e-mail; an e-mail never overrides a contractual figure, except the
  team rule for capacity (a lower capacity stated by the supplier itself is used for planning); an expired
  certificate means no new orders.

## Tests (`tests/test_contract_agent.py`, 11, no Azure needed)
Terms and certificates with their sources · Atlas v3 not v2 · nothing for a viewer · every supplier
covered without a model · notes with invented / unseen sources dropped · a note can cite an e-mail the
agent read · the injected Helios notice never reaches the model · tools refuse suppliers outside the case ·
the real `create_agent` loop with a scripted model.

Graph tests never call Azure for the agent: `conftest.py` fakes `analyze_contracts`.
