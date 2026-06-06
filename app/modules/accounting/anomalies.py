"""Spend anomaly detection (docs/AGENT-FLEET.md §2 — the 📊 insight push).

Read-only analytics over the ledger: catch a category whose spend spiked vs its
own recent baseline, and likely duplicate vendor bills. Deterministic and cheap
so it can run on a schedule and surface alerts to the founder.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.money import ZERO as _ZERO
from . import reports as _r
from .ap_models import APBill


def _month_end(first: date) -> date:
    return date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])


def spend_anomalies(
    session: Session, *, as_of: date | None = None, trailing_months: int = 3,
    spike_factor: float = 2.0, min_amount: float = 100,
) -> list[dict]:
    """Expense categories whose current-month spend is >= spike_factor × the
    average of the prior `trailing_months` full months (and over a noise floor)."""
    as_of = as_of or date.today()
    accts = _r._accounts(session)
    expense = {a.id: a for a in accts.values() if a.type == "expense"}
    cstart = date(as_of.year, as_of.month, 1)
    current = _r._net_by_account(session, start=cstart, end=as_of)
    factor, floor = Decimal(str(spike_factor)), Decimal(str(min_amount))

    out: list[dict] = []
    for aid, a in expense.items():
        cur = current.get(aid, _ZERO)
        if cur < floor:
            continue
        totals = []
        for k in range(1, trailing_months + 1):
            ms = _r._months_back(as_of, k)
            nets = _r._net_by_account(session, start=ms, end=_month_end(ms))
            totals.append(nets.get(aid, _ZERO))
        baseline = (sum(totals, _ZERO) / trailing_months) if totals else _ZERO
        if baseline <= _ZERO:
            continue  # no history to compare against -> not flagged (avoid noise)
        if cur >= baseline * factor:
            out.append({
                "type": "spend_spike", "account_code": a.code, "account_name": a.name,
                "current": str(cur.quantize(_ZERO)), "baseline": str(baseline.quantize(_ZERO)),
                "factor": str((cur / baseline).quantize(Decimal("0.1"))),
            })
    return out


def duplicate_bills(session: Session, *, window_days: int = 7) -> list[dict]:
    """Vendor bills with the same vendor + amount within a short window — a likely
    double charge or double entry worth a human glance."""
    bills = list(session.scalars(select(APBill)))
    groups: dict[tuple, list[APBill]] = {}
    for b in bills:
        groups.setdefault((b.vendor_id, str(b.amount)), []).append(b)

    out: list[dict] = []
    for (vendor_id, amount), bs in groups.items():
        if len(bs) < 2:
            continue
        bs.sort(key=lambda x: x.bill_date or date.min)
        for i in range(len(bs) - 1):
            d1, d2 = bs[i].bill_date, bs[i + 1].bill_date
            if d1 and d2 and (d2 - d1).days <= window_days:
                out.append({
                    "type": "duplicate_bill", "vendor_id": vendor_id, "amount": amount,
                    "bill_nos": [bs[i].bill_no, bs[i + 1].bill_no],
                })
                break
    return out


def detect_all(session: Session, *, as_of: date | None = None) -> list[dict]:
    """Every anomaly, one flat list — what the insight role surfaces."""
    return spend_anomalies(session, as_of=as_of) + duplicate_bills(session)
