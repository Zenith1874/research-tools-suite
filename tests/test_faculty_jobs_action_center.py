"""Evidence, independent axes, timing and cross-surface action contracts."""
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from services import faculty_jobs_requirements as req
from services.faculty_jobs_actions import action_sql, position_filter, position_sql, ACTION_VIEWS
from services.faculty_jobs_normalizer import parse_deadline
from services.faculty_jobs_service import ensure_faculty_jobs_tables, build_faculty_jobs_payload, build_faculty_job_summary, export_faculty_jobs_csv, _sanitize_saved_search_query


class RequirementsTests(unittest.TestCase):
    def parse(self, content, title="Assistant Professor of Information Systems", kind="official_posting"):
        html = f'<html><h1>{title}</h1><p>Regional University</p>{content}</html>'
        return req.parse_posting(html, {"title_raw": title, "institution_name": "Regional University"}, "https://example.edu/job/7", kind)

    def test_explicit_five_fields_keep_literal_evidence_and_review(self):
        result = self.parse('''<a href="/apply/7">Apply now</a>
          <p>Faculty teach three courses per semester.</p>
          <p>Candidates must demonstrate research resulting in peer-reviewed publications.</p>
          <p>Target Start Date: August 17, 2027</p>
          <p>Application Process:</p><p>A completed application will consist of:</p>
          <ul><li>A cover letter</li><li>A curriculum vitae</li><li>Three references</li></ul>
          <p>The position is open until filled. First consideration will be given to completed applications received no later than October 11, 2026.</p>''')
        self.assertEqual("ok", result["status"])
        for name in req.REQUIRED_FIELDS:
            self.assertEqual("supported", result["fields"][name]["status"], name)
            self.assertIn(result["fields"][name]["quote"], result["text"])
        self.assertEqual("https://example.edu/apply/7", result["fields"]["application_url"]["value"])
        self.assertEqual("2026-10-11", result["fields"]["review_date"]["normalized_date"])
        self.assertEqual("not_stated", result["fields"]["hard_deadline"]["status"])
        self.assertEqual("open_until_filled", result["fields"]["recruitment_mode"]["value"])

    def test_department_context_is_not_job_contract_or_load(self):
        result = self.parse('<p>Our department has clinical faculty. Students must complete 30 credit hours per year.</p><p>Faculty members share a strong commitment to innovative scholarship.</p>')
        self.assertEqual("not_stated", result["fields"]["teaching_load"]["status"])
        self.assertEqual("not_stated", result["fields"]["research_requirements"]["status"])

    def test_failed_and_identity_reads_cannot_be_not_stated(self):
        denied = self.parse('<p>Access denied. Verify you are human.</p>')
        self.assertEqual("blocked", denied["status"])
        mismatch = req.parse_posting('<h1>Assistant Professor of Marketing</h1><p>Regional University</p>' + '<p>Other position details.</p>' * 20, {"title_raw":"Assistant Professor of Information Systems", "institution_name":"Regional University"}, "https://example.edu/job/8")
        self.assertEqual("identity_unverified", mismatch["status"])
        self.assertTrue(all(x["status"] == "needs_verification" for x in mismatch["fields"].values()))

    def test_title_body_start_conflict_is_not_silently_resolved(self):
        result = self.parse('<p>Appointment starting September 1, 2024.</p>' * 5, title="Assistant Professor Information Systems starting 2026")
        self.assertEqual("needs_verification", result["fields"]["start_date"]["status"])

    def test_bare_term_is_not_fabricated_calendar_date(self):
        result = self.parse('<p>The assistant professor will begin during the Fall Semester of 2027. Regional University welcomes qualified candidates.</p>' * 2)
        self.assertEqual("supported", result["fields"]["start_date"]["status"])
        self.assertIsNone(result["fields"]["start_date"]["normalized_date"])

    def test_deadline_is_qualified_without_losing_negation(self):
        parsed = parse_deadline("Application Deadline: October 1, 2026 (Applications accepted until filled or closed)", return_details=True)
        self.assertEqual("open_until_filled", parsed["mode"])
        negative = parse_deadline("Application Deadline: October 1, 2026 Open Until Filled: No", return_details=True)
        self.assertEqual("fixed", negative["mode"])
        result = self.parse('<p>Application Deadline: October 1, 2026 (Applications accepted until filled or closed)</p>' * 3)
        self.assertEqual("needs_verification", result["fields"]["hard_deadline"]["status"])

    def test_board_evidence_is_not_official_application_verification(self):
        result = self.parse('<a href="https://example.edu/apply/1">Apply now</a><p>Faculty teach three courses per semester. The successful candidate will maintain a productive research program.</p>', kind="job_board")
        self.assertEqual("not_stated", result["fields"]["application_url"]["status"])

    def test_official_jobposting_jsonld_is_not_mistaken_for_a_blocked_shell(self):
        payload = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Lecturer in School of Business",
            "hiringOrganization": {"name": "Regional University"},
            "description": "Teaching responsibilities may range from one to five courses per semester. To Apply: upload a cover letter and resume or CV.",
        }
        html = '<html><script type="application/ld+json">' + json.dumps(payload) + '</script><div id="app"></div></html>'
        result = req.parse_posting(html, {"title_raw":"Lecturer in School of Business", "institution_name":"Regional University"}, "https://example.edu/job/9")
        self.assertEqual("ok", result["status"])
        self.assertEqual("supported", result["fields"]["teaching_load"]["status"])
        self.assertEqual("supported", result["fields"]["materials"]["status"])
        self.assertIn("one to five courses per semester", result["fields"]["teaching_load"]["quote"])
        self.assertNotIn("To Apply", result["fields"]["teaching_load"]["quote"])


class ActionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.template = Path(cls.temp.name) / "template.db"
        ensure_faculty_jobs_tables(cls.template)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.db = Path(self.temp.name) / (self._testMethodName + ".db")
        source, self.conn = sqlite3.connect(self.template), sqlite3.connect(self.db)
        source.backup(self.conn)
        source.close()
        self.conn.row_factory = sqlite3.Row
        today = date.today().isoformat()
        for jid, title, track, appointment in [(1,"TT Assistant Professor Information Systems","tenure_track","full_time"), (2,"Clinical Lecturer in Management","non_tenure_track","full_time"), (3,"Adjunct Lecturer in Management","non_tenure_track","adjunct"), (4,"Professor of Marketing","unknown","unknown")]:
            self.conn.execute("""INSERT INTO jobs(id,canonical_key,title_raw,title_normalized,status,business_scope,derived_quality,faculty_market_eligible,faculty_market_role,track_type,appointment_type,discipline_primary,first_seen_at,last_seen_at,created_at,updated_at) VALUES (?,?,?,?,'open','business_school','accepted',1,'faculty',?,?,'Management',?,?,?,?)""", (jid, str(jid),title,title,track,appointment,today,today,today,today))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def read(self, jid=1, stamp=None, status="ok", kind="official_posting"):
        fields = req.empty_fields("not_stated" if status == "ok" else "blocked")
        if status == "ok":
            for key in req.REQUIRED_FIELDS:
                fields[key] = {"status":"supported", "value":"literal evidence", "quote":"literal evidence", "normalized_date":None}
            fields["review_date"] = {"status":"supported", "value":"First review", "quote":"First review", "normalized_date":(date.today()+timedelta(days=10)).isoformat()}
        return {"job_id":jid,"source_url":"https://example.edu/job/1", "source_kind":kind,"captured_at":stamp or date.today().isoformat()+"T01:00:00Z", "status":status,"identity_verified":status=="ok","parser_version":req.PARSER_VERSION,"fields":fields}

    def test_role_axes_independent_and_overlapping(self):
        expected = {"tt":[1],"teaching":[2,3],"clinical":[2],"adjunct":[3],"other":[4]}
        for role, ids in expected.items():
            payload = build_faculty_jobs_payload(self.db, {"position_type":role})
            self.assertEqual(ids, sorted(job["id"] for job in payload["jobs"]))
        self.assertEqual([2,3], sorted(job["id"] for job in build_faculty_jobs_payload(self.db,{"position_type":"teaching,adjunct"})["jobs"]))

    def test_action_list_summary_export_parity_and_transparent_exclusion(self):
        req.import_read(self.conn, self.read())
        self.conn.commit()
        for action in ACTION_VIEWS:
            query = {"action_view":action}
            listed = build_faculty_jobs_payload(self.db, query)
            summary = build_faculty_job_summary(self.db,query)["summary"]
            exported = list(csv.DictReader(io.StringIO(export_faculty_jobs_csv(self.db,query))))
            self.assertEqual(listed["pagination"]["total"],summary["matching_records"])
            self.assertEqual(len(exported),summary["action_counts"][action])
        self.assertEqual([1,2], sorted(job["id"] for job in build_faculty_jobs_payload(self.db,{"action_view":"worth_review"})["jobs"]))
        self.assertEqual([1], [job["id"] for job in build_faculty_jobs_payload(self.db,{"action_view":"review_soon"})["jobs"]])

    def test_idempotency_and_failed_attempt_does_not_renew_verification(self):
        first = self.read()
        self.assertEqual(1,req.import_read(self.conn,first))
        self.assertEqual(0,req.import_read(self.conn,first))
        req.import_read(self.conn,self.read(stamp=date.today().isoformat()+"T02:00:00Z",status="blocked"))
        self.conn.commit()
        job = build_faculty_jobs_payload(self.db,{"q":"TT Assistant"})["jobs"][0]
        self.assertEqual(first["captured_at"],job["last_verified_at"])
        self.assertTrue(job["timing"]["last_attempt_at"] > job["last_verified_at"])
        self.assertIn("needs_verification", job["actions"])

    def test_saved_search_keeps_both_axes_and_action(self):
        query = {"career_view":"r2_teaching","country":"US","position_type":"teaching,clinical","action_view":"review_soon"}
        self.assertEqual({**query,"scope":"business"},_sanitize_saved_search_query(query))
        for value in ("all OR 1=1", "bad"):
            with self.assertRaises(ValueError):
                action_sql(value)
            with self.assertRaises(ValueError):
                position_filter(value)

    def test_department_is_is_not_a_marketing_vacancys_discipline(self):
        self.conn.execute("UPDATE jobs SET title_raw='Assistant Professor, Marketing - Department of Business Administration & Information Systems',discipline_primary='Information Systems / MIS' WHERE id=4")
        self.conn.commit()
        all_jobs = build_faculty_jobs_payload(self.db,{})["jobs"]
        marketing = next(job for job in all_jobs if job["id"] == 4)
        self.assertTrue(marketing["discipline_needs_verification"])
        self.assertNotIn("worth_review",marketing["actions"])
        self.assertIn("needs_verification",marketing["actions"])


if __name__ == "__main__":
    unittest.main()
