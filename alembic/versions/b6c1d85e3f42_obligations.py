"""obligations — the compliance calendar

Revision ID: b6c1d85e3f42
Revises: a2e7f94c1d58
Create Date: 2026-08-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6c1d85e3f42"
down_revision: Union[str, None] = "a2e7f94c1d58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "obligations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=12), nullable=False,
                  server_default="other"),
        sa.Column("jurisdiction", sa.String(length=60), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("recurrence", sa.String(length=12), nullable=False,
                  server_default="none"),
        sa.Column("notice_days", sa.Integer(), nullable=False,
                  server_default="30"),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="open"),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="manual"),
        sa.Column("linked_type", sa.String(length=30), nullable=True),
        sa.Column("linked_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("obligations")
