"""Authorization sweep over the web layer (DESIGN §8.5).

Every state-changing or data-revealing route must name its scope gate; a plain
employee (hr/finance L1 self) gets an explicit 403 — never a silent success.
This is the regression net for the review finding that O2C routes were
login-gated only (a staff user could accept quotes and ship stock).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app
from app.modules import (  # noqa: F401  register all tables
    accounting, ai, approval, assets, auth, bank, budget, contracts, documents,
    expense, fleet, hr, inventory, leave, learning, notifications, procurement,
    sales,
)
from app.modules.accounting import service as acct
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as s:
        acct.seed_coa(s)
        auth_svc.create_user(s, name="Admin", email="admin@x", password="pw",
                             role=Role.ADMIN)
        auth_svc.create_user(s, name="Staff", email="staff@x", password="pw")
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
    assert client.post("/login", data={"email": email, "password": "pw"}).status_code == 303


# (method, path, form) — routes a plain employee must NOT be able to reach.
GATED = [
    # O2C: the review finding — these were login-only before
    ("GET", "/sales", None),
    ("POST", "/sales/quote", {"customer": "Acme", "desc1": "x", "qty1": 1, "price1": 5}),
    ("POST", "/sales/quote/1/send", {}),
    ("POST", "/sales/quote/1/accept", {"customer_po": "PO-1"}),
    ("POST", "/sales/order/1/ship", {}),
    ("POST", "/sales/order/1/invoice", {}),
    ("GET", "/sales/quote/1/document", None),
    ("GET", "/sales/shipment/1/document", None),
    ("GET", "/sales/invoice/1/document", None),
    # already-gated routes, kept here as the regression net
    ("POST", "/fleet/run", {}),
    ("POST", "/fleet/1/approve", {}),
    ("POST", "/fleet/1/reject", {}),
    ("GET", "/reports/financials", None),
    ("GET", "/reports/export?kind=general_ledger", None),
    ("GET", "/po/1/document", None),
    ("GET", "/contracts", None),
    ("POST", "/contracts/add", {"title": "t", "counterparty": "c"}),
    ("POST", "/contracts/1/end", {}),
    ("GET", "/budget", None),
    ("POST", "/budget/set", {"account_code": "6100", "monthly_amount": 1}),
]


@pytest.mark.parametrize("method,path,form", GATED,
                         ids=[f"{m} {p}" for m, p, _ in GATED])
def test_plain_employee_is_denied(client, method, path, form):
    _login(client, "staff@x")
    r = (client.get(path) if method == "GET"
         else client.post(path, data=form or {}))
    assert r.status_code == 403, f"{method} {path} -> {r.status_code} (expected 403)"


def test_denials_require_login_first(client):
    # logged out -> redirected to /login, not 403 (auth before authz)
    r = client.get("/sales")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_admin_runs_the_o2c_flow_the_staffer_could_not(client):
    _login(client, "admin@x")
    assert client.get("/sales").status_code == 200
    assert client.post("/sales/quote", data={
        "customer": "Acme Co", "desc1": "Widget", "qty1": 2, "price1": 10,
    }).status_code == 303
    assert client.post("/sales/quote/1/send", data={}).status_code == 303
    assert client.post("/sales/quote/1/accept",
                       data={"customer_po": "PO-77"}).status_code == 303
    # the accepted quote created SO 1; invoicing it posts revenue (finance L3)
    assert client.post("/sales/order/1/invoice", data={}).status_code == 303
