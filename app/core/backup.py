"""Backup / restore (POLICIES §G13). Per-appliance, local.

run_backup() snapshots the database (SQLite = file copy; PostgreSQL = pg_dump)
into a timestamped file and prunes old ones. In production an APScheduler job
calls this nightly (wired at the server entrypoint, M15); the function itself is
synchronous and testable.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _prune(dest: Path, *, prefix: str, keep: int) -> list[Path]:
    backups = sorted(dest.glob(f"{prefix}*"), key=lambda p: p.name)
    removed = []
    while len(backups) > keep:
        old = backups.pop(0)
        old.unlink()
        removed.append(old)
    return removed


def run_backup(*, dest_dir: str | Path, database_url: str | None = None, keep: int = 7) -> Path:
    """Create one backup snapshot under dest_dir, prune to `keep` most recent.
    Returns the backup path."""
    url = database_url or settings.database_url
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()

    if url.startswith("sqlite"):
        # sqlite:///./dev.db  ->  ./dev.db
        src = Path(url.split("///", 1)[1]) if "///" in url else Path("dev.db")
        out = dest / f"erp_{stamp}.db"
        if src.exists():
            shutil.copy2(src, out)
        else:  # nothing to copy yet — still produce an (empty) marker
            out.touch()
    else:
        # PostgreSQL: pg_dump the database to a .sql file
        out = dest / f"erp_{stamp}.sql"
        with out.open("wb") as f:
            subprocess.run(["pg_dump", url], stdout=f, check=True)

    _prune(dest, prefix="erp_", keep=keep)
    return out
