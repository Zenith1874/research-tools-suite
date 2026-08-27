# -*- coding: utf-8 -*-
"""AACSB roster reconciliation against a complete run.

Without it the roster only grows: a school that loses accreditation, merges or
is renamed stays listed forever. The danger is the opposite mistake -- a bounded
run (``--max-pages 2``, or one cut short by an HTTP error) observing a slice and
retiring a thousand accredited schools -- so most of these tests are about
refusing to reconcile.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    AACSB_MISSING_RUNS_BEFORE_INACTIVE,
    _aacsb_snapshot_is_complete,
    _reconcile_aacsb_snapshot,
    ensure_faculty_jobs_tables,
)

NOW = "2026-08-26T00:00:00Z"


class CompletenessGateTests(unittest.TestCase):
    def test_a_full_run_is_complete(self):
        complete, _reason = _aacsb_snapshot_is_complete(1054, 1093, None, 110, 42)
        self.assertTrue(complete)

    def test_a_record_limited_run_is_never_complete(self):
        complete, reason = _aacsb_snapshot_is_complete(100, 1093, 100, 110, 3)
        self.assertFalse(complete)
        self.assertIn("max_records", reason)

    def test_a_page_limited_run_falls_below_the_bar(self):
        complete, reason = _aacsb_snapshot_is_complete(40, 1093, None, 2, 2)
        self.assertFalse(complete)
        self.assertIn("completeness", reason)

    def test_no_reported_total_means_no_comparison(self):
        complete, reason = _aacsb_snapshot_is_complete(1054, 0, None, 110, 42)
        self.assertFalse(complete)
        self.assertIn("total", reason)

    def test_the_known_parse_gap_still_counts_as_complete(self):
        # The directory reports more results than it exposes as /accredited/
        # rows, so exact equality would never hold.
        self.assertTrue(_aacsb_snapshot_is_complete(1054, 1093, None, 110, 42)[0])


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        for index in range(1, 11):
            self.conn.execute("""
                INSERT INTO aacsb_directory_schools
                  (id,directory_result_id,directory_url,institution_name,directory_title,
                   roster_source_url,first_seen_at,last_seen_at,active,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,1,?,?)
            """, (index, f"r{index}", f"https://x/{index}", f"School {index}",
                  f"School {index}", "https://roster", NOW, NOW, NOW, NOW))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def state(self, record_id):
        return self.conn.execute(
            "SELECT active, consecutive_missing_runs FROM aacsb_directory_schools WHERE id=?",
            (record_id,)).fetchone()

    def active_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM aacsb_directory_schools WHERE active=1").fetchone()[0]

    def run_complete(self, seen):
        result = _reconcile_aacsb_snapshot(self.conn, seen, 10, None, 110, 1)
        self.conn.commit()
        return result

    def test_a_bounded_run_never_deactivates_anything(self):
        result = _reconcile_aacsb_snapshot(self.conn, [1, 2], 10, 100, 110, 1)
        self.conn.commit()
        self.assertFalse(result["reconciled"])
        self.assertEqual(10, self.active_count(), "a slice must not retire the roster")

    def test_a_short_run_never_deactivates_anything(self):
        result = _reconcile_aacsb_snapshot(self.conn, [1, 2], 10, None, 110, 1)
        self.conn.commit()
        self.assertFalse(result["reconciled"])
        self.assertEqual(10, self.active_count())

    def test_one_absence_only_starts_a_streak(self):
        self.run_complete(list(range(1, 10)))
        row = self.state(10)
        self.assertEqual(1, row["active"], "one miss is not evidence a school is gone")
        self.assertEqual(1, row["consecutive_missing_runs"])

    def test_deactivation_after_three_complete_runs(self):
        for _ in range(AACSB_MISSING_RUNS_BEFORE_INACTIVE):
            self.run_complete(list(range(1, 10)))
        row = self.state(10)
        self.assertEqual(0, row["active"])
        self.assertEqual(AACSB_MISSING_RUNS_BEFORE_INACTIVE, row["consecutive_missing_runs"])
        self.assertEqual(9, self.active_count())

    def test_reappearing_before_the_limit_clears_the_streak(self):
        self.run_complete(list(range(1, 10)))
        self.assertEqual(1, self.state(10)["consecutive_missing_runs"])
        self.run_complete(list(range(1, 11)))
        row = self.state(10)
        self.assertEqual(0, row["consecutive_missing_runs"])
        self.assertEqual(1, row["active"])

    def test_a_deactivated_record_is_revived_when_it_returns(self):
        for _ in range(AACSB_MISSING_RUNS_BEFORE_INACTIVE):
            self.run_complete(list(range(1, 10)))
        self.assertEqual(0, self.state(10)["active"])
        result = self.run_complete(list(range(1, 11)))
        self.assertEqual(1, self.state(10)["active"], "the roster is the authority")
        self.assertEqual(1, result["revived"])

    def test_nothing_is_deleted(self):
        for _ in range(AACSB_MISSING_RUNS_BEFORE_INACTIVE):
            self.run_complete(list(range(1, 10)))
        self.assertEqual(10, self.conn.execute(
            "SELECT COUNT(*) FROM aacsb_directory_schools").fetchone()[0])

    def test_the_reconciliation_is_recorded_in_the_audit(self):
        self.run_complete(list(range(1, 10)))
        row = self.conn.execute(
            "SELECT action, reason FROM faculty_job_repair_audit "
            "WHERE action='aacsb_snapshot_reconciliation'").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("consecutive complete runs", row["reason"])

    def test_a_skipped_reconciliation_writes_no_audit_row(self):
        _reconcile_aacsb_snapshot(self.conn, [1], 10, 100, 110, 1)
        self.conn.commit()
        self.assertEqual(0, self.conn.execute(
            "SELECT COUNT(*) FROM faculty_job_repair_audit "
            "WHERE action='aacsb_snapshot_reconciliation'").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
