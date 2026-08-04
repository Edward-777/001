"""policy.models — autonomy envelopes and their decision trail.

`policy_decisions` is deliberately audit-shaped: one row per evaluation with a
snapshot of the inputs and the per-condition verdicts. It answers "why was
this allowed?" — and doubles as evidence of automated-control operation for
auditor mode later.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base

# Autonomy ladder (docs: the master design)
#   L0 answer · L1 draft · L2 execute-on-approval (default ceiling)
#   L3 auto-execute inside an approved envelope · L4 standing agent
DEFAULT_LEVEL = 2
BREAKER_THRESHOLD = 3  # review-card rejections that auto-suspend a policy


class PolicyStatus(StrEnum):
    DRAFT = "draft"          # proposed (by human or AI) — grants nothing
    ACTIVE = "active"        # human-activated — grants its max_level
    SUSPENDED = "suspended"  # breaker tripped or human-suspended
    EXPIRED = "expired"


class AutonomyPolicy(PKMixin, TimestampMixin, Base):
    __tablename__ = "autonomy_policies"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # which action family this envelope covers, e.g. "spend.approve_bill"
    action_scope: Mapped[str] = mapped_column(String(60), nullable=False)
    max_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # condition vocabulary (all deterministic; unknown keys FAIL CLOSED):
    #   max_amount: float · daily_cap: float · vendor_allowlisted: true
    #   account_codes: [..] · budget_headroom: true
    conditions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=str(PolicyStatus.DRAFT))
    proposed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"),
                                                    nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                         nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    suspend_reason: Mapped[str | None] = mapped_column(String(400), nullable=True)
    rejection_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PolicyDecision(PKMixin, Base):
    __tablename__ = "policy_decisions"

    policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("autonomy_policies.id"), nullable=True)  # None = nothing matched
    action_scope: Mapped[str] = mapped_column(String(60), nullable=False)
    action_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_level: Mapped[int] = mapped_column(Integer, nullable=False,
                                                default=DEFAULT_LEVEL)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
