# -*- coding: utf-8 -*-
"""Four layers, kept apart.

The easiest way to invent a candidate supply is to count enrolled students. A
programme listing twenty doctoral students has twenty doctoral students; how
many of them are competing this year is a different question that only the
school can answer, and most schools do not.
"""

import sqlite3
import unittest

from services.phd_pipeline import (
    LAYER_CURRENT, LAYER_EXPLICIT_JMC, LAYER_PLACEMENT, LAYERS, PAGE_JMC,
    PAGE_PLACEMENT, PAGE_ROSTER, classify_layer, ensure_tables, market_window,
    person_key, pipeline_summary, record_snapshot, register_program,
)


class LayerTests(unittest.TestCase):
    def test_only_the_schools_own_words_reach_explicit_jmc(self):
        for text in ("2026-27 Job Market Candidates",
                     "Our students on the job market this year",
                     "Placement Candidate: Finance"):
            layer, _why = classify_layer(text, page_kind=PAGE_JMC)
            self.assertEqual(LAYER_EXPLICIT_JMC, layer, text)

    def test_a_roster_supports_enrolment_and_nothing_stronger(self):
        # Even on a page a person filed as a JMC page: the words decide.
        layer, why = classify_layer("Current Doctoral Students", page_kind=PAGE_JMC)
        self.assertEqual(LAYER_CURRENT, layer)
        self.assertIn("not market participation", why)

    def test_a_placement_page_is_its_own_layer(self):
        layer, _why = classify_layer("Recent graduate placements",
                                     page_kind=PAGE_PLACEMENT)
        self.assertEqual(LAYER_PLACEMENT, layer)


class WindowTests(unittest.TestCase):
    def test_a_window_never_collapses_to_a_year(self):
        # No page in the audit sample published an expected graduation date.
        # A point estimate would read as something the school stated.
        start, end = market_window(2023)
        self.assertEqual((2027, 2030), (start, end))
        self.assertNotEqual(start, end)

    def test_no_entry_year_means_no_window(self):
        self.assertEqual((None, None), market_window(None))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_a_programme_is_registered_with_the_urls_a_person_found(self):
        # There is no URL convention: five of twelve guessed URLs 404'd in the
        # audit, so the registry holds discovered addresses.
        program_id = register_program(
            self.conn, "Example State University", "Management PhD",
            field="Management", jmc_url="https://example.edu/phd/job-market",
            placement_url="https://example.edu/phd/placement", carnegie_basic=15)
        row = self.conn.execute(
            "SELECT jmc_url, carnegie_basic FROM phd_program_sources WHERE id=?",
            (program_id,)).fetchone()
        self.assertEqual("https://example.edu/phd/job-market", row["jmc_url"])
        self.assertEqual(15, row["carnegie_basic"])

    def test_re_registering_updates_rather_than_duplicating(self):
        register_program(self.conn, "Example State University", "Management PhD",
                         jmc_url="https://example.edu/a")
        register_program(self.conn, "Example State University", "Management PhD",
                         jmc_url="https://example.edu/b")
        rows = self.conn.execute(
            "SELECT jmc_url FROM phd_program_sources").fetchall()
        self.assertEqual(1, len(rows))
        self.assertEqual("https://example.edu/b", rows[0]["jmc_url"])

    def test_an_unknown_page_kind_is_refused(self):
        program_id = register_program(self.conn, "Example", "PhD")
        with self.assertRaises(ValueError):
            record_snapshot(self.conn, program_id, "brochure", "2026-27",
                            "https://example.edu/x")

    def test_a_snapshot_records_capture_before_any_parsing(self):
        # The urgency is capture: JMC pages are replaced each autumn and the
        # previous cohort is not archived anywhere.
        program_id = register_program(self.conn, "Example", "PhD")
        snapshot_id = record_snapshot(
            self.conn, program_id, PAGE_JMC, "2026-27",
            "https://example.edu/jmc", http_status=200, content_hash="a" * 64)
        row = self.conn.execute(
            "SELECT parser_status, content_hash FROM phd_page_snapshots WHERE id=?",
            (snapshot_id,)).fetchone()
        self.assertEqual("captured", row["parser_status"])
        self.assertEqual("a" * 64, row["content_hash"])

    def test_capturing_updates_when_the_programme_was_last_checked(self):
        program_id = register_program(self.conn, "Example", "PhD")
        record_snapshot(self.conn, program_id, PAGE_ROSTER, "2026-27",
                        "https://example.edu/students")
        self.assertIsNotNone(self.conn.execute(
            "SELECT last_checked FROM phd_program_sources WHERE id=?",
            (program_id,)).fetchone()["last_checked"])


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_tables(self.conn)
        program_id = register_program(self.conn, "Example", "Management PhD")
        self.snapshot = record_snapshot(self.conn, program_id, PAGE_ROSTER,
                                        "2026-27", "https://example.edu/students")
        for name, layer in (("A", LAYER_CURRENT), ("B", LAYER_CURRENT),
                            ("C", LAYER_EXPLICIT_JMC)):
            self.conn.execute("""
                INSERT INTO phd_person_observations
                  (snapshot_id, person_key, display_name, layer, confidence)
                VALUES (?,?,?,?,'observed')
            """, (self.snapshot, person_key("Example", name), name, layer))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_layers_are_reported_separately(self):
        summary = pipeline_summary(self.conn, "2026-27")
        self.assertEqual(2, summary["by_layer"][LAYER_CURRENT]["people"])
        self.assertEqual(1, summary["by_layer"][LAYER_EXPLICIT_JMC]["people"])
        for layer in LAYERS:
            self.assertIn(layer, summary["by_layer"])

    def test_the_summary_refuses_to_offer_a_total(self):
        summary = pipeline_summary(self.conn, "2026-27")
        self.assertNotIn("candidate_supply", summary)
        self.assertNotIn("total_candidates", summary)
        self.assertIn("must not be summed", summary["not_a_supply"])

    def test_coverage_is_stated_alongside_the_counts(self):
        # Three students at one captured programme is not a market reading.
        summary = pipeline_summary(self.conn, "2026-27")
        self.assertEqual(1, summary["programs_registered"])
        self.assertEqual(1, summary["programs_captured"])
        self.assertIn("2026-27", summary["coverage_note"])

    def test_a_person_key_does_not_carry_the_name(self):
        key = person_key("Example", "Jane Doe")
        self.assertNotIn("jane", key.casefold())
        self.assertEqual(key, person_key("example", "  Jane Doe "))


if __name__ == "__main__":
    unittest.main()
