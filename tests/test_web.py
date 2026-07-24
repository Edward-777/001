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
from app.modules.auth.models import DataBoundary, Role, Scope
from app.modules.hr import service as hr_svc


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    with TestSession() as s:
        acct.seed_coa(s)
        appr.seed_approval_rules(s)
        # CEO is admin (finance 3 -> sees financials); staff is a plain employee (finance 1).
        ceo = auth_svc.create_user(s, name="CEO", email="ceo@x", password="pw", role=Role.ADMIN)
        staff = auth_svc.create_user(s, name="Staff", email="staff@x", password="pw")
        # A finance-LEVEL-2 user (e.g. AR/AP clerk): must NOT see GL/financials (level 3).
        clerk = auth_svc.create_user(s, name="Clerk", email="clerk@x", password="pw")
        auth_svc.grant_scope(s, clerk, Scope.FINANCE, 2, DataBoundary.ALL)
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


def test_financials_visible_to_finance_role(client):
    _login(client, "ceo@x")  # admin -> has finance scope
    r = client.get("/reports/financials?period=2026-01")
    assert r.status_code == 200
    assert "Income Statement" in r.text and "Balance Sheet" in r.text


def test_financials_denied_to_employee(client):
    """The permission gate is wired at the door: an employee cannot view GL (P0-1)."""
    _login(client, "staff@x")  # employee -> no finance scope
    r = client.get("/reports/financials?period=2026-01")
    assert r.status_code == 403


def test_financials_requires_level_3_not_2(client):
    """DESIGN §8.5: financials/ledger = finance level 3. A finance-level-2 user
    (AP/AR clerk) must be denied — the gate enforces the spec'd level, not just >=1."""
    _login(client, "clerk@x")  # finance level 2
    assert client.get("/reports/financials?period=2026-01").status_code == 403


def test_assistant_page_renders(client):
    _login(client, "staff@x")
    r = client.get("/assistant")
    assert r.status_code == 200 and "Assistant" in r.text


def test_assistant_message_renders_turn(client, monkeypatch):
    """POST a chat message; the agent is mocked so no Ollama is needed in CI."""
    from app.modules.ai import agent
    monkeypatch.setattr(agent, "run", lambda session, user, message, **kw: {
        "reply": "You have 7 W1 widgets.", "tool_calls": [{"tool": "get_stock"}]})
    _login(client, "staff@x")
    r = client.post("/assistant/message", data={"message": "how many W1?"})
    assert r.status_code == 200
    assert "how many W1?" in r.text          # user bubble
    assert "You have 7 W1 widgets." in r.text  # assistant reply
    assert "get_stock" in r.text             # tool chip


def test_assistant_handles_llm_outage_gracefully(client, monkeypatch):
    """If Ollama is down, the chat turn degrades to a friendly message, never a
    500 (F8)."""
    from app.modules.ai import agent

    def _boom(*a, **k):
        raise ConnectionError("ollama refused")

    monkeypatch.setattr(agent, "run", _boom)
    _login(client, "staff@x")
    r = client.post("/assistant/message", data={"message": "hello?"})
    assert r.status_code == 200
    assert "unavailable" in r.text.lower()


def test_health_still_ok(client):
    assert client.get("/health").json()["status"] == "ok"


def test_report_export_is_permission_gated(client):
    """The download route is the bypass-proof gate for report files (F5). A
    non-finance user is refused; an unknown kind is 404; finance gets the file."""
    _login(client, "staff@x")  # plain employee, no finance
    assert client.get("/reports/export?kind=financials").status_code == 403
    assert client.get("/reports/export?kind=trial_balance").status_code == 403
    assert client.get("/reports/export?kind=does-not-exist").status_code == 404

    _login(client, "ceo@x")  # admin (finance L3)
    r = client.get("/reports/export?kind=financials")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")


def test_linkify_makes_report_link_downloadable():
    """A report URL in assistant text becomes a clickable download link, so the
    user can grab the .xlsx even after a reload (when the green button is gone)."""
    from app.web.deps import _linkify

    # markdown form the model writes
    html = str(_linkify(
        "FS: [/reports/export?kind=closing_package&period=2025]"
        "(/reports/export?kind=closing_package&period=2025)"))
    assert '<a href="/reports/export?kind=closing_package&amp;period=2025"' in html
    assert "download" in html and "Download report" in html
    # bare URL form is linkified too
    assert "<a href=" in str(_linkify("get /reports/export?kind=financials&period=2025"))


def test_linkify_escapes_untrusted_llm_html():
    """LLM output is escaped first — no raw <script> survives (XSS guard)."""
    from app.web.deps import _linkify

    html = str(_linkify("<script>alert(1)</script>"))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_upload_dest_is_confined_to_uploads_dir():
    """Path-traversal / absolute filenames must never escape the uploads dir, and
    disallowed extensions are rejected before anything is written to disk (F-crit:
    /assistant/upload used the client filename verbatim -> arbitrary file write)."""
    from app.web.ai_routes import _UPLOAD_DIR, _safe_upload_dest

    base = _UPLOAD_DIR.resolve()
    # traversal/absolute names with a disallowed extension are rejected outright
    for name in ["..\..\dev.db", "../../dev.db", "C:\Windows\System32\evil.dll", "x.exe"]:
        with pytest.raises(ValueError):
            _safe_upload_dest(name)
    # a traversal name with an ALLOWED extension is confined + server-renamed
    dest = _safe_upload_dest("..\..\..\etc\payload.pdf")
    assert dest.parent == base                     # stays inside uploads/
    assert dest.suffix == ".pdf"
    assert dest.name != "payload.pdf"              # generated name -> cannot clobber
    assert dest.resolve().is_relative_to(base)
