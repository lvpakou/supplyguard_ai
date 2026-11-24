# SupplyGuard AI

Agentic supply chain disruption & recovery assistant — capstone of the Code.Hub × PwC Agentic AI Bootcamp.
A procurement manager describes a disruption in the chat; the system investigates impact, gathers
evidence, compares recovery options with deterministic tools, and asks a human to approve the exact
plan before anything is executed in a simulated procurement system. All data is fictional (`data/`).

## First-time setup
```bash
cp .env.example .env            # fill in Azure keys + embeddings (never commit .env: the repo is public)
uv run chainlit create-secret   # put the printed CHAINLIT_AUTH_SECRET line in .env, and set DEMO_PASSWORD
docker compose up -d            # Postgres+pgvector, Neo4j, ChromaDB, risk service
uv sync
uv run python scripts/load_postgres.py     # role 2: the CSV tables -> Postgres
uv run python scripts/index_documents.py   # role 3: the 212 documents -> pgvector + ChromaDB
uv run pytest -q                           # fast tests (no Azure needed)
uv run chainlit run src/supplyguard_ai/chat_app.py   # sign in with e.g. u-pm-01 + DEMO_PASSWORD
```
Run the two load scripts again after pulling changes to them. Demo users (`data/config/users.csv`):
`u-pm-01` procurement manager · `u-fc-01` finance controller · `u-ro-01` read-only viewer.
| Service | Address on your laptop |
|---|---|
| Postgres (+pgvector) | `localhost:5433` (user/pass/db `supplyguard`) |
| Neo4j browser / bolt | http://localhost:7475 · `bolt://localhost:7688` (`neo4j` / `supplyguard-password`) |
| ChromaDB | http://localhost:8001 |
| External risk service | http://localhost:8099/alerts?region=TW |
| Chat in Docker | `docker compose --profile app up -d` → http://localhost:8010 |

## Evaluation and tracing
```bash
uv run python scripts/run_evaluation.py --local              # the trainer's 105 cases, score per category
uv run python scripts/run_evaluation.py --local --no-judge   # faster, without the LLM-as-judge
uv run python -m supplyguard_ai.tracing                      # check the LangSmith settings
```
Results and what each category checks: `docs/evaluation.md`.

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
| 1 · Platform, flow & evaluation | Nikos | `docker-compose.yml`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `state.py`, `config.py`, `llm.py`, `graph.py`, `nodes.py`, `tracing.py`, `evaluation.py`, `scripts/run_evaluation.py`, `tests/conftest.py`, `README.md` |
| 2 · Data & calculations | Marianna | `tools/inventory.py`, `tools/impact.py`, `tools/tables.py`, `tools/options.py`, `tools/critic.py`, `report.py`, `scripts/load_postgres.py` |
| 3 · Documents, retrieval & contract agent | Louiza | `tools/retrieval.py`, `auth.py`, `memory.py`, `agents/contract_agent.py`, `scripts/index_documents.py` |
| 4 · Graph, MCP & Deep Agent | Christos | `tools/graph_queries.py`, `integrations/`, `mcp_servers/`, `agents/investigator.py`, `scripts/load_graph.py` |
| 5 · UI, approval & safety | Nikos G. | `chat_app.py`, `approval.py`, `followup.py`, `tools/guards.py` |

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
