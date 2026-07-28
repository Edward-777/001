"""AI Runtime Map (/map): live wiring diagram whose numbers come from the DB."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.modules import (  # noqa: F401  register all tables
    accounting, ai, approval, assets, auth, bank, documents, expense,
    hr, inventory, learning, notifications, procurement, sales,
)
from app.modules.auth import service as auth_svc
from app.modules.fleet.models import Task, TaskStatus
from app.modules.learning.models import LearnedRule
from app.web.map_routes import runtime_stats


@pytest.fixture
def client():
    from app.main import app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as s:
        auth_svc.create_user(s, name="Emp", email="e@x", password="pw")
        s.add(Task(source="upload", category="invoice", from_role="dispatcher",
                   to_role="spend", title="Acme — $10",
                   status=str(TaskStatus.NEEDS_APPROVAL)))
        s.add(LearnedRule(kind="vendor_alias", params={}, status="active",
                          applied_count=3))
        s.commit()

    def override():
        s = TestSession()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def test_map_requires_login(client):
    r = client.get("/map")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_map_renders_live_wiring(client):
    client.post("/login", data={"email": "e@x", "password": "pw"})
    r = client.get("/map")
    assert r.status_code == 200
    for label in ("AI Runtime Map", "GUARDRAILS", "HUMAN DECIDES",
                  "SYSTEM OF RECORD", "Approval Inbox", "Learned rules",
                  "Maker-checker gate", "Honesty backstop"):
        assert label in r.text
    assert "1 drafts waiting" in r.text          # the seeded fleet task
    assert "1 active · 3 applications" in r.text  # the seeded learned rule
    assert "permission-checked tools" in r.text


def test_runtime_stats_counts():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Task(source="upload", category="invoice", from_role="dispatcher",
                   to_role="spend", title="t", status=str(TaskStatus.DONE)))
        s.add(LearnedRule(kind="vendor_alias", params={}, status="retired",
                          applied_count=5))
        s.flush()
        stats = runtime_stats(s)
    assert stats["fleet_done"] == 1
    assert stats["role_tasks"] == {"spend": 1}
    assert stats["rules_active"] == 0           # retired rule doesn't count
    assert stats["rules_applied"] == 5          # but its applications still show
    assert stats["tools"] > 30                  # the registry is populated
