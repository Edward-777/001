"""procurement.service — vendor master (M3) + purchase orders (M6)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.money import CENTS as _CENTS
from ...core.money import current_year
from ...core.sequences import next_number
from .models import PaymentTerms, POLine, POStatus, PurchaseOrder, Vendor


def create_vendor(
    session: Session,
    *,
    name: str,
    payment_terms: PaymentTerms = PaymentTerms.NET30,
    tax_id: str | None = None,
    is_1099: bool = False,
    email: str | None = None,
) -> Vendor:
    v = Vendor(
        name=name,
        payment_terms=str(payment_terms),
        tax_id=tax_id,
        is_1099=is_1099,
        email=email,
    )
    session.add(v)
    session.flush()
    return v


def get_vendor(session: Session, vendor_id: int) -> Vendor | None:
    return session.get(Vendor, vendor_id)


def list_vendors(session: Session, *, active_only: bool = True) -> list[Vendor]:
    stmt = select(Vendor)
    if active_only:
        stmt = stmt.where(Vendor.is_active.is_(True))
    return list(session.scalars(stmt))


# ---- purchase orders (M6) ----------------------------------------------



def create_po_from_request(
    session: Session, *, request_id: int, lines: list[dict]
) -> PurchaseOrder:
    """Auto-create a DRAFT PO from an approved purchase request's line snapshot.
    Vendor is assigned later via issue_po (approval authorizes the spend; procurement
    places the actual order)."""
    po = PurchaseOrder(
        po_no=next_number(session, "PO", current_year()),
        request_id=request_id,
        status=str(POStatus.DRAFT),
    )
    session.add(po)
    session.flush()

    subtotal = Decimal("0")
    for ln in lines:
        qty = Decimal(str(ln.get("qty", 0)))
        price = Decimal(str(ln.get("unit_price", 0)))
        amount = (qty * price).quantize(_CENTS)
        subtotal += amount
        session.add(
            POLine(
                po_id=po.id,
                product_id=ln.get("product_id"),
                description=ln.get("description"),
                qty_ordered=qty,
                qty_received=Decimal("0"),
                unit_price=price,
                amount=amount,
            )
        )
    po.subtotal = subtotal
    po.tax = Decimal("0")
    po.total = subtotal
    session.flush()
    return po


def issue_po(
    session: Session,
    po_id: int,
    *,
    vendor_id: int,
    order_date: date | None = None,
    expected_date: date | None = None,
) -> PurchaseOrder:
    """Assign a vendor and move the PO from draft -> open (ready to receive)."""
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise ValueError("PO not found")
    if po.status != POStatus.DRAFT:
        raise ValueError(f"can only issue a draft PO (is {po.status})")
    po.vendor_id = vendor_id
    po.order_date = order_date or date.today()
    po.expected_date = expected_date
    po.status = str(POStatus.OPEN)
    session.flush()
    return po


def get_po(session: Session, po_id: int) -> PurchaseOrder | None:
    return session.get(PurchaseOrder, po_id)


def list_pos(session: Session, *, status: POStatus | None = None) -> list[PurchaseOrder]:
    stmt = select(PurchaseOrder)
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == str(status))
    return list(session.scalars(stmt))
