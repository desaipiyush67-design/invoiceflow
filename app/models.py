"""Data shapes shared by every stage of the pipeline."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class InvoiceFields(BaseModel):
    """What we pull out of an invoice. Anything not printed on the invoice stays None (never guessed)."""
    vendor_name: Optional[str] = None
    vendor_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD")
    po_reference: Optional[str] = Field(None, description="Purchase order number exactly as printed, e.g. PO-4501")
    currency: Optional[str] = "INR"
    line_items: list[LineItem] = []
    subtotal: Optional[float] = Field(None, description="Total before tax")
    tax_amount: Optional[float] = Field(None, description="Sum of all GST components (CGST+SGST or IGST)")
    total: Optional[float] = Field(None, description="Grand total payable")
    bank_account_last4: Optional[str] = None


Status = Literal["pass", "warn", "fail", "info"]
Severity = Literal["none", "review", "block"]


class Check(BaseModel):
    """One rule result. severity says what it does to the decision: block -> reject, review -> hold."""
    id: str
    group: str
    title: str
    status: Status
    severity: Severity = "none"
    detail: str


DecisionType = Literal["APPROVE", "HOLD", "REJECT"]


class Decision(BaseModel):
    decision: DecisionType
    headline: str
    reasons: list[str]
    next_action: str
    owner: str
    vendor_email: Optional[str] = None
    explanation: str = ""
