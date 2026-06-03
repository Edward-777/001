"""Background scheduler — nightly backup (POLICIES §G13).

Off by default (settings.enable_scheduler=False) so tests/dev don't spawn a
thread; the production server sets ENABLE_SCHEDULER=true. apscheduler is imported
lazily so it's only required when actually enabled.
"""
from __future__ import annotations

from .backup import run_backup
from .config import settings

_scheduler = None


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
    sch.start()
    _scheduler = sch
    return sch
