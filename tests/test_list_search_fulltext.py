# -*- coding: utf-8 -*-
"""The list filter box, after full-text matching was added beside it.

The box did a substring match across title, institution, school, department,
body and city. That is the right behaviour for a filter -- typing part of a
city narrows the list -- but it cannot match separate words: "tenure
marketing" is not a substring of any posting, so it returned nothing while
plenty of postings contain both words.

So the two are ORed rather than one replacing the other, and the substring pass
keeps reaching the joined columns the index does not carry. These tests hold
both halves, because losing the substring behaviour to gain the word behaviour
would be a straight trade, not an improvement.
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    build_faculty_jobs_payload, ensure_faculty_jobs_tables,
)

NOW = "2026-09-05T00:00:00Z"


class SearchBoxTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "f.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, job_id, title, body, *, city=None, department=None):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              faculty_market_role,description_excerpt,city,department,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,'open','business_school','accepted',1,'faculty',?,?,?,?,?,?,?)
        """, (job_id, f"k{job_id}", title, title.lower(), body, city, department,
              NOW, NOW, NOW, NOW))
        self.conn.commit()

    def total(self, q):
        payload = build_faculty_jobs_payload(self.db, query={"q": q, "limit": 50})
        return payload["pagination"]["total"]

    def test_separate_words_match_a_posting_containing_both(self):
        # The gap this closed: no posting contains the literal string
        # "tenure marketing", and many contain both words.
        self.add(1, "Assistant Professor of Marketing",
                 "This is a tenure track appointment in the marketing group.")
        self.assertEqual(1, self.total("tenure marketing"))

    def test_a_posting_missing_one_of_the_words_does_not_match(self):
        # AND, not OR: an extra word has to narrow the result, or the box is
        # useless for anything but a single term.
        self.add(2, "Assistant Professor of Finance",
                 "This is a tenure track appointment in finance.")
        self.assertEqual(0, self.total("tenure marketing"))

    def test_a_plain_substring_still_matches(self):
        self.add(3, "Assistant Professor", "Body text.", city="Palo Alto")
        self.assertEqual(1, self.total("Palo"))

    def test_a_partial_word_still_matches_as_a_substring(self):
        # The full-text index tokenises, so it would never match "profess".
        # The substring pass is what keeps a filter box feeling like one.
        self.add(4, "Assistant Professor", "Body text.")
        self.assertEqual(1, self.total("profess"))

    def test_a_department_only_hit_still_works(self):
        self.add(5, "Assistant Professor", "Body.", department="Operations Research")
        self.assertEqual(1, self.total("Operations Research"))

    def test_a_query_matching_nothing_returns_nothing(self):
        self.add(6, "Assistant Professor", "Body text.")
        self.assertEqual(0, self.total("xyzzy nothing"))

    def test_punctuation_does_not_break_the_query(self):
        # `-` is FTS5's NOT and unbalanced quotes are a syntax error; a filter
        # box that throws on an apostrophe is worse than one that cannot
        # express a boolean.
        self.add(7, "Assistant Professor (Finance)", "The dean's office is here.")
        for text in ("(Finance)", "dean's", "H-1B", '"unbalanced'):
            with self.subTest(text=text):
                self.total(text)          # must not raise

    def test_the_two_passes_do_not_double_count_a_posting(self):
        # A posting matched by both must appear once.
        self.add(8, "Marketing tenure position",
                 "A tenure track marketing appointment.")
        self.assertEqual(1, self.total("tenure marketing"))


if __name__ == "__main__":
    unittest.main()
