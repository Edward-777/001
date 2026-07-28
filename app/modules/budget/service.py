"""budget.service — plan vs reality per expense account.

Actual = posted debits minus credits on the account in the period (credits net
out refunds and reversals). Only EXPENSE accounts can carry a budget: revenue
targets are a different animal and assets/liabilities have no "spend"."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core import audit
from ...core.money import money
from ..accounting.ledger_models import JournalEntry, JournalLine, JournalStatus
from ..accounting.models import Account, AccountType
from .models import Budget


def set_budget(session: Session, *, account_code: str, year: int,
               monthly_amount, created_by: int | None = None) -> Budget:
    account = session.scalar(select(Account).where(Account.code == str(account_code)))
    if account is None:
        raise ValueError(f"unknown account code {account_code!r}")
    if account.type != str(AccountType.EXPENSE):
        raise ValueError(f"{account.code} {account.name} is {account.type}, not an "
                         "expense account — only expense accounts carry a budget")
    amount = money(monthly_amount)
    if amount < 0:
        raise ValueError("monthly_amount must be >= 0")
    row = session.scalar(select(Budget).where(
        Budget.account_id == account.id, Budget.year == year))
    if row is None:
        row = Budget(account_id=account.id, year=year, monthly_amount=amount)
        session.add(row)
    else:
        row.monthly_amount = amount
    session.flush()
    audit.record(session, actor_user_id=created_by, action="update",
                 entity_type="budget", entity_id=row.id,
                 detail={"account": account.code, "year": year,
                         "monthly_amount": str(amount)})
    return row


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def actual(session: Session, account_id: int, year: int,
           month: int | None = None) -> Decimal:
    """Posted net debits on the account: one month, or YTD through `month=None`
    meaning the whole year."""
    start = date(year, 1, 1) if month is None else _month_bounds(year, month)[0]
    end = date(year + 1, 1, 1) if month is None else _month_bounds(year, month)[1]
    total = session.scalar(
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.je_id)
        .where(JournalLine.account_id == account_id,
               JournalEntry.status == str(JournalStatus.POSTED),
               JournalEntry.entry_date >= start,
               JournalEntry.entry_date < end))
    return money(total or 0)


def _ytd_actual(session: Session, account_id: int, year: int, month: int) -> Decimal:
    end = _month_bounds(year, month)[1]
    total = session.scalar(
        select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
        .join(JournalEntry, JournalEntry.id == JournalLine.je_id)
        .where(JournalLine.account_id == account_id,
               JournalEntry.status == str(JournalStatus.POSTED),
               JournalEntry.entry_date >= date(year, 1, 1),
               JournalEntry.entry_date < end))
    return money(total or 0)


def _pct(spent: Decimal, budget: Decimal) -> float | None:
    if budget <= 0:
        return None
    return round(float(spent / budget * 100), 1)


def budget_vs_actual(session: Session, *, year: int, month: int) -> dict:
    """Per budgeted account: this month's actual vs the monthly budget, plus
    YTD (monthly × months elapsed) — and any UNBUDGETED expense spend this
    month, so the report never hides money by omission."""
    if not 1 <= month <= 12:
        raise ValueError("month must be 1..12")
    rows = []
    budgeted_ids = set()
    for b in session.scalars(select(Budget).where(Budget.year == year)):
        account = session.get(Account, b.account_id)
        budgeted_ids.add(b.account_id)
        monthly = money(b.monthly_amount)
        spent = actual(session, b.account_id, year, month)
        ytd_budget = money(monthly * month)
        ytd_spent = _ytd_actual(session, b.account_id, year, month)
        rows.append({
            "account_code": account.code, "account_name": account.name,
            "monthly_budget": str(monthly), "month_actual": str(spent),
            "month_remaining": str(money(monthly - spent)),
            "month_pct": _pct(spent, monthly),
            "ytd_budget": str(ytd_budget), "ytd_actual": str(ytd_spent),
            "ytd_pct": _pct(ytd_spent, ytd_budget),
            "over": spent > monthly,
        })
    rows.sort(key=lambda r: r["account_code"])

    unbudgeted = []
    expense_accounts = session.scalars(select(Account).where(
        Account.type == str(AccountType.EXPENSE)))
    for account in expense_accounts:
        if account.id in budgeted_ids:
            continue
        spent = actual(session, account.id, year, month)
        if spent != 0:
            unbudgeted.append({"account_code": account.code,
                               "account_name": account.name,
                               "month_actual": str(spent)})
    unbudgeted.sort(key=lambda r: r["account_code"])

    total_budget = sum((money(r["monthly_budget"]) for r in rows), Decimal("0"))
    total_actual = sum((money(r["month_actual"]) for r in rows), Decimal("0"))
    return {"year": year, "month": month, "rows": rows,
            "unbudgeted": unbudgeted,
            "total_monthly_budget": str(total_budget),
            "total_month_actual": str(total_actual),
            "total_month_pct": _pct(total_actual, total_budget)}


def overruns(session: Session, *, as_of: date | None = None) -> list[dict]:
    """Budgeted accounts already OVER their monthly amount in as_of's month."""
    as_of = as_of or date.today()
    report = budget_vs_actual(session, year=as_of.year, month=as_of.month)
    return [r for r in report["rows"] if r["over"]]


def consumption_note(session: Session, *, account_id: int, add_amount,
                     on_date: date | None = None) -> str | None:
    """One line for spend tools: where this posting leaves the month's budget.
    None when the account has no budget (nothing to say)."""
    on_date = on_date or date.today()
    b = session.scalar(select(Budget).where(
        Budget.account_id == account_id, Budget.year == on_date.year))
    if b is None:
        return None
    account = session.get(Account, account_id)
    monthly = money(b.monthly_amount)
    after = actual(session, account_id, on_date.year, on_date.month) + money(add_amount)
    pct = _pct(after, monthly)
    note = (f"{account.code} {account.name}: {on_date.strftime('%B')} spend now "
            f"${after} of ${monthly} budget"
            + (f" ({pct}%)" if pct is not None else ""))
    if monthly > 0 and after > monthly:
        note += " — OVER BUDGET"
    return note
