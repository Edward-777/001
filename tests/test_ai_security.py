"""AI-layer security fixes from the final review:
  - RAG retrieval enforces the data_boundary (③) axis, not just scope×level.
  - Segregation of Duties: paying a vendor bill needs finance L3 (entry is L2).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import accounting, ai, hr  # noqa: F401  register tables
from app.modules.accounting import service as acct
from app.modules.ai import llm, rag
from app.modules.ai.registry import registry
from app.modules.auth import service as auth
from app.modules.auth.models import DataBoundary, Role, Scope
from app.modules.hr import service as hr_svc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


# ---- RAG data_boundary (③ axis) -----------------------------------------

def test_rag_enforces_boundary_for_per_subject_chunk(session, monkeypatch):
    monkeypatch.setattr(llm, "embed", lambda text, **k: [1.0, 0.0])  # all chunks score 1.0

    admin = auth.create_user(session, name="Admin", email="a@x", password="p", role=Role.ADMIN)
    carol = auth.create_user(session, name="Carol", email="c@x", password="p", role=Role.EMPLOYEE)
    session.flush()
    admin_e = hr_svc.create_employee(session, employee_no="E1", name="Admin", user_id=admin.id)
    alice_e = hr_svc.create_employee(session, employee_no="E2", name="Alice", reports_to_id=admin_e.id)
    carol_e = hr_svc.create_employee(session, employee_no="E3", name="Carol",
                                     reports_to_id=admin_e.id, user_id=carol.id)
    # Carol has HR clearance L3 but only over her TEAM — Alice is a peer, not a report.
    auth.grant_scope(session, carol, Scope.HR, 3, DataBoundary.TEAM)
    session.flush()

    rag.ingest(session, source="alice_review", text="Alice performance review: excellent.",
               acl_scope="hr", acl_level=3, subject_employee_id=alice_e.id)

    # Admin (hr L3, boundary ALL) can retrieve it; Carol (boundary TEAM, not Alice's mgr) cannot.
    assert rag.search(session, "review", user=admin, min_score=0.0)
    assert rag.search(session, "review", user=carol, min_score=0.0) == []
    assert carol_e.id  # (carol is a real employee; she simply isn't over Alice)


def test_rag_general_docs_readable_by_all(session, monkeypatch):
    monkeypatch.setattr(llm, "embed", lambda text, **k: [1.0, 0.0])
    emp = auth.create_user(session, name="Emp", email="e@x", password="p", role=Role.EMPLOYEE)
    session.flush()
    rag.ingest(session, source="policy", text="Travel policy: economy class.", acl_scope="general")
    assert rag.search(session, "travel", user=emp, min_score=0.0)


# ---- Segregation of Duties: pay_vendor needs L3 -------------------------

def test_pay_vendor_denied_at_finance_level_2(session):
    """A user who can ENTER bills (finance L2) must not be able to PAY them."""
    u = auth.create_user(session, name="Clerk", email="k@x", password="p", role=Role.EMPLOYEE)
    auth.grant_scope(session, u, Scope.FINANCE, 2, DataBoundary.ALL)
    session.flush()
    out = registry.execute("pay_vendor", {"bill_no": "BILL-2026-0001", "amount": 10},
                           session=session, user=u)
    assert "permission denied" in out["error"]


def test_pay_vendor_requires_explicit_amount(session):
    admin = auth.create_user(session, name="Admin", email="a@x", password="p", role=Role.ADMIN)
    session.flush()
    out = registry.execute("pay_vendor", {"bill_no": "NOPE"}, session=session, user=admin)
    # admin PASSES the L3 SoD gate (not a permission denial); the handler then runs
    assert "permission denied" not in str(out)
    assert "error" in out.get("result", {})


def test_can_access_subject_helper(session):
    admin = auth.create_user(session, name="Admin", email="a@x", password="p", role=Role.ADMIN)
    session.flush()
    admin_e = hr_svc.create_employee(session, employee_no="E1", name="Admin", user_id=admin.id)
    alice_e = hr_svc.create_employee(session, employee_no="E2", name="Alice", reports_to_id=admin_e.id)
    session.flush()
    # admin (hr L3, ALL) can access Alice's per-subject record
    assert auth.can_access_subject(session, admin, "hr", 3, alice_e.id) is True
