# -*- coding: utf-8 -*-
"""Which board carries which part of the market, and what that costs.

The matrix exists to answer a question a plain count cannot: if this source
stopped tomorrow, what would be missing? A board supplying 148 postings that
four others also carry is nearly free to lose; one supplying 40 nobody else has
puts a hole in a discipline.

And a zero has to be readable. A source with no Marketing postings may not
cover Marketing, or may have been blocked, or may never have been read at all
-- only the first is a fact about the market, so every zero is reported beside
that source's completeness state.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_coverage_matrix import build_matrix, field_gaps
from services.faculty_jobs_service import ensure_faculty_jobs_tables

NOW = "2026-09-01T00:00:00Z"


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def source_id(self, name):
        row = self.conn.execute("SELECT id FROM sources WHERE name=?", (name,)).fetchone()
        self.assertIsNotNone(row, f"seed source {name} missing")
        return row["id"]

    def add_job(self, job_id, discipline, *, deadline=None, official=None,
                salary=None, scope="business_school"):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              faculty_market_role,region_group,discipline_primary,
                              deadline_date,official_url,salary_min,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,'open',?,'accepted',1,'faculty','United States',?,?,?,?,?,?,?,?)
        """, (job_id, f"k{job_id}", "Assistant Professor", "assistant professor",
              scope, discipline, deadline, official, salary, NOW, NOW, NOW, NOW))

    def link(self, job_id, source_name, active=1):
        self.conn.execute("""
            INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,
                                     first_seen,last_seen)
            VALUES (?,?,?,?,?,?,?)
        """, (job_id, self.source_id(source_name), f"{source_name}-{job_id}",
              f"https://example.test/{job_id}", active, NOW, NOW))

    def run_record(self, source_name, *, status="success", coverage_complete=None,
                   reported=None, seen=10):
        self.conn.execute("""
            INSERT INTO ingestion_runs
              (source_id,started_at,finished_at,status,pages_fetched,items_seen,
               items_inserted,items_updated,items_merged,error_count,
               reported_total,coverage_complete,listing_pages)
            VALUES (?,?,?,?,1,?,0,0,0,0,?,?,1)
        """, (self.source_id(source_name), NOW, NOW, status, seen, reported,
              coverage_complete))


class MatrixTests(_Fixture):
    def setUp(self):
        super().setUp()
        # chronicle carries two Management jobs, one of them shared with poms.
        self.add_job(1, "Management", deadline="2026-11-01")
        self.add_job(2, "Management")
        self.add_job(3, "Finance", official="https://apply.example.edu/3")
        self.link(1, "chronicle_business")
        self.link(2, "chronicle_business")
        self.link(2, "poms")
        self.link(3, "poms")
        self.run_record("chronicle_business", coverage_complete=1, reported=2)
        self.run_record("poms")
        self.conn.commit()

    def test_a_shared_posting_is_not_counted_as_unique(self):
        matrix = build_matrix(self.conn)
        by_source = {row["source"]: row for row in matrix["sources"]}
        # chronicle has 2 jobs; only job 1 is exclusively its own.
        self.assertEqual(2, by_source["chronicle_business"]["total_jobs"])
        self.assertEqual(1, by_source["chronicle_business"]["unique_jobs"])
        # poms has 2; only job 3 is exclusively its own.
        self.assertEqual(1, by_source["poms"]["unique_jobs"])

    def test_unique_share_says_what_losing_a_source_would_cost(self):
        matrix = build_matrix(self.conn)
        by_source = {row["source"]: row for row in matrix["sources"]}
        self.assertEqual(50.0, by_source["chronicle_business"]["unique_share"])

    def test_a_disciplines_size_is_distinct_postings_not_the_column_sum(self):
        # Job 2 sits on both boards. Adding the source columns would report
        # Management at 3, and every share computed against that denominator
        # would be understated.
        matrix = build_matrix(self.conn)
        management = matrix["by_discipline"]["Management"]
        self.assertEqual(2, management["jobs"])
        self.assertEqual(2, management["sources_contributing"])

    def test_carrying_a_discipline_and_being_able_to_lose_it_differ(self):
        # chronicle carries both Management postings, but only job 1 is its
        # own, so half of Management survives chronicle going dark.
        matrix = build_matrix(self.conn)
        management = matrix["by_discipline"]["Management"]
        self.assertEqual("chronicle_business", management["largest_source"])
        self.assertEqual(100.0, management["largest_share"])
        self.assertEqual(50.0, management["largest_source_only_share"])
        self.assertIn("would actually", matrix["concentration_note"])

    def test_a_discipline_on_one_board_is_reported_as_fully_single_sourced(self):
        matrix = build_matrix(self.conn)
        self.assertEqual(100.0, matrix["by_discipline"]["Finance"]["single_sourced_share"])
        self.assertEqual(50.0, matrix["by_discipline"]["Management"]["single_sourced_share"])

    def test_field_quality_is_measured_per_source_not_globally(self):
        matrix = build_matrix(self.conn)
        by_source = {row["source"]: row for row in matrix["sources"]}
        chronicle = by_source["chronicle_business"]["field_quality"]
        # One of chronicle's two jobs has a deadline.
        self.assertEqual(50.0, chronicle["deadline"]["percent"])
        # Neither has an official URL.
        self.assertEqual(0.0, chronicle["official_url"]["percent"])

    def test_a_zero_is_reported_beside_the_sources_completeness(self):
        # The whole reason the state is carried: a board we never read and a
        # board that genuinely has no Marketing postings look identical
        # otherwise.
        matrix = build_matrix(self.conn)
        by_source = {row["source"]: row for row in matrix["sources"]}
        self.assertEqual("complete", by_source["chronicle_business"]["completeness_state"])
        self.assertEqual("unverifiable", by_source["poms"]["completeness_state"])
        self.assertIn("not evidence a board does not cover", matrix["reading_note"])

    def test_a_source_that_contributed_nothing_is_still_listed(self):
        # A missing row and a zero row mean different things; dropping the
        # source would hide that it is configured at all.
        matrix = build_matrix(self.conn)
        silent = {row["source"] for row in matrix["silent_sources"]}
        self.assertIn("aom", silent)
        for row in matrix["silent_sources"]:
            self.assertIn("completeness_state", row)

    def test_an_inactive_link_does_not_count_as_coverage(self):
        self.add_job(4, "Marketing")
        self.link(4, "chronicle_business", active=0)
        self.conn.commit()
        matrix = build_matrix(self.conn)
        by_source = {row["source"]: row for row in matrix["sources"]}
        self.assertEqual(2, by_source["chronicle_business"]["total_jobs"],
                         "a link the board has taken down is not current coverage")

    def test_the_scope_comes_from_the_shared_contract(self):
        # A non-business posting must not appear, and the strict scope must be
        # narrower than the broad one -- both decided by faculty_jobs_scope.
        self.add_job(5, "Management", scope="non_business")
        self.link(5, "poms")
        self.conn.commit()
        broad = build_matrix(self.conn, "business")
        self.assertEqual(3, sum(row["total_jobs"] for row in broad["sources"]) - 1,
                         "the non-business posting is excluded from the business scope")


    def test_cumulative_reach_and_the_current_market_are_separate_columns(self):
        # A board that carried a discipline and has since stopped must not read
        # as still carrying it.
        self.conn.execute("UPDATE jobs SET status='closed' WHERE id=1")
        self.conn.commit()
        matrix = build_matrix(self.conn)
        by_source = {row["source"]: row for row in matrix["sources"]}
        chronicle = by_source["chronicle_business"]
        self.assertEqual(2, chronicle["total_jobs"], "the closed posting is still observed")
        self.assertEqual(1, chronicle["active_jobs"], "but only one is still open")
        self.assertEqual(1, matrix["by_discipline"]["Management"]["active_jobs"])

    def test_the_matrix_says_which_predicate_produced_its_counts(self):
        matrix = build_matrix(self.conn, "business_school")
        self.assertEqual("catalogue", matrix["basis"])
        self.assertIn("business_school", matrix["catalogue_filter_sql"])
        self.assertIn("status IN", matrix["active_filter_sql"])
        self.assertIn("cumulative reach", matrix["basis_note"])


class GapTests(_Fixture):
    def test_gaps_are_ranked_by_postings_affected_not_by_percentage(self):
        # 0% on a five-posting board matters less than 10% on a large one.
        for job_id in range(1, 21):
            self.add_job(job_id, "Management")
            self.link(job_id, "higheredjobs")
        self.add_job(50, "Finance")
        self.link(50, "poms")
        self.run_record("higheredjobs", coverage_complete=1, reported=20)
        self.run_record("poms")
        self.conn.commit()
        gaps = field_gaps(self.conn)
        self.assertGreater(len(gaps["gaps"]), 0)
        first = gaps["gaps"][0]
        self.assertEqual("higheredjobs", first["source"],
                         "the largest board's gap costs the most postings")
        self.assertIn("costs more than a zero on a small one", gaps["note"])

    def test_a_well_filled_field_is_not_reported_as_a_gap(self):
        for job_id in range(1, 6):
            self.add_job(job_id, "Management", deadline="2026-11-01")
            self.link(job_id, "chronicle_business")
        self.run_record("chronicle_business", coverage_complete=1, reported=5)
        self.conn.commit()
        gaps = field_gaps(self.conn)
        fields = {row["field"] for row in gaps["gaps"] if row["source"] == "chronicle_business"}
        self.assertNotIn("deadline", fields, "100% coverage is not a gap")


if __name__ == "__main__":
    unittest.main()
