# -*- coding: utf-8 -*-
import unittest

from services.carnegie_vacancy_scan import (
    _merge_detail,
    parse_portal_html,
    portal_selection,
    resolve_target,
)


class CarnegieVacancyScanTests(unittest.TestCase):
    def test_opt_in_business_priority_precedes_budget_without_losing_raw_candidates(self):
        html = "".join(
            f'<a href="/jobs/biology-{index}">Assistant Professor of Biology</a>'
            for index in range(45)
        ) + '<a href="/jobs/management">Assistant Professor of Management</a>'
        default = parse_portal_html(html, "https://example.edu/jobs", max_jobs=2)
        preferred = parse_portal_html(
            html, "https://example.edu/jobs", max_jobs=2, prioritize_business=True)
        self.assertEqual("Assistant Professor of Biology", default["accepted"][0]["title"])
        self.assertEqual("Assistant Professor of Management", preferred["accepted"][0]["title"])
        self.assertEqual(46, len(preferred["candidates"]))
        self.assertEqual("Assistant Professor of Biology", preferred["candidates"][0]["title"])
        self.assertTrue(preferred["job_budget_truncated"])

    def test_business_priority_does_not_use_adjacent_business_text(self):
        html = '''<article>College of Business
            <a href="/jobs/biology">Assistant Professor of Biology</a></article>
            <a href="/jobs/information-systems">Assistant Professor of Information Systems</a>'''
        result = parse_portal_html(
            html, "https://example.edu/jobs", max_jobs=1, prioritize_business=True)
        self.assertEqual("Assistant Professor of Information Systems", result["accepted"][0]["title"])
        self.assertEqual("other_title", result["candidates"][0]["selection_priority"])

    def test_jsonld_faculty_job_is_accepted_and_student_job_is_rejected(self):
        html = """
        <html><head><title>University jobs</title>
        <script type="application/ld+json">
        [
          {"@type":"JobPosting","title":"Assistant Professor of Management",
           "url":"/jobs/management-123","description":"Teach and conduct research in management.",
           "hiringOrganization":{"name":"Example University"},
           "jobLocation":{"address":{"addressLocality":"Las Cruces","addressRegion":"NM"}},
           "datePosted":"2026-08-20","validThrough":"2026-10-01"},
          {"@type":"JobPosting","title":"Graduate Teaching Assistant",
           "url":"/jobs/student-456","description":"Assist with undergraduate courses."}
        ]
        </script></head><body>Faculty and staff employment</body></html>
        """
        result = parse_portal_html(html, "https://example.edu/careers", max_jobs=10)
        self.assertEqual(result["jobposting_jsonld"], 2)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["title"], "Assistant Professor of Management")
        self.assertEqual(result["accepted"][0]["institution"], "Example University")
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["candidates"][1]["role"], "student_role")

    def test_explicit_faculty_link_is_accepted_and_generic_link_is_not(self):
        html = """
        <html><body>
          <article><h2>Associate Professor of Accounting</h2>
            <a href="/position/associate-professor-accounting">View position</a>
          </article>
          <a href="/faculty">Faculty directory</a>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/jobs", max_jobs=10)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["extraction_method"], "explicit_job_link_url_title")
        self.assertIn("accounting", result["accepted"][0]["title"].casefold())

    def test_collection_title_is_pending_until_detail_or_url_supplies_a_role(self):
        html = """
        <html><body>
          <h2>Current Job Opportunities at Example</h2>
          <a href="/jobs/job-details.php?id=42">Job Listings</a>
          <a href="/jobs/assistant-professor-of-accounting">Current Job Opportunities at Example</a>
          <a href="/careers/faculty.html">Faculty Careers</a>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/jobs", max_jobs=10)
        self.assertEqual(len(result["accepted"]), 1)
        self.assertEqual(result["accepted"][0]["title"], "Assistant Professor Of Accounting")
        self.assertEqual(len(result["needs_detail"]), 1)
        self.assertEqual(result["needs_detail"][0]["candidate_url"], "https://example.edu/jobs/job-details.php?id=42")

    def test_navigation_and_recruitment_process_links_are_not_vacancies(self):
        html = """
        <html><body>
          <a href="/faculty-recruitment">Faculty Recruitment</a>
          <a href="/equal-employment-opportunity">Equal employment opportunity</a>
          <a href="/jobs/faculty-recruitment/">Faculty Recruitment</a>
          <a href="/careers/faculty.html">Faculty Careers</a>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/jobs", max_jobs=10)
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["needs_detail"], [])

    def test_collection_heading_does_not_promote_an_instructor_application(self):
        html = """
        <html><body>
          <section><h2>Open Instructor Positions</h2>
            <a href="/instructor-application/">Professional Education Openings</a>
          </section>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/careers", max_jobs=10)
        self.assertEqual(result["accepted"], [])

    def test_employment_path_without_role_signal_is_not_a_vacancy(self):
        html = """
        <html><body>
          <a href="/employment/adj-english.aspx">Bluffton University</a>
          <a href="/employment/faculty-development">Faculty Development</a>
          <a href="/employment/meet-our-faculty">Meet Our Faculty</a>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/careers", max_jobs=10)
        self.assertEqual(result["accepted"], [])

    def test_unhelpful_detail_heading_does_not_replace_card_role_title(self):
        candidate = {"title": "Adjunct Instructor in English"}
        detail = {
            "title": "Bluffton University",
            "role": "unknown",
            "role_confidence": "low",
            "role_reason": "No individual role title.",
        }
        merged = _merge_detail(candidate, detail)
        self.assertEqual(merged["title"], "Adjunct Instructor in English")

    def test_collection_detail_heading_does_not_replace_role_bearing_anchor(self):
        candidate = {"title": "Adjunct Instructor (Part-time)"}
        detail = {
            "title": "Job Openings: Adjunct Instructor",
            "role": "faculty",
            "role_confidence": "high",
            "role_reason": "Collection heading contains a role word.",
        }
        merged = _merge_detail(candidate, detail)
        self.assertEqual(merged["title"], "Adjunct Instructor (Part-time)")

    def test_numbered_slug_suffix_does_not_make_staff_page_a_detail_job(self):
        html = """
        <html><body>
          <a href="/job/faculty-and-student-support-associate-2/">
            Faculty and Student Support Associate
          </a>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/jobs", max_jobs=10)
        self.assertEqual(result["accepted"], [])

    def test_collection_and_application_pages_are_not_single_vacancies(self):
        html = """
        <html><body>
          <a href="/about/employment/faculty/index.htm">Full-Time Faculty</a>
          <a href="/admin/hr/jobs/help/">Lecturers/Part-time Faculty</a>
          <a href="/employment/adjunct-application/">Adjunct Professor Application</a>
          <a href="/human-resources/job-openings-adjunct-instructor/">
            Job Openings: Adjunct Instructor
          </a>
        </body></html>
        """
        result = parse_portal_html(html, "https://example.edu/jobs", max_jobs=10)
        self.assertEqual(result["accepted"], [])

    def test_portal_selection_excludes_student_and_nonemployment_faculty_pages(self):
        base = {
            "latest_page_status": "ok",
            "latest_jobposting_jsonld": 0,
            "portal_kind": "faculty_recruitment",
        }
        student = {
            **base,
            "latest_title": "Career Services for Students",
            "canonical_url": "https://example.edu/career-services",
            "discovery_evidence": "Career Services -> https://example.edu/career-services",
        }
        directory = {
            **base,
            "latest_title": "Faculty - Example University",
            "canonical_url": "https://example.edu/faculty",
            "discovery_evidence": "Faculty -> https://example.edu/faculty",
        }
        employment = {
            **base,
            "latest_title": "Faculty Employment Opportunities",
            "canonical_url": "https://example.edu/employment/faculty",
            "discovery_evidence": "Faculty Employment -> https://example.edu/employment/faculty",
        }
        self.assertFalse(portal_selection(student)["selected"])
        self.assertFalse(portal_selection(directory)["selected"])
        self.assertTrue(portal_selection(employment)["selected"])

    def test_shared_group_is_not_force_matched_to_one_target(self):
        candidate = {"institution": "Other University"}
        targets = [
            {"unitid": 1, "institution_name": "First University"},
            {"unitid": 2, "institution_name": "Second University"},
        ]
        result = resolve_target(candidate, targets)
        self.assertIsNone(result["target_unitid"])
        self.assertEqual(result["target_match_status"], "shared_group_unresolved")
        self.assertEqual(result["target_unitids"], [1, 2])

    def test_single_target_group_is_explicitly_labeled_as_registry_match(self):
        result = resolve_target(
            {"institution": None},
            [{"unitid": 7, "institution_name": "Example University"}],
        )
        self.assertEqual(result["target_unitid"], 7)
        self.assertEqual(result["target_match_status"], "single_registry_target")


if __name__ == "__main__":
    unittest.main()
