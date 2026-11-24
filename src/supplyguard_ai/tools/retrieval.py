"""DOCUMENT RETRIEVAL: pgvector, ChromaDB and hybrid search. OWNER: role 3.

Rules for the real version:
  - filter by the user's role (users.csv document_scopes): a viewer only sees 'public';
    only finance_controller sees 'finance-confidential';
  - only the newest version of a document (Atlas contract v3, not v2);
  - every retrieved text goes through guards.check_injection() before an LLM sees it.

The first part of this file is shared by scripts/index_documents.py and the search, so
indexing and searching always use the same names, the same parsing and the same
embedding model.

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
from supplyguard_ai.config import data_dir, database_url, policies, require
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


# ---------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------
# policies.json names the source types in order of authority; this maps our doc_type to them.
# Procedures, incident reports and the finance sheet are not supplier statements: never compared.
_PRECEDENCE_NAMES = {
    "contract": "contract (latest version)",
    "qualification": "qualification record",
    "supplier_notice": "supplier notice",
    "email": "supplier e-mail",
}
_SAME_INCIDENT_DAYS = 7   # delay statements further apart are separate incidents, not a conflict
_SCOPE_RANK = {"public": 0, "internal": 1, "procurement": 2, "finance-confidential": 3}

# Which facts we compare, where each one may appear, and how it is written there.
_PATTERNS = {
    "lead_time_days": {
        "contract": [r"lead time[^:]*:\s*\**(\d+)\**\s*calendar days"],
        "email": [r"(\d+)-day lead time", r"lead time (\d+) days"],
    },
    "monthly_capacity": {
        "contract": [r"monthly capacity[^:]*:\s*\**([\d,]+)\**\s*units"],
        "email": [r"([\d,]+)\**\s*units (?:per month|/month)"],
    },
    "expedite_fee_pct": {
        "contract": [r"expedite[^.]*?fee:?\s*(\d+(?:\.\d+)?)%"],
        "email": [r"charge\s*\**(\d+(?:\.\d+)?)%"],
    },
    "delay_days": {                      # notices: the stated_delay_days front-matter field
        "email": [r"delay\b[^.]*?(\d+)\**\s*days"],
    },
}
_FORMATS = {
    "lead_time_days": ("lead time", "{:,} days"),
    "monthly_capacity": ("monthly capacity", "{:,}/month"),
    "expedite_fee_pct": ("expedite fee", "{:g}%"),
    "delay_days": ("delay", "{:,} days"),
}


@lru_cache
def _documents_by_id() -> dict[str, dict]:
    return {doc["source_id"]: doc for doc in load_documents()}


@lru_cache
def _supplier_names() -> dict[str, str]:
    with (data_dir() / "structured" / "suppliers.csv").open(newline="", encoding="utf-8") as f:
        return {row["supplier_id"]: row["name"] for row in csv.DictReader(f)}


def _rank(doc_type: str) -> int:
    """0 = most authoritative, following policies.json source_precedence."""
    return policies()["source_precedence"].index(_PRECEDENCE_NAMES[doc_type])


def _number(text: str) -> float:
    value = float(text.replace(",", ""))
    return int(value) if value.is_integer() else value


def extract_facts(doc: dict) -> dict[str, float]:
    """The comparable facts one document states, e.g. {'monthly_capacity': 1500, 'lead_time_days': 21}."""
    facts = {}
    if doc["doc_type"] == "supplier_notice" and doc["extra"].get("stated_delay_days"):
        facts["delay_days"] = _number(doc["extra"]["stated_delay_days"])
    for attribute, by_type in _PATTERNS.items():
        for pattern in by_type.get(doc["doc_type"], []):
            match = re.search(pattern, doc["content"], re.IGNORECASE)
            if match:
                facts[attribute] = _number(match.group(1))
                break
    return facts


def _component(doc: dict) -> str | None:
    """Delays belong to one component: from the front matter, else the first MC-.. in the text."""
    found = re.search(r"\bMC-\d+\b", doc["content"])
    return doc["extra"].get("component_id") or (found.group(0) if found else None)


def _supplier(doc: dict) -> str:
    sid = doc["supplier_id"]
    return f"{_supplier_names().get(sid, sid)} ({sid})"


def _show(attribute: str, value: float) -> str:
    return _FORMATS[attribute][1].format(value)


def _choose(attribute: str, claims: list[tuple[dict, float]]) -> tuple[str, str]:
    """The value we use and why. claims: (document, value), at least two different values."""
    ordered = sorted(claims, key=lambda c: (_rank(c[0]["doc_type"]), -c[0]["effective_date"].toordinal()))
    best_doc, best_value = ordered[0]
    others = [doc for doc, value in ordered[1:] if value != best_value]
    if all(doc["doc_type"] == best_doc["doc_type"] for doc in others):
        reason = f"same source type: {best_doc['source_id']} is the most recent ({best_doc['effective_date']})"
    else:
        lower = ", ".join(sorted({_PRECEDENCE_NAMES[d["doc_type"]] for d in others}))
        reason = f"{_PRECEDENCE_NAMES[best_doc['doc_type']]} outranks {lower} (policies.json source_precedence)"

    # Team rule: when the supplier itself states in writing a LOWER capacity than the contract,
    # the contract stays the official figure but we plan with the lower one.
    lowest_doc, lowest = min(claims, key=lambda c: c[1])
    if attribute == "monthly_capacity" and lowest < best_value and lowest_doc["doc_type"] != "contract":
        return (f"{_show(attribute, lowest)} for planning",
                f"{reason}, so {_show(attribute, best_value)} stays the official figure; but the supplier "
                f"states in writing ({lowest_doc['source_id']}) that it can only deliver "
                f"{_show(attribute, lowest)}, and planning on more would leave production short")
    if attribute == "delay_days" and max(v for _, v in claims) > best_value:
        reason += f"; the longer {_show(attribute, max(v for _, v in claims))} is reported as a risk"
    return _show(attribute, best_value), reason


def _version_conflicts(evidence_docs: list[dict]) -> list[Conflict]:
    """Older versions of retrieved documents: search hides them, but the change must be reported."""
    conflicts = []
    for doc in evidence_docs:
        older = [d for d in _documents_by_id().values()
                 if d["base_id"] == doc["base_id"] and d["version"] < doc["version"]
                 and _SCOPE_RANK[d["access_scope"]] <= _SCOPE_RANK[doc["access_scope"]]]  # never reveal more
        new_facts = extract_facts(doc)
        for old in older:
            old_facts = extract_facts(old)
            changed = [a for a in _FORMATS if a in new_facts and a in old_facts and new_facts[a] != old_facts[a]]
            if not changed:
                continue
            def describe(d, facts):
                return f"v{d['version']} ({d['effective_date']}): " + ", ".join(
                    f"{_FORMATS[a][0]} {_show(a, facts[a])}" for a in changed)
            conflicts.append(Conflict(
                topic=f"{_supplier(doc)} contract version",
                values={old["source_id"]: describe(old, old_facts), doc["source_id"]: describe(doc, new_facts)},
                chosen=doc["source_id"],
                reason=f"v{old['version']} is superseded by v{doc['version']} effective {doc['effective_date']}; "
                       "only the latest version in force applies (DOC-PRO-02)",
            ))
    return conflicts


def find_conflicts(evidence: list[Evidence]) -> list[Conflict]:
    """Sources that disagree, resolved with policies.json source_precedence.

    Compares only the evidence it is given (already filtered by the user's role). The facts
    are read from the source document itself, so a short claim from the contract agent
    still counts as its document.
    """
    by_id = _documents_by_id()
    docs = [by_id[sid] for sid in dict.fromkeys(e.source_id for e in evidence) if sid in by_id]
    sources = [d for d in docs if d["doc_type"] in _PRECEDENCE_NAMES and d["supplier_id"]
               and d["status"] != "superseded"]

    groups: dict[tuple, list[tuple[dict, float]]] = {}
    for doc in sources:
        for attribute, value in extract_facts(doc).items():
            component = _component(doc) if attribute == "delay_days" else None
            groups.setdefault((doc["supplier_id"], attribute, component), []).append((doc, value))

    conflicts = []
    for (supplier_id, attribute, component), claims in groups.items():
        if attribute == "delay_days":   # keep only statements about the latest incident
            newest = max(doc["effective_date"] for doc, _ in claims)
            claims = [(d, v) for d, v in claims if (newest - d["effective_date"]).days <= _SAME_INCIDENT_DAYS]
        if len({value for _, value in claims}) < 2:
            continue                                     # every source agrees
        chosen, reason = _choose(attribute, claims)
        topic = f"{_supplier(claims[0][0])} {_FORMATS[attribute][0]}" + (f" {component}" if component else "")
        conflicts.append(Conflict(
            topic=topic,
            values={doc["source_id"]: _show(attribute, value) for doc, value in claims},
            chosen=chosen,
            reason=reason,
        ))
    return sorted(conflicts + _version_conflicts(docs), key=lambda c: c.topic)

