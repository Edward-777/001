"""Chat vendor onboarding — create/update/attach-document tools over the
procurement + documents services. Master data, not money: no draft gate, but
dedupe-by-name and only-user-stated-fields keep the model honest."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import ai, auth, documents, procurement  # noqa: F401  register
from app.modules.ai.registry import registry
from app.modules.auth import service as auth_svc
from app.modules.auth.models import DataBoundary, Role, Scope
from app.modules.documents import service as docs
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def buyer(session):
    u = auth_svc.create_user(session, name="Buyer", email="b@x", password="pw")
    auth_svc.grant_scope(session, u, Scope.PROCUREMENT, 2, DataBoundary.ALL)
    session.flush()
    return u


def test_create_vendor_roundtrips_contact_fields(session, buyer):
    out = registry.execute("create_vendor",
                           {"name": "Dell Inc.", "email": "ar@dell.com",
                            "phone": "800-999-3355", "payment_terms": "net60"},
                           session=session, user=buyer)["result"]
    assert out["vendor_id"] and out["payment_terms"] == "net60"
    v = proc.get_vendor(session, out["vendor_id"])
    assert v.phone == "800-999-3355" and v.email == "ar@dell.com"


def test_create_vendor_dedupes_by_name(session, buyer):
    registry.execute("create_vendor", {"name": "Acme Supplies"},
                     session=session, user=buyer)
    out = registry.execute("create_vendor", {"name": "acme"},
                           session=session, user=buyer)["result"]
    assert "already exists" in out["error"]
    assert len(proc.list_vendors(session)) == 1


def test_update_vendor_whitelist(session, buyer):
    registry.execute("create_vendor", {"name": "Acme Supplies"},
                     session=session, user=buyer)
    out = registry.execute("update_vendor", {"vendor": "Acme", "email": "ap@acme.com"},
                           session=session, user=buyer)["result"]
    assert out["updated"] == ["email"]
    with pytest.raises(ValueError):
        proc.update_vendor(session, out["vendor_id"], is_active=False)  # not whitelisted


def test_attach_defaults_to_latest_unlinked_upload(session, buyer):
    vid = registry.execute("create_vendor", {"name": "Acme Supplies"},
                           session=session, user=buyer)["result"]["vendor_id"]
    docs.store_document(session, file_path="up/1.pdf", filename="old.pdf",
                        uploaded_by=buyer.id)
    d2 = docs.store_document(session, file_path="up/2.pdf", filename="w9.pdf",
                             uploaded_by=buyer.id)
    out = registry.execute("attach_document_to_vendor", {"vendor": "Acme"},
                           session=session, user=buyer)["result"]
    assert out["document_id"] == d2.id and out["filename"] == "w9.pdf"
    linked = docs.list_linked(session, "vendor", vid)
    assert [d.id for d in linked] == [d2.id]
    details = registry.execute("get_vendor_details", {"vendor": "Acme"},
                               session=session, user=buyer)["result"]
    assert details["documents"] == [{"document_id": d2.id, "filename": "w9.pdf"}]


def test_attach_with_no_upload_asks_for_file(session, buyer):
    registry.execute("create_vendor", {"name": "Acme Supplies"},
                     session=session, user=buyer)
    out = registry.execute("attach_document_to_vendor", {"vendor": "Acme"},
                           session=session, user=buyer)["result"]
    assert "upload the file first" in out["error"]


def test_vendor_tools_hidden_from_plain_employee(session, buyer):
    emp = auth_svc.create_user(session, name="Emp", email="e@x", password="pw")
    names = {t["function"]["name"] for t in registry.schemas_for(emp)}
    assert "create_vendor" not in names and "attach_document_to_vendor" not in names
    out = registry.execute("create_vendor", {"name": "Evil Corp"},
                           session=session, user=emp)
    assert "permission denied" in out["error"]
