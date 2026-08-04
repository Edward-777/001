"""payments.models — one row per payment the humans intend to execute."""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base
from ...core.money import Money


class InstructionStatus(StrEnum):
    PREPARED = "prepared"    # instruction packet ready — nothing has moved
    CONFIRMED = "confirmed"  # human executed the transfer; journal posted
    CANCELED = "canceled"


class PaymentInstruction(PKMixin, TimestampMixin, Base):
    __tablename__ = "payment_instructions"

    bill_id: Mapped[int] = mapped_column(ForeignKey("ap_bills.id"), nullable=False)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Money, nullable=False)
    # where/how to pay — snapshotted from the vendor at preparation time
    remit_to: Mapped[str | None] = mapped_column(String(400), nullable=True)
    # what to put on the wire so the vendor can apply it
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    # the evidence chain a human (or auditor) reviews before releasing money:
    # bill/invoice numbers, PO, match status/note, due date
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=str(InstructionStatus.PREPARED))
    prepared_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                     nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                          nullable=True)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # the bank's confirmation number — the human's proof of execution
    payment_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # the payment journal this confirmation posted (loose ref)
    payment_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
