"""Deploy completeness: a fresh database must be installable from migrations
alone, and the migration chain must stay in lockstep with the models.

Runs `alembic upgrade head` against an EMPTY database (SQLite here; CI also
runs it against PostgreSQL via DATABASE_URL) and asserts:
- the chain applies end to end (no dialect-specific breakage),
- every table the code defines exists, with every column the code defines,
- the migrated schema actually boots the app (login + a page render).
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.db import Base
from app.modules import (  # noqa: F401  register every model on Base.metadata
    accounting, ai, approval, assets, auth, bank, budget, contracts, documents,
    expense, fleet, hr, inventory, leave, learning, notifications, procurement,
    sales,
)

# CI can point this at a postgres service; locally we use a temp sqlite file.
_URL = os.environ.get("MIGRATION_TEST_URL")


@pytest.fixture(scope="module")
def migrated_url():
    if _URL:
        url = _URL
    else:
        path = os.path.join(tempfile.gettempdir(),
                            f"mig_test_{uuid.uuid4().hex}.db")
        url = f"sqlite:///{path}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    # env.py prefers settings.database_url — make them agree for this run,
    # then restore so the rest of the suite is untouched.
    from app.core.config import settings
    old = settings.database_url
    settings.database_url = url
    try:
        command.upgrade(cfg, "head")
        yield url
    finally:
        settings.database_url = old


def test_upgrade_head_applies_on_an_empty_database(migrated_url):
    insp = inspect(create_engine(migrated_url, poolclass=NullPool))
    assert "alembic_version" in insp.get_table_names()


def test_every_model_table_and_column_is_migrated(migrated_url):
    insp = inspect(create_engine(migrated_url, poolclass=NullPool))
    db_tables = set(insp.get_table_names()) - {"alembic_version"}
    code_tables = set(Base.metadata.tables)

    missing = code_tables - db_tables
    assert not missing, f"tables defined in code but absent from migrations: {sorted(missing)}"
    extra = db_tables - code_tables
    assert not extra, f"tables created by migrations but unknown to the code: {sorted(extra)}"

    drift: list[str] = []
    for name, table in Base.metadata.tables.items():
        db_cols = {c["name"] for c in insp.get_columns(name)}
        code_cols = {c.name for c in table.columns}
        if code_cols - db_cols:
            drift.append(f"{name}: missing columns {sorted(code_cols - db_cols)}")
        if db_cols - code_cols:
            drift.append(f"{name}: extra columns {sorted(db_cols - code_cols)}")
    assert not drift, "column drift between models and migrations:\n" + "\n".join(drift)


def test_migrated_schema_boots_the_app(migrated_url):
    """Smoke: seed the COA + a user on the MIGRATED schema, log in, render a page."""
    from fastapi.testclient import TestClient

    from app.core.db import get_session
    from app.main import app
    from app.modules.accounting import service as acct
    from app.modules.auth import service as auth_svc
    from app.modules.auth.models import Role

    engine = create_engine(migrated_url, poolclass=NullPool)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as s:
        acct.seed_coa(s)
        auth_svc.create_user(s, name="Smoke", email="smoke@x", password="pw",
                             role=Role.ADMIN)
        s.commit()

    def override():
        s = TestSession()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    try:
        client = TestClient(app, follow_redirects=False)
        assert client.post("/login", data={"email": "smoke@x",
                                           "password": "pw"}).status_code == 303
        assert client.get("/").status_code == 200
        assert client.get("/map").status_code == 200  # touches most subsystems
    finally:
        app.dependency_overrides.clear()
