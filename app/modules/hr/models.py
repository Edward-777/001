"""HR / org chart (SCHEMA §A departments, employees).

`employees.reports_to_id` is the backbone reused for BOTH approval routing (M5)
and the permission gate's team/department data-boundary (DESIGN §8.5 axis ③).
"""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class Department(PKMixin, TimestampMixin, Base):
    __tablename__ = "departments"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True
    )
    # Logical ref to employees (kept plain to avoid a circular FK at create time).
    manager_employee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Employee(PKMixin, TimestampMixin, Base):
    __tablename__ = "employees"

    employee_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id"), nullable=True
    )
    position_title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The reporting line — the spine of approvals + permission boundaries.
    reports_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id"), nullable=True
    )
    hire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EmployeeStatus.ACTIVE
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    manager: Mapped[Employee | None] = relationship(remote_side="Employee.id")
