# SupplyGuard AI

Agentic supply chain disruption & recovery assistant — capstone of the Code.Hub × PwC Agentic AI Bootcamp.
A procurement manager describes a disruption in the chat; the system investigates impact, gathers
evidence, compares recovery options with deterministic tools, and asks a human to approve the exact
plan before anything is executed in a simulated procurement system. All data is fictional (`data/`).

## Quick start
```bash
cp .env.example .env            # fill in the Azure keys (never commit .env: the repo is public)
docker compose up -d            # Postgres+pgvector, Neo4j, ChromaDB, risk service
uv sync
uv run pytest -q                # the skeleton runs end to end with stubs
uv run chainlit run src/supplyguard_ai/chat_app.py
```
| Service | Address on your laptop |
|---|---|
| Postgres (+pgvector) | `localhost:5433` (user/pass/db `supplyguard`) |
| Neo4j browser / bolt | http://localhost:7475 · `bolt://localhost:7688` (`neo4j` / `supplyguard-password`) |
| ChromaDB | http://localhost:8001 |
| External risk service | http://localhost:8099/alerts?region=TW |
| Chat in Docker | `docker compose --profile app up -d` → http://localhost:8010 |

## The workflow (`src/supplyguard_ai/graph.py`)
```
intake → (clarify) → impact → evidence → dependencies → options → challenge → approval ⏸
                                                           ↑                    │
                                                           └──── changed ───────┤
                                     report ← rejected ─────────────────────────┤
                                     report ← execute ← approved ───────────────┘
                                       ↓
                                    followup ⏸ (loops)
```

## Who owns what (only the owner changes these files)
| Role | Person | Files |
|---|---|---|
| 1 · Platform, flow & evaluation | Nikos | `docker-compose.yml`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `state.py`, `config.py`, `llm.py`, `graph.py`, `nodes.py`, `scripts/run_evaluation.py`, `tests/test_smoke.py`, `README.md` |
| 2 · Data & calculations | ? | `tools/inventory.py`, `tools/impact.py`, `tools/options.py`, `tools/critic.py`, `report.py`, `scripts/load_postgres.py` |
| 3 · Documents, retrieval & contract agent | ? | `tools/retrieval.py`, `auth.py`, `memory.py`, `agents/contract_agent.py`, `scripts/index_documents.py` |
| 4 · Graph, MCP & Deep Agent | ? | `tools/graph_queries.py`, `integrations/`, `mcp_servers/`, `agents/investigator.py`, `scripts/load_graph.py` |
| 5 · UI, approval & safety | ? | `chat_app.py`, `approval.py`, `followup.py`, `tools/guards.py` |

Each owner also writes their part of `docs/` and their own tests (`tests/test_<area>.py`).

**Stubs:** every module already has its final function signature and returns the trainer's golden
MC-17 numbers (`data/evaluation/golden_scenario.json`), so the whole flow runs today. Replace the
stub inside your module; keep the signature. Need a change in `state.py` or a new library? Ask role 1.

## How we work
1. `git switch main && git pull`, then `git switch -c <name>-<topic>` (e.g. `maria-impact`).
2. Small PRs (half a day of work at most); `uv run pytest -q` must pass; one teammate reviews.
3. Before a PR: `git pull origin main` into your branch.
4. Integration checkpoints: everyone merges, then we run the MC-17 demo together.
5. Never commit `.env`. Never put secrets in code.

## Data (`data/`, from the trainer — load it, don't change it)
`structured/` CSV tables · `documents/` 212 markdown docs with provenance · `graph/` Neo4j CSVs + `load.cypher` ·
`evaluation/` golden scenario + 105 cases · `config/` policies, users, procurement contract · `external_service/` risk feed.
See `data/README.md` for the planted traps (reserved/quarantined stock, expired certificate, shared upstream,
conflicting sources, prompt injection, ambiguous "Atlas").

## Seed Neo4j
run : docker compose up -d neo4j
and then: uv run python scripts/load_graph.py