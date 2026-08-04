"""mail — inbound email as an intake surface

Revision ID: e4b8c72f5a19
Revises: c8f5a3e19d72
Create Date: 2026-08-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b8c72f5a19"
down_revision: Union[str, None] = "c8f5a3e19d72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inbound_emails",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("from_addr", sa.String(length=255), nullable=False),
        sa.Column("from_name", sa.String(length=255), nullable=True),
        sa.Column("to_addr", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("thread_key", sa.String(length=500), nullable=True),
        sa.Column("vendor_id", sa.Integer(), sa.ForeignKey("vendors.id"),
                  nullable=True),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="received"),
        sa.Column("status_note", sa.String(length=400), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("inbound_emails")
