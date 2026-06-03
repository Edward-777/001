"""documents.service — register, classify, and route uploaded files.

Default-Deny (DESIGN §8.4/§8.6): store_document quarantines and does NOT index;
only an explicit classify() promotes a document and assigns its ACL."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import Document, DocStatus, Relevance


def store_document(
    session: Session,
    *,
    file_path: str,
    filename: str | None = None,
    mime: str | None = None,
    extracted_text: str | None = None,
) -> Document:
    """Register an uploaded file — quarantined, unindexed, most-restrictive ACL."""
    doc = Document(
        file_path=file_path,
        filename=filename,
        mime=mime,
        extracted_text=extracted_text,
        acl_level=3,                       # Default-Deny
        status=str(DocStatus.QUARANTINED),
        is_indexed=False,
    )
    session.add(doc)
    session.flush()
    return doc


def classify(
    session: Session,
    document_id: int,
    *,
    category_id: int | None = None,
    acl_scope: str | None = None,
    acl_level: int = 3,
    subject_employee_id: int | None = None,
    relevance: Relevance = Relevance.BUSINESS,
    classified_by: str = "human",
    confidence: float | None = None,
    linked_type: str | None = None,
    linked_id: int | None = None,
    index_it: bool = True,
) -> Document:
    """Promote a document: assign category/ACL/relevance. Only business-relevant,
    classified documents get indexed into RAG (Phase 3)."""
    doc = session.get(Document, document_id)
    if doc is None:
        raise ValueError("document not found")
    doc.category_id = category_id
    doc.acl_scope = acl_scope
    doc.acl_level = acl_level
    doc.subject_employee_id = subject_employee_id
    doc.relevance = str(relevance)
    doc.classified_by = classified_by
    doc.confidence = confidence
    doc.linked_type = linked_type
    doc.linked_id = linked_id
    if relevance == Relevance.UNCATEGORIZED:
        doc.status = str(DocStatus.QUARANTINED)  # junk stays quarantined, never indexed
        doc.is_indexed = False
    else:
        doc.status = str(DocStatus.CLASSIFIED)
        doc.is_indexed = index_it
    session.flush()
    return doc


def get_document(session: Session, document_id: int) -> Document | None:
    return session.get(Document, document_id)
