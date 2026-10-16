# -*- coding: utf-8 -*-
"""One place that gets the order of a production write right.

The order is the whole point and it is easy to get subtly wrong: a script that
calls ``ensure_faculty_jobs_tables`` to open the database has already migrated
it before the backup runs, so the backup is of the post-migration file and the
pre-migration state is gone. That happened here twice -- once via a --dry-run
that only meant to report, once in a write path whose author (me) believed the
read-only fix had covered it.

The sequence, in order:

  1. open read-only and check integrity -- never touch a database that is
     already damaged;
  2. inventory every preserved and private table, discovered from the schema
     rather than from a hand-written list that silently omits a table;
  3. back up to a unique, non-overwritable file with a manifest recording
     DB/WAL/SHM state and a SHA-256;
  4. only then migrate and write;
  5. re-check integrity, and fail loudly if any preserved or private table lost
     rows.
"""

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

# Tables whose rows are evidence and must never shrink through a repair.
PRESERVED_TABLES = (
    "jobs", "source_job_records", "job_sources", "sources", "ingestion_runs",
    "job_field_provenance", "job_status_history", "possible_duplicates",
    "faculty_job_repair_audit", "aacsb_directory_schools", "aacsb_scan_history",
    "aacsb_job_source_partitions", "job_detail_fetches", "source_record_decisions",
)

# Anything the user typed or saved. Discovered as well as listed: a private
# table added later must not be missed because the constant was not updated,
# which is exactly how user_job_state went unreported as "private state: 0".
PRIVATE_TABLE_HINTS = ("user_", "saved_", "application", "profile", "personal", "note")


class FacultyJobsWriteGuardRequired(RuntimeError):
    """Raised when a production writer bypasses the backup/postflight guard."""


_WRITE_GUARD_STATE = threading.local()


def write_guard_active():
    return bool(getattr(_WRITE_GUARD_STATE, "active", False))


@contextmanager
def guarded_write():
    """Mark a write as being inside its preflight/backup/postflight wrapper."""
    previous = write_guard_active()
    _WRITE_GUARD_STATE.active = True
    try:
        yield
    finally:
        _WRITE_GUARD_STATE.active = previous


def discover_private_tables(conn):
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return tuple(sorted(
        name for name in names
        if any(hint in name.casefold() for hint in PRIVATE_TABLE_HINTS)
    ))


def open_read_only(db_path):
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def check_integrity(conn, label, echo=print):
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    echo(f"{label}: quick_check={quick} foreign_key_violations={len(violations)}")
    if quick != "ok" or violations:
        raise SystemExit(f"{label} integrity check failed; nothing was written")
    return quick


def table_counts(conn, tables):
    counts = {}
    for table in tables:
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            counts[table] = None
    return counts


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar(db_path, suffix):
    path = Path(str(db_path) + suffix)
    if not path.exists():
        return None
    stat = path.stat()
    return {"bytes": stat.st_size, "mtime": datetime.fromtimestamp(
        stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}


# Where guarded backups land.
#
# Every guarded write copies the whole database first and never overwrites an
# earlier copy, which is the right rule and also means the directory only
# grows: one busy day produced 71 copies and 11.8GB. Pinning that to the
# database's own drive eventually costs the drive the database lives on.
#
# So the location is configurable. `FACULTY_JOBS_BACKUP_DIR` wins when set;
# otherwise a `backup_dir` recorded in `data/faculty_jobs_backup_dir.txt` is
# used, because the environment for the scheduled runs is set outside this
# repository and editing it is a separate errand; otherwise the old default
# beside the database, so nothing changes for anyone who sets neither.
BACKUP_DIR_ENV = "FACULTY_JOBS_BACKUP_DIR"


def backup_directory(db_path):
    """Resolve the backup directory for ``db_path``, creating nothing."""
    configured = os.environ.get(BACKUP_DIR_ENV, "").strip()
    if not configured:
        pointer = Path(db_path).parent / "faculty_jobs_backup_dir.txt"
        if pointer.exists():
            configured = pointer.read_text(encoding="utf-8").strip()
    if configured:
        target = Path(configured)
        # A configured directory that cannot be used is a silent downgrade to
        # backing up onto the drive we were trying to spare, so it is reported
        # rather than swallowed -- but it must not stop the write, because
        # failing to back up is the one outcome worse than backing up here.
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".write-probe"
            probe.touch()
            probe.unlink()
            return target
        except OSError as exc:
            print(f"backup directory {target} is unusable ({exc}); "
                  f"falling back to the default beside the database")
    return Path(db_path).parent / "backups"

def backup_before_write(db_path, tag, inventory, echo=print):
    """Unique, non-overwritable backup plus a manifest. Never migrates."""
    db_path = Path(db_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = backup_directory(db_path)
    directory.mkdir(parents=True, exist_ok=True)
    # Never overwrite, but two writes in the same second are legitimate -- a
    # migration chain can call this twice. Disambiguate rather than refuse, so
    # the guarantee is "no backup is ever lost" and not "the second write
    # fails".
    target = directory / f"faculty_jobs.{stamp}.{tag}.pre.db"
    suffix = 1
    while target.exists():
        suffix += 1
        target = directory / f"faculty_jobs.{stamp}.{tag}.{suffix}.pre.db"
    handle = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    os.close(handle)
    source, destination = sqlite3.connect(str(db_path)), sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    size = target.stat().st_size
    if size <= 0:
        raise SystemExit("backup is empty; nothing was written")
    manifest = {
        "taken_at": stamp,
        "reason": tag,
        "source_db": str(db_path),
        "backup_file": target.name,
        "backup_bytes": size,
        "backup_sha256": sha256_of(target),
        "wal": _sidecar(db_path, "-wal"),
        "shm": _sidecar(db_path, "-shm"),
        **inventory,
    }
    target.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    echo(f"backup={target.name} bytes={size}")
    echo(f"backup_sha256={manifest['backup_sha256']}")
    return target, manifest


def preflight(db_path, tag, echo=print):
    """Steps 1-3. Returns the inventory the post-check compares against."""
    conn = open_read_only(db_path)
    try:
        check_integrity(conn, "pre", echo)
        private = discover_private_tables(conn)
        inventory = {
            "schema_user_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "preserved_counts": table_counts(conn, PRESERVED_TABLES),
            "private_tables": list(private),
            "private_counts": table_counts(conn, private),
        }
    finally:
        conn.close()
    echo(f"pre_user_version={inventory['schema_user_version']}")
    echo(f"private tables discovered: {inventory['private_tables']}")
    backup_before_write(db_path, tag, inventory, echo)
    return inventory


def postflight(db_path, inventory, echo=print):
    """Step 5. Raises if anything that must be preserved shrank."""
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        check_integrity(conn, "post", echo)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        ledger = conn.execute(
            "SELECT MAX(version) FROM faculty_job_migrations").fetchone()[0]
        echo(f"post_user_version={version} migration_ledger={ledger}")
        if ledger is not None and int(version) != int(ledger):
            raise SystemExit(
                f"user_version {version} does not match the migration ledger {ledger}")
        after = table_counts(conn, PRESERVED_TABLES)
        after_private = table_counts(conn, tuple(inventory["private_tables"]))
        lost = {name: (before, after[name])
                for name, before in inventory["preserved_counts"].items()
                if before is not None and after.get(name) is not None and after[name] < before}
        private_lost = {name: (before, after_private[name])
                        for name, before in inventory["private_counts"].items()
                        if before is not None and after_private.get(name) is not None
                        and after_private[name] < before}
        if lost:
            raise SystemExit(f"preserved rows lost: {lost}")
        if private_lost:
            raise SystemExit(f"private state lost: {private_lost}")
        echo("row_loss=none private_loss=none")
        return {"preserved_counts": after, "private_counts": after_private,
                "schema_user_version": version}
    finally:
        conn.close()


__all__ = ["BACKUP_DIR_ENV", "PRESERVED_TABLES", "backup_directory",
           "FacultyJobsWriteGuardRequired",
           "backup_before_write", "check_integrity", "discover_private_tables",
           "guarded_write", "open_read_only", "postflight", "preflight",
           "sha256_of", "table_counts", "write_guard_active"]
