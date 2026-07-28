"""Budget vs actual page — finance L3 (same gate as the financial statements)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.accounting.models import Account, AccountType
from ..modules.budget import service as budget
from .deps import require_scope, templates

router = APIRouter()
_finance3 = require_scope("finance", 3)


def _render(request: Request, user, session: Session, *, year: int, month: int,
            error: str | None = None):
    report = budget.budget_vs_actual(session, year=year, month=month)
    expense_accounts = list(session.scalars(
        select(Account).where(Account.type == str(AccountType.EXPENSE),
                              Account.is_active.is_(True)).order_by(Account.code)))
    return templates.TemplateResponse(request, "budget.html", {
        "user": user, "r": report, "accounts": expense_accounts,
        "period": f"{year:04d}-{month:02d}", "error": error,
    })


@router.get("/budget", response_class=HTMLResponse)
def budget_page(request: Request, period: str = Query(""),
                user=Depends(_finance3), session: Session = Depends(get_session)):
    today = date.today()
    year, month = today.year, today.month
    if period:
        try:
            year, month = int(period[:4]), int(period[5:7])
        except ValueError:
            pass
    try:
        return _render(request, user, session, year=year, month=month)
    except ValueError as exc:
        return _render(request, user, session, year=today.year, month=today.month,
                       error=str(exc))


@router.post("/budget/set", response_class=HTMLResponse)
def budget_set(request: Request, account_code: str = Form(...),
               monthly_amount: float = Form(...), period: str = Form(""),
               user=Depends(_finance3), session: Session = Depends(get_session)):
    today = date.today()
    year = int(period[:4]) if period else today.year
    month = int(period[5:7]) if period else today.month
    try:
        budget.set_budget(session, account_code=account_code, year=year,
                          monthly_amount=monthly_amount, created_by=user.id)
    except ValueError as exc:
        return _render(request, user, session, year=year, month=month, error=str(exc))
    return RedirectResponse(f"/budget?period={year:04d}-{month:02d}", status_code=303)
