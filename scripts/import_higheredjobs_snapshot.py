# -*- coding: utf-8 -*-
"""Validate and optionally import a complete HigherEdJobs browser snapshot."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.faculty_jobs_service import FACULTY_DB_PATH, update_faculty_jobs
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight
from services.faculty_jobs_sources.higheredjobs import (
    HigherEdJobsBrowserSnapshotAdapter,
    load_browser_snapshot,
)


def _integrity(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {
            "quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
            "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
            "schema_version": conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM faculty_job_migrations").fetchone()[0],
            "sqlite_user_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            "source_records": conn.execute("SELECT COUNT(*) FROM source_job_records").fetchone()[0],
            "source_links": conn.execute("SELECT COUNT(*) FROM job_sources").fetchone()[0],
            "higheredjobs_records": conn.execute("""
                SELECT COUNT(*) FROM source_job_records r
                JOIN sources s ON s.id=r.source_id WHERE s.name='higheredjobs'
            """).fetchone()[0],
            "private_rows": conn.execute("SELECT COUNT(*) FROM user_job_state").fetchone()[0],
        }
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate and transactionally import a complete HigherEdJobs browser snapshot.")
    parser.add_argument("snapshot", help="path to the complete browser snapshot JSON")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH), help="faculty jobs SQLite database")
    parser.add_argument(
        "--apply", action="store_true",
        help="write the validated snapshot; without this flag the command is validation-only")
    args = parser.parse_args(argv)

    snapshot_path = Path(args.snapshot).resolve()
    raw = snapshot_path.read_bytes()
    payload = load_browser_snapshot(snapshot_path)
    adapter = HigherEdJobsBrowserSnapshotAdapter(payload)
    validation = {
        "snapshot": str(snapshot_path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "reported_total": adapter._response.reported_total,
        "jobs": len(adapter._response.jobs),
        "pages": adapter._response.listing_pages,
        "coverage_complete": adapter._response.coverage_complete,
    }
    if not args.apply:
        print(json.dumps({"ok": True, "mode": "validation_only", **validation}, indent=2))
        return 0

    db_path = Path(args.db).resolve()
    # The largest write this project performs was also the only one with no
    # backup behind it. Integrity, a schema-discovered inventory and a unique
    # backup all happen before update_faculty_jobs touches anything.
    inventory = preflight(str(db_path), "higheredjobs_snapshot_import")
    before = _integrity(db_path)
    if before["quick_check"] != "ok" or before["foreign_key_violations"]:
        raise RuntimeError(f"Refusing import because database integrity failed: {before}")
    with guarded_write():
        result = update_faculty_jobs(
            db_path,
            source_names=["higheredjobs"],
            adapters=[adapter],
            max_pages=adapter._response.listing_pages,
            detail_budget=0,
        )
    postflight(str(db_path), inventory)
    after = _integrity(db_path)
    if after["quick_check"] != "ok" or after["foreign_key_violations"]:
        raise RuntimeError(f"Database integrity failed after import: {after}")
    print(json.dumps({
        "ok": bool(result.get("ok")),
        "mode": "apply",
        **validation,
        "before": before,
        "update": result,
        "after": after,
    }, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
