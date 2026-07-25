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
    phone: str | None = None,
    address: str | None = None,
) -> Vendor:
    v = Vendor(
        name=name,
        payment_terms=str(payment_terms),
        tax_id=tax_id,
        is_1099=is_1099,
        email=email,
        phone=phone,
        address=address,
    )
    session.add(v)
    session.flush()
    return v


_VENDOR_UPDATABLE = {"name", "email", "phone", "address", "tax_id", "payment_terms", "is_1099"}


def update_vendor(session: Session, vendor_id: int, **fields) -> Vendor:
    """Update vendor master data (whitelisted fields only)."""
    v = session.get(Vendor, vendor_id)
    if v is None:
        raise ValueError("vendor not found")
    for key, value in fields.items():
        if key not in _VENDOR_UPDATABLE:
            raise ValueError(f"field not updatable: {key}")
        if value is not None:
            setattr(v, key, str(value) if key == "payment_terms" else value)
    session.flush()
    return v


def deactivate_vendor(session: Session, vendor_id: int) -> Vendor:
    v = session.get(Vendor, vendor_id)
    if v is None:
        raise ValueError("vendor not found")
    v.is_active = False
    session.flush()
    return v


def get_vendor(session: Session, vendor_id: int) -> Vendor | None:
    return session.get(Vendor, vendor_id)


def list_vendors(session: Session, *, active_only: bool = True) -> list[Vendor]:
    stmt = select(Vendor)
    if active_only:
        stmt = stmt.where(Vendor.is_active.is_(True))
    return list(session.scalars(stmt))


def find_vendor_by_name(session: Session, name: str) -> Vendor | None:
    """Case-insensitive name lookup so the AI can resolve 'Acme' to a vendor.
    Only active vendors — a deactivated duplicate must never win a match."""
    return session.scalar(
        select(Vendor).where(Vendor.name.ilike(f"%{name}%"),
                             Vendor.is_active.is_(True))
    )


def resolve_vendor(session: Session, name: str) -> Vendor | None:
    """Name → vendor, with learned aliases: direct match first, then any active
    human-approved vendor_alias rule ('Office Depot, Inc.' → 'Office Depot').
    The application is counted on the rule — the learning loop's payoff metric."""
    vendor = find_vendor_by_name(session, name)
    if vendor is not None:
        return vendor
    from ..learning import service as learn

    canonical_id = learn.resolve_vendor_alias(session, name)
    return get_vendor(session, canonical_id) if canonical_id else None


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


def get_po_by_no(session: Session, po_no: str) -> PurchaseOrder | None:
    return session.scalar(
        select(PurchaseOrder).where(PurchaseOrder.po_no == po_no.strip().upper())
    )


def get_po_for_request(session: Session, request_id: int) -> PurchaseOrder | None:
    return session.scalar(
        select(PurchaseOrder).where(PurchaseOrder.request_id == request_id)
    )


def list_pos(session: Session, *, status: POStatus | None = None) -> list[PurchaseOrder]:
    stmt = select(PurchaseOrder)
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == str(status))
    return list(session.scalars(stmt))


def cancel_po(session: Session, po_id: int) -> PurchaseOrder:
    """Cancel a PO nothing has been received against (draft or open only)."""
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise ValueError("PO not found")
    if po.status not in (str(POStatus.DRAFT), str(POStatus.OPEN)):
        raise ValueError(f"cannot cancel a {po.status} PO")
    if any(ln.qty_received > 0 for ln in po.lines):
        raise ValueError("cannot cancel — goods were already received against this PO")
    po.status = str(POStatus.CANCELED)
    session.flush()
    return po


def close_po(session: Session, po_id: int) -> PurchaseOrder:
    """Close a fully received PO."""
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise ValueError("PO not found")
    if po.status != str(POStatus.RECEIVED):
        raise ValueError(f"can only close a fully received PO (is {po.status})")
    po.status = str(POStatus.CLOSED)
    session.flush()
    return po


def validate_receipt_against_po(po: PurchaseOrder, allocations: list[dict]) -> list[str]:
    """Reject over-receipts BEFORE anything posts. allocations: [{po_line_id, qty}].
    Genuine overshipments are received ad hoc (without a PO) — a deliberate escape
    hatch so an AI-typed quantity can never silently overrun the ordered amount."""
    errors: list[str] = []
    by_id = {ln.id: ln for ln in po.lines}
    for alloc in allocations:
        ln = by_id.get(alloc.get("po_line_id"))
        if ln is None:
            errors.append(f"line {alloc.get('po_line_id')} is not on {po.po_no}")
            continue
        remaining = Decimal(str(ln.qty_ordered)) - Decimal(str(ln.qty_received))
        if Decimal(str(alloc.get("qty", 0))) > remaining:
            errors.append(
                f"over-receipt on '{ln.description}': {alloc.get('qty')} exceeds the "
                f"remaining {remaining} of {ln.qty_ordered} ordered"
            )
    return errors


def apply_receipt(session: Session, *, po_id: int, receipts: list[dict]) -> PurchaseOrder:
    """Roll received quantities into the PO and advance its status. Driven by the
    InboundPosted event so every receiving path (chat, web, fleet) behaves alike."""
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise ValueError("PO not found")
    by_id = {ln.id: ln for ln in po.lines}
    for r in receipts:
        ln = by_id.get(r.get("po_line_id"))
        if ln is None:
            continue
        ln.qty_received = Decimal(str(ln.qty_received)) + Decimal(str(r["qty"]))
    if all(Decimal(str(ln.qty_received)) >= Decimal(str(ln.qty_ordered)) for ln in po.lines):
        po.status = str(POStatus.RECEIVED)
    elif any(Decimal(str(ln.qty_received)) > 0 for ln in po.lines):
        po.status = str(POStatus.PARTIALLY_RECEIVED)
    session.flush()
    return po


def deliver_po(session: Session, po_id: int) -> dict:
    """How an issued PO reaches the vendor. Today: a downloadable document the
    user sends themselves; at launch an email branch slots in HERE so no tool
    or route has to change."""
    po = session.get(PurchaseOrder, po_id)
    if po is None:
        raise ValueError("PO not found")
    vendor = session.get(Vendor, po.vendor_id) if po.vendor_id else None
    return {
        "method": "download",
        "download_url": f"/po/{po.id}/document",
        "vendor_email": vendor.email if vendor else None,
    }
