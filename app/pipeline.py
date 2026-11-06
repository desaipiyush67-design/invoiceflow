"""The run: six visible stages, each emitting events the UI streams live."""
from __future__ import annotations

import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config, review, store
from .extract import extract
from .models import Decision
from .reader import read_document

STAGES = [
    ("read", "Prepare document", "Pages to images, text layer"),
    ("extract", "AI reads invoice", "Vision model extracts every field"),
    ("records", "Look up company records", "Vendor master, POs, invoice history"),
    ("review", "AI reviews & decides", "Policy check: document, vendor, duplicates, PO"),
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
        if not config.GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env (local) or the host's environment variables.")
        doc, ms = timed("read", lambda: read_document(path))
        run["sha256"] = doc.sha256
        kind = {"digital-pdf": "Digital PDF", "scanned-pdf": "Scanned PDF (image only)", "image": "Image"}[doc.kind]
        stage("read", "done", f"{kind} · {doc.pages} page(s)", {"kind": doc.kind, "pages": doc.pages, "notes": doc.notes, "text": doc.text[:4000]}, ms)

        fields, ms = timed("extract", lambda: extract(doc))
        found = sum(1 for k in ("vendor_name", "vendor_gstin", "invoice_number", "invoice_date", "po_reference", "subtotal", "tax_amount", "total") if getattr(fields, k))
        stage("extract", "done", f"{found}/8 key fields · {len(fields.line_items)} line item(s)",
              {"extractor": f"AI vision · {config.VISION_MODEL}", "fields": fields.model_dump(), "notes": []}, ms)

        records, ms = timed("records", lambda: review.gather_records(fields))
        stage("records", "done", f"{len(records['vendor_master'])} vendors · {len(records['purchase_orders'])} POs · {len(records['earlier_invoices'])} earlier invoices",
              {"counts": {k: len(v) for k, v in records.items()}}, ms)

        (vendor, po, model, result), ms = timed("review", lambda: review.review(fields, records))
        decision = Decision(**{k: getattr(result, k) for k in Decision.model_fields})
        status = {"APPROVE": "approved", "HOLD": "held", "REJECT": "rejected"}[decision.decision]
        if vendor and decision.decision != "REJECT":
            store.record_invoice(vendor["vendor_id"], fields, po["po_number"] if po else None, status, doc.sha256, run["id"])
        checks = [c.model_dump() for c in result.checks]
        stage("review", {"APPROVE": "pass", "HOLD": "warn", "REJECT": "fail"}[decision.decision], decision.headline,
              {"model": model, "checks": checks}, ms)

        run.update(status="done", decision=decision.decision, vendor=vendor["name"] if vendor else fields.vendor_name,
                   invoice_number=fields.invoice_number, po_number=po["po_number"] if po else None, total=fields.total,
                   fields=fields.model_dump(), checks=checks, result=decision.model_dump(),
                   extractor=f"AI · {config.VISION_MODEL} + {model}")
    except Exception as e:  # a broken file or an AI outage must still end the run cleanly, with the reason visible
        message = str(e) if type(e).__name__ in ("UsageLimit", "RuntimeError") else f"{type(e).__name__}: {e}"
        run.update(status="error", decision="ERROR", error=message, trace=traceback.format_exc()[-2000:])
        for k, s in run["stages"].items():
            if s["status"] in ("pending", "running"):
                stage(k, "error" if s["status"] == "running" else "skipped", str(e)[:300] if s["status"] == "running" else "")
    run["duration_ms"] = round((time.perf_counter() - t0) * 1000)
    record = {k: v for k, v in run.items() if k != "events"}  # the event log is only for the live stream
    store.save_run(record)
    emit({"type": "done", "run": record})
    return run


