"""Tests for role 3 (documents and retrieval). These need no Azure, Postgres or Chroma."""

from collections import Counter

import pytest

from supplyguard_ai.tools.retrieval import load_documents


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
