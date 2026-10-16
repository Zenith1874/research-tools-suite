# -*- coding: utf-8 -*-
"""Recover posting text that the old 8,000-character cap cut off.

No network requests. The pages were already fetched and archived, so the text
is sitting in the raw archive -- this re-runs the parser over stored bytes with
the raised cap and writes back what the old one discarded.

Why it matters, measured rather than assumed: 57 stored postings sat exactly at
the old cap, losing 175,655 characters between them. Re-extracting them changed
the visa verdict on six, and four of those turned out to say plainly that
sponsorship is *not* available. Work-authorisation wording sits at the end of a
posting, so truncating the tail loses the one sentence a candidate who needs
sponsorship most needs to read.

Visa is re-derived from the recovered text, because a longer body that nobody
re-reads changes nothing.

Usage:
    python scripts/backfill_truncated_text.py
    python scripts/backfill_truncated_text.py --apply
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import raw_archive  # noqa: E402
from services.faculty_jobs_normalizer import classify_visa  # noqa: E402
from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)
from services.faculty_jobs_sources.source_jobboards import (  # noqa: E402
    DETAIL_TEXT_LIMIT, _parse_public_detail,
)
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)

# The cap the stored rows were written under. Anything sitting exactly at it is
# a candidate for recovery; anything shorter was not truncated.
OLD_LIMIT = 8000


def candidates(conn, old_limit=OLD_LIMIT):
    """Postings stored at the old cap that still have their archived page."""
    return conn.execute("""
        SELECT j.id, s.name AS source, js.source_url, ro.content_hash,
               j.description_excerpt AS stored, j.visa_status, j.visa_text
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        JOIN sources s ON s.id = js.source_id
        JOIN raw_observations ro ON ro.source_job_id = js.source_job_id
                                AND ro.source_id = js.source_id
        WHERE LENGTH(j.description_excerpt) >= ?
        GROUP BY j.id
    """, (old_limit,)).fetchall()


def recover(conn, row):
    """Re-parse one archived page. Returns the update, or None if nothing gained."""
    blob = raw_archive.load_blob(conn, row["content_hash"])
    html = blob.decode("utf-8", errors="replace") if isinstance(blob, bytes) else str(blob)
    parsed = _parse_public_detail(html, row["source"], row["source_url"]) or {}
    text = parsed.get("description") or ""
    if len(text) <= len(row["stored"] or ""):
        return None
    verdict = classify_visa(text)
    return {
        "job_id": row["id"],
        "source": row["source"],
        "was_length": len(row["stored"] or ""),
        "now_length": len(text),
        "description_excerpt": text[:DETAIL_TEXT_LIMIT],
        "visa_was": row["visa_status"],
        "visa_now": verdict["status"],
        "visa_text": verdict.get("evidence"),
        "visa_pathways": verdict.get("pathways"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the recovered text; without it nothing changes")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    conn = open_read_only(args.db)
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if int(version) != int(FACULTY_JOBS_SCHEMA_VERSION):
            raise SystemExit(f"schema user_version={version}, expected "
                             f"{FACULTY_JOBS_SCHEMA_VERSION}")
        rows = candidates(conn)
        recoveries = [r for r in (recover(conn, row) for row in rows) if r]
    finally:
        conn.close()

    gained = sum(r["now_length"] - r["was_length"] for r in recoveries)
    visa_changes = [r for r in recoveries if r["visa_was"] != r["visa_now"]]
    print(f"postings stored at the old {OLD_LIMIT}-character cap: {len(rows)}")
    print(f"  recoverable from the archive:  {len(recoveries)}")
    print(f"  characters the cap discarded:  {gained:,}")
    print(f"  visa verdict changes:          {len(visa_changes)}")
    for r in visa_changes:
        print(f"    #{r['job_id']:<6}{r['source'][:20]:22}{str(r['visa_was']):24}"
              f"-> {r['visa_now']}")
    if not args.apply:
        print("\nno --apply: nothing was written")
        return

    inventory = preflight(args.db, "text_truncation_backfill")
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        conn = sqlite3.connect(str(args.db), timeout=60)
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
                      "request was made: the old 8,000-character limit truncated "
                      "the tail of the posting, which is where work-authorisation "
                      "wording sits."))
            conn.commit()
        finally:
            conn.close()
    print(f"\nrewrote {len(recoveries)} postings from the archive; no page was re-fetched")
    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
