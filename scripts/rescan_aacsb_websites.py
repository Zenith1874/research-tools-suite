# -*- coding: utf-8 -*-
"""Rescan AACSB official websites under the current rule, in bounded batches.

A rule-version bump retires every earlier observation by design, so the whole
roster needs re-reading. That is roughly a thousand schools and about an hour,
which is why this exists as a repeatable script rather than a one-off: it
reports what a run will cost before making a request, works in batches so an
interruption costs one batch rather than the pass, and resumes naturally
because the scan selects rows whose recorded rule version is stale.

Usage:
    python scripts/rescan_aacsb_websites.py --status
    python scripts/rescan_aacsb_websites.py --estimate
    python scripts/rescan_aacsb_websites.py --batch 100
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, ensure_faculty_jobs_tables, scan_aacsb_official_websites,
)
from services.faculty_jobs_sources.aacsb import AACSB_SCAN_RULE_VERSION  # noqa: E402
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight  # noqa: E402

PRESERVED = ("jobs", "source_job_records", "job_sources", "sources",
             "aacsb_directory_schools", "aacsb_scan_history", "faculty_job_repair_audit")

# Measured on a 25-school probe on 2026-08-29 and confirmed across a full
# 1,053-school pass: 4.6 s/school including robots, homepage and career pages.
SECONDS_PER_SCHOOL = 4.6


def read_only(path):
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def remaining(conn):
    return conn.execute("""
        SELECT COUNT(*) FROM aacsb_directory_schools
        WHERE active=1 AND official_website IS NOT NULL AND official_website!=''
          AND (website_checked_at IS NULL OR COALESCE(scan_rule_version,'')!=?)
    """, (AACSB_SCAN_RULE_VERSION,)).fetchone()[0]


def counts(conn):
    out = {}
    for table in PRESERVED:
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            out[table] = None
    return out


def integrity(conn, label):
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    print(f"{label}: quick_check={quick} foreign_key_violations={len(fk)}", flush=True)
    if quick != "ok" or fk:
        raise SystemExit(f"{label} failed; stopping")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status(db):
    conn = read_only(db)
    try:
        print(f"current rule: {AACSB_SCAN_RULE_VERSION}")
        print(f"schools owed a rescan: {remaining(conn)}")
        print("\nrecorded rule versions:")
        for row in conn.execute("""
            SELECT COALESCE(scan_rule_version,'(never scanned)') AS v, COUNT(*) AS n
            FROM aacsb_directory_schools GROUP BY 1 ORDER BY n DESC
        """):
            print(f"   {row['v']:<36} {row['n']}")
        print("\njob_scan_status:")
        for row in conn.execute("""
            SELECT COALESCE(job_scan_status,'(none)') AS v, COUNT(*) AS n
            FROM aacsb_directory_schools GROUP BY 1 ORDER BY n DESC
        """):
            print(f"   {row['v']:<40} {row['n']}")
        print("\nA blocked, unknown or not_found school is one we could not read.")
        print("It is not evidence that the school has no vacancy.")
        running = conn.execute(
            "SELECT COUNT(*) FROM aacsb_scan_runs WHERE status='running'").fetchone()[0]
        if running:
            print(f"\nWARNING: {running} scan run(s) recorded as running. Do not start another.")
    finally:
        conn.close()


def estimate(db, batch):
    conn = read_only(db)
    try:
        owed = remaining(conn)
    finally:
        conn.close()
    seconds = owed * SECONDS_PER_SCHOOL
    print(f"schools owed a rescan: {owed}")
    print(f"batch size:            {batch}")
    print(f"batches:               {-(-owed // batch) if batch else 0}")
    print(f"estimated duration:    {seconds/60:.0f} minutes at {SECONDS_PER_SCHOOL}s/school")
    print("Requests are spread across one origin per school, so no single site is pressed.")
    print("No request was made.")


def backup(db):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(db).parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"faculty_jobs.{stamp}.aacsb_rescan.pre.db"
    if target.exists():
        raise SystemExit(f"refusing to overwrite {target}")
    handle = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_RDWR)
    os.close(handle)
    src, dst = sqlite3.connect(str(db)), sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    manifest = {
        "taken_at": stamp, "source_db": str(db), "backup_file": target.name,
        "backup_bytes": target.stat().st_size, "backup_sha256": sha256(target),
        "rule_version": AACSB_SCAN_RULE_VERSION,
        "reason": "AACSB official-site rescan under the current rule",
    }
    target.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"backup={target.name} bytes={manifest['backup_bytes']}", flush=True)
    print(f"backup_sha256={manifest['backup_sha256']}", flush=True)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    parser.add_argument("--batch", type=int, default=100, help="schools per batch")
    parser.add_argument("--max-batches", type=int, help="stop after this many batches")
    parser.add_argument("--delay", type=float, default=0.45)
    parser.add_argument("--site-max-pages", type=int, default=2)
    parser.add_argument("--status", action="store_true", help="read-only progress report")
    parser.add_argument("--estimate", action="store_true", help="cost only; makes no request")
    args = parser.parse_args()

    if args.status:
        status(args.db)
        return
    if args.batch < 1:
        raise SystemExit("--batch must be at least 1")
    if args.estimate:
        estimate(args.db, args.batch)
        return

    conn = read_only(args.db)
    try:
        integrity(conn, "pre")
        before = counts(conn)
        owed = remaining(conn)
        running = conn.execute(
            "SELECT COUNT(*) FROM aacsb_scan_runs WHERE status='running'").fetchone()[0]
    finally:
        conn.close()
    if running:
        raise SystemExit(f"{running} scan run(s) are still marked running; refusing to start "
                         "a second scan against the same roster")
    print(f"pre_counts={before}", flush=True)
    print(f"rule={AACSB_SCAN_RULE_VERSION} owed={owed}", flush=True)
    if not owed:
        print("every active school with a website has been read under the current rule")
        return

    # Shared guard: integrity, schema-discovered inventory of preserved and
    # private tables, then a unique backup with a DB/WAL/SHM manifest -- all
    # before ensure migrates anything.
    inventory = preflight(args.db, "aacsb_rescan")
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)

        started = time.time()
        totals = {"schools": 0, "jobs_found": 0, "errors": 0,
                  "candidates_seen": 0, "candidates_rejected": 0}
        batch_number = 0
        while True:
            conn = read_only(args.db)
            try:
                left = remaining(conn)
            finally:
                conn.close()
            if not left:
                break
            if args.max_batches and batch_number >= args.max_batches:
                print(f"stopping after {batch_number} batch(es) as requested; {left} left", flush=True)
                break
            batch_number += 1
            result = scan_aacsb_official_websites(
                args.db, max_schools=args.batch, delay=args.delay,
                site_max_pages=args.site_max_pages)
            scanned = int(result.get("websites_checked") or 0)
            totals["schools"] += scanned
            for key in ("jobs_found", "errors", "candidates_seen", "candidates_rejected"):
                totals[key] += int(result.get(key) or 0)
            print(f"batch {batch_number:>2}: scanned={scanned} jobs_found={result.get('jobs_found')} "
                  f"errors={result.get('errors')} remaining={left - scanned} "
                  f"elapsed={(time.time()-started)/60:.1f}m", flush=True)
            if not scanned:
                print("a batch scanned nothing; stopping rather than looping", flush=True)
                break

    print(f"\ntotal elapsed: {(time.time()-started)/60:.1f} minutes", flush=True)
    print(f"totals: {totals}", flush=True)

    postflight(args.db, inventory)
    status(args.db)


if __name__ == "__main__":
    main()
