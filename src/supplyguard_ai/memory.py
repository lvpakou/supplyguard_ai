"""INCIDENT MEMORIES (pgvector, separate table). OWNER: role 3.

The system's experience: approved resolutions of past incidents.
  - seed_memories():   the trainer's 40 approved memories -> pgvector (run by scripts/index_documents.py)
  - similar_cases():   past resolutions similar to a new incident (for the evidence / the report)
  - save_resolution(): the summary of a case closed WITH approval, stored for future cases

The table is never dropped: it also holds the resolutions of our own approved cases, and a
re-index must not lose them. Seeding updates the trainer's rows; saving a case twice keeps the first.
"""

import json
import logging

import psycopg

from supplyguard_ai.auth import scopes_for_role
from supplyguard_ai.config import data_dir, database_url
from supplyguard_ai.state import CaseState, Evidence
from supplyguard_ai.tools.retrieval import (MIN_SIMILARITY, _embed_query, _supplier_names,
                                            get_embeddings, to_pgvector)

MEMORY_TABLE = "incident_memories"
log = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    memory_id    text PRIMARY KEY,          -- MEM-HC-001, or MEM-CASE-<case_id> for our own cases
    case_id      text NOT NULL UNIQUE,      -- one memory per case
    component_id text,
    supplier_id  text,
    strategy     text,
    summary      text NOT NULL,
    access_scope text NOT NULL,
    source       text NOT NULL,             -- 'trainer' or 'approved case'
    created_at   timestamptz NOT NULL DEFAULT now(),
    embedding    vector({dim}) NOT NULL
)"""

_INSERT_SQL = """
INSERT INTO {table} (memory_id, case_id, component_id, supplier_id, strategy, summary,
                     access_scope, source, embedding)
VALUES (%(memory_id)s, %(case_id)s, %(component_id)s, %(supplier_id)s, %(strategy)s, %(summary)s,
        %(access_scope)s, %(source)s, %(embedding)s::vector)
ON CONFLICT {on_conflict}"""

_SIMILAR_SQL = """
SELECT memory_id, case_id, component_id, supplier_id, strategy, summary, access_scope, source,
       1 - (embedding <=> %(query)s::vector) AS similarity
FROM {table}
WHERE access_scope = ANY(%(scopes)s)
ORDER BY embedding <=> %(query)s::vector
LIMIT %(k)s"""


def _connect() -> psycopg.Connection:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env.")
    return psycopg.connect(url)


def _ensure_table(conn: psycopg.Connection, dim: int) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute(_CREATE_SQL.format(table=MEMORY_TABLE, dim=dim))


def memory_text(memory: dict) -> str:
    """What gets embedded: the summary, plus the component, supplier and strategy it does not name."""
    supplier = memory.get("supplier_id") or ""
    name = _supplier_names().get(supplier, supplier)
    return (f"{memory['summary']} Component {memory.get('component_id') or 'unknown'}, "
            f"supplier {name} ({supplier}). Strategy: {memory.get('strategy') or 'unknown'}.")


def load_seed_memories() -> list[dict]:
    """The trainer's approved memories (structured/approved_incident_memories.jsonl)."""
    path = data_dir() / "structured" / "approved_incident_memories.jsonl"
    with path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [
        {"memory_id": r["memory_id"], "case_id": r["case_id"], "component_id": r.get("component_id"),
         "supplier_id": r.get("supplier_id"), "strategy": r.get("strategy"),
         "summary": r["approved_summary"], "access_scope": r.get("access_scope") or "internal",
         "source": "trainer"}
        for r in rows
    ]


def seed_memories() -> int:
    """The trainer's memories -> pgvector. Safe to re-run: updates them, keeps our own cases."""
    memories = load_seed_memories()
    vectors = get_embeddings().embed_documents([memory_text(m) for m in memories])
    upsert = ("(memory_id) DO UPDATE SET summary = EXCLUDED.summary, strategy = EXCLUDED.strategy, "
              "access_scope = EXCLUDED.access_scope, embedding = EXCLUDED.embedding")
    with _connect() as conn:
        _ensure_table(conn, len(vectors[0]))
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SQL.format(table=MEMORY_TABLE, on_conflict=upsert),
                            [m | {"embedding": to_pgvector(v)} for m, v in zip(memories, vectors)])
        return conn.execute(f"SELECT count(*) FROM {MEMORY_TABLE}").fetchone()[0]


def similar_cases(text: str, k: int = 3, user_role: str | None = None) -> list[dict]:
    """Approved past resolutions similar to this incident, most similar first.

    Pass the case's user_role. The memories are 'internal': without a role (least access) the
    answer is empty. Memories below MIN_SIMILARITY are left out: "similar" must mean similar.
    """
    params = {"query": to_pgvector(list(_embed_query(text))),
              "scopes": scopes_for_role(user_role or ""), "k": max(1, min(k, 10))}
    with _connect() as conn:
        try:
            cursor = conn.execute(_SIMILAR_SQL.format(table=MEMORY_TABLE), params)
        except psycopg.errors.UndefinedTable:
            raise RuntimeError(f"The memory table '{MEMORY_TABLE}' does not exist yet. "
                               "Run once: uv run python scripts/index_documents.py") from None
        columns = [column.name for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return [row | {"similarity": round(float(row["similarity"]), 3)}
            for row in rows if row["similarity"] >= MIN_SIMILARITY]


def as_evidence(memory: dict) -> Evidence:
    """A memory as evidence, with its provenance (source_id = memory_id), for the case and the report."""
    return Evidence(claim=f"Past case {memory['case_id']}: {memory['summary']}",
                    source_id=memory["memory_id"], doc_type="incident_memory",
                    access_scope=memory["access_scope"])


def resolution_summary(state: CaseState) -> str:
    """One line in the style of the trainer's memories, plus what this case taught us.

    Built only from our own structured fields: never from the user's message or a warning's text,
    so an injection can never be stored and handed to a future case (memory poisoning).
    """
    facts, rec = state.facts, state.recommendation
    strategies = " + ".join(f"{o.strategy} {o.title}" for o in rec.options)
    line = (f"delay ({facts.delay_days} d) of {facts.component_id} from "
            f"{_supplier_names().get(facts.supplier_id or '', facts.supplier_id)} "
            f"resolved with '{strategies}' at EUR {rec.total_cost_eur:,.0f}.")
    lessons = [f"{c.topic}: used {c.chosen}" for c in state.conflicts]
    ignored = sum(w.startswith("Ignored ") for w in state.warnings)
    if ignored:
        lessons.append(f"{ignored} document(s) ignored as prompt injection")
    if rec.uncovered_units:
        lessons.append(f"{rec.uncovered_units} units not covered ({rec.residual_handling or 'no residual plan'})")
    return line + (f" Lessons: {'; '.join(lessons)}." if lessons else "")


def save_resolution(state: CaseState) -> None:
    """Store the approved summary of a closed case, once, for future similar cases.

    Only a case whose plan was APPROVED and executed without a refusal is stored. Saving the
    same case again (the report node re-runs after a restart) keeps the first memory.
    A failure is logged, never raised: the case is already closed and its report must still come.
    """
    if not (state.approval and state.approval.status == "approved" and state.recommendation and state.facts):
        return None
    if any(result.status == "refused" for result in state.executions):
        return None
    memory = {"memory_id": f"MEM-CASE-{state.case_id}", "case_id": state.case_id,
              "component_id": state.facts.component_id, "supplier_id": state.facts.supplier_id,
              "strategy": " + ".join(o.title for o in state.recommendation.options),
              "summary": resolution_summary(state), "access_scope": "internal", "source": "approved case"}
    try:
        vector = get_embeddings().embed_documents([memory_text(memory)])[0]
        with _connect() as conn:
            _ensure_table(conn, len(vector))
            conn.execute(_INSERT_SQL.format(table=MEMORY_TABLE, on_conflict="DO NOTHING"),
                         memory | {"embedding": to_pgvector(vector)})
    except Exception as error:
        log.warning("Could not save the memory of case %s: %s", state.case_id, error)
    return None
