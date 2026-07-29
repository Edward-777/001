"""Auth/permission models (SCHEMA §A users, user_scopes; DESIGN §8.5 3-axis).

PRIVATE to the auth module — other modules go through auth.service.
"""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class Role(StrEnum):
    """Coarse role = default scope bundle (POLICIES §G11). Fine control = UserScope."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    ACCOUNTANT = "accountant"
    ADMIN = "admin"


class Scope(StrEnum):
    """Permission domain — axis ① (DESIGN §8.5)."""

    HR = "hr"
    FINANCE = "finance"
    INVENTORY = "inventory"
    PROCUREMENT = "procurement"
    SALES = "sales"
    SYSTEM = "system"


class DataBoundary(StrEnum):
    """Whose records — axis ③. team/department resolved via org chart (reports_to)."""

    SELF = "self"
    TEAM = "team"
    DEPARTMENT = "department"
    ALL = "all"


class User(PKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.EMPLOYEE)
    # FK→departments added in M2 (HR module). Kept as plain int until then.
    department_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    scopes: Mapped[list[UserScope]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserScope(PKMixin, Base):
    """One (scope, level, data_boundary) grant for a user — axis ①②③."""

    __tablename__ = "user_scopes"
    __table_args__ = (UniqueConstraint("user_id", "scope", name="uq_user_scope"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 1..3
    data_boundary: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DataBoundary.SELF
    )

    user: Mapped[User] = relationship(back_populates="scopes")
