# InvoiceFlow — AI accounts-payable reviewer

InvoiceFlow takes a vendor invoice (a digital PDF, a scan or a photo) and an AI reviewer decides **Approve**, **Hold** or **Reject**, the way a senior AP clerk would: it reads the invoice, checks it against the company's AP policy, vendor master, purchase orders and invoice history, and explains every finding. Anything not approved goes to a named owner with the exact next step; when the vendor has to fix something, the email is drafted.

Built for the Zamp AI Solutions Associate case study (PS-1, Finance / AP).

## How it works

```
Invoice ──► 1 Prepare ──► 2 AI reads invoice ──► 3 Look up records ──► 4 AI reviews & decides
            pages to       vision model reads     vendor master, POs     reasoning model applies the AP policy:
            images +       every field, even      (+ amount already      document, vendor, duplicates, PO, split billing
            text layer     from scans             billed), history       → APPROVE / HOLD / REJECT + owner + next step
```

| Step | Model | What it does |
|---|---|---|
| AI reads invoice | `qwen/qwen3.8-27b` (vision) | Reads the page image (and the text layer when there is one) and returns the vendor, GSTIN, invoice number, date, PO, line items, subtotal, tax, total and bank account. Told never to guess a field that isn't printed. |
| AI reviews & decides | `openai/gpt-oss-120b` (reasoning) | Gets the extracted invoice, the company records and the **AP policy written in plain English** ([`data/ap_policy.md`](data/ap_policy.md)), and returns every finding plus the decision, owner, next step and vendor email. |

The policy is the control panel: edit the text (for example change the 2% tolerance to 5%) and the reviewer's behaviour changes, with no code change. Every AI reply is validated against a schema and re-asked once if malformed. If the main model hits a usage limit, a backup model takes over; if both are unavailable, the run stops with a clear message and **no decision is recorded**.

### UI
- **Live run view**: each step lights up as it runs, with timing; open a step to see the extracted fields and the reviewer's findings grouped by Document, Vendor, Duplicates and Purchase order.
- **Dashboard**: every run with decision, amount, next owner and time, plus the straight-through rate, value approved and value stopped.
- **Policy & data**: the AP policy the AI applies, the purchase orders (with how much is already billed), the vendor master and the invoice ledger.

## Test invoices (`samples/`)

| # | Case | Expected |
|---|---|---|
| 01 | Clean invoice, PO matches line by line | APPROVE |
| 02 | **Duplicate in disguise**: an already-paid invoice re-sent with its number re-formatted (`INV/2026/417` vs `INV-2026-0417`) | REJECT |
| 03 | **Split PO overrun**: second part-bill takes a ₹50,000 PO to ₹53,000 | HOLD → buyer |
| 04 | **Scanned invoice, no PO number**: the AI reads the image and infers PO-4504, but a person must confirm | HOLD → requester |
| 05 | **Tax ID and bank account changed** ("please pay our new account") | HOLD → AP lead verifies by phone |
| 06 | 1.25% over the PO | APPROVE with a note |
| 07 | Vendor blocked after failed KYC | REJECT |
| 08 | No invoice number, GST charged at 12% | HOLD + email to the vendor |

One click runs each case from the UI. **Reset demo data** restores the starting ledger, so the demo is repeatable.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
echo GROQ_API_KEY=your_key > .env  # free key from console.groq.com
uvicorn app.main:app --reload      # open http://127.0.0.1:8000
pytest                             # includes 8 live AI tests, one per sample
```

`python tools/run_all.py` prints every sample's decision; `python tools/make_samples.py` regenerates the sample invoices.

Deploy: `render.yaml` + `Dockerfile` (Render free web service); set `GROQ_API_KEY` in the Render dashboard.

## Design choices
- **AI reads and judges; the policy is plain English.** Finance teams can read and change the rules without a developer.
- **Facts come from the company's records, not the model's memory.** The reviewer only sees the vendor master, POs, billed amounts and invoice history it is given, and is told never to invent data.
- **Held is not consumed.** Only approved invoices count against a PO's budget.
- **Inferred POs are suggested, never auto-paid**, and identity changes (GSTIN, bank account) are verified out of band.
- **Fail safe.** Malformed AI replies are re-asked; usage limits fall back to a second model; if nothing works, no decision is recorded.

## Assumptions
- Buyer: Northwind Retail Pvt Ltd, Bengaluru; INR; GST 18%. PO amounts are compared before tax.
- Vendor master, POs and the paid-invoice ledger are CSV files in `data/` (in production: the ERP).
- One invoice per file; up to 3 pages are read.
- Free Groq accounts allow roughly 8,000 tokens per minute and 200,000 per day per model, about 40 invoices a day.
