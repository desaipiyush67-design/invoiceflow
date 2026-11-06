"""The run: six visible stages, each emitting events the UI streams live."""
from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import store
from .decide import decide
from .extract import extract
from .reader import read_document
from .rules import document_checks, duplicate_checks, match_vendor, po_checks

STAGES = [
    ("read", "Read document", "Text layer or OCR"),
    ("extract", "Extract fields", "Vendor, numbers, lines"),
    ("validate", "Validate invoice", "Required fields, maths, GST"),
    ("vendor", "Verify vendor", "Master data, tax ID, bank"),
    ("match", "Match PO & history", "Duplicates, PO, tolerances"),
    ("decide", "Decide", "Approve / Hold / Reject"),
]


def new_run(filename: str, path: Path) -> dict:
    return {"id": uuid.uuid4().hex[:10], "created_at": datetime.now().isoformat(timespec="seconds"), "filename": filename,
            "file_path": str(path), "status": "running", "stages": {k: {"status": "pending"} for k, *_ in STAGES}, "events": []}


def execute(run: dict, emit: Callable[[dict], None]) -> dict:
    t0 = time.perf_counter()

    def stage(key: str, status: str, summary: str = "", data=None, ms: float | None = None):
        s = run["stages"][key]
        s.update(status=status, summary=summary)
        if data is not None:
            s["data"] = data
        if ms is not None:
            s["ms"] = round(ms)
        emit({"type": "stage", "stage": key, **s})

    def timed(key, fn):
        stage(key, "running")
        t = time.perf_counter()
        out = fn()
        return out, (time.perf_counter() - t) * 1000

    path = Path(run["file_path"])
    try:
        doc, ms = timed("read", lambda: read_document(path))
        run["sha256"] = doc.sha256
        stage("read", "done", f"{'OCR (scanned image)' if doc.method == 'ocr' else 'Digital PDF text layer'} · {doc.pages} page(s)"
              + (f" · OCR confidence {doc.ocr_confidence:.0%}" if doc.ocr_confidence is not None else ""),
              {"method": doc.method, "pages": doc.pages, "ocr_confidence": doc.ocr_confidence, "notes": doc.notes, "text": doc.text[:4000]}, ms)

        (fields, extractor, notes), ms = timed("extract", lambda: extract(path, doc.text))
        found = sum(1 for k in ("vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "po_reference", "subtotal", "tax_amount", "total") if getattr(fields, k))
        stage("extract", "done", f"{extractor} · {found}/8 key fields · {len(fields.line_items)} line item(s)",
              {"extractor": extractor, "fields": fields.model_dump(), "notes": notes}, ms)

        checks = []
        doc_checks, ms = timed("validate", lambda: document_checks(fields))
        checks += doc_checks
        stage("validate", _worst(doc_checks), _summary(doc_checks), [c.model_dump() for c in doc_checks], ms)

        (vendor, v_checks), ms = timed("vendor", lambda: match_vendor(fields))
        checks += v_checks
        stage("vendor", _worst(v_checks), vendor["name"] if vendor else "Unknown vendor", [c.model_dump() for c in v_checks], ms)

        def match():
            d = duplicate_checks(fields, vendor, doc.sha256)
            po, p = po_checks(fields, vendor)
            return po, d + p
        (po, m_checks), ms = timed("match", match)
        checks += m_checks
        stage("match", _worst(m_checks), po["po_number"] if po else "No PO matched", [c.model_dump() for c in m_checks], ms)

        decision, ms = timed("decide", lambda: decide(fields, vendor, po, checks))
        status = {"APPROVE": "approved", "HOLD": "held", "REJECT": "rejected"}[decision.decision]
        if vendor and decision.decision != "REJECT":
            store.record_invoice(vendor["vendor_id"], fields, po["po_number"] if po else None, status, doc.sha256, run["id"])
        stage("decide", {"APPROVE": "pass", "HOLD": "warn", "REJECT": "fail"}[decision.decision], decision.headline, decision.model_dump(), ms)

        run.update(status="done", decision=decision.decision, vendor=vendor["name"] if vendor else fields.vendor_name,
                   invoice_number=fields.invoice_number, po_number=po["po_number"] if po else None, total=fields.total,
                   fields=fields.model_dump(), checks=[c.model_dump() for c in checks], result=decision.model_dump(), extractor=extractor)
    except Exception as e:  # a broken file must still end the run cleanly, with the reason visible
        run.update(status="error", decision="ERROR", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
        for k, s in run["stages"].items():
            if s["status"] in ("pending", "running"):
                stage(k, "error" if s["status"] == "running" else "skipped", str(e) if s["status"] == "running" else "")
    run["duration_ms"] = round((time.perf_counter() - t0) * 1000)
    record = {k: v for k, v in run.items() if k != "events"}  # the event log is only for the live stream
    store.save_run(record)
    emit({"type": "done", "run": record})
    return run


def _worst(checks) -> str:
    st = [c.status for c in checks]
    return "fail" if "fail" in st else "warn" if "warn" in st else "pass"


def _summary(checks) -> str:
    bad = [c for c in checks if c.status in ("fail", "warn")]
    return f"{len(checks) - len(bad)}/{len(checks)} passed" + (f" · {bad[0].title}" if bad else "")
