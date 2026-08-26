# -*- coding: utf-8 -*-
"""robots.txt is a policy gate, not a transport detail.

The adapter layer reaches arbitrary institution websites during the AACSB
official-site scan, so a refusal has to be observable and must never be
recorded as evidence that a school has no vacancy.
"""

from types import SimpleNamespace
import unittest

import requests

from services.faculty_jobs_sources import base
from services.faculty_jobs_sources.aacsb import AACSBDirectoryClient, AACSBDirectoryRecord
from services.faculty_jobs_sources.base import (
    AdapterError,
    RobotsDisallowedError,
    SourceAdapter,
    reset_robots_cache,
)


class FakeSession:
    """Answer robots.txt from a script and count every call."""

    def __init__(self, robots=None, status=200, raise_on_robots=None):
        self.headers = {}
        self.robots = robots
        self.status = status
        self.raise_on_robots = raise_on_robots
        self.robots_calls = []
        self.page_calls = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.robots_calls.append(url)
        if self.raise_on_robots:
            raise self.raise_on_robots
        return SimpleNamespace(status_code=self.status, text=self.robots or "")

    def request(self, method, url, params=None, data=None, timeout=None, allow_redirects=True):
        self.page_calls.append(url)
        return SimpleNamespace(status_code=200, text="<html></html>", url=url,
                               headers={}, encoding="utf-8")


def adapter_with(session):
    adapter = SourceAdapter(timeout=10)
    adapter.session = session
    adapter._crawl_delay_noted = {}
    return adapter


class RobotsGateTests(unittest.TestCase):
    def setUp(self):
        reset_robots_cache()

    def tearDown(self):
        reset_robots_cache()

    def test_disallowed_path_is_refused_before_any_page_request(self):
        session = FakeSession("User-agent: *\nDisallow: /jobs/\n")
        adapter = adapter_with(session)
        with self.assertRaises(RobotsDisallowedError):
            adapter.request("https://example.edu/jobs/1")
        self.assertEqual([], session.page_calls,
                         "a refused URL must never reach the network")

    def test_allowed_path_still_fetches(self):
        session = FakeSession("User-agent: *\nDisallow: /private/\n")
        adapter = adapter_with(session)
        response = adapter.request("https://example.edu/careers/faculty")
        self.assertEqual(200, response.status_code)
        self.assertEqual(["https://example.edu/careers/faculty"], session.page_calls)

    def test_missing_robots_file_allows_crawling(self):
        session = FakeSession(status=404)
        adapter = adapter_with(session)
        adapter.request("https://example.edu/careers")
        self.assertEqual(1, len(session.page_calls))

    def test_server_error_on_robots_is_treated_as_disallow(self):
        # RFC 9309: an unreachable robots.txt is not permission to crawl.
        session = FakeSession(status=503)
        adapter = adapter_with(session)
        with self.assertRaises(RobotsDisallowedError):
            adapter.request("https://example.edu/careers")
        self.assertEqual([], session.page_calls)

    def test_transport_failure_on_robots_is_treated_as_disallow(self):
        session = FakeSession(raise_on_robots=requests.ConnectionError("no route"))
        adapter = adapter_with(session)
        with self.assertRaises(RobotsDisallowedError):
            adapter.request("https://example.edu/careers")
        self.assertEqual([], session.page_calls)

    def test_robots_is_fetched_once_per_origin(self):
        session = FakeSession("User-agent: *\nDisallow: /private/\n")
        adapter = adapter_with(session)
        for path in ("/a", "/b", "/c"):
            adapter.request("https://example.edu" + path)
        self.assertEqual(1, len(session.robots_calls))
        self.assertEqual(3, len(session.page_calls))

    def test_query_string_is_included_in_the_rule_check(self):
        session = FakeSession("User-agent: *\nDisallow: /search?\n")
        adapter = adapter_with(session)
        with self.assertRaises(RobotsDisallowedError):
            adapter.request("https://example.edu/search", params={"q": "professor"})

    def test_refusal_is_not_a_generic_adapter_error_only(self):
        # It must stay catchable as AdapterError for existing handlers, while
        # remaining distinguishable for the honest-outcome path.
        self.assertTrue(issubclass(RobotsDisallowedError, AdapterError))

    def test_crawl_delay_above_the_ceiling_is_capped_and_logged(self):
        session = FakeSession("User-agent: *\nCrawl-delay: 3600\nDisallow:\n")
        adapter = adapter_with(session)
        with self.assertLogs(base.LOG, level="WARNING") as logs:
            adapter.request("https://example.edu/jobs")
        self.assertTrue(any("Crawl-delay" in line for line in logs.output))
        self.assertEqual(1, len(session.page_calls))

    def test_first_request_to_an_idle_origin_does_not_wait(self):
        self.assertEqual(0.0, base.space_requests("https://example.edu", 30.0))


class AACSBRobotsOutcomeTests(unittest.TestCase):
    def setUp(self):
        reset_robots_cache()

    def tearDown(self):
        reset_robots_cache()

    def record(self):
        return AACSBDirectoryRecord(
            directory_result_id="r1", directory_url="https://www.aacsb.edu/accredited/x",
            institution_name="Example University",
            school_name="Example College of Business",
            location_raw="Austin, Texas",
            directory_title="Example College of Business",
            roster_source_url="https://www.aacsb.edu/accredited",
            captured_at="2026-08-25T12:00:00Z",
            official_website="https://example.edu/",
        )

    def test_refused_school_site_is_not_recorded_as_having_no_jobs(self):
        client = AACSBDirectoryClient(timeout=10, delay=0.1)
        client.session = FakeSession("User-agent: *\nDisallow: /\n")
        scan = client.scan_official_site(self.record())
        self.assertEqual("robots_disallowed", scan.website_status)
        self.assertEqual("unknown", scan.job_scan_status)
        self.assertNotEqual("no_current_jobs", scan.job_scan_status)
        self.assertIn("robots.txt", (scan.reason or ""))


if __name__ == "__main__":
    unittest.main()
