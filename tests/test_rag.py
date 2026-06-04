"""RAG retrieval + the permission gate on retrieval (DESIGN §8.3 — a chunk the
user can't read is never returned). Embeddings are faked for determinism."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai  # noqa: F401  register rag_chunks
from app.modules.ai import llm, rag
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role


def _fake_embed(text, **kw):
    t = text.lower()
    # 3-dim keyword vector: [travel, laptop, salary]
    return [1.0 if "travel" in t or "per diem" in t else 0.0,
            1.0 if "laptop" in t else 0.0,
            1.0 if "salary" in t or "comp" in t else 0.0]


@pytest.fixture(autouse=True)
def _patch_embed(monkeypatch):
    monkeypatch.setattr(llm, "embed", _fake_embed)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def user(session):
    return auth_svc.create_user(session, name="U", email="u@x", password="pw")


def test_ingest_and_retrieve_relevant_chunk(session, user):
    rag.ingest(session, source="Policy", text="Travel per diem rules and limits")
    rag.ingest(session, source="Policy", text="Laptop purchase guidelines", replace=False)
    hits = rag.search(session, "what is the travel per diem?", user=user)
    assert hits and "Travel per diem" in hits[0]["content"]


def test_general_docs_readable_by_all(session, user):
    rag.ingest(session, source="Policy", text="Travel per diem rules", acl_scope="general")
    assert rag.search(session, "travel per diem", user=user)  # employee can read company policy


def test_retrieval_gate_blocks_unreadable_scope(session):
    employee = auth_svc.create_user(session, name="E", email="e@x", password="pw")
    admin = auth_svc.create_user(session, name="A", email="a@x", password="pw", role=Role.ADMIN)
    # an HR-confidential chunk (scope hr, level 3 — salaries)
    rag.ingest(session, source="HR", text="salary comp bands", acl_scope="hr", acl_level=3)

    assert rag.search(session, "salary comp", user=employee) == []   # filtered out, not in context
    assert rag.search(session, "salary comp", user=admin)            # admin may read hr
