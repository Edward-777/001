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
    sch.start()
    _scheduler = sch
    return sch
