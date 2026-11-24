"""DOCUMENT RETRIEVAL: pgvector, ChromaDB and hybrid search. OWNER: role 3.

Rules for the real version:
  - filter by the user's role (users.csv document_scopes): a viewer only sees 'public';
    only finance_controller sees 'finance-confidential';
  - only the newest version of a document (Atlas contract v3, not v2);
  - every retrieved text goes through guards.check_injection() before an LLM sees it.

The first part of this file is shared by scripts/index_documents.py and the search, so
indexing and searching always use the same names, the same parsing and the same
embedding model.

STUB (still): search_documents returns no documents and find_conflicts the four golden
conflicts. Keep the signatures.
"""

import csv
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import psycopg
from langchain_openai import AzureOpenAIEmbeddings

from supplyguard_ai.auth import scopes_for_role
from supplyguard_ai.config import data_dir, database_url, require
from supplyguard_ai.state import Conflict, Evidence

# ---------------------------------------------------------------------------
# Shared by indexing and search
# ---------------------------------------------------------------------------
PG_TABLE = "documents"                    # pgvector table in the supplyguard database
CHROMA_COLLECTION = "supplyguard_documents"

# Front-matter keys that get their own column; anything else (component_id,
# stated_delay_days, disruption_type ...) is kept in `extra`.
_COLUMNS = {"source_id", "doc_type", "title", "supplier_id", "version", "effective_date",
            "access_scope", "status"}
_VERSION_SUFFIX = re.compile(r"-v\d+$")   # DOC-CON-S001-v3 -> DOC-CON-S001


def parse_document(path: Path) -> dict:
    """Read one markdown document: the front matter becomes metadata, the rest is the text."""
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path.name}: no front matter")
    _, header, body = raw.split("---", 2)

    meta = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")   # first ':' only: titles contain ':' too
        meta[key.strip()] = value.strip()

    source_id = meta["source_id"]
    return {
        "source_id": source_id,
        "base_id": _VERSION_SUFFIX.sub("", source_id),   # same id for every version
        "doc_type": meta["doc_type"],
        "title": meta.get("title", ""),
        "supplier_id": meta.get("supplier_id") or None,  # procedures, e-mails: no supplier
        "version": int(meta.get("version") or 1),
        "effective_date": date.fromisoformat(meta["effective_date"]),
        "access_scope": meta.get("access_scope") or "internal",
        "status": meta.get("status") or "current",       # Atlas v2 says 'superseded'
        "path": path.relative_to(data_dir()).as_posix(),
        "content": body.strip(),                         # kept as is: the guard must see everything
        "extra": {k: v for k, v in meta.items() if k not in _COLUMNS},
    }


def load_documents() -> list[dict]:
    """All documents listed in documents_index.csv, checked against their own front matter."""
    root = data_dir()
    with (root / "documents" / "documents_index.csv").open(newline="", encoding="utf-8") as f:
        index = list(csv.DictReader(f))
    docs = []
    for row in index:
        doc = parse_document(root / row["path"])
        # The access scope decides who may read a document: never index a mismatch.
        if doc["source_id"] != row["source_id"] or doc["access_scope"] != row["access_scope"]:
            raise ValueError(f"{row['path']}: front matter does not match documents_index.csv")
        docs.append(doc)
    return docs


def embedding_text(doc: dict) -> str:
    """What gets embedded: the title carries the supplier and topic, so it goes first."""
    return f"{doc['title']}\n\n{doc['content']}"


@lru_cache(maxsize=1)
def get_embeddings() -> AzureOpenAIEmbeddings:
    """The one embedding model, for indexing AND queries (vectors must come from the same model)."""
    settings = require("AZURE_EMBEDDING_ENDPOINT", "AZURE_EMBEDDING_API_KEY",
                       "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "OPENAI_API_VERSION")
    return AzureOpenAIEmbeddings(
        azure_endpoint=settings["AZURE_EMBEDDING_ENDPOINT"],
        api_key=settings["AZURE_EMBEDDING_API_KEY"],
        azure_deployment=settings["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        api_version=settings["OPENAI_API_VERSION"],
    )


def chroma_client():
    """HTTP client for the ChromaDB container (imported here: chromadb is slow to import)."""
    import chromadb

    return chromadb.HttpClient(host=os.getenv("CHROMA_HOST", "localhost"),
                               port=int(os.getenv("CHROMA_PORT", "8001")))


def to_pgvector(vector: list[float]) -> str:
    """A vector as pgvector text ('[0.1,0.2,...]'), used with %s::vector in SQL."""
    return "[" + ",".join(str(x) for x in vector) + "]"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
# Filters a caller may use, and the column each one reads. A whitelist: the key ends
# up in the SQL text, so only names from this dict are ever accepted.
_FILTER_COLUMNS = {"doc_type": "doc_type", "supplier_id": "supplier_id", "base_id": "base_id"}

_SEARCH_SQL = """
WITH latest AS (                                -- 1. newest version of every document
    SELECT DISTINCT ON (base_id) *
    FROM {table}
    ORDER BY base_id, version DESC, effective_date DESC
)
SELECT source_id, doc_type, title, version, effective_date, access_scope, content,
       1 - (embedding <=> %(query)s::vector) AS score
FROM latest
WHERE access_scope = ANY(%(scopes)s)            -- 2. only what this role may read
  AND status <> 'superseded'
  {filters}                                     -- 3. optional filters (doc_type, supplier)
ORDER BY embedding <=> %(query)s::vector        -- 4. most similar first
LIMIT %(k)s
"""


def _filter_sql(filters: dict | None) -> tuple[str, dict]:
    """{'doc_type': 'contract', 'supplier_id': ['S002', 'S004']} -> SQL + parameters."""
    clauses, params = [], {}
    for key, value in (filters or {}).items():
        if key not in _FILTER_COLUMNS:
            raise ValueError(f"Unknown filter {key!r}; allowed: {sorted(_FILTER_COLUMNS)}")
        params[f"f_{key}"] = [value] if isinstance(value, str) else list(value)
        clauses.append(f"AND {_FILTER_COLUMNS[key]} = ANY(%(f_{key})s)")
    return " ".join(clauses), params


def _connect() -> psycopg.Connection:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env.")
    return psycopg.connect(url)


def search_documents(query: str, user_role: str, filters: dict | None = None, k: int = 5) -> list[Evidence]:
    """Top-k documents for the query that this role may read, newest version only.

    The text is returned as it is: the caller runs guards.check_injection() on every
    claim before an LLM sees it.
    """
    where, params = _filter_sql(filters)        # before any I/O: a bad filter fails at once
    params |= {
        "query": to_pgvector(get_embeddings().embed_query(query)),
        "scopes": scopes_for_role(user_role),
        "k": max(1, min(k, 20)),
    }
        with _connect() as conn:
        try:
            rows = conn.execute(_SEARCH_SQL.format(table=PG_TABLE, filters=where), params).fetchall()
        except psycopg.errors.UndefinedTable:
            raise RuntimeError(f"The document index '{PG_TABLE}' does not exist yet. "
                               "Run once: uv run python scripts/index_documents.py") from None
        return [
        Evidence(
            claim=f"{title}\n{content}",
            source_id=source_id,
            doc_type=doc_type,
            version=str(version),
            effective_date=effective_date.isoformat(),
            access_scope=access_scope,
        )
        for source_id, doc_type, title, version, effective_date, access_scope, content, _score in rows
    ]


def find_conflicts(evidence: list[Evidence]) -> list[Conflict]:
    """Sources that disagree, resolved with policies.json source_precedence."""
    return [
        Conflict(topic="Atlas delay", values={"supplier notice": "12 days", "supplier e-mail": "16 days"},
                 chosen="12 days", reason="STUB: supplier notice outranks supplier e-mail"),
        Conflict(topic="Helios capacity", values={"contract": "4,000/month", "e-mail": "1,500/month"},
                 chosen="1,500/month", reason="STUB: role 3 decides with source precedence and recency"),
        Conflict(topic="Cordillera expedite fee", values={"contract": "6%", "e-mail": "10%"},
                 chosen="6%", reason="STUB: contract outranks e-mail"),
        Conflict(topic="Atlas contract version", values={"v2": "10 days", "v3": "14 days"},
                 chosen="v3", reason="STUB: v2 is superseded"),
    ]
