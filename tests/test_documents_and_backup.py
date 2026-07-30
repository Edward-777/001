"""M14 — documents registry (Default-Deny) + backup with retention."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core import backup
from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
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

def _make_sqlite(path):
    import sqlite3
    with sqlite3.connect(path) as con:
        con.execute("create table t(x int)")
        con.execute("insert into t values (42)")


def test_backup_produces_valid_verified_snapshot(tmp_path):
    src = tmp_path / "dev.db"
    _make_sqlite(src)
    dest = tmp_path / "backups"
    out = backup.run_backup(dest_dir=dest, database_url=f"sqlite:///{src}")
    assert out.exists()
    import sqlite3
    with sqlite3.connect(out) as con:  # backup is a usable sqlite db with the data
        assert con.execute("select x from t").fetchone()[0] == 42


def test_backup_retention_keeps_most_recent_daily(tmp_path):
    src = tmp_path / "dev.db"
    _make_sqlite(src)
    dest = tmp_path / "backups"
    dest.mkdir()
    # pre-seed 5 valid-named old backups across different days
    for i in range(1, 6):
        (dest / f"erp_2026010{i}_000000.db").write_bytes(b"old")
    backup.run_backup(dest_dir=dest, database_url=f"sqlite:///{src}",
                      daily=3, weekly=0, monthly=0)
    remaining = sorted(dest.glob("erp_*.db"))
    assert len(remaining) == 3  # only the 3 most recent kept
