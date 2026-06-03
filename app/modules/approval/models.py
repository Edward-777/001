"""Approval workflow (SCHEMA §B requests, request_lines, approval_lines, approval_rules).

Routing is org-chart based by default: on submit, the approval line is built by
climbing the requester's reports_to chain (DESIGN — org-chart routing).
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

Money = Numeric(15, 2)


class RequestType(StrEnum):
    PURCHASE = "purchase"
    EXPENSE = "expense"
    TRIP = "trip"
    GENERAL = "general"


class RequestStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELED = "canceled"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class Routing(StrEnum):
    ORG_CHART = "org_chart"
    FIXED_ROLE = "fixed_role"
    FIXED_EMPLOYEE = "fixed_employee"


class Request(PKMixin, TimestampMixin, Base):
    __tablename__ = "requests"

    request_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    total_amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=RequestStatus.DRAFT)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RequestLine(PKMixin, Base):
    __tablename__ = "request_lines"

    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(String(400), nullable=True)
    qty: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False, default=1)
    estimated_unit_price: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)


class ApprovalLine(PKMixin, Base):
    __tablename__ = "approval_lines"

    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), nullable=False)
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=ApprovalStatus.PENDING)
    comment: Mapped[str | None] = mapped_column(String(400), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalRule(PKMixin, Base):
    __tablename__ = "approval_rules"

    applies_to_type: Mapped[str] = mapped_column(String(20), nullable=False)
    min_amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    max_amount: Mapped[float | None] = mapped_column(Money, nullable=True)  # None = unbounded
    routing: Mapped[str] = mapped_column(String(20), nullable=False, default=Routing.ORG_CHART)
    climb_levels: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fixed_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fixed_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
