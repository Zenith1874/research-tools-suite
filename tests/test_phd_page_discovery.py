# -*- coding: utf-8 -*-
"""Finding a programme's roster, job-market and placement pages.

The distinction this exists to protect: a programme page that links to no
job-market page and a programme page we could not read are different facts, and
neither of them says anything about how many candidates the programme has on
the market. The panel previously recorded all twenty programmes as "pending
confirmation", which is indistinguishable from nobody having looked.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import ensure_faculty_jobs_tables
from services.faculty_jobs_sources.base import (
    NonRetryableAdapterError, RobotsDisallowedError,
)
from services.phd_page_discovery import (
    KIND_JMC, KIND_PLACEMENT, KIND_ROSTER, STATUS_BLOCKED, STATUS_CONFIRMED,
    STATUS_NOT_FOUND, STATUS_UNREACHABLE, classify_link, discover, find_pages,
)

PAGE = """
<html><body>
  <a href="/phd/apply">Prospective Students</a>
  <a href="/phd/students">Current Doctoral Students</a>
  <a href="/phd/job-market">Job Market Candidates 2026</a>
  <a href="/phd/placement">Where Our Graduates Go</a>
  <a href="https://example.org/other">Job Market Candidates elsewhere</a>
  <a href="/phd/life">Student Life</a>
</body></html>
"""


class _Response:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class _Adapter:
    """Serves canned pages; records what was requested."""

    def __init__(self, pages=None, error=None):
        self.pages = pages or {}
        self.error = error
        self.requested = []

    def request(self, url):
        self.requested.append(url)
        if self.error:
            raise self.error
        if url not in self.pages:
            raise NonRetryableAdapterError(f"HTTP 404 from {url}")
        return _Response(self.pages[url])


class LinkTests(unittest.TestCase):
    def test_a_job_market_page_is_recognised_by_the_words_schools_use(self):
        self.assertEqual(KIND_JMC, classify_link("/x", "Job Market Candidates 2026"))
        self.assertEqual(KIND_JMC, classify_link("/x", "Students on the Market"))

    def test_a_placement_page_is_recognised(self):
        self.assertEqual(KIND_PLACEMENT, classify_link("/x", "Placement"))
        self.assertEqual(KIND_PLACEMENT, classify_link("/x", "Where Our Graduates Go"))

    def test_prospective_students_is_not_a_roster(self):
        # It is an admissions page. Counting it as a roster would attribute a
        # page about applicants to the people actually enrolled.
        self.assertIsNone(classify_link("/apply", "Prospective Students"))
        self.assertIsNone(classify_link("/life", "Student Life"))

    def test_a_url_containing_phd_is_not_by_itself_evidence(self):
        # Classification reads the link's words, not its path.
        self.assertIsNone(classify_link("/phd/curriculum", "Curriculum"))

    def test_an_undergraduate_page_is_not_a_doctoral_roster(self):
        # The real match: Kelley's PhD page carries a school-wide "Current
        # Students" link pointing at /undergraduate/advising/. The label is
        # right and the page is wrong, so the path vetoes it.
        self.assertIsNone(classify_link(
            "https://kelley.iu.edu/undergraduate/advising/index.html",
            "Current Students"))
        self.assertIsNone(classify_link("/mba/current-students", "Current Students"))
        self.assertEqual(KIND_ROSTER, classify_link(
            "https://kelley.iu.edu/phd/current-students", "Current Students"))

    def test_the_path_veto_does_not_apply_to_placement_or_job_market(self):
        # The veto exists for rosters, where the label is generic. A page
        # actually called "Placement" is that whatever the path says.
        self.assertEqual(KIND_PLACEMENT,
                         classify_link("/mba/placement", "Placement"))

    def test_the_more_specific_kind_wins(self):
        # A link offering both should be the job-market page, not the roster.
        self.assertEqual(KIND_JMC, classify_link("/x", "PhD Students on the Job Market"))


class FindPagesTests(unittest.TestCase):
    def test_all_three_kinds_are_found_and_made_absolute(self):
        found = find_pages(PAGE, "https://biz.example.edu/phd/")
        self.assertEqual("https://biz.example.edu/phd/students", found[KIND_ROSTER]["url"])
        self.assertEqual("https://biz.example.edu/phd/job-market", found[KIND_JMC]["url"])
        self.assertEqual("https://biz.example.edu/phd/placement",
                         found[KIND_PLACEMENT]["url"])

    def test_a_link_to_another_host_is_not_this_programmes_page(self):
        # A programme linking to a national listing is not the programme
        # publishing its own candidates.
        found = find_pages(PAGE, "https://biz.example.edu/phd/")
        self.assertNotIn("example.org", found[KIND_JMC]["url"])

    def test_a_subdomain_of_the_same_institution_is_kept(self):
        html = '<a href="https://phd.example.edu/market">Job Market Candidates</a>'
        found = find_pages(html, "https://example.edu/business/")
        self.assertIn(KIND_JMC, found)

    def test_a_page_with_no_such_links_yields_nothing_rather_than_a_guess(self):
        found = find_pages("<html><body><a href='/x'>Curriculum</a></body></html>",
                           "https://example.edu/")
        self.assertEqual({}, found)

    def test_malformed_html_yields_what_it_could_parse(self):
        html = '<a href="/m">Job Market Candidates</a><div><p>unclosed'
        self.assertIn(KIND_JMC, find_pages(html, "https://example.edu/"))


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("DELETE FROM phd_program_sources")
        self.conn.execute("""
            INSERT INTO phd_program_sources (id, institution_name, program, program_url,
                                             source_type, status)
            VALUES (1,'Example University','Example PhD',
                    'https://biz.example.edu/phd/','pilot','active')
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def row(self):
        return self.conn.execute(
            "SELECT * FROM phd_program_sources WHERE id=1").fetchone()

    def test_a_confirmed_programme_records_the_urls_it_found(self):
        adapter = _Adapter({"https://biz.example.edu/phd/": PAGE})
        result = discover(self.conn, sleep=0, adapter=adapter, archive=False)
        self.assertEqual({STATUS_CONFIRMED: 1}, result["by_status"])
        row = self.row()
        self.assertEqual("https://biz.example.edu/phd/job-market", row["jmc_url"])
        self.assertEqual("https://biz.example.edu/phd/placement", row["placement_url"])
        self.assertEqual(STATUS_CONFIRMED, row["status"])
        self.assertIsNotNone(row["last_checked"])

    def test_a_page_that_links_to_nothing_is_not_found_not_blocked(self):
        adapter = _Adapter({"https://biz.example.edu/phd/": "<html><body>hi</body></html>"})
        discover(self.conn, sleep=0, adapter=adapter, archive=False)
        row = self.row()
        self.assertEqual(STATUS_NOT_FOUND, row["status"])
        self.assertIn("describes the website", row["notes"],
                      "the note must refuse the reading that the programme has "
                      "no candidates")

    def test_a_404_is_unreachable_rather_than_not_found(self):
        # The audit found 5 of 12 programme pages 404ing. Recording those as
        # `not_found` would turn a broken link into a finding about the market.
        adapter = _Adapter({})
        discover(self.conn, sleep=0, adapter=adapter, archive=False)
        self.assertEqual(STATUS_UNREACHABLE, self.row()["status"])

    def test_a_robots_refusal_is_blocked_and_records_why(self):
        adapter = _Adapter(error=RobotsDisallowedError("robots.txt disallows this"))
        result = discover(self.conn, sleep=0, adapter=adapter, archive=False)
        self.assertEqual({STATUS_BLOCKED: 1}, result["by_status"])
        self.assertIn("robots.txt", self.row()["notes"])

    def test_an_unreadable_page_does_not_erase_a_url_found_earlier(self):
        # COALESCE, not assignment: one bad check should not delete a URL a
        # previous run confirmed.
        discover(self.conn, sleep=0, archive=False,
                 adapter=_Adapter({"https://biz.example.edu/phd/": PAGE}))
        discover(self.conn, sleep=0, archive=False, adapter=_Adapter({}))
        row = self.row()
        self.assertEqual(STATUS_UNREACHABLE, row["status"])
        self.assertEqual("https://biz.example.edu/phd/job-market", row["jmc_url"],
                         "a failed re-check must not discard a confirmed URL")

    def test_the_summary_refuses_the_no_candidates_reading(self):
        discover(self.conn, sleep=0, archive=False, adapter=_Adapter({}))
        result = discover(self.conn, sleep=0, archive=False, adapter=_Adapter({}))
        self.assertIn("is evidence about how many candidates", result["note"])


if __name__ == "__main__":
    unittest.main()
