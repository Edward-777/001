"""catch-up — tables that shipped without a migration (AI phase 2, fleet, O2C)

The baseline predates the AI conversation store, the fleet work queue, and the
O2C fulfillment wave; dev ran on auto_create_tables so the gap went unnoticed.
tests/test_migrations.py now asserts code/migration parity so this class of
drift cannot recur.

Revision ID: c8f5a3e19d72
Revises: b7e2c94a1f60
Create Date: 2026-07-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8f5a3e19d72"
down_revision: Union[str, None] = "b7e2c94a1f60"
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
    # ---- column drift caught by the parity test -----------------------------
    # journal_lines.party (the vendor/customer on a line) shipped with the
    # per-vendor AP/spend work but never got a migration.
    op.add_column("journal_lines",
                  sa.Column("party", sa.String(length=160), nullable=True))

    # ---- AI conversations (phase 2c) ---------------------------------------
    op.create_table(
        "ai_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summarized_upto_id", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_table(
        "ai_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Integer(),
                  sa.ForeignKey("ai_conversations.id"), nullable=False),
        sa.Column("role", sa.String(length=12), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tools_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("acl_scope", sa.String(length=20), nullable=False,
                  server_default="general"),
        sa.Column("acl_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("subject_employee_id", sa.Integer(), nullable=True),
    )

    # ---- fleet work queue (D6) ----------------------------------------------
    op.create_table(
        "fleet_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("from_role", sa.String(length=16), nullable=False),
        sa.Column("to_role", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False,
                  server_default="queued"),
        sa.Column("bounce_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bounce_reason", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("approval_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True,
                  unique=True),
        *_timestamps(),
    )

    # ---- O2C fulfillment (quote -> shipment) --------------------------------
    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_no", sa.String(length=30), nullable=False, unique=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"),
                  nullable=False),
        sa.Column("quote_date", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False,
                  server_default="draft"),
        sa.Column("customer_po", sa.String(length=60), nullable=True),
        sa.Column("so_id", sa.Integer(), sa.ForeignKey("sales_orders.id"),
                  nullable=True),
        sa.Column("subtotal", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(15, 2), nullable=False,
                  server_default="0"),
        sa.Column("total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_table(
        "quote_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("quote_id", sa.Integer(), sa.ForeignKey("quotes.id"),
                  nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"),
                  nullable=True),
        sa.Column("description", sa.String(length=400), nullable=True),
        sa.Column("qty", sa.Numeric(15, 3), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False,
                  server_default="0"),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
    )
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shipment_no", sa.String(length=30), nullable=False, unique=True),
        sa.Column("so_id", sa.Integer(), sa.ForeignKey("sales_orders.id"),
                  nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"),
                  nullable=False),
        sa.Column("ship_date", sa.Date(), nullable=True),
        sa.Column("carrier", sa.String(length=80), nullable=True),
        sa.Column("tracking_no", sa.String(length=80), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "shipment_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipments.id"),
                  nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"),
                  nullable=True),
        sa.Column("description", sa.String(length=400), nullable=True),
        sa.Column("qty", sa.Numeric(15, 3), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    for table in ("shipment_lines", "shipments", "quote_lines", "quotes",
                  "fleet_tasks", "rag_chunks", "ai_messages", "ai_conversations"):
        op.drop_table(table)
    op.drop_column("journal_lines", "party")
