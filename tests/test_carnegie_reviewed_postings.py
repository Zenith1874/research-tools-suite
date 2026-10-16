"""Official-seed identity, campus, closing-date and evidence archive checks."""
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services import raw_archive
from services.faculty_jobs_normalizer import classify_business_scope, parse_deadline, parse_start
from services.faculty_jobs_sources.carnegie_reviewed import (
    CarnegieReviewedPageUpAdapter, parse_reviewed_posting,
)
from scripts.repair_carnegie_nonbusiness_scope import inspect_job


URL = "https://csucareers.calstate.edu/en-us/job/562131/assistant-professor-is"
TITLE = "Assistant Professor of Information Systems"
SEED = {"unitid": 1, "url": URL, "expected_title": TITLE, "school": "College of Business"}
TARGETS = {1: {"unitid": 1, "institution_name": "Example University", "city": "Test", "state": "CA"}}


def page(title=TITLE, employer="Example University", number="562131", closing="", extra=""):
    return f'''<html><body><h2>Job Search</h2><form>Subscribe Recaptcha</form>
        <div id="job"><div id="job-content"><h2>{title}</h2>
        <span class="job-externalJobNo">{number}</span>
        <div id="job-details">{employer} invites applications in the College of Business.
        {("Teach Information Systems and conduct scholarly research. " * 15)} {extra}</div>
        <p>Applications close: {closing}</p><a>Back to search results</a></div></div></body></html>'''


class ReviewedPostingTests(unittest.TestCase):
    def parse(self, html=None, **kwargs):
        return parse_reviewed_posting(html or page(), URL, SEED, TARGETS,
                                      captured_at="2026-09-20T15:00:00Z", **kwargs)

    def test_individual_identity_uses_posting_body_not_generic_page_heading_or_form(self):
        job = self.parse()
        self.assertEqual(TITLE, job.title_raw)
        self.assertEqual("College of Business", job.school_raw)
        self.assertEqual(1, job.extra["unitid"])
        self.assertNotIn("Subscribe Recaptcha", job.description_excerpt)

    def test_one_advertisement_can_explicitly_offer_two_positions(self):
        title = TITLE + " (2 Open Positions)"
        job = parse_reviewed_posting(page(title=title), URL, {**SEED, "expected_title": title}, TARGETS)
        self.assertEqual("individual_advertisement", job.extra["posting_scope"])

    def test_wrong_campus_job_number_and_title_are_held(self):
        for html in (page(employer="Other University"), page(number="999"),
                     page(title="Assistant Professor of Marketing")):
            with self.subTest(html=html[:100]), self.assertRaises(ValueError):
                self.parse(html)

    def test_closed_footer_overrules_open_until_filled_body(self):
        with self.assertRaisesRegex(ValueError, "closing date has passed"):
            self.parse(page(closing="September 13, 2026", extra="Open until filled."))

    def test_preference_date_is_not_a_hard_close(self):
        job = self.parse(page(extra="Review begins August 17, 2026. Open until filled."))
        self.assertIsNone(job.deadline_raw)

    def test_review_begin_date_under_deadline_heading_stays_open_until_filled(self):
        result = parse_deadline(None, "APPLICATION DEADLINE: Review of applications to begin "
                                "August 17, 2026. Position opened until filled (or recruitment canceled).")
        self.assertEqual({"date": None, "mode": "open_until_filled"}, result)
        actual_deadline = parse_deadline(None, "Application Deadline: October 1, 2026 "
                                        "(Applications accepted until filled or closed).")
        self.assertEqual("2026-10-01", actual_deadline["date"])
        preferred = parse_deadline(None, "Application Deadline: Preferred application deadline is "
                                   "October 30, 2026, and applications received after this date may be "
                                   "considered on an as-needed basis. However, the position will remain open until filled.")
        self.assertEqual("open_until_filled", preferred["mode"])
        fixed = parse_deadline(None, "Application Deadline: October 1, 2026. Review begins August 1, "
                               "2026. Other vacancies are open until filled.")
        self.assertEqual("2026-10-01", fixed["date"])

    def test_explicit_start_beats_unrelated_old_narrative_year(self):
        cases = [
            "Fall 2025 campus news. Target Start Date: August 17, 2027",
            "Effective Date of Appointment: August 19, 2027. Fall 2025 ranking.",
            "Effective Date: August 17, 2027 (Fall Semester)",
            "Fall 2024 ranking. This position is to begin during the Fall Semester of 2027.",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(2027, parse_start(text)[1])

    def test_music_technology_is_not_business_due_to_entrepreneurship_word(self):
        result = classify_business_scope(title=
            "Adjunct Professor - Music, Technology, Entrepreneurship, and Production Program")
        self.assertEqual("non_business", result["scope"])

    def test_missing_posting_container_and_pool_are_held(self):
        with self.assertRaises(ValueError):
            self.parse("<h1>Verify you are human</h1>")
        with self.assertRaisesRegex(ValueError, "Pool"):
            self.parse(page(extra="Applications enter an adjunct pool for future vacancies."))

    def test_archive_preserves_raw_bytes_and_reviewed_manifest_for_accepted_and_held_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, registry, audit = root / "seeds.json", root / "registry.db", root / "audit.db"
            manifest.write_text(json.dumps({"postings": [SEED]}), encoding="utf-8")
            conn = sqlite3.connect(registry)
            conn.execute("CREATE TABLE institution_recruitment_targets (unitid INTEGER, institution_name TEXT, city TEXT, state TEXT)")
            conn.execute("INSERT INTO institution_recruitment_targets VALUES (1,'Example University','Test','CA')")
            conn.commit()
            conn.close()
            adapter = CarnegieReviewedPageUpAdapter(manifest, registry_db=registry, audit_db=audit)
            payload = page().encode()
            with patch.object(adapter, "request", return_value=SimpleNamespace(
                    content=payload, url=URL, status_code=200)):
                result = adapter.fetch()
            self.assertEqual(1, len(result.jobs))
            self.assertFalse(result.coverage_complete)
            self.assertEqual(0, result.listing_pages)
            with patch.object(adapter, "request", return_value=SimpleNamespace(
                    content=page(employer="Other University").encode(), url=URL, status_code=200)):
                self.assertEqual([], adapter.fetch().jobs)
            with patch.object(adapter, "request", return_value=SimpleNamespace(
                    content=payload, url=URL, status_code=202)):
                self.assertEqual([], adapter.fetch().jobs)
            conn = sqlite3.connect(audit)
            rows = conn.execute("SELECT content_hash,note FROM raw_observations ORDER BY id").fetchall()
            self.assertEqual(3, len(rows))
            self.assertEqual(payload, raw_archive.load_blob(conn, rows[0][0], root=root / "carnegie_reviewed_raw"))
            self.assertEqual("accepted", json.loads(rows[0][1])["decision"])
            self.assertTrue(json.loads(rows[1][1])["decision"].startswith("held:"))
            self.assertIn("HTTP 202", json.loads(rows[2][1])["decision"])
            conn.close()

    def test_one_job_scope_repair_requires_exact_url_and_carnegie_link(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.db"
            conn = sqlite3.connect(path)
            conn.executescript('''
                CREATE TABLE jobs (id INTEGER, official_url TEXT, title_raw TEXT, department TEXT);
                CREATE TABLE sources (id INTEGER, name TEXT);
                CREATE TABLE job_sources (job_id INTEGER, source_id INTEGER);
                INSERT INTO sources VALUES (1,'carnegie_official');
                INSERT INTO job_sources VALUES (1,1);
                INSERT INTO jobs VALUES (1,'https://example.edu/job/1','Adjunct Professor of Music Technology',NULL);
            ''')
            conn.close()
            row, result = inspect_job(path, 1, "https://example.edu/job/1")
            self.assertEqual("non_business", result["scope"])
            with self.assertRaises(ValueError):
                inspect_job(path, 1, "https://wrong.example/job/1")
            with self.assertRaises(ValueError):
                inspect_job(path, 2, "https://example.edu/job/1")


if __name__ == "__main__":
    unittest.main()
