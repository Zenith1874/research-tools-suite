# -*- coding: utf-8 -*-
"""HigherEdJobs is opt-in and either returns a complete snapshot or nothing."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.faculty_jobs_service import ensure_faculty_jobs_tables, update_faculty_jobs
from services.faculty_jobs_sources.base import (
    AdapterError, NonRetryableAdapterError, adapter_catalog,
)
from services.faculty_jobs_sources.higheredjobs import (
    HigherEdJobsAdapter, browser_snapshot_response,
)


def card(job_code, title, institution, location, category, posted="Posted 2 days ago",
         salary=None):
    salary_html = f'<br><span class="job-salary">{salary}</span>' if salary else ""
    return f"""
      <div class="row record">
        <div class="col-sm-7">
          <a href="details.cfm?JobCode={job_code}&amp;Title={title}">{title}</a><br>
          {institution}<br>{location}{salary_html}
        </div>
        <div class="col-sm-5 text-sm-right">
          <span class="text-nowrap">{category}</span><br>{posted}<br>
        </div>
        <div class="col-sm-12"><span class="addon-marker">Priority</span></div>
      </div>
    """


def page(start, end, total, *cards):
    return (
        "<html><body>"
        f"<div>Results {start} - {end} of {total:,}</div>"
        f"<div class='result-page'>{''.join(cards)}</div>"
        "</body></html>"
    )


PAGE_ONE_COMPLETE = page(
    1, 2, 2,
    card("179542048", "Assistant or Associate Professor, Finance",
         "Example University", "Austin, TX", "Finance", salary="$90,000 per year"),
    card("179541984", "Assistant Professor of Marketing",
         "Example College", "Boston, MA", "Marketing and Sales"),
)


def browser_snapshot(*jobs):
    return {
        "source": "higheredjobs",
        "source_url": HigherEdJobsAdapter.base_url,
        "capture_method": "ordinary_visible_browser_pagination",
        "captured_at": "2026-08-28T23:20:00Z",
        "reported_total": len(jobs),
        "page_size": 100,
        "pages_fetched": 1,
        "coverage_complete": True,
        "pages": [{
            "page": 1, "start": 1, "end": len(jobs), "cards": len(jobs),
            "captured_at": "2026-08-28T23:20:00Z",
        }],
        "jobs": list(jobs),
    }


def browser_job(job_code, title="Assistant Professor of Finance"):
    return {
        "source_job_id": str(job_code),
        "source_url": (
            "https://www.higheredjobs.com/faculty/details.cfm?"
            f"JobCode={job_code}&Title={title}"
        ),
        "title_raw": title,
        "institution_raw": "Example University",
        "location_raw": "Austin, TX",
        "description_excerpt": "HigherEdJobs category: Finance.",
        "posted_date_raw": "Posted Today",
        "salary_raw": "$90,000 per year",
        "captured_at": "2026-08-28T23:20:00Z",
        "extra": {"source_category": "Finance", "source_priority_listing": False},
    }


class HigherEdJobsAdapterTests(unittest.TestCase):
    def adapter(self, max_pages=1):
        adapter = HigherEdJobsAdapter(max_pages=max_pages)
        adapter.page_delay = 0
        return adapter

    def test_source_is_explicit_opt_in_not_part_of_default_update(self):
        self.assertFalse(HigherEdJobsAdapter.enabled)
        self.assertEqual("opt_in", HigherEdJobsAdapter.support_status)
        enabled = {adapter.name for adapter in adapter_catalog() if adapter.enabled}
        self.assertNotIn("higheredjobs", enabled)

    def test_complete_page_parses_listing_metadata_and_provenance(self):
        adapter = self.adapter()
        response_obj = SimpleNamespace(text=PAGE_ONE_COMPLETE)
        with patch.object(adapter, "request", return_value=response_obj):
            response = adapter.fetch()
        self.assertTrue(response.coverage_complete)
        self.assertEqual(2, response.reported_total)
        self.assertEqual(1, response.listing_pages)
        self.assertEqual(2, len(response.jobs))
        first = response.jobs[0]
        self.assertEqual("179542048", first.source_job_id)
        self.assertEqual("Example University", first.institution_raw)
        self.assertEqual("Austin, TX", first.location_raw)
        self.assertEqual("Posted 2 days ago", first.posted_date_raw)
        self.assertEqual("$90,000 per year", first.salary_raw)
        self.assertIn("/faculty/details.cfm?JobCode=179542048", first.source_url)
        self.assertIsNone(first.official_url)
        self.assertEqual("Finance", first.extra["source_category"])

    def test_complete_numbered_pagination_is_distinct_and_auditable(self):
        first = page(
            1, 2, 3,
            card("1", "Assistant Professor of Finance", "One University", "One, TX", "Finance"),
            card("2", "Lecturer in Marketing", "Two College", "Two, MA", "Marketing"),
        )
        second = page(
            3, 3, 3,
            card("3", "Professor of Management", "Three University", "Three, NY", "Management"),
        )
        adapter = self.adapter(max_pages=2)
        with patch.object(adapter, "request", side_effect=[
                SimpleNamespace(text=first), SimpleNamespace(text=second)]) as request:
            response = adapter.fetch()
        self.assertEqual(2, response.pages_fetched)
        self.assertEqual(3, response.reported_total)
        self.assertEqual({"1", "2", "3"}, {job.source_job_id for job in response.jobs})
        self.assertTrue(response.coverage_complete)
        self.assertEqual(
            HigherEdJobsAdapter.base_url + "&Page=2",
            request.call_args_list[1].args[0],
        )

    def test_department_line_does_not_become_location(self):
        html = page(
            1, 1, 1,
            """
            <div class="row record">
              <div class="col-sm-7">
                <a href="details.cfm?JobCode=9">Adjunct Faculty - College of Business</a><br>
                Eastern New Mexico University<br>College of Business<br>Portales, NM
              </div>
              <div class="col-sm-5"><span class="text-nowrap">Management</span></div>
            </div>
            """,
        )
        adapter = self.adapter()
        with patch.object(adapter, "request", return_value=SimpleNamespace(text=html)):
            response = adapter.fetch()
        job = response.jobs[0]
        self.assertEqual("Eastern New Mexico University", job.institution_raw)
        self.assertEqual("Portales, NM", job.location_raw)
        self.assertEqual(["College of Business"], job.extra["source_middle_lines"])

    def test_insufficient_page_budget_returns_no_partial_snapshot(self):
        first = page(
            1, 2, 3,
            card("1", "Assistant Professor of Finance", "One University", "One, TX", "Finance"),
            card("2", "Lecturer in Marketing", "Two College", "Two, MA", "Marketing"),
        )
        adapter = self.adapter(max_pages=1)
        with patch.object(adapter, "request", return_value=SimpleNamespace(text=first)):
            with self.assertRaisesRegex(AdapterError, "requires at least 2 pages"):
                adapter.fetch()

    def test_imperva_interstitial_is_an_error_not_an_empty_board(self):
        challenge = """
          <html><head><meta name='robots' content='noindex, nofollow'></head>
          <body><h1>Pardon Our Interruption</h1>
          <script>window.reeseSkipExpirationCheck = true;</script></body></html>
        """
        adapter = self.adapter()
        with patch.object(adapter, "request", return_value=SimpleNamespace(text=challenge)):
            with self.assertRaisesRegex(NonRetryableAdapterError, "no partial snapshot"):
                adapter.fetch()

    def test_explicit_source_selection_may_run_the_opt_in_adapter(self):
        with tempfile.TemporaryDirectory(prefix="higheredjobs-optin-") as directory:
            db = str(Path(directory) / "faculty.db")
            ensure_faculty_jobs_tables(db)
            adapter = self.adapter()
            with patch.object(adapter, "request", return_value=SimpleNamespace(
                    text=PAGE_ONE_COMPLETE)):
                result = update_faculty_jobs(
                    db, source_names=["higheredjobs"], adapters=[adapter], max_pages=1)
            self.assertTrue(result["ok"], result)
            self.assertEqual("success", result["sources"][0]["status"])
            self.assertTrue(result["sources"][0]["coverage_complete"])
            conn = sqlite3.connect(db)
            try:
                count = conn.execute("""
                    SELECT COUNT(*) FROM job_sources js
                    JOIN sources s ON s.id=js.source_id
                    WHERE s.name='higheredjobs'
                """).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(2, count)

    def test_complete_browser_snapshot_is_validated_and_converted(self):
        response = browser_snapshot_response(browser_snapshot(
            browser_job("179542048"), browser_job("179541984", "Lecturer in Marketing")))
        self.assertTrue(response.coverage_complete)
        self.assertEqual(2, response.reported_total)
        self.assertEqual(1, response.listing_pages)
        self.assertEqual({"179542048", "179541984"}, {
            job.source_job_id for job in response.jobs})
        self.assertEqual(
            "ordinary_visible_browser_pagination",
            response.jobs[0].extra["capture_method"],
        )

    def test_partial_or_duplicate_browser_snapshot_is_rejected(self):
        partial = browser_snapshot(browser_job("1"), browser_job("2"))
        partial["coverage_complete"] = False
        with self.assertRaisesRegex(AdapterError, "not marked coverage-complete"):
            browser_snapshot_response(partial)

        duplicate = browser_snapshot(browser_job("1"), browser_job("1"))
        with self.assertRaisesRegex(AdapterError, "invalid identity"):
            browser_snapshot_response(duplicate)


if __name__ == "__main__":
    unittest.main()
