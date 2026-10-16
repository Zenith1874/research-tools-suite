# -*- coding: utf-8 -*-
"""Synthetic AACSB roster/detail/official-site contracts.

These tests never call AACSB or a school website.  Live coverage is recorded
separately by the opt-in bounded updater and must not be inferred from these
fixtures.
"""

from pathlib import Path
from types import SimpleNamespace
import contextlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from services.faculty_jobs_service import (
    FACULTY_JOBS_SCHEMA_VERSION,
    _aacsb_source_is_known_false_positive,
    _quarantine_known_aacsb_false_positives,
    _refresh_aacsb_accreditation_state,
    build_aacsb_directory_summary,
    ensure_faculty_jobs_tables,
    list_aacsb_directory,
    scan_aacsb_official_websites,
    update_aacsb_directory,
)
from services.faculty_jobs_sources.aacsb import (
    AACSB_SCAN_RULE_VERSION,
    AACSBDirectoryClient,
    AACSBDirectoryRecord,
    OfficialSiteScan,
    parse_detail_page,
    parse_directory_page,
    parse_directory_total,
)
from services.faculty_jobs_sources.base import SourceJob


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "faculty_jobs"


class _Response:
    def __init__(self, text, url, status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code
        self.headers = {}


class FacultyJobsAACSBTests(unittest.TestCase):
    def read(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_directory_parser_excludes_non_accredited_insertions(self):
        html = self.read("aacsb_directory.html")
        records = parse_directory_page(html, "https://www.aacsb.edu/api/member-search-page/load-members?page=1", "2026-08-24T00:00:00Z")
        self.assertEqual(2, len(records))
        self.assertEqual({"school-1", "school-2"}, {record.directory_result_id for record in records})
        self.assertEqual("Example University", records[0].institution_name)
        self.assertEqual("Example School of Business", records[0].school_name)
        self.assertEqual("Dublin, Ireland", records[0].location_raw)
        self.assertEqual(3, parse_directory_total(html))

    def test_false_positive_policy_uses_source_identity_not_local_job_id(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-decision-grain-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            source_id = conn.execute(
                "SELECT id FROM sources WHERE name='aacsb_official'"
            ).fetchone()["id"]
            reviewed_source_job_id = "92253496ea68c11694a496dbee0c6384"
            valid_source_job_id = "valid-finance-record-with-local-id-202"
            self.assertTrue(_aacsb_source_is_known_false_positive(
                conn, source_id, reviewed_source_job_id))
            self.assertFalse(_aacsb_source_is_known_false_positive(
                conn, source_id, valid_source_job_id))

            now = "2026-08-27T00:00:00Z"
            for job_id, key, title in (
                (202, "valid-local-202", "Assistant Professor of Finance"),
                (987, "reviewed-source-987", "Dean of AAGBS"),
            ):
                conn.execute("""
                    INSERT INTO jobs
                      (id,canonical_key,title_raw,title_normalized,derived_quality,
                       business_scope,faculty_market_role,faculty_market_eligible,status,
                       first_seen_at,last_seen_at,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (job_id, key, title, title.casefold(), "accepted",
                      "business_discipline", "faculty", 1, "open",
                      now, now, now, now))
            conn.execute("""
                INSERT INTO job_sources
                  (job_id,source_id,source_job_id,source_url,first_seen,last_seen,active)
                VALUES (202,?,?,?, ?,?,1)
            """, (source_id, valid_source_job_id, "https://example.edu/valid", now, now))
            conn.execute("""
                INSERT INTO job_sources
                  (job_id,source_id,source_job_id,source_url,first_seen,last_seen,active)
                VALUES (987,?,?,?, ?,?,1)
            """, (source_id, reviewed_source_job_id, "https://example.edu/reviewed", now, now))

            stats = _quarantine_known_aacsb_false_positives(conn)
            conn.commit()
            self.assertEqual(1, stats["jobs"])
            self.assertEqual((1, "accepted"), tuple(conn.execute("""
                SELECT js.active,j.derived_quality FROM job_sources js
                JOIN jobs j ON j.id=js.job_id WHERE js.source_job_id=?
            """, (valid_source_job_id,)).fetchone()))
            self.assertEqual((0, "quarantined"), tuple(conn.execute("""
                SELECT js.active,j.derived_quality FROM job_sources js
                JOIN jobs j ON j.id=js.job_id WHERE js.source_job_id=?
            """, (reviewed_source_job_id,)).fetchone()))
            conn.close()

    def test_directory_fetch_records_raw_result_and_exclusion_grains(self):
        client = AACSBDirectoryClient(timeout=5, max_pages=1, delay=0.1)
        response = _Response(
            self.read("aacsb_directory.html"),
            "https://www.aacsb.edu/api/member-search-page/load-members?page=1",
        )
        with patch.object(client, "request", return_value=response):
            records, pages, reported = client.fetch_directory(max_pages=1)
        self.assertEqual(2, len(records))
        self.assertEqual(1, pages)
        self.assertEqual(3, reported)
        self.assertEqual({
            "reported_results": 3,
            "raw_results_observed": 3,
            "accredited_records_observed": 2,
            "non_accredited_results_excluded": 1,
            "complete": True,
            "max_pages_requested": 1,
            "max_records": None,
            "pages_fetched": 1,
            "pagination_natural_end": True,
            "page_budget_exhausted": False,
            "error_count": 0,
        }, client.last_directory_metadata)

    def test_detail_parser_preserves_official_website_and_accreditation_scope(self):
        record = AACSBDirectoryRecord(
            directory_result_id="school-1",
            directory_url="https://www.aacsb.edu/accredited/a/example-business-school",
            institution_name="Example University",
            school_name="Example School of Business",
            location_raw="Dublin, Ireland",
            directory_title="Example University Example School of Business",
            roster_source_url="https://www.aacsb.edu/accredited",
            captured_at="2026-08-24T00:00:00Z",
        )
        parsed = parse_detail_page(self.read("aacsb_detail.html"), record)
        self.assertEqual("https://business.example.edu/", parsed.official_website)
        self.assertEqual("Business & Accounting", parsed.accreditation_scope)
        self.assertEqual("ok", parsed.detail_status)
        self.assertIn("accredited business school", parsed.detail_excerpt)

    def test_official_site_jsonld_is_a_public_academic_job_only(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-1",
            directory_url="https://www.aacsb.edu/accredited/a/example-business-school",
            institution_name="Example University",
            school_name="Example School of Business",
            location_raw="Dublin, Ireland",
            directory_title="Example University Example School of Business",
            roster_source_url="https://www.aacsb.edu/accredited",
            captured_at="2026-08-24T00:00:00Z",
            official_website="https://business.example.edu/",
            accreditation_scope="Business",
            detail_status="ok",
        )
        responses = [
            _Response("<a href='/faculty-positions'>Faculty positions</a>", "https://business.example.edu/"),
            _Response(self.read("aacsb_official_jobs.html"), "https://business.example.edu/faculty-positions"),
        ]
        with patch.object(client, "request", side_effect=responses):
            scan = client.scan_official_site(record, max_pages=2, max_jobs=5)
        self.assertEqual("jobs_found", scan.job_scan_status)
        self.assertEqual(1, len(scan.jobs))
        job = scan.jobs[0]
        self.assertEqual("Assistant Professor of Marketing", job.title_raw)
        self.assertEqual("Example University", job.institution_raw)
        self.assertEqual("Dublin, IE", job.location_raw)
        self.assertEqual("2026-10-01", job.deadline_raw)
        self.assertIn("EUR", job.salary_raw)
        self.assertEqual("https://business.example.edu/jobs/marketing-2026", job.official_url)
        self.assertEqual("https://business.example.edu/faculty-positions", job.source_url)

    def test_no_explicit_job_page_is_not_reported_as_no_jobs_when_unchecked(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-2",
            directory_url="https://www.aacsb.edu/accredited/u/another-university",
            institution_name="Another University",
            school_name="College of Management",
            location_raw="Dhaka, Bangladesh",
            directory_title="Another University College of Management",
            roster_source_url="https://www.aacsb.edu/accredited",
            captured_at="2026-08-24T00:00:00Z",
            official_website="https://business.example.edu/",
            detail_status="ok",
        )
        response = _Response("<p>Welcome to the school.</p>", "https://business.example.edu/")
        with patch.object(client, "request", return_value=response):
            scan = client.scan_official_site(record, max_pages=2)
        self.assertIn(scan.job_scan_status, {"not_found", "unknown"})
        self.assertEqual([], scan.jobs)
        self.assertNotEqual("jobs_found", scan.job_scan_status)

    def test_generic_university_faculty_posting_is_not_assumed_to_be_business(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-generic",
            directory_url="https://www.aacsb.edu/accredited/generic-school",
            institution_name="Example University",
            school_name="College of Business",
            location_raw="Austin, Texas, United States",
            directory_title="Example University College of Business",
            roster_source_url="https://www.aacsb.edu/accredited",
            captured_at="2026-08-24T00:00:00Z",
            official_website="https://www.example.edu/",
            detail_status="ok",
        )
        home = _Response("<a href='/careers'>Faculty careers</a>", "https://www.example.edu/")
        career = _Response("""
          <script type="application/ld+json">
            {"@type":"JobPosting","title":"Assistant Professor of Physics",
             "url":"https://www.example.edu/jobs/physics-1",
             "hiringOrganization":{"name":"Example University"},
             "description":"Tenure-track appointment in physics."}
          </script>
        """, "https://www.example.edu/careers")
        with patch.object(client, "request", side_effect=[home, career]):
            scan = client.scan_official_site(record, max_pages=2)
        self.assertEqual("no_eligible_business_faculty_jobs", scan.job_scan_status)
        self.assertEqual([], scan.jobs)
        self.assertEqual(1, scan.candidates_seen)
        self.assertEqual(1, scan.candidates_rejected)

    def test_student_generic_and_roster_only_candidates_are_rejected(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-boundary",
            directory_url="https://www.aacsb.edu/accredited/boundary-school",
            institution_name="Example University",
            school_name="College of Business",
            location_raw="Austin, Texas, United States",
            directory_title="Example University College of Business",
            roster_source_url="https://www.aacsb.edu/accredited",
            captured_at="2026-08-24T00:00:00Z",
            official_website="https://www.example.edu/",
            detail_status="ok",
        )
        home = _Response("<a href='/careers'>Faculty careers</a>", "https://www.example.edu/")
        career = _Response('''
          <script type="application/ld+json">
          {"@graph":[
            {"@type":"JobPosting",
             "title":"Graduate Assistant, Master of Accountancy - College of Business",
             "url":"https://www.example.edu/jobs/ga-1",
             "description":"Student appointment in the College of Business."},
            {"@type":"JobPosting",
             "title":"Assistant Professor",
             "url":"https://www.example.edu/jobs/generic-1",
             "description":"Tenure-track appointment."}
          ]}
          </script>
          <a href="/jobs/faculty">Faculty Job Openings</a>
        ''', "https://www.example.edu/careers")
        with patch.object(client, "request", side_effect=[home, career]):
            scan = client.scan_official_site(record, max_pages=2)
        self.assertEqual("no_eligible_business_faculty_jobs", scan.job_scan_status)
        self.assertEqual([], scan.jobs)
        self.assertEqual(3, scan.candidates_seen)
        self.assertEqual(3, scan.candidates_rejected)

    def test_explicit_job_link_is_kept_but_faculty_directory_link_is_rejected(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-links",
            directory_url="https://www.aacsb.edu/accredited/links-school",
            institution_name="Example University", school_name="School of Business",
            location_raw="Dublin, Ireland", directory_title="Example University School of Business",
            roster_source_url="https://www.aacsb.edu/accredited", captured_at="2026-08-24T00:00:00Z",
            official_website="https://business.example.edu/", detail_status="ok",
        )
        home = _Response("<a href='/careers'>Careers</a>", "https://business.example.edu/")
        career = _Response("""
          <a href="/jobs/finance-1">Assistant Professor of Finance</a>
          <a href="/business/faculty-directory">Faculty Directory</a>
        """, "https://business.example.edu/careers")
        with patch.object(client, "request", side_effect=[home, career]):
            scan = client.scan_official_site(record, max_pages=2)
        self.assertEqual("jobs_found", scan.job_scan_status)
        self.assertEqual(1, len(scan.jobs))
        self.assertEqual("Assistant Professor of Finance", scan.jobs[0].title_raw)

    def test_html_job_link_is_checked_when_jsonld_has_only_nonbusiness_posting(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-jsonld-mixed",
            directory_url="https://www.aacsb.edu/accredited/mixed-school",
            institution_name="Example University", school_name="School of Business",
            location_raw="Austin, Texas, United States", directory_title="Example University School of Business",
            roster_source_url="https://www.aacsb.edu/accredited", captured_at="2026-08-24T00:00:00Z",
            official_website="https://business.example.edu/", detail_status="ok",
        )
        home = _Response("<a href='/careers'>Faculty careers</a>", "https://business.example.edu/")
        career = _Response('''
          <script type="application/ld+json">
            {"@type":"JobPosting","title":"Assistant Professor of Physics",
             "url":"https://www.example.edu/jobs/physics-1",
             "hiringOrganization":{"name":"Example University"},
             "description":"Tenure-track appointment in physics."}
          </script>
          <a href="/jobs/finance-1">Assistant Professor of Finance</a>
        ''', "https://business.example.edu/careers")
        with patch.object(client, "request", side_effect=[home, career]):
            scan = client.scan_official_site(record, max_pages=2)
        self.assertEqual("jobs_found", scan.job_scan_status)
        self.assertEqual(["Assistant Professor of Finance"], [job.title_raw for job in scan.jobs])

    def test_official_scan_collects_jobs_from_multiple_public_career_entries(self):
        client = AACSBDirectoryClient(timeout=5, delay=0.1)
        record = AACSBDirectoryRecord(
            directory_result_id="school-multiple-career-pages",
            directory_url="https://www.aacsb.edu/accredited/multiple-school",
            institution_name="Example University", school_name="School of Business",
            location_raw="Austin, Texas, United States", directory_title="Example University School of Business",
            roster_source_url="https://www.aacsb.edu/accredited", captured_at="2026-08-24T00:00:00Z",
            official_website="https://business.example.edu/", detail_status="ok",
        )
        home = _Response('''
          <a href="/careers/faculty">Faculty careers</a>
          <a href="/employment">Employment</a>
        ''', "https://business.example.edu/")
        finance = _Response(
            '<a href="/jobs/finance-1">Assistant Professor of Finance</a>',
            "https://business.example.edu/careers/faculty",
        )
        marketing = _Response(
            '<a href="/jobs/marketing-1">Assistant Professor of Marketing</a>',
            "https://business.example.edu/employment",
        )
        with patch.object(client, "request", side_effect=[home, finance, marketing]):
            scan = client.scan_official_site(record, max_pages=2, max_jobs=5)
        self.assertEqual("jobs_found", scan.job_scan_status)
        self.assertEqual(
            {"Assistant Professor of Finance", "Assistant Professor of Marketing"},
            {job.title_raw for job in scan.jobs},
        )

    def test_schema_migration_is_idempotent_and_integrity_safe(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-schema-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            ensure_faculty_jobs_tables(db)
            # closing() matters here: without it a failed assertion leaves the
            # handle open, Windows refuses to remove the temp directory, and the
            # cleanup error replaces the assertion in the report.
            with contextlib.closing(sqlite3.connect(db)) as conn:
                self.check_migrated_schema(conn)

    def check_migrated_schema(self, conn):
            names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"aacsb_directory_schools", "aacsb_scan_history", "aacsb_scan_runs",
                             "source_record_decisions"}.issubset(names))
            self.assertEqual("ok", conn.execute("PRAGMA quick_check").fetchone()[0])
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=16").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=17").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=18").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=19").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=20").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=25").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=28").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=29").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=30").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=31").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=32").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=33").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=34").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=35").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=36").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=37").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=38").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=67").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=68").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=69").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=70").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=71").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM faculty_job_migrations WHERE version=72").fetchone()[0])
            self.assertEqual(FACULTY_JOBS_SCHEMA_VERSION,
                             conn.execute("PRAGMA user_version").fetchone()[0],
                             "user_version must track the migration ledger")
            self.assertEqual(16, conn.execute(
                "SELECT COUNT(*) FROM source_record_decisions WHERE decision='false_positive' AND is_current=1"
            ).fetchone()[0])
            job_columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            self.assertTrue({
                "derived_quality", "faculty_market_role", "faculty_market_eligible",
                "faculty_market_reason", "school_evidence_context",
            }.issubset(job_columns))
            self.assertTrue({
                "candidates_seen", "candidates_rejected", "scan_rule_version",
            }.issubset({row[1] for row in conn.execute("PRAGMA table_info(aacsb_scan_history)")}))
            self.assertIn("scan_rule_version", {row[1] for row in conn.execute("PRAGMA table_info(aacsb_directory_schools)")})
            self.assertTrue({
                "directory_results_reported", "directory_results_observed",
                "non_accredited_results_excluded", "directory_observation_complete", "scan_rule_version",
            }.issubset({row[1] for row in conn.execute("PRAGMA table_info(aacsb_scan_runs)")}))
            self.assertTrue({
                "seen_source_job_ids", "reconciliation_complete", "reconciliation_reason", "scan_run_id",
            }.issubset({row[1] for row in conn.execute("PRAGMA table_info(aacsb_scan_history)")}))
            self.assertTrue({
                "directory_pagination_natural_end", "directory_metadata_json",
            }.issubset({row[1] for row in conn.execute("PRAGMA table_info(aacsb_scan_runs)")}))
            self.assertTrue({
                "directory_school_id", "source_job_id", "consecutive_missing_runs", "active",
            }.issubset({row[1] for row in conn.execute("PRAGMA table_info(aacsb_job_source_partitions)")}))
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM sources WHERE name='aacsb_official'").fetchone()[0])
            self.assertEqual("opt_in", conn.execute("SELECT support_status FROM sources WHERE name='aacsb_official'").fetchone()[0])
            conn.close()

    def test_scan_existing_records_history_and_job_provenance(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-scan-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            conn = sqlite3.connect(db)
            now = "2026-08-24T00:00:00Z"
            conn.execute("""
                INSERT INTO aacsb_directory_schools
                  (directory_result_id,directory_url,institution_name,school_name,directory_title,
                   official_website,roster_source_url,first_seen_at,last_seen_at,
                   detail_status,active,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, ("scan-school", "https://www.aacsb.edu/accredited/a/scan-school",
                   "Example University", "Example School of Business",
                   "Example University Example School of Business",
                   "https://business.example.edu/", "https://www.aacsb.edu/accredited",
                   now, now, "ok", 1, now, now))
            conn.commit()
            conn.close()

            job = SourceJob(
                source="aacsb_official", source_job_id="official-1",
                source_url="https://business.example.edu/faculty-positions",
                official_url="https://business.example.edu/jobs/official-1",
                title_raw="Assistant Professor of Finance",
                institution_raw="Example University", school_raw="Example School of Business",
                location_raw="Dublin, Ireland", deadline_raw="2026-10-01",
                captured_at=now,
            )

            class FakeClient:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

                def scan_official_site(self, record, max_pages=2, max_jobs=20):
                    return OfficialSiteScan("ok", "found", "jobs_found",
                                           "https://business.example.edu/faculty-positions",
                                           [job], 200, "fixture job", complete=True)

            with patch("services.faculty_jobs_sources.aacsb.AACSBDirectoryClient", FakeClient):
                result = scan_aacsb_official_websites(db, max_schools=1, delay=0.1)
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["jobs_found"])
            conn = sqlite3.connect(db)
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM aacsb_scan_history").fetchone()[0])
            self.assertEqual("jobs_found", conn.execute("SELECT job_scan_status FROM aacsb_directory_schools").fetchone()[0])
            self.assertEqual(AACSB_SCAN_RULE_VERSION, conn.execute("SELECT scan_rule_version FROM aacsb_directory_schools").fetchone()[0])
            self.assertEqual(AACSB_SCAN_RULE_VERSION, conn.execute("SELECT scan_rule_version FROM aacsb_scan_history").fetchone()[0])
            self.assertEqual(AACSB_SCAN_RULE_VERSION, conn.execute("SELECT scan_rule_version FROM aacsb_scan_runs ORDER BY id DESC LIMIT 1").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM source_job_records").fetchone()[0])
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
            conn.close()
            self.assertEqual(0, result["stale_or_unchecked_remaining"])

    def test_complete_site_partition_missing_runs_do_not_close_job_supported_elsewhere(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-partition-lifecycle-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            now = "2026-08-24T00:00:00Z"
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            conn.execute("""
                INSERT INTO aacsb_directory_schools
                  (directory_result_id,directory_url,institution_name,school_name,directory_title,
                   official_website,roster_source_url,first_seen_at,last_seen_at,detail_status,
                   active,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, ("partition-school", "https://www.aacsb.edu/accredited/a/partition-school",
                   "Example University", "Example School of Business",
                   "Example University Example School of Business",
                   "https://business.example.edu/", "https://www.aacsb.edu/accredited",
                   now, now, "ok", 1, now, now))
            conn.commit()
            conn.close()

            job = SourceJob(
                source="aacsb_official", source_job_id="partition-job-1",
                source_url="https://business.example.edu/faculty-positions",
                official_url="https://business.example.edu/jobs/partition-job-1",
                title_raw="Assistant Professor of Finance",
                institution_raw="Example University", school_raw="Example School of Business",
                location_raw="Dublin, Ireland", captured_at=now,
            )

            class FakeClient:
                calls = 0

                def __init__(self, **kwargs):
                    self.kwargs = kwargs

                def scan_official_site(self, record, max_pages=2, max_jobs=20):
                    type(self).calls += 1
                    if type(self).calls in {1, 5}:
                        return OfficialSiteScan(
                            "ok", "found", "jobs_found", "https://business.example.edu/faculty-positions",
                            [job], 200, "fixture job", complete=True,
                        )
                    return OfficialSiteScan(
                        "ok", "found", "no_current_jobs", "https://business.example.edu/faculty-positions",
                        [], 200, "fixture complete empty result", complete=True,
                    )

            with patch("services.faculty_jobs_sources.aacsb.AACSBDirectoryClient", FakeClient):
                first = scan_aacsb_official_websites(db, max_schools=1, include_checked=True, delay=0.1)
                self.assertTrue(first["ok"])

                conn = sqlite3.connect(db)
                job_id = conn.execute("SELECT id FROM jobs WHERE title_raw=?", (job.title_raw,)).fetchone()[0]
                alternate_source = conn.execute(
                    "SELECT id FROM sources WHERE name!='aacsb_official' ORDER BY id LIMIT 1"
                ).fetchone()[0]
                conn.execute("""
                    INSERT INTO job_sources
                      (job_id,source_id,source_job_id,source_url,official_url,first_seen,last_seen,active)
                    VALUES (?,?,?,?,?,?,?,1)
                """, (job_id, alternate_source, "alternate-source-job",
                       "https://other.example/jobs/1", "https://other.example/jobs/1", now, now))
                conn.commit()
                conn.close()

                for _ in range(3):
                    result = scan_aacsb_official_websites(
                        db, max_schools=1, include_checked=True, delay=0.1,
                    )
                    self.assertTrue(result["ok"])

                conn = sqlite3.connect(db)
                partition = conn.execute("""
                    SELECT active,consecutive_missing_runs,last_scan_status
                    FROM aacsb_job_source_partitions
                """).fetchone()
                aacsb_link = conn.execute(
                    "SELECT active,consecutive_missing_runs FROM job_sources WHERE source_job_id=?",
                    (job.source_job_id,),
                ).fetchone()
                other_link = conn.execute(
                    "SELECT active FROM job_sources WHERE source_job_id='alternate-source-job'"
                ).fetchone()
                job_state = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
                self.assertEqual((0, 3, "no_current_jobs"), partition)
                self.assertEqual((0, 3), aacsb_link)
                self.assertEqual((1,), other_link)
                self.assertNotEqual("closed", job_state)
                conn.close()

                revived = scan_aacsb_official_websites(
                    db, max_schools=1, include_checked=True, delay=0.1,
                )
                self.assertTrue(revived["ok"])

            conn = sqlite3.connect(db)
            self.assertEqual((1, 0), conn.execute(
                "SELECT active,consecutive_missing_runs FROM aacsb_job_source_partitions"
            ).fetchone())
            self.assertEqual((1, 0), conn.execute(
                "SELECT active,consecutive_missing_runs FROM job_sources WHERE source_job_id=?",
                (job.source_job_id,),
            ).fetchone())
            self.assertEqual(5, conn.execute(
                "SELECT COUNT(*) FROM aacsb_scan_history"
            ).fetchone()[0])
            conn.close()

    def test_roster_run_persists_reported_and_excluded_result_grains(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-roster-run-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            record = AACSBDirectoryRecord(
                directory_result_id="school-run",
                directory_url="https://www.aacsb.edu/accredited/a/school-run",
                institution_name="Example University",
                school_name="Example School of Business",
                location_raw="Dublin, Ireland",
                directory_title="Example University Example School of Business",
                roster_source_url="https://www.aacsb.edu/accredited",
                captured_at="2026-08-24T00:00:00Z",
            )

            class FakeDirectoryClient:
                def __init__(self, **kwargs):
                    self.last_directory_metadata = {
                        "reported_results": 2,
                        "raw_results_observed": 2,
                        "accredited_records_observed": 1,
                        "non_accredited_results_excluded": 1,
                        "complete": True,
                    }

                def fetch_directory(self, **kwargs):
                    return [record], 1, 2

            with patch("services.faculty_jobs_sources.aacsb.AACSBDirectoryClient", FakeDirectoryClient):
                result = update_aacsb_directory(db, max_pages=1, fetch_details=False)
            self.assertTrue(result["ok"])
            self.assertEqual(1, result["non_accredited_results_excluded"])
            self.assertTrue(result["directory_observation_complete"])
            conn = sqlite3.connect(db)
            row = conn.execute("""
                SELECT directory_results_reported,directory_results_observed,
                       non_accredited_results_excluded,directory_observation_complete
                FROM aacsb_scan_runs ORDER BY id DESC LIMIT 1
            """).fetchone()
            self.assertEqual((2, 2, 1, 1), row)
            conn.close()

    def test_aacsb_current_evidence_retires_and_reappears_with_roster_state(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-accreditation-lifecycle-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            now = "2026-08-24T00:00:00Z"
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            conn.execute("""
                INSERT INTO institutions
                  (id,official_name,normalized_name,country_code,is_current,created_at,updated_at)
                VALUES (1,'Example University','example university','IE',1,?,?)
            """, (now, now))
            conn.execute("""
                INSERT INTO business_schools
                  (id,institution_id,official_name,normalized_name,is_current,created_at,updated_at)
                VALUES (1,1,'Example School of Business','example school of business',1,?,?)
            """, (now, now))
            conn.execute("""
                INSERT INTO aacsb_directory_schools
                  (id,directory_result_id,directory_url,institution_name,school_name,directory_title,
                   official_website,roster_source_url,first_seen_at,last_seen_at,detail_status,
                   country_code,active,linked_business_school_id,created_at,updated_at)
                VALUES (1,'lifecycle-school','https://www.aacsb.edu/accredited/a/lifecycle-school',
                        'Example University','Example School of Business',
                        'Example University Example School of Business','https://business.example.edu/',
                        'https://www.aacsb.edu/accredited',?,?, 'ok','IE',1,1,?,?)
            """, (now, now, now, now))
            conn.commit()

            _refresh_aacsb_accreditation_state(conn)
            current = conn.execute(
                "SELECT aacsb FROM business_schools WHERE id=1"
            ).fetchone()[0]
            evidence = conn.execute(
                "SELECT COUNT(*) FROM school_evidence WHERE school_id=1 AND evidence_type='AACSB' AND is_current=1"
            ).fetchone()[0]
            self.assertEqual(1, current)
            self.assertEqual(1, evidence)

            conn.execute("UPDATE aacsb_directory_schools SET active=0 WHERE id=1")
            _refresh_aacsb_accreditation_state(conn)
            self.assertEqual(0, conn.execute(
                "SELECT aacsb FROM business_schools WHERE id=1"
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM school_evidence WHERE school_id=1 AND evidence_type='AACSB' AND is_current=1"
            ).fetchone()[0])
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM school_evidence WHERE school_id=1 AND evidence_type='AACSB' AND is_current=0"
            ).fetchone()[0])

            conn.execute("UPDATE aacsb_directory_schools SET active=1 WHERE id=1")
            _refresh_aacsb_accreditation_state(conn)
            self.assertEqual(1, conn.execute(
                "SELECT aacsb FROM business_schools WHERE id=1"
            ).fetchone()[0])
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM school_evidence WHERE school_id=1 AND evidence_type='AACSB' AND is_current=1"
            ).fetchone()[0])
            self.assertEqual(1, conn.execute(
                "SELECT COUNT(*) FROM school_evidence WHERE school_id=1 AND evidence_type='AACSB' AND is_current=0"
            ).fetchone()[0])
            conn.close()

    def test_directory_prioritizes_current_rule_and_summary_separates_current_candidates(self):
        with tempfile.TemporaryDirectory(prefix="aacsb-current-rule-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            conn = sqlite3.connect(db)
            now = "2026-08-24T00:00:00Z"
            rows = [
                ("stale", "https://www.aacsb.edu/accredited/a/stale", "Alpha Stale University", 9, 40, 10, "legacy_rule"),
                ("current", "https://www.aacsb.edu/accredited/z/current", "Zulu Current University", 0, 3, 2, AACSB_SCAN_RULE_VERSION),
            ]
            for result_id, url, institution, jobs, seen, rejected, rule in rows:
                conn.execute("""
                    INSERT INTO aacsb_directory_schools
                      (directory_result_id,directory_url,institution_name,directory_title,
                       official_website,roster_source_url,first_seen_at,last_seen_at,
                       detail_status,website_checked_at,job_scan_status,jobs_found,
                       candidates_seen,candidates_rejected,scan_rule_version,
                       active,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (result_id, url, institution, institution, "https://example.edu/",
                       "https://www.aacsb.edu/accredited", now, now, "ok", now,
                       "jobs_found" if jobs else "no_current_jobs", jobs, seen, rejected,
                       rule, 1, now, now))
            conn.commit()
            conn.close()

            listing = list_aacsb_directory(db, limit=10)
            self.assertEqual("Zulu Current University", listing["schools"][0]["institution_name"])
            summary = build_aacsb_directory_summary(db)["summary"]
            self.assertEqual(3, summary["candidates_seen_current_rule"])
            self.assertEqual(2, summary["candidates_rejected_current_rule"])
            self.assertEqual(43, summary["candidates_seen"])

    def test_aacsb_directory_http_routes_are_public_read_only(self):
        import http.client
        import json
        import server
        import threading

        with tempfile.TemporaryDirectory(prefix="aacsb-http-") as directory:
            db = Path(directory) / "faculty_jobs.db"
            ensure_faculty_jobs_tables(db)
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(server, "FACULTY_DB_PATH", db):
                    for path in (
                        "/api/faculty-jobs/aacsb/summary",
                        "/api/aacsb-directory/summary",
                        "/api/faculty-jobs/aacsb/directory?limit=5",
                    ):
                        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=20)
                        connection.request("GET", path)
                        response = connection.getresponse()
                        payload = json.loads(response.read().decode("utf-8"))
                        connection.close()
                        self.assertEqual(200, response.status, path)
                        self.assertTrue(payload.get("ok"), path)
            finally:
                httpd.shutdown(); httpd.server_close(); thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
