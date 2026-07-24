"""Receive against a PO — qty_received rolls up event-driven, over-receipt is
rejected, and the unit cost defaults to the humanly-approved PO price."""
import pytest
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register tables + tools + handlers
    accounting, ai, approval, auth, hr, inventory, notifications, procurement,
)
from app.modules.ai.registry import registry
from app.modules.approval import service as appr
from app.modules.approval.models import RequestType
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Scope
from app.modules.hr import service as hr_svc
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
        appr.seed_approval_rules(s)
        register_handlers()
        s.flush()
        yield s


@pytest.fixture
def org(session):
    people = {}
    parent = None
    for name in ["mgr", "staff"]:
        u = auth_svc.create_user(session, name=name, email=f"{name}@001.local", password="pw")
        session.flush()
        e = hr_svc.create_employee(
            session, employee_no=name.upper(), name=name,
            reports_to_id=parent.id if parent else None, user_id=u.id,
        )
        people[name] = dict(user=u, emp=e)
        parent = e
    auth_svc.grant_scope(session, people["mgr"]["user"], Scope.PROCUREMENT, 2, DataBoundary.ALL)
    auth_svc.grant_scope(session, people["mgr"]["user"], Scope.INVENTORY, 2, DataBoundary.ALL)
    session.flush()
    return people


@pytest.fixture
def open_po(session, org):
    """An issued PO for 10 WIDGET-A @ $12."""
    product = inv.create_product(session, sku="WIDGET-A", name="Widget A",
                                 type=ProductType.INVENTORY)
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="Widgets", lines=[{"description": "Widget A", "qty": 10,
                                 "unit_price": 12, "product_id": product.id}],
    )
    appr.submit_request(session, req.id)
    appr.approve(session, req.id, org["mgr"]["user"].id)
    po = proc.get_po_for_request(session, req.id)
    vendor = proc.create_vendor(session, name="Acme")
    proc.issue_po(session, po.id, vendor_id=vendor.id)
    return po


def _receive(session, org, **kw):
    return registry.execute("receive_inventory", kw, session=session,
                            user=org["mgr"]["user"])["result"]


def test_receive_against_po_rolls_status_and_qty(session, org, open_po):
    out = _receive(session, org, po_no=open_po.po_no, qty=4)
    assert out["po_status"] == str(POStatus.PARTIALLY_RECEIVED)
    assert out["unit_cost"] == "12.0"  # defaulted from the PO line, not invented
    assert open_po.lines[0].qty_received == 4

    out = _receive(session, org, po_no=open_po.po_no, qty=6)
    assert out["po_status"] == str(POStatus.RECEIVED)
    assert out["remaining_on_line"].startswith("0")


def test_over_receipt_rejected_with_remaining(session, org, open_po):
    _receive(session, org, po_no=open_po.po_no, qty=4)
    out = _receive(session, org, po_no=open_po.po_no, qty=7)
    assert "over-receipt" in out["error"] and "6" in out["error"]
    assert open_po.lines[0].qty_received == 4  # nothing posted


def test_receive_against_draft_po_rejected(session, org):
    inv.create_product(session, sku="W2", name="W2", type=ProductType.INVENTORY)
    req = appr.create_request(
        session, type=RequestType.PURCHASE, requester_id=org["staff"]["user"].id,
        title="W2", lines=[{"description": "W2", "qty": 1, "unit_price": 5}],
    )
    appr.submit_request(session, req.id)
    appr.approve(session, req.id, org["mgr"]["user"].id)
    po = proc.get_po_for_request(session, req.id)
    out = _receive(session, org, po_no=po.po_no, qty=1)
    assert "issue it to a vendor first" in out["error"]


def test_adhoc_receipt_without_po_unchanged(session, org):
    inv.create_product(session, sku="ADHOC", name="Adhoc", type=ProductType.INVENTORY)
    out = _receive(session, org, sku="ADHOC", qty=3, unit_cost=7)
    assert out["inbound_no"].startswith("INB-")
    assert "po_no" not in out
    out2 = _receive(session, org, sku="ADHOC", qty=3)  # no cost, no PO -> must ask
    assert "unit_cost" in out2["error"]


def test_single_open_line_resolves_without_sku(session, org, open_po):
    out = _receive(session, org, po_no=open_po.po_no, qty=2)
    assert out["sku"] == "WIDGET-A"
    assert out["po_no"] == open_po.po_no
