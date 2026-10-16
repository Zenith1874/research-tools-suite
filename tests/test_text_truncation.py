# -*- coding: utf-8 -*-
"""The text cap, and the sentence it used to swallow.

A posting's work-authorisation wording sits at the end. That is not a guess:
of the 57 postings stored at the old 8,000-character cap, re-reading the
archived pages changed the visa verdict on six, and four of those said plainly
that sponsorship is *not* available -- the single sentence a candidate who
needs sponsorship most needs to see, cut off because it fell past character
8,000.

So the cap is a runaway guard against a parse failure dumping a whole page of
navigation into the field, and it has to stay well clear of a real posting's
length. These tests hold that, and hold the two constants together: storing
less than the parser captured throws away exactly the tail the parser was
widened for.
"""

import unittest

from services.faculty_jobs_normalizer import DESCRIPTION_EXCERPT_LIMIT, classify_visa
from services.faculty_jobs_sources.source_jobboards import DETAIL_TEXT_LIMIT

# The longest real posting observed in the archive.
LONGEST_OBSERVED = 16948


class CapTests(unittest.TestCase):
    def test_the_two_caps_are_one_value_not_two_literals(self):
        # They were kept in step by a comment asking a human to remember. The
        # normalizer now imports the parser's constant, so they cannot drift.
        self.assertIs(DESCRIPTION_EXCERPT_LIMIT, DETAIL_TEXT_LIMIT)

    def test_the_cap_clears_the_longest_posting_actually_seen(self):
        self.assertGreater(
            DETAIL_TEXT_LIMIT, LONGEST_OBSERVED * 2,
            "the cap must leave room for postings longer than any yet observed; "
            "at 8,000 it truncated 57 of them and hid four 'no sponsorship' "
            "statements")

    def test_the_cap_still_bounds_a_runaway_parse(self):
        # It is a guard, not an invitation to store whole pages: an archived
        # page averages ~114,000 bytes of HTML.
        self.assertLess(DETAIL_TEXT_LIMIT, 100000)


class SponsorshipTailTests(unittest.TestCase):
    """The concrete failure, reconstructed from the real postings."""

    # Verbatim from the four postings whose refusal was cut off.
    REFUSALS = (
        "Visa sponsorship is not available.",
        "We are unable to provide work visa sponsorship or employment "
        "authorization for this position.",
        "University sponsorship is not available for this position, including "
        "transfers of sponsorship.",
        "Employment visa sponsorship is not available for this position.",
    )

    def body_with_refusal_at_the_end(self, refusal, filler_chars=8500):
        # Padding that says nothing about immigration, so only the tail can
        # produce a verdict.
        unit = ("The department seeks candidates with a strong record of "
                "research and teaching. ")
        filler = unit * (filler_chars // len(unit) + 2)
        self.assertGreaterEqual(len(filler), filler_chars,
                                "the padding must actually reach the requested length")
        return filler[:filler_chars] + " " + refusal

    def test_each_refusal_is_read_when_the_tail_survives(self):
        for refusal in self.REFUSALS:
            with self.subTest(refusal=refusal[:40]):
                verdict = classify_visa(self.body_with_refusal_at_the_end(refusal))
                self.assertEqual("sponsorship_explicit_no", verdict["status"])

    def test_truncating_at_the_old_cap_loses_the_refusal(self):
        # The regression this exists to prevent, demonstrated rather than
        # asserted: cut at 8,000 and the same posting reads as unknown.
        for refusal in self.REFUSALS:
            with self.subTest(refusal=refusal[:40]):
                body = self.body_with_refusal_at_the_end(refusal)
                self.assertNotEqual(
                    "sponsorship_explicit_no", classify_visa(body[:8000])["status"],
                    "this test's own premise is wrong if the refusal survives 8,000")
                self.assertEqual(
                    "sponsorship_explicit_no",
                    classify_visa(body[:DETAIL_TEXT_LIMIT])["status"],
                    "the current cap must keep it")

    def test_a_refusal_beyond_the_current_cap_would_still_be_lost(self):
        # Honest about the limit that remains: this is a cap, not a promise.
        # A posting longer than the cap can still hide its tail, which is why
        # the cap sits far above any observed posting rather than just above.
        body = self.body_with_refusal_at_the_end(
            self.REFUSALS[0], filler_chars=DETAIL_TEXT_LIMIT + 100)
        self.assertNotEqual("sponsorship_explicit_no",
                            classify_visa(body[:DETAIL_TEXT_LIMIT])["status"])


if __name__ == "__main__":
    unittest.main()
