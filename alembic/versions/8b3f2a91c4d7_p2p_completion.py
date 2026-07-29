"""p2p completion — vendor docs, link-based requests, 3-way match note

Revision ID: 8b3f2a91c4d7
Revises: 5cfd965794f6
Create Date: 2026-07-24

Columns added by the chat-first procure-to-pay completion:
- documents.uploaded_by          (attach-my-last-upload resolution per user)
- request_lines.product_url      (link-based purchase requests)
- request_lines.price_source     ("user" | "url" — where the price came from)
- ap_bills.match_note            (WHY a 3-way match passed or excepted)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8b3f2a91c4d7"
down_revision: Union[str, None] = "5cfd965794f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table: SQLite cannot ALTER in an FK constraint — batch mode
    # rebuilds the table (copy-and-move); on PostgreSQL it degrades to plain ALTERs.
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("uploaded_by", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_documents_uploaded_by_users",
                                 "users", ["uploaded_by"], ["id"])
    op.add_column("request_lines",
                  sa.Column("product_url", sa.String(length=1000), nullable=True))
    op.add_column("request_lines",
                  sa.Column("price_source", sa.String(length=12), nullable=True))
    op.add_column("ap_bills",
                  sa.Column("match_note", sa.String(length=400), nullable=True))


def downgrade() -> None:
    op.drop_column("ap_bills", "match_note")
    op.drop_column("request_lines", "price_source")
    op.drop_column("request_lines", "product_url")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("fk_documents_uploaded_by_users", type_="foreignkey")
        batch.drop_column("uploaded_by")
