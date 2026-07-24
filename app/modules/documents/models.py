"""Document registry (SCHEMA §K2). The single home for every uploaded file.

M14 is the registry skeleton; the AI classification pipeline (§8.4) + pgvector
RAG chunks (§8.6) arrive in Phase 3. Default-Deny here: a new document is
quarantined and NOT indexed until classified.
"""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ...core.base import PKMixin, TimestampMixin
from ...core.db import Base


class DocStatus(StrEnum):
    QUARANTINED = "quarantined"
    CLASSIFIED = "classified"
    NEEDS_REVIEW = "needs_review"
    ROUTED = "routed"
    REJECTED = "rejected"


class Relevance(StrEnum):
    BUSINESS = "business"
    UNCATEGORIZED = "uncategorized"


class DocumentCategory(PKMixin, TimestampMixin, Base):
    __tablename__ = "document_categories"

    name: Mapped[str] = mapped_column(String(60), nullable=False)  # invoice/statement/payroll...
    default_acl_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    default_acl_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    route_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Document(PKMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("document_categories.id"), nullable=True)
    # ACL (DESIGN §8.5) — Default-Deny: most restrictive until classified.
    acl_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    acl_level: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    subject_employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(String, nullable=True)
    linked_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    linked_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    classified_by: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ai | human
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=DocStatus.QUARANTINED)
    is_indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relevance: Mapped[str | None] = mapped_column(String(14), nullable=True)
