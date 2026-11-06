"""Tests. The AI tests call the real models (they need GROQ_API_KEY) and check every prepared invoice gets the
expected decision for the expected reason; the rest run offline."""
import pytest

from app import config, store
from app.pipeline import execute, new_run
from app.reader import read_document
from app.review import gather_records
from app.models import InvoiceFields

needs_ai = pytest.mark.skipif(not config.GROQ_API_KEY, reason="GROQ_API_KEY not set")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    monkeypatch.setattr(config, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    store.init(reset=True)


def run(name):
    return execute(new_run(name, config.SAMPLES / name), lambda e: None)


def flagged_text(r):
    return " ".join((c["id"] + " " + c["title"] + " " + c["detail"]).lower() for c in r["checks"] if c["severity"] != "none")


EXPECTED = [
    ("01_happy_apex_paper_toner.pdf", "APPROVE", []),
    ("02_edge_duplicate_reformatted_apex.pdf", "REJECT", ["duplicate"]),
    ("03_edge_split_po_overrun_blueline.pdf", "HOLD", ["53,000"]),
    ("04_edge_scanned_no_po_delta.pdf", "HOLD", ["po-4504"]),
    ("05_edge_gstin_bank_mismatch_cobalt.pdf", "HOLD", ["gstin", "6621"]),
    ("06_extra_within_tolerance_cobalt.pdf", "APPROVE", []),
    ("07_extra_blocked_vendor_evergreen.pdf", "REJECT", ["blocked"]),
    ("08_extra_missing_number_wrong_gst_blueline.pdf", "HOLD", ["invoice number", "12"]),
]


@needs_ai
@pytest.mark.parametrize("name,decision,mentions", EXPECTED)
def test_ai_decision(name, decision, mentions):
    r = run(name)
    assert r["status"] == "done", r.get("error")
    assert r["decision"] == decision, r["result"]
    text = flagged_text(r)
    for m in mentions:
        assert m in text, f"expected a finding mentioning {m!r}: {text[:500]}"


def test_scanned_pdf_has_no_text_layer():
    doc = read_document(config.SAMPLES / "04_edge_scanned_no_po_delta.pdf")
    assert doc.kind == "scanned-pdf" and doc.images and not doc.text


def test_digital_pdf_keeps_text_layer():
    doc = read_document(config.SAMPLES / "01_happy_apex_paper_toner.pdf")
    assert doc.kind == "digital-pdf" and "INV-2026-0533" in doc.text


def test_records_include_billed_so_far():
    records = gather_records(InvoiceFields())
    po = next(p for p in records["purchase_orders"] if p["po_number"] == "PO-4502")
    assert po["billed_so_far"] == 30000  # the seed invoice BL-2026-118


def test_missing_key_ends_cleanly(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", None)
    r = run("01_happy_apex_paper_toner.pdf")
    assert r["status"] == "error" and "GROQ_API_KEY" in r["error"]


def test_unreadable_file_ends_cleanly(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    r = execute(new_run("broken.pdf", bad), lambda e: None)
    assert r["status"] == "error" and r["decision"] == "ERROR"
