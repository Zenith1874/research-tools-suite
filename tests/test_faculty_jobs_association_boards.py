# -*- coding: utf-8 -*-
"""Association and portal boards, parsed from markup rather than joined text.

These boards are small, but they carry tenure-track and research appointments
where a general aggregator's volume is mostly contingent teaching work, so
their composition matters more than their size.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.faculty_jobs_sources.association_boards import (
    ANZAMAdapter, EAAAccountingAdapter, EconJobMarketAdapter,
    TimesHigherEducationUnijobsAdapter,
)
from services.faculty_jobs_sources.base import adapter_catalog


ECON_CARD = """
<div class="card">
  <div class="row"><div class="col-md-12"><span class="label">Featured advertisement</span></div></div>
  <div class="col-md-4">
    <a class="adBody" href="#ad-12554">{title}</a>
    <button class="btn"></button><br>{place} ( map ) . Starts 2027-07-01.
  </div>
  <div class="col-md-4"><div class="media"><div class="media-body">{employer}</div></div></div>
</div>
"""


def econ_page(*cards):
    return "<html><body>" + "".join(cards) + "</body></html>"


class EconJobMarketParsingTests(unittest.TestCase):
    """A title may contain commas, so it cannot be split off by regex."""

    def parse(self, html):
        return EconJobMarketAdapter.parse_html(html, EconJobMarketAdapter.base_url, 100)

    def test_a_plain_title_and_place_are_separated(self):
        jobs = self.parse(econ_page(ECON_CARD.format(
            title="Assistant/Associate Professor", place="Burnaby, Canada",
            employer="Department of Economics Simon Fraser University")))
        self.assertEqual(1, len(jobs))
        self.assertEqual("Assistant/Associate Professor", jobs[0].title_raw)
        self.assertEqual("Burnaby, Canada", jobs[0].location_raw)
        self.assertEqual("12554", jobs[0].source_job_id)

    def test_a_comma_inside_the_title_survives(self):
        # "Faculty Positions in Economics, AI & Data Analytics Kuala Lumpur,
        # Malaysia ( map )" cannot be split on its last comma: an earlier
        # attempt produced the title "Faculty Positions in Economics," and the
        # location "AI & Data Analytics Kuala Lumpur, Malaysia".
        jobs = self.parse(econ_page(ECON_CARD.format(
            title="Faculty Positions in Economics, AI &amp; Data Analytics",
            place="Kuala Lumpur, Malaysia", employer="Asia School of Business")))
        self.assertEqual("Faculty Positions in Economics, AI & Data Analytics",
                         jobs[0].title_raw)
        self.assertEqual("Kuala Lumpur, Malaysia", jobs[0].location_raw)

    def test_a_title_that_starts_with_a_comma_phrase_survives(self):
        jobs = self.parse(econ_page(ECON_CARD.format(
            title="Monash Economics, Associate Professor",
            place="Caulfield East, Australia", employer="Department of Economics")))
        self.assertEqual("Monash Economics, Associate Professor", jobs[0].title_raw)
        self.assertEqual("Caulfield East, Australia", jobs[0].location_raw)

    def test_the_same_advertisement_is_not_counted_twice(self):
        card = ECON_CARD.format(title="Assistant Professor", place="Boston, United States",
                                employer="Economics Boston University")
        self.assertEqual(1, len(self.parse(econ_page(card, card))))

    def test_a_card_without_an_advertisement_anchor_is_skipped(self):
        self.assertEqual([], self.parse(econ_page(
            '<div class="card"><div class="col-md-4">Sort by deadline</div></div>')))


ANZAM_BLOCK = """
<div class="single_block border_bottom">
  <a href="/jobs/{slug}/">{title}</a>
  <span>Deadline:</span><span>{deadline}</span>
  <p>{body}</p>
</div>
"""


class ANZAMParsingTests(unittest.TestCase):
    def parse(self, html):
        return ANZAMAdapter.parse_html(html, ANZAMAdapter.base_url, 100)

    def test_the_deadline_label_is_not_read_as_the_date(self):
        jobs = self.parse("<html><body>" + ANZAM_BLOCK.format(
            slug="monash-university-lecturer", title="Monash University - Lecturer",
            deadline="August 31 2026", body="Employment relations.") + "</body></html>")
        self.assertEqual(1, len(jobs))
        self.assertEqual("August 31 2026", jobs[0].deadline_raw)
        self.assertEqual("Monash University - Lecturer", jobs[0].title_raw)
        self.assertEqual("monash-university-lecturer", jobs[0].source_job_id)

    def test_board_furniture_is_not_part_of_the_title(self):
        # "Job Posting – Head of School, Management and Marketing" is a label
        # glued to a title. Left in, it becomes the leading words of the job
        # name and the downstream role classifier reads the posting as chrome.
        jobs = self.parse("<html><body>" + ANZAM_BLOCK.format(
            slug="qut-head-of-school", title="Job Posting – Head of School, Management",
            deadline="September 21 2026", body="Queensland.") + "</body></html>")
        self.assertEqual("Head of School, Management", jobs[0].title_raw)

    def test_a_title_without_that_label_is_untouched(self):
        jobs = self.parse("<html><body>" + ANZAM_BLOCK.format(
            slug="monash-lecturer", title="Monash University – Lecturer/Senior Lecturer",
            deadline="August 31 2026", body="Employment relations.") + "</body></html>")
        self.assertEqual("Monash University – Lecturer/Senior Lecturer", jobs[0].title_raw)

    def test_an_institution_is_left_unknown_rather_than_guessed(self):
        # The board's card names a university inside the posting title, but
        # nothing in it asserts a school entity, so the field stays unknown.
        jobs = self.parse("<html><body>" + ANZAM_BLOCK.format(
            slug="unsw-business-school-job", title="UNSW Business School - Job posting",
            deadline="September 1 2026", body="Sydney.") + "</body></html>")
        self.assertEqual("Unknown institution", jobs[0].institution_raw)


class EAAParsingTests(unittest.TestCase):
    def test_listing_slugs_become_stable_ids(self):
        html = ("<html><body><div>"
                "<a href='/arc/jobs/full-professor-in-accounting/'>"
                "Full Professor in Accounting and Auditing</a></div></body></html>")
        jobs = EAAAccountingAdapter.parse_html(html, EAAAccountingAdapter.base_url, 100)
        self.assertEqual(1, len(jobs))
        self.assertEqual("full-professor-in-accounting", jobs[0].source_job_id)
        self.assertEqual("Full Professor in Accounting and Auditing", jobs[0].title_raw)

    def test_the_index_link_itself_is_not_a_posting(self):
        html = "<html><body><div><a href='/arc/jobs/'>Jobs</a></div></body></html>"
        self.assertEqual([], EAAAccountingAdapter.parse_html(
            html, EAAAccountingAdapter.base_url, 100))


class UnijobsParsingTests(unittest.TestCase):
    """THE is another Madgex tenant; only its job path differs."""

    def test_the_shared_madgex_parser_reads_a_unijobs_card(self):
        html = """
        <html><body><ul class="lister">
          <li class="lister__item">
            <div class="lister__details">
              <h3><a href="/unijobs/listing/414961/professor-of-marketing/">Professor of Marketing</a></h3>
              <ul>
                <li class="lister__meta-item lister__meta-item--location">Melbourne, Australia</li>
                <li class="lister__meta-item lister__meta-item--recruiter">DEAKIN UNIVERSITY</li>
              </ul>
            </div>
          </li>
        </ul></body></html>
        """
        jobs = TimesHigherEducationUnijobsAdapter.parse_html(
            html, TimesHigherEducationUnijobsAdapter.base_url, 100)
        self.assertEqual(1, len(jobs))
        self.assertEqual("Professor of Marketing", jobs[0].title_raw)
        self.assertEqual("DEAKIN UNIVERSITY", jobs[0].institution_raw)
        self.assertEqual("Melbourne, Australia", jobs[0].location_raw)

    def test_the_chronicle_job_path_does_not_match_this_tenant(self):
        # Guards the parameterisation: THE postings live under
        # /unijobs/listing/, so the default /job/ path must find nothing here.
        from services.faculty_jobs_sources.source_jobboards import parse_madgex_listing
        html = ("<html><body><ul class='lister'><li class='lister__item'>"
                "<h3><a href='/unijobs/listing/1/x/'>Professor</a></h3>"
                "</li></ul></body></html>")
        self.assertEqual([], parse_madgex_listing(html, "x", "https://e.test", None, 10))
        self.assertEqual(1, len(parse_madgex_listing(
            html, "x", "https://e.test", None, 10, job_path=r"/unijobs/listing/")))


class RegistrationTests(unittest.TestCase):
    def test_all_four_boards_are_enabled_in_the_catalogue(self):
        catalogue = {adapter.name: adapter for adapter in adapter_catalog()}
        for name in ("the_unijobs", "econjobmarket", "eaa_accounting", "anzam"):
            self.assertIn(name, catalogue)
            self.assertTrue(catalogue[name].enabled, name)

    def test_single_page_boards_declare_it(self):
        catalogue = {adapter.name: adapter for adapter in adapter_catalog()}
        self.assertTrue(catalogue["the_unijobs"].paginates)
        for name in ("econjobmarket", "eaa_accounting", "anzam"):
            self.assertFalse(catalogue[name].paginates, name)

    def test_an_unread_board_never_reports_false_coverage(self):
        adapter = ANZAMAdapter(max_pages=1)
        with patch.object(adapter, "request",
                          return_value=SimpleNamespace(text="<html></html>",
                                                       url=ANZAMAdapter.base_url)):
            response = adapter.fetch()
        self.assertEqual([], response.jobs)
        self.assertIsNone(response.coverage_complete)


if __name__ == "__main__":
    unittest.main()


class SourceCategoryPreservationTests(unittest.TestCase):
    """A board's own taxonomy label is evidence and must not be discarded.

    HigherEdJobs files every posting under a category it chose ("Accounting",
    "Business Law"). That is the only discipline assertion the source itself
    makes, and it disagreed with our derived discipline often enough to matter.
    The adapter was already collecting it and the normalizer was dropping it,
    so it never reached the source record.
    """

    def normalize(self, extra):
        from services.faculty_jobs_normalizer import normalize_source_job
        from services.faculty_jobs_sources.base import SourceJob
        job = SourceJob(source="higheredjobs", source_job_id="1",
                        source_url="https://example.test/1",
                        title_raw="Adjunct Faculty, Business Law",
                        institution_raw="Babson College", location_raw="Babson Park, MA",
                        captured_at="2026-08-29T00:00:00Z", extra=extra)
        return normalize_source_job(job, "United States")

    def test_the_board_category_reaches_the_normalized_record(self):
        self.assertEqual("Business Law",
                         self.normalize({"source_category": "Business Law"})["source_category"])

    def test_a_board_without_a_category_records_none(self):
        self.assertIsNone(self.normalize({})["source_category"])

    def test_it_does_not_silently_become_the_derived_discipline(self):
        # Preserving the source's own label is not the same as adopting it.
        # Whether it should override the classifier is a separate decision;
        # this test pins that the change made here was preservation only.
        normalized = self.normalize({"source_category": "Business Law"})
        self.assertEqual("Business Law", normalized["source_category"])
        self.assertIsNotNone(normalized["discipline_primary"])
        self.assertNotEqual("Business Law", normalized["discipline_primary"])
