"""Business settings. These are the knobs an AP manager would tune; every rule reads them from here."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SAMPLES = ROOT / "samples"
RUNTIME = Path(os.getenv("INVOICEFLOW_RUNTIME", ROOT / "runtime"))
UPLOADS = RUNTIME / "uploads"
DB_PATH = RUNTIME / "invoiceflow.db"

BUYER_NAME = "Northwind Retail Pvt Ltd"
BUYER_GSTIN = "29AAACN1234F1Z5"
BUYER_STATE_CODE = "29"  # Karnataka: same-state vendors charge CGST+SGST, others IGST

GST_RATE = 18.0
# Over-billing against a PO is accepted up to BOTH limits (rounding, small freight); above either -> hold.
TOLERANCE_PCT = 2.0
TOLERANCE_ABS = 5000.0
# Unit price may drift this much from the PO price before we flag it.
UNIT_PRICE_TOLERANCE_PCT = 2.0
ARITHMETIC_TOLERANCE = 1.0          # rupees; invoices round to the nearest rupee
MAX_INVOICE_AGE_DAYS = 180
# Near-duplicate: same vendor, same total, dates this close -> hold for review.
NEAR_DUPLICATE_DAYS = 10
# Inferring a PO when none is printed: below this score we don't suggest one at all.
PO_INFERENCE_MIN_SCORE = 0.6
