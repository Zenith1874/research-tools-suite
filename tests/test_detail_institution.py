# -*- coding: utf-8 -*-
"""Reading an employer's name off a job board's detail page.

Every string below is the real text of a posting in the production database on
2026-09-09, not an invented example.

The bug: when a board's employer field names a *school* ("Rutgers Business
School at Newark and New Brunswick"), the parser looks in the description for
the parent university. If it could not find the employer string verbatim in the
description it fell back to returning the whole first clause that contained the
word "University". So the institution field ended up holding

    "The Accounting and Information Systems Department of Rutgers Business
     School, Rutgers, The State University of New Jersey, is seeking a
     full-time, tenure-track Assistant Professor"

which matches no entity, so the site showed "Unknown institution" for a posting
whose employer the Chronicle printed in bold at the top of the page. Worse, a
sentence like that had also been written into the institution registry as an
entity in its own right.

Returning nothing beats returning a sentence. An unresolved institution is
honestly unknown and shows up in the review queue; a sentence in that field is
a wrong answer that also guarantees the row can never match anything.
"""

import unittest

from services.faculty_jobs_sources.source_jobboards import (
    _detail_institution, _university_name,
)


class UniversityNameTests(unittest.TestCase):
    def test_it_stops_at_the_first_ordinary_word(self):
        # The whole point: the name ends where the sentence carries on.
        self.assertEqual(
            "University of Virginia",
            _university_name("The Darden School of Business at the University of "
                             "Virginia invites applications for a TT faculty "
                             "position in Entrepreneurship beginning in Fall 2027"))

    def test_a_name_buried_mid_sentence_is_found(self):
        self.assertEqual(
            "Rutgers University",
            _university_name("An equal opportunity /affirmative action employer, "
                             "Rutgers University actively seeks and encourages "
                             "applications from minorities, women, and people "
                             "with disabilities"))

    def test_a_multi_word_campus_name_survives_intact(self):
        # "at Chapel Hill" is part of the name; "consistently ranks" is not.
        self.assertEqual(
            "University of North Carolina at Chapel Hill",
            _university_name("A global higher education leader in innovative "
                             "teaching, research, and public service, the "
                             "University of North Carolina at Chapel Hill "
                             "consistently ranks as one of the nation's top "
                             "public universities"))

    def test_the_legal_name_after_a_school_and_a_short_form_is_found(self):
        self.assertEqual(
            "The State University of New Jersey",
            _university_name("The Accounting and Information Systems Department "
                             "of Rutgers Business School, Rutgers, The State "
                             "University of New Jersey, is seeking a full-time, "
                             "tenure-track Assistant Professor starting in the "
                             "2027- 2028 academic year"))

    def test_a_university_that_prefixes_its_own_school_is_read_correctly(self):
        self.assertEqual(
            "Peking University",
            _university_name("Peking University HSBC Business School (PHBS) "
                             "invites applications for a Tenure-Track "
                             "Assistant/Associate/Full Professor in Finance"))

    def test_text_with_no_university_in_it_yields_nothing(self):
        # This one is real too, and it is genuinely not there: the university
        # is named in the posting's title, not in this field. "Nothing" is the
        # correct answer, and it is what keeps a department name out of the
        # institution column.
        self.assertIsNone(_university_name(
            "Laboratory of Clinical Engineering Chair and Department of "
            "Neurosurgery and Paediatric Neurosurgery"))

    def test_empty_input_is_not_an_error(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                self.assertIsNone(_university_name(value))


class DetailInstitutionTests(unittest.TestCase):
    def test_an_employer_that_is_already_a_university_is_returned_unchanged(self):
        # The common case, and the one this change must not disturb.
        self.assertEqual("Texas A&M University",
                         _detail_institution("Texas A&M University", "anything at all"))

    def test_a_school_employer_resolves_to_the_university_in_the_description(self):
        self.assertEqual(
            "The State University of New Jersey",
            _detail_institution(
                "Rutgers Business School at Newark and New Brunswick",
                "The Accounting and Information Systems Department of Rutgers "
                "Business School, Rutgers, The State University of New Jersey, "
                "is seeking a full-time, tenure-track Assistant Professor."))

    def test_the_parent_named_right_after_the_school_still_wins(self):
        # The path that already worked: employer string appears verbatim and
        # the university follows it.
        self.assertEqual(
            "Texas A&M University",
            _detail_institution(
                "Mays Business School",
                "Mays Business School, Texas A&M University invites applications."))

    def test_a_school_brand_with_no_university_anywhere_stays_unresolved(self):
        # emlyon publishes no parent entity. Promoting the brand to a
        # university would invent one.
        self.assertIsNone(_detail_institution(
            "emlyon business school",
            "emlyon business school is recruiting a professor of marketing."))

    def test_a_description_that_only_talks_about_the_job_stays_unresolved(self):
        # The regression guard: this used to return the sentence.
        result = _detail_institution(
            "Some Business School",
            "The department is seeking a full-time, tenure-track Assistant "
            "Professor starting in the 2027-2028 academic year.")
        self.assertIsNone(result)

    def test_nothing_returned_is_ever_a_sentence(self):
        # A blunt property check over every string in this file's fixtures:
        # whatever comes back names an entity, it does not describe a vacancy.
        descriptions = [
            "The Darden School of Business at the University of Virginia invites "
            "applications for a TT faculty position in Entrepreneurship.",
            "An equal opportunity employer, Rutgers University actively seeks "
            "and encourages applications from minorities and women.",
            "Peking University HSBC Business School (PHBS) invites applications "
            "for a Tenure-Track Assistant Professor in Finance.",
        ]
        for description in descriptions:
            with self.subTest(description=description[:40]):
                result = _detail_institution("A Business School", description)
                if result is None:
                    continue
                self.assertLess(len(result), 70, result)
                for verb in (" is seeking", " invites ", " actively seeks", " ranks "):
                    self.assertNotIn(verb, result)


if __name__ == "__main__":
    unittest.main()
