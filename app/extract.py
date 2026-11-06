"""Pull structured fields out of an invoice's text (text layer or OCR) with label-driven rules.

Nothing is guessed: a field that is not printed on the invoice comes back empty.
"""
from __future__ import annotations

import re
from datetime import datetime

from . import config
from .models import InvoiceFields, LineItem

NUM = r"(?:₹|Rs\.?|INR)?\s*(-?\d[\d,]*(?:\.\d+)?)"
# No \b: OCR often glues the label to the number ("GSTIN29AAGFD...").
GSTIN_RE = re.compile(r"(\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z])(?![0-9A-Z])")
COMPANY_HINT = re.compile(r"\b(pvt|ltd|llp|limited|co\b|company|services|logistics|supplies|packaging|inc)\b", re.I)


def _num(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _last_number(line: str) -> float | None:
    nums = re.findall(r"\d[\d,]*(?:\.\d+)?", line)
    return _num(nums[-1]) if nums else None


def _iso_date(raw: str) -> str | None:
    raw = raw.strip().replace(",", "")
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d/%b/%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%b %d %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def normalize_po(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    return f"PO-{digits}" if digits else None


def parse_text(text: str) -> InvoiceFields:
    """Label-driven parser. Works on clean text layers and on OCR output (where rows can be noisy)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    flat = "\n".join(lines)
    f = InvoiceFields()

    m = re.search(r"(?:invoice|bill)\s*(?:no|number|#)\.?\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-_]*\d[A-Z0-9/\-_]*)", flat, re.I)
    if m:
        f.invoice_number = m.group(1).strip()

    m = re.search(r"(?:invoice\s*)?dated?\s*[:\-]?\s*(\d{1,2}[\-/ .][A-Za-z]{3,9}[\-/ .]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})", flat, re.I)
    if m:
        f.invoice_date = _iso_date(m.group(1).replace(".", "/") if re.match(r"\d{1,2}\.\d", m.group(1)) else m.group(1))

    m = re.search(r"(?:P\.?\s?O\.?|purchase\s*order)\s*(?:no|number|ref(?:erence)?|#)?\.?\s*[:#]?\s*(PO[\s\-]?\d{3,6}|\d{4,6})\b", flat, re.I)
    if m:
        f.po_reference = normalize_po(m.group(1))

    gstins = [g for g in GSTIN_RE.findall(flat.upper()) if g != config.BUYER_GSTIN]
    if gstins:
        f.vendor_gstin = gstins[0]

    # Vendor = first company-looking line above "Bill To" that isn't the buyer. Rows can carry other columns
    # ("Cobalt IT Services Pvt Ltd  Invoice # CIT-7781"), so only the first cell of each row is considered.
    fallback = None
    for l in lines:
        cell = re.split(r"\s{2,}", l)[0].strip()
        if re.match(r"(bill|billed|ship|customer)\s*(to)?\b", cell, re.I):
            break
        if config.BUYER_NAME.lower().replace(" ", "") in cell.lower().replace(" ", "") or re.search(r"invoice|gstin|address|phone|email|@|\d{3}", cell, re.I):
            continue
        if COMPANY_HINT.search(cell):
            f.vendor_name = cell
            break
        if fallback is None and re.fullmatch(r"[A-Za-z&.,' ]{4,}", cell):
            fallback = cell  # e.g. OCR'd "DELTAPACKAGINGCO" with spaces lost
    f.vendor_name = f.vendor_name or fallback

    tax_parts = []
    for l in lines:
        low = l.lower()
        if re.search(r"sub\s*-?\s*total|taxable\s*(value|amount)|amount\s*before\s*tax", low):
            f.subtotal = _last_number(l)
        elif re.search(r"\b(cgst|sgst|igst)\b", low) and "gstin" not in low:
            v = _last_number(l)
            if v is not None:
                tax_parts.append(v)
        elif re.search(r"total\s*(tax|gst)", low):
            f.tax_amount = _last_number(l)
        elif re.search(r"grand\s*total|total\s*(amount|payable|due)|amount\s*(due|payable)|invoice\s*total|^total\b", low):
            f.total = _last_number(l)
    if f.tax_amount is None and tax_parts:
        f.tax_amount = round(sum(tax_parts), 2)

    m = re.search(r"(?:a/c|account)\s*(?:no|number)?\.?\s*[:]?\s*[X*\d\s-]*?(\d{4})\b", flat, re.I)
    if m:
        f.bank_account_last4 = m.group(1)

    # Line items: rows ending in qty, rate, amount where qty * rate ~= amount.
    for l in lines:
        found = list(re.finditer(r"\d[\d,]*(?:\.\d+)?", l))
        if len(found) < 3 or re.search(r"total|gst|tax|invoice|date|account|ifsc|phone|po\b", l, re.I):
            continue
        q, r, a = (_num(x.group()) for x in found[-3:])
        if q and r and a and abs(q * r - a) <= max(1.0, a * 0.001):
            desc = l[:found[-3].start()]                      # everything left of the qty column
            desc = re.sub(r"^\s*\d+\s*[.)]?\s*(?=\D)", "", desc)  # drop the serial number ("1." / "2)")
            desc = re.sub(r"(₹|Rs\.?|INR)", "", desc)
            f.line_items.append(LineItem(description=re.sub(r"\s{2,}", " ", desc).strip(" -|"), quantity=q, unit_price=r, amount=a))
    return f


def extract(text: str) -> tuple[InvoiceFields, str, list[str]]:
    """Returns (fields, extractor name, notes)."""
    return parse_text(text), "Built-in parser", []
