# -*- coding: utf-8 -*-
"""Full-text search over posting bodies.

Two things are defended here.

The index must not drift from the table. It is an external-content FTS5 index,
so `jobs` holds the text and the index points at it -- but external-content
indexes are updated by hand-written triggers, and the classic bug is a delete
trigger written with NEW values instead of OLD, which leaves the old terms
behind so a posting keeps matching text it no longer contains.

And a hit must not be mistaken for a fact. A posting matching `sponsorship`
may be offering it or refusing it; the derived `visa_status` is the answer, and
search is only a way to find rows worth reading.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_search import (
    INDEXED_COLUMNS, ensure_tables, index_status, integrity_ok, rebuild,
    sanitise, search,
)
from services.faculty_jobs_service import ensure_faculty_jobs_tables

NOW = "2026-09-04T00:00:00Z"


class SanitiseTests(unittest.TestCase):
    def test_words_become_quoted_and_anded(self):
        self.assertEqual('"tenure" AND "track"', sanitise("tenure track"))

    def test_punctuation_a_person_types_does_not_become_a_syntax_error(self):
        # A search box that errors on brackets or an apostrophe is worse than
        # one that cannot express a boolean.
        for text in ("assistant professor (finance)", "dean's office",
                     '"unbalanced', "a - b", "col:value", "star*"):
            with self.subTest(text=text):
                expression = sanitise(text)
                self.assertNotIn("(", expression)
                self.assertNotIn("*", expression)

    def test_a_hyphenated_term_splits_rather_than_becoming_a_negation(self):
        # `-` is FTS5's NOT. Left alone, searching "H-1B" would mean
        # "H, excluding 1B" and quietly return the wrong postings.
        self.assertEqual('"H" AND "1B"', sanitise("H-1B"))

    def test_an_empty_query_matches_nothing_not_everything(self):
        self.assertEqual("", sanitise("   "))
        self.assertEqual("", sanitise("()*"))


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "f.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, job_id, title, body, discipline="Finance"):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              discipline_primary,description_excerpt,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,'open','business_school','accepted',1,?,?,?,?,?,?)
        """, (job_id, f"k{job_id}", title, title.lower(), discipline, body,
              NOW, NOW, NOW, NOW))
        self.conn.commit()

    def test_a_posting_is_findable_by_a_word_in_its_body(self):
        self.add(1, "Assistant Professor", "We offer visa sponsorship for the right candidate.")
        self.assertEqual(1, search(self.conn, "sponsorship")["total"])

    def test_an_edit_removes_the_old_words_from_the_index(self):
        # The external-content trap: a delete trigger written with NEW values
        # leaves the old terms behind, and the posting keeps matching text it
        # no longer contains.
        self.add(2, "Assistant Professor", "This post mentions kangaroos.")
        self.assertEqual(1, search(self.conn, "kangaroos")["total"])
        self.conn.execute("UPDATE jobs SET description_excerpt=? WHERE id=2",
                          ("This post mentions penguins.",))
        self.conn.commit()
        self.assertEqual(0, search(self.conn, "kangaroos")["total"],
                         "the replaced text must stop matching")
        self.assertEqual(1, search(self.conn, "penguins")["total"])

    def test_a_deleted_posting_stops_matching(self):
        self.add(3, "Assistant Professor", "This post mentions wombats.")
        self.conn.execute("DELETE FROM jobs WHERE id=3")
        self.conn.commit()
        self.assertEqual(0, search(self.conn, "wombats")["total"])

    def test_the_index_stays_consistent_after_edits(self):
        self.add(4, "Assistant Professor", "alpha beta")
        self.conn.execute("UPDATE jobs SET description_excerpt='gamma' WHERE id=4")
        self.conn.execute("DELETE FROM jobs WHERE id=4")
        self.conn.commit()
        self.assertTrue(integrity_ok(self.conn),
                        "the index disagrees with the table it points at")

    def test_a_rebuild_reports_what_it_indexed(self):
        for n in range(5, 9):
            self.add(n, f"Professor {n}", "text")
        self.assertEqual(4, rebuild(self.conn))
        status = index_status(self.conn)
        self.assertTrue(status["in_step"])
        self.assertEqual(list(INDEXED_COLUMNS), status["indexed_columns"])

    def test_a_title_hit_outranks_a_passing_mention(self):
        self.add(10, "Assistant Professor of Marketing", "The department is large.")
        self.add(11, "Assistant Professor", "We also teach some marketing occasionally.")
        results = search(self.conn, "marketing")["results"]
        self.assertEqual(10, results[0]["id"])

    def test_search_obeys_the_callers_scope_rather_than_its_own(self):
        self.add(12, "Assistant Professor", "sponsorship available")
        self.conn.execute("UPDATE jobs SET business_scope='non_business' WHERE id=12")
        self.conn.commit()
        self.assertEqual(0, search(self.conn, "sponsorship",
                                   scope_sql="j.business_scope='business_school'")["total"])

    def test_a_hit_is_not_a_claim_about_the_posting(self):
        # The word appears in a refusal. Search must not imply otherwise.
        self.add(13, "Assistant Professor", "Visa sponsorship is not available.")
        result = search(self.conn, "sponsorship")
        self.assertEqual(1, result["total"])
        self.assertIn("offering it or refusing it", result["note"])

    def test_an_empty_query_returns_nothing_and_says_so(self):
        self.add(14, "Assistant Professor", "text")
        result = search(self.conn, "   ")
        self.assertEqual(0, result["total"])
        self.assertEqual([], result["results"])


if __name__ == "__main__":
    unittest.main()
