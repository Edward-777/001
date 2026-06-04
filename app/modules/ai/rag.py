"""Minimal local RAG (Phase 3 starter): chunk a document, embed each chunk with
bge-m3 (Ollama), store it, and retrieve by cosine similarity — permission-filtered.

Dev uses SQLite, so embeddings are stored as JSON and scored in Python. In
production this moves to pgvector (documents.document_chunks), but the retrieval
contract — and the permission gate (DESIGN §8.3 'filter before retrieval') — is
identical: a chunk is only returned if the asking user may read its ACL scope.
"""
from __future__ import annotations

import json
import math

from sqlalchemy import String, Text, delete, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session

from ...core.base import PKMixin
from ...core.db import Base
from ..auth import service as auth
from ..auth.models import User
from . import llm


class RagChunk(PKMixin, Base):
    __tablename__ = "rag_chunks"

    source: Mapped[str] = mapped_column(String(200), nullable=False)  # document name
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list[float]
    acl_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="general")
    acl_level: Mapped[int] = mapped_column(nullable=False, default=1)


def _chunk_text(text: str, *, size: int = 900, overlap: int = 150) -> list[str]:
    """Paragraph-aware chunks of ~`size` chars with a little overlap for continuity."""
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if len(cur) + len(p) + 1 <= size:
            cur = f"{cur}\n{p}".strip()
        else:
            if cur:
                chunks.append(cur)
            cur = (cur[-overlap:] + "\n" + p).strip() if cur and len(p) < size else p
    if cur:
        chunks.append(cur)
    return chunks


def ingest(session: Session, *, source: str, text: str,
           acl_scope: str = "general", acl_level: int = 1, replace: bool = True) -> int:
    """Embed and store a document's chunks. Returns the chunk count."""
    if replace:
        session.execute(delete(RagChunk).where(RagChunk.source == source))
    chunks = _chunk_text(text)
    for i, c in enumerate(chunks):
        session.add(RagChunk(
            source=source, chunk_index=i, content=c,
            embedding=json.dumps(llm.embed(c)), acl_scope=acl_scope, acl_level=acl_level,
        ))
    session.flush()
    return len(chunks)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _readable(chunk: RagChunk, grants) -> bool:
    if chunk.acl_scope == "general":
        return True
    return auth.can_access(grants, chunk.acl_scope, chunk.acl_level)


def search(session: Session, query: str, *, user: User, top_k: int = 4,
           min_score: float = 0.3) -> list[dict]:
    """Return the top-k readable chunks most similar to the query (the §8.3
    retrieval gate: chunks the user can't read are never even scored in)."""
    qv = llm.embed(query)
    grants = auth.get_grants(user)
    scored: list[tuple[float, RagChunk]] = []
    for r in session.scalars(select(RagChunk)).all():
        if not _readable(r, grants):
            continue
        scored.append((_cosine(qv, json.loads(r.embedding)), r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [
        {"source": r.source, "content": r.content, "score": round(s, 3)}
        for s, r in scored[:top_k] if s >= min_score
    ]
