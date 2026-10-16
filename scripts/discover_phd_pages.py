# -*- coding: utf-8 -*-
"""Confirm each doctoral programme's roster / job-market / placement pages.

Replaces the panel's twenty "pending confirmation" notes with an outcome per
programme. The outcomes that are not `confirmed` matter just as much: a
programme page that 404s and one that links to no job-market page are different
facts, and neither says anything about how many candidates that programme has
on the market.

Usage:
    python scripts/discover_phd_pages.py
    python scripts/discover_phd_pages.py --apply

Nothing is requested or written without --apply.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)
from services.phd_page_discovery import discover  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="check only the first N programmes")
    parser.add_argument("--sleep", type=float, default=1.5,
                        help="seconds between programme pages")
    parser.add_argument("--apply", action="store_true",
                        help="actually request and write; without it nothing happens")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    conn = open_read_only(args.db)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if int(version) != int(FACULTY_JOBS_SCHEMA_VERSION):
            raise SystemExit(f"schema user_version={version}, expected "
                             f"{FACULTY_JOBS_SCHEMA_VERSION}")
        rows = conn.execute("""
            SELECT status, COUNT(*) AS n FROM phd_program_sources
            GROUP BY status ORDER BY n DESC""").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM phd_program_sources").fetchone()[0]
    finally:
        conn.close()

    print(f"programmes in the panel: {total}")
    for row in rows:
        print(f"  {str(row[0]):14}{row[1]}")
    planned = min(total, args.limit) if args.limit else total
    print(f"this run would read: {planned} programme page(s)")
    if not args.apply:
        print("\nno --apply: nothing was requested and nothing was written")
        return

    inventory = preflight(args.db, "phd_page_discovery")
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        conn = sqlite3.connect(str(args.db), timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            result = discover(conn, limit=args.limit, sleep=args.sleep,
                              echo=lambda *a: print(*a, flush=True))
        finally:
            conn.close()

    print("\n" + "=" * 66)
    print("by outcome:")
    for status, count in sorted(result["by_status"].items(), key=lambda kv: -kv[1]):
        print(f"  {status:14}{count}")
    print("pages found:")
    for kind, count in sorted(result["pages_found"].items(), key=lambda kv: -kv[1]):
        print(f"  {kind:14}{count}")
    print(f"\n{result['note']}")
    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
