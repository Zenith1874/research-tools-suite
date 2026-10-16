# -*- coding: utf-8 -*-
"""An institution is only created from something that is plausibly a school.

Every rejected string here was a real ``institutions.official_name`` row in the
production database on 2026-08-27: AKADEUS equal-opportunity paragraphs of 669
and 723 characters, a POMS sentence fragment, and an Inside Higher Ed "Not
Specified" string. Minting an entity from posting prose invents a school that
does not exist and then pollutes the directory, the country filter and every
count derived from institutions. Leaving the job without an institution is the
honest outcome.

The length bound is evidence-based: in this corpus the 99th percentile
institution name is 78 characters and the longest legitimate one is 96.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    _MAX_INSTITUTION_NAME_LENGTH,
    _is_plausible_institution_name,
    _retire_contaminated_institutions,
    ensure_faculty_jobs_tables,
)

NOW = "2026-08-27T00:00:00Z"

OBSERVED_CONTAMINATION = [
    "Ohio Not Specified Miami University",
    "Management. University",
    "Business Analytics. University",
    "Technology Management. University",
    ("that does not discriminate against employees based on their race, religion, "
     "gender, sexual orientation or gender identity, age, disability, or any other "
     "characteristic unrelated to job performance."),
    ("and is committed to fostering diversity and inclusion in its academic community. "
     "Women candidates, candidates from underrepresented groups, and international "
     "applicants are especially encouraged to apply."),
    ("An equal opportunity /affirmative action employer, Rutgers University actively "
     "seeks and encourages applications"),
]

REAL_INSTITUTIONS = [
    "Tulane University",
    "Miami University",
    "St. John's University",
    "Universidad EAFIT, School of Business and Economics",
    "Veterinärmedizinische Universität Wien (University of Veterinary Medicine Vienna)",
    "School of Professional Education and Executive Development, The Hong Kong Polytechnic University",
    "Boston University Chobanian & Avedisian School of Medicine, Pharmacology-Physiology & Biophysics",
    "College of Management, National Kaohsiung University of Science and Technology-First Campus",
]


class PlausibilityTests(unittest.TestCase):
    def test_every_observed_contamination_is_rejected(self):
        for name in OBSERVED_CONTAMINATION:
            self.assertFalse(_is_plausible_institution_name(name), name[:60])

    def test_every_real_institution_is_accepted(self):
        for name in REAL_INSTITUTIONS:
            self.assertTrue(_is_plausible_institution_name(name), name[:60])

    def test_the_length_bound_clears_the_longest_real_name(self):
        longest_real = max(len(name) for name in REAL_INSTITUTIONS)
        self.assertLess(longest_real, _MAX_INSTITUTION_NAME_LENGTH,
                        "the bound must not reject a name this corpus actually contains")

    def test_a_period_inside_a_real_name_is_not_a_fragment(self):
        # The fragment rule keys on a bare organisation word after a full stop.
        self.assertTrue(_is_plausible_institution_name("St. John's University"))
        self.assertTrue(_is_plausible_institution_name("Washington Univ. in St. Louis"))
        self.assertFalse(_is_plausible_institution_name("Marketing. College"))

    def test_empty_and_none(self):
        self.assertFalse(_is_plausible_institution_name(""))
        self.assertFalse(_is_plausible_institution_name(None))


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.add_institution(1, "Tulane University")
        self.add_institution(2, OBSERVED_CONTAMINATION[4])
        self.add_job(100, 1)
        self.add_job(101, 2)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add_institution(self, institution_id, name):
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,is_current,created_at,"
            "updated_at) VALUES (?,?,?,1,?,?)",
            (institution_id, name, name.casefold()[:120], NOW, NOW))

    def add_job(self, job_id, institution_id):
        self.conn.execute(
            "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,"
            "business_scope,derived_quality,faculty_market_eligible,status,"
            "first_seen_at,last_seen_at,created_at,updated_at) "
            "VALUES (?,?,?,?,?, 'business_school','accepted',1,'open',?,?,?,?)",
            (job_id, f"k{job_id}", "Assistant Professor", "assistant professor",
             institution_id, NOW, NOW, NOW, NOW))

    def test_only_the_contaminated_row_is_retired(self):
        stats = _retire_contaminated_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(1, stats["retired"])
        self.assertEqual(1, self.conn.execute(
            "SELECT is_current FROM institutions WHERE id=1").fetchone()["is_current"])
        self.assertEqual(0, self.conn.execute(
            "SELECT is_current FROM institutions WHERE id=2").fetchone()["is_current"])

    def test_the_job_is_detached_not_reassigned(self):
        _retire_contaminated_institutions(self.conn)
        self.conn.commit()
        row = self.conn.execute(
            "SELECT institution_id, school_id FROM jobs WHERE id=101").fetchone()
        self.assertIsNone(row["institution_id"],
                          "guessing a replacement school would repeat the original mistake")
        self.assertIsNone(row["school_id"])
        self.assertEqual(1, self.conn.execute(
            "SELECT institution_id FROM jobs WHERE id=100").fetchone()["institution_id"])

    def test_nothing_is_deleted(self):
        _retire_contaminated_institutions(self.conn)
        self.conn.commit()
        self.assertEqual(2, self.conn.execute(
            "SELECT COUNT(*) FROM institutions").fetchone()[0])
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def test_both_actions_are_audited(self):
        _retire_contaminated_institutions(self.conn)
        self.conn.commit()
        actions = {row[0] for row in self.conn.execute(
            "SELECT action FROM faculty_job_repair_audit")}
        self.assertIn("retire_contaminated_institution", actions)
        self.assertIn("detach_job_from_contaminated_institution", actions)

    def test_running_twice_retires_nothing_further(self):
        _retire_contaminated_institutions(self.conn)
        self.conn.commit()
        second = _retire_contaminated_institutions(self.conn)
        self.conn.commit()
        self.assertEqual({"retired": 0, "jobs_detached": 0}, second)


if __name__ == "__main__":
    unittest.main()
