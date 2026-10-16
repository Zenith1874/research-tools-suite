# -*- coding: utf-8 -*-
"""Fold vacancies that two boards both carry, under the write guard.

Reports first and merges only when asked. The default is --dry-run because the
list is the interesting part: it says which groups were accepted, and -- more
usefully -- which were refused and why.

Nothing is deleted. An absorbed row keeps every column it had and gains a
pointer to the survivor, so a merge this got wrong is undone by clearing one
column. That is also what lets the guard's rule stand: `jobs` is a preserved
table and the run fails if its count drops.

    python scripts/merge_cross_source_duplicates.py            # report only
    python scripts/merge_cross_source_duplicates.py --apply
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import cross_source_merge
from services.faculty_jobs_service import (
    FACULTY_DB_PATH, ensure_faculty_jobs_tables, now_utc,
)
from services.faculty_jobs_scope import catalogue_sql
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight


def _open(db_path):
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _describe(verdict):
    members = " | ".join(
        f"{'+'.join(row['sources'])}#{row['id']} ({row['body_chars']} chars)"
        for row in sorted(verdict["members"], key=lambda r: r["sources"]))
    return f"  {verdict['institution']} -- {verdict['title']}\n      {members}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    parser.add_argument("--scope", default="all",
                        help="which catalogue to search for duplicates in")
    parser.add_argument("--apply", action="store_true",
                        help="write the merges; without it nothing is changed")
    parser.add_argument("--show", type=int, default=15,
                        help="how many accepted groups to print")
    parser.add_argument("--json", dest="json_path",
                        help="write the full plan, accepted and refused alike")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"no database at {db_path}")

    # Report first, off a read-only connection, so a dry run cannot migrate or
    # write anything at all.
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        has_column = any(row["name"] == "merged_into_job_id"
                         for row in conn.execute("PRAGMA table_info(jobs)"))
        if not has_column:
            print("jobs.merged_into_job_id is not present yet; "
                  "run with --apply to migrate (migration 85) and merge.")
            report = None
        else:
            report = cross_source_merge.plan(conn, catalogue_sql(args.scope))
    finally:
        conn.close()

    if report is not None:
        _print_report(report, args.show)
        if args.json_path:
            Path(args.json_path).write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
            print(f"plan written to {args.json_path}")
        if not args.apply:
            print("\ndry run: nothing was written. Re-run with --apply.")
            return 0
        if not report["merges"]:
            print("\nnothing to merge.")
            return 0
    elif not args.apply:
        return 0

    inventory = preflight(db_path, "cross_source_duplicate_merge")
    ensure_faculty_jobs_tables(str(db_path))          # migration 85, after the backup

    conn = _open(db_path)
    try:
        with guarded_write():
            # Re-planned against the migrated database: the read-only pass
            # above ran before the column existed on a first run, and in any
            # case a plan built from a different connection is a plan about a
            # database state that may have moved.
            report = cross_source_merge.plan(conn, catalogue_sql(args.scope))
            _print_report(report, args.show)
            applied = cross_source_merge.apply_all(conn, report["merges"], now_utc())
            conn.commit()
    finally:
        conn.close()
    postflight(db_path, inventory)

    absorbed = sum(len(item["absorbed"]) for item in applied)
    filled = sum(len(item["fields_filled"]) for item in applied)
    print(f"\nmerged {len(applied)} groups; {absorbed} rows now point at a survivor "
          f"and are no longer counted; {filled} empty fields filled from them.")
    print("No row was deleted. Clearing jobs.merged_into_job_id undoes a merge; "
          "faculty_job_repair_audit records which source links moved and from where.")
    return 0


def _print_report(report, show):
    print(f"candidate groups: {report['groups']}")
    print(f"  accepted: {len(report['merges'])} "
          f"({report['rows_absorbed']} rows absorbed)")
    for reason, count in sorted(report["held_back"].items(), key=lambda kv: -kv[1]):
        print(f"  left alone: {count}  -- {reason}")
    if report["merges"]:
        print(f"\nfirst {min(show, len(report['merges']))} accepted:")
        for verdict in report["merges"][:show]:
            print(_describe(verdict))
    disagreeing = [v for v in report["merges"] if not v["disciplines_agree"]]
    apart = [v for v in report["merges"] if not v["windows_overlap"]]
    print(f"\nof the accepted groups, {len(disagreeing)} carry disagreeing discipline "
          f"labels and {len(apart)} have non-overlapping observation windows.")
    print("Neither was used to decide: the first is our own classifier and the "
          "second records when we crawled, not when the vacancy existed.")
    print(report["note"])


if __name__ == "__main__":
    raise SystemExit(main())
