"""Order-to-cash pipeline UI (docs/AGENT-FLEET.md §1).

The founder runs the whole quote -> PO -> ship -> invoice flow here, downloading
the customer-facing documents (quote, packing list, invoice) at each step.
Login-gated; the invoice step posts revenue, so it requires finance authority.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_session
from ..modules.auth import service as auth
from ..modules.sales import documents as sdocs
from ..modules.sales import fulfillment as ful
from ..modules.sales import service as sales
from ..modules.sales.models import ARInvoice, SalesOrder, Shipment
from .deps import require_scope, templates

router = APIRouter()
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# O2C authority (DESIGN §8.5): reading the pipeline/documents = sales L1;
# moving it forward (quote, acceptance, shipment — which deducts stock) =
# sales L2; invoicing posts REVENUE, so it stays finance L3.
_sales1 = require_scope("sales", 1)
_sales2 = require_scope("sales", 2)
_finance3 = require_scope("finance", 3)


def _can_finance(user) -> bool:
    return auth.can_access(auth.get_grants(user), "finance", 3)


def _pipeline_rows(session: Session) -> list[dict]:
    """One row per quote with its downstream SO / shipment / invoice (if any)."""
    rows = []
    for q in ful.list_quotes(session):
        shipment = invoice = so = None
        if q.so_id is not None:
            so = session.get(SalesOrder, q.so_id)
            shipment = session.scalar(select(Shipment).where(Shipment.so_id == q.so_id))
            invoice = session.scalar(select(ARInvoice).where(ARInvoice.so_id == q.so_id))
        cust = sales.get_customer(session, q.customer_id)
        rows.append({"quote": q, "customer": cust, "so": so,
                     "shipment": shipment, "invoice": invoice})
    return rows


@router.get("/sales", response_class=HTMLResponse)
def sales_pipeline(request: Request, user=Depends(_sales1),
                   session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "sales.html", {
        "user": user, "rows": _pipeline_rows(session), "can_finance": _can_finance(user),
    })


@router.post("/sales/quote")
def create_quote(customer: str = Form(...),
                 desc1: str = Form(""), qty1: float = Form(0), price1: float = Form(0),
                 desc2: str = Form(""), qty2: float = Form(0), price2: float = Form(0),
                 user=Depends(_sales2), session: Session = Depends(get_session)):
    c = next((x for x in sales.list_customers(session)
              if customer.strip().lower() in x.name.lower()), None)
    if c is None:
        c = sales.create_customer(session, name=customer.strip())
    lines = []
    for desc, qty, price in ((desc1, qty1, price1), (desc2, qty2, price2)):
        if desc.strip() and qty > 0:
            lines.append({"description": desc.strip(), "qty": qty, "unit_price": price})
    if lines:
        ful.create_quote(session, customer_id=c.id, lines=lines)
    return RedirectResponse("/sales", status_code=303)


@router.post("/sales/quote/{quote_id}/send")
def send_quote(quote_id: int, user=Depends(_sales2),
               session: Session = Depends(get_session)):
    ful.send_quote(session, quote_id)
    return RedirectResponse("/sales", status_code=303)


@router.post("/sales/quote/{quote_id}/accept")
def accept_quote(quote_id: int, customer_po: str = Form(...),
                 user=Depends(_sales2), session: Session = Depends(get_session)):
    ful.accept_quote(session, quote_id, customer_po=customer_po.strip() or "PO")
    return RedirectResponse("/sales", status_code=303)


@router.post("/sales/order/{so_id}/ship")
def ship_order(so_id: int, carrier: str = Form(""), tracking_no: str = Form(""),
               user=Depends(_sales2), session: Session = Depends(get_session)):
    ful.create_shipment(session, so_id=so_id, carrier=carrier.strip() or None,
                        tracking_no=tracking_no.strip() or None)
    return RedirectResponse("/sales", status_code=303)


@router.post("/sales/order/{so_id}/invoice")
def invoice_order(so_id: int, user=Depends(_finance3),
                  session: Session = Depends(get_session)):
    """Invoicing posts revenue to the ledger — finance L3, and a denial is an
    explicit 403 (it used to be silently swallowed, which hid the gate)."""
    ful.invoice_order(session, so_id)
    return RedirectResponse("/sales", status_code=303)


def _download(builder, session, obj_id):
    filename, data = builder(session, obj_id)
    return StreamingResponse(iter([data]), media_type=_XLSX,
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/sales/quote/{quote_id}/document")
def quote_doc(quote_id: int, user=Depends(_sales1),
              session: Session = Depends(get_session)):
    return _download(sdocs.build_quote_xlsx, session, quote_id)


@router.get("/sales/shipment/{shipment_id}/document")
def packing_doc(shipment_id: int, user=Depends(_sales1),
                session: Session = Depends(get_session)):
    return _download(sdocs.build_packing_list_xlsx, session, shipment_id)


@router.get("/sales/invoice/{invoice_id}/document")
def invoice_doc(invoice_id: int, user=Depends(_sales1),
                session: Session = Depends(get_session)):
    return _download(sdocs.build_invoice_xlsx, session, invoice_id)
