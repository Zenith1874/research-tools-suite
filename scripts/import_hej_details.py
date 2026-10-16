# -*- coding: utf-8 -*-
"""Apply posting bodies collected in the browser to the database.

The browser collector writes JSONL as it reads; this validates those records
and applies them under the write guard, re-deriving the fields that only a
posting's own text can answer.

Why the two halves are separate processes: the collector talks to a board and
must be free to stop the moment it is challenged, while the writer must be free
to take a backup and run a transaction. Tying them together would mean either a
crawl holding a write lock or a database write that cannot stop politely.

**A body is only ever written when it is longer than what is stored.** The card
blurb averages 193 characters and a real posting averages 4,200, so a shorter
capture means the page did not render, and overwriting a good body with it
would be a silent loss.

Usage:
    python scripts/import_hej_details.py outputs/hej_details.jsonl
    python scripts/import_hej_details.py outputs/hej_details.jsonl --apply
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
from services.faculty_jobs_sources.source_jobboards import DETAIL_TEXT_LIMIT  # noqa: E402
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)

SOURCE = "higheredjobs"


def load_records(path):
    records, malformed = [], 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1        # a torn last line from an interrupted append
            continue
        if row.get("status") == "ok" and (row.get("body") or "").strip():
            records.append(row)
    return records, malformed


def plan(conn, records):
    """What each record would change. Nothing is decided in the writer."""
    updates, skipped = [], []
    for row in records:
        current = conn.execute("""
            SELECT j.id, j.description_excerpt AS body, j.visa_status, j.official_url
            FROM job_sources js JOIN sources s ON s.id = js.source_id
            JOIN jobs j ON j.id = js.job_id
            WHERE s.name = ? AND js.source_job_id = ? AND js.active = 1
        """, (SOURCE, str(row["source_job_id"]))).fetchone()
        if not current:
            skipped.append((row["source_job_id"], "no active posting with this id"))
            continue
        body = row["body"][:DETAIL_TEXT_LIMIT]
        if len(body) <= len(current["body"] or ""):
            skipped.append((row["source_job_id"], "capture is not longer than what is stored"))
            continue
        verdict = classify_visa(body)
        updates.append({
            "job_id": current["id"],
            "source_job_id": row["source_job_id"],
            "was_chars": len(current["body"] or ""),
            "now_chars": len(body),
            "body": body,
            "visa_was": current["visa_status"],
            "visa_now": verdict["status"],
            "visa_text": verdict.get("evidence"),
            "visa_pathways": verdict.get("pathways"),
            # Only fill an application URL the posting itself carries, and only
            # where one is missing: a listing-derived value is not improved by
            # guessing from a link label.
            "official_url": (row.get("apply_url")
                             if row.get("apply_url") and not current["official_url"]
                             else None),
        })
    return updates, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsonl")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    records, malformed = load_records(args.jsonl)
    conn = open_read_only(args.db)
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if int(version) != int(FACULTY_JOBS_SCHEMA_VERSION):
            raise SystemExit(f"schema user_version={version}, expected "
                             f"{FACULTY_JOBS_SCHEMA_VERSION}")
        updates, skipped = plan(conn, records)
    finally:
        conn.close()

    gained = sum(u["now_chars"] - u["was_chars"] for u in updates)
    visa_changes = [u for u in updates if u["visa_was"] != u["visa_now"]]
    urls = [u for u in updates if u["official_url"]]
    print(f"records read from {args.jsonl}: {len(records)}"
          + (f"  ({malformed} malformed line(s) skipped)" if malformed else ""))
    print(f"  postings that would gain text: {len(updates)}")
    print(f"  characters gained:             {gained:,}")
    print(f"  visa verdicts that change:     {len(visa_changes)}")
    print(f"  application URLs filled:       {len(urls)}")
    print(f"  skipped:                       {len(skipped)}")
    for _id, reason in skipped[:5]:
        print(f"    {_id}: {reason}")
    for u in visa_changes[:10]:
        print(f"    #{u['job_id']:<7}{str(u['visa_was']):20}-> {u['visa_now']}")
    if not args.apply or not updates:
        print("\nno --apply: nothing was written" if not args.apply else "\nnothing to write")
        return

    inventory = preflight(args.db, "hej_detail_bodies")
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        conn = sqlite3.connect(str(args.db), timeout=120)
        conn.row_factory = sqlite3.Row
        try:
            for i, u in enumerate(updates, 1):
                conn.execute("""
                    UPDATE jobs SET description_excerpt = ?, visa_status = ?,
                                    visa_text = ?, visa_pathways = ?,
                                    official_url = COALESCE(?, official_url),
                                    updated_at = ?
                     WHERE id = ?
                """, (u["body"], u["visa_now"], u["visa_text"],
                      json.dumps(u["visa_pathways"], ensure_ascii=False)
                      if u["visa_pathways"] else None,
                      u["official_url"], raw_archive.now_utc(), u["job_id"]))
                conn.execute("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at, action, job_id, old_value, new_value, reason)
                    VALUES (?,?,?,?,?,?)
                """, (raw_archive.now_utc(), "hej_detail_body", u["job_id"],
                      json.dumps({"description_length": u["was_chars"],
                                  "visa_status": u["visa_was"]}, ensure_ascii=False),
                      json.dumps({"description_length": u["now_chars"],
                                  "visa_status": u["visa_now"]}, ensure_ascii=False),
                      "Posting body read from the board's own detail page in an "
                      "ordinary visible browser. The listing card carries about "
                      "190 characters; the posting itself carries thousands, and "
                      "the work-authorisation paragraph is only in the latter."))
                if i % 200 == 0:
                    conn.commit()
            conn.commit()
        finally:
            conn.close()
    print(f"\nwrote {len(updates)} postings")
    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
