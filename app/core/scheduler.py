"""Background scheduler — nightly backup (POLICIES §G13).

Off by default (settings.enable_scheduler=False) so tests/dev don't spawn a
thread; the production server sets ENABLE_SCHEDULER=true. apscheduler is imported
lazily so it's only required when actually enabled.
"""
from __future__ import annotations

from .backup import run_backup
from .config import settings

_scheduler = None


def _in_session(fn) -> None:
    """Run fn(session) in its own committed session, swallowing errors so a bad
    tick never crashes the scheduler thread."""
    from .db import SessionLocal

    session = SessionLocal()
    try:
        fn(session)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def _fleet_tick() -> None:
    """One pass of the fleet work loop (AGENT-FLEET §3)."""
    from ..modules.fleet import loop

    _in_session(loop.run_once)


def _payment_run_tick() -> None:
    """Build the weekly vendor-payment proposal (AGENT-FLEET §4)."""
    from ..modules.fleet import payment_run

    _in_session(payment_run.enqueue_weekly_payment_run)


def _anomaly_tick() -> None:
    """Daily anomaly scan -> alert in the founder's inbox (AGENT-FLEET §2)."""
    from ..modules.fleet import alerts

    _in_session(alerts.enqueue_anomaly_alerts)


def _month_close_tick() -> None:
    """Monthly: propose closing the previous month (AGENT-FLEET §4)."""
    from ..modules.fleet import month_close

    _in_session(month_close.enqueue_month_close)


def _renewal_tick() -> None:
    """Daily: contracts entering their notice window -> founder inbox card."""
    from ..modules.fleet import alerts

    _in_session(alerts.enqueue_renewal_alerts)


def _budget_tick() -> None:
    """Daily: expense accounts over their monthly budget -> founder inbox card."""
    from ..modules.fleet import alerts

    _in_session(alerts.enqueue_budget_alerts)


def _obligation_tick() -> None:
    """Daily: compliance deadlines entering their notice window -> inbox card."""
    from ..modules.fleet import alerts

    _in_session(alerts.enqueue_obligation_alerts)


def _mail_tick() -> None:
    """Every few minutes: poll the mailbox and ingest new messages."""
    from ..modules.mail import service as mail

    _in_session(mail.poll_and_ingest)


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    sch = BackgroundScheduler()
    sch.add_job(
        lambda: run_backup(dest_dir=settings.backup_dir),
        trigger="cron", hour=2, minute=0, id="nightly_backup",
    )
    # The single fleet work loop: drains the task queue every N minutes.
    sch.add_job(
        _fleet_tick, trigger="interval",
        minutes=settings.fleet_loop_minutes, id="fleet_loop",
    )
    # Weekly vendor-payment proposal — Monday 08:00.
    sch.add_job(
        _payment_run_tick, trigger="cron", day_of_week="mon", hour=8, minute=0,
        id="payment_run",
    )
    # Daily anomaly scan — 07:00.
    sch.add_job(_anomaly_tick, trigger="cron", hour=7, minute=0, id="anomaly_scan")
    # Daily contract-renewal check — 07:10 (idempotent per week per due-set).
    sch.add_job(_renewal_tick, trigger="cron", hour=7, minute=10, id="renewal_scan")
    # Daily budget-overrun check — 07:20 (idempotent per month per over-set).
    sch.add_job(_budget_tick, trigger="cron", hour=7, minute=20, id="budget_scan")
    # Daily compliance-deadline check — 07:15 (idempotent per week per due-set).
    sch.add_job(_obligation_tick, trigger="cron", hour=7, minute=15,
                id="obligation_scan")
    # Mailbox poll — email is an intake surface, so it runs like the fleet loop.
    if settings.mail_enabled:
        sch.add_job(_mail_tick, trigger="interval",
                    minutes=settings.mail_poll_minutes, id="mail_poll")
    # Monthly close proposal — 1st of the month, 06:00 (closes the prior month).
    sch.add_job(_month_close_tick, trigger="cron", day=1, hour=6, minute=0, id="month_close")
    sch.start()
    _scheduler = sch
    return sch
