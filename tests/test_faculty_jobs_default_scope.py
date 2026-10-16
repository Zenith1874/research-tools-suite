# -*- coding: utf-8 -*-
"""The page called Business Faculty Jobs must default to business-school jobs.

The default was the union of explicit school evidence with "the title mentions
a business discipline, school unverified". The second set is several times the
first, so the default view was mostly postings whose school had never been
established -- while the page presented it as the business faculty market.

Nothing is deleted by this change. The broader set and the raw catalogue are
both still reachable; they are just no longer what you get without asking.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    _requested_scope, _scope_conditions, build_faculty_job_filters,
    build_faculty_job_summary, build_faculty_jobs_payload, ensure_faculty_jobs_tables,
    export_faculty_jobs_csv,
)

NOW = "2026-08-29T00:00:00Z"


class ScopeResolutionTests(unittest.TestCase):
    def test_no_scope_means_explicit_school_evidence(self):
        self.assertEqual("business_school", _requested_scope({}))
        self.assertEqual("business_school", _requested_scope(None))
        self.assertEqual("business_school", _requested_scope({"scope": ""}))

    def test_the_broader_and_audit_views_stay_reachable(self):
        self.assertEqual("business", _requested_scope({"scope": "business"}))
        self.assertEqual("all", _requested_scope({"scope": "all"}))
        self.assertEqual("all", _requested_scope({"scope": "audit"}))


class ScopeCountTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.add(1, "Assistant Professor of Finance", "business_school", "faculty", 1)
        self.add(2, "Assistant Professor of Marketing", "business_discipline", "faculty", 1)
        self.add(3, "Graduate Assistant, Accounting", "business_discipline", "graduate_assistant", 0)
        self.add(4, "Assistant Professor of Nursing", "non_business", "faculty", 1)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, job_id, title, scope, role, eligible):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              faculty_market_role,first_seen_at,last_seen_at,
                              created_at,updated_at)
            VALUES (?,?,?,?,'open',?,'accepted',?,?,?,?,?,?)
        """, (job_id, f"key-{job_id}", title, title.casefold(), scope, eligible, role,
              NOW, NOW, NOW, NOW))

    def count(self, **query):
        return build_faculty_jobs_payload(self.db, query=query)["pagination"]["total"]

    def test_the_default_shows_only_established_business_schools(self):
        self.assertEqual(1, self.count())

    def test_the_broader_view_adds_unverified_discipline_roles(self):
        self.assertEqual(2, self.count(scope="business"))

    def test_the_audit_view_retains_everything(self):
        self.assertEqual(4, self.count(scope="all"))

    def test_a_graduate_assistantship_is_absent_from_both_market_views(self):
        for scope in ("business_school", "business"):
            rows = build_faculty_jobs_payload(self.db, query={"scope": scope})["jobs"]
            self.assertNotIn("graduate_assistant", [job["faculty_market_role"] for job in rows],
                             scope)

    def test_a_graduate_assistantship_is_still_auditable(self):
        rows = build_faculty_jobs_payload(self.db, query={"scope": "all"})["jobs"]
        self.assertIn("graduate_assistant", [job["faculty_market_role"] for job in rows])

    def test_list_summary_filters_and_export_agree_on_one_query(self):
        # They used to be able to drift because each assembled its own
        # predicate; the same query must produce the same total everywhere.
        query = {"scope": "business_school"}
        listed = build_faculty_jobs_payload(self.db, query=query)["pagination"]["total"]
        summary = build_faculty_job_summary(self.db, query=query)["summary"]["active_jobs"]
        csv_text = export_faculty_jobs_csv(self.db, query=query)
        csv_rows = [line for line in csv_text.splitlines() if line.strip()][1:]
        self.assertEqual(listed, summary)
        self.assertEqual(listed, len(csv_rows))
        self.assertEqual("business_school",
                         build_faculty_job_filters(self.db, query=query)["filters"]["scope"])

    def test_scope_conditions_are_shared_rather_than_re_derived(self):
        clauses, args, scope = _scope_conditions({"scope": "business_school"}, "j.")
        self.assertEqual("business_school", scope)
        where = " AND ".join(clauses)
        self.assertIn("business_scope", where)
        count = self.conn.execute(f"SELECT COUNT(*) FROM jobs j WHERE {where}", args).fetchone()[0]
        self.assertEqual(self.count(), count)


class SortTests(unittest.TestCase):
    def test_market_priority_is_the_default_public_ordering(self):
        import inspect
        from services import faculty_jobs_service
        source = inspect.getsource(faculty_jobs_service.build_faculty_jobs_payload)
        self.assertIn('"fit" if include_private else "market_priority"', source)

    def test_the_ordering_prefers_continuing_appointments_over_adjunct_volume(self):
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        db = str(Path(directory.name) / "faculty.db")
        ensure_faculty_jobs_tables(db)
        conn = sqlite3.connect(db)
        try:
            # The adjunct posting is newer, so newest-first would put it top.
            conn.execute("""
                INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                                  business_scope,derived_quality,faculty_market_eligible,
                                  faculty_market_role,track_type,appointment_type,
                                  first_seen_at,last_seen_at,created_at,updated_at)
                VALUES (1,'k1','Assistant Professor of Finance','a','open','business_school',
                        'accepted',1,'faculty','tenure_track',NULL,
                        '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z',
                        '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z')
            """)
            conn.execute("""
                INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                                  business_scope,derived_quality,faculty_market_eligible,
                                  faculty_market_role,track_type,appointment_type,
                                  first_seen_at,last_seen_at,created_at,updated_at)
                VALUES (2,'k2','Adjunct Faculty, Accounting','b','open','business_school',
                        'accepted',1,'faculty','unknown','adjunct',
                        '2026-08-28T00:00:00Z','2026-08-28T00:00:00Z',
                        '2026-08-28T00:00:00Z','2026-08-28T00:00:00Z')
            """)
            conn.commit()
        finally:
            conn.close()
        default_order = [job["id"] for job in
                         build_faculty_jobs_payload(db, query={})["jobs"]]
        newest_order = [job["id"] for job in
                        build_faculty_jobs_payload(db, query={"sort": "newest"})["jobs"]]
        self.assertEqual([1, 2], default_order,
                         "a tenure-track line should not be buried by newer adjunct volume")
        self.assertEqual([2, 1], newest_order, "newest-first is still available unchanged")


if __name__ == "__main__":
    unittest.main()
