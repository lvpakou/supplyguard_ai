"""Tests for role 3 (documents and retrieval). These need no Azure, Postgres or Chroma."""

from collections import Counter

import pytest
import psycopg

from supplyguard_ai.state import Evidence
from supplyguard_ai.auth import scopes_for_role
from supplyguard_ai.config import database_url
from supplyguard_ai.tools import retrieval
from supplyguard_ai.tools.retrieval import get_embeddings, load_documents, search_documents, extract_facts, find_conflicts


@pytest.fixture(scope="module")
def docs():
    return {d["source_id"]: d for d in load_documents()}


def test_all_212_documents_load_once(docs):
    assert len(docs) == 212
    assert Counter(d["doc_type"] for d in docs.values()) == {
        "contract": 61, "qualification": 60, "supplier_notice": 42, "incident_report": 30,
        "procedure": 12, "email": 6, "finance": 1,
    }


def test_atlas_contract_versions_share_one_base_id(docs):
    v2, v3 = docs["DOC-CON-S001-v2"], docs["DOC-CON-S001-v3"]
    assert v2["base_id"] == v3["base_id"] == "DOC-CON-S001"
    assert (v2["version"], v2["status"]) == (2, "superseded")
    assert (v3["version"], v3["status"]) == (3, "current")
    assert v3["effective_date"] > v2["effective_date"]


def test_access_scopes(docs):
    assert docs["DOC-FIN-01-v1"]["access_scope"] == "finance-confidential"
    assert docs["DOC-NOT-HELIOS-PRICE"]["access_scope"] == "public"


def test_extra_front_matter_is_kept(docs):
    notice = docs["DOC-NOT-ATLAS-MC17"]
    assert notice["base_id"] == "DOC-NOT-ATLAS-MC17"          # no version suffix
    assert notice["extra"]["stated_delay_days"] == "12"
    assert notice["extra"]["component_id"] == "MC-17"


def test_titles_with_colons_and_empty_supplier(docs):
    email = docs["DOC-EM-INTERNAL-01"]
    assert email["title"] == "Internal e-mail: spending limit"
    assert email["supplier_id"] is None


def test_hidden_text_is_not_dropped(docs):
    # The injection guard (role 5) can only report what retrieval keeps.
    assert "<!--" in docs["DOC-NOT-HELIOS-PRICE"]["content"]


# --- roles: no services needed ---------------------------------------------
def test_scopes_for_role():
    assert scopes_for_role("viewer") == ["public"]
    assert "finance-confidential" in scopes_for_role("finance_controller")
    assert "finance-confidential" not in scopes_for_role("procurement_manager")
    assert scopes_for_role("someone_new") == ["public"]      # unknown role: least access


def test_unknown_filter_is_refused():
    with pytest.raises(ValueError):
        search_documents("x", "procurement_manager", filters={"title; DROP TABLE": "x"})


# --- search: needs docker compose up -d, the index, and Azure keys in .env --
def _index_ready() -> bool:
    try:
        with psycopg.connect(database_url(), connect_timeout=3) as conn:
            conn.execute("SELECT 1 FROM documents LIMIT 1")
        get_embeddings()                                      # fails if Azure settings are missing
        return True
    except Exception:
        return False


live = pytest.mark.skipif(not _index_ready(), reason="needs the services, the index and Azure keys")


def ids(results):
    return [r.source_id for r in results]


@live
def test_viewer_sees_only_public_documents():
    results = search_documents("Helios MC-17 price capacity contract", "viewer", k=10)
    assert results and {r.access_scope for r in results} == {"public"}


@live
def test_finance_sheet_only_for_the_finance_controller():
    query = "margin and penalty rate sheet by customer tier"
    assert "DOC-FIN-01-v1" not in ids(search_documents(query, "procurement_manager", k=10))
    assert "DOC-FIN-01-v1" in ids(search_documents(query, "finance_controller", k=10))


@live
def test_only_the_newest_atlas_contract():
    results = search_documents("Atlas Components contract lead time capacity", "procurement_manager",
                               filters={"doc_type": "contract"}, k=10)
    assert "DOC-CON-S001-v3" in ids(results)
    assert "DOC-CON-S001-v2" not in ids(results)


@live
def test_supplier_filter():
    results = search_documents("contract capacity", "procurement_manager",
                               filters={"supplier_id": "S002"}, k=10)
    assert "DOC-CON-S002-v1" in ids(results)
    assert "DOC-CON-S001-v3" not in ids(results)


# --- conflicts: no services needed ------------------------------------------
GOLDEN_SOURCES = ["DOC-NOT-ATLAS-MC17", "DOC-EM-ATLAS-01", "DOC-CON-S001-v3", "DOC-CON-S002-v1",
                  "DOC-EM-HELIOS-01", "DOC-CON-S004-v1", "DOC-EM-CORDILLERA-01"]


def evidence(*source_ids):
    return [Evidence(claim="", source_id=sid) for sid in source_ids]


def test_the_four_golden_conflicts():
    found = {c.topic: c for c in find_conflicts(evidence(*GOLDEN_SOURCES))}
    assert set(found) == {
        "Atlas Components (S001) contract version",
        "Atlas Components (S001) delay MC-17",
        "Cordillera Industrial (S004) expedite fee",
        "Helios Supply (S002) monthly capacity",
    }
    assert found["Atlas Components (S001) delay MC-17"].chosen == "12 days"
    assert found["Cordillera Industrial (S004) expedite fee"].chosen == "6%"
    assert found["Helios Supply (S002) monthly capacity"].chosen == "1,500/month for planning"
    assert found["Atlas Components (S001) contract version"].chosen == "DOC-CON-S001-v3"


def test_no_false_conflicts_in_the_whole_corpus(docs):
    # even if every document were retrieved, only the 4 real conflicts exist
    assert len(find_conflicts(evidence(*docs))) == 4


def test_agreeing_sources_are_not_a_conflict():
    assert find_conflicts(evidence("DOC-CON-S005-v1", "DOC-EM-DELTA-01")) == []   # Delta: 8 d, 2,500 in both


def test_non_supplier_documents_are_ignored():
    assert find_conflicts(evidence("DOC-INC-HC-001", "DOC-PRO-02-v1", "DOC-FIN-01-v1")) == []


def test_contract_notice_clause_is_not_a_delay(docs):
    # clause 8 "any expected delay exceeding 3 days" is a rule, not a delay
    assert "delay_days" not in extract_facts(docs["DOC-CON-S001-v3"])


# --- step 4: modes, hybrid, confidence --------------------------------------
def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        retrieval._search("x", "procurement_manager", mode="bm25")


def test_chroma_filter_has_the_same_rules():
    where = retrieval._chroma_where(["public"], {"supplier_id": "S002"})
    assert {"access_scope": {"$in": ["public"]}} in where["$and"]
    assert {"status": {"$ne": "superseded"}} in where["$and"]
    assert {"supplier_id": {"$in": ["S002"]}} in where["$and"]


def test_newest_versions_come_from_the_files():
    assert retrieval._newest_versions()["DOC-CON-S001"] == 3


def _row(similarity):
    return ("DOC-X", "contract", "t", 1, None, "procurement", "text", similarity)


def test_confident_keeps_all_or_nothing(monkeypatch):
    monkeypatch.setattr(retrieval, "MIN_SIMILARITY", 0.5)
    assert len(retrieval._confident([_row(0.8), _row(0.2)])) == 2   # best is strong: keep the list
    assert retrieval._confident([_row(0.4), _row(0.3)]) == []        # best is weak: no reliable source
    assert retrieval._confident([]) == []


def _chroma_ready() -> bool:
    try:
        retrieval.chroma_client().get_collection(retrieval.CHROMA_COLLECTION)
        return True
    except Exception:
        return False


needs_chroma = pytest.mark.skipif(not _chroma_ready(), reason="needs ChromaDB and the index")
MODES = [pytest.param("pgvector", marks=live), pytest.param("hybrid", marks=live),
         pytest.param("chroma", marks=[live, needs_chroma])]


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_keeps_the_rules(mode):
    viewer = retrieval._search("Helios MC-17 price capacity contract", "viewer", k=10, mode=mode)
    assert viewer and {row[5] for row in viewer} == {"public"}
    atlas = [row[0] for row in retrieval._search("Atlas Components contract lead time", "procurement_manager",
                                               filters={"doc_type": "contract"}, k=10, mode=mode)]
    assert "DOC-CON-S001-v3" in atlas and "DOC-CON-S001-v2" not in atlas
    finance = [row[0] for row in retrieval._search("margin and penalty rate sheet", "procurement_manager",
                                                 k=20, mode=mode)]
    assert "DOC-FIN-01-v1" not in finance


@live
def test_hybrid_finds_an_exact_certificate_number():
    top3 = [row[0] for row in retrieval._search("CERT-S003-72388", "procurement_manager", k=3, mode="hybrid")]
    assert "DOC-QUA-S003-v1" in top3


@live
def test_off_topic_question_finds_nothing():
    assert search_documents("A recipe for moussaka", "procurement_manager") == []

def test_query_vectors_are_cached(monkeypatch):
    calls = []

    class FakeEmbeddings:
        def embed_query(self, text):
            calls.append(text)
            return [1.0, 0.0]

    monkeypatch.setattr(retrieval, "get_embeddings", lambda: FakeEmbeddings())
    retrieval._embed_query.cache_clear()
    retrieval._embed_query("same text")
    retrieval._embed_query("same text")
    assert calls == ["same text"]                 # Azure asked once
    retrieval._embed_query.cache_clear()          # don't leak the fake vector into other tests


@live
def test_supplier_filter_skips_the_confidence_threshold(monkeypatch):
    monkeypatch.setattr(retrieval, "MIN_SIMILARITY", 0.99)        # nothing is that similar
    assert search_documents("delay capacity fee", "procurement_manager", filters={"supplier_id": "S002"})
    assert search_documents("delay capacity fee", "procurement_manager") == []

