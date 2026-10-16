# -*- coding: utf-8 -*-
"""A snapshot has to survive the source set changing under it.

The failure this guards against is the one that makes a longitudinal series
worthless: an adapter lands, observed jobs jump 60%, and the chart reports a
booming market. Every snapshot therefore records which sources actually
delivered that day, and comparisons run over the sources common to both ends.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import ensure_faculty_jobs_tables
from services.faculty_jobs_snapshots import (
    backfill, ensure_tables, source_health_for, stable_panel_series, write_snapshot,
)

DAY_ONE = "2026-08-24"
DAY_TWO = "2026-08-25"


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def source_id(self, name):
        row = self.conn.execute("SELECT id FROM sources WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    def add_job(self, job_id, *, status="open", discipline="Management",
                first_seen=DAY_ONE + "T00:00:00Z", cycle=None):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              faculty_market_role,region_group,discipline_primary,
                              hiring_cycle,first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,?,'business_school','accepted',1,'faculty',
                    'United States',?,?,?,?,?,?)
        """, (job_id, f"k{job_id}", "Assistant Professor",
              "assistant professor", status, discipline, cycle,
              first_seen, first_seen, first_seen, first_seen))

    def add_history(self, job_id, observed_at, status, deadline=None, salary=None,
                    title="Assistant Professor"):
        self.conn.execute("""
            INSERT INTO job_status_history
              (job_id, observed_at, status, deadline, salary_raw, title_raw, source_count)
            VALUES (?,?,?,?,?,?,1)
        """, (job_id, observed_at, status, deadline, salary, title))

    def add_run(self, source_name, day, status="success", items=10,
                coverage_complete=None, reported=None):
        sid = self.source_id(source_name)
        self.assertIsNotNone(sid, f"source {source_name} missing from seed")
        self.conn.execute("""
            INSERT INTO ingestion_runs
              (source_id, started_at, finished_at, status, pages_fetched, items_seen,
               items_inserted, items_updated, items_merged, error_count,
               reported_total, coverage_complete, listing_pages)
            VALUES (?,?,?,?,1,?,0,0,0,0,?,?,1)
        """, (sid, day + "T06:00:00Z", day + "T06:01:00Z", status, items,
              reported, coverage_complete))


class SnapshotTests(_Fixture):
    def test_a_snapshot_records_the_sources_that_actually_delivered(self):
        self.add_job(1)
        self.add_run("chronicle_business", DAY_ONE, items=5)
        self.add_run("poms", DAY_ONE, status="error", items=0)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)
        row = self.conn.execute("""
            SELECT source_count, source_panel FROM market_snapshots
            WHERE snapshot_date=? AND scope='business_school' AND dimension='total'
        """, (DAY_ONE,)).fetchone()
        panel = json.loads(row["source_panel"])
        self.assertIn("chronicle_business", panel)
        self.assertNotIn("poms", panel, "a source that errored delivered nothing")
        self.assertEqual(1, row["source_count"])

    def test_the_same_day_written_twice_updates_rather_than_duplicates(self):
        self.add_job(1)
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)
        write_snapshot(self.conn, DAY_ONE)
        self.assertEqual(1, self.conn.execute("""
            SELECT COUNT(*) FROM market_snapshots
            WHERE snapshot_date=? AND scope='business_school'
              AND dimension='total' AND dimension_value='all'
        """, (DAY_ONE,)).fetchone()[0])

    def test_every_scope_is_written(self):
        self.add_job(1)
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)
        scopes = {row[0] for row in self.conn.execute(
            "SELECT DISTINCT scope FROM market_snapshots")}
        self.assertEqual({"business_school", "business", "all"}, scopes)

    def test_change_counts_come_from_history_not_from_the_current_row(self):
        # A job that closed yesterday and a job that opened today must be
        # distinguishable, and the current row alone cannot tell them apart.
        self.add_job(1, first_seen=DAY_ONE + "T00:00:00Z")
        self.add_job(2, status="closed", first_seen="2026-08-20T00:00:00Z")
        self.add_history(2, "2026-08-21T00:00:00Z", "open")
        self.add_history(2, DAY_ONE + "T09:00:00Z", "closed")
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)
        row = self.conn.execute("""
            SELECT new_jobs, closed_jobs FROM market_snapshots
            WHERE snapshot_date=? AND scope='business_school' AND dimension='total'
        """, (DAY_ONE,)).fetchone()
        self.assertEqual(1, row["new_jobs"])
        self.assertEqual(1, row["closed_jobs"])

    def test_a_deadline_move_is_counted_as_a_change(self):
        self.add_job(1)
        self.add_history(1, "2026-08-23T00:00:00Z", "open", deadline="2026-11-01")
        self.add_history(1, DAY_ONE + "T09:00:00Z", "open", deadline="2026-12-15")
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)
        row = self.conn.execute("""
            SELECT deadline_changed FROM market_snapshots
            WHERE snapshot_date=? AND scope='business_school' AND dimension='total'
        """, (DAY_ONE,)).fetchone()
        self.assertEqual(1, row["deadline_changed"])

    def test_change_counts_are_not_repeated_on_every_dimension(self):
        # Otherwise summing across disciplines multiplies the day's new jobs.
        self.add_job(1, discipline="Management")
        self.add_job(2, discipline="Finance")
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)
        total = self.conn.execute("""
            SELECT SUM(new_jobs) FROM market_snapshots
            WHERE snapshot_date=? AND scope='business_school' AND dimension='discipline'
        """, (DAY_ONE,)).fetchone()[0]
        self.assertEqual(0, total)


class StablePanelTests(_Fixture):
    def test_adding_a_source_does_not_read_as_market_growth(self):
        # The whole point. Day one has one board; day two adds a second.
        self.add_job(1)
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE)

        self.add_job(2)
        self.add_run("chronicle_business", DAY_TWO)
        self.add_run("poms", DAY_TWO)
        self.conn.commit()
        write_snapshot(self.conn, DAY_TWO)

        series = stable_panel_series(self.conn)
        self.assertEqual(["chronicle_business"], series["panel"],
                         "only the source present on both days is comparable")
        self.assertEqual(2, len(series["series"]))
        self.assertIn("without the market moving", series["note"])

    def test_the_series_says_which_rows_were_reconstructed(self):
        self.add_job(1)
        self.add_run("chronicle_business", DAY_ONE)
        self.conn.commit()
        write_snapshot(self.conn, DAY_ONE, reconstructed=True)
        series = stable_panel_series(self.conn)
        self.assertTrue(series["series"][0]["reconstructed"])


class BackfillTests(_Fixture):
    def test_backfill_covers_the_history_that_exists_and_marks_itself(self):
        self.add_job(1, first_seen="2026-08-23T00:00:00Z")
        self.add_history(1, "2026-08-23T00:00:00Z", "open")
        self.add_history(1, "2026-08-24T00:00:00Z", "open")
        self.add_run("chronicle_business", "2026-08-23")
        self.add_run("chronicle_business", "2026-08-24")
        self.conn.commit()
        result = backfill(self.conn, since="2026-08-23", until="2026-08-24")
        self.assertEqual(2, result["days"])
        self.assertTrue(result["reconstructed"])
        flags = {row[0] for row in self.conn.execute(
            "SELECT DISTINCT reconstructed FROM market_snapshots")}
        self.assertEqual({1}, flags, "back-filled rows must not look contemporaneous")

    def test_backfill_with_no_history_reports_why_rather_than_writing_nothing(self):
        result = backfill(self.conn)
        self.assertEqual(0, result["days"])
        self.assertIn("no history", result["reason"])

    def test_source_health_reads_the_runs_that_happened(self):
        self.add_run("chronicle_business", DAY_ONE, items=42,
                     coverage_complete=1, reported=42)
        self.conn.commit()
        health = source_health_for(self.conn, DAY_ONE)
        self.assertEqual(1, len(health))
        self.assertEqual(42, health[0]["items_seen"])
        self.assertEqual(1, health[0]["coverage_complete"])


if __name__ == "__main__":
    unittest.main()
