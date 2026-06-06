"""Monthly close proposal -> approve locks the period (docs/AGENT-FLEET.md §4)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.accounting.posting import PostingError
from app.modules.fleet import month_close, roles
from app.modules.fleet.models import Role, TaskStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


def _expense(session, d, amount):
    dr = acct.get_account_by_code(session, "6100")
    cr = acct.get_account_by_code(session, "1000")
    acct.post_journal(session, entry_date=d,
                      lines=[acct.Line(dr.id, debit=amount), acct.Line(cr.id, credit=amount)],
                      description="rent")


def test_close_proposed_for_prior_month(session):
    _expense(session, date(2026, 5, 10), 3000)
    task = month_close.enqueue_month_close(session, as_of=date(2026, 6, 1))
    assert task.to_role == Role.ACCOUNTING
    assert task.status == TaskStatus.NEEDS_APPROVAL
    assert task.result["period"] == "2026-05"


def test_empty_month_skipped(session):
    assert month_close.enqueue_month_close(session, as_of=date(2026, 6, 1)) is None


def test_idempotent_per_period(session):
    _expense(session, date(2026, 5, 10), 3000)
    a = month_close.enqueue_month_close(session, as_of=date(2026, 6, 1))
    b = month_close.enqueue_month_close(session, as_of=date(2026, 6, 2))
    assert a.id == b.id


def test_approve_locks_the_month(session):
    _expense(session, date(2026, 5, 10), 3000)
    task = month_close.enqueue_month_close(session, as_of=date(2026, 6, 1))
    roles.resolve(session, task, approved=True)
    assert task.status == TaskStatus.DONE
    # the period is now closed -> posting into May is rejected
    with pytest.raises(PostingError):
        _expense(session, date(2026, 5, 20), 100)
