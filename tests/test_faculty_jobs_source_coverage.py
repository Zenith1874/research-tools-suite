# -*- coding: utf-8 -*-
"""A source's own result count, recorded next to what we actually read.

AIS prints "1 - 25 Results of 53" and paginates by calling an internal search
endpoint rather than by linking to page two, so a plain fetch reaches 25 of 53.
Without recording the board's own total, a first-page-only read is
indistinguishable from having harvested the source, and every count derived
from it silently overstates the market.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.faculty_jobs_service import build_faculty_job_sources, ensure_faculty_jobs_tables
from services.faculty_jobs_sources.ais import AISAdapter, _reported_total
from bs4 import BeautifulSoup

NOW = "2026-08-27T00:00:00Z"

PAGE = """
<html><body>
  <div class="results-count">1 - 25 Results of 53</div>
  <div class="job-tile">
    <a href="/job/professor-at-novasbe/85721994/">Professor (open rank) at NovaSBE</a>
    <div class="job-company-row">Unknown institution</div>
  </div>
  <div class="job-tile">
    <a href="/job/assistant-professor/85721995/">Assistant Professor of Marketing</a>
    <div class="job-company-row">Example University</div>
  </div>
  <ul class="pagination">
    <li><a class="page-link-nav" onclick="searchJobs(2,true);">Next</a></li>
  </ul>
</body></html>
"""


class ReportedTotalTests(unittest.TestCase):
    def test_the_boards_own_count_is_read(self):
        self.assertEqual(53, _reported_total(BeautifulSoup(PAGE, "html.parser")))

    def test_thousands_separators_are_handled(self):
        soup = BeautifulSoup("<div>1 - 10 Results of 1,234</div>", "html.parser")
        self.assertEqual(1234, _reported_total(soup))

    def test_a_board_without_a_count_reports_none(self):
        self.assertIsNone(_reported_total(BeautifulSoup("<div>Jobs</div>", "html.parser")))


class AdapterCoverageTests(unittest.TestCase):
    def fetch(self, max_pages=3):
        adapter = AISAdapter(max_pages=max_pages, max_items=100)
        with patch.object(adapter, "request") as request:
            request.return_value.text = PAGE
            response = adapter.fetch()
        return response, request

    def test_the_shortfall_is_reported_not_hidden(self):
        response, _request = self.fetch()
        self.assertEqual(53, response.reported_total)
        self.assertFalse(response.coverage_complete)
        self.assertEqual(2, len(response.jobs))
        self.assertTrue(any("of 53" in note for note in response.notes), response.notes)

    def test_further_pages_are_not_refetched(self):
        # The ?page=n URL returns page one again, so looping would spend
        # requests to rediscover the same 25 ids.
        _response, request = self.fetch(max_pages=3)
        self.assertEqual(1, request.call_count)

    def test_full_coverage_is_reported_when_the_page_holds_everything(self):
        page = PAGE.replace("Results of 53", "Results of 2")
        adapter = AISAdapter(max_pages=1, max_items=100)
        with patch.object(adapter, "request") as request:
            request.return_value.text = page
            response = adapter.fetch()
        self.assertEqual(2, response.reported_total)
        self.assertTrue(response.coverage_complete)
        self.assertEqual([], response.notes)


class SourcePayloadTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def record_run(self, reported_total, items_seen, complete):
        source_id = self.conn.execute(
            "SELECT id FROM sources WHERE name='ais'").fetchone()["id"]
        self.conn.execute("""
            INSERT INTO ingestion_runs
              (source_id,started_at,finished_at,status,pages_fetched,items_seen,
               reported_total,coverage_complete)
            VALUES (?,?,?,'success',1,?,?,?)
        """, (source_id, NOW, NOW, items_seen, reported_total, complete))
        self.conn.commit()

    def ais_payload(self):
        payload = build_faculty_job_sources(self.db)
        return next(item for item in payload["sources"] if item["name"] == "ais")

    def test_a_partial_read_is_labelled_as_a_floor(self):
        self.record_run(53, 25, 0)
        item = self.ais_payload()
        self.assertEqual(53, item["source_reported_total"])
        self.assertEqual(25, item["last_run_items_seen"])
        self.assertFalse(item["source_coverage_complete"])
        self.assertEqual(47.2, item["source_coverage_percent"])
        self.assertIn("floor", item["source_coverage_note"])

    def test_a_complete_read_says_so(self):
        self.record_run(25, 25, 1)
        item = self.ais_payload()
        self.assertTrue(item["source_coverage_complete"])
        self.assertEqual(100.0, item["source_coverage_percent"])
        self.assertIn("all 25", item["source_coverage_note"])

    def test_a_measured_shortfall_is_partial_and_not_unverifiable(self):
        # "We read 25 of the 53 it advertises" and "this board never told us
        # how many there are" are different states of knowledge, and only one
        # of them is unverifiable.
        self.record_run(53, 25, 0)
        self.assertEqual("partial", self.ais_payload()["completeness_state"])

    def test_a_board_that_publishes_no_total_stays_unverifiable(self):
        self.assertEqual("unverifiable", self.ais_payload()["completeness_state"])

    def test_a_full_read_is_complete(self):
        self.record_run(25, 25, 1)
        self.assertEqual("complete", self.ais_payload()["completeness_state"])

    def test_a_board_without_a_total_is_not_assumed_complete(self):
        item = self.ais_payload()
        self.assertIsNone(item["source_reported_total"])
        self.assertIsNone(item["source_coverage_complete"],
                          "no total is not the same claim as full coverage")
        self.assertIn("No successful run has recorded", item["source_coverage_note"])
        self.assertIn("cannot be verified", item["source_coverage_note"])


class SourceLifecycleCompletenessTests(unittest.TestCase):
    """Only complete source snapshots may treat unseen IDs as missing."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)

    def tearDown(self):
        self.dir.cleanup()

    @staticmethod
    def source_job():
        from services.faculty_jobs_sources.base import SourceJob
        return SourceJob(
            source="ais",
            source_job_id="lifecycle-1",
            source_url="https://example.test/jobs/lifecycle-1",
            title_raw="Assistant Professor of Information Systems",
            institution_raw="Example University",
            captured_at=NOW,
        )

    def update(self, jobs, coverage_complete):
        from services.faculty_jobs_service import update_faculty_jobs
        from services.faculty_jobs_sources.base import AdapterResponse, SourceAdapter

        response = AdapterResponse(
            jobs,
            pages_fetched=1,
            listing_pages=1,
            reported_total=1,
            coverage_complete=coverage_complete,
        )

        class OfflineStub(SourceAdapter):
            name = adapter_name = "ais"
            base_url = "https://example.test/jobs"

            def fetch(self):
                return response

        return update_faculty_jobs(
            self.db, source_names=["ais"], adapters=[OfflineStub()])

    def link_and_job(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            link = conn.execute("""
                SELECT js.* FROM job_sources js
                JOIN sources s ON s.id=js.source_id
                WHERE s.name='ais' AND js.source_job_id='lifecycle-1'
            """).fetchone()
            job = conn.execute("SELECT * FROM jobs WHERE id=?", (link["job_id"],)).fetchone()
            return dict(link), dict(job)
        finally:
            conn.close()

    def set_missing_state(self, active, missing, status):
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("""
                UPDATE job_sources SET active=?,consecutive_missing_runs=?
                WHERE source_job_id='lifecycle-1'
            """, (active, missing))
            conn.execute("UPDATE jobs SET status=?", (status,))
            conn.commit()
        finally:
            conn.close()

    def test_partial_and_unknown_snapshots_do_not_advance_missing_lifecycle(self):
        self.update([self.source_job()], True)
        for complete in (False, None):
            with self.subTest(coverage_complete=complete):
                self.set_missing_state(active=1, missing=2, status="likely_open")
                result = self.update([], complete)
                link, job = self.link_and_job()
                self.assertEqual(1, link["active"])
                self.assertEqual(2, link["consecutive_missing_runs"])
                self.assertEqual("likely_open", job["status"])
                self.assertFalse(result["sources"][0]["absence_reconciliation_applied"])

    def test_complete_snapshot_advances_missing_lifecycle(self):
        self.update([self.source_job()], True)
        self.set_missing_state(active=1, missing=2, status="likely_open")
        result = self.update([], True)
        link, job = self.link_and_job()
        self.assertEqual(0, link["active"])
        self.assertEqual(3, link["consecutive_missing_runs"])
        self.assertEqual("closed", job["status"])
        self.assertTrue(result["sources"][0]["absence_reconciliation_applied"])

    def test_partial_snapshot_still_reactivates_an_observed_id(self):
        self.update([self.source_job()], True)
        self.set_missing_state(active=0, missing=3, status="closed")
        result = self.update([self.source_job()], False)
        link, job = self.link_and_job()
        self.assertEqual(1, link["active"])
        self.assertEqual(0, link["consecutive_missing_runs"])
        self.assertEqual("likely_open", job["status"])
        self.assertFalse(result["sources"][0]["absence_reconciliation_applied"])


class InsideHigherEdEntityPersistenceTests(unittest.TestCase):
    """Captured card boundaries must remain clean through isolated ingestion."""

    def test_pilot_cards_do_not_create_location_or_chrome_entities(self):
        from services.faculty_jobs_service import update_faculty_jobs
        from services.faculty_jobs_sources.base import AdapterResponse, SourceAdapter
        from services.faculty_jobs_sources.insidehighered import parse_fixture

        fixture = (
            Path(__file__).resolve().parent / "fixtures" / "faculty_jobs" /
            "inside_higher_ed_pilot_entity_regressions.html"
        )
        jobs = parse_fixture(fixture.read_text(encoding="utf-8"), detail_budget=0)

        class OfflineIHE(SourceAdapter):
            name = adapter_name = "inside_higher_ed"
            base_url = "https://careers.insidehighered.com/jobs/"

            def fetch(self):
                return AdapterResponse(
                    jobs,
                    pages_fetched=1,
                    listing_pages=1,
                    reported_total=851,
                    coverage_complete=False,
                )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            db = str(Path(temp) / "faculty.db")
            ensure_faculty_jobs_tables(db)
            update_faculty_jobs(
                db,
                source_names=["inside_higher_ed"],
                adapters=[OfflineIHE()],
            )
            conn = sqlite3.connect(db)
            try:
                linked_names = {
                    row[0] for row in conn.execute("""
                        SELECT DISTINCT i.official_name
                        FROM institutions i
                        JOIN jobs j ON j.institution_id=i.id
                        JOIN job_sources js ON js.job_id=j.id
                        JOIN sources s ON s.id=js.source_id
                        WHERE s.name='inside_higher_ed'
                    """)
                }
                self.assertEqual({
                    "NC State University",
                    "Atlanta Metropolitan State College",
                    "Lebanese American University",
                    "Fayetteville State University",
                    "Quinnipiac University",
                    "Miami University",
                    "Dartmouth College",
                }, linked_names)
                self.assertFalse(linked_names & {
                    "NC State University Posting",
                    "Lebanese American University The",
                    "NC Fayetteville State University",
                    "CT Quinnipiac University",
                    "Ohio Salary Miami University",
                    "NH Dartmouth College",
                })
                self.assertIsNone(conn.execute("""
                    SELECT j.city FROM jobs j
                    JOIN job_sources js ON js.job_id=j.id
                    JOIN sources s ON s.id=js.source_id
                    WHERE s.name='inside_higher_ed' AND js.source_job_id='3467729'
                """).fetchone()[0])
            finally:
                conn.close()

    def test_shadow_599_cards_persist_without_entity_churn(self):
        from services.faculty_jobs_service import update_faculty_jobs
        from services.faculty_jobs_sources.base import AdapterResponse, SourceAdapter
        from services.faculty_jobs_sources.insidehighered import parse_fixture

        fixture = (
            Path(__file__).resolve().parent / "fixtures" / "faculty_jobs" /
            "inside_higher_ed_shadow_599_regressions.html"
        )
        jobs = parse_fixture(fixture.read_text(encoding="utf-8"), detail_budget=0)

        class OfflineIHE(SourceAdapter):
            name = adapter_name = "inside_higher_ed"
            base_url = "https://careers.insidehighered.com/jobs/"

            def fetch(self):
                return AdapterResponse(
                    jobs,
                    pages_fetched=1,
                    listing_pages=1,
                    reported_total=856,
                    coverage_complete=False,
                )

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp:
            db = str(Path(temp) / "faculty.db")
            ensure_faculty_jobs_tables(db)
            update_faculty_jobs(
                db,
                source_names=["inside_higher_ed"],
                adapters=[OfflineIHE()],
            )
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                linked_names = {
                    row[0] for row in conn.execute("""
                        SELECT DISTINCT i.official_name
                        FROM institutions i
                        JOIN jobs j ON j.institution_id=i.id
                        JOIN job_sources js ON js.job_id=j.id
                        JOIN sources s ON s.id=js.source_id
                        WHERE s.name='inside_higher_ed'
                    """)
                }
                self.assertEqual({
                    "University of Virginia",
                    "Brigham Young University Hawaii",
                    "University of Tennessee",
                    "Sam Houston State University",
                    "Towson University",
                    "Illinois State University",
                    "Miami University",
                    "Ohio State University",
                    "University of Kansas",
                    "Florida State University",
                }, linked_names)

                locations = {
                    row["source_job_id"]: row["city"]
                    for row in conn.execute("""
                        SELECT js.source_job_id,j.city
                        FROM jobs j
                        JOIN job_sources js ON js.job_id=j.id
                        JOIN sources s ON s.id=js.source_id
                        WHERE s.name='inside_higher_ed'
                          AND js.source_job_id IN ('3507076','3514729','3521991','3524554','3539640')
                    """)
                }
                self.assertEqual({
                    "3507076": None,
                    "3514729": None,
                    "3521991": None,
                    "3524554": None,
                    "3539640": None,
                }, locations)

                school_names = {
                    row[0] for row in conn.execute(
                        "SELECT official_name FROM business_schools WHERE is_current=1"
                    )
                }
                self.assertTrue({
                    "College of Business Administration",
                    "Herbert Wertheim College of Business",
                    "Fisher College of Business",
                }.issubset(school_names))
                self.assertFalse(school_names & {
                    "Administration Real Estate College of Business Administration",
                    "Department Herbert Wertheim College of Business",
                    "Tenure-Track Save Fisher College of Business",
                })
                self.assertEqual(0, conn.execute(
                    "SELECT COUNT(*) FROM business_schools WHERE is_current=0"
                ).fetchone()[0])
                self.assertEqual(0, conn.execute("""
                    SELECT COUNT(*) FROM faculty_job_repair_audit
                    WHERE action='merge_variant_school_entity'
                """).fetchone()[0])
            finally:
                conn.close()


class PaginationCapabilityTests(unittest.TestCase):
    """Single-page-by-construction must not read as fully harvested."""

    def test_every_enabled_adapter_declares_whether_it_paginates(self):
        from services.faculty_jobs_sources.base import adapter_catalog
        for adapter in adapter_catalog():
            self.assertIsInstance(getattr(adapter, "paginates", None), bool, adapter.name)

    def test_ais_is_declared_single_page(self):
        # Verified against the live board: ?page= does not paginate and the
        # real paging endpoint returns HTTP 403 to this fetcher.
        self.assertFalse(AISAdapter.paginates)

    def test_the_payload_says_a_single_page_source_cannot_reach_more(self):
        payload = build_faculty_job_sources(self.db)
        item = next(s for s in payload["sources"] if s["name"] == "ais")
        self.assertFalse(item["paginates"])
        self.assertIn("single-page", item["source_coverage_note"])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)

    def tearDown(self):
        self.dir.cleanup()


EURAXESS_CARD = """
  <article class="ecl-content-item">
    <a href="/jobs/{job_id}">Assistant Professor of Marketing</a>
    <div class="id-Work-Locations">Work Locations: Portugal, Lisbon</div>
  </article>
"""


def euraxess_page(*job_ids, total="Showing 1-10 of 7,601 jobs"):
    cards = "".join(EURAXESS_CARD.format(job_id=job_id) for job_id in job_ids)
    return f"<html><body><p>{total}</p>{cards}</body></html>"


class EuraxessPaginationTests(unittest.TestCase):
    """The board publishes ?page=0..760; reading only page one hides the rest.

    Page two was verified against the live board on 2026-08-27 to return ten
    ids absent from page one, so this is real pagination rather than a re-read.
    """

    def fetch(self, max_pages, pages):
        from services.faculty_jobs_sources.euraxess import EuraxessAdapter
        adapter = EuraxessAdapter(max_pages=max_pages, max_items=100)
        search_urls = []

        def request(url):
            if "/jobs/search" in url:
                search_urls.append(url)
                index = len(search_urls) - 1
                body = pages[index] if index < len(pages) else euraxess_page()
            else:
                body = "<html><body></body></html>"
            return type("R", (), {"text": body, "url": url})()

        with patch.object(adapter, "request", side_effect=request):
            return adapter.fetch(), search_urls

    def test_the_second_page_is_actually_read(self):
        response, urls = self.fetch(2, [euraxess_page("1", "2"), euraxess_page("3", "4")])
        self.assertEqual(["https://euraxess.ec.europa.eu/jobs/search",
                          "https://euraxess.ec.europa.eu/jobs/search?page=1"], urls)
        self.assertEqual({"1", "2", "3", "4"}, {job.source_job_id for job in response.jobs})
        self.assertEqual(2, response.pages_fetched)

    def test_the_default_budget_still_reads_one_page(self):
        response, urls = self.fetch(1, [euraxess_page("1", "2"), euraxess_page("3", "4")])
        self.assertEqual(1, len(urls))
        self.assertEqual(2, len(response.jobs))

    def test_an_empty_page_ends_the_loop_instead_of_spending_the_budget(self):
        _response, urls = self.fetch(5, [euraxess_page("1"), euraxess_page()])
        self.assertEqual(2, len(urls), "an empty result page means the end of the set")

    def test_the_shortfall_against_the_boards_own_total_is_reported(self):
        response, _urls = self.fetch(1, [euraxess_page("1", "2")])
        self.assertEqual(7601, response.reported_total)
        self.assertFalse(response.coverage_complete)
        self.assertTrue(any("of 7601" in note for note in response.notes), response.notes)

    def test_the_adapter_declares_that_it_paginates(self):
        from services.faculty_jobs_sources.euraxess import EuraxessAdapter
        self.assertTrue(EuraxessAdapter.paginates)


class PagedBoardBaseTests(unittest.TestCase):
    """Adapters built on the shared page loop must not read as single-page."""

    def test_the_shared_loop_declares_that_it_paginates(self):
        from services.faculty_jobs_sources.source_jobboards import _PagedBoardAdapter
        self.assertTrue(_PagedBoardAdapter.paginates)

    def test_every_adapter_on_that_base_inherits_the_true_label(self):
        from services.faculty_jobs_sources.base import adapter_catalog
        from services.faculty_jobs_sources.source_jobboards import _PagedBoardAdapter
        inheriting = [a.name for a in adapter_catalog() if isinstance(a, _PagedBoardAdapter)]
        self.assertTrue(inheriting, "the base class should still have adapters")
        for adapter in adapter_catalog():
            if isinstance(adapter, _PagedBoardAdapter):
                self.assertTrue(adapter.paginates,
                                f"{adapter.name} follows next-links but claims otherwise")


class ListingPagesVersusRequestsTests(unittest.TestCase):
    """Detail-page requests must not read as pagination reach.

    ``pages_fetched`` counts every request an adapter made, so a source that
    read one listing page and opened forty job pages recorded 41 — which, read
    as pages, makes a first-page-only harvest look like a deep crawl.
    """

    def test_listing_pages_defaults_to_the_request_count(self):
        from services.faculty_jobs_sources.base import AdapterResponse
        self.assertEqual(3, AdapterResponse([], pages_fetched=3).listing_pages)

    def test_detail_enrichment_does_not_inflate_listing_pages(self):
        from services.faculty_jobs_sources.base import AdapterResponse
        response = AdapterResponse([], pages_fetched=41, listing_pages=1)
        self.assertEqual(41, response.pages_fetched)
        self.assertEqual(1, response.listing_pages)

    def test_the_academic_jobs_online_adapter_separates_them(self):
        import inspect
        from services.faculty_jobs_sources import source_jobboards
        source = inspect.getsource(source_jobboards.AcademicJobsOnlineAdapter)
        self.assertIn("listing_pages=1", source,
                      "one listing page plus one detail page per job is not 41 pages")

    def test_the_payload_reports_reach_without_the_detail_requests(self):
        source_id = self.conn.execute("SELECT id FROM sources WHERE name='euraxess'").fetchone()[0]
        self.conn.execute("""
            INSERT INTO ingestion_runs
              (source_id,started_at,finished_at,status,pages_fetched,items_seen,listing_pages)
            VALUES (?,?,?,'success',11,10,1)
        """, (source_id, NOW, NOW))
        self.conn.commit()
        payload = build_faculty_job_sources(self.db)
        item = next(s for s in payload["sources"] if s["name"] == "euraxess")
        self.assertEqual(1, item["last_run_listing_pages"], "11 requests were not 11 pages")
        self.assertTrue(item["paginates"])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()


class PageBudgetTests(unittest.TestCase):
    """The scheduler and the coverage note must read one budget, not two.

    The note claims further pages "were left unread under the configured page
    budget". If the server ran under a different number than the note assumes,
    that sentence is false in whichever direction the two defaults disagree.
    """

    def setUp(self):
        self.saved = os.environ.pop("FACULTY_JOBS_MAX_PAGES_PER_SOURCE", None)

    def tearDown(self):
        os.environ.pop("FACULTY_JOBS_MAX_PAGES_PER_SOURCE", None)
        if self.saved is not None:
            os.environ["FACULTY_JOBS_MAX_PAGES_PER_SOURCE"] = self.saved

    def test_the_default_clears_every_paginating_source(self):
        from services.faculty_jobs_service import DEFAULT_MAX_PAGES_PER_SOURCE
        self.assertGreaterEqual(DEFAULT_MAX_PAGES_PER_SOURCE, 2,
                                "a budget of 1 stops every paginating board on page one")

    def test_the_environment_overrides_and_the_value_is_clamped(self):
        from services.faculty_jobs_service import (DEFAULT_MAX_PAGES_PER_SOURCE,
                                                   max_pages_per_source)
        self.assertEqual(DEFAULT_MAX_PAGES_PER_SOURCE, max_pages_per_source())
        for value, expected in (("1", 1), ("5", 5), ("0", 1), ("-3", 1),
                                ("abc", DEFAULT_MAX_PAGES_PER_SOURCE)):
            os.environ["FACULTY_JOBS_MAX_PAGES_PER_SOURCE"] = value
            self.assertEqual(expected, max_pages_per_source(), value)

    def test_the_server_takes_its_budget_from_the_same_accessor(self):
        import inspect
        import server
        source = inspect.getsource(server)
        self.assertIn("FACULTY_JOBS_MAX_PAGES = max_pages_per_source()", source,
                      "the server must not parse the budget with its own default")


class SlowOriginBudgetTests(unittest.TestCase):
    """A declared hour-long Crawl-delay is a pace, not just a sleep length.

    sms.careerwebsite.com publishes ``Crawl-delay: 3600`` under
    ``User-agent: *``, commented "Force the crawl delay for all bots to be one
    hour". Capping only the wait let a single run spend 13 requests on it at
    30s apart, which is not the pace the board asked for.
    """

    def setUp(self):
        from services.faculty_jobs_sources.base import reset_crawl_budgets
        reset_crawl_budgets()

    tearDown = setUp

    def consume(self, times, declared=3600.0, origin="https://slow.example"):
        from services.faculty_jobs_sources.base import _consume_slow_origin_budget
        for _ in range(times):
            _consume_slow_origin_budget(origin, declared)

    def test_the_first_request_to_a_slow_origin_is_allowed(self):
        self.consume(1)

    def test_the_second_request_in_the_same_run_is_refused(self):
        from services.faculty_jobs_sources.base import CrawlBudgetExhaustedError
        self.consume(1)
        with self.assertRaises(CrawlBudgetExhaustedError):
            self.consume(1)

    def test_a_refusal_is_a_policy_outcome_not_a_transport_error(self):
        from services.faculty_jobs_sources.base import (CrawlBudgetExhaustedError,
                                                        RobotsDisallowedError)
        self.assertTrue(issubclass(CrawlBudgetExhaustedError, RobotsDisallowedError),
                        "an unread page must never count as evidence of an empty board")

    def test_a_new_run_starts_a_fresh_budget(self):
        from services.faculty_jobs_sources.base import reset_crawl_budgets
        self.consume(1)
        reset_crawl_budgets()
        self.consume(1)

    def test_budgets_are_tracked_per_origin(self):
        self.consume(1, origin="https://a.example")
        self.consume(1, origin="https://b.example")

    def test_a_normal_crawl_delay_is_not_budgeted(self):
        from services.faculty_jobs_sources.base import _SLOW_ORIGIN_USED
        # Only origins above the wait ceiling reach the budget at all.
        self.assertEqual({}, _SLOW_ORIGIN_USED)

    def test_the_update_run_resets_the_budget(self):
        # Asserted behaviourally rather than by reading the function's source:
        # inspect.getsource locates code by file and line, so an unrelated edit
        # above the function makes it return a different function entirely and
        # the test fails for a reason that has nothing to do with the budget.
        import tempfile
        from pathlib import Path
        from services.faculty_jobs_service import ensure_faculty_jobs_tables, update_faculty_jobs
        from services.faculty_jobs_sources.base import _SLOW_ORIGIN_USED

        from services.faculty_jobs_sources.base import AdapterResponse, SourceAdapter

        class OfflineStub(SourceAdapter):
            # An empty `adapters` list is falsy and would fall back to the real
            # catalogue, putting a live fetch inside a unit test.
            name = adapter_name = "ais"
            base_url = "https://stub.example/jobs"

            def fetch(self):
                return AdapterResponse([], pages_fetched=0)

        self.consume(1, origin="https://slow.example")
        self.assertEqual({"https://slow.example": 1}, dict(_SLOW_ORIGIN_USED))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            db = str(Path(directory) / "faculty.db")
            ensure_faculty_jobs_tables(db)
            update_faculty_jobs(db, source_names=["ais"], adapters=[OfflineStub()])
        self.assertEqual({}, dict(_SLOW_ORIGIN_USED),
                         "each run starts a fresh per-origin budget")

    def paged_adapter(self, calls, fail_from):
        """A _PagedBoardAdapter whose Nth request hits the origin's budget."""
        from services.faculty_jobs_sources.base import CrawlBudgetExhaustedError, SourceJob
        from services.faculty_jobs_sources.source_jobboards import _PagedBoardAdapter

        class Stub(_PagedBoardAdapter):
            name = adapter_name = "stub"
            base_url = "https://slow.example/jobs/"

            def request(self, url):
                calls.append(url)
                if len(calls) >= fail_from:
                    raise CrawlBudgetExhaustedError(
                        "https://slow.example asks for Crawl-delay=3600.0s; this run "
                        "already used its 1-request budget for that origin")
                return type("R", (), {"text": "<html></html>", "url": url})()

            def fetch(self):
                def parser(_soup, _url):
                    return [SourceJob(source=self.name, source_job_id=str(len(calls)),
                                      source_url=f"{self.base_url}{len(calls)}",
                                      title_raw="Professor of Marketing",
                                      institution_raw="Example University",
                                      captured_at=NOW)]
                return self._fetch_pages(parser)

        return Stub(max_pages=3, max_items=100)

    def test_the_page_loop_stops_instead_of_failing_the_source(self):
        calls = []
        adapter = self.paged_adapter(calls, fail_from=2)
        with patch("services.faculty_jobs_sources.source_jobboards._next_page",
                   return_value="https://slow.example/jobs/2/"):
            response = adapter.fetch()
        self.assertEqual(2, len(calls), "it should stop asking after the refusal")
        self.assertEqual(1, response.pages_fetched)
        self.assertTrue(response.jobs, "page one was read and must be kept")
        self.assertTrue(any("Stopped after 1 page" in n for n in response.notes), response.notes)

    def test_a_refusal_on_the_very_first_page_is_not_silently_empty(self):
        from services.faculty_jobs_sources.base import CrawlBudgetExhaustedError
        calls = []
        adapter = self.paged_adapter(calls, fail_from=1)
        with self.assertRaises(CrawlBudgetExhaustedError):
            adapter.fetch()


class SharedTotalParserTests(unittest.TestCase):
    def test_common_board_phrasings(self):
        from services.faculty_jobs_sources.base import reported_result_total
        for text, expected in (("1 - 25 Results of 53", 53),
                               ("Showing 1-20 of 1,204 jobs", 1204),
                               ("128 jobs found", 128),
                               ("Latest vacancies", None),
                               ("Job ID 12345", None)):
            soup = BeautifulSoup(f"<p>{text}</p>", "html.parser")
            self.assertEqual(expected, reported_result_total(soup), text)



class RosterDenominatorTests(unittest.TestCase):
    """A school with no website is excluded from the scan denominator, and said so."""

    NOW = "2026-08-29T00:00:00Z"

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.add_school(1, "Reachable A", "https://a.example.edu")
        self.add_school(2, "Reachable B", "https://b.example.edu")
        self.add_school(3, "No website recorded", None)
        self.conn.execute(
            "INSERT INTO aacsb_scan_history "
            "(directory_school_id,checked_at,website_status,career_page_status,"
            " job_scan_status,reconciliation_complete) "
            "VALUES (1,?,'ok','ok','no_current_jobs',1)", (self.NOW,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add_school(self, school_id, name, website):
        self.conn.execute("""
            INSERT INTO aacsb_directory_schools
              (id,directory_result_id,directory_url,institution_name,directory_title,
               roster_source_url,official_website,active,
               first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,1,?,?,?,?)
        """, (school_id, f"r{school_id}", f"https://directory.example/{school_id}",
              name, name, "https://directory.example/", website,
              self.NOW, self.NOW, self.NOW, self.NOW))

    def roster(self):
        payload = build_faculty_job_sources(self.db)
        item = next(s for s in payload["sources"] if s["name"] == "aacsb_official")
        return item["roster_coverage"]

    def test_the_denominator_holds_only_schools_that_can_be_scanned(self):
        self.assertEqual(2, self.roster()["schools"])

    def test_a_school_with_no_website_is_reported_rather_than_dropped(self):
        roster = self.roster()
        self.assertEqual(1, roster["no_website_recorded"])
        self.assertEqual(3, roster["roster_rows"])
        self.assertEqual(roster["roster_rows"],
                         roster["schools"] + roster["no_website_recorded"])

    def test_a_partial_roster_never_reports_a_complete_scan(self):
        payload = build_faculty_job_sources(self.db)
        item = next(s for s in payload["sources"] if s["name"] == "aacsb_official")
        self.assertEqual(1, item["roster_coverage"]["complete_observations"])
        self.assertIsNone(item["last_complete_scan"],
                          "one school read completely is not the roster read completely")

if __name__ == "__main__":
    unittest.main()
