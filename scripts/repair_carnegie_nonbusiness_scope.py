"""Preview or guard a one-job non-business correction from explicit title evidence.

Does not delete the job, alter raw source evidence or change private preferences.
Both job ID and the observed official URL must match; no bulk mode is provided.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.faculty_jobs_normalizer import classify_business_scope
from services.faculty_jobs_service import FACULTY_DB_PATH, _record_derived_repair_provenance
from services.faculty_jobs_sources.base import now_utc
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight


def inspect_job(path, job_id, expected_url):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""SELECT j.* FROM jobs j WHERE j.id=? AND j.official_url=?
            AND EXISTS (SELECT 1 FROM job_sources js JOIN sources s ON s.id=js.source_id
                        WHERE js.job_id=j.id AND s.name='carnegie_official')""",
                           (job_id, expected_url)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Expected Carnegie-linked job and official URL did not match.")
    result = classify_business_scope(title=row["title_raw"], department=row["department"])
    if result["scope"] != "non_business" or result["confidence"] != "high":
        raise ValueError("Explicit title/department does not support a high-confidence non-business correction.")
    return dict(row), result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", type=int, required=True)
    parser.add_argument("--expected-url", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    row, result = inspect_job(FACULTY_DB_PATH, args.job_id, args.expected_url)
    print(json.dumps({"job_id": row["id"], "title": row["title_raw"],
                      "old_scope": row["business_scope"], "proposed": result}, indent=2))
    if not args.apply or row["business_scope"] == result["scope"]:
        return 0
    inventory = preflight(FACULTY_DB_PATH, "carnegie_nonbusiness_scope_repair")
    try:
        with guarded_write():
            conn = sqlite3.connect(FACULTY_DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                with conn:
                    changed = conn.execute("""UPDATE jobs SET business_scope=?,
                        business_scope_confidence=?,business_scope_reason=?
                        WHERE id=? AND official_url=? AND title_raw=? AND business_scope=?""",
                        (result["scope"], result["confidence"], result["reason"],
                         row["id"], args.expected_url, row["title_raw"], row["business_scope"]))
                    if changed.rowcount != 1:
                        raise RuntimeError("Concurrent job change; correction was not applied.")
                    _record_derived_repair_provenance(
                        conn, row["id"], "business_scope", result["scope"], result["reason"])
                    conn.execute("""INSERT INTO faculty_job_repair_audit
                        (observed_at,action,job_id,old_value,new_value,reason)
                        VALUES (?,?,?,?,?,?)""", (now_utc(), "carnegie_nonbusiness_title_repair",
                            row["id"], row["business_scope"], result["scope"], result["reason"]))
            finally:
                conn.close()
    finally:
        postflight(FACULTY_DB_PATH, inventory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
