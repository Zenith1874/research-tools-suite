# -*- coding: utf-8 -*-
"""A hiring cycle is an academic year, and it comes from when the job starts.

The previous derivation glued together the year we first saw a posting and the
last two digits of its start year, producing labels like ``2026-24``. Those are
not cycles: they are not sortable, they do not name a market, and two postings
for the same Fall 2027 start landed in different buckets depending on when we
happened to crawl them.
"""

import datetime
import unittest

from services.faculty_jobs_market_cycle import (
    UNKNOWN, current_cycle, cycle_for_start_year, cycle_label, derive,
    parse_expected_start,
)


class LabelTests(unittest.TestCase):
    def test_a_cycle_is_named_for_the_academic_year_it_opens(self):
        self.assertEqual("2028-29", cycle_label(2028))
        self.assertEqual("2026-27", cycle_label(2026))

    def test_the_turn_of_the_century_keeps_two_digits(self):
        self.assertEqual("2099-00", cycle_label(2099))

    def test_recruiting_runs_the_year_before_the_start(self):
        # A Fall 2029 job is advertised from summer 2028 and filled by spring
        # 2029. Calling that the 2029 cycle would split one market in half.
        self.assertEqual((2028, "2028-29"), cycle_for_start_year(2029))


class ParseTests(unittest.TestCase):
    def assertCycle(self, expected_label, **kwargs):
        self.assertEqual(expected_label, derive(**kwargs)["market_cycle_label"])

    def test_fall_2029(self):
        self.assertCycle("2028-29", text="The appointment begins Fall 2029.")

    def test_academic_year_2029_30(self):
        self.assertCycle("2028-29", text="Position begins in academic year 2029-30.")

    def test_august_2029(self):
        self.assertCycle("2028-29", text="Start date: August 2029.")

    def test_spring_start_belongs_to_the_same_cycle_as_the_fall_before_it(self):
        # Spring 2029 is advertised in autumn 2028, the same cycle as Fall 2029.
        self.assertCycle("2028-29", text="The position begins Spring 2029.")

    def test_an_explicit_start_year_field_wins(self):
        result = derive(start_year=2027, text="ignore this 2099 mention")
        self.assertEqual(2027, result["expected_start_year"])
        self.assertEqual("2026-27", result["market_cycle_label"])

    def test_unknown_stays_unknown(self):
        for text in (None, "", "Salary commensurate with experience.",
                     "A tenure-track position in Finance."):
            self.assertCycle(UNKNOWN, text=text)

    def test_a_review_date_is_not_a_start_date(self):
        # The single most common way to guess wrong: a posting full of dates
        # that says nothing about when the job begins.
        result = derive(text="Review of applications begins November 1, 2026.")
        self.assertEqual(UNKNOWN, result["market_cycle_label"])
        self.assertIsNone(result["expected_start_year"])

    def test_a_term_without_a_year_is_not_enough(self):
        result = derive(text="The appointment begins in the Fall.")
        self.assertEqual(UNKNOWN, result["market_cycle_label"])
        self.assertIn("without a year", result["market_cycle_reason"])

    def test_unknown_is_never_quietly_filed_as_the_current_cycle(self):
        reason = derive(text="No start stated.")["market_cycle_reason"]
        self.assertIn("not placed in the current cycle", reason.casefold())

    def test_every_answer_explains_itself(self):
        reason = derive(text="Begins Fall 2029.")["market_cycle_reason"]
        self.assertIn("2029", reason)
        self.assertIn("2028-29", reason)

    def test_the_parser_reports_why_it_could_not_answer(self):
        _year, reason = parse_expected_start("Applications close December 1.")
        self.assertIn("bare date", reason)


class ProductionMisreadTests(unittest.TestCase):
    """Every case here misfired against real rows before the proximity rule.

    A term and a year found anywhere in a 4,000-character excerpt were paired,
    so "Fall semester" plus a job ID produced a start in 2000. Three production
    rows landed in cycle 1999-00 that way.
    """

    def start(self, text, reference_year=2026):
        return derive(text=text, reference_year=reference_year)["expected_start_year"]

    def test_a_job_id_is_not_a_start_year(self):
        self.assertIsNone(self.start(
            "Dean, College of Allied Health Sciences Job ID: 296430 "
            "Full/Part Time: Full Time. Fall courses are assigned."))

    def test_a_word_count_is_not_a_start_year(self):
        # "(250-300 words)" beside a Fall mention produced Fall 2000.
        self.assertIsNone(self.start(
            "Statement of purpose describing your motivation (250-300 words). "
            "Fall semester teaching load is 2-2."))

    def test_review_of_applications_is_the_committee_not_the_job(self):
        # The commonest sentence in an academic advertisement.
        self.assertIsNone(self.start("Review of applications begins November 1, 2026."))
        self.assertIsNone(self.start("Applications will be reviewed beginning in 2026."))

    def test_a_grant_year_range_is_not_an_academic_year(self):
        self.assertIsNone(self.start(
            "Grant history 2024-2025 funded the lab. Fall teaching expected."))

    def test_a_stale_posting_keeps_the_start_it_states(self):
        # Still up in 2026, saying 2024-2025. The posting is stale; that is a
        # fact about the posting, not a reason to discard what it says.
        self.assertEqual(2024, self.start(
            "Disciplines: Management. Starting Date: 2024-2025"))

    def test_an_implausible_year_is_rejected_even_with_a_term(self):
        self.assertIsNone(self.start("The position begins Fall 1999."))


class CurrentCycleTests(unittest.TestCase):
    def test_the_market_year_turns_over_in_july(self):
        self.assertEqual((2026, "2026-27"), current_cycle(datetime.date(2026, 8, 15)))
        self.assertEqual((2025, "2025-26"), current_cycle(datetime.date(2026, 3, 15)))
        self.assertEqual((2026, "2026-27"), current_cycle(datetime.date(2026, 7, 1)))
        self.assertEqual((2025, "2025-26"), current_cycle(datetime.date(2026, 6, 30)))


if __name__ == "__main__":
    unittest.main()
