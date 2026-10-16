"""Offline bridge, coverage and existing ingestion contract tests."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services.carnegie_vacancy_scan import CarnegieVacancyScanner
from services.faculty_jobs_service import (
    build_faculty_job_sources, ensure_faculty_jobs_tables, update_faculty_jobs,
)
from services.faculty_jobs_sources.carnegie import (
    CarnegieOfficialAdapter, posting_scope, promote_record, source_coverage,
)
from services.faculty_jobs_sources.base import now_utc


TARGET = {"unitid": 1, "institution_name": "Example University", "city": "Test City",
          "state": "NM", "target_segment": "r2"}


def record(**kwargs):
    return {"id": 1, "run_id": 1, "title_raw": "Assistant Professor of Management",
            "institution_raw": "Example University", "target_unitid": 1,
            "target_match_status": "organization_exact", "source_url": "https://example.edu/jobs",
            "official_url": "https://example.edu/jobs/management-1", "captured_at": now_utc(),
            "extraction_method": "jsonld_jobposting", "detail_status": "not_attempted",
            "description_excerpt": "Teach management in the College of Business.", "raw_json": "{}", **kwargs}


class PromotionTests(unittest.TestCase):
    def test_individual_has_stable_id_across_portals_and_preserves_provenance(self):
        first, reason = promote_record(record(), TARGET)
        second, _ = promote_record(record(source_url="https://example.edu/hr"), TARGET)
        self.assertEqual("accepted", reason)
        self.assertEqual(first.source_job_id, second.source_job_id)
        self.assertEqual(1, first.extra["unitid"])
        self.assertEqual("individual", first.extra["posting_scope"])

    def test_pool_collection_unknown_stale_and_conflict_are_held(self):
        cases = [
            ({"title_raw": "Adjunct Professor Pool"}, "scope_pool"),
            ({"title_raw": "Faculty Positions"}, "scope_collection"),
            ({"extraction_method": "explicit_job_link"}, "scope_unknown"),
            ({"captured_at": "2020-01-01T00:00:00Z"}, "stale_observation"),
            ({"institution_raw": "Different University"}, "conflicting_institution"),
            ({"target_match_status": "shared_group_unresolved"}, "unresolved_institution"),
            ({"official_url": "https://example.edu/management.pdf"}, "unread_document"),
            ({"raw_json": '{"detail_accepted":false}'}, "ineligible_detail_or_role"),
            ({"description_excerpt": "Applications are held in an applicant pool."}, "scope_pool"),
            ({"institution_raw": None, "portal_target_unitids": [1, 2]}, "shared_portal_unresolved"),
            ({"institution_raw": None, "official_url": "https://other.edu/job/1"}, "external_employer_unverified"),
        ]
        for changes, expected in cases:
            with self.subTest(expected=expected):
                job, reason = promote_record(record(**changes), TARGET)
                self.assertIsNone(job)
                self.assertEqual(expected, reason)

    def test_html_needs_new_explicit_detail_evidence(self):
        item = record(extraction_method="explicit_job_link", detail_status="ok")
        self.assertEqual("unknown", posting_scope(item))
        item["raw_json"] = json.dumps({"detail_accepted": True,
            "detail_raw_json": {"detail_jsonld_count": 0, "explicit_role_heading": True}})
        self.assertEqual("individual", posting_scope(item))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.registry, self.scan, self.production = root / "registry.db", root / "scan.db", root / "jobs.db"
        conn = sqlite3.connect(self.registry)
        conn.executescript("""
            CREATE TABLE institution_recruitment_targets (
                unitid INTEGER, institution_name TEXT, city TEXT, state TEXT,
                target_segment TEXT, website_group_key TEXT, is_r2 INTEGER,
                is_teaching_oriented INTEGER, official_website_url TEXT);
            INSERT INTO institution_recruitment_targets VALUES
                (1,'Example University','Test City','NM','r2','example.edu',1,0,'https://example.edu');
            CREATE TABLE institution_recruitment_websites (latest_status TEXT);
            INSERT INTO institution_recruitment_websites VALUES ('portals_found');
            CREATE TABLE institution_recruitment_portals (
                id INTEGER, website_group_key TEXT, canonical_url TEXT, portal_kind TEXT,
                latest_page_status TEXT, latest_title TEXT, discovery_evidence TEXT,
                latest_jobposting_jsonld INTEGER, active INTEGER);
            INSERT INTO institution_recruitment_portals VALUES
                (1,'example.edu','https://example.edu/jobs-a','central_recruitment','ok','Faculty Jobs','Jobs',1,1),
                (2,'example.edu','https://example.edu/jobs-b','central_recruitment','ok','Faculty Jobs','Jobs',1,1);
        """)
        conn.close()
        self.html = '<script type="application/ld+json">' + json.dumps({
            "@type": "JobPosting", "title": "Assistant Professor of Management",
            "url": "https://example.edu/jobs/management-1", "hiringOrganization": {"name": "Example University"},
            "description": "Teach management in the College of Business. " * 20,
        }) + '</script>'

    def adapter(self):
        return CarnegieOfficialAdapter(registry_db=self.registry, scan_db=self.scan, max_pages=1)

    def fake_fetch(self, url):
        return SimpleNamespace(text=self.html, url=url, status_code=200)

    def test_live_bridge_advances_unvisited_then_oldest_without_claiming_completeness(self):
        with patch.object(CarnegieVacancyScanner, "_fetch", self.fake_fetch):
            first, second = self.adapter().fetch(), self.adapter().fetch()
        self.assertEqual(1, len(first.jobs))
        self.assertEqual(first.jobs[0].source_job_id, second.jobs[0].source_job_id)
        self.assertIn("offset=0", first.notes[0])
        self.assertIn("offset=1", second.notes[0])
        self.assertFalse(second.coverage_complete)
        coverage = source_coverage(self.registry, self.scan)
        self.assertEqual(2, coverage["scanned_eligible_portal_urls"])
        self.assertEqual(1, coverage["latest_candidate_urls"])
        self.assertEqual(0, coverage["remaining_eligible_portal_urls"])
        self.assertFalse(coverage["coverage_complete"])

    def test_read_only_coverage_does_not_create_missing_databases(self):
        missing = Path(self.temp.name) / "missing.db"
        self.assertFalse(source_coverage(missing, self.scan)["available"])
        self.assertFalse(missing.exists())
        before = self.registry.read_bytes()
        source_coverage(self.registry, self.scan)
        self.assertEqual(before, self.registry.read_bytes())
        self.assertFalse(self.scan.exists())

    def test_existing_ingestion_is_idempotent_and_partial_batches_do_not_close_jobs(self):
        ensure_faculty_jobs_tables(self.production)
        with patch.object(CarnegieVacancyScanner, "_fetch", self.fake_fetch):
            for _ in range(2):
                result = update_faculty_jobs(self.production, source_names=["carnegie_official"], adapters=[self.adapter()])
                self.assertTrue(result["ok"], result)
        self.html = "<h1>No listings in this HTML response</h1>"
        with patch.object(CarnegieVacancyScanner, "_fetch", self.fake_fetch):
            for _ in range(3):
                result = update_faculty_jobs(self.production, source_names=["carnegie_official"], adapters=[self.adapter()])
                self.assertFalse(result["sources"][0]["absence_reconciliation_applied"])
        conn = sqlite3.connect(self.production)
        try:
            self.assertEqual((1, 0), conn.execute("SELECT active,consecutive_missing_runs FROM job_sources").fetchone())
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
            self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
        finally:
            conn.close()
        with patch("services.faculty_jobs_sources.carnegie.source_coverage", return_value={"available": True, "schools": 1}):
            payload = build_faculty_job_sources(self.production)
        item = next(s for s in payload["sources"] if s["name"] == "carnegie_official")
        self.assertEqual("partial", item["completeness_state"])
        self.assertEqual(1, item["registry_coverage"]["schools"])
        self.assertEqual("opt_in", item["support_status"])


if __name__ == "__main__":
    unittest.main()
