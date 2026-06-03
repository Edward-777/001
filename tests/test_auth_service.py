"""auth.service against a real (in-memory) DB session."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import auth  # noqa: F401  registers tables
from app.modules.auth import service
from app.modules.auth.models import DataBoundary, Role, Scope


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_create_and_authenticate(session):
    service.create_user(
        session, name="Admin", email="admin@001.local", password="pw1234", role=Role.ADMIN
    )
    session.flush()
    assert service.authenticate(session, "admin@001.local", "pw1234") is not None
    assert service.authenticate(session, "admin@001.local", "wrong") is None
    assert service.authenticate(session, "nobody@001.local", "pw1234") is None


def test_grant_scope_and_materialize(session):
    u = service.create_user(session, name="HR Lead", email="hr@001.local", password="pw")
    service.grant_scope(session, u, Scope.HR, level=3, data_boundary=DataBoundary.DEPARTMENT)
    session.flush()

    grants = service.get_grants(u)
    assert grants["hr"].level == 3
    assert grants["hr"].data_boundary == DataBoundary.DEPARTMENT
    # gate works end-to-end:
    assert service.can_access(grants, "hr", 3) is True  # non-subject query
    # per-subject with department boundary + no resolver yet -> fail-closed
    assert (
        service.can_access(grants, "hr", 3, subject_employee_id=5, actor_employee_id=5)
        is False
    )


def test_grant_scope_replaces(session):
    u = service.create_user(session, name="U", email="u@001.local", password="pw")
    service.grant_scope(session, u, Scope.FINANCE, level=1)
    service.grant_scope(session, u, Scope.FINANCE, level=3, data_boundary=DataBoundary.ALL)
    session.flush()
    grants = service.get_grants(u)
    assert grants["finance"].level == 3
    assert grants["finance"].data_boundary == DataBoundary.ALL
