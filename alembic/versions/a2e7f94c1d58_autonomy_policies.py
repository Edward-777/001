"""policy — autonomy envelopes + decision trail; vendor autonomy tier

Revision ID: a2e7f94c1d58
Revises: f9d3a61c8b24
Create Date: 2026-08-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2e7f94c1d58"
down_revision: Union[str, None] = "f9d3a61c8b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "autonomy_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("action_scope", sa.String(length=60), nullable=False),
        sa.Column("max_level", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="draft"),
        sa.Column("proposed_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("suspend_reason", sa.String(length=400), nullable=True),
        sa.Column("rejection_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("autonomy_policies.id"),
                  nullable=True),
        sa.Column("action_scope", sa.String(length=60), nullable=False),
        sa.Column("action_ref", sa.String(length=120), nullable=True),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("resolved_level", sa.Integer(), nullable=False,
                  server_default="2"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.add_column("vendors",
                  sa.Column("autonomy_tier", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("vendors", "autonomy_tier")
    op.drop_table("policy_decisions")
    op.drop_table("autonomy_policies")
