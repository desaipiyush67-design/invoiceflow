"""Paths and AI model settings. The business rules themselves live in data/ap_policy.md, in plain English."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SAMPLES = ROOT / "samples"
RUNTIME = Path(os.getenv("INVOICEFLOW_RUNTIME", ROOT / "runtime"))
UPLOADS = RUNTIME / "uploads"
DB_PATH = RUNTIME / "invoiceflow.db"
POLICY_PATH = DATA / "ap_policy.md"

try:  # local development: read the key from .env (never committed)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
VISION_MODEL = os.getenv("INVOICEFLOW_VISION_MODEL", "qwen/qwen3.8-27b")          # reads the invoice image
REASONING_MODEL = os.getenv("INVOICEFLOW_REASONING_MODEL", "openai/gpt-oss-120b")  # reviews against the policy and decides
# Used when the main model hits a usage limit (free Groq accounts: ~8k tokens/minute and ~200k tokens/day per model).
BACKUP_MODEL = os.getenv("INVOICEFLOW_BACKUP_MODEL", "qwen/qwen3.8-27b")

BUYER_NAME = "Northwind Retail Pvt Ltd"
BUYER_GSTIN = "29AAACN1234F1Z5"
