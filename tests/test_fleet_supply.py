"""📦 supply role: supplier packing list -> draft goods receipt (unposted) parked
in /fleet; approval posts stock + GR/IR and rolls the PO. Ambiguity always fails
to a human — the role never guesses which PO a delivery belongs to."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.ai.classify import routing_for
from app.modules.fleet import dispatcher as disp
from app.modules.fleet import loop, roles
from app.modules.fleet.models import Role, TaskSource, TaskStatus
from app.modules.inventory import service as inv
from app.modules.inventory.models import ProductType
from app.modules.procurement import service as proc
from app.modules.procurement.handlers import register_handlers
from app.modules.procurement.models import POStatus


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        register_handlers()
        yield s


@pytest.fixture
def open_po(session):
    product = inv.create_product(session, sku="W-1", name="Widget A",
                                 type=ProductType.INVENTORY)
    vendor = proc.create_vendor(session, name="Acme Supplies")
    po = proc.create_po_from_request(
        session, request_id=None,
        lines=[{"description": "Widget A", "qty": 10, "unit_price": 12,
                "product_id": product.id}],
    )
    proc.issue_po(session, po.id, vendor_id=vendor.id)
    return {"po": po, "vendor": vendor, "product": product}


def _delivery_task(session, **parsed):
    p = {"vendor_name": "Acme Supplies", "po_number": None,
         "lines": [{"description": "Widget A", "sku": None, "qty": 10}]}
    p.update(parsed)
    return disp.dispatch(
        session, category="packing_list", title="Acme delivery",
        source=TaskSource.UPLOAD, payload={"parsed": p}, source_ref="doc:7",
    )


def test_classify_routing_for_packing_list():
    assert routing_for("packing_list") == ("inventory", 2, "supply", False)


def test_dispatch_routes_to_supply(session, open_po):
    task = _delivery_task(session)
    assert task.to_role == Role.SUPPLY


def test_handle_drafts_unposted_inbound(session, open_po):
    task = _delivery_task(session, po_number=open_po["po"].po_no)
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.NEEDS_APPROVAL
    from app.modules.inventory.models import Inbound
    inb = session.get(Inbound, task.result["inbound_id"])
    assert inb.status == "draft"                      # nothing posted yet
    assert inv.get_stock(session, open_po["product"].id) is None  # stock untouched
    assert open_po["po"].lines[0].qty_received == 0
    assert task.result["po_no"] == open_po["po"].po_no


def test_approve_posts_stock_and_rolls_po(session, open_po):
    task = _delivery_task(session)  # no po_number -> single open Acme PO matches
    loop.run_once(session)
    roles.resolve(session, task, approved=True)

    session.refresh(task)
    assert task.status == TaskStatus.DONE
    bal = inv.get_stock(session, open_po["product"].id)
    assert str(bal.qty_on_hand) == "10.000"
    assert str(bal.avg_unit_cost) == "12.00"          # valued at the PO price
    assert open_po["po"].status == POStatus.RECEIVED
    assert open_po["po"].lines[0].qty_received == 10


def test_unknown_po_number_fails_to_human(session, open_po):
    task = _delivery_task(session, po_number="PO-9999-0001")
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.FAILED


def test_ambiguous_vendor_pos_fail_to_human(session, open_po):
    po2 = proc.create_po_from_request(
        session, request_id=None,
        lines=[{"description": "Widget A", "qty": 5, "unit_price": 12,
                "product_id": open_po["product"].id}],
    )
    proc.issue_po(session, po2.id, vendor_id=open_po["vendor"].id)
    task = _delivery_task(session)  # two open POs, no po_number
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.FAILED


def test_overshipment_fails_to_human(session, open_po):
    task = _delivery_task(session, po_number=open_po["po"].po_no,
                          lines=[{"description": "Widget A", "sku": None, "qty": 12}])
    loop.run_once(session)
    session.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert inv.get_stock(session, open_po["product"].id) is None
