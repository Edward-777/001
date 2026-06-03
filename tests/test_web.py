"""M15 — the web UI end to end (login, request, approval, notifications)
through the real FastAPI app with an in-memory DB."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.approval import service as appr
from app.modules.auth import service as auth_svc
from app.modules.hr import service as hr_svc


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    with TestSession() as s:
        acct.seed_coa(s)
        appr.seed_approval_rules(s)
        ceo = auth_svc.create_user(s, name="CEO", email="ceo@x", password="pw")
        staff = auth_svc.create_user(s, name="Staff", email="staff@x", password="pw")
        s.flush()
        ce = hr_svc.create_employee(s, employee_no="E1", name="CEO", user_id=ceo.id)
        hr_svc.create_employee(s, employee_no="E2", name="Staff", reports_to_id=ce.id, user_id=staff.id)
        s.commit()

    def override():
        s = TestSession()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "pw"})


def test_dashboard_requires_login(client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_bad_login_rejected(client):
    r = client.post("/login", data={"email": "staff@x", "password": "wrong"})
    assert r.status_code == 401


def test_login_and_dashboard(client):
    assert _login(client, "staff@x").status_code == 303
    r = client.get("/")
    assert r.status_code == 200
    assert "Dashboard" in r.text


def test_create_request_and_see_it_listed(client):
    _login(client, "staff@x")
    r = client.post("/requests", data={"title": "Buy widgets", "type": "purchase",
                                       "description": "widgets", "qty": "2", "unit_price": "50"})
    assert r.status_code == 303
    page = client.get("/requests")
    assert "Buy widgets" in page.text
    assert "submitted" in page.text  # awaiting approval


def test_approver_sees_and_approves(client):
    # staff submits
    _login(client, "staff@x")
    client.post("/requests", data={"title": "Need a server", "type": "purchase",
                                   "description": "server", "qty": "1", "unit_price": "100"})
    # ceo (the approver) logs in and approves
    _login(client, "ceo@x")
    inbox = client.get("/approvals")
    assert "Need a server" in inbox.text
    # find the request id from the approve form
    import re
    m = re.search(r"/approvals/(\d+)/approve", inbox.text)
    assert m
    r = client.post(f"/approvals/{m.group(1)}/approve")
    assert r.status_code == 303
    # now nothing pending
    assert "Need a server" not in client.get("/approvals").text


def test_notifications_visible_to_approver(client):
    _login(client, "staff@x")
    client.post("/requests", data={"title": "Lunch run", "type": "purchase",
                                   "description": "lunch", "qty": "1", "unit_price": "20"})
    _login(client, "ceo@x")
    notes = client.get("/notifications")
    assert "Approval needed" in notes.text


def test_financials_page(client):
    _login(client, "staff@x")
    r = client.get("/reports/financials?period=2026-01")
    assert r.status_code == 200
    assert "Income Statement" in r.text and "Balance Sheet" in r.text


def test_health_still_ok(client):
    assert client.get("/health").json()["status"] == "ok"
