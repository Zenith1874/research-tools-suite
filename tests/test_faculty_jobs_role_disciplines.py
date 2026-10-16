"""Role-subject regressions from actual faculty-market classification errors."""
import unittest

from services.faculty_jobs_normalizer import classify_disciplines


class RoleDisciplineTests(unittest.TestCase):
    def test_marketing_role_does_not_inherit_is_from_its_department(self):
        value = classify_disciplines("Business Administration & Information Systems",
            "Assistant Professor, Marketing - Department of Business Administration & Information Systems",
            "HigherEdJobs category: Marketing and Sales")
        self.assertEqual("Marketing", value["primary"])
        self.assertNotIn("Information Systems / MIS", value["secondary"])

    def test_non_target_subjects_stay_out_of_management(self):
        for title, expected in (("Assistant Professor of Economics", "Economics"),
            ("Instructor - Economics", "Economics"),
            ("Assistant Professor - Department of Business Law #27-01", "Business Law / Ethics"),
            ("Adjunct Faculty - School of Business, Public Law", "Business Law / Ethics"),
            ("Assistant Professor - Economic Analysis & Policy - Haas School of Business", "Economics")):
            self.assertEqual(expected, classify_disciplines(None, title, "School of Business")["primary"], title)

    def test_general_business_pool_does_not_inherit_economics_from_school_name(self):
        value = classify_disciplines(None,
            "Part-Time Lecturer Pool, Argyros College of Business and Economics, Academic Year 2026-2027", "")
        # This is a multidisciplinary pool; the unit name alone is insufficient
        # to narrow it to Economics. The business pool remains discoverable.
        self.assertEqual("Management", value["primary"])

    def test_generic_title_still_uses_department_evidence(self):
        value = classify_disciplines("Information Systems", "Assistant Professor", "Marketing and strategy")
        self.assertEqual("Information Systems / MIS", value["primary"])

    def test_acronym_has_word_boundaries(self):
        value = classify_disciplines(None, "Assistant Professor of Management", "admissions mission")
        self.assertEqual("Management", value["primary"])


if __name__ == "__main__":
    unittest.main()
