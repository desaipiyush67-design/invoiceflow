"""The AI reviewer: one reasoning-model call checks the invoice against the AP policy and the company's
records, and makes the decision.

The policy is plain English (data/ap_policy.md). This file only gathers the facts and asks the model:
change the policy text and the behaviour changes, with no code edits.
"""
from __future__ import annotations

import json
from datetime import date

from . import config, store
from .ai import ask_with_backup
from .models import InvoiceFields, Review

TASK = """Review the invoice below against the policy and the company records, the way a senior AP reviewer would:
1. Document: required fields, subtotal + tax = total, line items add up to the subtotal, GST rate, invoice date.
2. Vendor: find it in the vendor master (by GSTIN, or by name allowing for capitals/spacing/suffixes), then compare GSTIN, bank account and status.
3. Duplicates: compare with this vendor's earlier invoices (same number in a different format = duplicate).
4. Purchase order: the PO printed on the invoice; if none is printed, the best-fitting open PO of this vendor plus a "po_inferred" finding with severity "review".
   billed_so_far is the pre-tax amount already approved on a PO: check billed_so_far + this invoice's subtotal against the PO subtotal and the tolerance.
   Compare line items with the PO lines (prices, quantities), except lump-sum lines.
5. Decide: REJECT if any finding has severity "block"; otherwise HOLD if any has severity "review"; otherwise APPROVE.

Reply with one JSON object only:
{
 "vendor_id": "<matched vendor id or null>",
 "po_number": "<PO this invoice is for (printed or inferred) or null>",
 "checks": [ {"id": "gst_rate", "group": "Document|Vendor|Duplicates|Purchase order", "title": "GST charged at 18%",
              "status": "pass|warn|fail|info", "severity": "none|review|block", "detail": "one or two plain sentences with the actual numbers"} ],
 "decision": "APPROVE|HOLD|REJECT",
 "headline": "<short, e.g. Hold: PO over budget, needs the buyer>",
 "reasons": ["<plain sentence>"],
 "next_action": "<the exact next step>",
 "owner": "<who acts: Vendor, Buyer, Requester, AP lead, AP team or Procurement; Payment run if approved>",
 "vendor_email": "<full email with To: and Subject: lines, only when the vendor must fix the invoice; else null>",
 "explanation": "<two or three sentences a non-finance person understands>"
}
Give at least one check per group (a "pass" check when all is well). severity is "block" only where the policy says REJECT,
"review" where it says HOLD, otherwise "none". Write amounts like ₹53,000.00. Do the arithmetic carefully.
Use only the facts given; never invent data."""


def gather_records(f: InvoiceFields) -> dict:
    """Everything the reviewer may need from the company's systems (vendor master, open POs, invoice history)."""
    vendors = store.vendors()
    pos = list(store.purchase_orders().values())
    for p in pos:
        p["billed_so_far"] = store.billed_against(p["po_number"])
    return {
        "vendor_master": [{k: v[k] for k in ("vendor_id", "name", "aliases", "gstin", "status", "status_reason", "bank_last4", "contact_email", "payment_terms_days")} for v in vendors],
        "purchase_orders": [{k: p[k] for k in ("po_number", "vendor_id", "description", "subtotal", "status", "lines", "billed_so_far")} for p in pos],
        "earlier_invoices": [{k: h[k] for k in ("vendor_id", "invoice_number", "invoice_date", "po_number", "subtotal", "total", "status")}
                             for v in vendors for h in store.ledger_for_vendor(v["vendor_id"]) if h["status"] in ("approved", "held")],
    }


def review(f: InvoiceFields, records: dict) -> tuple[dict | None, dict | None, Review]:
    policy = config.POLICY_PATH.read_text(encoding="utf-8")
    system = f"You are a careful senior accounts-payable reviewer at {config.BUYER_NAME}. Today is {date.today().isoformat()}.\n\nPOLICY:\n{policy}\n\n{TASK}"
    facts = "INVOICE (as read from the document):\n" + json.dumps(f.model_dump(), ensure_ascii=False) + "\n\n" + \
            "\n\n".join(f"{k.upper().replace('_', ' ')}:\n{json.dumps(v, ensure_ascii=False)}" for k, v in records.items())
    model, result = ask_with_backup([config.REASONING_MODEL, config.BACKUP_MODEL], system, facts, Review, effort="medium")
    vendor = next((v for v in store.vendors() if v["vendor_id"] == result.vendor_id), None)
    po = store.purchase_orders().get(result.po_number or "")
    return vendor, po, model, result
