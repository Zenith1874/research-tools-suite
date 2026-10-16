# -*- coding: utf-8 -*-
"""The layer strip has to show whether a layer holds anything.

This was a real reading failure, not a hypothetical one. Each layer card
carried its name, what it answers, and a red line saying what it is *not* --
a caveat about meaning. With no count beside it, a layer holding 11,763
filings and a layer holding nothing looked identical, and a reader took the
red caveat for a status meaning "not done". They were right that two layers
were empty and wrong about what the red text meant; both were the page's
fault.

So a layer now reports how much it holds, and an empty one says why it is
empty rather than looking the same as a full one.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import academic_market_api as api
from services import academic_market_store as store
from services.faculty_jobs_service import ensure_faculty_jobs_tables


class LayerStripTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.dir.name)
        self.faculty = str(root / "faculty.db")
        ensure_faculty_jobs_tables(self.faculty)
        self.conn = sqlite3.connect(self.faculty)
        self.conn.row_factory = sqlite3.Row
        self.market = root / "market.db"
        store.ensure_tables(store.connect(self.market)).close()
        self._saved = api.MARKET_DB
        api.MARKET_DB = self.market

    def tearDown(self):
        api.MARKET_DB = self._saved
        self.conn.close()
        self.dir.cleanup()

    def layers(self):
        return {entry["layer"]: entry for entry in api._layer_order(self.conn)}

    def add_candidate(self, layer="explicit_jmc", key="abc123"):
        self.conn.execute("""
            INSERT INTO phd_program_sources (id, institution_name, program, status)
            VALUES (1,'Example University','Example PhD','confirmed')
        """)
        self.conn.execute("""
            INSERT INTO phd_page_snapshots (id, program_source_id, page_kind,
                                            market_cycle, source_url, observed_at,
                                            parser_status)
            VALUES (1,1,'jmc','2026-27','https://example.edu/jmc',
                    '2026-09-03T00:00:00Z','parsed')
        """)
        self.conn.execute("""
            INSERT INTO phd_person_observations (snapshot_id, person_key, layer,
                                                 field, confidence)
            VALUES (1,?,?,'Marketing','observed')
        """, (key, layer))
        self.conn.commit()

    def test_an_empty_layer_says_it_is_empty_and_why(self):
        placements = self.layers()["Placements"]
        self.assertFalse(placements["rows"])
        self.assertIn("empty_because", placements)
        self.assertTrue(placements["empty_because"])

    def test_a_populated_layer_reports_its_count_and_no_empty_reason(self):
        self.add_candidate()
        jmc = self.layers()["Job market candidates"]
        self.assertEqual(1, jmc["rows"])
        self.assertEqual("people", jmc["unit"])
        self.assertNotIn("empty_because", jmc)

    def test_the_same_person_seen_twice_is_one_person(self):
        # Re-reading a page must not double a layer's holding.
        self.add_candidate(key="same-key")
        self.conn.execute("""
            INSERT INTO phd_person_observations (snapshot_id, person_key, layer,
                                                 field, confidence)
            VALUES (1,'same-key','explicit_jmc','Marketing','observed')
        """)
        self.conn.commit()
        self.assertEqual(1, self.layers()["Job market candidates"]["rows"])

    def test_every_layer_still_carries_what_it_is_not(self):
        # The caveat is the point of the strip and must survive the addition.
        for name, entry in self.layers().items():
            with self.subTest(layer=name):
                self.assertTrue(entry["not"], f"{name} lost its caveat")
                self.assertTrue(entry["answers"])

    def test_the_two_sponsorship_layers_are_separate(self):
        # PERM and LCA are different steps; a combined figure would answer
        # neither question.
        layers = self.layers()
        self.assertIn("PERM", layers)
        self.assertIn("H-1B LCA", layers)
        self.assertNotEqual(layers["PERM"]["answers"], layers["H-1B LCA"]["answers"])

    def test_a_missing_market_database_reports_unknown_not_zero(self):
        # No store at all is "we have not loaded this", which must not be
        # rendered as a layer that holds nothing because it found nothing.
        api.MARKET_DB = Path(self.dir.name) / "absent.db"
        self.assertIsNone(self.layers()["PERM"]["rows"])


if __name__ == "__main__":
    unittest.main()
