#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruct daily market snapshots from the history already held.

Nothing is fetched. Every figure comes from `jobs`, `job_status_history` and
`ingestion_runs`, which have covered this market since 2026-08-23.

What is genuine and what is not, because the difference has to survive:

* **change counts and the source panel are real.** They come from history rows
  written on the day, so "six postings appeared on 2026-08-23" and "five
  sources delivered that day" are contemporaneous facts.
* **active counts are not.** No daily state was recorded at the time, so they
  are computed from today's rows and are identical across every reconstructed
  day. Each row is flagged `reconstructed=1` and the health report says so.

From the first live run onward, snapshots are written on the day and carry
`reconstructed=0`.

    python scripts/backfill_market_snapshots.py --status
    python scripts/backfill_market_snapshots.py --apply
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import faculty_jobs_snapshots as snapshots
from services.faculty_jobs_service import FACULTY_DB_PATH
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight


def summarise(conn):
    row = conn.execute("""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT snapshot_date) AS days,
               MIN(snapshot_date) AS first_day, MAX(snapshot_date) AS last_day,
               SUM(reconstructed) AS reconstructed
        FROM market_snapshots
    """).fetchone()
    print(f"  snapshot rows        {row['rows'] or 0:,}")
    print(f"  days covered         {row['days'] or 0}")
    print(f"  range                {row['first_day'] or '-'} .. {row['last_day'] or '-'}")
    print(f"  reconstructed rows   {row['reconstructed'] or 0:,}")
    history = conn.execute("""
        SELECT MIN(substr(observed_at,1,10)) AS first_day,
               MAX(substr(observed_at,1,10)) AS last_day, COUNT(*) AS n
        FROM job_status_history
    """).fetchone()
    print(f"  history available    {history['first_day']} .. {history['last_day']} "
          f"({history['n']:,} rows)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the snapshots (guarded, backed up first)")
    parser.add_argument("--status", action="store_true", help="read-only summary")
    parser.add_argument("--since", help="first day to reconstruct (default: earliest history)")
    parser.add_argument("--until", help="last day to reconstruct (default: today)")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args(argv)

    if not args.apply:
        conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            print("Market snapshots (read-only)")
            summarise(conn)
        except sqlite3.DatabaseError as error:
            print(f"  snapshot tables not present: {error}")
        finally:
            conn.close()
        print("\nRe-run with --apply to reconstruct.")
        return 0

    inventory = preflight(args.db, "market_snapshot_backfill")
    conn = sqlite3.connect(args.db, timeout=120)
    conn.row_factory = sqlite3.Row
    try:
        with guarded_write():
            snapshots.ensure_tables(conn)
            result = snapshots.backfill(conn, since=args.since, until=args.until)
            conn.commit()
        print(f"\nreconstructed {result.get('days', 0)} days, "
              f"{result.get('rows', 0):,} rows")
        if result.get("reason"):
            print(f"  {result['reason']}")
        summarise(conn)
        series = snapshots.stable_panel_series(conn)
        print(f"\n  stable source panel  {series.get('panel_size', 0)} sources across "
              f"{len(series.get('series', []))} days")
        for name in series.get("panel", [])[:8]:
            print(f"    {name}")
        print("\n  Compare periods over that panel, not over the observed count: a "
              "source added\n  between two dates raises the count without the market "
              "moving.")
    finally:
        conn.close()
    postflight(args.db, inventory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
