# SupplyGuard AI

An agentic assistant for supply-chain disruptions: capstone of the Code.Hub × PwC Agentic AI Bootcamp.
A procurement manager describes a disruption in a chat. The app investigates the impact, collects evidence
with sources, checks supplier dependencies, compares recovery options with deterministic tools, and asks
people to approve the **exact** plan before anything is ordered in a simulated procurement system.
All data is fictional (`data/`).

## What you need
- **Docker Desktop** (running)
- **uv** (Python package manager): https://docs.astral.sh/uv/ (it installs Python 3.12 itself)
- **Azure OpenAI** keys: a chat model and an embedding model
- Optional: a LangSmith API key (tracing)

## Run it from scratch
**1. Install**
```bash
git clone https://github.com/lvpakou/supplyguard_ai.git && cd supplyguard_ai
uv sync
```

**2. Settings**: copy the template, then fill in `.env` (never commit it: the repo is public)
```bash
cp .env.example .env
uv run python -m chainlit create-secret    # paste the printed CHAINLIT_AUTH_SECRET=... line into .env
```
In `.env` fill: the 4 `AZURE_OPENAI_*` / `OPENAI_API_VERSION` keys, the 3 `AZURE_EMBEDDING*` keys, and
`DEMO_PASSWORD` (the login password for every demo user). Avoid `$` in values: Docker cuts it off.
Everything else already has a working default.

**3. Start the services** (Postgres+pgvector, Neo4j, ChromaDB, risk service, 2 MCP servers)
```bash
docker compose up -d
```

**4. Load the data** (once; again only if the data or these scripts change)
```bash
uv run python scripts/load_postgres.py     # CSV tables -> Postgres
uv run python scripts/index_documents.py   # 212 documents + 40 incident memories -> pgvector + ChromaDB (uses Azure)
uv run python scripts/load_graph.py        # supplier / component / product graph -> Neo4j
```

**5. Start the chat**
```bash
docker compose --profile app up -d --build             # in Docker -> http://localhost:8010  (Windows: use this)
uv run python -m chainlit run src/supplyguard_ai/chat_app.py   # or locally (macOS / Linux) -> http://localhost:8000
```

**6. Sign in** with a user from `data/config/users.csv` and your `DEMO_PASSWORD`:

| User | Role | Can |
|---|---|---|
| `u-pm-01` | procurement manager | start cases, approve (with the finance controller above EUR 25k) |
| `u-fc-01` | finance controller | approve, also sees finance-confidential documents |
| `u-an-01`, `u-ic-01` | analyst, incident coordinator | start cases, ask questions |
| `u-ro-01` | viewer | public documents only, cannot approve |

## Try it: the MC-17 case
1. As `u-pm-01`, paste:
   > Supplier Atlas Components has announced a 12-day delay for component MC-17. Determine which customer
   > commitments are at risk, investigate alternative sources, and recommend a recovery plan. Additional
   > spending must not exceed €75,000. Do not create a purchase order without approval.
2. A checklist shows each step as it runs. After about 1 minute (two agents run on Azure) you see:
   - **impact**: 3,200 of 5,200 units usable, shortfall 5,350, 77 orders at risk;
   - **evidence**: the conflicts and how they were settled; every document, and the agents' notes, open in
     the side panel;
   - **options compared**: Helios and Borealis are rejected, with the reasons; Delta is flagged because it
     shares Atlas's upstream manufacturer;
   - the **approval request**: about EUR 30,378, with what to check before approving.
3. Click **Approve**: "Still needed: finance_controller". Nothing is ordered yet.
4. In a private window sign in as `u-fc-01`, click **Open** on the waiting request, then **Approve**.
   The actions run once in the procurement system; a short summary shows what was done, and the full
   incident report opens in the side panel.
5. Ask follow-ups: *Why did you reject Supplier Helios?* · *What changes if we increase the spending limit to €90,000?*
6. Also try:
   - **Change** on the approval card ("make the quantity 6,000"): you get a new plan and a new approval;
   - only "Atlas" in the message: the app asks which supplier you mean;
   - **resume**: lists your saved cases, also after a restart.

**Before a demo**, clear old cases and restore the data:
```bash
uv run python scripts/reset_demo.py --yes && uv run python scripts/load_postgres.py
```
Full script with who says what: `docs/demo_script.md`.

## Tests, evaluation, benchmark
```bash
uv run python -m pytest -q                                   # all tests
uv run python scripts/run_evaluation.py --local              # the trainer's 105 cases, score per category (slow: uses Azure)
uv run python scripts/run_evaluation.py --local --no-judge   # faster, without the LLM-as-judge
uv run python scripts/benchmark_retrieval.py                 # pgvector vs ChromaDB vs hybrid
uv run python -m supplyguard_ai.tracing                      # check the LangSmith settings
```

## Services
| Service | Address on your laptop |
|---|---|
| Chat (Docker) | http://localhost:8010 |
| Postgres + pgvector | `localhost:5433`, user/password/db `supplyguard` |
| Neo4j | browser http://localhost:7475 · bolt `localhost:7688` · `neo4j` / `supplyguard-password` |
| ChromaDB | http://localhost:8001 |
| Risk service | http://localhost:8099/alerts?region=TW |
| Procurement MCP / Risk MCP | http://localhost:8002/mcp · http://localhost:8003/mcp |

## How it works
The workflow is a LangGraph graph (`src/supplyguard_ai/graph.py`). It saves its state in Postgres after
every step, so a case survives a restart and never runs an action twice.
```
intake → (clarify) → impact → evidence → dependencies → options → challenge → approval ⏸
                                                           ↑                    │
                                                           └──── changed ───────┤
                                     report ← rejected ─────────────────────────┤
                                     report ← execute ← approved ───────────────┘
                                       ↓
                                    followup ⏸ (loops)
```
| Step | What happens | Code |
|---|---|---|
| intake | The LLM extracts supplier, component, delay and cap; asks if something is unclear; injection check | `nodes.py` |
| impact | Usable stock, products, orders, days of cover, shortfall (plain Python) | `tools/impact.py`, `tools/inventory.py` |
| evidence | Hybrid search filtered by role; conflicts by source precedence; similar past cases; **contract agent** (`create_agent`) | `tools/retrieval.py`, `memory.py`, `agents/contract_agent.py` |
| dependencies | Alternatives from Neo4j, risk alerts (MCP); **Deep Agent** (planning, files, skill, subagents) checks each supplier's upstream | `tools/graph_queries.py`, `agents/investigator.py` |
| options / challenge | Strategies A–E costed; policy checks (cap, certificate, capacity) | `tools/options.py`, `tools/critic.py` |
| approval | Exact actions; approval tiers; both roles must sign; bound to the payload hash; audit trail | `approval.py`, `chat_app.py` |
| execute / report | Simulated procurement system via MCP, idempotent; incident report | `integrations/`, `report.py` |
| followup | Answers from the saved case; what-ifs recomputed with the tools | `followup.py` |

More detail, in `docs/`:
- `architecture.md`, `business_value.md`, `demo_script.md`, `evaluation.md`
- `approval_and_guardrails.md`, `red_team.md`, `followups.md`
- `retrieval.md`, `memories.md`, `contract_agent.md`, `investigator.md`, `graph_and_mcp.md`

## Troubleshooting
| Problem | Fix |
|---|---|
| Local chat on **Windows** shows nothing after a message | Known event-loop limit of async Postgres on Windows: run the chat in Docker (step 5) |
| Docker build skipped: *"additional privileges requested"* | Build the image yourself, then start without building: `docker build -t <folder>-app .` → `docker compose --profile app up -d --no-build` |
| Login fails | `.env` needs `CHAINLIT_AUTH_SECRET` and `DEMO_PASSWORD`; in Docker, no `$` in values |
| *"document index does not exist"* | `uv run python scripts/index_documents.py` |
| Empty supplier table / no dependency notes | `uv run python scripts/load_graph.py` |
| *"Connection error"* in the logs | Azure is unreachable (network/VPN). The agents fall back to their code checks; search needs Azure |
| `pytest` blocked on Windows | Use `uv run python -m pytest` |

## Team and ownership
| Role | Person | Main files |
|---|---|---|
| 1 · Platform, flow & evaluation | Nikos | `graph.py`, `nodes.py`, `state.py`, `config.py`, `llm.py`, `tracing.py`, `evaluation.py`, `docker-compose.yml`, `tests/conftest.py`, `README.md` |
| 2 · Data & calculations | Marianna | `tools/inventory.py`, `tools/impact.py`, `tools/tables.py`, `tools/options.py`, `tools/critic.py`, `report.py`, `scripts/load_postgres.py` |
| 3 · Documents, retrieval & contract agent | Louiza | `tools/retrieval.py`, `auth.py`, `memory.py`, `agents/contract_agent.py`, `scripts/index_documents.py` |
| 4 · Graph, MCP & Deep Agent | Christos | `tools/graph_queries.py`, `integrations/`, `mcp_servers/`, `agents/investigator.py`, `data/external_info_service/`, `scripts/load_graph.py` |
| 5 · UI, approval & safety | Nikos G. | `chat_app.py`, `chat_views.py`, `approval.py`, `followup.py`, `tools/guards.py` |

**How we work:**
- Create a branch from `main` (`<name>-<topic>`).
- Keep PRs small; `uv run python -m pytest -q` must pass; one teammate reviews.
- Pull `main` into your branch before the PR.
- Never commit `.env` or secrets.

## Data (`data/`, from the trainer: load it, don't change it)
| Folder | Contents |
|---|---|
| `structured/` | CSV tables |
| `documents/` | 212 documents with provenance |
| `graph/` | Neo4j CSVs |
| `evaluation/` | Golden scenario + 105 cases |
| `config/` | Policies, users |
| `external_service/` | Risk feed |

`data/README.md` lists the planted traps: reserved or quarantined stock, an expired certificate, a shared
upstream, conflicting sources, a prompt injection, and the ambiguous "Atlas".
