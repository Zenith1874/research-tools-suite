# -*- coding: utf-8 -*-
"""Real advertisements that were being read as something else.

Each case below is a posting a candidate would want to see and which the
classifier dropped. The second half is the reason the first half is delicate:
the same words appear on directory pages that must stay out of the market, so
every recall fix here is paired with the exclusion it must not break.
"""

import unittest

from services.faculty_jobs_normalizer import (
    classify_disciplines, classify_faculty_market_role,
)


class RecallTests(unittest.TestCase):
    def role(self, title):
        return classify_faculty_market_role(title=title)

    def test_a_tenure_track_opening_needs_no_professor_noun(self):
        # "Tenure-track Positions in Accounting and Corporate Finance" says
        # exactly what it is without using "professor" or "lecturer".
        result = self.role("Tenure-track Positions in Accounting and Corporate Finance")
        self.assertEqual("faculty", result["role"])
        self.assertEqual(1, result["eligible"])

    def test_the_word_professorship_counts_as_professorial(self):
        # An advert that counts posts rather than describing a person.
        result = self.role("Two tenure-track Assistant professorships")
        self.assertEqual("faculty", result["role"])
        self.assertEqual(1, result["eligible"])

    def test_faculty_positions_in_a_named_field_is_one_advertisement(self):
        # EconJobMarket publishes these with a stable advertisement id. A
        # collection-page rule that fired on "faculty positions in <anything>"
        # discarded them.
        result = self.role("Faculty Positions in Finance")
        self.assertEqual("faculty", result["role"])
        self.assertEqual(1, result["eligible"])

    def test_the_field_ob_and_hr_covers_under_its_other_names(self):
        for title, expected in (
            ("Lecturer in Employment Relations", "Organizational Behavior / HR"),
            ("Assistant Professor of Industrial Relations", "Organizational Behavior / HR"),
            ("Professor of Future of Work", "Organizational Behavior / HR"),
            ("Assistant Professor of Labour Relations", "Organizational Behavior / HR"),
        ):
            self.assertEqual(expected, classify_disciplines(None, title, None)["primary"], title)


class ExclusionStillHoldsTests(unittest.TestCase):
    """The recall fixes must not let directory pages into the market."""

    def role(self, title):
        return classify_faculty_market_role(title=title)

    def test_a_bare_collection_page_is_still_not_a_job(self):
        for title in ("Faculty Jobs", "Faculty Positions", "Search Faculty Positions",
                      "Faculty vacancies", "Faculty Job Openings", "Adjunct Faculty Openings"):
            result = self.role(title)
            self.assertEqual(0, result["eligible"], title)
            self.assertEqual("listing_page", result["role"], title)

    def test_positions_in_various_departments_is_still_a_directory(self):
        # The narrowed rule keeps the genuinely generic form out.
        for title in ("Faculty Positions in Various Departments",
                      "Faculty Positions in Multiple Schools",
                      "Faculty Positions in Several Disciplines"):
            self.assertEqual(0, self.role(title)["eligible"], title)

    def test_leadership_and_student_roles_are_unaffected(self):
        self.assertEqual("academic_leadership", self.role("Dean of the Business School")["role"])
        self.assertEqual("student_role", self.role("Graduate Assistant, Accounting")["role"])
        self.assertEqual(0, self.role("Dean of the Business School")["eligible"])
        self.assertEqual(0, self.role("Graduate Assistant, Accounting")["eligible"])

    def test_a_tenure_signal_alone_does_not_promote_a_directory(self):
        # "Tenure-track and visiting faculty positions" is a page listing both,
        # not one advertisement.
        result = self.role("Tenure-track and visiting faculty positions")
        self.assertEqual(0, result["eligible"], result)


if __name__ == "__main__":
    unittest.main()
