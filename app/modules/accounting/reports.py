"""Financial reports derived from journal_lines (SCHEMA §H). No stored tables —
these are computed on demand. The same functions back both the human UI and the
AI's "give me the January close" request.

Sign convention: net = Σdebit - Σcredit (debit-positive). Normal balances:
  asset/expense = +net,  liability/equity/revenue = -net.

Scope notes (acknowledged limitations):
  - No year-end CLOSE entry is posted (net income -> Retained Earnings). The
    balance sheet folds current net income into equity on the fly, which is
    correct for interim/period statements; a formal annual close is future work.
  - reporting reads other modules (inventory/sales) directly. That is an
    intentional exception to the "accounting reacts via events" rule, which
    governs POSTING only; read-only reporting/queries are allowed (ARCHITECTURE §3).
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.money import ZERO as _ZERO
from .ap_models import APBill
from .ledger_models import JournalEntry, JournalLine
from .models import Account

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


def _total(group: list[dict]) -> Decimal:
    return sum((r["balance"] for r in group), _ZERO)


def _net_income(groups: dict[str, list[dict]]) -> Decimal:
    return (_total(groups["revenue"]) - _total(groups["expense"])).quantize(_ZERO)


def income_statement(session: Session, *, start: date, end: date) -> dict:
    groups = _grouped(session, _net_by_account(session, start=start, end=end))
    return {
        "revenue": groups["revenue"], "expenses": groups["expense"],
        "total_revenue": _total(groups["revenue"]), "total_expenses": _total(groups["expense"]),
        "net_income": _net_income(groups),
    }


def balance_sheet(session: Session, *, as_of: date) -> dict:
    groups = _grouped(session, _net_by_account(session, end=as_of))
    total_assets = _total(groups["asset"])
    total_liab = _total(groups["liability"])
    net_income = _net_income(groups)
    total_equity = (_total(groups["equity"]) + net_income).quantize(_ZERO)
    return {
        "assets": groups["asset"], "liabilities": groups["liability"], "equity": groups["equity"],
        "total_assets": total_assets, "total_liabilities": total_liab,
        "net_income": net_income, "total_equity": total_equity,
        "balanced": total_assets == (total_liab + total_equity),
    }


def cash_flow(session: Session, *, start: date, end: date) -> dict:
    """Statement of cash flows — indirect method (simplified): net income + non-cash
    (depreciation) ± working-capital changes ≈ operating; the rest is investing/
    financing. Net change always equals the movement in the cash/bank accounts."""
    from datetime import timedelta

    accts = _accounts(session)
    cash_ids = [a.id for a in accts.values() if a.type == "asset" and a.subtype == "bank"]

    def cash_balance(as_of: date) -> Decimal:
        nets = _net_by_account(session, end=as_of)
        return sum((nets.get(i, _ZERO) for i in cash_ids), _ZERO).quantize(_ZERO)

    beginning = cash_balance(start - timedelta(days=1))
    ending = cash_balance(end)
    net_change = (ending - beginning).quantize(_ZERO)

    period = _net_by_account(session, start=start, end=end)
    by_role = {a.system_role: period.get(a.id, _ZERO) for a in accts.values() if a.system_role}
    net_income = income_statement(session, start=start, end=end)["net_income"]
    deprec_addback = -by_role.get("accum_deprec", _ZERO)       # non-cash expense add-back
    operating = (
        net_income + deprec_addback
        - by_role.get("ar", _ZERO)            # AR increase uses cash
        - by_role.get("inventory", _ZERO)     # inventory increase uses cash
        - by_role.get("ap", _ZERO)            # AP increase (net is negative) sources cash
    ).quantize(_ZERO)
    return {
        "beginning_cash": beginning, "ending_cash": ending, "net_change": net_change,
        "operating": operating, "investing_financing": (net_change - operating).quantize(_ZERO),
        "method": "indirect (simplified)",
    }


def generate_financials(session: Session, period: str) -> dict:
    """The "give me the January close" entrypoint: IS + BS + TB + cash flow, plus
    the subledger->GL tie-out control so the close report flags any divergence."""
    start, end = _month_bounds(period)
    return {
        "period": period,
        "income_statement": income_statement(session, start=start, end=end),
        "balance_sheet": balance_sheet(session, as_of=end),
        "trial_balance": trial_balance(session, as_of=end),
        "cash_flow": cash_flow(session, start=start, end=end),
        "subledger_check": subledger_check(session, as_of=end),
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


def _aging(items, *, as_of: date, due_of, bal_of, row_of) -> dict:
    """Bucket a set of open documents by days-past-due. Shared by AP and AR."""
    buckets = {b: _ZERO for b in _BUCKETS}
    rows = []
    for it in items:
        bucket = _bucket(as_of, due_of(it))
        bal = Decimal(str(bal_of(it)))
        buckets[bucket] += bal
        rows.append({**row_of(it), "balance": bal, "bucket": bucket})
    return {"as_of": as_of, "buckets": buckets, "rows": rows,
            "total": sum(buckets.values(), _ZERO)}


def ap_aging(session: Session, *, as_of: date) -> dict:
    # Only POSTED bills (open/partially_paid) — draft/exception bills aren't in the
    # GL yet, so excluding them keeps the aging tied to the AP control account.
    bills = session.scalars(
        select(APBill).where(APBill.balance > 0, APBill.status.in_(["open", "partially_paid"]))
    ).all()
    return _aging(
        bills, as_of=as_of, due_of=lambda b: b.due_date, bal_of=lambda b: b.balance,
        row_of=lambda b: {"bill_no": b.bill_no, "vendor_id": b.vendor_id, "due_date": b.due_date},
    )


def ar_aging(session: Session, *, as_of: date) -> dict:
    from ..sales import service as sales

    return _aging(
        sales.list_open_invoices(session), as_of=as_of,
        due_of=lambda i: i.due_date, bal_of=lambda i: i.balance,
        row_of=lambda i: {"invoice_no": i.invoice_no, "customer_id": i.customer_id,
                          "due_date": i.due_date},
    )


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
