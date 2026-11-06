"""The AP rulebook. Each function returns Check results; decide.py turns them into one decision.

Severity: "block" -> the invoice is rejected, "review" -> held for a person, "none" -> informational.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from rapidfuzz import fuzz

from . import config, store
from .models import Check, InvoiceFields


def inr(x: float | None) -> str:
    return "—" if x is None else f"₹{x:,.2f}"


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def desc_score(a: str, b: str) -> float:
    """How alike two item descriptions are, tolerant of word order and of OCR dropping spaces."""
    return max(fuzz.token_set_ratio(a.lower(), b.lower()), fuzz.ratio(_squash(a), _squash(b)))


def invoice_key(number: str | None) -> str | None:
    """Normalise an invoice number so cosmetic changes don't hide a duplicate:
    'INV-2026-0417', 'INV/2026/417' and 'inv 2026 417' all become '2026-417'."""
    if not number:
        return None
    groups = re.findall(r"[A-Za-z]+|\d+", number.upper())
    groups = [g for g in groups if g not in {"INV", "INVOICE", "BILL", "NO", "TI"}]
    return "-".join(str(int(g)) if g.isdigit() else g for g in groups) or None


# ---------- 1. Is the document itself complete and internally consistent? ----------

def document_checks(f: InvoiceFields) -> list[Check]:
    out = []
    required = {"vendor_name": "vendor name", "invoice_number": "invoice number", "invoice_date": "invoice date", "total": "total amount"}
    missing = [label for key, label in required.items() if not getattr(f, key)]
    out.append(Check(id="required_fields", group="Document", title="Required fields present",
                     status="fail" if missing else "pass", severity="review" if missing else "none",
                     detail=("Missing: " + ", ".join(missing) + ". We can't post an invoice without these; the vendor must re-issue.") if missing
                     else "Vendor, invoice number, date and total are all present."))

    if f.subtotal is not None and f.tax_amount is not None and f.total is not None:
        diff = round(f.subtotal + f.tax_amount - f.total, 2)
        ok = abs(diff) <= config.ARITHMETIC_TOLERANCE
        out.append(Check(id="arithmetic", group="Document", title="Subtotal + tax = total",
                         status="pass" if ok else "fail", severity="none" if ok else "review",
                         detail=f"{inr(f.subtotal)} + {inr(f.tax_amount)} = {inr(f.subtotal + f.tax_amount)} vs printed total {inr(f.total)}" + ("" if ok else f" (off by {inr(abs(diff))})")))
    if f.line_items and f.subtotal is not None:
        s = sum(li.amount or 0 for li in f.line_items)
        ok = abs(s - f.subtotal) <= config.ARITHMETIC_TOLERANCE
        out.append(Check(id="lines_sum", group="Document", title="Line items add up to subtotal",
                         status="pass" if ok else "warn", severity="none" if ok else "review",
                         detail=f"Lines sum to {inr(s)}; subtotal printed {inr(f.subtotal)}."))
    if f.subtotal and f.tax_amount is not None:
        rate = 100 * f.tax_amount / f.subtotal
        ok = abs(rate - config.GST_RATE) <= 0.1
        out.append(Check(id="gst_rate", group="Document", title=f"GST charged at {config.GST_RATE:g}%",
                         status="pass" if ok else "fail", severity="none" if ok else "review",
                         detail=f"Tax is {rate:.2f}% of the subtotal." + ("" if ok else " Wrong GST rate means we can't claim input credit; ask for a corrected invoice.")))
    if f.invoice_date:
        try:
            d = datetime.strptime(f.invoice_date, "%Y-%m-%d").date()
            age = (date.today() - d).days
            if age < 0:
                out.append(Check(id="date", group="Document", title="Invoice date is valid", status="fail", severity="review", detail=f"Dated {d:%d %b %Y}, which is in the future."))
            elif age > config.MAX_INVOICE_AGE_DAYS:
                out.append(Check(id="date", group="Document", title="Invoice date is valid", status="warn", severity="review", detail=f"Invoice is {age} days old (limit {config.MAX_INVOICE_AGE_DAYS})."))
            else:
                out.append(Check(id="date", group="Document", title="Invoice date is valid", status="pass", detail=f"Dated {d:%d %b %Y} ({age} days ago)."))
        except ValueError:
            out.append(Check(id="date", group="Document", title="Invoice date is valid", status="fail", severity="review", detail=f"Could not read the date '{f.invoice_date}'."))
    return out


# ---------- 2. Do we know this vendor, and is it really them? ----------

def match_vendor(f: InvoiceFields) -> tuple[dict | None, list[Check]]:
    vendors = store.vendors()
    by_gstin = next((v for v in vendors if f.vendor_gstin and v["gstin"] == f.vendor_gstin), None)
    by_name, best = None, 0.0
    if f.vendor_name:
        for v in vendors:
            # Also compare with spaces removed: OCR often drops them ("DELTAPACKAGINGCO").
            score = max(max(fuzz.token_set_ratio(f.vendor_name.lower(), n.lower()), fuzz.ratio(_squash(f.vendor_name), _squash(n)))
                        for n in [v["name"], *v["aliases"]])
            if score > best:
                by_name, best = v, score
        if best < 85:
            by_name = None

    checks = []
    vendor = by_gstin or by_name
    if not vendor:
        checks.append(Check(id="vendor_known", group="Vendor", title="Vendor is in the vendor master", status="fail", severity="review",
                            detail=f"'{f.vendor_name or 'unknown'}' (GSTIN {f.vendor_gstin or 'not printed'}) is not an onboarded vendor. Route to procurement for onboarding before paying."))
        return None, checks

    how = "GSTIN" if by_gstin else f"name ({best:.0f}% match)"
    checks.append(Check(id="vendor_known", group="Vendor", title="Vendor is in the vendor master", status="pass",
                        detail=f"Matched {vendor['name']} ({vendor['vendor_id']}) by {how}."))

    # Identity: a known vendor name with someone else's tax ID is a classic impersonation pattern.
    if by_name and f.vendor_gstin and f.vendor_gstin != by_name["gstin"]:
        checks.append(Check(id="vendor_identity", group="Vendor", title="Tax ID matches the vendor master", status="fail", severity="review",
                            detail=f"Invoice GSTIN {f.vendor_gstin} does not match {by_name['name']}'s registered GSTIN {by_name['gstin']}. Possible impersonation or a changed entity: verify with the vendor using the contact on file, not the one on this invoice."))
        vendor = by_name
    elif f.vendor_gstin:
        checks.append(Check(id="vendor_identity", group="Vendor", title="Tax ID matches the vendor master", status="pass", detail=f"GSTIN {f.vendor_gstin} matches."))
    else:
        checks.append(Check(id="vendor_identity", group="Vendor", title="Tax ID matches the vendor master", status="warn", severity="review",
                            detail="No GSTIN printed; we can't confirm the seller or claim input tax credit."))

    if f.bank_account_last4 and f.bank_account_last4 != vendor["bank_last4"]:
        checks.append(Check(id="vendor_bank", group="Vendor", title="Bank account matches the vendor master", status="fail", severity="review",
                            detail=f"Invoice asks for payment to an account ending {f.bank_account_last4}; master has ending {vendor['bank_last4']}. Bank-change requests must be verified by phone before any payment."))
    elif f.bank_account_last4:
        checks.append(Check(id="vendor_bank", group="Vendor", title="Bank account matches the vendor master", status="pass", detail=f"Account ending {f.bank_account_last4} matches."))

    if vendor["status"] != "approved":
        checks.append(Check(id="vendor_status", group="Vendor", title="Vendor is approved for payment", status="fail", severity="block",
                            detail=f"{vendor['name']} is {vendor['status'].upper()}: {vendor['status_reason'] or 'no reason recorded'}."))
    else:
        checks.append(Check(id="vendor_status", group="Vendor", title="Vendor is approved for payment", status="pass", detail="Active, approved vendor."))
    return vendor, checks


# ---------- 3. Have we seen this invoice before? ----------

def duplicate_checks(f: InvoiceFields, vendor: dict | None, sha: str) -> list[Check]:
    same_file = store.ledger_by_sha(sha)
    if same_file:
        return [Check(id="duplicate", group="Duplicates", title="Not a duplicate", status="fail", severity="block",
                      detail=f"This exact file was already processed as invoice {same_file['invoice_number']} on {same_file['recorded_on']} ({same_file['status']}).")]
    if not vendor:
        return [Check(id="duplicate", group="Duplicates", title="Not a duplicate", status="info", detail="Skipped: vendor not identified.")]

    key = invoice_key(f.invoice_number)
    history = [h for h in store.ledger_for_vendor(vendor["vendor_id"]) if h["status"] in ("approved", "held")]
    for h in history:
        if key and h["invoice_key"] == key:
            same_number = (h["invoice_number"] or "").strip().upper() == (f.invoice_number or "").strip().upper()
            note = "" if same_number else f" The number was re-formatted ('{f.invoice_number}' vs '{h['invoice_number']}') but it is the same invoice."
            return [Check(id="duplicate", group="Duplicates", title="Not a duplicate", status="fail", severity="block",
                          detail=f"{vendor['name']} invoice {h['invoice_number']} for {inr(h['total'])} was already {h['status']} on {h['recorded_on']}.{note}")]

    # Near-duplicates: different number, but same money and close dates (common with re-sent or re-typed invoices).
    if f.total and f.invoice_date:
        d = datetime.strptime(f.invoice_date, "%Y-%m-%d").date()
        for h in history:
            if h["total"] and abs(h["total"] - f.total) <= 1 and h["invoice_date"]:
                gap = abs((d - datetime.strptime(h["invoice_date"], "%Y-%m-%d").date()).days)
                if gap <= config.NEAR_DUPLICATE_DAYS:
                    return [Check(id="duplicate", group="Duplicates", title="Not a duplicate", status="warn", severity="review",
                                  detail=f"Same amount {inr(f.total)} as {h['invoice_number']} ({h['status']}) dated {gap} days apart. Could be a re-sent invoice; confirm before paying.")]
    return [Check(id="duplicate", group="Duplicates", title="Not a duplicate", status="pass",
                  detail=f"No earlier invoice from {vendor['name']} with this number or amount ({len(history)} on file).")]


# ---------- 4. Which PO is this for, and does it fit? ----------

def _line_match(f: InvoiceFields, po: dict) -> float:
    if not f.line_items:
        return 0.0
    hits = 0
    for li in f.line_items:
        for pl in po["lines"]:
            if desc_score(li.description, pl["item"]) >= 70 and li.unit_price and abs(li.unit_price - pl["unit_price"]) / pl["unit_price"] <= 0.05:
                hits += 1
                break
    return hits / len(f.line_items)


def infer_po(f: InvoiceFields, vendor: dict) -> tuple[dict | None, float, list[str]]:
    """No PO printed: score the vendor's open POs on remaining balance and line items."""
    pos = [p for p in store.purchase_orders().values() if p["vendor_id"] == vendor["vendor_id"] and p["status"] == "open"]
    scored = []
    for p in pos:
        remaining = p["subtotal"] - store.billed_against(p["po_number"])
        amount = max(0.0, 1 - abs((f.subtotal or 0) - remaining) / max(remaining, 1)) if f.subtotal else 0.0
        lines = _line_match(f, p)
        scored.append((round(0.5 * amount + 0.5 * lines, 2), p, amount, lines))
    scored.sort(key=lambda s: -s[0])
    notes = [f"{p['po_number']}: score {s:.2f} (amount fit {a:.0%}, line items {l:.0%})" for s, p, a, l in scored]
    if scored and scored[0][0] >= config.PO_INFERENCE_MIN_SCORE:
        return scored[0][1], scored[0][0], notes
    return None, scored[0][0] if scored else 0.0, notes


def po_checks(f: InvoiceFields, vendor: dict | None) -> tuple[dict | None, list[Check]]:
    if not vendor:
        return None, [Check(id="po_match", group="Purchase order", title="Matched to a purchase order", status="info", detail="Skipped: vendor not identified.")]
    pos = store.purchase_orders()
    checks = []
    if f.po_reference:
        po = pos.get(f.po_reference)
        if not po:
            return None, [Check(id="po_match", group="Purchase order", title="Matched to a purchase order", status="fail", severity="review",
                                detail=f"{f.po_reference} does not exist in the PO register. Ask the requester for the correct PO.")]
        if po["vendor_id"] != vendor["vendor_id"]:
            return po, [Check(id="po_match", group="Purchase order", title="Matched to a purchase order", status="fail", severity="block",
                              detail=f"{po['po_number']} was issued to a different vendor ({po['vendor_id']}), not {vendor['name']}.")]
        checks.append(Check(id="po_match", group="Purchase order", title="Matched to a purchase order", status="pass",
                            detail=f"{po['po_number']} — {po['description']} ({inr(po['subtotal'])} before tax), printed on the invoice."))
    else:
        po, score, notes = infer_po(f, vendor)
        if not po:
            return None, [Check(id="po_match", group="Purchase order", title="Matched to a purchase order", status="fail", severity="review",
                                detail="No PO number on the invoice and no open PO for this vendor fits it. " + ("Candidates: " + "; ".join(notes) if notes else "Vendor has no open POs."))]
        checks.append(Check(id="po_match", group="Purchase order", title="Matched to a purchase order", status="warn", severity="review",
                            detail=f"No PO number printed. Best fit is {po['po_number']} ({po['description']}), confidence {score:.0%}. A person must confirm before we pay against an inferred PO. Scores: " + "; ".join(notes)))

    if po["status"] != "open":
        checks.append(Check(id="po_open", group="Purchase order", title="PO is open", status="fail", severity="review",
                            detail=f"{po['po_number']} is {po['status']}. Buyer must reopen it or issue a new PO."))
        return po, checks

    billed = store.billed_against(po["po_number"])
    new_total = billed + (f.subtotal or 0)
    over = new_total - po["subtotal"]
    limit = min(po["subtotal"] * config.TOLERANCE_PCT / 100, config.TOLERANCE_ABS)
    split = f" (already billed {inr(billed)} on earlier invoices)" if billed else ""
    if over <= 0:
        checks.append(Check(id="po_amount", group="Purchase order", title="Within PO amount", status="pass",
                            detail=f"This invoice {inr(f.subtotal)}{split}; PO {inr(po['subtotal'])}. Remaining after this: {inr(max(0.0, -over))}."))
    elif over <= limit:
        checks.append(Check(id="po_amount", group="Purchase order", title="Within PO amount", status="warn", severity="none",
                            detail=f"Over the PO by {inr(over)} ({100 * over / po['subtotal']:.2f}%){split}, inside the tolerance of {config.TOLERANCE_PCT:g}% / {inr(config.TOLERANCE_ABS)}. Approved with a note."))
    else:
        checks.append(Check(id="po_amount", group="Purchase order", title="Within PO amount", status="fail", severity="review",
                            detail=f"Cumulative billing {inr(new_total)}{split} exceeds the PO {inr(po['subtotal'])} by {inr(over)} ({100 * over / po['subtotal']:.1f}%), beyond the {config.TOLERANCE_PCT:g}% / {inr(config.TOLERANCE_ABS)} tolerance. Needs a PO amendment from the buyer or a credit note from the vendor."))

    # Line-level: price drift and quantities beyond what was ordered.
    if f.line_items:
        issues, notes, ok = [], [], []
        for li in f.line_items:
            best = max(po["lines"], key=lambda pl: desc_score(li.description, pl["item"]))
            if desc_score(li.description, best["item"]) < 60:
                issues.append(f"'{li.description}' is not on the PO")
                continue
            if best["qty"] == 1 and (li.quantity or 1) == 1:
                ok.append(f"{best['item']}: lump-sum line, checked against the PO total")
                continue
            if li.unit_price and best["unit_price"]:
                drift = 100 * (li.unit_price - best["unit_price"]) / best["unit_price"]
                if abs(drift) > config.UNIT_PRICE_TOLERANCE_PCT:
                    issues.append(f"{best['item']}: billed {inr(li.unit_price)} vs PO {inr(best['unit_price'])} ({drift:+.1f}%)")
                elif abs(drift) > 0.01:
                    notes.append(f"{best['item']}: price {drift:+.2f}% vs PO (within {config.UNIT_PRICE_TOLERANCE_PCT:g}%)")
            if li.quantity and li.quantity > best["qty"]:
                issues.append(f"{best['item']}: billed qty {li.quantity:g} > ordered {best['qty']:g}")
        if issues:
            checks.append(Check(id="po_lines", group="Purchase order", title="Line items match the PO", status="fail", severity="review", detail="; ".join(issues) + "."))
        else:
            checks.append(Check(id="po_lines", group="Purchase order", title="Line items match the PO", status="warn" if notes else "pass", severity="none",
                                detail="; ".join(notes + ok) + "." if notes or ok else f"All {len(f.line_items)} line(s) match PO items, prices and quantities."))
    else:
        checks.append(Check(id="po_lines", group="Purchase order", title="Line items match the PO", status="info",
                            detail="Invoice is bundled (no itemised lines); matched on totals only."))
    return po, checks
