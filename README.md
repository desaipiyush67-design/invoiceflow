# InvoiceFlow — from invoice PDF to a reasoned payment decision

InvoiceFlow takes a vendor invoice (a digital PDF, a scan or a photo) and decides **Approve**, **Hold** or **Reject**, showing every step it took and why. Anything that isn't approved goes to a named owner with the exact next step, and when the vendor has to fix something, a ready-to-send email is drafted.

Built for the Zamp AI Solutions Associate case study (PS-1, Finance / AP).

## What it does

```
Invoice ──► 1 Read ──► 2 Extract ──► 3 Validate ──► 4 Verify vendor ──► 5 Match PO & history ──► 6 Decide
            text layer   vendor, no.,   required fields,  vendor master,     duplicates, PO, split     APPROVE / HOLD / REJECT
            or OCR       date, PO,      maths, GST rate,  tax ID, bank,      billing, tolerance,       + reason, owner, next step
                         lines, totals  invoice date      vendor status      line prices & qty         + vendor email if needed
```

- **Live run view**: each stage lights up as it runs, with its result and timing; click a stage for the detail (raw text, extracted fields, every check).
- **Dashboard**: all runs with decision, amount, next owner and processing time, plus totals (straight-through rate, value approved, value stopped).
- **Vendors & POs**: the master data being checked against, including how much of each PO is already billed.

## Decision policy

| Outcome | When | Example |
|---|---|---|
| **REJECT** | It can never be paid as submitted | duplicate invoice, blocked vendor, PO issued to another vendor |
| **HOLD** | It may be payable, but a person must act | inferred PO, over the PO budget, tax ID or bank changed, missing invoice number, wrong GST |
| **APPROVE** | Every check passes (small variances inside tolerance are noted) | clean invoice, or 1.25% over PO with a note |

Tolerances live in [`app/config.py`](app/config.py): over-billing up to **2% or ₹5,000, whichever is lower**; unit price drift ±2%; GST 18%.

## Test invoices (in `samples/`)

| # | Case | Expected |
|---|---|---|
| 01 | Clean invoice, PO matches line by line | APPROVE |
| 02 | **Duplicate in disguise**: an invoice already paid, re-sent with its number re-formatted (`INV/2026/417` vs `INV-2026-0417`) | REJECT |
| 03 | **Split PO overrun**: second part-bill against a ₹50,000 PO takes the total to ₹53,000 (6% over) | HOLD → buyer |
| 04 | **Scanned invoice with no PO number**: OCR, then the PO is inferred from the vendor's open POs | HOLD → requester confirms |
| 05 | **Tax ID and bank account changed** ("please pay our new account") | HOLD → AP lead verifies by phone |
| 06 | 1.25% over the PO | APPROVE with a note |
| 07 | Vendor blocked after failed KYC | REJECT |
| 08 | No invoice number, GST charged at 12% | HOLD + email to vendor |

Each prepared case can be run from the UI with one click. **Reset demo data** restores the starting ledger, so the demo is repeatable.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload     # open http://127.0.0.1:8000
pytest                            # 18 tests: every sample's decision and reasons
```

Optional: set `ANTHROPIC_API_KEY` to use Claude (`claude-opus-5-5`) for field extraction. Without a key, the built-in parser is used. If Claude is unavailable mid-run, the run falls back to the parser instead of failing.

Regenerate the sample invoices with `python tools/make_samples.py`; print every decision with `python tools/run_all.py`.

## Design choices

- **Rules decide, AI reads.** Extraction is where invoices are messy, so that's where AI helps. The payment decision is deterministic code that an auditor can read; the same invoice always gets the same answer.
- **Never guess a field.** A value that isn't on the invoice stays empty and becomes a check result ("missing invoice number"), not an invented value.
- **Held is not consumed.** Only approved invoices count against a PO's budget, so a held invoice never blocks a correct one.
- **Inferred POs are suggested, never auto-paid.** Even at 100% confidence, a person confirms.
- **Identity changes are verified out of band.** A changed tax ID or bank account is never confirmed using contact details from the same invoice.

## Stack

Python · FastAPI · Server-Sent Events for the live view · PyMuPDF (text layer) · RapidOCR on ONNX Runtime (scans, CPU only) · RapidFuzz (vendor/item matching) · SQLite (runs and ledger) · Claude via the Anthropic SDK (optional) · plain HTML/CSS/JS front end · Docker (deploys to Render with `render.yaml`).

## Assumptions

- Buyer: Northwind Retail Pvt Ltd, Bengaluru; amounts in INR; GST 18%.
- A PO's amount is compared before tax; tax is checked separately.
- Vendor master, POs and the paid-invoice ledger are CSV files in `data/` (in production: the ERP).
- One invoice per file.
