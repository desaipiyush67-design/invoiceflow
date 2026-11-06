"""HTTP API + the single-page UI. Start with:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import json
import shutil
import threading
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, store
from .extract import claude_available
from .pipeline import STAGES, execute, new_run

app = FastAPI(title="InvoiceFlow", description="Invoice to decision, with every step visible.")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")
LIVE: dict[str, dict] = {}  # runs in progress, so the event stream can follow them
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_BYTES = 15 * 1024 * 1024


@app.on_event("startup")
def startup() -> None:
    store.init()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/meta")
def meta() -> dict:
    return {"stages": [{"key": k, "title": t, "hint": h} for k, t, h in STAGES], "extractor": f"Claude ({config.CLAUDE_MODEL})" if claude_available() else "Built-in parser",
            "samples": sorted(p.name for p in config.SAMPLES.glob("*.pdf")),
            "settings": {"tolerance_pct": config.TOLERANCE_PCT, "tolerance_abs": config.TOLERANCE_ABS, "gst_rate": config.GST_RATE,
                         "unit_price_tolerance_pct": config.UNIT_PRICE_TOLERANCE_PCT, "near_duplicate_days": config.NEAR_DUPLICATE_DAYS}}


def _start(filename: str, path: Path) -> dict:
    run = new_run(filename, path)
    LIVE[run["id"]] = run
    threading.Thread(target=execute, args=(run, run["events"].append), daemon=True).start()
    return {"id": run["id"]}


@app.post("/api/runs")
async def upload(file: UploadFile = File(...)) -> dict:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Upload a PDF, PNG or JPG.")
    data = await file.read()
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "File is larger than 15 MB.")
    config.UPLOADS.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in Path(file.filename).name if c.isalnum() or c in "._-") or f"upload{ext}"
    dest = config.UPLOADS / f"{len(list(config.UPLOADS.iterdir()))}_{safe}"
    dest.write_bytes(data)
    return _start(file.filename, dest)


@app.post("/api/runs/sample/{name}")
def run_sample(name: str) -> dict:
    src = config.SAMPLES / Path(name).name
    if not src.exists():
        raise HTTPException(404, "No such sample")
    config.UPLOADS.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOADS / f"{len(list(config.UPLOADS.iterdir()))}_{src.name}"
    shutil.copy(src, dest)
    return _start(src.name, dest)


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str):
    async def stream():
        sent = 0
        while True:
            run = LIVE.get(run_id)
            if run is None:
                saved = store.get_run(run_id)
                if saved:
                    yield f"data: {json.dumps({'type': 'done', 'run': saved}, default=str)}\n\n"
                return
            while sent < len(run["events"]):
                ev = run["events"][sent]
                sent += 1
                yield f"data: {json.dumps(ev, default=str)}\n\n"
                if ev["type"] == "done":
                    LIVE.pop(run_id, None)
                    return
            await asyncio.sleep(0.1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/runs")
def runs() -> list[dict]:
    return [{k: r.get(k) for k in ("id", "created_at", "filename", "status", "decision", "vendor", "invoice_number", "po_number", "total", "duration_ms", "extractor")}
            | {"headline": (r.get("result") or {}).get("headline"), "owner": (r.get("result") or {}).get("owner")} for r in store.list_runs()]


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    r = store.get_run(run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    return r


@app.get("/api/runs/{run_id}/file")
def run_file(run_id: str):
    r = LIVE.get(run_id) or store.get_run(run_id)  # live runs aren't saved until they finish
    if not r or not Path(r["file_path"]).exists():
        raise HTTPException(404, "File not found")
    return FileResponse(r["file_path"])


@app.get("/api/reference")
def reference() -> dict:
    pos = store.purchase_orders()
    for p in pos.values():
        p["billed"] = store.billed_against(p["po_number"])
    with store.connect() as con:
        ledger = [dict(r) for r in con.execute("SELECT vendor_id, invoice_number, invoice_date, po_number, total, status, recorded_on FROM ledger ORDER BY id DESC")]
    return {"vendors": store.vendors(), "purchase_orders": list(pos.values()), "ledger": ledger}


@app.post("/api/reset")
def reset() -> dict:
    """Restore the demo to its starting state (seed ledger, no runs)."""
    store.init(reset=True)
    return {"ok": True}
