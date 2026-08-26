# -*- coding: utf-8 -*-
"""Synthetic parser contracts for the public source expansion adapters."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from services.faculty_jobs_normalizer import (
    _reference_date,
    normalize_source_job,
    parse_date,
)
from services.faculty_jobs_sources.base import SourceJob
from services.faculty_jobs_sources.source_jobboards import (
    AAACareerCenterAdapter,
    AACSBJobConnectionAdapter,
    AKADEUSAdapter,
    AcademicJobsOnlineAdapter,
    AMAAcademicPlacementAdapter,
    ChronicleAdapter,
    DecisionSciencesAdapter,
    EFMDJobsAdapter,
    FMAAdapter,
    HERCAdapter,
    INFORMSAdapter,
    POMSAdapter,
    SMSAdapter,
)


class FacultyJobSourceExpansionTests(unittest.TestCase):
    def test_chronicle_listing_fields(self):
        html = """
        <li class="lister__item" id="item-1001">
          <h3><a href="/job/1001/assistant-professor-finance/">Assistant Professor of Finance</a></h3>
          <ul class="lister__meta">
            <li class="lister__meta-item lister__meta-item--location">Austin, Texas (US)</li>
            <li class="lister__meta-item lister__meta-item--salary">$120,000 - $140,000 per year</li>
            <li class="lister__meta-item lister__meta-item--recruiter">Example University School of Business</li>
          </ul>
          <p class="lister__description">Tenure-track faculty position in the School of Business.</p>
        </li>
        """
        job = ChronicleAdapter.parse_html(html, "https://jobs.chronicle.com/jobs/business-and-management/")[0]
        self.assertEqual("1001", job.source_job_id)
        self.assertEqual("Assistant Professor of Finance", job.title_raw)
        self.assertEqual("Example University", job.institution_raw)
        self.assertEqual("Austin, Texas (US)", job.location_raw)
        self.assertIn("$120,000", job.salary_raw)
        self.assertTrue(job.source_url.endswith("/job/1001/assistant-professor-finance/"))
        normalized = normalize_source_job(job, "Global")
        self.assertEqual("business_school", normalized["business_scope"])
        self.assertEqual("faculty", normalized["faculty_market_role"])

    def test_aaa_listing_fields_and_relative_posted_date(self):
        html = """
        <li class="lister__item" id="item-2001">
          <h3><a href="/job/2001/assistant-professor-management/">Assistant Professor of Management</a></h3>
          <ul class="lister__meta">
            <li class="lister__meta-item lister__meta-item--location">Dublin, Ireland</li>
            <li class="lister__meta-item lister__meta-item--salary">€70,000 per year</li>
            <li class="lister__meta-item lister__meta-item--recruiter">Example College of Business</li>
            <li class="lister__meta-item lister__meta-item--date">3 days ago</li>
          </ul>
          <p class="lister__description">The College of Business invites applications.</p>
        </li>
        """
        job = AAACareerCenterAdapter.parse_html(html, "https://careercenter.aaahq.org/jobs")[0]
        self.assertEqual("2001", job.source_job_id)
        self.assertEqual("Example College", job.institution_raw)
        self.assertEqual("Dublin, Ireland", job.location_raw)
        self.assertEqual("3 days ago", job.posted_date_raw)
        # Pin the capture instant: a relative posted date is only meaningful
        # against a fixed anchor, and asserting a literal date against the
        # wall clock makes the test pass for exactly one day.
        job = replace(job, captured_at="2026-08-25")
        normalized = normalize_source_job(job, "Global")
        self.assertEqual("IE", normalized["country_code"])
        self.assertEqual("2026-08-22", normalized["posted_date"])

    def test_relative_posted_date_anchors_on_the_local_calendar_day(self):
        """captured_at is a UTC instant; the anchor must be the local day.

        Taking the calendar day straight off the UTC value shifts every
        relative date forward by one once UTC has rolled over but the local
        day has not, which is every evening west of Greenwich.
        """
        captured = datetime(2026, 8, 26, 5, 45, tzinfo=timezone.utc)
        expected = captured.astimezone().date()
        self.assertEqual(expected, _reference_date(captured.isoformat()))
        self.assertEqual(
            (expected - timedelta(days=3)).isoformat(),
            parse_date("3 days ago", reference_date=captured.isoformat()),
        )

    def test_poms_table_fields(self):
        html = """
        <table><tr><th>Position</th><th>University</th><th>Date</th><th>View</th></tr>
        <tr><td>Assistant Professor of Supply Chain Management</td><td>Syracuse University</td>
          <td>08/20/2026</td><td><a href="/sites/default/files/2026-08/ad.pdf">View Posting</a></td></tr>
        </table>
        """
        job = POMSAdapter.parse_html(html, "https://www.poms.org/opportunities")[0]
        self.assertEqual("Assistant Professor of Supply Chain Management", job.title_raw)
        self.assertEqual("Syracuse University", job.institution_raw)
        self.assertEqual("08/20/2026", job.posted_date_raw)
        normalized = normalize_source_job(job, "Global")
        self.assertEqual("2026-08-20", normalized["posted_date"])
        self.assertEqual("business_discipline", normalized["business_scope"])

    def test_decision_sciences_fields_and_direct_application_url(self):
        html = """
        <table><tr><th>Posted</th><th>Institution</th><th>Location</th><th>Job Title</th><th>Job Type</th><th>Area of Interest</th></tr>
        <tr><td>08/24/2026</td><td>Example University</td><td>Columbus, OH USA</td>
        <td>Assistant Professor See Details</td><td>Full Time, Tenure Track</td><td>Operations Management</td>
        <td><a href="https://example.edu/jobs/123">See Details</a></td></tr></table>
        """
        job = DecisionSciencesAdapter.parse_html(html, "https://decisionsciences.org/professional-growth/open-positions/")[0]
        self.assertEqual("Assistant Professor", job.title_raw)
        self.assertEqual("Example University", job.institution_raw)
        self.assertEqual("Columbus, OH USA", job.location_raw)
        self.assertEqual("2026-08-24", normalize_source_job(job, "Global")["posted_date"])
        self.assertEqual("https://example.edu/jobs/123", job.official_url)

    def test_sms_uses_full_hidden_title_not_truncated_card_text(self):
        html = """
        <div class="job-tile-3001 job-tile">
          <div class="job-details">
            <input name="job_Position" value="Tenure-Track Position in Strategy &amp; Entrepreneurship (Assistant, Associate &amp; Full Professor)">
            <div class="job-title"><a href="/job/strategy/3001/" title="Tenure-Track Position in Strategy &amp; Entrepreneurship (Assistant, Associate &amp; Full Professor)">Tenure-Track Position in Strategy &amp; Entrepreneurship (Assistant, Associate &amp; Full...</a></div>
            <div class="job-company-row">Singapore Management University</div>
            <div class="job-location">Singapore, Singapore <span>(on-site)</span></div>
            <div class="job-posted-date">27 days ago</div>
          </div>
        </div>
        """
        job = SMSAdapter.parse_html(html, "https://sms.careerwebsite.com/jobs")[0]
        self.assertIn("Full Professor", job.title_raw)
        self.assertEqual("Singapore Management University", job.institution_raw)
        normalized = normalize_source_job(job, "Global")
        self.assertEqual("faculty", normalized["faculty_market_role"])
        self.assertEqual("business_discipline", normalized["business_scope"])

    def test_academic_jobs_online_detail_fields(self):
        html = """
        <h2>Example University, Questrom School of Business</h2>
        Position ID: EX-QST-1 [#31001]
        Position Title: Assistant Professor of Marketing Position Type: Tenure-track faculty
        Position Location: Boston, Massachusetts 02115, United States of America [ map ]
        Subject Area: Business Appl Deadline: 2026/10/07 23:59:59 (posted 2026/08/17 , listed until 2027/01/03)
        Position Description: The business school invites applications. Salary Range: $110,000-$130,000.
        """
        job = AcademicJobsOnlineAdapter.parse_detail_html(
            html, "https://academicjobsonline.org/ajo/jobs/31001"
        )
        self.assertIsNotNone(job)
        self.assertEqual("Assistant Professor of Marketing", job.title_raw)
        self.assertEqual("Example University", job.institution_raw)
        self.assertEqual("Questrom School of Business", job.school_raw)
        self.assertEqual("Business", job.department_raw)
        self.assertIn("2026/10/07", job.deadline_raw)
        normalized = normalize_source_job(job, "Global")
        self.assertEqual("US", normalized["country_code"])
        self.assertEqual("business_school", normalized["business_scope"])

    def test_akadeus_fields_and_european_date(self):
        html = """
        <div class="itemsList"><div class="row"><div class="xx-12">
          <a href="/announcement/4001"><div class="box-2">
            <h2>Assistant / Associate Professor in Finance</h2>
            <p class="location">France / Paris</p><p class="discipline">Finance</p>
            <div class="params"><p>Example Business School</p><p>Location: France / Paris</p>
            <p>Employment Type: Permanent Full-time</p><p>Posted: 24/07/2026</p></div>
          </div></a>
        </div></div></div>
        """
        job = AKADEUSAdapter.parse_html(html, "https://akadeus.com/announcements")[0]
        self.assertEqual("4001", job.source_job_id)
        self.assertEqual("Example Business School", job.institution_raw)
        self.assertEqual("2026-07-24", job.posted_date_raw)
        normalized = normalize_source_job(job, "Global")
        self.assertEqual("FR", normalized["country_code"])
        self.assertEqual("2026-07-24", normalized["posted_date"])
        self.assertIn(normalized["business_scope"], {"business_school", "business_discipline"})

    def test_chronicle_public_detail_keeps_university_and_school_separate(self):
        html = """
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"Assistant/Associate Professor Position in Entrepreneurship",
         "datePosted":"2026-08-20T17:00:00.000Z","validThrough":"2026-10-20T03:59:00.000Z",
         "hiringOrganization":{"name":"Rutgers Business School at Newark and New Brunswick"},
         "jobLocation":{"address":{"addressLocality":"Newark","addressRegion":"New Jersey","addressCountry":"US"}},
         "description":"Rutgers Business School is part of Rutgers, The State University of New Jersey. Application deadline: October 20, 2026."}
        </script>
        <h1>Assistant/Associate Professor Position in Entrepreneurship</h1>
        """
        job = ChronicleAdapter.parse_detail_html(html, "https://jobs.chronicle.com/job/38028184/example/")
        self.assertEqual("Rutgers, The State University of New Jersey", job.institution_raw)
        self.assertEqual("Rutgers Business School", job.school_raw)
        self.assertEqual("October 20, 2026", job.deadline_raw)
        self.assertEqual("Newark, New Jersey, (US)", job.location_raw)

    def test_aaa_public_detail_extracts_deadline_start_text_and_school(self):
        html = """
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"Tenure-track Assistant Professor in Business Analytics",
         "datePosted":"2026-08-17T16:15:00.000Z","validThrough":"2026-10-17T03:59:00.000Z",
         "hiringOrganization":{"name":"Pace University"},
         "jobLocation":{"address":{"addressLocality":"Pleasantville","addressRegion":"New York","addressCountry":"US"}},
         "description":"The Lubin School of Business at Pace University invites applications. Application deadline: October 1, 2026. The start date is September 1, 2027."}
        </script>
        <h1>Tenure-track Assistant Professor in Business Analytics</h1>
        """
        job = AAACareerCenterAdapter.parse_detail_html(html, "https://careercenter.aaahq.org/job/269825/example/")
        self.assertEqual("Pace University", job.institution_raw)
        self.assertEqual("Lubin School of Business", job.school_raw)
        self.assertEqual("October 1, 2026", job.deadline_raw)
        self.assertEqual("US", normalize_source_job(job, "Global")["country_code"])

    def test_aaa_detail_uses_parent_university_after_school_name(self):
        html = """
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"Tenure-Track Accounting Faculty",
         "validThrough":"2026-10-21T03:59:00.000Z",
         "hiringOrganization":{"name":"Mays Business School"},
         "jobLocation":{"address":{"addressLocality":"College Station","addressRegion":"Texas","addressCountry":"US"}},
         "description":"The James Benjamin Department of Accounting at Mays Business School, Texas A&amp;M University invites applications for full-time faculty positions."}
        </script>
        """
        job = AAACareerCenterAdapter.parse_detail_html(html, "https://careercenter.aaahq.org/job/270786/example/")
        self.assertEqual("Texas A&M University", job.institution_raw)
        self.assertEqual("Mays Business School", job.school_raw)

    def test_sms_jsonld_graph_extracts_salary_phd_and_deadline(self):
        html = """
        <script type="application/ld+json">
        {"@graph":[{"@type":"WebSite","name":"SMS"},{"@type":"JobPosting",
         "title":"Assistant Professor Position in Strategy & Entrepreneurship","datePosted":"2026-08-11",
         "validThrough":"2026-09-10","educationRequirements":"Ph.D.",
         "hiringOrganization":{"name":"University of California, Irvine"},
         "jobLocation":{"address":{"addressLocality":"Irvine","addressRegion":"CA","addressCountry":"US"}},
         "baseSalary":{"value":{"minValue":208000,"maxValue":223000,"unitText":"YEAR"},"currency":"USD"},
         "description":"The UC Irvine Paul Merage School of Business is seeking candidates. DEADLINE: September 10, 2026."}]}
        </script>
        <h1>Assistant Professor Position in Strategy &amp; Entrepreneurship</h1>
        """
        job = SMSAdapter.parse_detail_html(html, "https://sms.careerwebsite.com/job/example/1/")
        self.assertEqual("University of California, Irvine", job.institution_raw)
        self.assertEqual("Paul Merage School of Business", job.school_raw)
        self.assertIn("208000-223000", job.salary_raw)
        self.assertEqual("September 10, 2026", job.deadline_raw)
        self.assertEqual("Ph.D.", job.extra["detail_education"])

    def test_akadeus_detail_does_not_promote_school_brand_to_university(self):
        html = """
        <h1>Multiple Full-Time Faculty Positions in Finance</h1>
        <p>Company: emlyon business school</p>
        <p>Location: France / Lyon / Paris</p>
        <p>Discipline: Finance</p>
        <p>Posted: 24/07/2026</p>
        <a href="https://galileo.wd3.myworkdayjobs.com/emlyonfac_career_site">HERE</a>
        <p>Deadline: Please apply by 15 September 2026 through the official portal and include all materials.</p>
        <p>emlyon business school invites applications for a full-time faculty position.</p>
        """
        job = AKADEUSAdapter.parse_detail_html(html, "https://akadeus.com/announcement/9845")
        self.assertEqual("emlyon business school", job.institution_raw)
        self.assertEqual("emlyon business school", job.school_raw)
        self.assertEqual("2026-07-24", normalize_source_job(job, "Global")["posted_date"])
        self.assertEqual("15 September 2026", job.deadline_raw)
        self.assertEqual("https://galileo.wd3.myworkdayjobs.com/emlyonfac_career_site", job.official_url)

    def test_blocked_sources_are_catalog_only(self):
        for adapter in (
            AACSBJobConnectionAdapter(), AMAAcademicPlacementAdapter(),
            FMAAdapter(), INFORMSAdapter(), HERCAdapter(), EFMDJobsAdapter(),
        ):
            with self.subTest(adapter=adapter.name):
                self.assertFalse(adapter.enabled)
                self.assertEqual("manual", adapter.support_status)
                self.assertEqual([], adapter.fetch().jobs)

    def test_role_and_business_boundary_still_excludes_nonfaculty_and_nonbusiness(self):
        cases = (
            ("Graduate Assistant in Accounting", "non_academic"),
            ("Financial Analyst", "non_academic"),
            ("Assistant Professor of Computer Science", "non_business"),
            ("Assistant Professor of Psychology", "non_business"),
            ("Assistant Professor of Economics", "unknown"),
            ("Research Assistant Professor of Finance", "business_discipline"),
            ("Assistant Professor of Marketing", "business_discipline"),
        )
        for title, expected in cases:
            job = SourceJob(
                source="synthetic", source_job_id=title, source_url="https://example.test/job/1",
                title_raw=title, institution_raw="Example University",
                location_raw="Columbus, Ohio, US", description_excerpt="",
                captured_at="2026-08-25T00:00:00Z",
            )
            self.assertEqual(expected, normalize_source_job(job, "Global")["business_scope"], title)


if __name__ == "__main__":
    unittest.main()
