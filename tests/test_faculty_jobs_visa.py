# -*- coding: utf-8 -*-
"""Visa sponsorship inference.

Every phrase here is taken from a real posting in the production database on
2026-08-26. The old implementation asked ``eligible.*sponsorship`` before it
asked about refusal, so "not eligible for sponsorship" matched the affirmative
branch: all three jobs the system reported as sponsoring were wrong, and two of
them said the exact opposite. For a reader who needs sponsorship, an inverted
answer is worse than no answer, so these tests exist mainly to keep negation
winning.
"""

import unittest

from services.faculty_jobs_normalizer import infer_visa


class RefusalTests(unittest.TestCase):
    def test_not_eligible_for_sponsorship_is_a_refusal(self):
        # Wake Forest, two postings. Previously reported as explicit_yes.
        self.assertEqual("sponsorship_explicit_no", infer_visa(
            "This position is not eligible for sponsorship of non-immigrant or "
            "immigrant visa status through Wake Forest University"))

    def test_unable_to_provide_sponsorship_is_a_refusal(self):
        self.assertEqual("sponsorship_explicit_no", infer_visa(
            "At this time, Midway University is unable to provide new employment "
            "visa sponsorship."))

    def test_unable_to_take_over_sponsorship_is_a_refusal(self):
        self.assertEqual("sponsorship_explicit_no", infer_visa(
            "We are unable to sponsor or take over sponsorship of an employment "
            "Visa at this time."))

    def test_authorized_without_sponsorship_is_a_refusal(self):
        self.assertEqual("sponsorship_explicit_no", infer_visa(
            "Applicants must be authorized to work in the US without sponsorship."))

    def test_common_refusal_phrasings(self):
        for text in ("The university will not sponsor work visas.",
                     "We cannot sponsor applicants for this role.",
                     "No visa sponsorship is offered.",
                     "Sponsorship is not available for this appointment.",
                     "This employer does not sponsor employment visas."):
            self.assertEqual("sponsorship_explicit_no", infer_visa(text), text)


class OfferTests(unittest.TestCase):
    def test_plain_offers_are_explicit_yes(self):
        for text in ("The university will sponsor H-1B visas for qualified candidates.",
                     "Visa sponsorship is available for this position.",
                     "We are able to sponsor a work visa.",
                     "The successful applicant is eligible for visa sponsorship."):
            self.assertEqual("sponsorship_explicit_yes", infer_visa(text), text)


class HedgedOfferTests(unittest.TestCase):
    """A conditional offer is information, but it is not a commitment."""

    def test_may_be_available_is_not_an_explicit_yes(self):
        self.assertEqual("unclear", infer_visa(
            "Immigration/visa sponsorship may be available in very limited "
            "situations (e.g., F1/OPT)"))

    def test_case_by_case_is_not_an_explicit_yes(self):
        self.assertEqual("unclear", infer_visa(
            "Visa sponsorship is considered on a case-by-case basis."))


class PrecedenceTests(unittest.TestCase):
    def test_refusal_wins_when_both_appear(self):
        # Boilerplate can carry both; the stated constraint is what binds.
        self.assertEqual("sponsorship_explicit_no", infer_visa(
            "Visa sponsorship is available for some roles. This position is not "
            "eligible for sponsorship."))


class NoEvidenceTests(unittest.TestCase):
    def test_unrelated_sponsored_programs_office_is_not_visa_evidence(self):
        # "Office of Sponsored Programs" is research administration. The old
        # pattern matched the bare word "sponsor" and produced a false signal.
        self.assertEqual("unknown", infer_visa("Office of Sponsored Programs and Research"))
        self.assertEqual("unknown", infer_visa("Faculty Sponsor Responsibilities"))

    def test_a_bare_visa_mention_stays_unclear(self):
        self.assertEqual("unclear", infer_visa(
            "J1 visa waiver program for qualified applicants"))

    def test_silence_is_unknown(self):
        self.assertEqual("unknown", infer_visa("Teaching load is 2-2 with summer support."))
        self.assertEqual("unknown", infer_visa(""))
        self.assertEqual("unknown", infer_visa(None))


if __name__ == "__main__":
    unittest.main()
