"""True 3-way match: bill vs receipt vs PO (vendor + total within tolerance),
and the fleet spend role wiring the parsed po_number into it. An EXCEPTION
never posts — GL stays clean on any mismatch."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import loop, roles
from app.modules.fleet.models import TaskSource, TaskStatus
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        yield s


@pytest.fixture
def received_po(session):
    """Open PO for 10 W-1 @ $12 from Acme, fully received (value $120)."""
    product = inv.create_product(session, sku="W-1", name="Widget",
                                 type=ProductType.INVENTORY)
    vendor = proc.create_vendor(session, name="Acme Supplies")
    po = proc.create_po_from_request(
        session, request_id=None,
        lines=[{"description": "Widget", "qty": 10, "unit_price": 12,
                "product_id": product.id}],
    )
    proc.issue_po(session, po.id, vendor_id=vendor.id)
    inb = inv.create_inbound(session, po_id=po.id, lines=[
        {"product_id": product.id, "qty": 10, "unit_cost": 12,
         "po_line_id": po.lines[0].id}])
    inv.post_inbound(session, inb.id)
    return {"po": po, "vendor": vendor, "inbound": inb}


def _bill_for(session, fixture, *, amount_per_unit=12, vendor=None, with_po=True):
    inb = fixture["inbound"]
    lines = [{"inbound_line_id": ln.id, "description": "received goods",
              "qty": ln.qty_received, "unit_price": amount_per_unit}
             for ln in inb.lines]
    return acct.create_ap_bill(
        session, vendor_id=(vendor or fixture["vendor"]).id, lines=lines,
        po_id=fixture["po"].id if with_po else None,
    )


def test_clean_three_way_match_posts(session, received_po):
    bill = _bill_for(session, received_po)
    acct.match_ap_bill(session, bill.id)
    assert bill.match_status == "matched"
    assert bill.status == "open"
    assert received_po["po"].po_no in bill.match_note


def test_vendor_mismatch_is_exception(session, received_po):
    other = proc.create_vendor(session, name="Impostor LLC")
    bill = _bill_for(session, received_po, vendor=other)
    acct.match_ap_bill(session, bill.id)
    assert bill.match_status == "exception"
    assert "vendor" in bill.match_note


def test_bill_over_receipt_is_exception(session, received_po):
    bill = _bill_for(session, received_po, amount_per_unit=13)  # $130 vs received $120
    acct.match_ap_bill(session, bill.id)
    assert bill.match_status == "exception"
    assert "received" in bill.match_note  # the receipt leg catches it first


def _po_received_at(session, *, po_price=12, receipt_cost=12.5):
    """PO priced at po_price but goods received (and billed) at receipt_cost —
    the receipt leg holds; only the PO leg varies."""
    product = inv.create_product(session, sku="W-2", name="Widget2",
                                 type=ProductType.INVENTORY)
    vendor = proc.create_vendor(session, name="Beta Parts")
    po = proc.create_po_from_request(
        session, request_id=None,
        lines=[{"description": "Widget2", "qty": 10, "unit_price": po_price,
                "product_id": product.id}],
    )
    proc.issue_po(session, po.id, vendor_id=vendor.id)
    inb = inv.create_inbound(session, po_id=po.id, lines=[
        {"product_id": product.id, "qty": 10, "unit_cost": receipt_cost,
         "po_line_id": po.lines[0].id}])
    inv.post_inbound(session, inb.id)
    return {"po": po, "vendor": vendor, "inbound": inb}


def test_po_variance_within_tolerance_matches(session, monkeypatch):
    fx = _po_received_at(session)  # bill/receipt $125 vs PO $120 = +4.2%
    monkeypatch.setattr(settings, "ap_match_tolerance_pct", 10.0)
    bill = _bill_for(session, fx, amount_per_unit=12.5)
    acct.match_ap_bill(session, bill.id)
    assert bill.match_status == "matched"


def test_po_variance_beyond_tolerance_is_exception(session, monkeypatch):
    fx = _po_received_at(session)
    monkeypatch.setattr(settings, "ap_match_tolerance_pct", 0.0)
    bill = _bill_for(session, fx, amount_per_unit=12.5)
    acct.match_ap_bill(session, bill.id)
    assert bill.match_status == "exception"
    assert fx["po"].po_no in bill.match_note


def test_no_po_bill_stays_two_way(session, received_po):
    bill = _bill_for(session, received_po, with_po=False)
    acct.match_ap_bill(session, bill.id)
    assert bill.match_status == "matched"
    assert bill.match_note is None


def _invoice_task(session, **parsed):
    p = {"vendor_name": "Acme Supplies", "invoice_no": "ACM-9", "total": 120.00}
    p.update(parsed)
    return disp.dispatch(
        session, category="invoice", title="Acme bill", source=TaskSource.UPLOAD,
        payload={"goods_received": True, "parsed": p}, source_ref="doc:9",
    )


def test_spend_handle_links_parsed_po_and_match_posts_grir(session, received_po):
    task = _invoice_task(session, po_number=received_po["po"].po_no)
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL
    assert task.result["po_matched"] is True
    assert received_po["po"].po_no in task.result["note"]

    roles.resolve(session, task, approved=True)
    session.refresh(task)
    assert task.status == TaskStatus.DONE
    bill = acct.get_ap_bill(session, task.result["draft_bill_id"])
    assert bill.match_status == "matched" and bill.status == "open"


def test_spend_handle_flags_total_variance_not_matched(session, received_po):
    task = _invoice_task(session, po_number=received_po["po"].po_no, total=150.00)
    loop.run_once(session)
    session.refresh(task)
    assert task.result["po_matched"] is False
    assert "variance" in task.result["note"]


def test_spend_handle_notes_unknown_po(session, received_po):
    task = _invoice_task(session, po_number="PO-9999-0001")
    loop.run_once(session)
    session.refresh(task)
    assert "no such PO" in task.result["note"]
    assert task.result["po_matched"] is False
