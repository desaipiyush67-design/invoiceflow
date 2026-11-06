"""Data shapes shared by every stage. The AI's replies are validated against these."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class InvoiceFields(BaseModel):
    """What the AI reads off the invoice. Anything not printed on the invoice stays null (never guessed)."""
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD")
    po_reference: Optional[str] = None
    currency: Optional[str] = "INR"
    line_items: list[LineItem] = []
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total: Optional[float] = None
    bank_account_last4: Optional[str] = None


class Check(BaseModel):
    """One finding. severity says what it does to the decision: block -> reject, review -> hold."""
    id: str
    group: str = ""
    title: str
    status: Literal["pass", "warn", "fail", "info"]
    severity: Literal["none", "review", "block"] = "none"
    detail: str


class Decision(BaseModel):
    decision: Literal["APPROVE", "HOLD", "REJECT"]
    headline: str
    reasons: list[str]
    next_action: str
    owner: str
    vendor_email: Optional[str] = None
    explanation: str = ""


class Review(Decision):
    """The reviewer's single reply: what it matched, every finding, and the decision."""
    vendor_id: Optional[str] = None
    po_number: Optional[str] = None
    checks: list[Check]
