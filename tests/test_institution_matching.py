# -*- coding: utf-8 -*-
"""Employer names from official files, matched to institutions we already hold.

The rule that shapes every test here: a wrong institution carrying sponsorship
history is worse than an honest gap. So there is no fuzzy scoring, every match
records the rule that produced it, and anything unresolved is queued rather
than dropped.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import academic_market_store as store
from services import institution_matching as im


def _faculty_db(path, institutions):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE institutions (
            id INTEGER PRIMARY KEY, official_name TEXT, normalized_name TEXT,
            aliases_json TEXT)
    """)
    conn.executemany(
        "INSERT INTO institutions (id, official_name, normalized_name, aliases_json) "
        "VALUES (?,?,?,?)", institutions)
    conn.commit()
    return conn


class NormalisationTests(unittest.TestCase):
    def test_a_leading_article_is_not_part_of_the_name(self):
        self.assertEqual(im.normalize_institution("THE PENNSYLVANIA STATE UNIVERSITY"),
                         im.normalize_institution("Pennsylvania State University"))

    def test_a_hyphen_and_a_space_are_the_same_join(self):
        self.assertEqual(im.normalize_institution("Embry-Riddle Aeronautical University"),
                         im.normalize_institution("Embry Riddle Aeronautical University"))

    def test_an_ampersand_reads_as_and(self):
        self.assertEqual(im.normalize_institution("Texas A&M University"),
                         im.normalize_institution("Texas A and M University"))

    def test_a_named_school_is_stripped_from_an_employer(self):
        self.assertEqual(
            "University of Washington",
            im.core_name("University of Washington  Michael G. Foster School of Business"))

    def test_a_system_wrapper_is_stripped(self):
        self.assertEqual("University of Wisconsin",
                         im.core_name("University of Wisconsin System"))


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.dir.name)
        self.faculty = _faculty_db(root / "faculty.db", [
            (1, "Pennsylvania State University", "pennsylvania state university", "[]"),
            (2, "Embry-Riddle Aeronautical University", None, "[]"),
            # A duplicate row for the same school: the table really holds these.
            (3, "Embry-Riddle Aeronautical University", None, "[]"),
            (4, "Virginia Polytechnic Institute and State University", None, "[]"),
            (5, "University of Missouri", None, "[]"),
            (6, "Arizona State University", None, '["ASU"]'),
            (7, "University of Nebraska", None, "[]"),
        ])
        self.index = im.build_index(self.faculty)

    def tearDown(self):
        self.faculty.close()
        self.dir.cleanup()

    def assertMatch(self, name, expected_id, expected_method):
        institution_id, method = im.match_name(name, self.index)
        self.assertEqual((expected_id, expected_method), (institution_id, method), name)

    def test_an_exact_normalised_name_matches(self):
        self.assertMatch("THE PENNSYLVANIA STATE UNIVERSITY", 1, im.METHOD_EXACT)

    def test_a_recorded_alias_matches(self):
        self.assertMatch("ASU", 6, im.METHOD_ALIAS)

    def test_a_legal_holder_is_the_institution(self):
        self.assertMatch("THE CURATORS OF THE UNIVERSITY OF MISSOURI", 5, im.METHOD_LEGAL)

    def test_a_dropped_ampersand_still_matches(self):
        # DOL strips the ampersand and leaves a gap: "INSTITUTE  STATE".
        self.assertMatch("VIRGINIA POLYTECHNIC INSTITUTE  STATE UNIVERSITY", 4,
                         im.METHOD_PUNCTUATION)

    def test_a_swallowed_hyphen_still_matches(self):
        # And duplicate rows for one school must not read as a name collision:
        # treating them as one dropped this match entirely.
        self.assertMatch("EMBRYRIDDLE AERONAUTICAL UNIVERSITY", 2, im.METHOD_PUNCTUATION)

    def test_a_different_institution_is_not_matched_to_a_similar_name(self):
        # "University of Nebraska Medical Center" is not "University of
        # Nebraska". Attributing one's sponsorship history to the other is the
        # error this module exists to avoid.
        institution_id, method = im.match_name(
            "UNIVERSITY OF NEBRASKA MEDICAL CENTER", self.index)
        self.assertIsNone(institution_id)
        self.assertIsNone(method)

    def test_an_unknown_employer_does_not_match_anything(self):
        self.assertMatch("ACME MANUFACTURING CORPORATION", None, None)

    def test_an_empty_name_is_not_a_match(self):
        self.assertMatch("", None, None)

    def test_every_method_carries_a_confidence(self):
        for method in (im.METHOD_EXACT, im.METHOD_ALIAS, im.METHOD_LEGAL,
                       im.METHOD_PUNCTUATION, im.METHOD_CORE, im.METHOD_CAMPUS,
                       im.METHOD_MANUAL):
            self.assertIn(method, im.CONFIDENCE_BY_METHOD)
        self.assertEqual("verified", im.CONFIDENCE_BY_METHOD[im.METHOD_EXACT])
        self.assertEqual("derived", im.CONFIDENCE_BY_METHOD[im.METHOD_CAMPUS])


class CollisionTests(unittest.TestCase):
    def test_two_different_schools_sharing_a_variant_key_match_neither(self):
        # The variant keys are a weaker identity than a full name. These two
        # names differ only by the connector the key strips, so the key cannot
        # tell them apart and must not pick one.
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        faculty = _faculty_db(Path(directory.name) / "f.db", [
            (1, "College of the Ozarks", None, "[]"),
            (2, "College Ozarks", None, "[]"),
        ])
        self.addCleanup(faculty.close)
        index = im.build_index(faculty)
        self.assertNotIn("college ozarks", index["connectors"],
                         "a key two different names share identifies neither")
        # Exact for neither row, but sharing the connector key with both.
        institution_id, _method = im.match_name("COLLEGE OF OZARKS", index)
        self.assertIsNone(institution_id,
                          "an ambiguous key must not pick one arbitrarily")

    def test_duplicate_rows_for_one_school_still_resolve(self):
        # The other half of the same rule: the table really does hold two rows
        # for Embry-Riddle, and treating that as ambiguity lost a good match.
        directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        faculty = _faculty_db(Path(directory.name) / "f.db", [
            (7, "Embry-Riddle Aeronautical University", None, "[]"),
            (9, "Embry-Riddle Aeronautical University", None, "[]"),
        ])
        self.addCleanup(faculty.close)
        index = im.build_index(faculty)
        institution_id, method = im.match_name(
            "EMBRYRIDDLE AERONAUTICAL UNIVERSITY", index)
        self.assertEqual(7, institution_id, "the lowest id of the duplicate pair")
        self.assertEqual(im.METHOD_PUNCTUATION, method)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.dir.name)
        self.market = store.ensure_tables(store.connect(root / "market.db"))
        self.faculty = _faculty_db(root / "faculty.db", [
            (1, "Pennsylvania State University", None, "[]"),
        ])
        release_id = store.register_release(
            self.market, store.DATASET_PERM, "test", "https://example.test/p.xlsx",
            data_year=2024)
        for case, employer in (("A-1", "THE PENNSYLVANIA STATE UNIVERSITY"),
                               ("A-2", "THE PENNSYLVANIA STATE UNIVERSITY"),
                               ("A-3", "SOMEWHERE MEDICAL CENTER")):
            self.market.execute("""
                INSERT INTO perm_faculty_cases
                  (case_number, fiscal_year, employer_name, faculty_evidence, release_id)
                VALUES (?,?,?,?,?)
            """, (case, 2024, employer, im.METHOD_EXACT, release_id))
        self.market.commit()

    def tearDown(self):
        self.market.close()
        self.faculty.close()
        self.dir.cleanup()

    def test_matched_cases_are_stamped_and_unmatched_ones_are_queued(self):
        result = im.match_perm_employers(self.market, self.faculty)
        self.assertEqual(1, result["employers_matched"])
        self.assertEqual(1, result["employers_queued"])
        self.assertEqual(2, result["cases_matched"])
        stamped = self.market.execute(
            "SELECT institution_id FROM perm_faculty_cases WHERE case_number='A-1'"
        ).fetchone()["institution_id"]
        self.assertEqual(1, stamped)

    def test_an_unmatched_employer_keeps_its_case_count(self):
        # The queue is ordered by what it costs to leave unresolved.
        im.match_perm_employers(self.market, self.faculty)
        row = self.market.execute(
            "SELECT external_name, occurrences FROM institution_match_queue").fetchone()
        self.assertIn("MEDICAL CENTER", row["external_name"])
        self.assertEqual(1, row["occurrences"])

    def test_nothing_unmatched_is_silently_dropped(self):
        im.match_perm_employers(self.market, self.faculty)
        employers = self.market.execute(
            "SELECT COUNT(DISTINCT employer_name) FROM perm_faculty_cases").fetchone()[0]
        accounted = (self.market.execute(
            "SELECT COUNT(*) FROM institution_matches").fetchone()[0]
            + self.market.execute(
            "SELECT COUNT(*) FROM institution_match_queue").fetchone()[0])
        self.assertEqual(employers, accounted)

    def test_rerunning_does_not_duplicate_rows(self):
        im.match_perm_employers(self.market, self.faculty)
        im.match_perm_employers(self.market, self.faculty)
        self.assertEqual(1, self.market.execute(
            "SELECT COUNT(*) FROM institution_matches").fetchone()[0])
        self.assertEqual(1, self.market.execute(
            "SELECT COUNT(*) FROM institution_match_queue").fetchone()[0])

    def test_the_report_separates_strong_matches_from_weak_ones(self):
        im.match_perm_employers(self.market, self.faculty)
        report = im.match_report(self.market)
        self.assertIn(im.METHOD_EXACT, report["matches_by_method"])
        self.assertIn("should be reviewed", report["confidence_note"])


if __name__ == "__main__":
    unittest.main()
