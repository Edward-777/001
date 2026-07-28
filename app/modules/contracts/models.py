"""contracts.models — one row per standing commitment.

The document itself (the signed PDF) lives in the documents registry; this row
carries the dates and money the company must act on. `notice_days` defines the
alert window before end_date: for auto-renewing contracts that's the last
chance to cancel, for fixed-term ones the time to renegotiate.
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base
from ...core.money import Money


class ContractKind(StrEnum):
    SUBSCRIPTION = "subscription"
    LEASE = "lease"
    INSURANCE = "insurance"
    SERVICE = "service"
    OTHER = "other"


class ContractStatus(StrEnum):
    ACTIVE = "active"
    ENDED = "ended"


class Contract(PKMixin, TimestampMixin, Base):
    __tablename__ = "contracts"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False,
                                      default=str(ContractKind.OTHER))
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notice_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    amount: Mapped[float | None] = mapped_column(Money, nullable=True)
    billing: Mapped[str | None] = mapped_column(String(12), nullable=True)  # monthly|annual|one_time
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=str(ContractStatus.ACTIVE))
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
