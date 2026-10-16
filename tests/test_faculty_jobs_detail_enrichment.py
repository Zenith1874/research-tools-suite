# -*- coding: utf-8 -*-
"""A detail pass must be resumable, and must not invent evidence.

Two failures this guards against. First, an unread page silently reading as
"this posting has no deadline" -- the field is blank either way, so only a
record of what was attempted keeps them apart. Second, a board that stops
serving partway through discarding the pages already read: at 2,824 postings
that would waste thousands of good requests every time.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.faculty_jobs_detail_enrichment import (
    detail_progress, enrich_source_details, pending_count,
)
from services.faculty_jobs_service import ensure_faculty_jobs_tables
from services.faculty_jobs_sources.base import CrawlBudgetExhaustedError

NOW = "2026-08-29T00:00:00Z"

DETAIL = """
<html><body>
  <h1>Assistant Professor of Finance</h1>
  <script type="application/ld+json">
  {{"@type":"JobPosting","title":"Assistant Professor of Finance",
    "validThrough":"2026-11-30",
    "hiringOrganization":{{"name":"Example University"}},
    "baseSalary":{{"@type":"MonetaryAmount","currency":"USD",
      "value":{{"@type":"QuantitativeValue","minValue":{salary},"unitText":"YEAR"}}}}}}
  </script>
  <p>Application Deadline: {deadline}</p>
  <p>Department: {department}</p>
  <a href="https://apply.example.edu/{job_id}">Apply for this position</a>
</body></html>
"""

CHALLENGE = ("<html><head><meta name='robots' content='noindex'></head>"
             "<body><h1>Pardon Our Interruption</h1></body></html>")


class _DetailFixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.source_id = self.conn.execute(
            "SELECT id FROM sources WHERE name='higheredjobs'").fetchone()["id"]
        for index in range(1, 6):
            self.add_job(index)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add_job(self, job_id):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,'open','business_school','accepted',1,?,?,?,?)
        """, (job_id, f"key-{job_id}", "Assistant Professor of Finance",
              "assistant professor of finance", NOW, NOW, NOW, NOW))
        self.conn.execute("""
            INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,
                                     first_seen,last_seen)
            VALUES (?,?,?,?,1,?,?)
        """, (job_id, self.source_id, str(job_id),
              f"https://www.higheredjobs.com/faculty/details.cfm?JobCode={job_id}", NOW, NOW))

    def adapter_returning(self, responder):
        from services.faculty_jobs_sources.higheredjobs import HigherEdJobsAdapter
        adapter = HigherEdJobsAdapter(max_pages=1)
        patcher = patch.object(adapter, "request", side_effect=responder)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patch("services.faculty_jobs_detail_enrichment._adapter", return_value=adapter)

    def page(self, job_id, deadline="November 30, 2026", department="Finance", salary="95000"):
        return SimpleNamespace(
            text=DETAIL.format(job_id=job_id, deadline=deadline,
                               department=department, salary=salary),
            status_code=200, url=f"https://e.test/{job_id}")


class DetailEnrichmentTests(_DetailFixture):
    def test_a_read_page_fills_only_blank_fields(self):
        self.conn.execute(
            "UPDATE jobs SET official_url='https://kept.example/original' WHERE id=1")
        self.conn.commit()
        calls = []

        def responder(url):
            calls.append(url)
            return self.page(len(calls))

        with self.adapter_returning(responder):
            stats = enrich_source_details(self.conn, "higheredjobs", limit=2, sleep=None)
        self.assertEqual(2, stats["read"])
        rows = {row["id"]: row for row in self.conn.execute(
            "SELECT id,deadline_date,official_url FROM jobs WHERE id IN (1,2)")}
        self.assertEqual("2026-11-30", rows[1]["deadline_date"],
                         "a blank field is filled from the page")
        self.assertEqual("https://kept.example/original", rows[1]["official_url"],
                         "a value the job already had must not be overwritten")
        self.assertEqual("https://apply.example.edu/2", rows[2]["official_url"])

    def test_the_pass_does_not_claim_a_field_the_parser_never_supplies(self):
        # The shared detail parser reads a fixed set of labels and does not
        # return a department. Listing it as enrichable would make every run
        # report that pages simply never carry one.
        from services.faculty_jobs_detail_enrichment import ENRICHABLE
        self.assertNotIn("department", ENRICHABLE)

    def test_an_unread_page_is_not_evidence_of_no_deadline(self):
        # The whole point of the attempt record: a blank deadline means one of
        # two very different things, and only this table tells them apart.
        progress = detail_progress(self.conn, "higheredjobs")
        self.assertEqual(5, progress["pending"])
        self.assertEqual({}, progress["by_status"])

    def test_a_challenge_stops_the_run_and_keeps_what_was_read(self):
        calls = []

        def responder(url):
            calls.append(url)
            if len(calls) <= 2:
                return self.page(len(calls))
            return SimpleNamespace(text=CHALLENGE, status_code=200, url=url)

        with self.adapter_returning(responder):
            stats = enrich_source_details(self.conn, "higheredjobs", limit=5, sleep=None)
        self.assertEqual(2, stats["read"], "the two good pages are kept")
        self.assertEqual(3, len(calls), "it stops at the challenge instead of spending the queue")
        self.assertIn("challenged", stats["stopped_reason"])
        statuses = detail_progress(self.conn, "higheredjobs")["by_status"]
        self.assertEqual(2, statuses.get("ok"))
        self.assertEqual(1, statuses.get("challenged"))

    def test_a_rerun_continues_from_where_it_stopped(self):
        calls = []

        def first(url):
            calls.append(url)
            if len(calls) <= 2:
                return self.page(len(calls))
            return SimpleNamespace(text=CHALLENGE, status_code=200, url=url)

        with self.adapter_returning(first):
            enrich_source_details(self.conn, "higheredjobs", limit=5, sleep=None)
        # Two were read; the third was challenged and now waits out its backoff,
        # so only the two never-attempted postings are immediately pending.
        self.assertEqual(2, pending_count(self.conn, "higheredjobs"))

        second_calls = []

        def second(url):
            second_calls.append(url)
            return self.page(len(second_calls) + 2)

        with self.adapter_returning(second):
            stats = enrich_source_details(self.conn, "higheredjobs", limit=5, sleep=None)
        self.assertEqual(2, stats["read"], "only the unread postings are re-requested")
        self.assertEqual(0, stats["pending_after"],
                         "the challenged one is owed but not due yet")

    def test_a_challenged_posting_is_retried_on_the_next_run(self):
        # Only "ok" clears a posting. A challenge must leave it owed.
        calls = []

        def responder(url):
            calls.append(url)
            return SimpleNamespace(text=CHALLENGE, status_code=200, url=url)

        with self.adapter_returning(responder):
            enrich_source_details(self.conn, "higheredjobs", limit=5, sleep=None)
        # The challenged posting is still owed a reading, but it waits: asking
        # again immediately is what the backoff exists to prevent.
        self.assertEqual(4, pending_count(self.conn, "higheredjobs"))
        due = self.conn.execute(
            "SELECT next_retry_at FROM job_detail_fetches").fetchone()["next_retry_at"]
        self.assertIsNotNone(due)
        self.assertEqual(5, pending_count(self.conn, "higheredjobs", now="2099-01-01T00:00:00Z"),
                         "once the backoff has passed it is due again")

    def test_a_policy_refusal_stops_rather_than_burning_the_queue(self):
        calls = []

        def responder(url):
            calls.append(url)
            raise CrawlBudgetExhaustedError("origin used its 1-request budget")

        with self.adapter_returning(responder):
            stats = enrich_source_details(self.conn, "higheredjobs", limit=5, sleep=None)
        self.assertEqual(1, len(calls))
        self.assertIn("refused", stats["stopped_reason"])
        self.assertEqual(4, pending_count(self.conn, "higheredjobs"))
        self.assertEqual(5, pending_count(self.conn, "higheredjobs", now="2099-01-01T00:00:00Z"),
                         "a refusal defers the posting, it does not resolve it")

    def test_a_page_that_carries_nothing_is_recorded_as_read(self):
        # "We opened it and it said nothing" is a real answer and must not be
        # retried forever, but it is still not a filled field.
        def responder(url):
            return SimpleNamespace(text="<html><body><h1>Job</h1></body></html>",
                                   status_code=200, url=url)

        with self.adapter_returning(responder):
            stats = enrich_source_details(self.conn, "higheredjobs", limit=1, sleep=None)
        self.assertEqual(1, stats["read"])
        self.assertEqual(1, stats["empty"])
        self.assertEqual(0, stats["updated"])

    def test_every_fill_is_audited_with_the_page_it_came_from(self):
        with self.adapter_returning(lambda url: self.page(1)):
            enrich_source_details(self.conn, "higheredjobs", limit=1, sleep=None)
        row = self.conn.execute(
            "SELECT reason,new_value FROM faculty_job_repair_audit "
            "WHERE action='detail_page_enrichment'").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("details.cfm", row["reason"])
        self.assertIn("deadline_date", row["new_value"])


class TerminalEmptyTests(_DetailFixture):
    """A page we read that carried nothing is answered, not still owed."""

    def blank_page(self, url):
        return SimpleNamespace(text="<html><body><h1>Job</h1></body></html>",
                               status_code=200, url=url)

    def test_an_empty_read_reduces_pending_and_is_not_re_requested(self):
        before = pending_count(self.conn, "higheredjobs")
        calls = []

        def responder(url):
            calls.append(url)
            return self.blank_page(url)

        with self.adapter_returning(responder):
            enrich_source_details(self.conn, "higheredjobs", limit=1, sleep=None)
        self.assertEqual(1, len(calls))
        self.assertEqual(before - 1, pending_count(self.conn, "higheredjobs"),
                         "an answered page must leave the queue")

        second = []

        def again(url):
            second.append(url)
            return self.blank_page(url)

        with self.adapter_returning(again):
            enrich_source_details(self.conn, "higheredjobs", limit=1, sleep=None)
        self.assertNotIn(calls[0], second,
                         "the same empty page must not be requested again")

    def test_a_page_holding_values_we_already_have_is_not_filed_as_empty(self):
        # Every slot the page could fill is already filled, including
        # deadline_mode: leaving that as 'unknown' would legitimately be a
        # blank the page gets to fill, and the assertion below would then be
        # testing the wrong thing.
        self.conn.execute(
            "UPDATE jobs SET deadline_date=?, deadline_mode=?, deadline_evidence=?, "
            "deadline_parse_reason=?, official_url=?, salary_raw=? WHERE id=1",
            ("2026-11-30", "fixed", "listing_card", "already parsed",
             "https://kept.example/a", "$95,000"))
        self.conn.commit()
        with self.adapter_returning(lambda url: self.page(1)):
            enrich_source_details(self.conn, "higheredjobs", limit=1, sleep=None)
        row = self.conn.execute(
            """SELECT status, fields_observed, fields_found, reason FROM job_detail_fetches
               WHERE source_job_id=1""").fetchone()
        self.assertIn("deadline_date", row["fields_observed"],
                      "the page did carry a deadline")
        self.assertEqual("[]", row["fields_found"], "but nothing needed writing")
        self.assertIn("already held", row["reason"] or "")

    def test_an_unfinished_attempt_backs_off_instead_of_retrying_tightly(self):
        with self.adapter_returning(lambda url: SimpleNamespace(
                text=CHALLENGE, status_code=200, url=url)):
            enrich_source_details(self.conn, "higheredjobs", limit=1, sleep=None)
        row = self.conn.execute(
            "SELECT attempt_count, next_retry_at FROM job_detail_fetches").fetchone()
        self.assertEqual(1, row["attempt_count"])
        self.assertIsNotNone(row["next_retry_at"],
                             "a challenged posting must wait before being asked again")

    def test_a_source_without_per_posting_pages_is_refused(self):
        from services.faculty_jobs_detail_enrichment import enrich_source_details as run
        stats = run(self.conn, "econjobmarket", limit=5, sleep=None)
        self.assertEqual(0, stats["read"])
        self.assertIn("same listing anchor", stats["stopped_reason"])


class DeadlineModeBlankTests(unittest.TestCase):
    def test_the_literal_unknown_counts_as_an_empty_slot(self):
        from services.faculty_jobs_detail_enrichment import _is_blank
        for value in (None, "", "unknown", "Unknown", "  "):
            self.assertTrue(_is_blank(value), repr(value))
        for value in ("rolling", "2026-11-30", "fixed"):
            self.assertFalse(_is_blank(value), repr(value))


if __name__ == "__main__":
    unittest.main()
