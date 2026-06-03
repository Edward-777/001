"""M14 — documents registry (Default-Deny) + backup with retention."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import backup
from app.core.db import Base
from app.modules import documents  # noqa: F401  register tables
from app.modules.documents import service as docs
from app.modules.documents.models import DocStatus, Relevance


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# ---- documents ---------------------------------------------------------

def test_stored_document_is_quarantined_and_unindexed(session):
    d = docs.store_document(session, file_path="/up/inv.pdf", filename="inv.pdf", mime="application/pdf")
    assert d.status == DocStatus.QUARANTINED
    assert d.is_indexed is False
    assert d.acl_level == 3  # Default-Deny: most restrictive


def test_classify_promotes_and_indexes(session):
    d = docs.store_document(session, file_path="/up/inv.pdf")
    docs.classify(session, d.id, acl_scope="finance", acl_level=2, relevance=Relevance.BUSINESS,
                  classified_by="ai", confidence=0.95)
    assert d.status == DocStatus.CLASSIFIED
    assert d.is_indexed is True
    assert d.acl_scope == "finance"


def test_uncategorized_stays_quarantined_never_indexed(session):
    d = docs.store_document(session, file_path="/up/meme.jpg")
    docs.classify(session, d.id, relevance=Relevance.UNCATEGORIZED)
    assert d.status == DocStatus.QUARANTINED
    assert d.is_indexed is False  # junk structurally barred from RAG


# ---- backup ------------------------------------------------------------

def test_backup_copies_sqlite_file(tmp_path):
    src = tmp_path / "dev.db"
    src.write_bytes(b"SQLite format 3\x00fake")
    dest = tmp_path / "backups"
    out = backup.run_backup(dest_dir=dest, database_url=f"sqlite:///{src}", keep=7)
    assert out.exists()
    assert out.read_bytes() == src.read_bytes()


def test_backup_retention_prunes_old(tmp_path):
    src = tmp_path / "dev.db"
    src.write_bytes(b"x")
    dest = tmp_path / "backups"
    # pre-seed 5 fake old backups
    dest.mkdir()
    for i in range(5):
        (dest / f"erp_2026010{i}_000000.db").write_bytes(b"old")
    backup.run_backup(dest_dir=dest, database_url=f"sqlite:///{src}", keep=3)
    remaining = sorted(dest.glob("erp_*"))
    assert len(remaining) == 3  # pruned to keep=3
