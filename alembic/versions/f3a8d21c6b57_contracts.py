"""contracts — the commitments register (renewal tracking)

Revision ID: f3a8d21c6b57
Revises: d92c4f7b1e03
Create Date: 2026-07-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a8d21c6b57"
down_revision: Union[str, None] = "d92c4f7b1e03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("counterparty", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False,
                  server_default="other"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("auto_renew", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("notice_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("billing", sa.String(length=12), nullable=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"),
                  nullable=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id"),
                  nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="active"),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("contracts")
