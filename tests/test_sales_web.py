"""Order-to-cash pipeline over HTTP (docs/AGENT-FLEET.md §1)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role
from app.modules.sales.models import ARInvoice, Quote, Shipment


@pytest.fixture
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    from app.wiring import register_all_handlers
    register_all_handlers(force=True)
    with TestSession() as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        auth_svc.create_user(s, name="CEO", email="ceo@x", password="pw", role=Role.ADMIN)
        s.commit()

    def override():
        s = TestSession()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    app.dependency_overrides[get_session] = override
    yield TestClient(app, follow_redirects=False), TestSession
    app.dependency_overrides.clear()


def _login(client):
    client.post("/login", data={"email": "ceo@x", "password": "pw"})


def test_o2c_flow_end_to_end_over_http(ctx):
    client, TestSession = ctx
    _login(client)

    # 1. create a quote
    client.post("/sales/quote", data={
        "customer": "BigCo Inc", "desc1": "Widget Pro", "qty1": 10, "price1": 1500,
        "desc2": "Setup", "qty2": 1, "price2": 2000})
    with TestSession() as s:
        q = s.scalars(select(Quote)).first()
        assert q is not None and str(q.total) == "17000.00"
        qid = q.id

    # quote document downloads
    r = client.get(f"/sales/quote/{qid}/document")
    assert r.status_code == 200 and "Quote_" in r.headers["content-disposition"]

    # 2. send -> 3. receive PO (accept) -> order
    client.post(f"/sales/quote/{qid}/send")
    client.post(f"/sales/quote/{qid}/accept", data={"customer_po": "PO-555"})
    with TestSession() as s:
        q = s.get(Quote, qid)
        assert q.status == "accepted" and q.so_id is not None
        so_id = q.so_id

    # 4. ship -> packing list exists
    client.post(f"/sales/order/{so_id}/ship", data={"carrier": "FedEx", "tracking_no": "FX9"})
    with TestSession() as s:
        sh = s.scalars(select(Shipment).where(Shipment.so_id == so_id)).first()
        assert sh is not None
        r = client.get(f"/sales/shipment/{sh.id}/document")
        assert r.status_code == 200 and "PackingList_" in r.headers["content-disposition"]

    # 5. invoice -> AR invoice posted, document downloads
    client.post(f"/sales/order/{so_id}/invoice")
    with TestSession() as s:
        inv = s.scalars(select(ARInvoice).where(ARInvoice.so_id == so_id)).first()
        assert inv is not None and str(inv.total) == "17000.00"
        r = client.get(f"/sales/invoice/{inv.id}/document")
        assert r.status_code == 200 and "Invoice_" in r.headers["content-disposition"]
        # revenue recognized on the ledger
        from datetime import date
        tb = acct.trial_balance(s, as_of=date.today())
        by_code = {row["code"]: row for row in tb["rows"]}
        assert str(by_code["4000"]["credit"]) == "17000.00"


def test_sales_page_renders(ctx):
    client, _ = ctx
    _login(client)
    r = client.get("/sales")
    assert r.status_code == 200 and "Order to Cash" in r.text
