# -*- coding: utf-8 -*-
"""Read posting detail pages for a source, resumably.

Usage:
    python scripts/enrich_job_details.py --source higheredjobs --limit 200
    python scripts/enrich_job_details.py --source higheredjobs --status

The pass stops cleanly when a board substitutes a challenge or refuses, keeps
what it already read, and continues from there on the next run. It never treats
an unread page as evidence that a posting has no deadline.

Every run that writes takes a unique, non-overwritable backup first and
verifies integrity and row counts afterwards.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.faculty_jobs_detail_enrichment import (  # noqa: E402
    detail_progress, enrich_source_details, pending_count,
)
from services.faculty_jobs_service import FACULTY_DB_PATH, ensure_faculty_jobs_tables  # noqa: E402
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)

PRESERVED = ("jobs", "source_job_records", "job_sources", "sources",
             "ingestion_runs", "faculty_job_repair_audit")


def connect(path):
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def integrity(conn, label):
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"{label}: quick_check={quick} foreign_key_violations={len(violations)}")
    if quick != "ok" or violations:
        raise SystemExit(f"{label} failed; no further writes attempted")


def counts(conn):
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in PRESERVED}


def backup(db_path, tag):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(db_path).parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"faculty_jobs.{stamp}.{tag}.pre.db"
    if target.exists():
        raise SystemExit(f"refusing to overwrite an existing backup: {target}")
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
        raise SystemExit("backup is empty; aborting before any write")
    print(f"backup={target.name} bytes={size}")
    return target


def schema_is_current(conn):
    from services.faculty_jobs_service import FACULTY_JOBS_SCHEMA_VERSION
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError:
        return False, None
    return int(version) == int(FACULTY_JOBS_SCHEMA_VERSION), version


def report_status(args):
    """Read-only progress report. Opens the file read-only and never migrates."""
    from services.faculty_jobs_service import FACULTY_JOBS_SCHEMA_VERSION
    if not Path(args.db).exists():
        raise SystemExit(f"no database at {args.db}")
    conn = open_read_only(args.db)
    try:
        current, version = schema_is_current(conn)
        if not current:
            print(f"schema user_version={version} but this build expects "
                  f"{FACULTY_JOBS_SCHEMA_VERSION}.")
            print("Run a write-mode command to migrate; --status will not modify the file.")
            return
        try:
            progress = detail_progress(conn, args.source)
        except sqlite3.OperationalError as exc:
            print(f"cannot report progress on this database: {exc}")
            return
        print(f"source={progress['source']}")
        print(f"  pending (owed a reading): {progress['pending']}")
        for status, count in sorted(progress["by_status"].items(), key=lambda kv: -kv[1]):
            print(f"  {status:<12} {count}")
    finally:
        conn.close()


def dry_run(args):
    """Say what a run would cost without making a request -- or a write.

    This previously called ensure_faculty_jobs_tables, which migrates. A
    command whose whole purpose is "tell me what would happen" must not change
    the database to answer, and certainly not before the backup that the write
    path takes.
    """
    from services.faculty_jobs_service import FACULTY_JOBS_SCHEMA_VERSION
    if not Path(args.db).exists():
        raise SystemExit(f"no database at {args.db}")
    conn = open_read_only(args.db)
    try:
        current, version = schema_is_current(conn)
        if not current:
            print(f"schema user_version={version} but this build expects "
                  f"{FACULTY_JOBS_SCHEMA_VERSION}; run a write-mode command to migrate.")
            return
        try:
            owed = pending_count(conn, args.source)
        except sqlite3.OperationalError as exc:
            print(f"cannot estimate on this database: {exc}")
            return
    finally:
        conn.close()
    planned = min(owed, args.limit)
    seconds = planned * (args.sleep + 1.0)
    print(f"source={args.source}")
    print(f"  postings owed a reading: {owed}")
    print(f"  this run would request:  {planned}")
    print(f"  estimated duration:      {seconds/60:.1f} minutes "
          f"(at --sleep {args.sleep}s plus ~1s per response)")
    print(f"  postings left after:     {max(0, owed - planned)}")
    print("  no request was made")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="source name, e.g. higheredjobs")
    parser.add_argument("--limit", type=int, default=100,
                        help="maximum detail pages to read this run")
    parser.add_argument("--sleep", type=float, default=1.0,
                        help="seconds between detail requests")
    parser.add_argument("--status", action="store_true",
                        help="report progress without making any request")
    parser.add_argument("--timeout", type=int, default=20,
                        help="per-request timeout in seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the planned request count and stop")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    # A status report that migrates the database is not a status report: it
    # changes user_version and the file hash of whatever it is pointed at,
    # including a copy someone made to inspect safely.
    if args.status:
        report_status(args)
        return

    if args.limit < 1:
        raise SystemExit("--limit must be at least 1; SQLite reads a negative LIMIT as "
                         "unbounded, which here would mean every posting in one run")
    if args.sleep < 0:
        raise SystemExit("--sleep may not be negative")
    if args.timeout < 1 or args.timeout > 120:
        raise SystemExit("--timeout must be between 1 and 120 seconds")

    if args.dry_run:
        dry_run(args)
        return

    # Order matters: integrity, inventory and backup all happen while the file
    # is still untouched. Calling ensure first -- as this did -- migrates the
    # database before the copy exists, so the backup is of the post-migration
    # state and the pre-migration state is unrecoverable.
    conn = open_read_only(args.db)
    try:
        remaining = pending_count(conn, args.source)
    except sqlite3.OperationalError as exc:
        conn.close()
        raise SystemExit(f"cannot read progress on this database: {exc}. "
                         "Run a write-mode command on a current schema first.")
    else:
        conn.close()
    print(f"pending before this run: {remaining}")
    if not remaining:
        print("nothing to read; every active posting from this source has been attempted")
        return

    inventory = preflight(args.db, f"detail_{args.source}")
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        conn = connect(args.db)
        try:
            stats = enrich_source_details(conn, args.source, limit=args.limit, sleep=args.sleep)
        finally:
            conn.close()

    print("\nrun summary")
    print(f"  considered:  {stats['considered']}")
    print(f"  pages read:  {stats['read']}")
    print(f"  jobs filled: {stats['updated']}")
    print(f"  read but empty: {stats['empty']}")
    print(f"  errors:      {stats['errors']}")
    for field, count in stats["fields_filled"].items():
        if count:
            print(f"    {field}: {count}")
    if stats["stopped_reason"]:
        print(f"  stopped early: {stats['stopped_reason']}")
        print("  progress is saved; rerun to continue from here")
    print(f"  pending after: {stats['pending_after']}")

    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
