"""Sales/AR domain events — accounting books revenue and cash (ARCHITECTURE §3)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ...core.events import Event


@dataclass
class ARInvoicePosted(Event):
    invoice_id: int
    entry_date: date
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal


@dataclass
class ReceiptPosted(Event):
    receipt_id: int
    entry_date: date
    amount: Decimal
