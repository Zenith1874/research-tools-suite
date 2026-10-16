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

import json
import unittest

from unittest.mock import patch

from services import faculty_jobs_visa_llm as visa_llm
from services.faculty_jobs_detail_enrichment import ENRICHABLE, _derived_updates
from services.faculty_jobs_normalizer import (
    VISA_BLOCKING_STATUSES, VISA_STATUSES, VISA_SUPPORTIVE_STATUSES,
    classify_visa, infer_visa, visa_pathways,
)
from services.faculty_jobs_sources.source_jobboards import _parse_public_detail


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



class HardEligibilityBarTests(unittest.TestCase):
    """A citizenship requirement is not silence, and it is not a refusal either.

    Both used to read `unknown`, which sorted the one posting that definitively
    excludes an international reader together with the 3,082 that simply never
    mentioned the subject.
    """

    def test_a_citizenship_requirement_has_its_own_answer(self):
        self.assertEqual("citizenship_required", classify_visa(
            "U.S. citizenship is required due to federal export control "
            "regulations.")["status"])

    def test_citizen_or_permanent_resident_is_a_different_bar(self):
        # A green-card holder can accept this one and not the one above.
        self.assertEqual("citizen_or_pr_required", classify_visa(
            "Applicants must be a U.S. citizen or permanent resident.")["status"])

    def test_a_citizen_of_the_world_is_not_a_citizenship_requirement(self):
        self.assertEqual("unknown", classify_visa(
            "The department seeks a citizen of the world with broad "
            "interests.")["status"])


class InvertedAnswerTests(unittest.TestCase):
    """The failure this field keeps having: an affirmative read out of a refusal.

    Found by replaying the nine production rows that already had a verdict, not
    by any test above -- which is why the replay is worth keeping as a habit.
    """

    MINNESOTA = ("***Please note this position is not eligible for H-1B or "
                 "Green Card sponsorship.***")

    def test_a_refusal_naming_the_programmes_is_still_a_refusal(self):
        # "not eligible for sponsorship" was covered; naming H-1B and Green
        # Card in between broke the pattern, and the green-card rule then read
        # "Green Card sponsorship" as support -- the exact opposite.
        self.assertEqual("sponsorship_explicit_no",
                         classify_visa(self.MINNESOTA)["status"])

    def test_sponsor_does_not_match_inside_sponsorship(self):
        # The green-card pattern ended without a word boundary.
        self.assertNotEqual("permanent_residency_supported",
                            classify_visa("No Green Card sponsorship is offered.")["status"])

    def test_a_negation_in_the_sentence_vetoes_an_affirmative(self):
        # A phrasing neither pattern anticipated must land on "we could not
        # tell", never on the opposite of what the posting said.
        for text in ("We are not able to support permanent residency petitions.",
                     "The department cannot sponsor an H-1B for this role."):
            self.assertNotIn(classify_visa(text)["status"],
                             ("permanent_residency_supported",
                              "sponsorship_explicit_yes"), text)


class FundingNotImmigrationTests(unittest.TestCase):
    """In academia "sponsorship" is more often money than a work visa.

    Both cases here appeared on live pages during the first real enrichment
    run. The second is the dangerous one: an offer of scholarship money read
    as an offer to sponsor a work visa, on the field where an inverted answer
    costs a candidate an application.
    """

    def test_scholarship_sponsorship_is_not_a_visa_mention(self):
        self.assertEqual("unknown", classify_visa(
            "Lecturer for Scholarship Sponsorship in Digital Innovation")["status"])

    def test_an_offer_of_scholarship_money_is_not_an_offer_to_sponsor(self):
        self.assertEqual("unknown", classify_visa(
            "Scholarship sponsorship is available for doctoral students.")["status"])

    def test_sponsored_research_and_funders_are_not_immigration(self):
        for text in ("Office of Sponsored Programs and Research",
                     "Faculty Sponsor Responsibilities",
                     "The post is sponsored by the Wellcome Trust.",
                     "Industry sponsorship funds the laboratory."):
            self.assertEqual("unknown", classify_visa(text)["status"], text)

    def test_a_sentence_naming_a_visa_still_counts_despite_money_words(self):
        # The rule disregards funding language, not the whole sentence.
        self.assertEqual("sponsorship_explicit_yes", classify_visa(
            "We offer scholarship sponsorship and will also sponsor an H-1B visa."
        )["status"])


class PermanentResidencyTests(unittest.TestCase):
    """Green-card support is a larger commitment than a work visa."""

    def test_support_for_permanent_residency_is_recognised(self):
        for wording in (
            "The successful candidate will be supported for permanent residency.",
            "The university will support the EB-1B outstanding researcher petition.",
            "We will file for permanent labor certification (PERM) after appointment.",
        ):
            self.assertEqual("permanent_residency_supported",
                             classify_visa(wording)["status"], wording)

    def test_it_outranks_a_bare_work_visa_offer(self):
        # A posting that offers both has made the larger commitment.
        self.assertEqual("permanent_residency_supported", classify_visa(
            "The University will sponsor an H-1B visa and will support the "
            "subsequent permanent residency petition.")["status"])


class EvidenceTests(unittest.TestCase):
    """visa_text was NULL on all 5,038 rows because nothing ever produced one."""

    def test_an_answer_carries_the_sentence_it_came_from(self):
        verdict = classify_visa(
            "Applicants must hold a PhD. This position is not eligible for visa "
            "sponsorship. Review begins in November.")
        self.assertIn("not eligible for visa sponsorship", verdict["evidence"])
        self.assertNotIn("Review begins", verdict["evidence"],
                         "the quote is the sentence, not the paragraph")

    def test_unknown_carries_no_evidence(self):
        self.assertIsNone(classify_visa("Teaching load is 2-2.")["evidence"])

    def test_the_legacy_entry_point_still_returns_a_bare_string(self):
        self.assertEqual("sponsorship_explicit_no",
                         infer_visa("This role offers no visa sponsorship."))


class PathwayTests(unittest.TestCase):
    """Programmes are recorded when named, never inferred."""

    def test_named_programmes_are_recorded(self):
        named = visa_pathways("We sponsor H-1B and may pursue an EB-2 NIW.")
        self.assertIn("h1b", named)
        self.assertIn("eb2", named)

    def test_nothing_is_read_out_of_an_ordinary_posting(self):
        # An employer picks an EB category after hiring. Deriving one from a
        # job advertisement would be invention.
        self.assertEqual([], visa_pathways(
            "A tenure-track position at a research university with a strong "
            "record of placing graduates."))

    def test_a_named_programme_alone_is_unclear_rather_than_unknown(self):
        # No "visa" or "sponsorship" in this sentence at all.
        self.assertEqual("unclear", classify_visa(
            "J-1 exchange visitor status may be arranged.")["status"])

    def test_the_vocabularies_are_disjoint(self):
        self.assertFalse(set(VISA_BLOCKING_STATUSES) & set(VISA_SUPPORTIVE_STATUSES))
        for status in VISA_BLOCKING_STATUSES + VISA_SUPPORTIVE_STATUSES:
            self.assertIn(status, VISA_STATUSES)


class _FakeRow(dict):
    """sqlite3.Row exposes .keys(); the code under test relies on that."""

    def keys(self):
        return list(super().keys())


class BodyCaptureTests(unittest.TestCase):
    """The field read 0.0% because the text was missing, not the parser.

    Sponsorship wording sits at the end of a posting, next to the EEO
    paragraph. The detail parser kept the first 2,000 characters, so it kept
    precisely the part that never mentions it.
    """

    PAGE = ("<html><body><h1>Assistant Professor of Finance</h1>"
            "<p>Employer: Example State University</p>"
            + "<p>Filler about the department and its facilities.</p>" * 60
            + "<p>The University will sponsor an H-1B visa for the successful "
              "candidate.</p></body></html>")

    def body(self):
        return _parse_public_detail(
            self.PAGE, "example", "https://example.edu/1")["description"]

    def test_the_parser_now_reaches_the_sponsorship_line(self):
        self.assertGreater(len(self.body()), 2000)
        self.assertEqual("sponsorship_explicit_yes", classify_visa(self.body())["status"])

    def test_the_old_cap_would_have_returned_unknown(self):
        self.assertEqual("unknown", classify_visa(self.body()[:2000])["status"])

    def test_the_pass_declares_the_fields_it_fills(self):
        for field in ("description_excerpt", "visa_status", "visa_text", "visa_pathways"):
            self.assertIn(field, ENRICHABLE, field)

    def test_a_detail_read_fills_visa_over_a_listing_blurb(self):
        fields = _parse_public_detail(self.PAGE, "example", "https://example.edu/1")
        row = _FakeRow({
            "job_id": 1, "title_raw": "Assistant Professor of Finance",
            "department": "Finance", "deadline_date": None, "deadline_mode": None,
            "official_url": None, "salary_raw": None,
            "description_excerpt": "Assistant Professor of Finance.",
            "visa_status": "unknown", "visa_text": None, "visa_pathways": None,
        })
        observed, updates = _derived_updates(row, fields, reference_date=None)
        self.assertIn("visa_status", observed)
        self.assertEqual("sponsorship_explicit_yes", updates["visa_status"])
        self.assertIn("sponsor an H-1B", updates["visa_text"])
        self.assertIn("h1b", updates["visa_pathways"])

    def test_a_shorter_page_never_replaces_a_fuller_stored_body(self):
        fields = _parse_public_detail(
            "<html><body><h1>T</h1><p>Short.</p></body></html>",
            "example", "https://example.edu/2")
        row = _FakeRow({
            "job_id": 2, "title_raw": "T", "department": None,
            "deadline_date": None, "deadline_mode": None,
            "official_url": None, "salary_raw": None,
            "description_excerpt": "x" * 3000,
            "visa_status": "unknown", "visa_text": None, "visa_pathways": None,
        })
        _observed, updates = _derived_updates(row, fields, reference_date=None)
        self.assertNotIn("description_excerpt", updates)


class ModelAssistTests(unittest.TestCase):
    """A verdict that cannot be traced to the posting is discarded whole."""

    BODY = ("The Department of Finance invites applications for a tenure-track "
            "position. " * 8 + "The University will sponsor an H-1B visa for the "
            "successful candidate. Applications close in November.")

    def reply(self, payload):
        return patch.object(visa_llm, "_anthropic_call",
                            return_value=json.dumps(payload))

    def setUp(self):
        self.env = patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_a_grounded_answer_is_kept(self):
        with self.reply({"status": "sponsorship_explicit_yes",
                         "quote": "The University will sponsor an H-1B visa for "
                                  "the successful candidate.",
                         "pathways": ["h1b"]}):
            verdict = visa_llm.classify(self.BODY)
        self.assertEqual("sponsorship_explicit_yes", verdict["status"])
        self.assertIn("h1b", verdict["pathways"])

    def test_an_invented_quote_discards_the_whole_verdict(self):
        # The failure this check exists for: a plausible sentence the posting
        # never contained. The status goes with it -- a claim we cannot trace
        # is a claim about some other posting.
        with self.reply({"status": "sponsorship_explicit_yes",
                         "quote": "The University sponsors all international "
                                  "faculty without exception.",
                         "pathways": ["h1b"]}):
            verdict = visa_llm.classify(self.BODY)
        self.assertEqual("unknown", verdict["status"])
        self.assertIsNone(verdict["evidence"])
        self.assertIn("does not appear", verdict["rejected"])

    def test_a_paraphrase_is_not_a_quote(self):
        with self.reply({"status": "sponsorship_explicit_yes",
                         "quote": "The university will sponsor an H1B for the "
                                  "chosen applicant.",
                         "pathways": []}):
            self.assertEqual("unknown", visa_llm.classify(self.BODY)["status"])

    def test_an_unrecognised_status_is_refused(self):
        with self.reply({"status": "probably_fine", "quote": None, "pathways": []}):
            verdict = visa_llm.classify(self.BODY)
        self.assertEqual("unknown", verdict["status"])
        self.assertIn("not one of the allowed values", verdict["rejected"])

    def test_pathways_are_re_derived_rather_than_trusted(self):
        with self.reply({"status": "sponsorship_explicit_yes",
                         "quote": "The University will sponsor an H-1B visa for "
                                  "the successful candidate.",
                         "pathways": ["h1b", "eb1", "eb2", "perm"]}):
            self.assertEqual(["h1b"], visa_llm.classify(self.BODY)["pathways"])

    def test_a_short_body_is_never_sent(self):
        with patch.object(visa_llm, "_anthropic_call") as call:
            verdict = visa_llm.classify("Assistant Professor of Finance.")
        call.assert_not_called()
        self.assertIn("too short", verdict["rejected"])

    def test_without_a_key_it_refuses_rather_than_guessing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(visa_llm.available())
            with self.assertRaises(visa_llm.VisaLLMUnavailable):
                visa_llm.classify(self.BODY)


if __name__ == "__main__":
    unittest.main()
