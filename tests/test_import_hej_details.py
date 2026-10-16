# -*- coding: utf-8 -*-
"""Applying browser-collected posting bodies.

The guard worth locking is the length comparison. A HigherEdJobs listing card
carries about 190 characters and the posting itself about 4,200, so a capture
*shorter* than what is stored means the page did not render -- and writing it
would silently replace a real posting with a fragment.

The collector is a separate process that can stop the moment a board refuses,
so its output is always partial by design. Everything here therefore has to be
safe to run twice on the same file.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.import_hej_details import load_records, plan
from services.faculty_jobs_service import ensure_faculty_jobs_tables

NOW = "2026-09-05T00:00:00Z"


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.dir.name) / "d.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, *lines):
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.path

    def test_only_successful_captures_are_loaded(self):
        self.write(
            json.dumps({"source_job_id": "1", "status": "ok", "body": "x" * 900}),
            json.dumps({"source_job_id": "2", "status": "challenged", "note": "interstitial"}),
            json.dumps({"source_job_id": "3", "status": "error", "note": "timeout"}),
            json.dumps({"source_job_id": "4", "status": "ok", "body": "   "}),
        )
        records, malformed = load_records(self.path)
        self.assertEqual(["1"], [r["source_job_id"] for r in records])
        self.assertEqual(0, malformed)

    def test_a_torn_final_line_is_counted_not_fatal(self):
        # The collector appends as it goes, so an interrupted run can leave a
        # half-written line. Losing the whole file to it would be absurd.
        self.write(json.dumps({"source_job_id": "1", "status": "ok", "body": "y" * 900}),
                   '{"source_job_id": "2", "status": "ok", "bo')
        records, malformed = load_records(self.path)
        self.assertEqual(1, len(records))
        self.assertEqual(1, malformed)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "f.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.source_id = self.conn.execute(
            "SELECT id FROM sources WHERE name='higheredjobs'").fetchone()["id"]

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, job_id, source_job_id, body, *, official_url=None, active=1):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,status,
                              business_scope,derived_quality,faculty_market_eligible,
                              description_excerpt,official_url,visa_status,
                              first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,'open','business_school','accepted',1,?,?, 'unknown',?,?,?,?)
        """, (job_id, f"k{job_id}", "Assistant Professor", "assistant professor",
              body, official_url, NOW, NOW, NOW, NOW))
        self.conn.execute("""
            INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,
                                     first_seen,last_seen)
            VALUES (?,?,?,?,?,?,?)
        """, (job_id, self.source_id, source_job_id,
              f"https://www.higheredjobs.com/faculty/details.cfm?JobCode={source_job_id}",
              active, NOW, NOW))
        self.conn.commit()

    def record(self, source_job_id, body, apply_url=None):
        return {"source_job_id": source_job_id, "status": "ok", "body": body,
                "apply_url": apply_url}

    def test_a_longer_body_replaces_the_card_blurb(self):
        self.add(1, "111", "HigherEdJobs category: Finance. Assistant Professor" * 2)
        updates, skipped = plan(self.conn, [self.record("111", "The department seeks " * 300)])
        self.assertEqual(1, len(updates))
        self.assertEqual([], skipped)
        self.assertGreater(updates[0]["now_chars"], updates[0]["was_chars"])

    def test_a_shorter_capture_is_refused(self):
        # The whole point: a page that did not render must not overwrite a real
        # posting with a fragment.
        self.add(2, "222", "A real posting body. " * 300)
        updates, skipped = plan(self.conn, [self.record("222", "Loading…")])
        self.assertEqual([], updates)
        self.assertIn("not longer than what is stored", skipped[0][1])

    def test_an_equal_length_capture_is_refused(self):
        body = "Exactly the same text. " * 50
        self.add(3, "333", body)
        updates, _ = plan(self.conn, [self.record("333", body)])
        self.assertEqual([], updates, "re-importing the same file must change nothing")

    def test_a_posting_the_board_no_longer_lists_is_skipped(self):
        self.add(4, "444", "short", active=0)
        updates, skipped = plan(self.conn, [self.record("444", "long " * 500)])
        self.assertEqual([], updates)
        self.assertIn("no active posting", skipped[0][1])

    def test_an_unknown_id_is_skipped_rather_than_guessed(self):
        updates, skipped = plan(self.conn, [self.record("999999", "long " * 500)])
        self.assertEqual([], updates)
        self.assertEqual(1, len(skipped))

    def test_an_application_url_is_only_filled_when_missing(self):
        self.add(5, "555", "short", official_url="https://school.example/apply")
        self.add(6, "666", "short")
        updates, _ = plan(self.conn, [
            self.record("555", "long " * 500, apply_url="https://board.example/x"),
            self.record("666", "long " * 500, apply_url="https://board.example/y")])
        by_id = {u["source_job_id"]: u for u in updates}
        self.assertIsNone(by_id["555"]["official_url"],
                          "an existing application URL is not overwritten")
        self.assertEqual("https://board.example/y", by_id["666"]["official_url"])

    def test_the_visa_verdict_is_re_derived_from_the_new_body(self):
        self.add(7, "777", "short")
        body = ("The department seeks candidates. " * 200
                + " Visa sponsorship is not available for this position.")
        updates, _ = plan(self.conn, [self.record("777", body)])
        self.assertEqual("sponsorship_explicit_no", updates[0]["visa_now"])
        self.assertEqual("unknown", updates[0]["visa_was"])


if __name__ == "__main__":
    unittest.main()
