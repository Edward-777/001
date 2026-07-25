"""learned_rules — governed learning loop (ADR-10)

Revision ID: c41d7e55a9b2
Revises: 8b3f2a91c4d7
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c41d7e55a9b2"
down_revision: Union[str, None] = "8b3f2a91c4d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "learned_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.String(length=400), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="active"),
        sa.Column("applied_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    # user_memories shipped alongside (agent memory) — same wave
    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("fact", sa.String(length=400), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="stated"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_memories")
    op.drop_table("learned_rules")
