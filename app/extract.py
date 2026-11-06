"""Stage 2: the vision model reads the invoice image and returns its fields."""
from __future__ import annotations

import base64

from . import config
from .ai import ask_with_backup
from .models import InvoiceFields
from .reader import Document

SYSTEM = f"""You are an accounts-payable clerk reading a vendor invoice. Reply with one JSON object only, with exactly these keys:
vendor_name, vendor_gstin, invoice_number, invoice_date (YYYY-MM-DD), po_reference, currency,
line_items (list of {{description, quantity, unit_price, amount}}), subtotal, tax_amount, total, bank_account_last4.

Rules:
- Copy values exactly as printed. If something is not printed on the invoice, use null. Never infer or invent a value.
- The buyer is {config.BUYER_NAME} (GSTIN {config.BUYER_GSTIN}). vendor_* fields describe the SELLER, never the buyer.
- Indian dates are day-first: 03/11/2026 is 3 November 2026.
- Amounts are plain numbers (1,20,000.00 -> 120000.0). subtotal is the amount before tax.
- tax_amount is the sum of all GST lines (CGST + SGST, or IGST).
- po_reference only if a purchase order number is printed, written like PO-4501.
- bank_account_last4: last 4 digits of the vendor's bank account number, if printed."""


def extract(doc: Document) -> InvoiceFields:
    content = [{"type": "text", "text": "Read this invoice and return the JSON."}]
    if doc.text:
        content.append({"type": "text", "text": "Embedded text layer of the same invoice (use it to read numbers exactly):\n" + doc.text[:6000]})
    content += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode()}} for img in doc.images]
    return ask_with_backup([config.VISION_MODEL], SYSTEM, content, InvoiceFields, effort="none")[1]
