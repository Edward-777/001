"""Sales master: customers (SCHEMA §I, mirror of vendors). SO/AR come in M9."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class Customer(PKMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(400), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payment_terms: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ar_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
