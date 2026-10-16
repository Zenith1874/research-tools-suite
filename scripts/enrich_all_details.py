# -*- coding: utf-8 -*-
"""Read detail pages across every enabled source, under one backup.

Why this exists rather than a shell loop over enrich_job_details.py: that
script takes its own backup per invocation. Running it once per source meant
eighteen consecutive copies of a 180MB database, and four of those in a row
were enough to starve the running server of I/O until its watchdog gave up
restarting it. The queue is one job; it deserves one backup.

Two other things follow from doing it in one process:

* **One source's refusal is not the run's.** A board that serves a challenge
  stops its own pass and the run moves to the next source. Stopping everything
  because one board said no would leave the other seventeen unread.
* **The write transaction stays bounded.** ``enrich_source_details`` commits
  once at the end of its batch, so a single 1,000-page call would hold SQLite's
  write lock for the whole run and block the server behind it. Calling it per
  source, with a per-source limit, keeps each transaction to minutes.

Usage:
    python scripts/enrich_all_details.py
    python scripts/enrich_all_details.py --limit-per-source 60 --apply

Nothing is requested or written without --apply.
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.faculty_jobs_detail_enrichment import (  # noqa: E402
    enrich_source_details, pending_count,
)
from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)


def enabled_sources(conn, only=None):
    """Sources we are permitted to read.

    ``enabled = 0`` is a standing decision, not an oversight -- higheredjobs is
    off deliberately -- so this never widens the set to "everything with rows".
    """
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sources WHERE enabled = 1 ORDER BY name")]
    if only:
        wanted = {name.strip() for name in only.split(",") if name.strip()}
        unknown = wanted - set(names)
        if unknown:
            raise SystemExit("not enabled (or not a source): " + ", ".join(sorted(unknown)))
        names = [name for name in names if name in wanted]
    return names


def survey(db_path, only=None):
    conn = open_read_only(db_path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if int(version) != int(FACULTY_JOBS_SCHEMA_VERSION):
            raise SystemExit(
                "schema user_version={0}, this build expects {1}; run a write-mode "
                "command to migrate first".format(version, FACULTY_JOBS_SCHEMA_VERSION))
        return [(name, pending_count(conn, name)) for name in enabled_sources(conn, only)]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-per-source", type=int, default=60,
                        help="maximum detail pages to read per source this run")
    parser.add_argument("--sleep", type=float, default=1.0,
                        help="seconds between detail requests")
    parser.add_argument("--sources", default=None,
                        help="comma-separated subset; default is every enabled source")
    parser.add_argument("--max-minutes", type=float, default=45.0,
                        help="stop starting new sources once this much time has passed")
    parser.add_argument("--apply", action="store_true",
                        help="actually request and write; without it nothing happens")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    if args.limit_per_source < 1:
        raise SystemExit("--limit-per-source must be at least 1")
    if args.sleep < 0:
        raise SystemExit("--sleep may not be negative")

    queue = sorted(survey(args.db, args.sources), key=lambda pair: -pair[1])
    owed = sum(count for _name, count in queue)
    planned = sum(min(count, args.limit_per_source) for _name, count in queue)

    print("sources enabled: {0}".format(len(queue)))
    for name, count in queue:
        capped = "" if count <= args.limit_per_source else \
            "  (this run: {0})".format(args.limit_per_source)
        print("  {0:24}{1:>5} owed{2}".format(name, count, capped))
    print("\ntotal owed a reading: {0}".format(owed))
    print("this run would request: {0}".format(planned))
    print("estimated: {0:.0f} minutes at --sleep {1}s plus ~1s per response".format(
        planned * (args.sleep + 1.0) / 60, args.sleep))

    if not args.apply:
        print("\nno --apply: nothing was requested and nothing was written")
        return

    # Integrity, inventory and the backup all happen while the file is still
    # untouched -- before ensure migrates anything.
    inventory = preflight(args.db, "detail_all")
    started = time.monotonic()
    results = []
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        for name, count in queue:
            if not count:
                continue
            elapsed = (time.monotonic() - started) / 60.0
            if elapsed >= args.max_minutes:
                results.append((name, {"skipped":
                                       "time budget reached at {0:.0f}m".format(elapsed)}))
                continue
            print("\n--- {0} ({1} owed) ---".format(name, count), flush=True)
            conn = sqlite3.connect(str(args.db), timeout=60)
            conn.row_factory = sqlite3.Row
            try:
                stats = enrich_source_details(
                    conn, name, limit=args.limit_per_source, sleep=args.sleep)
            except Exception as exc:  # noqa: BLE001 - one source must not end the run
                conn.rollback()
                stats = {"error": "{0}: {1}".format(type(exc).__name__, exc)}
                print("  ERROR {0}".format(stats["error"]), flush=True)
            finally:
                conn.close()
            results.append((name, stats))
            if "error" not in stats:
                print("  read={0} filled={1} empty={2} errors={3} pending_after={4}".format(
                    stats["read"], stats["updated"], stats["empty"], stats["errors"],
                    stats["pending_after"]), flush=True)
                if stats.get("stopped_reason"):
                    print("  stopped early: {0}".format(stats["stopped_reason"]), flush=True)

    print("\n" + "=" * 78)
    print("{0:24}{1:>6}{2:>8}{3:>7}{4:>5}{5:>7}  note".format(
        "source", "read", "filled", "empty", "err", "left"))
    totals = {"read": 0, "updated": 0, "empty": 0, "errors": 0}
    for name, stats in results:
        if "error" in stats or "skipped" in stats:
            print("{0:24}{1:>33}  {2}".format(
                name, "", stats.get("error") or stats.get("skipped")))
            continue
        for key in totals:
            totals[key] += stats.get(key, 0)
        print("{0:24}{1:>6}{2:>8}{3:>7}{4:>5}{5:>7}  {6}".format(
            name, stats["read"], stats["updated"], stats["empty"], stats["errors"],
            stats["pending_after"], (stats.get("stopped_reason") or "")[:38]))
    print("{0:24}{1:>6}{2:>8}{3:>7}{4:>5}".format(
        "TOTAL", totals["read"], totals["updated"], totals["empty"], totals["errors"]))
    print("elapsed: {0:.1f} minutes".format((time.monotonic() - started) / 60))

    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
