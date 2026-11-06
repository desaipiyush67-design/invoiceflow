"""Generate the demo invoices in samples/. Three vendor layouts, one scanned (image-only) PDF.

python tools/make_samples.py
"""
from __future__ import annotations

import io
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "samples"
BUYER = ("Northwind Retail Pvt Ltd", "No. 14, 2nd Floor, Prestige Tech Park, Outer Ring Road", "Bengaluru 560103, Karnataka", "GSTIN: 29AAACN1234F1Z5")
W, H = A4


def money(x: float) -> str:
    """Indian digit grouping: 1,20,000.00"""
    neg, x = x < 0, abs(x)
    whole, frac = f"{x:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    s = ",".join(groups + [tail]) if groups else tail
    return ("-" if neg else "") + s + "." + frac


def totals(lines, rate=18.0):
    sub = round(sum(q * r for _, q, r in lines), 2)
    tax = round(sub * rate / 100, 2)
    return sub, tax, round(sub + tax, 2)


def layout_classic(c, v, inv):
    """Vendor block top-left, TAX INVOICE box top-right, CGST/SGST split."""
    c.setFont("Helvetica-Bold", 15); c.drawString(40, H - 55, v["name"])
    c.setFont("Helvetica", 9)
    for i, t in enumerate([v["addr"], v["city"], f"GSTIN: {v['gstin']}", f"Email: {v['email']}"]):
        c.drawString(40, H - 72 - i * 12, t)
    c.setFillColor(colors.HexColor("#1f3a5f")); c.rect(360, H - 125, 195, 80, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 13); c.drawString(372, H - 64, "TAX INVOICE")
    c.setFont("Helvetica", 9)
    meta = [("Invoice No:", inv.get("number")), ("Invoice Date:", inv.get("date")), ("PO Number:", inv.get("po"))]
    y = H - 82
    for k, val in meta:
        if val:
            c.drawString(372, y, f"{k} {val}"); y -= 13
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9); c.drawString(40, H - 150, "Bill To:")
    c.setFont("Helvetica", 9)
    for i, t in enumerate(BUYER):
        c.drawString(40, H - 163 - i * 12, t)
    y = H - 235
    c.setFillColor(colors.HexColor("#e8edf3")); c.rect(40, y - 4, 515, 18, fill=1, stroke=0); c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    for x, t in [(46, "#"), (70, "Description"), (330, "Qty"), (390, "Rate"), (480, "Amount")]:
        c.drawString(x, y, t)
    c.setFont("Helvetica", 9)
    for i, (d, q, r) in enumerate(inv["lines"], 1):
        y -= 20
        c.drawString(46, y, str(i)); c.drawString(70, y, d); c.drawRightString(355, y, f"{q:g}")
        c.drawRightString(440, y, money(r)); c.drawRightString(550, y, money(q * r))
    sub, tax, tot = inv["totals"]
    y -= 35
    rows = [("Subtotal", sub), (f"CGST @ {inv['rate'] / 2:g}%", tax / 2), (f"SGST @ {inv['rate'] / 2:g}%", tax / 2)]
    for k, val in rows:
        c.drawString(380, y, k); c.drawRightString(550, y, money(val)); y -= 15
    c.setFont("Helvetica-Bold", 10); c.drawString(380, y - 3, "Grand Total"); c.drawRightString(550, y - 3, "Rs. " + money(tot))
    c.setFont("Helvetica", 8)
    c.drawString(40, 90, f"Bank: {v['bank']}  |  A/c No: XXXXXX{inv.get('bank4', v['bank4'])}  |  IFSC: {v['ifsc']}")
    c.drawString(40, 76, f"Payment terms: {v['terms']}. This is a computer generated invoice.")


def layout_band(c, v, inv):
    """Coloured header band, 'Bill No' / 'Dated' / 'Your PO Ref', Taxable Value wording, dd/mm/yyyy dates."""
    c.setFillColor(colors.HexColor(v.get("colour", "#0f766e"))); c.rect(0, H - 95, W, 95, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 18); c.drawCentredString(W / 2, H - 45, v["name"].upper())
    c.setFont("Helvetica", 9); c.drawCentredString(W / 2, H - 62, f"{v['addr']}, {v['city']}")
    c.drawCentredString(W / 2, H - 76, f"GSTIN {v['gstin']}  ·  {v['email']}")
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 12); c.drawString(40, H - 125, "INVOICE")
    c.setFont("Helvetica", 9)
    y = H - 145
    for k, val in [("Bill No:", inv.get("number")), ("Dated:", inv.get("date")), ("Your PO Ref:", inv.get("po"))]:
        if val:
            c.drawString(40, y, f"{k} {val}"); y -= 13
    c.setFont("Helvetica-Bold", 9); c.drawString(330, H - 145, "Billed To")
    c.setFont("Helvetica", 9)
    for i, t in enumerate(BUYER):
        c.drawString(330, H - 158 - i * 12, t)
    y = H - 235
    c.line(40, y + 14, 555, y + 14); c.line(40, y - 5, 555, y - 5)
    c.setFont("Helvetica-Bold", 9)
    for x, t in [(44, "S.No"), (80, "Particulars"), (330, "Qty"), (395, "Rate (Rs)"), (480, "Amount (Rs)")]:
        c.drawString(x, y, t)
    c.setFont("Helvetica", 9)
    for i, (d, q, r) in enumerate(inv["lines"], 1):
        y -= 20
        c.drawString(48, y, f"{i}."); c.drawString(80, y, d); c.drawRightString(355, y, f"{q:g}")
        c.drawRightString(445, y, money(r)); c.drawRightString(550, y, money(q * r))
    sub, tax, tot = inv["totals"]
    y -= 30; c.line(330, y + 14, 555, y + 14)
    for k, val in [("Taxable Value", sub), (f"CGST @{inv['rate'] / 2:g}%", tax / 2), (f"SGST @{inv['rate'] / 2:g}%", tax / 2)]:
        c.drawString(335, y, k); c.drawRightString(550, y, money(val)); y -= 15
    c.setFont("Helvetica-Bold", 10); c.drawString(335, y - 3, "Total Amount Payable"); c.drawRightString(550, y - 3, money(tot))
    c.setFont("Helvetica", 8)
    c.drawString(40, 90, f"Please remit to {v['bank']}, Account No. XXXX{inv.get('bank4', v['bank4'])}, IFSC {v['ifsc']}.")
    c.drawString(40, 76, f"{v['terms']}. Subject to Bengaluru jurisdiction.")


def layout_igst(c, v, inv):
    """Inter-state vendor: IGST, 'Invoice #', 'Purchase Order:', 'Amount before tax', 'Total Due'."""
    c.setFont("Helvetica-Bold", 22); c.setFillColor(colors.HexColor("#4338ca")); c.drawString(40, H - 60, v["name"].split()[0].upper())
    c.setFillColor(colors.black); c.setFont("Helvetica", 9)
    c.drawString(40, H - 76, v["name"]); c.drawString(40, H - 88, f"{v['addr']}, {v['city']}"); c.drawString(40, H - 100, f"GSTIN: {v['gstin']}")
    c.setFont("Helvetica-Bold", 11); c.drawRightString(555, H - 60, "Tax Invoice")
    c.setFont("Helvetica", 9)
    y = H - 78
    for k, val in [("Invoice #", inv.get("number")), ("Invoice Date:", inv.get("date")), ("Purchase Order:", inv.get("po"))]:
        if val:
            c.drawRightString(555, y, f"{k} {val}"); y -= 13
    c.setFont("Helvetica-Bold", 9); c.drawString(40, H - 130, "Customer")
    c.setFont("Helvetica", 9)
    for i, t in enumerate(BUYER):
        c.drawString(40, H - 143 - i * 12, t)
    y = H - 220
    c.setFont("Helvetica-Bold", 9)
    for x, t in [(40, "Item"), (330, "Qty"), (390, "Unit price"), (485, "Line total")]:
        c.drawString(x, y, t)
    c.line(40, y - 5, 555, y - 5)
    c.setFont("Helvetica", 9)
    for d, q, r in inv["lines"]:
        y -= 20
        c.drawString(40, y, d); c.drawRightString(350, y, f"{q:g}"); c.drawRightString(445, y, money(r)); c.drawRightString(550, y, money(q * r))
    sub, tax, tot = inv["totals"]
    y -= 35
    for k, val in [("Amount before tax", sub), (f"IGST @ {inv['rate']:g}%", tax)]:
        c.drawString(370, y, k); c.drawRightString(550, y, money(val)); y -= 15
    c.setFont("Helvetica-Bold", 11); c.drawString(370, y - 4, "Total Due"); c.drawRightString(550, y - 4, "INR " + money(tot))
    c.setFont("Helvetica", 8)
    if inv.get("bank_note"):
        c.setFillColor(colors.HexColor("#b91c1c")); c.drawString(40, 104, inv["bank_note"]); c.setFillColor(colors.black)
    c.drawString(40, 90, f"Bank transfer: {v['bank']} · Account number XXXXXXXX{inv.get('bank4', v['bank4'])} · IFSC {v['ifsc']}")
    c.drawString(40, 76, f"{v['terms']}.")


VENDORS = {
    "apex": dict(name="Apex Office Supplies Pvt Ltd", addr="42, 3rd Cross, Peenya Industrial Area", city="Bengaluru 560058", gstin="29AAPCA1111K1Z2",
                 email="accounts@apexoffice.example", bank="HDFC Bank", bank4="4417", ifsc="HDFC0001234", terms="Payment within 30 days"),
    "blueline": dict(name="BlueLine Logistics LLP", addr="Plot 9, KIADB Hoskote", city="Bengaluru 562114", gstin="29AAKFB2222L1Z8",
                     email="billing@blueline.example", bank="ICICI Bank", bank4="9032", ifsc="ICIC0004321", terms="Due in 45 days", colour="#1d4ed8"),
    "cobalt": dict(name="Cobalt IT Services Pvt Ltd", addr="Unit 501, Mindspace, Malad West", city="Mumbai 400064", gstin="27AABCC3333M1Z1",
                   email="ar@cobaltit.example", bank="Axis Bank", bank4="1185", ifsc="UTIB0000552", terms="Net 30"),
    "delta": dict(name="Delta Packaging Co", addr="18, Bommasandra Industrial Area", city="Bengaluru 560099", gstin="29AAGFD4444N1Z4",
                  email="accounts@deltapack.example", bank="Canara Bank", bank4="7720", ifsc="CNRB0002610", terms="Due in 30 days", colour="#92400e"),
    "evergreen": dict(name="Evergreen Facility Services", addr="7, Old Madras Road", city="Bengaluru 560016", gstin="29AAJFE5555P1Z9",
                      email="finance@evergreenfs.example", bank="SBI", bank4="3051", ifsc="SBIN0008899", terms="Payment within 30 days"),
}

# name, vendor, layout, invoice fields, extra
SAMPLES = [
    ("01_happy_apex_paper_toner.pdf", "apex", layout_classic,
     dict(number="INV-2026-0533", date="04-Nov-2026", po="PO-4501", lines=[("A4 paper ream 75gsm", 50, 260), ("Laser toner cartridge", 20, 3200)])),
    ("02_edge_duplicate_reformatted_apex.pdf", "apex", layout_classic,
     dict(number="INV/2026/417", date="02-Nov-2026", po="PO-4505", lines=[("Ergonomic office chair", 10, 4500)])),
    ("03_edge_split_po_overrun_blueline.pdf", "blueline", layout_band,
     dict(number="BL-2026-131", date="03/11/2026", po="PO-4502", lines=[("Inbound freight services - October (balance)", 1, 23000)])),
    ("04_edge_scanned_no_po_delta.pdf", "delta", layout_band,
     dict(number="DP/889", date="01/11/2026", po=None, lines=[("Corrugated boxes 5-ply", 2000, 18.5), ("Packing tape 2 inch", 100, 85)]), "scan"),
    ("05_edge_gstin_bank_mismatch_cobalt.pdf", "cobalt", layout_igst,
     dict(number="CIT-7781", date="03 Nov 2026", po="PO-4503", gstin="27AABCC9999M1Z1", bank4="6621",
          bank_note="NOTE: Our bank details have changed. Please pay only to the new account below.",
          lines=[("Laptop setup and imaging (hours)", 40, 1500), ("Annual maintenance contract", 1, 25000)])),
    ("06_extra_within_tolerance_cobalt.pdf", "cobalt", layout_igst,
     dict(number="CIT-7790", date="05 Nov 2026", po="PO-4506", lines=[("Cloud migration support", 1, 121500)])),
    ("07_extra_blocked_vendor_evergreen.pdf", "evergreen", layout_classic,
     dict(number="EFS/1093", date="31-Oct-2026", po="PO-4507", lines=[("Housekeeping services - monthly", 1, 60000)])),
    ("08_extra_missing_number_wrong_gst_blueline.pdf", "blueline", layout_band,
     dict(number=None, date="04/11/2026", po="PO-4502", rate=12.0, lines=[("Inbound freight services - October", 1, 15000)])),
]


def scanify(pdf_bytes: bytes) -> bytes:
    """Render to an image, tilt it, add grain and blur, and save as an image-only PDF (no text layer)."""
    page = pymupdf.open(stream=pdf_bytes, filetype="pdf")[0]
    img = Image.open(io.BytesIO(page.get_pixmap(dpi=150).tobytes("png"))).convert("L")
    img = img.rotate(0.8, expand=True, fillcolor=245).filter(ImageFilter.GaussianBlur(0.6))
    rnd = random.Random(7)
    px = img.load()
    for _ in range(img.width * img.height // 40):
        x, y = rnd.randrange(img.width), rnd.randrange(img.height)
        px[x, y] = max(0, min(255, px[x, y] + rnd.randint(-60, 60)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PDF", resolution=150)
    return buf.getvalue()


def main():
    OUT.mkdir(exist_ok=True)
    for name, key, layout, inv, *extra in SAMPLES:
        v = dict(VENDORS[key])
        if inv.get("gstin"):
            v["gstin"] = inv["gstin"]
        inv.setdefault("rate", 18.0)
        inv["totals"] = totals(inv["lines"], inv["rate"])
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        c.setTitle(f"{v['name']} invoice"); c.setAuthor(v["name"])
        layout(c, v, inv)
        c.showPage(); c.save()
        data = scanify(buf.getvalue()) if "scan" in extra else buf.getvalue()
        (OUT / name).write_bytes(data)
        print(f"{name:52s} total {money(inv['totals'][2]):>14s}")


if __name__ == "__main__":
    main()
