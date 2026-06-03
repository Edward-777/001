"""Financial reports derived from journal_lines (SCHEMA §H). No stored tables —
these are computed on demand. The same functions back both the human UI and the
AI's "give me the January close" request.

Sign convention: net = Σdebit - Σcredit (debit-positive). Normal balances:
  asset/expense = +net,  liability/equity/revenue = -net.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ap_models import APBill
from .ledger_models import JournalEntry, JournalLine
from .models import Account

_ZERO = Decimal("0.00")
_POSTED = ["posted", "reversed"]  # reversed entries net out against their reversal


def _month_bounds(period: str) -> tuple[date, date]:
    y, m = (int(x) for x in period.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _net_by_account(session: Session, *, start: date | None = None, end: date | None = None) -> dict[int, Decimal]:
    """{account_id: Σdebit - Σcredit} over posted entries in the date window."""
    stmt = (
        select(JournalLine.account_id, func.sum(JournalLine.debit), func.sum(JournalLine.credit))
        .join(JournalEntry, JournalLine.je_id == JournalEntry.id)
        .where(JournalEntry.status.in_(_POSTED))
        .group_by(JournalLine.account_id)
    )
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    out: dict[int, Decimal] = {}
    for account_id, dr, cr in session.execute(stmt).all():
        out[account_id] = (Decimal(str(dr or 0)) - Decimal(str(cr or 0))).quantize(_ZERO)
    return out


def _accounts(session: Session) -> dict[int, Account]:
    return {a.id: a for a in session.scalars(select(Account))}


# ---- trial balance ------------------------------------------------------

def trial_balance(session: Session, *, as_of: date | None = None) -> dict:
    nets = _net_by_account(session, end=as_of)
    accts = _accounts(session)
    rows, total_dr, total_cr = [], _ZERO, _ZERO
    for aid, net in sorted(nets.items(), key=lambda kv: accts[kv[0]].code):
        if net == 0:
            continue
        debit = net if net > 0 else _ZERO
        credit = -net if net < 0 else _ZERO
        total_dr += debit
        total_cr += credit
        a = accts[aid]
        rows.append({"code": a.code, "name": a.name, "type": a.type, "debit": debit, "credit": credit})
    return {"rows": rows, "total_debit": total_dr, "total_credit": total_cr,
            "balanced": total_dr == total_cr}


# ---- income statement & balance sheet -----------------------------------

def _grouped(session: Session, nets: dict[int, Decimal]):
    accts = _accounts(session)
    groups: dict[str, list[dict]] = {"asset": [], "liability": [], "equity": [], "revenue": [], "expense": []}
    for aid, net in nets.items():
        if net == 0:
            continue
        a = accts[aid]
        # report each line as a positive number in its natural balance
        bal = net if a.type in ("asset", "expense") else -net
        groups[a.type].append({"code": a.code, "name": a.name, "balance": bal})
    for g in groups.values():
        g.sort(key=lambda r: r["code"])
    return groups


def income_statement(session: Session, *, start: date, end: date) -> dict:
    groups = _grouped(session, _net_by_account(session, start=start, end=end))
    revenue = sum((r["balance"] for r in groups["revenue"]), _ZERO)
    expenses = sum((r["balance"] for r in groups["expense"]), _ZERO)
    return {
        "revenue": groups["revenue"], "expenses": groups["expense"],
        "total_revenue": revenue, "total_expenses": expenses,
        "net_income": (revenue - expenses).quantize(_ZERO),
    }


def balance_sheet(session: Session, *, as_of: date) -> dict:
    groups = _grouped(session, _net_by_account(session, end=as_of))
    total_assets = sum((r["balance"] for r in groups["asset"]), _ZERO)
    total_liab = sum((r["balance"] for r in groups["liability"]), _ZERO)
    equity_accounts = sum((r["balance"] for r in groups["equity"]), _ZERO)
    revenue = sum((r["balance"] for r in groups["revenue"]), _ZERO)
    expenses = sum((r["balance"] for r in groups["expense"]), _ZERO)
    net_income = (revenue - expenses).quantize(_ZERO)
    total_equity = (equity_accounts + net_income).quantize(_ZERO)
    return {
        "assets": groups["asset"], "liabilities": groups["liability"], "equity": groups["equity"],
        "total_assets": total_assets, "total_liabilities": total_liab,
        "net_income": net_income, "total_equity": total_equity,
        "balanced": total_assets == (total_liab + total_equity),
    }


def generate_financials(session: Session, period: str) -> dict:
    """The "give me the January close" entrypoint: IS for the month + BS as of month-end."""
    start, end = _month_bounds(period)
    return {
        "period": period,
        "income_statement": income_statement(session, start=start, end=end),
        "balance_sheet": balance_sheet(session, as_of=end),
    }


# ---- general ledger -----------------------------------------------------

def general_ledger(session: Session, account_id: int, *, start: date | None = None, end: date | None = None) -> list[dict]:
    stmt = (
        select(JournalEntry.je_no, JournalEntry.entry_date, JournalEntry.description,
               JournalLine.debit, JournalLine.credit)
        .join(JournalEntry, JournalLine.je_id == JournalEntry.id)
        .where(JournalLine.account_id == account_id, JournalEntry.status.in_(_POSTED))
        .order_by(JournalEntry.entry_date, JournalEntry.id)
    )
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    return [
        {"je_no": je_no, "date": d, "description": desc, "debit": dr, "credit": cr}
        for je_no, d, desc, dr, cr in session.execute(stmt).all()
    ]


# ---- aging --------------------------------------------------------------

_BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def _bucket(as_of: date, due: date | None) -> str:
    if due is None or due >= as_of:
        return "current"
    days = (as_of - due).days
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def ap_aging(session: Session, *, as_of: date) -> dict:
    # Only POSTED bills (open/partially_paid) — draft/exception bills aren't in the
    # GL yet, so excluding them keeps the aging tied to the AP control account.
    bills = session.scalars(
        select(APBill).where(
            APBill.balance > 0, APBill.status.in_(["open", "partially_paid"])
        )
    ).all()
    buckets = {b: _ZERO for b in _BUCKETS}
    rows = []
    for b in bills:
        bucket = _bucket(as_of, b.due_date)
        bal = Decimal(str(b.balance))
        buckets[bucket] += bal
        rows.append({"bill_no": b.bill_no, "vendor_id": b.vendor_id, "due_date": b.due_date,
                     "balance": bal, "bucket": bucket})
    return {"as_of": as_of, "buckets": buckets, "rows": rows,
            "total": sum(buckets.values(), _ZERO)}


def ar_aging(session: Session, *, as_of: date) -> dict:
    from ..sales import service as sales

    invoices = sales.list_open_invoices(session)
    buckets = {b: _ZERO for b in _BUCKETS}
    rows = []
    for inv in invoices:
        bucket = _bucket(as_of, inv.due_date)
        bal = Decimal(str(inv.balance))
        buckets[bucket] += bal
        rows.append({"invoice_no": inv.invoice_no, "customer_id": inv.customer_id,
                     "due_date": inv.due_date, "balance": bal, "bucket": bucket})
    return {"as_of": as_of, "buckets": buckets, "rows": rows,
            "total": sum(buckets.values(), _ZERO)}


def inventory_valuation(session: Session) -> dict:
    from ..inventory import service as inv

    rows = []
    total = _ZERO
    for bal in inv.inventory_valuation(session):
        value = Decimal(str(bal.total_value))
        total += value
        rows.append({"product_id": bal.product_id, "qty": bal.qty_on_hand,
                     "avg_unit_cost": bal.avg_unit_cost, "value": value})
    return {"rows": rows, "total_value": total.quantize(_ZERO)}


def subledger_check(session: Session, *, as_of: date) -> dict:
    """Reconcile each subledger to its GL control account (P0-4). A mismatch =
    a rounding error or rogue manual entry — the first thing an accountant checks."""
    nets = _net_by_account(session, end=as_of)
    by_role = {a.system_role: nets.get(a.id, _ZERO) for a in _accounts(session).values()
               if a.system_role}

    def chk(name, gl, sub):
        gl, sub = gl.quantize(_ZERO), sub.quantize(_ZERO)
        return {"control": name, "gl": gl, "subledger": sub, "ok": gl == sub,
                "diff": (gl - sub).quantize(_ZERO)}

    checks = [
        chk("AP", -by_role.get("ap", _ZERO), ap_aging(session, as_of=as_of)["total"]),       # liability: -net
        chk("AR", by_role.get("ar", _ZERO), ar_aging(session, as_of=as_of)["total"]),         # asset: +net
        chk("Inventory", by_role.get("inventory", _ZERO), inventory_valuation(session)["total_value"]),
    ]
    return {"as_of": as_of, "checks": checks, "all_ok": all(c["ok"] for c in checks)}
