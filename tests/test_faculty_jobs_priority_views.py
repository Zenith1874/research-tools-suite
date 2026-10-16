"""Regression coverage for priority correctness and separate career views."""
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from services.faculty_jobs_career_views import import_profiles, link_institution, career_view_sql
from services.faculty_jobs_lifecycle import effective_status, effective_status_sql, lifecycle_fields
from services.faculty_jobs_normalizer import infer_track, normalize_source_job
from services.faculty_jobs_sources.base import SourceJob
from services.faculty_jobs_service import (
    ensure_faculty_jobs_tables, build_faculty_jobs_payload, build_faculty_job_summary,
    export_faculty_jobs_csv, _sanitize_saved_search_query, _status_for,
)
from services.institution_matching import normalize_institution
from scripts.repair_faculty_job_priorities import apply_repairs, protected_fingerprints


class TrackTests(unittest.TestCase):
    def test_negations_and_positive_contracts(self):
        for title in ["Non-Tenure Track", "Non Tenure Track", "Nontenure-track", "Non–Tenure Track", "Not a tenure-track position", "FT, non-TT Lecturer"]:
            self.assertEqual("non_tenure_track", infer_track(title), title)
        self.assertEqual("tenure_track", infer_track("Tenure-track Assistant Professor"))
        self.assertEqual("unknown", infer_track("Tenure-track and non-tenure-track faculty opportunities"))

    def test_title_wins_over_context_about_other_faculty(self):
        job = SourceJob(source="test", source_job_id="1", source_url="https://example.edu/1",
            title_raw="Lecturer (Non-Tenure Track)",
            description_excerpt="Our department also has tenure-track faculty.")
        self.assertEqual("non_tenure_track", normalize_source_job(job)["track_type"])


class LifecycleTests(unittest.TestCase):
    def test_python_sql_parity_and_no_rolling_expiration(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE jobs(status,deadline_mode,deadline_date)")
        today = date(2026, 9, 21)
        cases = [("open", "fixed", "2026-09-20", "closed"),
                 ("likely_open", "fixed", "2026-09-21", "closing_soon"),
                 ("closing_soon", "fixed", "2027-01-01", "open"),
                 ("open", "open_until_filled", "2026-08-01", "open"),
                 ("open", "rolling", "2026-08-01", "open"),
                 ("closing_soon", "open_until_filled", "2026-10-01", "likely_open"),
                 ("closing_soon", "rolling", "2026-08-01", "likely_open"),
                 ("closed", "fixed", "2027-01-01", "closed"),
                 ("unknown", "fixed", "2027-01-01", "unknown"),
                 ("open", "fixed", "2026-02-30", "open"),
                 ("open", "fixed", "", "open")]
        for status, mode, deadline, expected in cases:
            conn.execute("DELETE FROM jobs")
            conn.execute("INSERT INTO jobs VALUES (?,?,?)", (status, mode, deadline))
            self.assertEqual(expected, conn.execute("SELECT " + effective_status_sql("jobs", today) + " FROM jobs").fetchone()[0])
            self.assertEqual(expected, effective_status(dict(status=status, deadline_mode=mode, deadline_date=deadline), today))
        conn.close()

    def test_rolling_review_date_and_freshness_are_not_proof_of_closure(self):
        status, _ = _status_for({"deadline_date": "2020-01-01", "deadline_mode": "rolling"})
        self.assertEqual("likely_open", status)
        fields = lifecycle_fields({"status": "open", "last_seen_at": "2026-08-01T00:00:00Z"}, date(2026, 9, 21))
        self.assertEqual("open", fields["status"])
        self.assertEqual("stale", fields["freshness"])


class CareerViewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.temp.name) / "fixture.db"
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.profiles = []
        for unitid, name, level, teaching in [(1, "Research University", "R1", 0), (2, "Regional University", "R2", 1), (3, "Teaching College", "Other", 1), (4, "Research University South Campus", "R2", 0)]:
            self.profiles.append(dict(unitid=unitid, data_year=2025, official_name=name,
                name_key=normalize_institution(name), research_level=level, research_designation=level,
                institutional_classification="Test category", teaching_proxy=teaching,
                state="CA", city="Test", source_url="https://example.edu/source", source_sha256="fixture"))
        import_profiles(self.conn, self.profiles)
        for i, name, country, state in [(1, "Research University", "US", "CA"), (2, "Regional University", "US", "CA"), (3, "Teaching College", "US", "CA"), (4, "Unmatched College", "US", "CA"), (5, "Research University South Campus", "CA", "ON"), (6, "Research University", "US", "NY")]:
            self.conn.execute("""INSERT INTO institutions
                (id,official_name,normalized_name,country_code,state_province,created_at,updated_at)
                VALUES (?,?,?,?,?,'2026-09-01','2026-09-01')""", (i, name, str(i), country, state))
            link_institution(self.conn, i)
        for i in range(1, 5):
            self.conn.execute("""INSERT INTO jobs
                (id,institution_id,canonical_key,title_raw,title_normalized,status,business_scope,
                 derived_quality,faculty_market_eligible,faculty_market_role,track_type,
                 first_seen_at,last_seen_at,created_at,updated_at)
                VALUES (?,?,?,'Lecturer (Non-Tenure Track)','lecturer','open','business_school',
                        'accepted',1,'faculty','tenure_track','2026-09-01','2026-09-01','2026-09-01','2026-09-01')""", (i, i, f"job-{i}"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def test_views_are_disjoint_and_overlap_is_not_double_counted(self):
        for view, expected in [("r1", [1]), ("r2_teaching", [2, 3]), ("r2", [2]), ("teaching", [2, 3]), ("unclassified", [4])]:
            query = {"scope": "business_school", "career_view": view}
            listed = build_faculty_jobs_payload(self.db, query)
            self.assertEqual(expected, sorted(job["id"] for job in listed["jobs"]))
            summary = build_faculty_job_summary(self.db, query)["summary"]
            exported = list(csv.DictReader(io.StringIO(export_faculty_jobs_csv(self.db, query))))
            self.assertEqual(len(expected), summary["matching_records"])
            self.assertEqual(len(expected), len(exported))
            self.assertEqual(2, summary["career_view_counts"]["r2_teaching"])
            self.assertIn("carnegie_year", exported[0])

    def test_identity_country_state_and_campus_guards(self):
        self.assertEqual("ineligible", link_institution(self.conn, 5))
        self.assertEqual("unmatched", link_institution(self.conn, 6))
        links = [tuple(row) for row in self.conn.execute("SELECT institution_id,unitid FROM institution_career_links ORDER BY 1")]
        self.assertEqual([(1, 1), (2, 2), (3, 3)], links)

    def test_expiry_updates_every_read_without_writing_observations(self):
        expired = (date.today() - timedelta(days=1)).isoformat()
        self.conn.execute("UPDATE jobs SET deadline_mode='fixed',deadline_date=? WHERE id=1", (expired,))
        self.conn.commit()
        query = {"career_view": "r1"}
        self.assertEqual(0, build_faculty_jobs_payload(self.db, query)["pagination"]["total"])
        self.assertEqual(0, build_faculty_job_summary(self.db, query)["summary"]["matching_records"])
        job = build_faculty_jobs_payload(self.db, {**query, "status": "closed"})["jobs"][0]
        self.assertEqual("closed", job["status"])
        self.assertEqual("open", job["observed_status"])
        self.assertEqual("open", self.conn.execute("SELECT status FROM jobs WHERE id=1").fetchone()[0])

    def test_repairs_are_idempotent_and_preserve_private_and_source_content(self):
        before = protected_fingerprints(self.conn)
        first = apply_repairs(self.conn, self.profiles)
        second = apply_repairs(self.conn, self.profiles)
        self.assertEqual(4, len(first["track_repairs"]))
        self.assertEqual(0, len(second["track_repairs"]))
        self.assertEqual(before, protected_fingerprints(self.conn))
        self.assertEqual(4, self.conn.execute("SELECT COUNT(*) FROM job_field_provenance WHERE field_name='track_type' AND is_current=1").fetchone()[0])

    def test_saved_search_keeps_career_and_other_filters(self):
        query = {"career_view": "r1", "source": "carnegie_official", "visa_stance": "supportive",
                 "include_contingent": "1", "appointment_type": "full_time", "country": "US,CA", "sort": "market_priority"}
        saved = _sanitize_saved_search_query(query)
        for key, value in query.items():
            self.assertEqual(value, saved[key])
        with self.assertRaises(ValueError):
            career_view_sql("r1 OR 1=1")

    def test_excerpt_shorthand_and_ambiguity_do_not_survive_as_tenure_track(self):
        self.conn.execute("UPDATE jobs SET title_raw='Clinical Assistant Professor',description_excerpt='FT, non-TT clinical appointment' WHERE id=1")
        self.conn.execute("UPDATE jobs SET title_raw='Faculty opportunities',description_excerpt='Tenure-track and non-tenure-track appointments' WHERE id=2")
        self.conn.execute("UPDATE jobs SET title_raw='Tenure-track Professor',description_excerpt='Our other faculty include non-TT lecturers' WHERE id=3")
        result = apply_repairs(self.conn, self.profiles)
        tracks = {r['id']: r['track_type'] for r in self.conn.execute('SELECT id,track_type FROM jobs')}
        self.assertEqual('non_tenure_track', tracks[1])
        self.assertEqual('unknown', tracks[2])
        self.assertEqual('tenure_track', tracks[3])


if __name__ == "__main__":
    unittest.main()
