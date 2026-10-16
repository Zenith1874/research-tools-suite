# -*- coding: utf-8 -*-
"""Linking business schools to the A* corpus as tier evidence.

Tiers were 920 T4 / 291 Unclassified / 1 T3 / 1 T2 / 0 T1. The ladder is
evidence-driven and the only evidence at scale was AACSB accreditation, which
lands a school on T4 by definition. This adds the one research signal the suite
actually owns -- observed A* publication output -- without inventing a ranking.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.faculty_jobs_school_service import (
    ASTAR_FOOTPRINT_LABEL, astar_footprint_for_school, classify_business_school)
from services.faculty_jobs_service import ensure_faculty_jobs_tables
from services.faculty_school_astar_evidence import (
    EVIDENCE_TYPE,
    EVIDENCE_TYPE_BELOW_THRESHOLD,
    HIGH_RESEARCH_MIN_ARTICLES,
    astar_institution_index,
    normalize_institution,
    refresh_astar_school_evidence,
)

NOW = "2026-08-26T00:00:00Z"


def astar_db(rows):
    """rows: (article_id, institution_openalex_id, display_name, ror)"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE astar_articles (id INTEGER PRIMARY KEY, publication_year INTEGER,"
                 " affiliation_status TEXT)")
    conn.execute("CREATE TABLE astar_article_affiliations (article_id INTEGER,"
                 " institution_openalex_id TEXT, institution_display_name TEXT,"
                 " institution_ror TEXT)")
    seen = set()
    for article_id, openalex_id, name, ror in rows:
        if article_id not in seen:
            conn.execute("INSERT INTO astar_articles (id,publication_year,affiliation_status)"
                         " VALUES (?,2025,'recorded')", (article_id,))
            seen.add(article_id)
        conn.execute("INSERT INTO astar_article_affiliations VALUES (?,?,?,?)",
                     (article_id, openalex_id, name, ror))
    conn.commit()
    return conn


class NormalizeTests(unittest.TestCase):
    def test_punctuation_case_and_leading_the_are_ignored(self):
        self.assertEqual(normalize_institution("The University of Hong Kong"),
                         normalize_institution("University of Hong Kong"))
        self.assertEqual(normalize_institution("Texas A&M University"),
                         normalize_institution("Texas A and M University"))

    def test_distinct_schools_do_not_collide(self):
        self.assertNotEqual(normalize_institution("University of California, Berkeley"),
                            normalize_institution("University of California, Davis"))


class IndexTests(unittest.TestCase):
    def test_the_variant_with_the_most_articles_wins(self):
        conn = astar_db([(1, "I1", "Tulane University", "01abc"),
                         (2, "I1", "Tulane University", "01abc"),
                         (3, "I2", "Tulane Univ", "01xyz")])
        index = astar_institution_index(conn)
        self.assertEqual(("01abc", "I1", 2), index[normalize_institution("Tulane University")])
        conn.close()


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "INSERT INTO institutions (id,official_name,normalized_name,is_current,created_at,"
            "updated_at) VALUES (1,'Wharton University','wharton university',1,?,?)", (NOW, NOW))
        self.conn.execute(
            "INSERT INTO business_schools (id,institution_id,official_name,normalized_name,"
            "is_current,created_at,updated_at) VALUES (1,1,'The Wharton School','wharton school',"
            "1,?,?)", (NOW, NOW))
        self.conn.execute(
            "INSERT INTO school_evidence (school_id,evidence_type,value,source_name,"
            "source_url,verified_at,confidence) VALUES (1,'AACSB','accredited','AACSB directory',"
            "'https://www.aacsb.edu/accredited',?,'High')", (NOW,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def link(self, article_count):
        rows = [(i, "I1", "Wharton University", "01wh") for i in range(1, article_count + 1)]
        astar = astar_db(rows)
        try:
            stats = refresh_astar_school_evidence(self.conn, astar)
        finally:
            astar.close()
        self.conn.commit()
        return stats

    def evidence_types(self):
        return {row[0] for row in self.conn.execute(
            "SELECT evidence_type FROM school_evidence WHERE school_id=1")}

    def test_the_ror_and_openalex_id_are_stored_on_the_institution(self):
        self.link(30)
        row = self.conn.execute(
            "SELECT ror, openalex_institution_id FROM institutions WHERE id=1").fetchone()
        self.assertEqual("01wh", row["ror"])
        self.assertEqual("I1", row["openalex_institution_id"])

    def test_a_substantial_footprint_is_recorded_but_does_not_move_the_tier(self):
        """The footprint is shown on its own, not folded into the tier.

        Promoting a school on a derived count from a partially backfilled corpus
        is a judgement about what a tier means, so it is opt-in only.
        """
        self.link(HIGH_RESEARCH_MIN_ARTICLES + 5)
        self.assertIn(EVIDENCE_TYPE, self.evidence_types())
        self.assertEqual("T4", classify_business_school(self.conn, 1)["tier"],
                         "accreditation alone is still T4")

    def test_the_tier_signal_can_be_opted_into(self):
        self.link(HIGH_RESEARCH_MIN_ARTICLES + 5)
        with mock.patch.dict(os.environ, {"FACULTY_ASTAR_TIER_SIGNAL": "1"}):
            self.assertEqual("T2", classify_business_school(self.conn, 1)["tier"])
        self.assertEqual("T4", classify_business_school(self.conn, 1)["tier"],
                         "the default must stay off")

    def test_the_footprint_is_exposed_with_its_coverage(self):
        self.link(40)
        footprint = astar_footprint_for_school(self.conn, 1)
        self.assertEqual(ASTAR_FOOTPRINT_LABEL, footprint["label"])
        self.assertEqual(40, footprint["articles"])
        self.assertIsNotNone(footprint["coverage_pct"])
        self.assertTrue(footprint["meets_research_threshold"])
        self.assertFalse(footprint["counts_toward_tier"])
        self.assertIn("does not affect this school", footprint["explanation"])
        self.assertIn("not an official ranking", footprint["explanation"])

    def test_the_explanation_says_so_when_the_signal_is_opted_into(self):
        self.link(40)
        with mock.patch.dict(os.environ, {"FACULTY_ASTAR_TIER_SIGNAL": "1"}):
            footprint = astar_footprint_for_school(self.conn, 1)
        self.assertTrue(footprint["counts_toward_tier"])
        self.assertIn("FACULTY_ASTAR_TIER_SIGNAL=1", footprint["explanation"])

    def test_an_unlinked_school_reports_no_footprint_rather_than_zero(self):
        self.assertIsNone(astar_footprint_for_school(self.conn, 1),
                          "no link is not the same claim as zero articles")

    def test_a_small_footprint_is_recorded_but_does_not_promote(self):
        # One incidental co-authorship must not make a school research-intensive.
        self.link(2)
        self.assertIn(EVIDENCE_TYPE_BELOW_THRESHOLD, self.evidence_types())
        self.assertNotIn(EVIDENCE_TYPE, self.evidence_types())
        self.assertEqual("T4", classify_business_school(self.conn, 1)["tier"],
                         "accreditation alone is still T4")

    def test_t1_still_requires_phd_evidence(self):
        self.link(500)
        with mock.patch.dict(os.environ, {"FACULTY_ASTAR_TIER_SIGNAL": "1"}):
            self.assertEqual("T2", classify_business_school(self.conn, 1)["tier"],
                             "publication evidence alone must not reach the top tier")
        self.conn.execute(
            "INSERT INTO school_evidence (school_id,evidence_type,value,source_name,"
            "source_url,verified_at,confidence) VALUES (1,'business_phd_program','PhD in Management',"
            "'School page','https://example.edu/phd',?,'High')", (NOW,))
        self.conn.commit()
        self.assertEqual("T3", classify_business_school(self.conn, 1)["tier"],
                         "by default the footprint is not a research signal, so PhD + "
                         "accreditation is T3")
        with mock.patch.dict(os.environ, {"FACULTY_ASTAR_TIER_SIGNAL": "1"}):
            self.assertEqual("T1", classify_business_school(self.conn, 1)["tier"])

    def test_the_coverage_caveat_travels_with_the_evidence(self):
        self.link(40)
        note = self.conn.execute(
            "SELECT notes FROM school_evidence WHERE evidence_type=?", (EVIDENCE_TYPE,)).fetchone()[0]
        self.assertIn("coverage", note)
        self.assertIn("not an official ranking", note)

    def test_an_unmatched_school_gets_no_evidence_and_no_tier_change(self):
        astar = astar_db([(1, "I9", "Some Other University", "01zz")])
        try:
            stats = refresh_astar_school_evidence(self.conn, astar)
        finally:
            astar.close()
        self.conn.commit()
        self.assertEqual(0, stats["institutions_linked"])
        self.assertEqual({"AACSB"}, self.evidence_types())
        self.assertEqual("T4", classify_business_school(self.conn, 1)["tier"])

    def test_rerunning_preserves_historical_evidence_without_accumulating_current_rows(self):
        self.link(30)
        self.link(40)
        rows = self.conn.execute(
            "SELECT value,is_current,valid_to FROM school_evidence "
            "WHERE evidence_type=? ORDER BY id", (EVIDENCE_TYPE,)).fetchall()
        self.assertEqual(2, len(rows), "the replaced observation remains available for provenance")
        self.assertEqual(["30", "40"], [row["value"] for row in rows])
        self.assertEqual([0, 1], [row["is_current"] for row in rows])
        self.assertIsNotNone(rows[0]["valid_to"])

    def test_a_manual_override_still_wins(self):
        self.link(500)
        self.conn.execute(
            "INSERT INTO school_tier_overrides (school_id,tier,reason,source_url,"
            "created_at,updated_at) VALUES (1,'T4','Local judgement recorded by hand',"
            "'https://example.edu/note',?,?)", (NOW, NOW))
        self.conn.commit()
        result = classify_business_school(self.conn, 1)
        self.assertEqual("T4", result["tier"])
        self.assertTrue(result["manual_override"])


if __name__ == "__main__":
    unittest.main()
