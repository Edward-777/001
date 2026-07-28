"""leave — PTO balances, leave requests, onboarding checklist

Revision ID: d92c4f7b1e03
Revises: c41d7e55a9b2
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d92c4f7b1e03"
down_revision: Union[str, None] = "c41d7e55a9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "pto_balances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"),
                  nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("allowance_days", sa.Numeric(5, 1), nullable=False,
                  server_default="0"),
        sa.Column("carried_over_days", sa.Numeric(5, 1), nullable=False,
                  server_default="0"),
        *_timestamps(),
    )
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"),
                  nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Numeric(5, 1), nullable=False),
        sa.Column("reason", sa.String(length=400), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="pending"),
        sa.Column("approver_employee_id", sa.Integer(),
                  sa.ForeignKey("employees.id"), nullable=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.String(length=400), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "onboarding_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"),
                  nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("doc_category", sa.String(length=40), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"),
                  nullable=True),
        *_timestamps(),
    )


def downgrade() -> None:
    op.drop_table("onboarding_tasks")
    op.drop_table("leave_requests")
    op.drop_table("pto_balances")
