"""M4 — the posting engine: balance invariant, period lock, reversal, rules."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs and learned rules cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave,
    notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.accounting.ledger_models import JournalStatus
from app.modules.accounting.posting import Line, PostingError

JAN = date(2026, 1, 15)
FEB = date(2026, 2, 10)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        s.flush()
        yield s


def _acct(session, role):
    return acct.get_account_by_role(session, role).id


def test_balanced_entry_posts(session):
    je = acct.post_journal(
        session,
        entry_date=JAN,
        description="manual test",
        lines=[
            Line(_acct(session, "inventory"), debit=100),
            Line(_acct(session, "gr_ir"), credit=100),
        ],
    )
    assert je.status == JournalStatus.POSTED
    assert je.je_no == "JE-2026-0001"
    assert len(je.lines) == 2


def test_unbalanced_entry_rejected(session):
    with pytest.raises(PostingError, match="unbalanced"):
        acct.post_journal(
            session,
            entry_date=JAN,
            lines=[
                Line(_acct(session, "inventory"), debit=100),
                Line(_acct(session, "gr_ir"), credit=99),
            ],
        )


def test_zero_amount_rejected(session):
    with pytest.raises(PostingError, match="zero"):
        acct.post_journal(
            session,
            entry_date=JAN,
            lines=[Line(_acct(session, "inventory"), debit=0), Line(_acct(session, "gr_ir"), credit=0)],
        )


def test_gapless_numbering(session):
    a, b = _acct(session, "inventory"), _acct(session, "gr_ir")
    je1 = acct.post_journal(session, entry_date=JAN, lines=[Line(a, debit=10), Line(b, credit=10)])
    je2 = acct.post_journal(session, entry_date=JAN, lines=[Line(a, debit=20), Line(b, credit=20)])
    assert (je1.je_no, je2.je_no) == ("JE-2026-0001", "JE-2026-0002")


def test_closed_period_blocks_posting(session):
    acct.close_period(session, "2026-01")
    with pytest.raises(PostingError, match="closed"):
        acct.post_journal(
            session,
            entry_date=JAN,
            lines=[Line(_acct(session, "inventory"), debit=5), Line(_acct(session, "gr_ir"), credit=5)],
        )
    # but an open period still works
    je = acct.post_journal(
        session, entry_date=FEB,
        lines=[Line(_acct(session, "inventory"), debit=5), Line(_acct(session, "gr_ir"), credit=5)],
    )
    assert je.status == JournalStatus.POSTED


def test_apply_rule_inbound_inventory(session):
    """The exact path M7 will trigger: InboundPosted(inventory) -> Dr Inventory / Cr GR-IR."""
    je = acct.apply_rule(
        session, event_type="inbound.posted", condition="inventory",
        amount=Decimal("250.00"), entry_date=JAN, source_id=1,
    )
    by_acct = {line.account_id: (line.debit, line.credit) for line in je.lines}
    inv, grir = _acct(session, "inventory"), _acct(session, "gr_ir")
    assert by_acct[inv] == (Decimal("250.00"), Decimal("0.00"))
    assert by_acct[grir] == (Decimal("0.00"), Decimal("250.00"))


def test_apply_rule_inbound_asset_routes_differently(session):
    je = acct.apply_rule(
        session, event_type="inbound.posted", condition="asset",
        amount=100, entry_date=JAN,
    )
    debited = next(line.account_id for line in je.lines if line.debit > 0)
    assert debited == _acct(session, "fixed_asset")


def test_reversal_swaps_and_links(session):
    a, b = _acct(session, "inventory"), _acct(session, "gr_ir")
    orig = acct.post_journal(session, entry_date=JAN, lines=[Line(a, debit=80), Line(b, credit=80)])
    rev = acct.reverse_journal(session, orig.id)

    assert orig.status == JournalStatus.REVERSED
    assert orig.reversed_by_id == rev.id
    assert rev.reverses_id == orig.id
    # debit/credit swapped
    rev_by_acct = {line.account_id: (line.debit, line.credit) for line in rev.lines}
    assert rev_by_acct[a] == (Decimal("0.00"), Decimal("80.00"))
    assert rev_by_acct[b] == (Decimal("80.00"), Decimal("0.00"))


def test_cannot_reverse_twice(session):
    a, b = _acct(session, "inventory"), _acct(session, "gr_ir")
    orig = acct.post_journal(session, entry_date=JAN, lines=[Line(a, debit=80), Line(b, credit=80)])
    acct.reverse_journal(session, orig.id)
    with pytest.raises(PostingError, match="cannot reverse"):
        acct.reverse_journal(session, orig.id)


def test_posting_rules_seed_idempotent(session):
    assert acct.seed_posting_rules(session) == 0  # already seeded in fixture
