"""index_documents. OWNER: role 3.

The 212 documents (data/documents) -> pgvector AND ChromaDB, with source_id, version,
effective_date, access_scope and the rest of the front matter as metadata.

    docker compose up -d
    uv run python scripts/index_documents.py               # both stores + a test query
    uv run python scripts/index_documents.py --only pgvector

Safe to run again: every run rebuilds both indexes from the files. Both stores get the
SAME vectors, so the pgvector / Chroma benchmark compares the stores, not the models.
One document = one chunk: the documents are short (0.3-1.1 KB).
"""

import argparse
import json
from collections import Counter

import psycopg

from supplyguard_ai.memory import MEMORY_TABLE, seed_memories
from supplyguard_ai.config import database_url
from supplyguard_ai.tools.retrieval import (
    CHROMA_COLLECTION,
    PG_TABLE,
    chroma_client,
    embedding_text,
    get_embeddings,
    load_documents,
    to_pgvector,
)

TEST_QUERY = "Borealis ISO 9001 certificate expired"   # expected: DOC-QUA-S003-v1


def write_pgvector(docs: list[dict], vectors: list[list[float]]) -> None:
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env.")
    dim = len(vectors[0])
    rows = [
        (d["source_id"], d["base_id"], d["doc_type"], d["title"], d["supplier_id"], d["version"],
         d["effective_date"], d["access_scope"], d["status"], d["path"], d["content"],
         json.dumps(d["extra"]), to_pgvector(v))
        for d, v in zip(docs, vectors)
    ]
    # One transaction (committed when the block ends): a reader sees the old index or the new one.
    with psycopg.connect(url) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(f"DROP TABLE IF EXISTS {PG_TABLE}")
        conn.execute(f"""
            CREATE TABLE {PG_TABLE} (
                source_id      text PRIMARY KEY,         -- DOC-CON-S001-v3
                base_id        text NOT NULL,            -- DOC-CON-S001 (all versions)
                doc_type       text NOT NULL,
                title          text NOT NULL,
                supplier_id    text,
                version        int  NOT NULL,
                effective_date date NOT NULL,
                access_scope   text NOT NULL,            -- public/internal/procurement/finance-confidential
                status         text NOT NULL,            -- current / superseded
                path           text NOT NULL,
                content        text NOT NULL,
                extra          jsonb NOT NULL,           -- component_id, stated_delay_days, ...
                embedding      vector({dim}) NOT NULL,
                -- keyword side of the hybrid search (step 4), filled by Postgres itself
                tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || content)) STORED
            )""")
        with conn.cursor() as cur:
            cur.executemany(
                f"""INSERT INTO {PG_TABLE} (source_id, base_id, doc_type, title, supplier_id, version,
                        effective_date, access_scope, status, path, content, extra, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)""",
                rows,
            )
        conn.execute(f"CREATE INDEX ON {PG_TABLE} (base_id, version DESC)")   # newest version per document
        conn.execute(f"CREATE INDEX ON {PG_TABLE} (access_scope)")
        conn.execute(f"CREATE INDEX ON {PG_TABLE} USING gin (tsv)")
        # No vector index: 212 rows are scanned in a millisecond, and HNSW stops at 2,000 dimensions.


def chroma_metadata(doc: dict) -> dict:
    """Chroma metadata: flat str/int values only (no None, no dates, no nested dicts)."""
    return {
        "source_id": doc["source_id"],
        "base_id": doc["base_id"],
        "doc_type": doc["doc_type"],
        "title": doc["title"],
        "supplier_id": doc["supplier_id"] or "",
        "version": doc["version"],
        "effective_date": doc["effective_date"].isoformat(),
        "effective_ymd": int(doc["effective_date"].strftime("%Y%m%d")),  # Chroma compares numbers only
        "access_scope": doc["access_scope"],
        "status": doc["status"],
        "path": doc["path"],
        **{key: str(value) for key, value in doc["extra"].items()},
    }


def write_chroma(docs: list[dict], vectors: list[list[float]]) -> None:
    client = chroma_client()
    try:
        client.delete_collection(CHROMA_COLLECTION)
    except Exception:  # first run: there is nothing to delete yet
        pass
    collection = client.create_collection(
        CHROMA_COLLECTION,
        configuration={"hnsw": {"space": "cosine"}},   # same distance as pgvector's <=>
        embedding_function=None,                        # we always pass our own Azure vectors
    )
    collection.add(
        ids=[d["source_id"] for d in docs],
        embeddings=vectors,
        documents=[d["content"] for d in docs],
        metadatas=[chroma_metadata(d) for d in docs],
    )


def check(stores: set[str], expected: int) -> None:
    """Milestone: both stores hold every document and answer a test query."""
    query = get_embeddings().embed_query(TEST_QUERY)
    print(f"\nTest query: {TEST_QUERY!r}")
    if "pgvector" in stores:
        with psycopg.connect(database_url()) as conn:
            count = conn.execute(f"SELECT count(*) FROM {PG_TABLE}").fetchone()[0]
            top = conn.execute(
                f"""SELECT source_id, 1 - (embedding <=> %s::vector) AS score
                    FROM {PG_TABLE} ORDER BY embedding <=> %s::vector LIMIT 3""",
                (to_pgvector(query), to_pgvector(query)),
            ).fetchall()
        print(f"  pgvector: {count}/{expected} rows | top 3: "
              + ", ".join(f"{sid} ({score:.3f})" for sid, score in top))
    if "chroma" in stores:
        collection = chroma_client().get_collection(CHROMA_COLLECTION)
        result = collection.query(query_embeddings=[query], n_results=3)
        top = zip(result["ids"][0], result["distances"][0])
        print(f"  chroma:   {collection.count()}/{expected} docs | top 3: "
              + ", ".join(f"{sid} ({1 - dist:.3f})" for sid, dist in top))


def main() -> None:
    parser = argparse.ArgumentParser(description="Index the documents into pgvector and ChromaDB.")
    parser.add_argument("--only", choices=["pgvector", "chroma", "memories"], help="index one store only")
    args = parser.parse_args()
    if args.only == "memories":                     # quick: the 40 memories, without re-embedding documents
        print(f"memories: {seed_memories()} rows in '{MEMORY_TABLE}'")
        return
    stores = {args.only} if args.only else {"pgvector", "chroma"}

    docs = load_documents()
    print(f"Loaded {len(docs)} documents")
    print("  by type: ", dict(Counter(d["doc_type"] for d in docs)))
    print("  by scope:", dict(Counter(d["access_scope"] for d in docs)))
    superseded = [d["source_id"] for d in docs if d["status"] != "current"]
    print("  superseded (indexed, filtered out at search time):", superseded)

    print("Embedding ...")
    vectors = get_embeddings().embed_documents([embedding_text(d) for d in docs])
    print(f"  {len(vectors)} vectors of {len(vectors[0])} dimensions")

    if "pgvector" in stores:
        write_pgvector(docs, vectors)
        print(f"pgvector: table '{PG_TABLE}' rebuilt")
        print(f"memories: {seed_memories()} rows in '{MEMORY_TABLE}' (trainer's 40 + our approved cases)")
    if "chroma" in stores:
        write_chroma(docs, vectors)
        print(f"chroma: collection '{CHROMA_COLLECTION}' rebuilt")

    check(stores, len(docs))


if __name__ == "__main__":
    main()
