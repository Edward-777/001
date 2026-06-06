"""Founder cash insight — runway / burn / affordability (AGENT-FLEET §2 star)."""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register tables
    accounting, approval, assets, auth, bank, documents, expense,
    hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct

AS_OF = date(2026, 6, 30)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        yield s


def _post(session, d, debit_code, credit_code, amount):
    dr = acct.get_account_by_code(session, debit_code)
    cr = acct.get_account_by_code(session, credit_code)
    acct.post_journal(
        session, entry_date=d,
        lines=[acct.Line(dr.id, debit=amount), acct.Line(cr.id, credit=amount)],
        description="test",
    )


def _seed_burning_startup(session):
    # $60k cash injection, then $5k/mo rent burn for Apr/May/Jun -> $45k cash left.
    _post(session, date(2026, 1, 1), "1000", "3100", 60000)
    for m in (4, 5, 6):
        _post(session, date(2026, m, 15), "6100", "1000", 5000)


def test_runway_from_cash_and_burn(session):
    _seed_burning_startup(session)
    r = acct.cash_runway(session, as_of=AS_OF, trailing_months=3)
    assert str(r["cash"]) == "45000.00"
    assert str(r["monthly_burn"]) == "5000.00"
    assert str(r["runway_months"]) == "9.0"   # 45000 / 5000
    assert r["profitable"] is False


def test_profitable_company_has_open_ended_runway(session):
    # revenue exceeds the only expense -> no burn
    _post(session, date(2026, 1, 1), "1000", "3100", 10000)
    _post(session, date(2026, 6, 10), "1000", "4000", 20000)   # cash sale (revenue)
    _post(session, date(2026, 6, 12), "6100", "1000", 3000)    # small expense
    r = acct.cash_runway(session, as_of=AS_OF, trailing_months=3)
    assert r["profitable"] is True
    assert r["runway_months"] is None


def test_affordability_reduces_runway(session):
    _seed_burning_startup(session)
    a = acct.affordability(session, amount=18000, as_of=AS_OF, trailing_months=3)
    assert str(a["cash_after"]) == "27000.00"
    assert a["affordable"] is True
    assert str(a["runway_after"]) == "5.4"   # 27000 / 5000
    assert str(a["runway_before"]) == "9.0"


def test_affordability_flags_unaffordable(session):
    _seed_burning_startup(session)
    a = acct.affordability(session, amount=99999, as_of=AS_OF, trailing_months=3)
    assert a["affordable"] is False
