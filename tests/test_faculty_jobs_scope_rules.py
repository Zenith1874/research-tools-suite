# -*- coding: utf-8 -*-
"""Scope and role rules derived from the unclassified bucket on 2026-08-26.

525 of 1,522 jobs (35%) sat in ``business_scope='unknown'``. Re-running the
classifier over them showed the bucket was not stale data but four distinct
gaps, each of which has a test here. Every example below is taken from a real
posting title in that bucket, so the rules stay auditable against the records
that motivated them.
"""

import unittest

from services.faculty_jobs_normalizer import (
    classify_business_scope,
    classify_faculty_market_role,
)


def scope(title, department=None, description=None, school=None, institution=None):
    return classify_business_scope(title=title, department=department,
                                   description=description, school=school,
                                   institution=institution)["scope"]


def role(title, description=None):
    return classify_faculty_market_role(title=title, description=description)["role"]


class PluralRoleTitleTests(unittest.TestCase):
    r"""``\bprofessor\b`` cannot match "Professors": the trailing s kills the
    word boundary, so an entire posting was dropped from the market."""

    def test_plural_professors_is_a_faculty_role(self):
        self.assertEqual("faculty", role("Assistant Professors of Management or Marketing"))
        self.assertEqual("faculty", role("Legal Studies - (2) Assistant or Associate Professors"))

    def test_plural_lecturers_is_a_faculty_role(self):
        self.assertEqual("faculty", role("Lecturers of Business (Full-Time)"))

    def test_plural_business_postings_reach_the_business_view(self):
        for title in ("Assistant Professors of Management or Marketing",
                      "2 Full Professors of Business Analytics and Decision Sciences",
                      "Lecturers of Business (Full-Time)"):
            self.assertIn(scope(title), {"business_school", "business_discipline"}, title)

    def test_singular_still_works(self):
        self.assertEqual("faculty", role("Assistant Professor"))
        self.assertEqual("faculty", role("Lecturer in Marketing"))


class BareBusinessTermTests(unittest.TestCase):
    """The list carried "business administration" but not the bare word."""

    def test_lecturer_in_business_is_a_business_posting(self):
        self.assertEqual("business_discipline", scope("Lecturer In Business"))
        self.assertEqual("business_discipline", scope("Lecturer / Senior Lecturer in Business"))
        self.assertEqual("business_discipline", scope("Lecturer in AI and Business – Teaching and Research"))

    def test_decision_sciences_and_management_science_count(self):
        self.assertEqual("business_discipline", scope("Assistant Professor of Decision Sciences"))
        self.assertEqual("business_discipline", scope("Professor of Management Science"))

    def test_a_named_non_business_field_still_outranks_the_bare_word(self):
        # The non-business check runs first; "business" must not rescue a
        # nursing or pharmacy posting advertised by a business school.
        self.assertEqual("non_business",
                         scope("Assistant Professor of Nursing",
                               school="College of Business"))
        self.assertEqual("non_business",
                         scope("Professor of Pharmacy", description="business school posting"))


class FrenchLanguagePostingTests(unittest.TestCase):
    """University Affairs publishes bilingually; English-only patterns left
    every French posting without a role, and therefore without a scope."""

    def test_french_professor_titles_are_faculty_roles(self):
        self.assertEqual("faculty", role("Sociologie du travail - Professeure régulière ou professeur régulier"))
        self.assertEqual("faculty", role("Santé publique - Professeure titulaire ou professeur titulaire"))

    def test_french_lecturer_and_dean_titles_are_recognised(self):
        self.assertEqual("faculty", role("Chargée de cours en marketing"))
        self.assertEqual("academic_leadership", role("Doyen de la faculté"))

    def test_french_non_business_fields_classify_as_non_business(self):
        self.assertEqual("non_business", scope("Santé publique - Professeure titulaire"))
        self.assertEqual("non_business", scope("Sciences forestières - Professeure régulière"))
        self.assertEqual("non_business", scope("Sociologie du travail - Professeur régulier"))


class SeniorAdministrationTests(unittest.TestCase):
    """University-wide administration is not a faculty-market vacancy. The
    hyphenated "Vice-President" never matched the whitespace-only pattern."""

    def test_hyphenated_vice_president_is_staff(self):
        self.assertEqual("staff_role", role("Provost and Vice-President Academic"))

    def test_president_and_provost_are_staff(self):
        self.assertEqual("staff_role", role("Transitional President (30-months)"))
        self.assertEqual("staff_role", role("Provost"))

    def test_they_land_as_non_academic_not_unknown(self):
        self.assertEqual("non_academic", scope("Provost and Vice-President Academic"))
        self.assertEqual("non_academic", scope("Transitional President (30-months)"))

    def test_a_dean_is_still_academic_leadership(self):
        # The role remains visible for audit/filtering, but the default product
        # is the faculty-job market rather than the academic-leadership market.
        self.assertEqual("academic_leadership", role("Dean of the Business School"))
        self.assertEqual(0, classify_faculty_market_role(
            title="Dean of the Business School")["eligible"])

    def test_chair_professor_is_a_professorial_rank_not_a_department_chair(self):
        result = classify_faculty_market_role(title="Chair Professor of Finance")
        self.assertEqual("faculty", result["role"])
        self.assertEqual(1, result["eligible"])


class UnrecognisedRoleKeepsFieldEvidenceTests(unittest.TestCase):
    """An unidentified role is not a reason to discard field evidence."""

    def test_non_business_field_beats_an_unknown_role(self):
        title = "Executive Director of Chiropractic"
        self.assertNotEqual("faculty", role(title))
        self.assertEqual("non_business", scope(title))

    def test_a_genuinely_uninformative_title_stays_unknown(self):
        # Honest ignorance is the correct answer here; nothing in the title
        # says whether this is a business posting.
        self.assertEqual("unknown", scope("Assistant Professor / Associate Professor / Professor (Two Positions)"))
        self.assertEqual("unknown", scope("KAUST Global Fellowship Program - Postdoctoral Fellowship (Call 2027)"))


class NewNonBusinessFieldTests(unittest.TestCase):
    """Fields taken from the 2026-08-26 unclassified bucket."""

    def test_observed_fields_classify_as_non_business(self):
        for title in ("Archaeology - Lecturer",
                      "Indigenous Studies - Associate Professor",
                      "Anthropology - Assistant Professor (Archaeology)",
                      "Associate Dean, Library Technology",
                      "Director, Community Planning Program (Associate or Full Professor)",
                      "Public Health - Full Professor",
                      "Health Policy - Assistant Professor, Teaching Stream",
                      "Mathematics and Statistics - Assistant Professor",
                      "Canada Research Chair, Tier II in School-Based Mental Health",
                      "Assistant Professor, MScN Nurse Practitioner Program"):
            self.assertEqual("non_business", scope(title), title)

    def test_business_analytics_is_not_swept_up_by_the_mathematics_rule(self):
        # "Business Analytics" must survive: it is the discipline most at risk
        # from a broad mathematics/statistics rule.
        self.assertIn(scope("Assistant Professor of Business Analytics"),
                      {"business_school", "business_discipline"})
        self.assertIn(scope("Professor of Applied Statistics and Business Analytics"),
                      {"business_school", "business_discipline"})

    def test_educator_track_is_not_confused_with_the_education_field(self):
        # "Educator Track" is a business-school appointment type, not K-12
        # teacher education.
        self.assertNotEqual("non_business",
                            scope("Tenure-Track and Educator Track Positions in Information Systems"))


if __name__ == "__main__":
    unittest.main()
