"""Master data (vendors, POs) from CSV, and run history + invoice ledger in SQLite."""
from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime

from . import config

_lock = threading.Lock()


def _csv(name: str) -> list[dict]:
    with open(config.DATA / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def vendors() -> list[dict]:
    out = []
    for v in _csv("vendors.csv"):
        v["aliases"] = [a for a in v["aliases"].split("|") if a]
        out.append(v)
    return out


def purchase_orders() -> dict[str, dict]:
    lines = defaultdict(list)
    for l in _csv("po_lines.csv"):
        lines[l["po_number"]].append({"item": l["item"], "qty": float(l["qty"]), "unit_price": float(l["unit_price"])})
    pos = {}
    for p in _csv("purchase_orders.csv"):
        for k in ("subtotal", "tax_rate", "total"):
            p[k] = float(p[k])
        p["lines"] = lines[p["po_number"]]
        pos[p["po_number"]] = p
    return pos


def connect() -> sqlite3.Connection:
    config.RUNTIME.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init(reset: bool = False) -> None:
    with _lock, connect() as con:
        if reset:
            con.execute("DROP TABLE IF EXISTS ledger")
            con.execute("DROP TABLE IF EXISTS runs")
            shutil.rmtree(config.UPLOADS, ignore_errors=True)
        con.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, created_at TEXT, filename TEXT, file_path TEXT, sha256 TEXT,
            status TEXT, decision TEXT, vendor TEXT, invoice_number TEXT, po_number TEXT, total REAL,
            duration_ms INTEGER, result_json TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_id TEXT, invoice_number TEXT, invoice_key TEXT,
            invoice_date TEXT, po_number TEXT, subtotal REAL, tax_amount REAL, total REAL, status TEXT,
            sha256 TEXT, run_id TEXT, recorded_on TEXT)""")
        if con.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 0:
            for r in _csv("ledger_seed.csv"):
                con.execute(
                    "INSERT INTO ledger (vendor_id, invoice_number, invoice_key, invoice_date, po_number, subtotal, tax_amount, total, status, sha256, run_id, recorded_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (r["vendor_id"], r["invoice_number"], r["invoice_number"], r["invoice_date"], r["po_number"],
                     float(r["subtotal"]), float(r["tax_amount"]), float(r["total"]), r["status"], None, "seed", r["recorded_on"]))
    config.UPLOADS.mkdir(parents=True, exist_ok=True)


def ledger_for_vendor(vendor_id: str) -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM ledger WHERE vendor_id=?", (vendor_id,))]


def ledger_by_sha(sha: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT * FROM ledger WHERE sha256=?", (sha,)).fetchone()
        return dict(r) if r else None


def billed_against(po_number: str) -> float:
    """Pre-tax amount already approved against a PO (held invoices don't consume the PO yet)."""
    with connect() as con:
        r = con.execute("SELECT COALESCE(SUM(subtotal),0) FROM ledger WHERE po_number=? AND status='approved'", (po_number,)).fetchone()
        return float(r[0])


def record_invoice(vendor_id, fields, po_number, status, sha, run_id) -> None:
    with _lock, connect() as con:
        con.execute(
            "INSERT INTO ledger (vendor_id, invoice_number, invoice_key, invoice_date, po_number, subtotal, tax_amount, total, status, sha256, run_id, recorded_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (vendor_id, fields.invoice_number, fields.invoice_number, fields.invoice_date, po_number,
             fields.subtotal, fields.tax_amount, fields.total, status, sha, run_id, datetime.now().date().isoformat()))


def save_run(run: dict) -> None:
    with _lock, connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run["id"], run["created_at"], run["filename"], run["file_path"], run.get("sha256"), run["status"],
             run.get("decision"), run.get("vendor"), run.get("invoice_number"), run.get("po_number"), run.get("total"),
             run.get("duration_ms"), json.dumps(run, default=str)))


def list_runs(limit: int = 200) -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT result_json FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def get_run(run_id: str) -> dict | None:
    with connect() as con:
        r = con.execute("SELECT result_json FROM runs WHERE id=?", (run_id,)).fetchone()
    return json.loads(r[0]) if r else None
