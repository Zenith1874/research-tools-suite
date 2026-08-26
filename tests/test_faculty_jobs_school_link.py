# -*- coding: utf-8 -*-
"""Linking a school-less job to its institution's only business school.

Half the default market had no school entity, so no tier could render on those
cards even where the school's tier was known. The link is safe only when it is
unambiguous, and it must never be mistaken for the posting having named a school
-- that would promote the job to business_school scope on evidence we invented.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    _DERIVED_SCHOOL_CONTEXTS,
    _link_jobs_to_unique_school,
    ensure_faculty_jobs_tables,
)

NOW = "2026-08-26T00:00:00Z"


class SchoolLinkTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def institution(self, institution_id, name):
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,is_current,created_at,"
            "updated_at) VALUES (?,?,?,1,?,?)",
            (institution_id, name, name.casefold(), NOW, NOW))

    def school(self, school_id, institution_id, name, tier='Unclassified'):
        self.conn.execute(
            "INSERT INTO business_schools (id,institution_id,official_name,normalized_name,"
            "business_research_tier,is_current,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?)",
            (school_id, institution_id, name, name.casefold(), tier, NOW, NOW))

    def job(self, job_id, institution_id, scope="business_discipline", school_id=None,
            context="unknown"):
        self.conn.execute(
            "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,"
            "school_id,school_evidence_context,business_scope,derived_quality,status,"
            "first_seen_at,last_seen_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,'accepted','open',?,?,?,?)",
            (job_id, f"k{job_id}", "Assistant Professor of Marketing",
             "assistant professor of marketing", institution_id, school_id, context, scope,
             NOW, NOW, NOW, NOW))

    def linked(self, job_id):
        return self.conn.execute(
            "SELECT school_id, school_evidence_context FROM jobs WHERE id=?", (job_id,)).fetchone()

    def test_a_single_business_school_is_linked(self):
        self.institution(1, "University of South Carolina")
        self.school(10, 1, "Darla Moore School of Business", tier="T2")
        self.job(100, 1)
        self.conn.commit()
        stats = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["linked"])
        row = self.linked(100)
        self.assertEqual(10, row["school_id"])
        self.assertEqual("institution_unique_school", row["school_evidence_context"])

    def test_two_schools_at_one_institution_are_left_alone(self):
        # Picking one would be a guess, and the wrong school's tier would render.
        self.institution(2, "Large University")
        self.school(20, 2, "College of Business")
        self.school(21, 2, "School of Management")
        self.job(200, 2)
        self.conn.commit()
        stats = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["linked"])
        self.assertEqual(1, stats["ambiguous_skipped"])
        self.assertIsNone(self.linked(200)["school_id"])

    def test_an_institution_with_no_business_school_is_left_alone(self):
        self.institution(3, "Small College")
        self.job(300, 3)
        self.conn.commit()
        stats = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["linked"])
        self.assertIsNone(self.linked(300)["school_id"])

    def test_an_existing_link_is_not_replaced(self):
        self.institution(4, "Another University")
        self.school(40, 4, "Business School")
        self.school(41, 4, "Other School")
        self.conn.execute(
            "UPDATE business_schools SET is_current=0 WHERE id=41")
        self.job(400, 4, school_id=40, context="posting")
        self.conn.commit()
        _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        row = self.linked(400)
        self.assertEqual(40, row["school_id"])
        self.assertEqual("posting", row["school_evidence_context"],
                         "a posting-level context must survive")

    def test_a_non_business_job_is_not_linked(self):
        self.institution(5, "Mixed University")
        self.school(50, 5, "College of Business")
        self.job(500, 5, scope="non_business")
        self.conn.commit()
        stats = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["linked"])
        self.assertIsNone(self.linked(500)["school_id"])

    def test_name_variants_of_one_school_resolve_to_the_fullest_name(self):
        """Tulane carried both "A. B. Freeman School of Business" and
        "Freeman School of Business" as current rows for the same unit."""
        self.institution(7, "Tulane University")
        self.school(70, 7, "Freeman School of Business")
        self.school(71, 7, "A. B. Freeman School of Business", tier="T2")
        self.job(700, 7)
        self.conn.commit()
        stats = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["linked"])
        self.assertEqual(71, self.linked(700)["school_id"])

    def test_a_prepended_programme_label_is_still_the_same_school(self):
        # Observed: "Full-time Fully On-Campus Farmer School of Business".
        self.institution(8, "Miami University")
        self.school(80, 8, "Farmer School of Business")
        self.school(81, 8, "Full-time Fully On-Campus Farmer School of Business")
        self.job(800, 8)
        self.conn.commit()
        self.assertEqual(1, _link_jobs_to_unique_school(self.conn)["linked"])

    def test_two_genuinely_different_schools_are_never_collapsed(self):
        # Virginia really does have both Darden and McIntire.
        self.institution(9, "University of Virginia")
        self.school(90, 9, "Darden School of Business")
        self.school(91, 9, "McIntire School of Commerce")
        self.job(900, 9)
        self.conn.commit()
        stats = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(0, stats["linked"])
        self.assertEqual(1, stats["ambiguous_skipped"])
        self.assertIsNone(self.linked(900)["school_id"])

    def test_the_derived_context_is_not_posting_evidence(self):
        """The guard that keeps a link we made from becoming scope evidence."""
        self.assertIn("institution_unique_school", _DERIVED_SCHOOL_CONTEXTS)
        self.assertIn("aacsb_roster_target", _DERIVED_SCHOOL_CONTEXTS)
        self.assertNotIn("posting", _DERIVED_SCHOOL_CONTEXTS)
        self.assertNotIn("structured_posting", _DERIVED_SCHOOL_CONTEXTS)

    def test_running_twice_links_nothing_new(self):
        self.institution(6, "Repeat University")
        self.school(60, 6, "Business School")
        self.job(600, 6)
        self.conn.commit()
        _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        second = _link_jobs_to_unique_school(self.conn)
        self.conn.commit()
        self.assertEqual(0, second["considered"])


if __name__ == "__main__":
    unittest.main()
