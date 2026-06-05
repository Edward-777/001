"""Downloadable report files (xlsx). The same report data the chat summarizes is
also offered as a real spreadsheet the user can hand to their accountant."""
from __future__ import annotations

import io
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import reports
from .ledger_models import JournalEntry

REPORT_KINDS = ("financials", "trial_balance", "ap_aging", "ar_aging", "inventory")


def latest_active_period(session: Session) -> str:
    """The YYYY-MM of the most recent journal activity (so 'current' financials
    land on real data, not an empty future month). Falls back to this month."""
    d = session.scalar(
        select(func.max(JournalEntry.entry_date)).where(
            JournalEntry.status.in_(["posted", "reversed"]))
    )
    d = d or date.today()
    return f"{d.year:04d}-{d.month:02d}"


def _h(ws, values) -> None:
    """Append a row and bold it (titles, headers, totals)."""
    from openpyxl.styles import Font

    ws.append(values)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)


def build_report_xlsx(session: Session, kind: str, period: str | None = None) -> tuple[str, bytes]:
    """Return (filename, xlsx-bytes) for a report kind."""
    from openpyxl import Workbook  # lazy: only needed when a report is exported

    period = period or latest_active_period(session)
    as_of = reports._month_bounds(period)[1]
    wb = Workbook()
    wb.remove(wb.active)

    if kind == "financials":
        fin = reports.generate_financials(session, period)
        is_, bs = fin["income_statement"], fin["balance_sheet"]
        s = wb.create_sheet("Income Statement")
        _h(s, [f"Income Statement — {period}"])
        _h(s, ["Account", "Amount"])
        for r in is_["revenue"]:
            s.append([f"Revenue: {r['code']} {r['name']}", float(r["balance"])])
        for r in is_["expenses"]:
            s.append([f"Expense: {r['code']} {r['name']}", float(r["balance"])])
        _h(s, ["Net income", float(is_["net_income"])])

        b = wb.create_sheet("Balance Sheet")
        _h(b, [f"Balance Sheet — as of {as_of}"])
        _h(b, ["Account", "Amount"])
        for grp, label in (("assets", "Asset"), ("liabilities", "Liability"), ("equity", "Equity")):
            for r in bs[grp]:
                b.append([f"{label}: {r['code']} {r['name']}", float(r["balance"])])
        b.append(["Total assets", float(bs["total_assets"])])
        b.append(["Total liabilities", float(bs["total_liabilities"])])
        _h(b, ["Total equity", float(bs["total_equity"])])

    elif kind == "trial_balance":
        tb = reports.trial_balance(session, as_of=as_of)
        s = wb.create_sheet("Trial Balance")
        _h(s, [f"Trial Balance — as of {as_of}"])
        _h(s, ["Code", "Account", "Type", "Debit", "Credit"])
        for r in tb["rows"]:
            s.append([r["code"], r["name"], r["type"], float(r["debit"]), float(r["credit"])])
        _h(s, ["", "TOTAL", "", float(tb["total_debit"]), float(tb["total_credit"])])

    elif kind in ("ap_aging", "ar_aging"):
        ag = (reports.ap_aging if kind == "ap_aging" else reports.ar_aging)(session, as_of=as_of)
        s = wb.create_sheet("Aging")
        _h(s, [f"{'AP' if kind == 'ap_aging' else 'AR'} Aging — as of {as_of}"])
        _h(s, ["Document", "Party", "Due date", "Balance", "Bucket"])
        for r in ag["rows"]:
            doc = r.get("bill_no") or r.get("invoice_no")
            party = r.get("vendor_id") or r.get("customer_id")
            s.append([doc, party, str(r.get("due_date") or ""), float(r["balance"]), r["bucket"]])
        _h(s, ["", "", "TOTAL", float(ag["total"]), ""])

    elif kind == "inventory":
        val = reports.inventory_valuation(session)
        s = wb.create_sheet("Inventory")
        _h(s, ["Inventory Valuation"])
        _h(s, ["Product id", "Qty on hand", "Avg cost", "Value"])
        for r in val["rows"]:
            s.append([r["product_id"], float(r["qty"]), float(r["avg_unit_cost"]), float(r["value"])])
        _h(s, ["", "", "TOTAL", float(val["total_value"])])
    else:
        raise ValueError(f"unknown report kind: {kind}")

    buf = io.BytesIO()
    wb.save(buf)
    return f"{kind}_{period}.xlsx", buf.getvalue()
