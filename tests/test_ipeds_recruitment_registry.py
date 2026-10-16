# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
import csv
from pathlib import Path

from bs4 import BeautifulSoup

from services.ipeds_recruitment_registry import (
    canonical_host,
    DISCOVERY_RULE_VERSION,
    discover_portal_candidates,
    export_registry_csv,
    normalize_public_url,
    registry_connect,
    registry_summary,
    seed_registry,
)


class IPEDSRecruitmentRegistryTests(unittest.TestCase):
    def test_normalizes_bare_ipeds_website_and_deduplicates_host(self):
        self.assertEqual("https://www.example.edu/", normalize_public_url("www.example.edu/"))
        self.assertEqual("example.edu", canonical_host("https://www.example.edu/"))
        self.assertEqual("https://example.edu/jobs?q=faculty", normalize_public_url(
            "https://example.edu/jobs?q=faculty#top", keep_query=True
        ))

    def test_discovery_rejects_student_and_directory_links(self):
        html = """
        <html><head><title>University</title></head><body>
          <a href="/student-careers">Student Careers</a>
          <a href="/career-services">Career Services</a>
          <a href="/faculty-directory">Faculty Directory</a>
          <a href="/BIOS/expertise_search.cfm">Expertise &amp; Faculty Search</a>
          <a href="/career-development/apprenticeship">Apprenticeship to Degree</a>
          <a href="/news/story-about-careers">Read Story Thanks to a successful career in steel manufacturing</a>
          <a href="/about/jobs/employee-benefits-information">Employee Benefits</a>
          <a href="/directory/alpha/A">Directory</a>
          <a href="/featuredevents?eventid=42">Fall Career Fair</a>
          <a href="/programs/human-resource-management">Human Resources Management</a>
          <a href="/human-resources/policies">Notice of Non-Discrimination</a>
          <a href="/hr/forms">Forms</a>
          <a href="/hr/retirement-plans">Retirement Plans</a>
          <a href="/hr/staff">Human Resources Staff</a>
          <a href="/media/press-releases/nsfgrant.html">NSF CAREER GRANT</a>
          <a href="/academics/schools-and-colleges">Explore Academic Opportunities</a>
          <a href="https://stories.university.edu/career-story">A Career Story</a>
          <a href="/student-life/career-and-professional-success">Career and Professional Success</a>
          <a href="/online/graduate-certificates.html">Graduate Certificates</a>
          <a href="/2026/05/27/career-story">Career Story</a>
          <a href="/site-search?q=human+resources">Search</a>
          <a href="/admissions/recruitment">Recruitment Team</a>
          <a href="/join-us">Join us</a>
          <a href="/hrsys">HR system</a>
          <a href="https://careerconnections.university.edu/">Career Connections Center</a>
          <a href="/hr/careers">Faculty and Staff Jobs</a>
          <a href="https://www2.university.edu/jobs">Jobs on the University subdomain</a>
          <a href="/faculty-positions">Faculty Positions</a>
          <a href="https://university.wd1.myworkdayjobs.com/en-US/University"
             >Search University Jobs</a>
          <a href="/about">About</a>
        </body></html>
        """
        candidates = discover_portal_candidates(
            BeautifulSoup(html, "html.parser"), "https://university.edu/"
        )
        urls = {item["canonical_url"] for item in candidates}
        self.assertIn("https://university.edu/faculty-positions", urls)
        self.assertIn("https://university.wd1.myworkdayjobs.com/en-US/University", urls)
        self.assertNotIn("https://university.edu/student-careers", urls)
        self.assertNotIn("https://university.edu/career-services", urls)
        self.assertNotIn("https://university.edu/faculty-directory", urls)
        self.assertNotIn("https://university.edu/BIOS/expertise_search.cfm", urls)
        self.assertNotIn("https://university.edu/career-development/apprenticeship", urls)
        self.assertNotIn("https://university.edu/news/story-about-careers", urls)
        self.assertNotIn("https://university.edu/about/jobs/employee-benefits-information", urls)
        self.assertNotIn("https://university.edu/directory/alpha/A", urls)
        self.assertNotIn("https://university.edu/featuredevents?eventid=42", urls)
        self.assertNotIn("https://university.edu/programs/human-resource-management", urls)
        self.assertNotIn("https://university.edu/human-resources/policies", urls)
        self.assertNotIn("https://university.edu/hr/forms", urls)
        self.assertNotIn("https://university.edu/hr/retirement-plans", urls)
        self.assertNotIn("https://university.edu/hr/staff", urls)
        self.assertNotIn("https://university.edu/media/press-releases/nsfgrant.html", urls)
        self.assertNotIn("https://university.edu/academics/schools-and-colleges", urls)
        self.assertNotIn("https://stories.university.edu/career-story", urls)
        self.assertNotIn("https://university.edu/student-life/career-and-professional-success", urls)
        self.assertNotIn("https://university.edu/online/graduate-certificates.html", urls)
        self.assertNotIn("https://university.edu/2026/05/27/career-story", urls)
        self.assertNotIn("https://university.edu/site-search?q=human+resources", urls)
        self.assertNotIn("https://university.edu/admissions/recruitment", urls)
        self.assertNotIn("https://university.edu/join-us", urls)
        self.assertNotIn("https://university.edu/hrsys", urls)
        self.assertNotIn("https://careerconnections.university.edu/", urls)
        self.assertIn("https://university.edu/hr/careers", urls)
        self.assertIn("https://www2.university.edu/jobs", urls)
        kinds = {item["portal_kind"] for item in candidates}
        self.assertIn("faculty_recruitment", kinds)
        self.assertIn("external_ats", kinds)

    def test_seed_preserves_institution_grain_and_groups_shared_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / "source.db"
            registry_path = tmp_path / "registry.db"
            source = sqlite3.connect(source_path)
            source.execute("""
                CREATE TABLE ipeds_institutions (
                    data_year INTEGER, unitid INTEGER, institution_name TEXT,
                    state TEXT, control INTEGER, carnegie_basic INTEGER,
                    website TEXT, release_id INTEGER
                )
            """)
            source.executemany("""
                INSERT INTO ipeds_institutions VALUES (?,?,?,?,?,?,?,?)
            """, [
                (2023, 1, "Alpha University", "NM", 1, 15, "www.alpha.edu/", 11),
                (2023, 2, "Alpha Digital University", "NM", 1, 16, "https://alpha.edu/", 11),
                (2023, 3, "Beta University", "TX", 2, 17, "www.beta.edu/", 11),
                (2023, 4, "No Website University", "CA", 2, 17, None, 11),
                (2023, 5, "Territory University", "PR", 1, 15, "www.pr.edu/", 11),
            ])
            source.commit()
            source.close()

            result = seed_registry(source_path, registry_path)
            self.assertEqual(4, result["target_count"])
            self.assertEqual(2, result["website_group_count"])
            self.assertEqual(1, result["missing_official_website"])
            self.assertEqual(1, result["duplicate_website_records"])

            conn = registry_connect(registry_path)
            self.assertEqual(4, conn.execute(
                "SELECT COUNT(*) FROM institution_recruitment_targets"
            ).fetchone()[0])
            self.assertEqual(2, conn.execute(
                "SELECT COUNT(*) FROM institution_recruitment_websites"
            ).fetchone()[0])
            self.assertEqual(2, conn.execute(
                "SELECT linked_institution_count FROM institution_recruitment_websites "
                "WHERE website_group_key='alpha.edu'"
            ).fetchone()[0])
            self.assertEqual(0, conn.execute(
                "SELECT COUNT(*) FROM registry_runs WHERE status!='ok'"
            ).fetchone()[0])
            conn.close()

            summary = registry_summary(registry_path)
            self.assertEqual(4, summary["targets"])
            self.assertEqual(2, summary["website_groups"])
            self.assertEqual(0, summary["observations"])
            self.assertEqual(DISCOVERY_RULE_VERSION, summary["rule_version"])

            export_path = tmp_path / "registry.csv"
            export_result = export_registry_csv(registry_path, export_path)
            self.assertEqual(4, export_result["rows"])
            with export_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(4, len(rows))
            self.assertEqual("not_scanned", rows[0]["latest_status"])
            missing = next(row for row in rows if row["institution_name"] == "No Website University")
            self.assertEqual("missing_official_website", missing["latest_status"])


if __name__ == "__main__":
    unittest.main()
