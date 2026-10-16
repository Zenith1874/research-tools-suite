"""Guarded, repeatable local-only repair. Default mode previews without DB writes.

Usage: python scripts/repair_faculty_job_priorities.py --db PATH [--apply]
       [--report outputs/unique-name.json] [--public-file preserved-release.xlsx]
No crawl, source replay, raw-data deletion, or private-state rewrite is performed.
Expired fixed deadlines are handled at read time, preserving observed status.
"""
import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.faculty_jobs_career_views import PUBLIC_FILE, import_profiles, link_institution, read_public_profiles
from services.faculty_jobs_lifecycle import effective_status
from services.faculty_jobs_normalizer import infer_track
from services.faculty_jobs_service import ensure_faculty_jobs_tables, _record_derived_repair_provenance, now_utc
from services.faculty_jobs_write_guard import discover_private_tables, guarded_write, open_read_only, postflight, preflight


def protected_fingerprints(conn):
    """Hash actual row contents, not just counts; never disclose private values."""
    tables = sorted(set(discover_private_tables(conn)) | {"source_job_records", "job_sources", "source_record_decisions"})
    result = {}
    for name in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        digest, count = hashlib.sha256(), 0
        for row in conn.execute(f"SELECT * FROM {quoted} ORDER BY rowid"):
            digest.update(json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        result[name] = {"rows": count, "sha256": digest.hexdigest()}
    # The repair may change these two derived columns only, never the posting
    # text, identity, source timestamps, deadline evidence, or observed status.
    fields = [row[1] for row in conn.execute("PRAGMA table_info(jobs)") if row[1] not in {"track_type", "updated_at"}]
    digest, count = hashlib.sha256(), 0
    columns = ",".join('"' + field.replace('"', '""') + '"' for field in fields)
    for row in conn.execute(f"SELECT {columns} FROM jobs ORDER BY id"):
        digest.update(json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    result["jobs_except_repaired_columns"] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def repair_plan(conn):
    tracks, expired = [], []
    for row in conn.execute("SELECT id,title_raw,description_excerpt,department,track_type,status,deadline_mode,deadline_date FROM jobs ORDER BY id"):
        title_track = infer_track(row["title_raw"])
        combined = " ".join(str(row[key] or "") for key in ("title_raw", "department", "description_excerpt"))
        track = title_track if title_track != "unknown" else infer_track(combined)
        explicit_negative = re.search(r"\bnon[\s\-\u2010-\u2015]*(?:tenur(?:e|ed)\b|tt\b)|\bnot(?: a)? tenure[- ]track\b", combined, re.I)
        if row["track_type"] == "tenure_track" and explicit_negative and track in {"non_tenure_track", "unknown"}:
            tracks.append({"id": row["id"], "title": row["title_raw"], "old": row["track_type"], "new": track,
                           "evidence": row["title_raw"] if title_track == "non_tenure_track" else combined})
        if effective_status(row) == "closed" and row["status"] in {"open", "likely_open", "closing_soon"}:
            expired.append(row["id"])
    return {"track_repairs": tracks, "elapsed_fixed_deadline_ids": expired}


def apply_repairs(conn, profiles):
    levels = import_profiles(conn, profiles)
    outcomes = Counter()
    for row in conn.execute("SELECT id FROM institutions ORDER BY id").fetchall():
        outcomes[link_institution(conn, row["id"])] += 1
    plan = repair_plan(conn)
    for change in plan["track_repairs"]:
        reason = ("Explicit non-tenure/non-TT evidence; a contract in the title takes precedence. "
                  "Mixed or conflicting excerpt evidence remains unknown: " + change["evidence"])
        conn.execute("UPDATE jobs SET track_type=?,updated_at=? WHERE id=?", (change["new"], now_utc(), change["id"]))
        _record_derived_repair_provenance(conn, change["id"], "track_type", change["new"], reason)
        conn.execute("""INSERT INTO faculty_job_repair_audit
            (observed_at,action,job_id,old_value,new_value,reason) VALUES (?,?,?,?,?,?)""",
            (now_utc(), "non_tenure_evidence_repair", change["id"], change["old"], change["new"], reason))
    return {**plan, "catalogue_levels": levels, "institution_links": dict(outcomes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/faculty_jobs.db")
    parser.add_argument("--public-file", type=Path, default=PUBLIC_FILE)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.report and args.report.exists():
        parser.error("Report already exists; choose a new path")
    profiles = read_public_profiles(args.public_file)
    conn = open_read_only(args.db)
    try:
        before = protected_fingerprints(conn)
        report = {"mode": "apply" if args.apply else "preview", "at": now_utc(),
                  "db": str(args.db.resolve()), "source_file": str(args.public_file.resolve()),
                  "source_sha256": profiles[0]["source_sha256"], "catalogue_rows": len(profiles),
                  "catalogue_levels": dict(Counter(p["research_level"] for p in profiles)),
                  "schema_before": conn.execute("PRAGMA user_version").fetchone()[0],
                  "protected_before": before, **repair_plan(conn)}
    finally:
        conn.close()
    if args.apply:
        inventory = preflight(args.db, "faculty_priority_career_views", echo=lambda message: print(message, file=sys.stderr))
        with guarded_write():
            ensure_faculty_jobs_tables(args.db)
            conn = sqlite3.connect(str(args.db), timeout=60)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    report.update(apply_repairs(conn, profiles))
                    after = protected_fingerprints(conn)
                    if before != after:
                        raise RuntimeError("Protected evidence/private content changed; repair rolled back")
                    report["protected_after"] = after
            finally:
                conn.close()
        report["postflight"] = postflight(args.db, inventory, echo=lambda message: print(message, file=sys.stderr))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: value for key, value in report.items() if key not in {"protected_before", "protected_after", "track_repairs", "elapsed_fixed_deadline_ids"}}, ensure_ascii=False, indent=2))
    print(f"track_repairs={len(report['track_repairs'])} elapsed_fixed_deadlines={len(report['elapsed_fixed_deadline_ids'])}")


if __name__ == "__main__":
    main()
