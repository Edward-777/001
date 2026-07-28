"""leave.models — PTO balances, leave requests, onboarding checklist.

Balances store what was GRANTED (allowance + carryover); what was USED is
always computed from approved leave_requests, so the two can never drift.
A leave request routes to the requester's immediate manager via the same
reports_to spine the spend approvals use.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class LeaveKind(StrEnum):
    VACATION = "vacation"   # draws down the PTO balance
    SICK = "sick"           # tracked, not balance-checked
    UNPAID = "unpaid"       # tracked, not balance-checked


class LeaveStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELED = "canceled"


class PtoBalance(PKMixin, TimestampMixin, Base):
    """Days GRANTED to an employee for one calendar year."""
    __tablename__ = "pto_balances"

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    allowance_days: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    carried_over_days: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False, default=0)


class LeaveRequest(PKMixin, TimestampMixin, Base):
    __tablename__ = "leave_requests"

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Business days, computed at request time (weekends excluded).
    days: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=str(LeaveStatus.PENDING))
    # The immediate manager at request time (None = no manager -> auto-approved).
    approver_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(String(400), nullable=True)


# Default checklist for a new hire (US small-company basics). doc_category maps
# a task to the document the employee must hand in, if any.
DEFAULT_ONBOARDING = [
    ("Signed offer letter", "offer_letter"),
    ("Form I-9 (employment eligibility)", "i9"),
    ("Form W-4 (federal withholding)", "w4"),
    ("Direct deposit authorization", "direct_deposit"),
    ("Employee handbook acknowledgment", "handbook_ack"),
]


class OnboardingTask(PKMixin, TimestampMixin, Base):
    __tablename__ = "onboarding_tasks"

    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                     nullable=True)
    # The collected document, when the task is document-backed.
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"),
                                                    nullable=True)
