"""M12 — bank reconciliation: upload a monthly statement, auto-match its lines to
existing journal entries on the cash account, and book the leftover (a bank fee)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import accounting, bank  # noqa: F401  register tables
from app.modules.accounting import service as acct
from app.modules.accounting.ledger_models import JournalEntry, JournalLine
from app.modules.accounting.service import Line
from app.modules.bank import service as bank_svc
from app.modules.bank.models import LineMatchStatus, StatementStatus

JAN = date(2026, 1, 20)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        s.flush()
        yield s


def _cash(session):
    return acct.get_account_by_role(session, "cash").id


def _seed_cash_activity(session):
    """Two transactions that already hit cash (a $100 deposit and a $60 payment)."""
    rev = acct.get_account_by_code(session, "4000").id
    rent = acct.get_account_by_code(session, "6100").id
    acct.post_journal(session, entry_date=JAN,
                      lines=[Line(_cash(session), debit=100), Line(rev, credit=100)],
                      description="cash sale")
    acct.post_journal(session, entry_date=JAN,
                      lines=[Line(rent, debit=60), Line(_cash(session), credit=60)],
                      description="rent payment")


def test_statement_auto_matches_existing_entries(session):
    _seed_cash_activity(session)
    ba = bank_svc.create_bank_account(session, name="Checking", gl_account_id=_cash(session))
    stmt = bank_svc.import_statement(
        session, bank_account_id=ba.id, period="2026-01",
        lines=[
            {"txn_date": JAN, "description": "Customer deposit", "amount": 100},
            {"txn_date": JAN, "description": "Rent ACH", "amount": -60},
        ],
    )
    result = bank_svc.reconcile(session, stmt.id)
    assert result["matched"] == 2
    assert result["unmatched"] == []
    assert all(ln.match_status == LineMatchStatus.MATCHED for ln in stmt.lines)
    assert stmt.status == StatementStatus.RECONCILED


def test_unmatched_fee_booked_as_new_je(session):
    _seed_cash_activity(session)
    ba = bank_svc.create_bank_account(session, name="Checking", gl_account_id=_cash(session))
    stmt = bank_svc.import_statement(
        session, bank_account_id=ba.id, period="2026-01",
        lines=[
            {"txn_date": JAN, "description": "Customer deposit", "amount": 100},
            {"txn_date": JAN, "description": "Monthly service charge", "amount": -5},
        ],
    )
    result = bank_svc.reconcile(session, stmt.id)
    assert result["matched"] == 1
    fee_line_id = result["unmatched"][0]

    bank_svc.categorize_unmatched(session, fee_line_id, counter_account_role="bank_fees")

    # a new JE: Dr Bank Service Charges 5 / Cr Cash 5
    je = [j for j in session.scalars(select(JournalEntry)) if j.source_type == "bank"][0]
    rows = session.scalars(select(JournalLine).where(JournalLine.je_id == je.id)).all()
    by = {ln.account_id: (ln.debit, ln.credit) for ln in rows}
    assert by[acct.get_account_by_role(session, "bank_fees").id] == (Decimal("5.00"), Decimal("0.00"))
    assert by[_cash(session)] == (Decimal("0.00"), Decimal("5.00"))
    # statement now fully reconciled
    assert stmt.status == StatementStatus.RECONCILED


def test_same_amount_lines_match_distinct_entries(session):
    """Two $50 deposits must match two different journal lines, not the same one."""
    rev = acct.get_account_by_code(session, "4000").id
    for _ in range(2):
        acct.post_journal(session, entry_date=JAN,
                          lines=[Line(_cash(session), debit=50), Line(rev, credit=50)])
    ba = bank_svc.create_bank_account(session, name="Checking", gl_account_id=_cash(session))
    stmt = bank_svc.import_statement(
        session, bank_account_id=ba.id, period="2026-01",
        lines=[{"amount": 50, "description": "dep1"}, {"amount": 50, "description": "dep2"}],
    )
    result = bank_svc.reconcile(session, stmt.id)
    assert result["matched"] == 2
    matched_ids = {ln.matched_journal_line_id for ln in stmt.lines}
    assert len(matched_ids) == 2  # two distinct journal lines


def test_reconcile_is_idempotent(session):
    _seed_cash_activity(session)
    ba = bank_svc.create_bank_account(session, name="Checking", gl_account_id=_cash(session))
    stmt = bank_svc.import_statement(
        session, bank_account_id=ba.id, period="2026-01",
        lines=[{"amount": 100, "description": "dep"}],
    )
    assert bank_svc.reconcile(session, stmt.id)["matched"] == 1
    assert bank_svc.reconcile(session, stmt.id)["matched"] == 0  # already matched
