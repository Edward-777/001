"""Background scheduler — nightly backup (POLICIES §G13).

Off by default (settings.enable_scheduler=False) so tests/dev don't spawn a
thread; the production server sets ENABLE_SCHEDULER=true. apscheduler is imported
lazily so it's only required when actually enabled.
"""
from __future__ import annotations

from .backup import run_backup
from .config import settings

_scheduler = None


def _fleet_tick() -> None:
    """One pass of the fleet work loop in its own session (AGENT-FLEET §3)."""
    from .db import SessionLocal
    from ..modules.fleet import loop

    session = SessionLocal()
    try:
        loop.run_once(session)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


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
    sch.start()
    _scheduler = sch
    return sch
