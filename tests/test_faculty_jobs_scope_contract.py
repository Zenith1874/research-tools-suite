# -*- coding: utf-8 -*-
"""One scope, one set of numbers, and metadata that names the query it ran.

Before this the audit view reported 4,733 records, 3,525 active, and groupings
summing to 2,423 -- three answers to one question on one page, because the
groupings re-applied the broad business predicate whatever the scope. The
metadata made it worse by naming the broad predicate for every scope, so the
strict view claimed to include business_discipline and the audit view claimed
to exclude everything else.
"""

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from services.faculty_jobs_query import default_market_where, is_default_market_row
from services.faculty_jobs_scope import (
    ACTIVE_STATUSES, active_filter_definition, active_sql, catalogue_sql, scope_counts,
)
from services.faculty_jobs_service import (
    _job_select, build_faculty_job_summary, build_faculty_jobs_payload,
    build_job_market_analytics, ensure_faculty_jobs_tables, export_faculty_jobs_csv,
)

NOW = "2026-08-29T00:00:00Z"


class PredicateTests(unittest.TestCase):
    def test_strict_never_admits_business_discipline(self):
        self.assertIn("business_scope='business_school'", catalogue_sql("business_school"))
        self.assertNotIn("business_discipline", catalogue_sql("business_school"))
        self.assertNotIn("business_discipline", active_sql("business_school"))

    def test_broad_admits_both_business_scopes(self):
        self.assertIn("business_discipline", catalogue_sql("business"))
        self.assertIn("business_school", catalogue_sql("business"))

    def test_the_audit_scope_restricts_nothing_by_business_scope(self):
        self.assertNotIn("business_scope", catalogue_sql("all"))
        self.assertNotIn("derived_quality", catalogue_sql("all"))
        self.assertNotIn("business_scope", active_sql("all"))

    def test_a_row_folded_into_another_is_dropped_from_every_scope(self):
        # Including the audit scope. That scope exists to show what the market
        # views leave out by derivation; a duplicate is not a second record in
        # any view, so counting it here would put back the double count the
        # merge removed.
        for scope in ("business_school", "business", "all"):
            with self.subTest(scope=scope):
                self.assertIn("merged_into_job_id IS NULL", catalogue_sql(scope))
                self.assertIn("merged_into_job_id IS NULL", active_sql(scope))

    def test_active_is_the_catalogue_plus_open_statuses(self):
        for scope in ("business_school", "business", "all"):
            for status in ACTIVE_STATUSES:
                self.assertIn(status, active_sql(scope), scope)


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.add(1, "Assistant Professor of Finance", "business_school", "open")
        self.add(2, "Assistant Professor of Marketing", "business_discipline", "open")
        self.add(3, "Assistant Professor of Strategy", "business_school", "closed")
        self.add(4, "Assistant Professor of Nursing", "non_business", "open")
        self.add(5, "Assistant Professor of History", "non_business", "unknown")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, job_id, title, scope, status):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,business_scope,
                              derived_quality,faculty_market_eligible,faculty_market_role,
                              region_group,discipline_primary,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,?,?,'accepted',1,'faculty','United States','Finance',?,?,?,?)
        """, (job_id, f"key-{job_id}", title, title.casefold(), status, scope,
              NOW, NOW, NOW, NOW))

    def test_the_audit_catalogue_holds_everything_and_active_holds_less(self):
        counts = scope_counts(self.conn, "all", _job_select())
        self.assertEqual(5, counts["catalogue_records"])
        self.assertEqual(3, counts["active_jobs"])
        self.assertEqual({"closed": 1, "unknown": 1}, counts["inactive_by_status"])

    def test_the_inactive_breakdown_names_each_status_rather_than_calling_it_closed(self):
        # 927 closed and 281 unknown were being reported together as "closed".
        counts = scope_counts(self.conn, "all", _job_select())
        self.assertIn("unknown", counts["inactive_by_status"])
        self.assertNotEqual(sum(counts["inactive_by_status"].values()),
                            counts["inactive_by_status"].get("closed"))

    def analytics(self, scope):
        return build_job_market_analytics(self.db, {"scope": scope})["analytics"]

    def test_a_folded_duplicate_leaves_every_surface_at_once(self):
        # The bug this pins: the list and CSV build their scope predicate in
        # _scope_conditions, separately from the scope module the summary,
        # analytics and coverage matrix use. Excluding folded rows in one
        # place moved four of those surfaces and left the other two counting
        # the duplicate, which is the drift this whole module exists to stop.
        before = {
            "list": build_faculty_jobs_payload(self.db, {"scope": "all"})["pagination"]["total"],
            "summary": build_faculty_job_summary(self.db, {"scope": "all"})["summary"]["scope_catalogue_records"],
            "analytics": self.analytics("all")["active_jobs"],
            "csv": export_faculty_jobs_csv(self.db, {"scope": "all"}).count(chr(10)),
        }
        self.conn.execute("UPDATE jobs SET merged_into_job_id=2 WHERE id=1")
        self.conn.commit()
        after = {
            "list": build_faculty_jobs_payload(self.db, {"scope": "all"})["pagination"]["total"],
            "summary": build_faculty_job_summary(self.db, {"scope": "all"})["summary"]["scope_catalogue_records"],
            "analytics": self.analytics("all")["active_jobs"],
            "csv": export_faculty_jobs_csv(self.db, {"scope": "all"}).count(chr(10)),
        }
        for surface, was in before.items():
            self.assertEqual(was - 1, after[surface],
                             f"{surface} still counts a posting folded into another")

    def test_the_school_explorer_predicate_drops_folded_rows_too(self):
        # default_market_where is its own third definition, used by the school
        # explorer and the generated report.
        self.assertIn("merged_into_job_id IS NULL", default_market_where())
        self.assertIn("j.merged_into_job_id IS NULL", default_market_where("j"))
        self.assertFalse(is_default_market_row(
            {"merged_into_job_id": 7, "derived_quality": "accepted",
             "faculty_market_eligible": 1, "business_scope": "business_school",
             "status": "open"}))
        self.assertTrue(is_default_market_row(
            {"derived_quality": "accepted", "faculty_market_eligible": 1,
             "business_scope": "business_school", "status": "open"}),
            "a row without the column at all is not a folded row")

    def test_every_grouping_sums_to_the_active_total(self):
        for scope in ("business_school", "business", "all"):
            data = self.analytics(scope)
            for grouping in ("by_region", "by_discipline"):
                self.assertEqual(
                    data["active_jobs"],
                    sum(item["count"] for item in data.get(grouping, [])),
                    f"{scope}/{grouping}")

    def test_analytics_metadata_names_the_predicate_it_ran(self):
        for scope in ("business_school", "business", "all"):
            listed = build_faculty_jobs_payload(self.db, {"scope": scope})
            summary = build_faculty_job_summary(self.db, {"scope": scope})["summary"]
            analytics = self.analytics(scope)
            self.assertEqual(active_filter_definition(scope), listed["meta"]["active_filter"])
            self.assertEqual(active_sql(scope), listed["meta"]["active_filter_sql"])
            self.assertEqual(active_filter_definition(scope), summary["active_filter"])
            self.assertEqual(active_sql(scope), summary["active_filter_sql"])
            self.assertEqual(active_filter_definition(scope), analytics["active_filter"])
            self.assertEqual(active_sql(scope, "j"), analytics["active_filter_sql"])
            self.assertEqual(active_sql(scope), analytics["overview"]["active_filter_sql"])

    def test_source_coverage_distinguishes_enabled_disabled_and_missing_links(self):
        enabled = self.conn.execute(
            "SELECT id FROM sources WHERE enabled=1 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        disabled = self.conn.execute(
            "SELECT id FROM sources WHERE enabled=0 ORDER BY id LIMIT 1"
        ).fetchone()[0]
        self.conn.executemany(
            "INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,first_seen,last_seen) "
            "VALUES (?,?,?,?,1,?,?)",
            [(1, enabled, "enabled-1", "https://enabled.example/1", NOW, NOW),
             (2, disabled, "disabled-2", "https://disabled.example/2", NOW, NOW)],
        )
        self.conn.commit()
        coverage = build_faculty_jobs_payload(
            self.db, {"scope": "all"}
        )["meta"]["source_coverage"]
        self.assertEqual(1, coverage["jobs_with_enabled_source"])
        self.assertEqual(1, coverage["jobs_with_disabled_or_opt_in_source_only"])
        self.assertEqual(3, coverage["jobs_with_no_active_source"])
        self.assertIn("preserved disabled/opt-in/manual", coverage["source_snapshot_policy"])

    def test_list_summary_and_csv_agree_for_every_scope(self):
        for scope in ("business_school", "business", "all"):
            query = {"scope": scope}
            listed = build_faculty_jobs_payload(self.db, query=query)["pagination"]["total"]
            summary = build_faculty_job_summary(self.db, query=query)["summary"]
            csv_rows = [line for line in
                        export_faculty_jobs_csv(self.db, query=query).splitlines()
                        if line.strip()][1:]
            self.assertEqual(listed, summary["matching_records"], scope)
            self.assertEqual(listed, len(csv_rows), scope)

    def test_matching_records_is_the_query_and_not_the_scope(self):
        # The default market query already carries the active-status filter, so
        # the strict scope holds more records than the default view returns.
        # Reporting the query's number under the name "catalogue" put 404 and
        # 315 under one heading with nothing to tell them apart.
        query = {"scope": "business_school"}
        summary = build_faculty_job_summary(self.db, query=query)["summary"]
        counts = scope_counts(self.conn, "business_school", _job_select())
        self.assertEqual(counts["catalogue_records"], summary["scope_catalogue_records"])
        self.assertEqual(counts["active_jobs"], summary["scope_active_jobs"])
        self.assertLess(summary["matching_records"], summary["scope_catalogue_records"])

    def test_the_summary_no_longer_ships_the_ambiguous_name(self):
        for scope in ("business_school", "business", "all"):
            summary = build_faculty_job_summary(self.db, query={"scope": scope})["summary"]
            self.assertNotIn("catalogue_records", summary, scope)

    def test_the_summary_carries_the_inactive_breakdown_for_its_scope(self):
        summary = build_faculty_job_summary(self.db, query={"scope": "all"})["summary"]
        self.assertEqual({"closed": 1, "unknown": 1}, summary["inactive_by_status"])

    def test_all_three_scopes_are_reported_together_and_nest(self):
        # Shown side by side because the relationship is the point: a reader on
        # the strict view has to be able to see how much sits outside it.
        summary = build_faculty_job_summary(self.db, query={})["summary"]
        comparison = summary["scope_comparison"]
        self.assertEqual({"business_school", "business", "all"}, set(comparison))
        strict = comparison["business_school"]["catalogue_records"]
        broad = comparison["business"]["catalogue_records"]
        audit = comparison["all"]["catalogue_records"]
        self.assertLessEqual(strict, broad)
        self.assertLessEqual(broad, audit)

    def test_the_comparison_does_not_change_with_the_selected_scope(self):
        # It is a fixed frame of reference, not another thing the dropdown
        # rewrites -- otherwise it cannot be used to compare.
        first = build_faculty_job_summary(
            self.db, query={"scope": "business_school"})["summary"]["scope_comparison"]
        second = build_faculty_job_summary(
            self.db, query={"scope": "all"})["summary"]["scope_comparison"]
        for scope in first:
            self.assertEqual(first[scope]["catalogue_records"],
                             second[scope]["catalogue_records"], scope)
            self.assertEqual(first[scope]["active_jobs"],
                             second[scope]["active_jobs"], scope)

    def test_the_summary_says_when_local_observation_began(self):
        # Every record here was first seen within a week of the first scan, so
        # "new in 7 days" equals the total and says nothing about the market.
        # The page can only caveat that if it is told how long we have looked.
        recent = (date.today() - timedelta(days=2)).isoformat() + "T00:00:00Z"
        self.conn.execute("UPDATE jobs SET first_seen_at=?", (recent,))
        self.conn.commit()
        summary = build_faculty_job_summary(self.db, query={"scope": "all"})["summary"]
        self.assertEqual(recent, summary["first_observation_at"])
        self.assertEqual(summary["new_7d"], summary["active_jobs"])

    def test_the_csv_carries_the_field_the_page_filters_on(self):
        header = export_faculty_jobs_csv(self.db, query={"scope": "all"}).splitlines()[0]
        for column in ("appointment_type", "business_scope", "faculty_market_role",
                       "salary_min", "deadline_mode"):
            self.assertIn(column, header, column)

    def test_the_public_csv_carries_no_private_state(self):
        header = export_faculty_jobs_csv(self.db, query={"scope": "all"}).splitlines()[0]
        for column in ("fit_score", "application_state", "notes"):
            self.assertNotIn(column, header, column)


if __name__ == "__main__":
    unittest.main()
