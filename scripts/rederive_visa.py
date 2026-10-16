#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-run the visa classifier over stored text after a rule change.

The classifier is the authority for this field, so when its rules move, the
stored values are stale until they are recomputed. No page is fetched: this
reads only text already held, so it can only correct a reading, never invent
one.

Every change is written to the repair audit with the old and new value, so a
rule change that turns out to be wrong can be found and reversed by the run
that made it.

    python scripts/rederive_visa.py --status
    python scripts/rederive_visa.py --apply
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.faculty_jobs_normalizer import classify_visa
from services.faculty_jobs_service import FACULTY_DB_PATH
from services.faculty_jobs_sources.base import now_utc
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight

REASON = ("Visa classifier re-derived after a rule change. Funding sponsorship "
          "-- scholarship, sponsored research, an industry sponsor -- no longer "
          "answers an immigration question: 'Scholarship sponsorship is "
          "available for doctoral students' had matched the offer pattern.")


def plan(conn):
    """What would change, without writing anything."""
    changes = []
    for row in conn.execute("""
            SELECT id, title_raw, department, description_excerpt,
                   COALESCE(visa_status,'unknown') AS visa_status, visa_text
            FROM jobs"""):
        combined = " ".join(part for part in (
            row["title_raw"], row["department"] or "",
            row["description_excerpt"] or "") if part)
        verdict = classify_visa(combined)
        if verdict["status"] != row["visa_status"]:
            changes.append({
                "job_id": row["id"],
                "title": (row["title_raw"] or "")[:56],
                "from": row["visa_status"],
                "to": verdict["status"],
                "evidence": (verdict["evidence"] or "")[:90],
            })
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the corrections")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args(argv)

    if not args.apply:
        conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            changes = plan(conn)
        finally:
            conn.close()
        print(f"{len(changes)} job(s) would change")
        for change in changes[:25]:
            print(f"  job {change['job_id']:<6} {change['from']:<32} -> {change['to']}")
            print(f"    {change['title']}")
            if change["evidence"]:
                print(f"    evidence: {change['evidence']}")
        if not changes:
            print("  nothing to correct; stored values already match the rules")
        else:
            print("\nRe-run with --apply to write them.")
        return 0

    inventory = preflight(args.db, "visa_rederive")
    conn = sqlite3.connect(args.db, timeout=120)
    conn.row_factory = sqlite3.Row
    try:
        changes = plan(conn)
        with guarded_write():
            for change in changes:
                conn.execute("""
                    INSERT INTO faculty_job_repair_audit
                      (observed_at, action, job_id, old_value, new_value, reason)
                    VALUES (?,?,?,?,?,?)
                """, (now_utc(), "visa_status_rederive", change["job_id"],
                      json.dumps({"visa_status": change["from"]}, ensure_ascii=False),
                      json.dumps({"visa_status": change["to"]}, ensure_ascii=False),
                      REASON))
                row = conn.execute(
                    "SELECT title_raw, department, description_excerpt FROM jobs WHERE id=?",
                    (change["job_id"],)).fetchone()
                combined = " ".join(part for part in (
                    row["title_raw"], row["department"] or "",
                    row["description_excerpt"] or "") if part)
                verdict = classify_visa(combined)
                conn.execute("""
                    UPDATE jobs SET visa_status=?, visa_text=?, visa_pathways=?
                    WHERE id=?
                """, (verdict["status"], verdict["evidence"],
                      ",".join(verdict["pathways"]) or None, change["job_id"]))
            conn.commit()
        print(f"corrected {len(changes)} job(s); each change is in the repair audit")
        print("  visa distribution now:",
              dict(conn.execute("SELECT COALESCE(visa_status,'?'), COUNT(*) "
                                "FROM jobs GROUP BY 1 ORDER BY 2 DESC").fetchall()))
    finally:
        conn.close()
    postflight(args.db, inventory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
