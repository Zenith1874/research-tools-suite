"""Source-scope, pagination and production preservation checks in isolated databases."""

import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import abdc_astar_research_service as radar
from services.astar_history_service import init_run, parse_crossref
from services.astar_history_service import HistoryRunner
from services.astar_openalex_scope_supplement import (
    SupplementCollector, assess_work, import_collected, initialize, supplement_spec,
)

JOURNAL = {"journal_title": "Fixture Information Systems Journal", "issn_print": "0268-3962",
           "issn_online": "1466-4437", "abdc_rating": "A", "abdc_version": "2025",
           "discipline": "Information Systems", "is_active": 1, "source_table": "test_fixture"}


def location(issns=None, published=True, source_type="journal"):
    return {"source": {"id": "https://openalex.org/S111", "issn": issns or ["0268-3962"],
                       "type": source_type, "display_name": JOURNAL["journal_title"]},
            "version": "publishedVersion" if published else "acceptedVersion", "is_published": published,
            "landing_page_url": "https://publisher.example.test/paper"}


def work(identifier="W1", kind="review", secondary=False, doi=None):
    target = location()
    return {"id": "https://openalex.org/" + identifier, "doi": doi,
            "title": "Supplemental paper " + identifier, "publication_date": "2020-03-04",
            "publication_year": 2020, "type": kind,
            "primary_location": location(["9999-9999"], source_type="repository") if secondary else target,
            "locations": [target], "biblio": {"volume": "10", "issue": "1"},
            "authorships": [{"author": {"display_name": "Fixture Author"}}],
            "abstract_inverted_index": {"Verified": [0], "public": [1], "abstract": [2]}}


class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "source.db"
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        radar.ensure_astar_tables(conn)
        fields = ("journal_title", "issn_print", "issn_online", "abdc_rating", "abdc_version", "discipline", "is_active", "source_table")
        conn.execute("INSERT INTO abdc_astar_journals(%s) VALUES(%s)" % (",".join(fields), ",".join("?" for _ in fields)),
                     [JOURNAL[field] for field in fields])
        original = parse_crossref({"DOI": "10.test/original", "title": ["Original article"],
                                   "published": {"date-parts": [[2020, 3, 4]]}, "type": "journal-article"}, JOURNAL)
        original["abstract"] = "Original nonempty abstract is protected."
        _, self.original_id = radar._upsert_article(conn, original, JOURNAL)
        conn.execute("UPDATE astar_article_classifications SET classification_method='llm',classification_notes='paid decision' WHERE article_id=?", (self.original_id,))
        conn.commit()
        self.original = dict(conn.execute("SELECT * FROM astar_articles WHERE id=?", (self.original_id,)).fetchone())
        self.classification = dict(conn.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.original_id,)).fetchone())
        self.sources = [dict(row) for row in conn.execute("SELECT * FROM astar_article_sources WHERE article_id=?", (self.original_id,))]
        conn.close()
        selection = self.root / "selection.json"
        selection.write_text(json.dumps([JOURNAL]), encoding="utf-8")
        self.primary = self.root / "primary"
        init_run(self.primary, self.db, 2010, "2026-10-06", selection)
        self.directory = self.root / "supplement"
        self.manifest = initialize(self.directory, [self.primary], expected_journals=1, page_size=2)
        self.collector = SupplementCollector(self.directory)
        self.journal = next(iter(self.collector.journals.values()))

    def tearDown(self):
        self.collector.close()
        self.temp.cleanup()

    def unit(self, kind="primary_nonarticle"):
        return dict(self.collector.state.execute("SELECT * FROM units WHERE kind=?", (kind,)).fetchone())

    def saved_page(self, items, expected=None, cursor=None, kind="primary_nonarticle", commit=True):
        unit = self.unit(kind)
        url, params = supplement_spec(kind, self.journal, self.manifest, unit["cursor"])
        envelope = {"url": url, "params": params, "rate_headers": {},
                    "data": {"results": items, "meta": {"count": len(items) if expected is None else expected,
                                                         "next_cursor": cursor}}}
        path = self.directory / "raw" / unit["unit_key"] / ("page_%06d.json.gz" % unit["next_page"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(envelope, stream)
        if commit:
            return self.collector.commit_page(unit, envelope, path)
        return unit, envelope, path

    def finish_empty_secondary(self):
        self.saved_page([], kind="secondary_location")

    def test_secondary_query_excludes_both_primary_issns_with_and(self):
        _, params = supplement_spec("secondary_location", self.journal, self.manifest, "*")
        filters = params["filter"].split(",")
        self.assertIn("locations.source.issn:0268-3962|1466-4437", filters)
        self.assertIn("primary_location.source.issn:!0268-3962", filters)
        self.assertIn("primary_location.source.issn:!1466-4437", filters)
        self.assertIn("locations", params["select"].split(","))

    def test_primary_nonarticle_query_keeps_frozen_dates(self):
        _, params = supplement_spec("primary_nonarticle", self.journal, self.manifest, "next")
        self.assertIn("type:!article", params["filter"])
        self.assertIn("to_publication_date:2026-10-06", params["filter"])
        self.assertEqual("next", params["cursor"])

    def test_secondary_published_journal_location_is_eligible(self):
        disposition, evidence, chosen = assess_work(work(secondary=True), self.journal, "secondary_location")
        self.assertEqual("ELIGIBLE_PENDING_IMPORT", disposition)
        self.assertEqual("journal", chosen["source"]["type"])
        self.assertEqual("publishedVersion", evidence[0]["version"])

    def test_preprint_type_with_a_verified_published_journal_copy_is_not_lost(self):
        item = work(kind="preprint", secondary=True, doi="https://doi.org/10.test/preprint")
        item["locations"][0]["id"] = "doi:10.test/published"
        disposition, evidence, _ = assess_work(item, self.journal, "secondary_location")
        self.assertEqual("ELIGIBLE_PENDING_IMPORT", disposition)
        self.assertEqual("10.test/published", evidence[0]["publisher_location_doi"])

    def test_import_uses_the_verified_publisher_doi_instead_of_the_preprint_doi(self):
        item = work("W3", kind="preprint", secondary=True, doi="https://doi.org/10.test/preprint")
        item["locations"][0]["id"] = "doi:10.test/published"
        self.saved_page([item], kind="secondary_location")
        self.saved_page([])
        import_collected(self.directory, self.primary)
        conn = sqlite3.connect(self.db)
        self.assertEqual("10.test/published", conn.execute("SELECT doi FROM astar_articles WHERE openalex_id='W3'").fetchone()[0])
        self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM astar_articles WHERE doi='10.test/preprint'").fetchone()[0])
        conn.close()

    def test_wrong_primary_issn_and_article_types_are_reviewed(self):
        self.assertEqual("REVIEW_QUERY_SCOPE_MISMATCH", assess_work(work(secondary=True), self.journal, "primary_nonarticle")[0])
        self.assertEqual("REVIEW_QUERY_SCOPE_MISMATCH", assess_work(work(kind="article"), self.journal, "primary_nonarticle")[0])

    def test_matching_repository_is_not_publication_evidence(self):
        item = work()
        item["primary_location"] = item["locations"][0] = location(source_type="repository")
        self.assertEqual("REVIEW_PUBLICATION_STATUS_UNCONFIRMED", assess_work(item, self.journal, "primary_nonarticle")[0])

    def test_accepted_version_and_dissertation_are_not_imported(self):
        item = work()
        item["primary_location"] = item["locations"][0] = location(published=False)
        self.assertEqual("REVIEW_PUBLICATION_STATUS_UNCONFIRMED", assess_work(item, self.journal, "primary_nonarticle")[0])
        self.assertEqual("EXCLUDED_NON_JOURNAL_WORK_TYPE", assess_work(work(kind="dissertation"), self.journal, "primary_nonarticle")[0])

    def test_pagination_collects_every_advertised_unique_record(self):
        self.assertEqual("RUNNING", self.saved_page([work("W1"), work("W2")], 3, "next"))
        self.assertEqual("COMPLETE", self.saved_page([work("W3")], 3))
        self.assertEqual(3, self.unit()["observed_count"])
        self.assertEqual(3, self.collector.state.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    def test_missing_duplicate_or_stalled_pages_never_complete(self):
        self.assertEqual("COUNT_MISMATCH", self.saved_page([work("W1"), work("W1")], 2))

    def test_repeated_cursor_is_stalled(self):
        self.assertEqual("CURSOR_STALLED", self.saved_page([work("W1"), work("W2")], 4, "*"))

    def test_source_count_drift_keeps_the_committed_cursor(self):
        self.saved_page([work("W1"), work("W2")], 3, "next")
        with self.assertRaisesRegex(ValueError, "Source count changed"):
            self.saved_page([work("W3")], 4)
        self.assertEqual("next", self.unit()["cursor"])
        self.assertEqual(2, self.unit()["observed_count"])

    def test_cached_raw_page_replays_without_network_calls(self):
        self.saved_page([work("W1")], commit=False)
        self.saved_page([], kind="secondary_location", commit=False)
        with patch.object(self.collector, "fetch_page", side_effect=AssertionError("No network on replay")):
            self.assertTrue(self.collector.collect(wait_for_primary=False)["all_queries_reconciled"])

    def test_import_waits_for_reconciled_collection(self):
        with self.assertRaisesRegex(ValueError, "must reconcile"):
            import_collected(self.directory, self.primary)

    def test_import_is_idempotent_and_preserves_original_paid_decisions(self):
        incoming = work("W1", doi="https://doi.org/10.test/original")
        incoming["title"] = "Source title must not replace original"
        self.saved_page([incoming, work("W2", doi="https://doi.org/10.test/new")])
        self.finish_empty_secondary()
        result = import_collected(self.directory, self.primary)
        self.assertEqual(2, result["pages_hash_verified"])
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        current = dict(conn.execute("SELECT * FROM astar_articles WHERE id=?", (self.original_id,)).fetchone())
        for key, value in self.original.items():
            if value not in (None, "") and key != "updated_at":
                self.assertEqual(value, current[key], key)
        self.assertEqual(self.classification, dict(conn.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.original_id,)).fetchone()))
        for source in self.sources:
            self.assertEqual(source, dict(conn.execute("SELECT * FROM astar_article_sources WHERE id=?", (source["id"],)).fetchone()))
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])
        conn.close()
        self.assertEqual({}, import_collected(self.directory, self.primary)["imported_this_pass"])

    def test_tampered_raw_page_blocks_import_before_article_changes(self):
        self.saved_page([work("W2")])
        self.finish_empty_secondary()
        raw = next((self.directory / "raw").rglob("*.gz"))
        raw.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash changed"):
            import_collected(self.directory, self.primary)
        conn = sqlite3.connect(self.db)
        self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])
        conn.close()

    def test_sql_import_preserves_baseline_and_links_cross_page_identifiers(self):
        original = work("W1", doi="https://doi.org/10.test/original")
        original["title"] = "Incoming title cannot replace the original"
        self.saved_page([original, work("W2", doi="https://doi.org/10.test/new")], 3, "next")
        self.saved_page([work("W3", doi="https://doi.org/10.test/new")], 3)
        self.finish_empty_secondary()
        runners = []

        def track_runner(*args, **kwargs):
            runner = HistoryRunner(*args, **kwargs)
            runners.append(runner)
            self.assertTrue(runner.sqlite_identities)
            self.assertEqual({}, runner.doi_index)
            self.assertEqual({}, runner.title_index)
            return runner

        with patch("services.astar_openalex_scope_supplement.HistoryRunner", side_effect=track_runner):
            result = import_collected(self.directory, self.primary, sqlite_identities=True)
        self.assertEqual("indexed_sqlite", result["identity_backend"])
        self.assertEqual(3, result["pages_hash_verified"])
        for name in ("doi_index", "oa_index", "title_index", "publisher_source_index"):
            self.assertEqual({}, getattr(runners[0], name), name)
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])
        current = dict(conn.execute("SELECT * FROM astar_articles WHERE id=?", (self.original_id,)).fetchone())
        for key, value in self.original.items():
            if value not in (None, "") and key != "updated_at":
                self.assertEqual(value, current[key], key)
        self.assertEqual(self.classification, dict(conn.execute(
            "SELECT * FROM astar_article_classifications WHERE article_id=?", (self.original_id,)).fetchone()))
        for source in self.sources:
            self.assertEqual(source, dict(conn.execute(
                "SELECT * FROM astar_article_sources WHERE id=?", (source["id"],)).fetchone()))
        conn.close()
        linked = self.collector.state.execute(
            "SELECT DISTINCT article_id FROM records WHERE source_id IN (?,?)",
            ("https://openalex.org/W2", "https://openalex.org/W3")).fetchall()
        self.assertEqual(1, len(linked))
        self.assertIsNotNone(linked[0][0])
        self.assertEqual({}, import_collected(
            self.directory, self.primary, sqlite_identities=True)["imported_this_pass"])

    def test_a_union_deduplicates_repeated_inputs_and_rejects_incomplete_scope(self):
        other = self.root / "other_supplement"
        self.assertEqual(1, initialize(other, [self.primary, self.primary], expected_journals=1)["journal_count"])
        with self.assertRaisesRegex(ValueError, "not 2"):
            initialize(self.root / "invalid_supplement", [self.primary], expected_journals=2)

    def test_primary_wait_is_based_on_live_checkpoint_states(self):
        self.assertFalse(self.collector.primaries_complete())
        conn = sqlite3.connect(self.primary / "checkpoint.sqlite3")
        conn.execute("UPDATE units SET status='COMPLETE'")
        conn.commit()
        conn.close()
        self.assertTrue(self.collector.primaries_complete())


if __name__ == "__main__":
    unittest.main()
