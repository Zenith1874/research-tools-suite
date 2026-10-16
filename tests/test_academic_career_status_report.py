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

from services.faculty_jobs_scope import active_sql
from services.faculty_jobs_service import (
    build_faculty_job_summary,
    build_faculty_jobs_payload,
    ensure_faculty_jobs_tables,
)

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

    def add_job(self, job_id, institution_id=1, school_id=1,
                status="open", title="Assistant Professor"):
        self.conn.execute(
            "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,"
            "school_id,business_scope,derived_quality,faculty_market_eligible,status,city,"
            "first_seen_at,last_seen_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?, 'business_school','accepted',1,?,'Austin',?,?,?,?)",
            (job_id, f"k{job_id}", title, title.casefold(),
             institution_id, school_id, status, NOW, NOW, NOW, NOW))
        self.conn.commit()

    def collect(self):
        return report_module.collect(self.db, astar_path="/nonexistent.db")

    def test_a_clean_database_reports_no_failures(self):
        self.add_job(1)
        report = self.collect()
        self.assertEqual([], report_module.failures(report))
        self.assertEqual("ok", report["integrity"]["quick_check"])

    def test_multiline_csv_fields_count_as_one_job(self):
        self.add_job(1, title='Assistant Professor\nManagement, OB/HR')
        report = self.collect()
        for scope, parity in report["surface_parity"].items():
            self.assertEqual(1, parity["csv_rows"], scope)
            self.assertTrue(parity["catalogue_parity"], scope)

    def test_market_coverage_is_computed_from_the_database(self):
        self.add_job(1)
        self.add_job(2, school_id=None)
        report = self.collect()
        self.assertEqual(2, report["market"]["jobs"])
        self.assertEqual(1, report["market"]["with_school_entity"])
        self.assertEqual(2, report["market"]["with_city_or_state"])

    def test_closed_and_unknown_are_historical_but_not_active_or_api_results(self):
        self.add_job(1, status="open")
        self.add_job(2, status="closed")
        self.add_job(3, status="unknown")

        report = self.collect()
        summary = build_faculty_job_summary(self.db)["summary"]
        payload = build_faculty_jobs_payload(self.db, {"limit": 20})

        self.assertEqual(1, report["market"]["jobs"])
        self.assertEqual(1, summary["active_jobs"])
        self.assertEqual(1, payload["pagination"]["total"])
        self.assertEqual(3, report["market"]["historical_eligible_jobs"])
        self.assertEqual({"open": 1, "closed": 1, "unknown": 1},
                         report["market"]["status_breakdown"])
        self.assertEqual(active_sql("business_school", ""),
                         report["active_filter"]["sql"])
        self.assertEqual(active_sql("business_school"),
                         summary["active_filter_sql"])
        closed = build_faculty_jobs_payload(self.db, {"status": "closed", "limit": 20})
        unknown = build_faculty_jobs_payload(self.db, {"status": "unknown", "limit": 20})
        self.assertEqual([2], [job["id"] for job in closed["jobs"]])
        self.assertEqual([3], [job["id"] for job in unknown["jobs"]])

    def test_partial_aacsb_reconciliation_is_explicitly_warned(self):
        self.conn.execute("""
            INSERT INTO aacsb_directory_schools
              (id,directory_result_id,directory_url,institution_name,directory_title,
               roster_source_url,official_website,active,
               first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (1,'r1','https://aacsb.example/r1','Example School','Example School',
                    'https://aacsb.example/','https://example.edu/jobs',1,?,?,?,?)
        """, (NOW, NOW, NOW, NOW))
        self.conn.commit()
        report = self.collect()
        roster = report["aacsb_roster"]
        self.assertEqual(1, roster["active_with_website"])
        self.assertEqual(0, roster["complete_current_rule_schools"])
        self.assertEqual(1, roster["incomplete_current_rule_schools"])
        self.assertTrue(any("reconciliation is partial: 0/1" in warning
                            for warning in report["quality"]["warnings"]))
        self.assertEqual("conditional", report["quality_verdicts"]["source_precision"])
        self.assertIn("Complete current-rule schools: 0 / 1",
                      report_module.render(report))

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

    def test_a_current_school_on_a_retired_parent_is_reported_even_without_jobs(self):
        self.conn.execute("UPDATE institutions SET is_current=0 WHERE id=1")
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["current_schools_on_retired_institution"])
        self.assertTrue(any("current schools" in item
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

    def test_an_active_aacsb_link_without_school_partition_is_blocking(self):
        self.add_job(1)
        source_id = self.conn.execute(
            "SELECT id FROM sources WHERE name='aacsb_official'"
        ).fetchone()["id"]
        self.conn.execute(
            "INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,"
            "first_seen,last_seen) VALUES (1,?,'new-unpartitioned','https://example.edu/x',1,?,?)",
            (source_id, NOW, NOW))
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["active_aacsb_source_without_partition"])
        self.assertTrue(any("without a school partition" in item
                            for item in report_module.failures(report)))

    def test_schema_user_version_must_match_migration_ledger(self):
        self.conn.execute("PRAGMA user_version=1")
        report = self.collect()
        self.assertEqual(1, report["invariants"]["schema_version_mismatch"])
        self.assertTrue(any("user_version" in item
                            for item in report_module.failures(report)))

    def test_country_prefixed_slash_city_is_blocking(self):
        self.add_job(1)
        self.conn.execute(
            "UPDATE jobs SET city='France / Paris',country='France',country_code='FR' WHERE id=1"
        )
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["country_prefixed_slash_city"])

    def test_board_default_region_leak_is_blocking(self):
        self.add_job(1)
        self.conn.execute(
            "UPDATE jobs SET country=NULL,country_code=NULL,region_group='United States',"
            "location_evidence='source_region_only_unknown_country' WHERE id=1"
        )
        self.conn.commit()
        report = self.collect()
        self.assertEqual(1, report["invariants"]["board_default_region_leak"])
        self.assertTrue(any("source board" in item
                            for item in report_module.failures(report)))

    def test_the_rendered_report_states_the_verdict(self):
        self.add_job(1)
        text = report_module.render(self.collect())
        # The wording changed on 2026-08-27: "every invariant holds" was untrue
        # while a non-zero review invariant was printed in the same report.
        self.assertIn("No blocking invariant is violated", text)
        self.assertIn("Academic Career status", text)

    def test_a_failing_report_says_so_in_the_rendered_text(self):
        self.add_job(1)
        self.conn.execute("UPDATE business_schools SET is_current=0 WHERE id=1")
        self.conn.commit()
        text = report_module.render(self.collect())
        self.assertNotIn("No blocking invariant is violated", text)
        self.assertIn("retired school", text)

    def test_the_tier_note_states_that_the_footprint_does_not_promote(self):
        self.add_job(1)
        text = report_module.render(self.collect())
        self.assertIn("does not move a tier", text)

    def test_the_verdict_reports_every_dimension_not_one_green_line(self):
        """A single pass line hid a non-zero review invariant printed above it."""
        self.add_job(1)
        text = report_module.render(self.collect())
        for dimension in ("structural integrity", "entity quality", "source precision",
                          "lifecycle freshness", "evidence limitations"):
            self.assertIn(dimension, text, dimension)

    def test_a_review_invariant_is_labelled_and_does_not_claim_all_zero(self):
        self.add_job(1)
        text = report_module.render(self.collect())
        self.assertNotIn("Invariants (all must be zero)", text,
                         "the table cannot claim every row is zero when review rows exist")
        self.assertIn("blocking", text)
        self.assertIn("review", text)

    def test_warnings_reach_the_rendered_report(self):
        self.add_job(1)
        report = self.collect()
        report["quality"]["warnings"] = ["a limitation the reader must see"]
        text = report_module.render(report)
        self.assertIn("a limitation the reader must see", text)

    def test_a_review_invariant_does_not_fail_the_run(self):
        self.add_job(1)
        report = self.collect()
        report["invariants"]["current_institution_name_country_conflicts"] = 2
        self.assertEqual([], report_module.failures(report),
                         "a genuine multi-campus pair is review, not corruption")

    def test_a_blocking_invariant_still_fails_the_run(self):
        self.add_job(1)
        report = self.collect()
        report["invariants"]["contaminated_current_institutions"] = 1
        problems = report_module.failures(report)
        self.assertTrue(any("contaminated" in item for item in problems), problems)

    def test_a_missing_astar_database_is_reported_not_fatal(self):
        self.add_job(1)
        report = self.collect()
        self.assertFalse(report["astar"]["available"])
        self.assertEqual([], report_module.failures(report))


if __name__ == "__main__":
    unittest.main()
