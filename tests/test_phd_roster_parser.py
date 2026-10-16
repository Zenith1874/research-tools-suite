# -*- coding: utf-8 -*-
"""Reading people off a job-market page, and refusing to invent a zero.

The rule these tests exist to hold: a page we could not parse reports a count
of ``None``. Of the five pages the panel confirmed, exactly one is machine
readable -- Stanford's lists six candidates, Kelley's is a JavaScript shell,
and Stanford's ``/placement`` is a landing page. Writing 0 for the latter two
would convert "we cannot read this" into "this programme has nobody on the
market", which is the worst thing this dataset could claim.
"""

import unittest

from services.phd_roster_parser import (
    STATUS_JS_RENDERED, STATUS_NO_RECORDS, STATUS_PARSED, STATUS_UNRECOGNISED,
    looks_like_js_shell, parse,
)

STANFORD = "https://www.gsb.stanford.edu/programs/phd/placement/job-market-candidates"

# The real shape: a section heading, a candidate whose link points into
# /students/, and the faculty advisors listed inside the same block whose links
# point into /faculty-research/faculty/.
PAGE = """
<h2>Marketing</h2>
<div class="node node--type-phd-candidate">
  <h3 class="views-field views-field-title "><a
     href="/programs/phd/academic-experience/students/abigail-bergman">Abigail Bergman</a></h3>
  <div class="field field--name-field-faculty-advisors">
    <div class="field__label">Faculty Advisors</div>
    <div class="person person--list">
      <a href="/faculty-research/faculty/szu-chi-huang">Szu-chi Huang</a>
      <div class="person__title">Associate Professor</div>
    </div>
  </div>
</div>
<h2>Placement Directors</h2>
<h2>Organizational Behavior</h2>
<div class="node node--type-phd-candidate">
  <h3 class="views-field views-field-title "><a
     href="/programs/phd/academic-experience/students/ziwen-chen">Ziwen Chen</a></h3>
</div>
"""


class StanfordTests(unittest.TestCase):
    def result(self, html=PAGE):
        return parse(html, STANFORD, "jmc")

    def test_candidates_are_read_with_their_field(self):
        people = self.result()["people"]
        self.assertEqual(["Abigail Bergman", "Ziwen Chen"], [p["name"] for p in people])
        self.assertEqual("Marketing", people[0]["field"])

    def test_faculty_advisors_are_not_recorded_as_candidates(self):
        # The real page carries 28 advisor links against 6 candidates. The
        # school's own URL taxonomy is what separates them.
        names = [p["name"] for p in self.result()["people"]]
        self.assertNotIn("Szu-chi Huang", names)

    def test_a_candidate_heading_does_not_become_the_next_ones_field(self):
        # Candidate names are h3. Scanning h3 as section headings made Samuel
        # Pertl's field of study come out as "Abigail Bergman".
        people = self.result()["people"]
        self.assertEqual("Organizational Behavior", people[1]["field"])

    def test_a_heading_that_is_not_a_field_is_skipped(self):
        # "Placement Directors" sits between the two sections and must not be
        # filed as anyone's discipline.
        fields = {p["field"] for p in self.result()["people"]}
        self.assertNotIn("Placement Directors", fields)

    def test_a_parsed_page_reports_a_real_count(self):
        result = self.result()
        self.assertEqual(STATUS_PARSED, result["status"])
        self.assertEqual(2, result["count"])


class RefusalTests(unittest.TestCase):
    def test_a_javascript_shell_reports_no_count_rather_than_zero(self):
        # Kelley's job-market page. The list arrives after load, so the HTML
        # says nothing about how many people are on it.
        result = parse('<div class="cardloaderHolder"></div>',
                       "https://kelley.iu.edu/faculty-research/phd/placements/"
                       "job-candidates.html", "jmc")
        self.assertEqual(STATUS_JS_RENDERED, result["status"])
        self.assertIsNone(result["count"])
        self.assertIn("shell", result["note"])

    def test_a_shell_is_detected_before_a_parser_is_chosen(self):
        # Even on a host we do have a parser for: a shell is a shell.
        result = parse('<div class="__NEXT_DATA__"></div>', STANFORD, "jmc")
        self.assertEqual(STATUS_JS_RENDERED, result["status"])

    def test_a_landing_page_on_a_known_host_is_no_records_not_zero(self):
        # Stanford's /placement carries no per-person records at all.
        result = parse("<h2>Placement</h2><p>Our graduates go on to...</p>",
                       STANFORD, "jmc")
        self.assertEqual(STATUS_NO_RECORDS, result["status"])
        self.assertIsNone(result["count"])
        self.assertIn("Not evidence", result["note"])

    def test_an_unknown_host_is_unrecognised_and_says_it_is_archived(self):
        result = parse("<html><body>anything</body></html>",
                       "https://www.utep.edu/business/graduate/phd/"
                       "academic-placements.html", "placement")
        self.assertEqual(STATUS_UNRECOGNISED, result["status"])
        self.assertIsNone(result["count"])
        self.assertIn("archived", result["note"])

    def test_no_refusal_state_ever_carries_a_count(self):
        # The single invariant the module exists for.
        for html, url, kind in (
                ('<div class="ng-app"></div>', STANFORD, "jmc"),
                ("<p>nothing here</p>", STANFORD, "jmc"),
                ("<p>nothing here</p>", "https://example.edu/phd", "placement")):
            with self.subTest(url=url, html=html[:20]):
                result = parse(html, url, kind)
                self.assertNotEqual(STATUS_PARSED, result["status"])
                self.assertIsNone(result["count"])
                self.assertEqual([], result["people"])

    def test_the_shell_detector_does_not_fire_on_ordinary_markup(self):
        self.assertFalse(looks_like_js_shell(PAGE))
        self.assertTrue(looks_like_js_shell('<div data-react-class="X"></div>'))


if __name__ == "__main__":
    unittest.main()
