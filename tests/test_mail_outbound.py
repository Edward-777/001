"""Outbound mail: maker-checker end to end — anything may draft, only a human
sends, the reference provider never leaves the machine (SENT_SIMULATED)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register ALL tables (FKs cross modules)
    accounting, ai, approval, assets, auth, bank, budget, contracts,
    documents, expense, fleet, hr, inventory, learning, leave, mail,
    notifications, procurement, sales,
)
from app.modules.auth import service as auth_svc
from app.modules.auth.models import Role as URole
from app.modules.mail import service as svc
from app.modules.mail.models import OutboundStatus
from app.modules.mail.provider import FilesystemMailbox


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def admin(session):
    return auth_svc.create_user(session, name="Adm", email="a@x", password="pw",
                                role=URole.ADMIN)


def test_draft_validates_inputs(session, admin):
    with pytest.raises(ValueError, match="not a valid email"):
        svc.draft_outbound(session, to_addr="nope", subject="s", body_text="b")
    with pytest.raises(ValueError, match="subject and body"):
        svc.draft_outbound(session, to_addr="v@acme.com", subject=" ",
                           body_text="b")


def test_draft_then_send_writes_simulated_eml(session, admin, tmp_path):
    box = FilesystemMailbox(tmp_path)
    row = svc.draft_outbound(session, to_addr="ap@acme.com",
                             subject="Invoice discrepancy INV-9",
                             body_text="Totals differ from PO-2026-0001.",
                             created_by=admin.id,
                             related_type="task", related_id=7)
    assert row.status == str(OutboundStatus.DRAFT)
    sent = svc.send_outbound(session, row.id, user_id=admin.id, provider=box)
    assert sent.status == str(OutboundStatus.SENT_SIMULATED)
    assert sent.approved_by == admin.id and sent.sent_at is not None
    content = (tmp_path / "outbox").glob("*.eml").__next__().read_text()
    assert "X-001-Status: SENT_SIMULATED" in content
    assert "Invoice discrepancy INV-9" in content


def test_send_is_single_shot_and_draft_only(session, admin, tmp_path):
    box = FilesystemMailbox(tmp_path)
    row = svc.draft_outbound(session, to_addr="v@acme.com", subject="s",
                             body_text="b")
    svc.send_outbound(session, row.id, user_id=admin.id, provider=box)
    with pytest.raises(ValueError, match="not a draft"):
        svc.send_outbound(session, row.id, user_id=admin.id, provider=box)
    canceled = svc.draft_outbound(session, to_addr="v@acme.com", subject="s2",
                                  body_text="b2")
    svc.cancel_outbound(session, canceled.id, user_id=admin.id)
    with pytest.raises(ValueError, match="not a draft"):
        svc.send_outbound(session, canceled.id, user_id=admin.id, provider=box)


def test_ai_tool_drafts_only_and_never_sends(session, admin):
    from app.modules.ai.registry import registry
    out = registry.execute("draft_outbound_email",
                           {"to": "ap@acme.com", "subject": "Payment delay",
                            "body": "We will confirm the schedule shortly."},
                           session=session, user=admin)["result"]
    assert out["status"] == "draft"
    assert "NOT sent" in out["note"]
    # and the registry offers no send tool at all — sending is human-only
    from app.modules.ai.registry import registry as reg
    assert "send_outbound_email" not in [
        t["function"]["name"] for t in reg.schemas_for(admin)]


def test_reply_threading_links_to_inbound(session, admin):
    from app.modules.mail.provider import parse_eml
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "jane@acme.com"
    msg["Message-ID"] = "<in1@acme.com>"
    msg["Subject"] = "Delivery delay"
    msg.set_content("The shipment slips a week.")
    inbound = svc.ingest(session, parse_eml(bytes(msg)))

    reply = svc.draft_outbound(session, to_addr="jane@acme.com",
                               subject="Re: Delivery delay",
                               body_text="Understood — please confirm the new ETA.",
                               reply_to_email_id=inbound.id)
    assert reply.reply_to_email_id == inbound.id
    with pytest.raises(ValueError, match="does not exist"):
        svc.draft_outbound(session, to_addr="j@a.com", subject="s",
                           body_text="b", reply_to_email_id=99999)
