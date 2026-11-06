# Northwind Retail Pvt Ltd — Accounts Payable policy

Buyer: Northwind Retail Pvt Ltd, Bengaluru, GSTIN 29AAACN1234F1Z5. All amounts are INR.

## 1. Invoice must be complete and correct
- An invoice needs: vendor name, invoice number, invoice date and total. If any is missing, HOLD and ask the vendor to re-issue.
- Subtotal + tax must equal the total (₹1 rounding allowed). Line items must add up to the subtotal.
- GST must be 18% of the subtotal (CGST 9% + SGST 9% for Karnataka vendors, IGST 18% for other states). A wrong rate means we can't claim input credit: HOLD and ask the vendor for a corrected invoice.
- The invoice date must not be in the future or older than 180 days.

## 2. Vendor must be known and genuine
- The vendor must be in the vendor master. Unknown vendor: HOLD, procurement must onboard them first.
- The GSTIN on the invoice must match the vendor master. A known vendor name with a different GSTIN is a classic impersonation pattern: HOLD for the AP lead.
- The bank account on the invoice must match the vendor master. Any request to pay a new account must be verified by phone using the contact on file, never the contact on the invoice: HOLD for the AP lead.
- A vendor whose status is not "approved" (e.g. blocked) must never be paid: REJECT.

## 3. No double payments
- If the same vendor already has an approved or held invoice with the same invoice number, it is a duplicate: REJECT. Treat numbers as the same when they differ only in formatting (separators, "INV" prefix, leading zeros): INV-2026-0417 = INV/2026/417.
- Same vendor, same total, dated within 10 days of an earlier invoice but a different number: possible re-send, HOLD for the AP team.

## 4. Every invoice must match a purchase order
- The PO printed on the invoice must exist and belong to the same vendor. A PO issued to a different vendor: REJECT. A PO that is not open: HOLD for the buyer.
- No PO printed on the invoice: find the vendor's open PO that best fits the amount and line items and suggest it, but ALWAYS HOLD for the requester to confirm, even when the fit is perfect. Never pay against an inferred PO.
- Compare amounts before tax. Vendors may bill one PO across several invoices: add this invoice to what was already billed (approved) on the PO. If the cumulative amount exceeds the PO by more than 2% of the PO or ₹5,000, whichever is lower: HOLD for the buyer (PO amendment or credit note). A smaller excess is approved with a note.
- Unit prices may differ from the PO by up to 2% (approve with a note); more than that, or a quantity above what was ordered, or an item not on the PO: HOLD for the buyer. A lump-sum line (PO quantity 1, e.g. a service fee) may be billed in parts across invoices: do NOT compare its unit price; check it only through the cumulative PO amount rule above.

## 5. Decision
- REJECT: anything that must never be paid as submitted (duplicate, blocked vendor, PO belonging to another vendor).
- HOLD: anything that may be payable but needs a person. Always name the owner (Vendor, Buyer, Requester, AP lead, AP team, Procurement) and the exact next step.
- APPROVE: everything checks out; mention any small differences that were within tolerance.
- When the vendor must fix the invoice (missing fields, wrong maths, wrong GST), draft a short, polite email to the vendor's contact on file.
