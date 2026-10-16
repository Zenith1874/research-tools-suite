"""Read-only production acceptance; writes only a uniquely named JSON report."""
import argparse
import csv
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.repair_faculty_job_priorities import protected_fingerprints
from services.faculty_jobs_write_guard import open_read_only
from services.faculty_jobs_service import now_utc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5001")
    parser.add_argument("--db", type=Path, default=ROOT / "data/faculty_jobs.db")
    parser.add_argument("--repair-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if urlsplit(args.base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Acceptance is local-only")
    if args.report.exists():
        parser.error("Output already exists; choose a new path")

    def get(path, query=None, raw=False):
        url = args.base + path + ("?" + urlencode(query) if query else "")
        with urlopen(url, timeout=30) as response:
            text = response.read().decode("utf-8-sig")
        return text if raw else json.loads(text)

    report = {"at": now_utc(), "base": args.base, "views": {}}
    for view in ["all", "r1", "r2_teaching", "r2", "teaching", "unclassified"]:
        query = {"scope": "business_school", "career_view": view}
        listed = get("/api/faculty-jobs", {**query, "limit": 200})
        summary = get("/api/faculty-jobs/summary", query)["summary"]
        rows = list(csv.DictReader(io.StringIO(get("/api/faculty-jobs/export.csv", query, raw=True))))
        analytics = get("/api/job-market-analytics", query)["analytics"]
        total = listed["pagination"]["total"]
        assert total == summary["matching_records"] == len(rows) == analytics["active_jobs"], view
        assert not ({"notes", "application_state", "fit_score", "cv_version"} & set(rows[0] if rows else {}))
        assert all(row["status"] in {"open", "likely_open", "closing_soon"} for row in rows)
        if view == "r1":
            assert all(row["university_level"] == "R1" and row["carnegie_year"] == "2025" for row in rows)
        elif view == "r2_teaching":
            assert all(row["university_level"] != "R1" and (row["university_level"] == "R2" or row["teaching_proxy"] == "1") for row in rows)
        report["views"][view] = {"list": total, "summary": summary["matching_records"], "csv": len(rows), "analytics": analytics["active_jobs"]}
    official = get("/api/faculty-jobs", {"source": "carnegie_official", "university_level": "R2"})
    official_ids = sorted(job["id"] for job in official["jobs"])
    assert set([6506, 6507, 6508]).issubset(official_ids)
    report["official_r2_ids"] = official_ids
    expired = get("/api/faculty-jobs/4791")["job"]
    assert expired["status"] == "closed" and expired["observed_status"] == "closing_soon"
    report["expired_sample"] = {key: expired[key] for key in ["id", "status", "observed_status", "deadline_date", "status_basis"]}
    corrected = get("/api/faculty-jobs/2895")["job"]
    assert corrected["track_type"] == "non_tenure_track"
    report["non_tenure_sample"] = {"id": 2895, "track_type": corrected["track_type"]}
    conn = open_read_only(args.db)
    try:
        report["schema"] = conn.execute("PRAGMA user_version").fetchone()[0]
        report["migration_ledger"] = conn.execute("SELECT MAX(version) FROM faculty_job_migrations").fetchone()[0]
        report["integrity"] = conn.execute("PRAGMA quick_check").fetchone()[0]
        report["foreign_key_violations"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        with args.repair_report.open(encoding="utf-8") as handle:
            repaired = json.load(handle)
        report["protected_content_unchanged"] = repaired["protected_after"] == protected_fingerprints(conn)
        assert report["protected_content_unchanged"], "Protected data changed since the repair; investigate before claiming acceptance"
        assert report["integrity"] == "ok" and not report["foreign_key_violations"]
        assert report["schema"] == report["migration_ledger"] == 86
    finally:
        conn.close()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
