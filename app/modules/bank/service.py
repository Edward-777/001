"""bank.service — upload a statement, auto-match its lines to existing journal
entries, and book the leftovers (fees/interest) as new journal entries.

Matching uses the bank account's GL (cash) account: a +amount (deposit) should
correspond to a debit on that account (e.g. a customer receipt); a -amount
(withdrawal) to a credit (e.g. a vendor payment)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..accounting import service as acct
from ..accounting.service import Line
from .models import (
    BankAccount,
    BankStatement,
    BankStatementLine,
    LineMatchStatus,
    StatementStatus,
)

_CENTS = Decimal("0.01")


def create_bank_account(
    session: Session, *, name: str, gl_account_id: int, account_no_masked: str | None = None
) -> BankAccount:
    ba = BankAccount(name=name, gl_account_id=gl_account_id, account_no_masked=account_no_masked)
    session.add(ba)
    session.flush()
    return ba


def import_statement(
    session: Session,
    *,
    bank_account_id: int,
    period: str,
    lines: list[dict],
    opening_balance: Decimal | float = 0,
    closing_balance: Decimal | float = 0,
    source_file_path: str | None = None,
) -> BankStatement:
    """lines: [{txn_date, description, amount}] — amount +deposit / -withdrawal.
    (In production these come from AI-parsing the uploaded PDF/CSV.)"""
    stmt = BankStatement(
        bank_account_id=bank_account_id,
        period=period,
        opening_balance=Decimal(str(opening_balance)),
        closing_balance=Decimal(str(closing_balance)),
        source_file_path=source_file_path,
        status=str(StatementStatus.PARSED),
    )
    session.add(stmt)
    session.flush()
    for ln in lines:
        session.add(
            BankStatementLine(
                statement_id=stmt.id,
                txn_date=ln.get("txn_date"),
                description=ln.get("description"),
                amount=Decimal(str(ln.get("amount", 0))).quantize(_CENTS),
                match_status=str(LineMatchStatus.UNMATCHED),
            )
        )
    session.flush()
    return stmt


def _used_journal_line_ids(session: Session) -> set[int]:
    rows = session.scalars(
        select(BankStatementLine.matched_journal_line_id).where(
            BankStatementLine.matched_journal_line_id.isnot(None)
        )
    ).all()
    return set(rows)


def _refresh_status(session: Session, stmt: BankStatement) -> None:
    if all(ln.match_status != LineMatchStatus.UNMATCHED for ln in stmt.lines):
        stmt.status = str(StatementStatus.RECONCILED)


def reconcile(session: Session, statement_id: int) -> dict:
    """Auto-match statement lines to existing journal lines on the bank's GL
    account. Returns {matched, unmatched:[line_ids]}."""
    stmt = session.get(BankStatement, statement_id)
    bank = session.get(BankAccount, stmt.bank_account_id)
    used = _used_journal_line_ids(session)

    matched, unmatched = 0, []
    for line in stmt.lines:
        if line.match_status != LineMatchStatus.UNMATCHED:
            continue
        jl = acct.find_journal_line_match(
            session, account_id=bank.gl_account_id, amount=Decimal(str(line.amount)),
            exclude_ids=used,
        )
        if jl is not None:
            line.matched_journal_line_id = jl.id
            line.match_status = str(LineMatchStatus.MATCHED)
            used.add(jl.id)
            matched += 1
        else:
            unmatched.append(line.id)
    session.flush()
    _refresh_status(session, stmt)
    return {"matched": matched, "unmatched": unmatched}


def categorize_unmatched(
    session: Session,
    line_id: int,
    *,
    counter_account_role: str | None = None,
    counter_account_id: int | None = None,
) -> BankStatementLine:
    """Book a bank-only line (fee/interest) as a new JE against a counter account.
    -amount (money out, e.g. fee) -> Dr counter / Cr Bank;
    +amount (money in, e.g. interest) -> Dr Bank / Cr counter."""
    line = session.get(BankStatementLine, line_id)
    if line is None or line.match_status != LineMatchStatus.UNMATCHED:
        raise ValueError("line not unmatched")
    stmt = session.get(BankStatement, line.statement_id)
    bank = session.get(BankAccount, stmt.bank_account_id)

    if counter_account_id is None:
        counter = acct.get_account_by_role(session, counter_account_role)
        if counter is None:
            raise ValueError(f"unknown counter account role: {counter_account_role}")
        counter_account_id = counter.id

    amt = Decimal(str(line.amount))
    mag = abs(amt)
    if amt < 0:
        lines = [Line(counter_account_id, debit=mag), Line(bank.gl_account_id, credit=mag)]
    else:
        lines = [Line(bank.gl_account_id, debit=mag), Line(counter_account_id, credit=mag)]

    from ..accounting.ledger_models import JournalSource

    je = acct.post_journal(
        session,
        entry_date=line.txn_date or date.today(),
        lines=lines,
        description=f"Bank: {line.description or 'reconciliation item'}",
        source_type=JournalSource.BANK,
        source_id=line.id,
    )
    bank_line = next(jl for jl in je.lines if jl.account_id == bank.gl_account_id)
    line.matched_journal_line_id = bank_line.id
    line.match_status = str(LineMatchStatus.NEW_JE)
    session.flush()
    _refresh_status(session, stmt)
    return line
