# -*- coding: utf-8 -*-
"""The archive is the only asset that cannot be back-filled.

IPEDS, SED and PERM are annual files and can be downloaded again in 2029. A
job posting's page cannot: the next posting replaces it. So these tests are
less about today's behaviour than about a promise -- that a 2029 parser can be
run over a 2026 page and produce something comparable.

Two properties carry that promise: bytes come back exactly as they went in,
and a hash that is already held is never rewritten.
"""

import gzip
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import raw_archive


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.dir.name) / "raw"
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        raw_archive.ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def store(self, payload, **kwargs):
        return raw_archive.record_observation(
            self.conn, kind=raw_archive.KIND_DETAIL,
            source_url=kwargs.pop("url", "https://example.edu/job/1"),
            payload=payload, root=self.root, **kwargs)

    def blob_files(self):
        return sorted(p for p in self.root.rglob("*.gz") if p.is_file())

    def test_the_same_page_twice_is_one_file_and_two_observations(self):
        # A Workday page that does not change for a week must cost one blob,
        # not seven. The timeline lives in the observations.
        page = "<html><body>Assistant Professor of Finance</body></html>"
        first = self.store(page)
        second = self.store(page)
        self.assertEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(1, len(self.blob_files()))
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM raw_source_blobs").fetchone()[0])
        self.assertEqual(2, self.conn.execute(
            "SELECT COUNT(*) FROM raw_observations").fetchone()[0])

    def test_a_changed_page_creates_a_second_blob(self):
        self.store("<html>original</html>")
        self.store("<html>the deadline moved</html>")
        self.assertEqual(2, len(self.blob_files()))
        self.assertEqual(2, self.conn.execute(
            "SELECT COUNT(*) FROM raw_source_blobs").fetchone()[0])

    def test_decompression_restores_the_original_bytes_exactly(self):
        # The whole promise. Anything less than byte-exact means a 2029 parser
        # is reading something we edited.
        page = ("<html><body><p>Sponsorship: the University will file an "
                "H-1B petition.</p><p>中文测试 — em dash, "
                "curly ’quote’</p></body></html>")
        result = self.store(page)
        back = raw_archive.load_text(self.conn, result["content_hash"], root=self.root)
        self.assertEqual(page, back)

    def test_the_record_points_at_the_blob_that_holds_it(self):
        result = self.store("<html>x</html>", source_id=3, source_job_id="J-9")
        row = self.conn.execute(
            "SELECT o.content_hash, o.source_job_id, b.storage_path, b.byte_size "
            "FROM raw_observations o JOIN raw_source_blobs b "
            "ON b.content_hash = o.content_hash WHERE o.id=?",
            (result["observation_id"],)).fetchone()
        self.assertEqual(result["content_hash"], row["content_hash"])
        self.assertEqual("J-9", row["source_job_id"])
        self.assertTrue((self.root / row["storage_path"]).exists())
        self.assertEqual(len("<html>x</html>"), row["byte_size"])

    def test_a_refusal_is_recorded_without_a_body(self):
        # A 403 is an observation. Dropping it would leave a hole in coverage
        # indistinguishable from never having looked.
        result = raw_archive.record_observation(
            self.conn, kind=raw_archive.KIND_LISTING,
            source_url="https://blocked.example/jobs", payload=None,
            http_status=403, note="Cloudflare challenge", root=self.root)
        self.assertIsNone(result["content_hash"])
        row = self.conn.execute(
            "SELECT http_status, note, content_hash FROM raw_observations").fetchone()
        self.assertEqual(403, row["http_status"])
        self.assertIn("Cloudflare", row["note"])
        self.assertIsNone(row["content_hash"])
        self.assertEqual(0, len(self.blob_files()))

    def test_a_corrupt_blob_is_refused_rather_than_returned(self):
        # Silently returning damaged bytes would poison a re-parse years later
        # in a way nobody would notice.
        result = self.store("<html>good</html>")
        path = self.root / self.conn.execute(
            "SELECT storage_path FROM raw_source_blobs").fetchone()["storage_path"]
        with gzip.open(path, "wb") as handle:
            handle.write(b"<html>tampered</html>")
        with self.assertRaises(ValueError):
            raw_archive.load_blob(self.conn, result["content_hash"], root=self.root)

    def test_a_missing_file_is_an_error_not_an_empty_string(self):
        result = self.store("<html>x</html>")
        for path in self.blob_files():
            path.unlink()
        with self.assertRaises(FileNotFoundError):
            raw_archive.load_blob(self.conn, result["content_hash"], root=self.root)

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            raw_archive.record_observation(
                self.conn, kind="whatever", source_url="https://e.test/1",
                payload="x", root=self.root)

    def test_stats_report_what_is_actually_held(self):
        self.store("<html>" + "a" * 4000 + "</html>")
        self.store("<html>" + "b" * 4000 + "</html>")
        self.store("<html>" + "a" * 4000 + "</html>")  # repeat of the first
        raw_archive.record_observation(
            self.conn, kind=raw_archive.KIND_LISTING,
            source_url="https://blocked.example/", payload=None,
            http_status=429, root=self.root)
        stats = raw_archive.archive_stats(self.conn, root=self.root)
        self.assertEqual(2, stats["blobs"], "the repeat must not add a blob")
        self.assertEqual(4, stats["observations"])
        self.assertEqual(1, stats["observations_without_body"])
        self.assertGreater(stats["compression_ratio"], 1.0,
                           "repetitive HTML should compress")

    def test_the_stored_path_is_relative_so_the_archive_can_move(self):
        self.store("<html>x</html>")
        stored = self.conn.execute(
            "SELECT storage_path FROM raw_source_blobs").fetchone()["storage_path"]
        self.assertFalse(Path(stored).is_absolute())
        self.assertIn("/", stored, "expected the two-character fan-out prefix")

    def test_bytes_and_text_hash_identically(self):
        page = "<html>identical</html>"
        by_text = raw_archive.content_hash(page)
        by_bytes = raw_archive.content_hash(page.encode("utf-8"))
        self.assertEqual(by_text, by_bytes)


if __name__ == "__main__":
    unittest.main()
