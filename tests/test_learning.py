"""Governed learning loop (ADR-10): duplicate-vendor resolutions are mined into
rule PROPOSALS in the approval inbox; approval activates the rule; the system's
behavior measurably changes on the next occurrence; rejection is remembered."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Base
from app.modules import (  # noqa: F401  register all tables
    accounting, approval, assets, auth, bank, documents, expense,
    fleet, hr, inventory, learning, notifications, procurement, sales,
)
from app.modules.accounting import service as acct
from app.modules.fleet import loop, miner, roles
from app.modules.fleet import service as q
from app.modules.fleet.models import Role, TaskStatus
from app.modules.learning import service as learn
from app.modules.procurement import service as proc


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        acct.seed_coa(s)
        acct.seed_posting_rules(s)
        yield s


def test_normalize_strips_punctuation_and_legal_suffixes():
    n = learn.normalize_vendor_name
    assert n("Office Depot, Inc.") == "office depot"
    assert n("OFFICE DEPOT") == "office depot"
    assert n("Acme LLC") == "acme"
    assert n("Dell Inc.") == "dell"
    assert n("Beta Parts") == "beta parts"          # no false stripping
    assert n("The Company Co.") == "the"            # suffixes strip right-to-left


def test_miner_proposes_alias_for_duplicate_vendors(session):
    proc.create_vendor(session, name="Office Depot")
    proc.create_vendor(session, name="Office Depot, Inc.")  # fleet-style duplicate
    proc.create_vendor(session, name="Dell Inc.")           # unique — no proposal

    assert miner.mine(session) == 1
    tasks = q.list_tasks(session, to_role=Role.INSIGHT)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.status == TaskStatus.NEEDS_APPROVAL
    assert task.category == "learned_rule"
    assert "Office Depot, Inc." in task.title
    assert task.result["params"]["alias_normalized"] == "office depot"
    # idempotent: re-mining proposes nothing new
    assert miner.mine(session) == 0


def test_approval_activates_rule_and_changes_behavior(session):
    canonical = proc.create_vendor(session, name="Office Depot")
    dup = proc.create_vendor(session, name="Office Depot, Inc.")
    miner.mine(session)
    task = q.list_tasks(session, to_role=Role.INSIGHT)[0]

    roles.resolve(session, task, approved=True)

    # rule active, duplicate deactivated
    rules = learn.active_rules(session, kind="vendor_alias")
    assert len(rules) == 1 and rules[0].applied_count == 0
    assert proc.get_vendor(session, dup.id).is_active is False

    # THE BEHAVIOR CHANGE: the parsed name now resolves to the canonical vendor
    resolved = proc.resolve_vendor(session, "Office Depot, Inc.")
    assert resolved.id == canonical.id
    assert learn.active_rules(session, kind="vendor_alias")[0].applied_count == 1


def test_rejection_is_remembered_and_never_reproposed(session):
    proc.create_vendor(session, name="Office Depot")
    proc.create_vendor(session, name="Office Depot, Inc.")
    miner.mine(session)
    task = q.list_tasks(session, to_role=Role.INSIGHT)[0]

    roles.resolve(session, task, approved=False)

    assert learn.active_rules(session) == []
    assert proc.resolve_vendor(session, "Office Depot, Inc.").name == "Office Depot, Inc."
    assert miner.mine(session) == 0  # the human said no — do not ask again


def test_spend_handle_uses_learned_alias_no_more_duplicates(session):
    """The original incident, closed: an invoice naming the duplicate spelling no
    longer creates a new vendor once the learned rule is active."""
    from app.modules.fleet import dispatcher as disp
    from app.modules.fleet.models import TaskSource

    canonical = proc.create_vendor(session, name="Office Depot")
    proc.create_vendor(session, name="Office Depot, Inc.")
    miner.mine(session)
    roles.resolve(session, q.list_tasks(session, to_role=Role.INSIGHT)[0], approved=True)

    invoice_task = disp.dispatch(
        session, category="invoice", title="OD bill", source=TaskSource.UPLOAD,
        payload={"goods_received": True,
                 "parsed": {"vendor_name": "Office Depot, Inc.",
                            "invoice_no": "OD-1", "total": 100.0}},
        source_ref="doc:42",
    )
    loop.run_once(session)
    session.refresh(invoice_task)
    assert invoice_task.result["vendor_id"] == canonical.id
    assert invoice_task.result["new_vendor"] is False
    assert len([v for v in proc.list_vendors(session)]) == 1  # still only Office Depot


def test_loop_runs_miner_automatically(session):
    proc.create_vendor(session, name="Acme Supplies")
    proc.create_vendor(session, name="Acme Supplies LLC")
    loop.run_once(session)  # miner runs as the loop's producer
    tasks = [t for t in q.list_tasks(session, to_role=Role.INSIGHT)
             if t.category == "learned_rule"]
    assert len(tasks) == 1 and tasks[0].status == TaskStatus.NEEDS_APPROVAL
