"""mail — outbound email (maker-checker end to end)

Revision ID: f9d3a61c8b24
Revises: e4b8c72f5a19
Create Date: 2026-08-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f9d3a61c8b24"
down_revision: Union[str, None] = "e4b8c72f5a19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbound_emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("to_addr", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="draft"),
        sa.Column("related_type", sa.String(length=30), nullable=True),
        sa.Column("related_id", sa.Integer(), nullable=True),
        sa.Column("reply_to_email_id", sa.Integer(),
                  sa.ForeignKey("inbound_emails.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_ref", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("outbound_emails")
