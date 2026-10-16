# -*- coding: utf-8 -*-
"""Country detection must not read US state evidence as a country.

Every wrong value here was observed in the production database on 2026-08-27:
two live Albuquerque postings were recorded as Mexican because "New Mexico"
ends in "Mexico"; University of Denver sat in Colombia and University of
Tennessee in Tunisia because a bare state code was accepted as an ISO country
code. Guessing a country is worse than leaving it Unknown, because the country
filter then hides real jobs and surfaces wrong ones.
"""

import unittest

from services.faculty_jobs_normalizer import (
    _STATE_COUNTRY_CODE_COLLISIONS,
    _alias_match_is_a_different_place,
    country_from_text,
    parse_location,
)


class StateNameCollisionTests(unittest.TestCase):
    def test_new_mexico_is_not_mexico(self):
        for text in ("University of New Mexico", "New Mexico",
                     "Albuquerque, New Mexico", "New Mexico State University"):
            self.assertIsNone(country_from_text(text), text)

    def test_a_real_mexican_location_still_resolves(self):
        self.assertEqual("MX", country_from_text("Tec de Monterrey, Mexico"))
        self.assertEqual("MX", country_from_text("Mexico City, Mexico"))

    def test_both_present_does_not_suppress_the_real_country(self):
        # A posting naming New Mexico and Mexico is still evidence of Mexico.
        self.assertEqual("MX", country_from_text("New Mexico office and Mexico City campus"))

    def test_continent_names_are_still_excluded(self):
        self.assertIsNone(country_from_text("South America regional office"))

    def test_the_helper_only_fires_when_every_hit_is_qualified(self):
        self.assertTrue(_alias_match_is_a_different_place("Mexico", "university of new mexico"))
        self.assertFalse(_alias_match_is_a_different_place("Mexico", "monterrey, mexico"))


class BareStateCodeTests(unittest.TestCase):
    def test_the_collision_set_covers_the_observed_codes(self):
        for code in ("co", "tn", "in", "ar", "ma", "mo", "nl", "pe", "il", "de", "id"):
            self.assertIn(code, _STATE_COUNTRY_CODE_COLLISIONS, code)

    def test_a_bare_colliding_code_is_not_a_country(self):
        # "CO" is Colorado far more often than Colombia in this corpus.
        for code in ("CO", "TN", "IN", "AR", "MA", "PE", "MO", "IL", "NL", "DE", "ID"):
            self.assertIsNone(country_from_text(code), code)

    def test_a_non_colliding_bare_code_still_works(self):
        self.assertEqual("GB", country_from_text("GB"))
        self.assertEqual("CL", country_from_text("CL"))
        self.assertEqual("TH", country_from_text("TH"))

    def test_a_spelled_out_country_beats_the_collision_guard(self):
        self.assertEqual("CO", country_from_text("Bogota, Colombia"))
        self.assertEqual("TN", country_from_text("Tunis, Tunisia"))
        self.assertEqual("IN", country_from_text("Mumbai, India"))
        self.assertEqual("PE", country_from_text("Lima, Peru"))


class LocationRegressionTests(unittest.TestCase):
    def test_us_state_cards_resolve_to_the_united_states(self):
        for raw, city, state in (("Albuquerque, NM", "Albuquerque", "NM"),
                                 ("Denver, CO", "Denver", "CO"),
                                 ("Knoxville, TN", "Knoxville", "TN"),
                                 ("Boise, ID", "Boise", "ID"),
                                 ("Dover, DE", "Dover", "DE"),
                                 ("Hickam AFB, HI", "Hickam AFB", "HI")):
            location = parse_location(raw, "US")
            self.assertEqual("US", location["country_code"], raw)
            self.assertEqual(city, location["city"], raw)
            self.assertEqual(state, location["state_province"], raw)

    def test_shenzhen_campus_hint_does_not_relabel_parent_university(self):
        shenzhen = parse_location(
            None, None,
            institution_text="The Chinese University of Hong Kong, Shenzhen",
        )
        self.assertEqual("CN", shenzhen["country_code"])
        parent = parse_location(
            None, None,
            institution_text="The Chinese University of Hong Kong",
        )
        self.assertNotEqual("CN", parent["country_code"])

    def test_the_institution_name_alone_does_not_invent_a_country(self):
        location = parse_location(None, None, institution_text="University of New Mexico")
        self.assertNotEqual("MX", location["country_code"],
                            "an institution name is not a country claim")


class BoardRegionTests(unittest.TestCase):
    """A job board's registered region is not the job's country.

    AIS is registered as United States and carried "Management of Information
    Systems Professor (open rank) at NovaSBE", which is in Portugal. Stamping it
    US hid it from a Portugal filter and surfaced it under the wrong country.
    """

    def test_a_board_default_region_does_not_become_the_country(self):
        location = parse_location("Remote", "United States", region_is_board_default=True)
        self.assertIsNone(location["country_code"])
        self.assertEqual("source_region_only_unknown_country", location["location_evidence"])

    def test_a_country_the_posting_exposes_is_still_evidence(self):
        location = parse_location("Remote", "GB")
        self.assertEqual("GB", location["country_code"])
        self.assertEqual("source_region_country", location["location_evidence"])

    def test_a_real_location_always_wins_over_the_board_region(self):
        for raw, expected in (("Lisbon, Portugal", "PT"), ("Austin, TX", "US"),
                              ("Dublin", "IE")):
            location = parse_location(raw, "United States", region_is_board_default=True)
            self.assertEqual(expected, location["country_code"], raw)


if __name__ == "__main__":
    unittest.main()
