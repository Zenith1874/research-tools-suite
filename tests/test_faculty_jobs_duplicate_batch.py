# -*- coding: utf-8 -*-
"""Batch review of duplicate candidates, and the scoring fix behind it.

The open queue reached 391 because fuzzy confidence was computed over a string
containing the institution, city and state -- all of which the candidate gate
had already forced to be equal. The identical prefix inflated every ratio, so
unrelated jobs at one school cleared the 0.82 threshold.
"""

import difflib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    ensure_faculty_jobs_tables,
    list_possible_duplicates,
    resolve_possible_duplicates_batch,
)


def similarity(title_a, discipline_a, title_b, discipline_b):
    """The corrected scorer: discriminating fields only."""
    return difflib.SequenceMatcher(
        None, "|".join((title_a, discipline_a)), "|".join((title_b, discipline_b))).ratio()


def inflated_similarity(institution, city, state, title_a, discipline_a, title_b, discipline_b):
    """The old scorer, kept here to document what it did."""
    left = "|".join((institution, title_a, city, state, discipline_a))
    right = "|".join((institution, title_b, city, state, discipline_b))
    return difflib.SequenceMatcher(None, left, right).ratio()


class ScoringTests(unittest.TestCase):
    def test_shared_gate_fields_inflate_the_ratio(self):
        """Two unrelated jobs at one school, with that school's real values.

        The exact historical score is not reproducible: city and state were
        later corrected by the derived-field repairs, so this asserts the
        mechanism -- a long identical prefix pulls the ratio up -- rather than
        a number that can no longer be recomputed from current data.
        """
        institution = "dyouville university - oakville ontario campus"
        old = inflated_similarity(
            institution, "", "on",
            "dean and principal", "Other",
            "executive director of chiropractic", "Other")
        new = similarity("dean and principal", "Other",
                         "executive director of chiropractic", "Other")
        self.assertLess(new, 0.50, "the titles are plainly different jobs")
        self.assertGreater(old - new, 0.30,
                           "the shared institution/city/state segments carried the old score")

    def test_a_longer_institution_name_inflates_the_score_further(self):
        # The inflation scales with the length of the shared prefix, which is
        # why long university names produced the worst false positives.
        short = inflated_similarity("mit", "", "ma", "dean", "Other", "librarian", "Other")
        long_name = inflated_similarity(
            "massachusetts institute of technology sloan school of management",
            "", "ma", "dean", "Other", "librarian", "Other")
        self.assertGreater(long_name, short)

    def test_genuine_duplicates_still_score_high(self):
        score = similarity("tenure track assistant professor in strategy", "Strategy",
                           "tenure track assistant professor in strategy", "Strategy")
        self.assertEqual(1.0, score)

    def test_a_near_miss_pair_stays_above_threshold(self):
        score = similarity("assistant professor of marketing", "Marketing",
                           "assistant professor of marketing (2 positions)", "Marketing")
        self.assertGreaterEqual(score, 0.82)


class BatchResolveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "faculty.db")
        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        now = "2026-08-26T00:00:00Z"
        for index in range(1, 7):
            conn.execute(
                "INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,"
                "first_seen_at,last_seen_at,created_at,updated_at) "
                "VALUES (?,?,?,?,'open',?,?,?,?)",
                (index, f"key-{index}", f"Job {index}", f"job {index}", now, now, now, now))
        for index, (left, right) in enumerate([(1, 2), (3, 4), (5, 6)], start=1):
            conn.execute(
                "INSERT INTO possible_duplicates (id,job_id,possible_job_id,confidence,"
                "match_basis,resolved,created_at) VALUES (?,?,?,?, 'fuzzy_review_only',0,?)",
                (index, left, right, 0.9, now))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.dir.cleanup()

    def open_count(self):
        conn = sqlite3.connect(self.db)
        count = conn.execute("SELECT COUNT(*) FROM possible_duplicates WHERE resolved=0").fetchone()[0]
        conn.close()
        return count

    def test_batch_reject_closes_every_listed_candidate(self):
        result = resolve_possible_duplicates_batch(self.db, {
            "ids": [1, 2, 3], "action": "reject",
            "reason": "Reviewed together: different postings at the same school."})
        self.assertTrue(result["ok"])
        self.assertEqual(3, result["resolved"])
        self.assertEqual(0, result["remaining_open"])
        self.assertEqual(0, self.open_count())

    def test_the_reason_is_stored_on_every_row_it_closed(self):
        reason = "Same school, unrelated vacancies; confirmed by reading both titles."
        resolve_possible_duplicates_batch(self.db, {
            "ids": [1, 2], "action": "confirm_distinct", "reason": reason})
        conn = sqlite3.connect(self.db)
        rows = conn.execute(
            "SELECT resolution, resolution_reason, resolved_at FROM possible_duplicates "
            "WHERE id IN (1,2)").fetchall()
        conn.close()
        for resolution, stored_reason, resolved_at in rows:
            self.assertEqual("confirmed_distinct", resolution)
            self.assertEqual(reason, stored_reason)
            self.assertTrue(resolved_at)

    def test_already_resolved_ids_are_reported_not_counted_as_successes(self):
        resolve_possible_duplicates_batch(self.db, {
            "ids": [1], "action": "reject", "reason": "First pass over the queue."})
        result = resolve_possible_duplicates_batch(self.db, {
            "ids": [1, 2], "action": "reject", "reason": "Second pass over the queue."})
        self.assertEqual(1, result["resolved"])
        self.assertEqual([1], result["skipped_ids"])

    def test_merge_is_refused_in_batch(self):
        # Merge repoints job links and can absorb private application state.
        with self.assertRaises(ValueError) as caught:
            resolve_possible_duplicates_batch(self.db, {
                "ids": [1], "action": "merge", "reason": "These look the same to me."})
        self.assertIn("per-pair", str(caught.exception))
        self.assertEqual(3, self.open_count())

    def test_a_short_reason_is_refused(self):
        with self.assertRaises(ValueError):
            resolve_possible_duplicates_batch(self.db, {
                "ids": [1], "action": "reject", "reason": "dup"})
        self.assertEqual(3, self.open_count())

    def test_an_empty_or_oversized_batch_is_refused(self):
        for ids in ([], list(range(600))):
            with self.assertRaises(ValueError):
                resolve_possible_duplicates_batch(self.db, {
                    "ids": ids, "action": "reject", "reason": "Bulk queue cleanup pass."})
        self.assertEqual(3, self.open_count())

    def test_non_integer_ids_are_refused_before_any_write(self):
        with self.assertRaises(ValueError):
            resolve_possible_duplicates_batch(self.db, {
                "ids": [1, "not-an-id"], "action": "reject",
                "reason": "Bulk queue cleanup pass."})
        self.assertEqual(3, self.open_count())

    def test_resolved_rows_are_retained_not_deleted(self):
        resolve_possible_duplicates_batch(self.db, {
            "ids": [1, 2, 3], "action": "reject", "reason": "Bulk queue cleanup pass."})
        conn = sqlite3.connect(self.db)
        total = conn.execute("SELECT COUNT(*) FROM possible_duplicates").fetchone()[0]
        conn.close()
        self.assertEqual(3, total, "review history must survive resolution")
        listing = list_possible_duplicates(self.db, include_resolved=True)
        self.assertEqual(3, listing["pagination"]["total"])


if __name__ == "__main__":
    unittest.main()
