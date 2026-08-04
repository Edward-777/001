"""payments — instructions, not transfers; vendors.remit_to

Revision ID: c9a4e73b2f61
Revises: b6c1d85e3f42
Create Date: 2026-08-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9a4e73b2f61"
down_revision: Union[str, None] = "b6c1d85e3f42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payment_instructions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("bill_id", sa.Integer(), sa.ForeignKey("ap_bills.id"),
                  nullable=False),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"),
                  nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("remit_to", sa.String(length=400), nullable=True),
        sa.Column("reference", sa.String(length=200), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="prepared"),
        sa.Column("prepared_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_date", sa.Date(), nullable=True),
        sa.Column("payment_ref", sa.String(length=120), nullable=True),
        sa.Column("payment_no", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.add_column("vendors",
                  sa.Column("remit_to", sa.String(length=400), nullable=True))


def downgrade() -> None:
    op.drop_column("vendors", "remit_to")
    op.drop_table("payment_instructions")
