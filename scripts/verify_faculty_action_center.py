"""Read-only live or isolated acceptance; produces a new JSON report."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import io
import json
import hashlib
from pathlib import Path
import sys
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.faculty_jobs_actions import PREFERRED_QUERY, ACTION_VIEWS, POSITION_TYPES
from services.faculty_jobs_service import build_faculty_jobs_payload, build_faculty_job_summary, export_faculty_jobs_csv, build_faculty_job_detail
from services.faculty_jobs_lifecycle import effective_status
from services.faculty_jobs_normalizer import infer_track
from services.faculty_jobs_write_guard import open_read_only
from scripts.activate_faculty_action_center import fingerprints, save_new


def verify(db, report, base_url=None):
    conn = open_read_only(db)
    before = fingerprints(conn)
    checks = []
    def read(query):
        if base_url:
            response = requests.get(base_url + '/api/faculty-jobs', params={**query,"limit":200}, timeout=30)
            response.raise_for_status()
            return response.json()
        return build_faculty_jobs_payload(db, {**query,"limit":200})
    for changes in ([{}] + [{"action_view":x} for x in ACTION_VIEWS[1:]] + [{"position_type":x} for x in POSITION_TYPES] + [{"career_view":"r1"},{"position_type":"teaching,clinical"}]):
        query = {**PREFERRED_QUERY, **changes}
        listed = read(query)
        if base_url:
            response = requests.get(base_url + '/api/faculty-jobs/summary', params=query, timeout=30)
            response.raise_for_status()
            summary = response.json()["summary"]
            exported_response = requests.get(base_url + '/api/faculty-jobs/export.csv', params=query, timeout=30)
            exported_response.raise_for_status()
            exported_response.encoding = "utf-8"
            exported = exported_response.text
        else:
            summary = build_faculty_job_summary(db,query)["summary"]
            exported = export_faculty_jobs_csv(db,query)
        csv_rows = list(csv.DictReader(io.StringIO(exported.lstrip('\ufeff'))))
        assert listed["pagination"]["total"] == summary["matching_records"] == len(csv_rows), query
        assert not listed["pagination"]["has_more"], "Bounded acceptance cohort grew beyond one page"
        assert all("personal_state" not in job and "fit" not in job for job in listed["jobs"])
        assert all("notes" not in row and "application_state" not in row for row in csv_rows)
        checks.append({"query":query,"count":len(csv_rows),"ids":[job["id"] for job in listed["jobs"]],"parity":True})
        print(json.dumps({"query_changes":changes,"count":len(csv_rows),"parity":True}),flush=True)
    preferred = read(PREFERRED_QUERY)["jobs"]
    r1_ids = set(checks[-2]["ids"])
    assert not r1_ids & {job["id"] for job in preferred}
    for jid in (6506,6507,6508):
        job = next(job for job in preferred if job["id"]==jid)
        assert job["university_level"] == "R2" and job["carnegie_unitid"], jid
        assert job["timing"]["recruitment_mode"] == "open_until_filled", jid
        assert job["timing"]["hard_deadline"] is None, jid
        assert job["last_verified_at"], jid
        assert job["status"] != "closing_soon", jid
        assert "clinical" not in job["position_types"], jid
    wrongly_tt = [row["id"] for row in conn.execute("SELECT id,title_raw,track_type FROM jobs WHERE track_type='tenure_track'") if infer_track(row["title_raw"]) == "non_tenure_track"]
    assert not wrongly_tt, wrongly_tt
    expired_closing = [row["id"] for row in conn.execute("SELECT id,status,deadline_mode,deadline_date FROM jobs WHERE status='closing_soon'") if effective_status(row)=="closing_soon" and row["deadline_mode"]=="fixed" and str(row["deadline_date"]) < datetime.now().date().isoformat()]
    assert not expired_closing
    coverage = {"cohort":len(preferred),"successful_official_reads":sum(bool(job["last_verified_at"]) for job in preferred),
                "successful_board_reads":sum(job["requirements"].get("status")=="ok" and job["requirements"].get("source_kind")=="job_board" for job in preferred),
                "no_successful_read":sum(job["requirements"].get("status")!="ok" for job in preferred),
                "official_supported_fields":dict(Counter(name for job in preferred if job["last_verified_at"] for name, field in job["requirements"]["fields"].items() if field["status"]=="supported")),
                "fully_documented_official_five_fields":sum(job["requirements"].get("official_supported_count")==5 for job in preferred)}
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    assert quick=="ok" and fk==0
    assert before == fingerprints(conn)
    result = {"as_of":datetime.now(timezone.utc).isoformat(),"db":str(db),"base_url":base_url,"checks":checks,
              "rules_sha256":hashlib.sha256((ROOT / 'services/faculty_jobs_actions.py').read_bytes()).hexdigest(),
              "coverage":coverage,"r1_r2_disjoint":True,"explicit_non_tt_mislabeled_tt":len(wrongly_tt),
              "elapsed_hard_deadlines_still_closing_soon":len(expired_closing),"quick_check":quick,"foreign_key_violations":fk,
              "readonly_protected_fingerprints_unchanged":True}
    save_new(report,result)
    conn.close()
    print(json.dumps(coverage),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',required=True)
    parser.add_argument('--report',required=True)
    parser.add_argument('--base-url')
    args=parser.parse_args()
    verify(args.db,args.report,args.base_url)
