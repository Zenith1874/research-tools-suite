# -*- coding: utf-8 -*-
"""The status report is a check, not a printout.

Every figure is read from the database at run time, and the invariants that used
to be verified by hand after each merge are asserted here instead: no job may
point at a retired entity, no source link may dangle, and integrity must be
clean. A report that prints a violation while exiting zero would be worse than
no report at all.
"""

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import ensure_faculty_jobs_tables

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "academic_career_status_report", ROOT / "scripts" / "academic_career_status_report.py")
report_module = importlib.util.module_from_spec(_spec)
sys.modules["academic_career_status_report"] = report_module
_spec.loader.exec_module(report_module)

NOW = "2026-08-26T00:00:00Z"


class StatusReportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,is_current,created_at,"
            "updated_at) VALUES (1,'Example University','example university',1,?,?)", (NOW, NOW))
        self.conn.execute(
            "INSERT INTO business_schools (id,institution_id,official_name,normalized_name,"
            "business_research_tier,is_current,created_at,updated_at) "
            "VALUES (1,1,'College of Business','college of business','T4',1,?,?)", (NOW, NOW))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add_job(self, job_id, institution_id=1, school_id=1):
        self.conn.execute(
            "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,"
            "school_id,business_scope,derived_quality,faculty_market_eligible,status,city,"
            "first_seen_at,last_seen_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?, 'business_school','accepted',1,'open','Austin',?,?,?,?)",
            (job_id, f"k{job_id}", "Assistant Professor", "assistant professor",
             institution_id, school_id, NOW, NOW, NOW, NOW))
        self.conn.commit()

    def collect(self):
        return report_module.collect(self.db, astar_path="/nonexistent.db")

    def test_a_clean_database_reports_no_failures(self):
        self.add_job(1)
        report = self.collect()
        self.assertEqual([], report_module.failures(report))
        self.assertEqual("ok", report["integrity"]["quick_check"])

    def test_market_coverage_is_computed_from_the_database(self):
        self.add_job(1)
        self.add_job(2, school_id=None)
        report = self.collect()
        self.assertEqual(2, report["market"]["jobs"])
        self.assertEqual(1, report["market"]["with_school_entity"])
        self.assertEqual(2, report["market"]["with_city_or_state"])

    def test_a_job_on_a_retired_school_is_reported_as_a_failure(self):
        self.add_job(1)
        self.conn.execute("UPDATE business_schools SET is_current=0 WHERE id=1")
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["jobs_on_retired_school"])
        problems = report_module.failures(report)
        self.assertTrue(any("retired school" in item for item in problems), problems)

    def test_a_job_on_a_retired_institution_is_reported_as_a_failure(self):
        self.add_job(1)
        self.conn.execute("UPDATE institutions SET is_current=0 WHERE id=1")
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["jobs_on_retired_institution"])
        self.assertTrue(any("retired institution" in item
                            for item in report_module.failures(report)))

    def test_a_dangling_source_link_is_reported_as_a_failure(self):
        self.add_job(1)
        # The source catalogue is seeded by ensure_faculty_jobs_tables; reuse a row.
        source_id = self.conn.execute("SELECT id FROM sources LIMIT 1").fetchone()["id"]
        self.conn.execute(
            "INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,"
            "first_seen,last_seen) VALUES (999,?,'x','https://example.edu/x',1,?,?)",
            (source_id, NOW, NOW))
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["source_links_without_job"])
        self.assertTrue(any("no job" in item for item in report_module.failures(report)))

    def test_the_rendered_report_states_the_verdict(self):
        self.add_job(1)
        text = report_module.render(self.collect())
        self.assertIn("Every invariant holds", text)
        self.assertIn("Academic Career status", text)

    def test_a_failing_report_says_so_in_the_rendered_text(self):
        self.add_job(1)
        self.conn.execute("UPDATE business_schools SET is_current=0 WHERE id=1")
        self.conn.commit()
        text = report_module.render(self.collect())
        self.assertNotIn("Every invariant holds", text)
        self.assertIn("retired school", text)

    def test_the_tier_note_states_that_the_footprint_does_not_promote(self):
        self.add_job(1)
        text = report_module.render(self.collect())
        self.assertIn("does not move a tier", text)

    def test_a_missing_astar_database_is_reported_not_fatal(self):
        self.add_job(1)
        report = self.collect()
        self.assertFalse(report["astar"]["available"])
        self.assertEqual([], report_module.failures(report))


if __name__ == "__main__":
    unittest.main()
