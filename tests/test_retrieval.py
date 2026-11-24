"""Tests for role 3 (documents and retrieval). These need no Azure, Postgres or Chroma."""

from collections import Counter

import pytest
import psycopg

from supplyguard_ai.auth import scopes_for_role
from supplyguard_ai.config import database_url
from supplyguard_ai.tools.retrieval import get_embeddings, load_documents, search_documents


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
    