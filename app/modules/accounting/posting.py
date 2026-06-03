"""The posting engine — every journal entry in the system goes through here
(ARCHITECTURE §4). Guarantees: balanced (Σdebit = Σcredit), period open,
gapless numbering, audit-logged, posted-immutable (reverse-only, POLICIES §G9).

The LLM never writes entries as free text — it calls a tool that ultimately
lands here, so AI postings obey the exact same rules as human ones (AI-AGENT §3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.sequences import next_number
from .ledger_models import (
    AccountingPeriod,
    JournalEntry,
    JournalLine,
    JournalSource,
    JournalStatus,
    PeriodStatus,
    PostingRule,
)

_CENTS = Decimal("0.01")


class PostingError(Exception):
    """Invalid posting (unbalanced, closed period, bad state)."""


@dataclass
class Line:
    account_id: int
    debit: Decimal | float = 0
    credit: Decimal | float = 0
    memo: str | None = None


@dataclass
class Posting:
    """A balanced set of lines to post."""

    lines: list[Line] = field(default_factory=list)


def _d(x: Decimal | float) -> Decimal:
    return Decimal(str(x)).quantize(_CENTS)


# ---- accounting periods -------------------------------------------------

def get_or_create_period(session: Session, period: str) -> AccountingPeriod:
    p = session.scalar(select(AccountingPeriod).where(AccountingPeriod.period == period))
    if p is None:
        p = AccountingPeriod(period=period, status=str(PeriodStatus.OPEN))
        session.add(p)
        session.flush()
    return p


def ensure_period_open(session: Session, entry_date: date) -> None:
    period = f"{entry_date.year:04d}-{entry_date.month:02d}"
    p = get_or_create_period(session, period)
    if p.status == PeriodStatus.CLOSED:
        raise PostingError(f"period {period} is closed")


def close_period(session: Session, period: str, *, closed_by: int | None = None) -> AccountingPeriod:
    from datetime import datetime, timezone

    p = get_or_create_period(session, period)
    p.status = str(PeriodStatus.CLOSED)
    p.closed_at = datetime.now(timezone.utc)
    p.closed_by = closed_by
    return p


# ---- the core: post a balanced journal entry ----------------------------

def post_journal(
    session: Session,
    *,
    entry_date: date,
    lines: list[Line],
    description: str | None = None,
    source_type: JournalSource = JournalSource.MANUAL,
    source_id: int | None = None,
    actor_user_id: int | None = None,
) -> JournalEntry:
    if not lines:
        raise PostingError("no lines")

    total_debit = sum((_d(line.debit) for line in lines), Decimal("0"))
    total_credit = sum((_d(line.credit) for line in lines), Decimal("0"))
    if total_debit != total_credit:
        raise PostingError(f"unbalanced: debit {total_debit} != credit {total_credit}")
    if total_debit <= 0:
        raise PostingError("zero-amount entry")

    ensure_period_open(session, entry_date)

    from datetime import datetime, timezone

    je = JournalEntry(
        je_no=next_number(session, "JE", entry_date.year),
        entry_date=entry_date,
        description=description,
        source_type=str(source_type),
        source_id=source_id,
        status=str(JournalStatus.POSTED),
        posted_at=datetime.now(timezone.utc),
    )
    session.add(je)
    session.flush()
    for line in lines:
        session.add(
            JournalLine(
                je_id=je.id,
                account_id=line.account_id,
                debit=_d(line.debit),
                credit=_d(line.credit),
                memo=line.memo,
            )
        )
    audit.record(
        session,
        actor_user_id=actor_user_id,
        action="post",
        entity_type="journal_entry",
        entity_id=je.id,
        detail={"je_no": je.je_no, "amount": str(total_debit), "source": str(source_type)},
    )
    session.flush()
    return je


# ---- rule-driven convenience for simple 2-line events -------------------

def apply_rule(
    session: Session,
    *,
    event_type: str,
    amount: Decimal | float,
    entry_date: date,
    condition: str | None = None,
    description: str | None = None,
    source_type: JournalSource = JournalSource.MANUAL,
    source_id: int | None = None,
    actor_user_id: int | None = None,
) -> JournalEntry:
    """Look up the posting rule, resolve roles -> accounts, post a balanced JE."""
    from .service import get_account_by_role  # lazy import: avoids import cycle

    rule = session.scalar(
        select(PostingRule).where(
            PostingRule.event_type == event_type, PostingRule.condition == condition
        )
    )
    if rule is None:
        raise PostingError(f"no posting rule for ({event_type}, {condition})")

    dr = get_account_by_role(session, rule.debit_role)
    cr = get_account_by_role(session, rule.credit_role)
    if dr is None or cr is None:
        raise PostingError(f"unresolved role(s): {rule.debit_role}/{rule.credit_role}")

    return post_journal(
        session,
        entry_date=entry_date,
        lines=[Line(dr.id, debit=amount), Line(cr.id, credit=amount)],
        description=description,
        source_type=source_type,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )


# ---- reversal (POLICIES §G9: posted entries are corrected, never edited) -

def reverse_journal(
    session: Session,
    je_id: int,
    *,
    entry_date: date | None = None,
    actor_user_id: int | None = None,
) -> JournalEntry:
    orig = session.get(JournalEntry, je_id)
    if orig is None:
        raise PostingError("entry not found")
    if orig.status != JournalStatus.POSTED:
        raise PostingError(f"cannot reverse a {orig.status} entry")

    rev_date = entry_date or orig.entry_date
    swapped = [
        Line(line.account_id, debit=line.credit, credit=line.debit, memo=line.memo)
        for line in orig.lines
    ]
    rev = post_journal(
        session,
        entry_date=rev_date,
        lines=swapped,
        description=f"Reversal of {orig.je_no}",
        source_type=JournalSource(orig.source_type),
        source_id=orig.source_id,
        actor_user_id=actor_user_id,
    )
    rev.reverses_id = orig.id
    orig.reversed_by_id = rev.id
    orig.status = str(JournalStatus.REVERSED)
    session.flush()
    return rev


# ---- seed ---------------------------------------------------------------

def seed_posting_rules(session: Session) -> int:
    from .posting_rules_seed import DEFAULT_POSTING_RULES

    existing = {
        (r.event_type, r.condition)
        for r in session.scalars(select(PostingRule)).all()
    }
    inserted = 0
    for event_type, condition, debit_role, credit_role in DEFAULT_POSTING_RULES:
        if (event_type, condition) in existing:
            continue
        session.add(
            PostingRule(
                event_type=event_type,
                condition=condition,
                debit_role=debit_role,
                credit_role=credit_role,
            )
        )
        inserted += 1
    session.flush()
    return inserted
