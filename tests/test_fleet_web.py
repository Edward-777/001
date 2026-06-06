"""Fleet approval inbox over HTTP (docs/AGENT-FLEET.md §5)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import service as q
from app.modules.fleet.models import TaskSource, TaskStatus


@pytest.fixture
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as s:
        acct.seed_coa(s)
        auth_svc.create_user(s, name="CEO", email="ceo@x", password="pw", role=Role.ADMIN)
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
    yield TestClient(app, follow_redirects=False), TestSession
    app.dependency_overrides.clear()


def _login(client, email):
    return client.post("/login", data={"email": email, "password": "pw"})


def _seed_invoice(TestSession):
    with TestSession() as s:
        disp.dispatch(s, category="invoice", title="ACME — $1200",
                      source=TaskSource.UPLOAD,
                      payload={"goods_received": True, "parsed": {
                          "vendor_name": "ACME Cloud Inc", "invoice_no": "INV-1",
                          "total": 1200.00}})
        s.commit()


def test_inbox_run_then_approve_posts_bill(ctx):
    client, TestSession = ctx
    _login(client, "ceo@x")
    _seed_invoice(TestSession)

    # queued shows on the inbox, no pending yet
    r = client.get("/fleet")
    assert r.status_code == 200 and "1 대기" in r.text

    # run the loop -> the spend role drafts a bill, parked for approval
    client.post("/fleet/run")
    r = client.get("/fleet")
    assert "ACME Cloud Inc" in r.text and "$1200.00" in r.text

    # approve -> posted
    with TestSession() as s:
        task = q.pending_approvals(s)[0]
        tid = task.id
    client.post(f"/fleet/{tid}/approve")
    with TestSession() as s:
        task = q.get_task(s, tid)
        assert task.status == TaskStatus.DONE
        bill = acct.get_ap_bill(s, task.result["draft_bill_id"])
        assert bill.status == "open"  # posted to the ledger


def test_reject_keeps_bill_draft(ctx):
    client, TestSession = ctx
    _login(client, "ceo@x")
    _seed_invoice(TestSession)
    client.post("/fleet/run")
    with TestSession() as s:
        tid = q.pending_approvals(s)[0].id
    client.post(f"/fleet/{tid}/reject")
    with TestSession() as s:
        task = q.get_task(s, tid)
        assert task.status == TaskStatus.FAILED
        assert acct.get_ap_bill(s, task.result["draft_bill_id"]).status == "draft"


def test_non_finance_user_cannot_approve(ctx):
    client, TestSession = ctx
    _login(client, "staff@x")  # plain employee, no finance L3
    _seed_invoice(TestSession)
    client.post("/fleet/run")
    with TestSession() as s:
        tid = q.pending_approvals(s)[0].id
    client.post(f"/fleet/{tid}/approve")
    with TestSession() as s:
        task = q.get_task(s, tid)
        assert task.status == TaskStatus.NEEDS_APPROVAL  # blocked, still pending
