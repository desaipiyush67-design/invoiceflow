"""Turn rule results into one decision a person can act on.

Policy (deliberately simple, so it can be explained to a buyer in one breath):
- any "block" check  -> REJECT  (never payable as submitted: duplicate, blocked vendor, PO of another vendor)
- any "review" check -> HOLD    (maybe payable, but a person must look: says who and what to do)
- otherwise          -> APPROVE (notes from warnings are kept on the record)
"""
from __future__ import annotations

from .models import Check, Decision, InvoiceFields
from .rules import inr

# Who resolves each kind of problem, and what they do.
ROUTES = {
    "required_fields": ("Vendor", "Ask the vendor to re-issue the invoice with the missing fields."),
    "arithmetic": ("Vendor", "Ask the vendor for a corrected invoice; the totals don't add up."),
    "lines_sum": ("AP team", "Check the line items against the subtotal."),
    "gst_rate": ("Vendor", "Ask the vendor for a corrected tax invoice at the right GST rate."),
    "date": ("AP team", "Confirm the invoice date with the vendor."),
    "vendor_known": ("Procurement", "Onboard the vendor (KYC, GSTIN, bank details) before this can be paid."),
    "vendor_identity": ("AP lead", "Verify the vendor's identity using the contact details on file, not the ones on the invoice."),
    "vendor_bank": ("AP lead", "Call the vendor on the number on file to confirm the bank change before paying."),
    "duplicate": ("AP team", "Compare with the earlier invoice before paying."),
    "po_match": ("Requester", "Confirm which purchase order this invoice is for."),
    "po_open": ("Buyer", "Reopen the PO or raise a new one."),
    "po_amount": ("Buyer", "Approve a PO amendment for the excess, or ask the vendor for a credit note."),
    "po_lines": ("Buyer", "Confirm the price or quantity difference with the vendor."),
}
REJECT_HEADLINES = {
    "duplicate": "Reject: duplicate of an invoice already on file",
    "vendor_status": "Reject: vendor is not approved for payment",
    "po_match": "Reject: PO belongs to another vendor",
}
VENDOR_FIXABLE = {"required_fields", "arithmetic", "gst_rate"}


def _email(f: InvoiceFields, vendor: dict | None, problems: list[Check]) -> str | None:
    fixable = [c for c in problems if c.id in VENDOR_FIXABLE]
    if not fixable or not vendor:
        return None
    asks = "\n".join(f"- {c.detail}" for c in fixable)
    ref = f"invoice {f.invoice_number}" if f.invoice_number else f"your invoice for {inr(f.total)}"
    return (f"To: {vendor['contact_email']}\nSubject: Action needed on {ref}\n\n"
            f"Hello {vendor['name']} team,\n\nWe received {ref} but can't process it yet:\n{asks}\n\n"
            f"Please send a corrected invoice and we'll process it within your {vendor['payment_terms_days']}-day terms.\n\n"
            f"Thanks,\nAccounts Payable, Northwind Retail Pvt Ltd")


def decide(f: InvoiceFields, vendor: dict | None, po: dict | None, checks: list[Check]) -> Decision:
    blocks = [c for c in checks if c.severity == "block"]
    reviews = [c for c in checks if c.severity == "review"]
    notes = [c for c in checks if c.status == "warn" and c.severity == "none"]
    who = vendor["name"] if vendor else (f.vendor_name or "Unknown vendor")
    amount = inr(f.total)

    if blocks:
        lead = blocks[0]
        return Decision(
            decision="REJECT", headline=REJECT_HEADLINES.get(lead.id, f"Reject: {lead.title.lower()} failed"),
            reasons=[c.detail for c in blocks] + [c.detail for c in reviews],
            next_action="Do not pay. " + ROUTES.get(lead.id, ("AP team", "Review."))[1], owner=ROUTES.get(lead.id, ("AP team",))[0],
            explanation=f"{who}'s invoice for {amount} cannot be paid as submitted. {blocks[0].detail}")

    if reviews:
        owners = []
        for c in reviews:
            o = ROUTES.get(c.id, ("AP team",))[0]
            if o not in owners:
                owners.append(o)
        return Decision(
            decision="HOLD", headline=f"Hold: {len(reviews)} issue{'s need' if len(reviews) > 1 else ' needs'} a person",
            reasons=[c.detail for c in reviews],
            next_action=" ".join(dict.fromkeys(ROUTES.get(c.id, ("", "Review."))[1] for c in reviews)),
            owner=", ".join(owners), vendor_email=_email(f, vendor, reviews),
            explanation=f"{who}'s invoice for {amount} is not paid yet. It goes to {', '.join(owners)} with the specific fix below; nothing else blocks it.")

    po_txt = f" against {po['po_number']}" if po else ""
    return Decision(
        decision="APPROVE", headline="Approve for payment",
        reasons=[c.detail for c in notes] or ["All checks passed."],
        next_action=f"Schedule payment of {amount} to {who} within {vendor['payment_terms_days'] if vendor else 30} days.", owner="AP team",
        explanation=f"{who}'s invoice {f.invoice_number} for {amount}{po_txt} matches the vendor master, the PO and our records." + (" Note: " + " ".join(c.detail for c in notes) if notes else ""))
