"""The injection guard flags the trainer's planted document (DOC-NOT-HELIOS-PRICE)."""

from supplyguard_ai.config import data_dir
from supplyguard_ai.tools.guards import check_injection


def test_the_planted_helios_document_is_flagged():
    notices = (data_dir() / "documents" / "supplier_notice").iterdir()
    doc = next(p for p in notices if "DOC-NOT-HELIOS-PRICE" in p.read_text())
    assert check_injection(doc.read_text()) is not None


def test_a_normal_sentence_is_not_flagged():
    assert check_injection("MC-17 pricing is EUR 7.20 until year end.") is None
