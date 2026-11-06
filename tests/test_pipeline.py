"""End-to-end tests: every prepared invoice must produce the expected decision, for the expected reason."""
import pytest

from app import config, store
from app.extract import parse_text
from app.models import InvoiceFields, LineItem
from app.pipeline import execute, new_run
from app.rules import document_checks, invoice_key


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    monkeypatch.setattr(config, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "USE_CLAUDE", "off")  # tests must not depend on the network
    store.init(reset=True)


def run(name):
    return execute(new_run(name, config.SAMPLES / name), lambda e: None)


def failing(r):
    return {c["id"] for c in r["checks"] if c["severity"] != "none"}


EXPECTED = [
    ("01_happy_apex_paper_toner.pdf", "APPROVE", set()),
    ("02_edge_duplicate_reformatted_apex.pdf", "REJECT", {"duplicate"}),
    ("03_edge_split_po_overrun_blueline.pdf", "HOLD", {"po_amount"}),
    ("04_edge_scanned_no_po_delta.pdf", "HOLD", {"po_match"}),
    ("05_edge_gstin_bank_mismatch_cobalt.pdf", "HOLD", {"vendor_identity", "vendor_bank"}),
    ("06_extra_within_tolerance_cobalt.pdf", "APPROVE", set()),
    ("07_extra_blocked_vendor_evergreen.pdf", "REJECT", {"vendor_status"}),
    ("08_extra_missing_number_wrong_gst_blueline.pdf", "HOLD", {"required_fields", "gst_rate"}),
]


@pytest.mark.parametrize("name,decision,reasons", EXPECTED)
def test_sample_decisions(name, decision, reasons):
    r = run(name)
    assert r["status"] == "done", r.get("error")
    assert r["decision"] == decision
    assert reasons <= failing(r)


def test_scanned_invoice_goes_through_ocr_and_finds_the_po():
    r = run("04_edge_scanned_no_po_delta.pdf")
    assert r["stages"]["read"]["data"]["method"] == "ocr"
    assert r["fields"]["total"] == 53690
    assert r["po_number"] == "PO-4504"


def test_same_file_twice_is_rejected_the_second_time():
    assert run("01_happy_apex_paper_toner.pdf")["decision"] == "APPROVE"
    second = run("01_happy_apex_paper_toner.pdf")
    assert second["decision"] == "REJECT" and "duplicate" in failing(second)


def test_approved_invoice_consumes_the_po():
    run("01_happy_apex_paper_toner.pdf")
    assert store.billed_against("PO-4501") == 77000


def test_held_invoice_does_not_consume_the_po():
    run("03_edge_split_po_overrun_blueline.pdf")
    assert store.billed_against("PO-4502") == 30000  # only the seed invoice


@pytest.mark.parametrize("a,b", [("INV-2026-0417", "INV/2026/417"), ("INV-2026-0417", "inv 2026 417"), ("BL-2026-118", "BL/2026/0118")])
def test_invoice_number_normalisation(a, b):
    assert invoice_key(a) == invoice_key(b)


def test_bad_arithmetic_is_held():
    f = InvoiceFields(vendor_name="X", invoice_number="1", invoice_date="2026-11-01", subtotal=1000, tax_amount=180, total=1250,
                      line_items=[LineItem(description="a", quantity=1, unit_price=1000, amount=1000)])
    bad = {c.id for c in document_checks(f) if c.status == "fail"}
    assert "arithmetic" in bad


def test_parser_reads_indian_number_format():
    f = parse_text("Acme Supplies Pvt Ltd\nInvoice No: A-1\nDate: 01/11/2026\nSubtotal 1,00,000.00\nIGST @ 18% 18,000.00\nTotal Due 1,18,000.00")
    assert (f.subtotal, f.tax_amount, f.total, f.invoice_date) == (100000, 18000, 118000, "2026-11-01")


def test_unreadable_file_ends_cleanly(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    r = execute(new_run("broken.pdf", bad), lambda e: None)
    assert r["status"] == "error" and r["decision"] == "ERROR"
