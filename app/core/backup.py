"""Backup / restore (POLICIES §G13). Per-appliance, local.

run_backup() snapshots the database (SQLite = file copy; PostgreSQL = pg_dump)
+ the uploads/ folder, verifies the snapshot, and applies tiered retention
(keep N daily, M weekly, K monthly). Production calls it nightly via APScheduler
(M15); the function itself is synchronous and testable.

Security: the Postgres password is passed via the PGPASSWORD env var, never on
the pg_dump command line (which is visible in `ps`).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .config import settings

_PREFIX = "erp_"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _verify_sqlite(path: Path) -> bool:
    try:
        with sqlite3.connect(path) as con:
            return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.DatabaseError:
        return False


def _dump_postgres(url: str, out: Path) -> None:
    p = urlparse(url.replace("postgresql+psycopg2", "postgresql"))
    env = dict(os.environ)
    if p.password:
        env["PGPASSWORD"] = p.password  # keep the password OUT of argv
    cmd = ["pg_dump", "--no-password", "-h", p.hostname or "localhost",
           "-p", str(p.port or 5432), "-U", p.username or "postgres",
           (p.path or "/").lstrip("/")]
    with out.open("wb") as f:
        subprocess.run(cmd, stdout=f, env=env, check=True)


def _stamp_of(p: Path) -> str:
    return p.name[len(_PREFIX):len(_PREFIX) + 15]  # erp_YYYYMMDD_HHMMSS...


def _prune_tiered(dest: Path, *, daily: int, weekly: int, monthly: int) -> list[Path]:
    """Keep the most recent `daily` DB backups, plus one per ISO-week for `weekly`
    weeks, plus one per month for `monthly` months. Delete the rest. The paired
    `_uploads.zip` archives are tiered ALONGSIDE the DB backups (same stamps kept),
    never counted against the DB quota."""
    db_backups = sorted(
        (p for p in dest.glob(f"{_PREFIX}*") if "_uploads" not in p.name),
        key=lambda p: p.name, reverse=True,
    )
    keep: set[Path] = set(db_backups[:daily])

    def _dt(p: Path) -> datetime:
        return datetime.strptime(_stamp_of(p), "%Y%m%d_%H%M%S")

    seen_weeks: set = set()
    seen_months: set = set()
    for p in db_backups:
        try:
            d = _dt(p)
        except ValueError:
            continue
        wk = d.isocalendar()[:2]
        if len(seen_weeks) < weekly and wk not in seen_weeks:
            seen_weeks.add(wk)
            keep.add(p)
        mo = (d.year, d.month)
        if len(seen_months) < monthly and mo not in seen_months:
            seen_months.add(mo)
            keep.add(p)

    removed = []
    for p in db_backups:
        if p not in keep:
            p.unlink()
            removed.append(p)
    # prune upload archives whose DB backup was pruned (keep them in parallel)
    kept_stamps = {_stamp_of(p) for p in keep}
    for z in dest.glob(f"{_PREFIX}*_uploads.zip"):
        if _stamp_of(z) not in kept_stamps:
            z.unlink()
            removed.append(z)
    return removed


def run_backup(
    *, dest_dir: str | Path, database_url: str | None = None,
    daily: int = 7, weekly: int = 4, monthly: int = 12,
) -> Path:
    """Create one verified backup snapshot under dest_dir and apply tiered
    retention. Returns the backup path. Raises if the snapshot fails verification."""
    url = database_url or settings.database_url
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()

    if url.startswith("sqlite"):
        src = Path(url.split("///", 1)[1]) if "///" in url else Path("dev.db")
        out = dest / f"{_PREFIX}{stamp}.db"
        if src.exists():
            # Use the sqlite backup API for a consistent copy of a live DB.
            with sqlite3.connect(src) as s, sqlite3.connect(out) as d:
                s.backup(d)
            if not _verify_sqlite(out):
                out.unlink(missing_ok=True)
                raise RuntimeError("backup failed integrity_check")
        else:
            out.touch()
    else:
        out = dest / f"{_PREFIX}{stamp}.sql"
        _dump_postgres(url, out)
        if out.stat().st_size == 0:
            out.unlink(missing_ok=True)
            raise RuntimeError("pg_dump produced an empty file")

    # Back up uploaded files (invoices/receipts/statements) alongside the DB.
    uploads = Path("uploads")
    if uploads.exists():
        shutil.make_archive(str(dest / f"{_PREFIX}{stamp}_uploads"), "zip", uploads)

    _prune_tiered(dest, daily=daily, weekly=weekly, monthly=monthly)
    return out
