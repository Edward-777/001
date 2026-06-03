"""Procurement master: vendors (SCHEMA §A vendors). PO comes in M6."""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class PaymentTerms(StrEnum):
    DUE_ON_RECEIPT = "due_on_receipt"
    NET15 = "net15"
    NET30 = "net30"
    NET60 = "net60"


class Vendor(PKMixin, TimestampMixin, Base):
    __tablename__ = "vendors"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(40), nullable=True)  # US EIN (1099)
    is_1099: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    payment_terms: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentTerms.NET30
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
