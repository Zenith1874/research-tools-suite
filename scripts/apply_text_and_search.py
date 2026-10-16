# -*- coding: utf-8 -*-
"""Migrate to the full-text index and recover truncated text, under one backup.

Deliberately one script rather than two. Each guarded write copies a ~200MB
database first, and four such copies back to back once starved the running
server of I/O until its watchdog gave up. These two changes touch the same
rows in the same way, so they belong in one transaction with one backup:

1. schema 84 -- the FTS5 index over posting text;
2. re-extract the 57 postings the old 8,000-character cap truncated, from the
   raw archive, with no network request;
3. rebuild the index so it reflects the recovered text rather than the
   truncated text it would otherwise have been built from.

Step 3 is the reason the order matters. Building the index first and then
rewriting the bodies would leave it correct only because of the update
triggers; rebuilding afterwards makes it true by construction.

Usage:
    python scripts/apply_text_and_search.py
    python scripts/apply_text_and_search.py --apply
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_truncated_text import OLD_LIMIT, candidates, recover  # noqa: E402
from services import faculty_jobs_search, raw_archive  # noqa: E402
from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)
from services.faculty_jobs_sources.source_jobboards import DETAIL_TEXT_LIMIT  # noqa: E402
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    # Read-only survey first, so the plan is known before anything is written.
    conn = open_read_only(args.db)
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = candidates(conn)
        recoveries = [r for r in (recover(conn, row) for row in rows) if r]
    finally:
        conn.close()

    gained = sum(r["now_length"] - r["was_length"] for r in recoveries)
    visa_changes = [r for r in recoveries if r["visa_was"] != r["visa_now"]]
    print(f"schema now {version} -> {FACULTY_JOBS_SCHEMA_VERSION}")
    print(f"text cap    {OLD_LIMIT} -> {DETAIL_TEXT_LIMIT}")
    print(f"postings truncated at the old cap: {len(rows)}")
    print(f"  recoverable without a request:   {len(recoveries)}")
    print(f"  characters the cap discarded:    {gained:,}")
    print(f"  visa verdicts that change:       {len(visa_changes)}")
    for r in visa_changes:
        print(f"    #{r['job_id']:<6}{r['source'][:20]:22}{str(r['visa_was']):24}"
              f"-> {r['visa_now']}")
    if not args.apply:
        print("\nno --apply: nothing was written")
        return

    inventory = preflight(args.db, "text_cap_and_fts")
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)        # applies schema 84
        conn = sqlite3.connect(str(args.db), timeout=120)
        conn.row_factory = sqlite3.Row
        try:
            for r in recoveries:
                conn.execute("""
                    UPDATE jobs SET description_excerpt = ?, visa_status = ?,
                                    visa_text = ?, visa_pathways = ?, updated_at = ?
                     WHERE id = ?
                """, (r["description_excerpt"], r["visa_now"], r["visa_text"],
                      json.dumps(r["visa_pathways"], ensure_ascii=False)
                      if r["visa_pathways"] else None,
                      raw_archive.now_utc(), r["job_id"]))
                conn.execute("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at, action, job_id, old_value, new_value, reason)
                    VALUES (?,?,?,?,?,?)
                """, (raw_archive.now_utc(), "text_truncation_backfill", r["job_id"],
                      json.dumps({"description_length": r["was_length"],
                                  "visa_status": r["visa_was"]}, ensure_ascii=False),
                      json.dumps({"description_length": r["now_length"],
                                  "visa_status": r["visa_now"]}, ensure_ascii=False),
                      "Re-parsed the archived page with the raised text cap. No "
                      "request was made: the old 8,000-character cap truncated the "
                      "tail of the posting, which is where work-authorisation "
                      "wording sits. Four of these postings turned out to say "
                      "sponsorship is not available."))
            indexed = faculty_jobs_search.rebuild(conn)
            healthy = faculty_jobs_search.integrity_ok(conn)
            conn.commit()
        finally:
            conn.close()

    print(f"\nrewrote {len(recoveries)} postings from the archive; no page re-fetched")
    print(f"full-text index rebuilt over {indexed} postings; integrity={healthy}")
    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
