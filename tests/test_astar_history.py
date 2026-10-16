"""Historical ingestion acceptance tests using isolated SQLite databases."""

import gzip
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services import abdc_astar_research_service as radar
from services.astar_history_service import (
    HistoryRunner, init_run, parse_crossref, request_spec,
)


JOURNAL = {
    "journal_title": "Academy of Management Journal", "issn_print": "0001-4273",
    "issn_online": "1948-0989", "abdc_rating": "A*", "abdc_version": "2025",
    "discipline": "Strategy, Management & Organisational Behaviour", "is_active": 1,
    "source_table": "abdc_data.json",
}


def work(doi, title="Historical article", year=2010, author="Researcher"):
    return {"DOI": doi, "title": [title], "published": {"date-parts": [[year, 2, 1]]},
            "author": [{"given": "A", "family": author}], "ISSN": ["0001-4273"],
            "container-title": [JOURNAL["journal_title"]], "type": "journal-article"}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "source.db"
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        radar.ensure_astar_tables(conn)
        conn.execute(
            "INSERT INTO abdc_astar_journals(journal_title,issn_print,issn_online,abdc_rating,abdc_version,discipline,is_active,source_table) VALUES (?,?,?,?,?,?,?,?)",
            tuple(JOURNAL[key] for key in ("journal_title", "issn_print", "issn_online", "abdc_rating", "abdc_version", "discipline", "is_active", "source_table")))
        article = parse_crossref(work("10.test/original", "Original article", 2020), JOURNAL)
        article["abstract"] = "Original verified publisher abstract which must be preserved."
        article["abstract_status"] = "available"
        _, self.original_id = radar._upsert_article(conn, article, JOURNAL)
        conn.execute("UPDATE astar_article_classifications SET classification_method='llm',classification_notes='original paid decision' WHERE article_id=?", (self.original_id,))
        conn.commit()
        self.original = dict(conn.execute("SELECT * FROM astar_articles WHERE id=?", (self.original_id,)).fetchone())
        self.original_classification = dict(conn.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.original_id,)).fetchone())
        conn.close()
        self.run_dir = Path(self.temp.name) / "run"
        init_run(self.run_dir, self.db, 2010, "2026-10-06")
        self.runner = HistoryRunner(self.run_dir, crossref_page_size=2, openalex_page_size=2)
        self.journal = next(iter(self.runner.journals.values()))
        self.unit_key = "crossref-" + self.journal["history_key"]

    def tearDown(self):
        self.runner.close()
        self.temp.cleanup()

    def unit(self):
        return dict(self.runner.state.execute("SELECT * FROM units WHERE unit_key=?", (self.unit_key,)).fetchone())

    def page(self, items, count, cursor):
        unit = self.unit()
        url, params = request_spec("crossref", self.journal, self.runner.manifest, unit["cursor"], 2)
        envelope = {"url": url, "params": params, "rate_headers": {},
                    "data": {"message": {"items": items, "total-results": count, "next-cursor": cursor}}}
        path = self.run_dir / "raw" / self.unit_key / f"page_{unit['next_page']:06d}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(envelope, stream)
        return unit, envelope, path

    def test_cursor_pagination_collects_past_first_page_and_reconciles(self):
        first = self.page([work("10.test/a"), work("10.test/b")], 3, "next")
        status, _ = self.runner.commit_page(first[0], self.journal, first[1], first[2])
        self.assertEqual("RUNNING", status)
        self.assertEqual("next", self.unit()["cursor"])
        second = self.page([work("10.test/c")], 3, "terminal")
        status, _ = self.runner.commit_page(second[0], self.journal, second[1], second[2])
        self.assertEqual("COMPLETE", status)
        self.assertEqual(3, self.unit()["observed_count"])
        self.assertEqual(3, self.runner.state.execute("SELECT COUNT(*) FROM records").fetchone()[0])
        self.assertEqual(4, self.runner.main.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])

    def test_existing_article_and_paid_classification_are_preserved(self):
        incoming = work("10.test/original", "Provider changed this title", 2021)
        incoming["abstract"] = "A new and different abstract must not replace the original."
        page = self.page([incoming], 1, "last")
        self.runner.commit_page(page[0], self.journal, page[1], page[2])
        current = dict(self.runner.main.execute("SELECT * FROM astar_articles WHERE id=?", (self.original_id,)).fetchone())
        classification = dict(self.runner.main.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.original_id,)).fetchone())
        self.assertEqual(self.original, current)
        self.assertEqual(self.original_classification, classification)

    def test_different_dois_with_identical_titles_are_distinct_articles(self):
        page = self.page([work("10.test/editorial-a", "Editorial"), work("10.test/editorial-b", "Editorial")], 2, None)
        self.runner.commit_page(page[0], self.journal, page[1], page[2])
        self.assertEqual(2, self.runner.main.execute("SELECT COUNT(*) FROM astar_articles WHERE title='Editorial'").fetchone()[0])

    def test_doi_less_distinct_openalex_ids_are_not_merged_by_generic_title(self):
        first = parse_crossref(work(None, "Editorial"), self.journal)
        second = dict(first)
        first["openalex_id"], second["openalex_id"] = "W111", "W222"
        first_id, _ = self.runner.ingest_article(first, self.journal)
        second_id, _ = self.runner.ingest_article(second, self.journal)
        self.runner.main.commit()
        self.assertNotEqual(first_id, second_id)

    def test_sql_identities_preserve_existing_paid_rows_and_bound_page_cache(self):
        self.runner.close()
        self.runner = HistoryRunner(self.run_dir, crossref_page_size=2, openalex_page_size=2, sqlite_identities=True)
        self.assertEqual({}, self.runner.title_index)
        page = self.page([work('10.test/original', 'Changed title', 2021), work('10.test/new')], 2, None)
        self.runner.commit_page(page[0], self.journal, page[1], page[2])
        self.assertEqual(self.original, dict(self.runner.main.execute('SELECT * FROM astar_articles WHERE id=?', (self.original_id,)).fetchone()))
        self.assertEqual(self.original_classification, dict(self.runner.main.execute('SELECT * FROM astar_article_classifications WHERE article_id=?', (self.original_id,)).fetchone()))
        self.assertEqual({}, self.runner.doi_index)
        self.assertEqual({}, self.runner.oa_index)
        self.assertEqual({}, self.runner.title_index)

    def test_sql_identities_keep_distinct_dois_and_openalex_ids_separate(self):
        self.runner.close()
        self.runner = HistoryRunner(self.run_dir, sqlite_identities=True)
        for first_id, second_id in [('10.test/first', '10.test/second'), (None, None)]:
            first = parse_crossref(work(first_id, 'Editorial'), self.journal)
            second = parse_crossref(work(second_id, 'Editorial'), self.journal)
            if first_id is None:
                first['openalex_id'], second['openalex_id'] = 'W111', 'W222'
            aid, _ = self.runner.ingest_article(first, self.journal)
            bid, _ = self.runner.ingest_article(second, self.journal)
            self.assertNotEqual(aid, bid)
        self.runner.main.commit()

    def test_sql_identities_find_prefix_stored_openalex_id_without_title_guess(self):
        first = parse_crossref(work(None, 'An actual article'), self.journal)
        first['openalex_id'] = 'https://openalex.org/W123'
        aid, _ = self.runner.ingest_article(first, self.journal)
        self.runner.main.commit()
        self.runner.close()
        self.runner = HistoryRunner(self.run_dir, sqlite_identities=True)
        incoming = dict(first, title='Different provider title', openalex_id='W123')
        self.assertEqual(aid, self.runner.existing_id(incoming, self.journal))

    def test_sql_identities_match_complete_doi_less_citation_with_same_conservative_rules(self):
        first = parse_crossref(work(None, 'Complete shared citation'), self.journal)
        aid, _ = self.runner.ingest_article(first, self.journal)
        self.runner.main.commit()
        self.runner.close()
        self.runner = HistoryRunner(self.run_dir, sqlite_identities=True)
        self.assertEqual(aid, self.runner.existing_id(first, self.journal))
        self.assertIsNone(self.runner.existing_id(dict(first, authors=['Different Author']), self.journal))

    def test_sql_identities_reject_noncanonical_storage_instead_of_merging_differently(self):
        self.runner.main.execute('UPDATE astar_articles SET doi=? WHERE id=?', ('HTTPS://DOI.ORG/10.TEST/ORIGINAL', self.original_id))
        self.runner.main.commit()
        with self.assertRaisesRegex(ValueError, 'canonical'):
            HistoryRunner(self.run_dir, sqlite_identities=True)

    def test_count_shortfall_never_reports_complete(self):
        page = self.page([work("10.test/a")], 2, "last")
        status, _ = self.runner.commit_page(page[0], self.journal, page[1], page[2])
        self.assertEqual("COUNT_MISMATCH", status)

    def test_repeated_cursor_on_full_page_never_reports_complete(self):
        page = self.page([work("10.test/a"), work("10.test/b")], 4, "*")
        status, _ = self.runner.commit_page(page[0], self.journal, page[1], page[2])
        self.assertEqual("CURSOR_STALLED", status)

    def test_resume_reuses_immutable_page_without_another_request(self):
        page = self.page([work("10.test/cached")], 1, "last")
        with patch.object(self.runner, "fetch_page", side_effect=AssertionError("resume must use the cached page")):
            self.runner.run_unit(self.unit_key)
        self.assertEqual("COMPLETE", self.unit()["status"])
        self.assertEqual(1, self.runner.main.execute("SELECT COUNT(*) FROM astar_articles WHERE doi='10.test/cached'").fetchone()[0])
        with patch.object(self.runner, "fetch_page", side_effect=AssertionError("complete units must not run again")):
            self.runner.run_unit(self.unit_key)

    def test_crash_after_db_commit_replays_without_duplicates(self):
        incoming = work("10.test/committed")
        self.runner.ingest_article(parse_crossref(incoming, self.journal), self.journal)
        self.runner.main.commit()
        page = self.page([incoming], 1, "last")
        self.runner.commit_page(page[0], self.journal, page[1], page[2])
        self.assertEqual(1, self.runner.main.execute("SELECT COUNT(*) FROM astar_articles WHERE doi='10.test/committed'").fetchone()[0])

    def test_source_count_drift_is_not_silently_accepted(self):
        first = self.page([work("10.test/a"), work("10.test/b")], 3, "next")
        self.runner.commit_page(first[0], self.journal, first[1], first[2])
        second = self.page([work("10.test/c")], 4, None)
        with self.assertRaisesRegex(RuntimeError, "source count changed"):
            self.runner.commit_page(second[0], self.journal, second[1], second[2])
        self.assertEqual(2, self.unit()["observed_count"])

    def test_out_of_range_canonical_date_has_explicit_disposition(self):
        page = self.page([work("10.test/old", year=2009)], 1, None)
        self.runner.commit_page(page[0], self.journal, page[1], page[2])
        disposition = self.runner.state.execute("SELECT disposition FROM records").fetchone()[0]
        self.assertEqual("EXCLUDED_CANONICAL_PUBLICATION_DATE", disposition)
        self.assertEqual(1, self.runner.main.execute("SELECT COUNT(*) FROM astar_articles").fetchone()[0])

    def test_year_only_source_date_precision_is_retained(self):
        item = work("10.test/year")
        item["published"] = {"date-parts": [[2010]]}
        parsed = parse_crossref(item, self.journal)
        self.assertIsNone(parsed["publication_date"])
        self.assertEqual("year", parsed["date_precision"])

    def test_second_source_enriches_new_record_and_local_rules(self):
        article = parse_crossref(work("10.test/new-enrichment"), self.journal)
        aid, _ = self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        second = dict(article)
        second.update({"openalex_id": "W333", "source_type": "openalex", "source_name": "OpenAlex",
                       "abstract": "A survey of employee burnout and turnover in organizations.",
                       "abstract_status": "inverted_index_reconstructed",
                       "concepts": [{"name": "Organizational behavior", "score": 0.9}],
                       "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "A Researcher"},
                                       "author_position": "first", "institutions": [{"id": "https://openalex.org/I1", "display_name": "Test University", "country_code": "US", "type": "education"}]}]})
        self.runner.ingest_article(second, self.journal)
        self.runner.main.commit()
        classification = self.runner.main.execute("SELECT classification_notes FROM astar_article_classifications WHERE article_id=?", (aid,)).fetchone()[0]
        self.assertNotIn("no_abstract:cap55", classification)
        self.assertEqual(1, self.runner.main.execute("SELECT COUNT(*) FROM astar_article_affiliations WHERE article_id=?", (aid,)).fetchone()[0])
        original = dict(self.runner.main.execute("SELECT * FROM astar_article_classifications WHERE article_id=?", (self.original_id,)).fetchone())
        self.assertEqual(self.original_classification, original)

    def test_paid_classification_on_new_record_also_survives_enrichment(self):
        article = parse_crossref(work("10.test/new-paid"), self.journal)
        aid, _ = self.runner.ingest_article(article, self.journal)
        self.runner.main.execute("UPDATE astar_article_classifications SET classification_method='llm',classification_notes='paid new decision' WHERE article_id=?", (aid,))
        article.update({"abstract": "A survey of remote work and employee burnout.", "abstract_status": "available"})
        self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        row = self.runner.main.execute("SELECT classification_method,classification_notes FROM astar_article_classifications WHERE article_id=?", (aid,)).fetchone()
        self.assertEqual(("llm", "paid new decision"), tuple(row))

    def test_restart_respects_persisted_openalex_budget_wait(self):
        deadline = time.time() + 3600
        self.runner.state.execute("UPDATE units SET status='WAITING_BUDGET',not_before=? WHERE provider='openalex'", (deadline,))
        self.runner.state.commit()
        self.runner.close()
        self.runner = HistoryRunner(self.run_dir, crossref_page_size=2, openalex_page_size=2)
        self.assertEqual(deadline, self.runner.openalex_not_before)
        with patch.object(self.runner, "fetch_page", side_effect=AssertionError("quota must not be bypassed by restart")), \
             patch.object(self.runner.stop, "wait", side_effect=lambda *args: self.runner.stop.set()):
            self.runner.worker("openalex")

    def test_publisher_path_is_idempotent_without_doi_or_author_names(self):
        article = parse_crossref(work(None, "A publisher article"), self.journal)
        article.update({"authors": [], "source_type": "publisher_metadata", "source_name": "Publisher",
                        "source_url": "https://publisher.example/article", "source_raw_id": "/article"})
        aid, _ = self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        self.runner.refresh_indexes()
        again, _ = self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        self.assertEqual(aid, again)
        self.assertEqual(1, self.runner.main.execute("SELECT COUNT(*) FROM astar_article_sources WHERE article_id=? AND source_type='publisher_metadata'", (aid,)).fetchone()[0])

    def test_verified_year_only_record_keeps_day_and_month_unknown(self):
        article = parse_crossref(work(None, "A year-only repository article", 2026), self.journal)
        article.update({"publication_date": None, "date_precision": "year", "source_type": "publisher_metadata", "source_raw_id": "/repository-article"})
        aid, disposition = self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        row = self.runner.main.execute("SELECT publication_year,publication_date,publication_month FROM astar_articles WHERE id=?", (aid,)).fetchone()
        self.assertEqual("INSERTED", disposition)
        self.assertEqual((2026, None, None), tuple(row))

    def test_unqualified_missing_date_is_excluded(self):
        article = parse_crossref(work(None, "An undated record", 2026), self.journal)
        article.update({"publication_date": None, "date_precision": "missing"})
        aid, disposition = self.runner.ingest_article(article, self.journal)
        self.assertIsNone(aid)
        self.assertEqual("EXCLUDED_CANONICAL_PUBLICATION_DATE", disposition)

    def test_verified_issue_year_boundary_retains_earlier_online_date(self):
        from services.astar_archive_year_service import year_expression
        item = work('10.test/early-online', 'An early-online issue-year record', 2009)
        item['published-print'] = {'date-parts': [[2010, 2, 1]]}
        article = parse_crossref(item, self.journal)
        rejected, _ = self.runner.ingest_article(dict(article), self.journal)
        self.assertIsNone(rejected)
        article['_archive_scope_admission'] = True
        aid, disposition = self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        self.assertEqual('INSERTED', disposition)
        row = self.runner.main.execute('SELECT publication_year,publication_date FROM astar_articles WHERE id=?', (aid,)).fetchone()
        self.assertEqual(2009, row[0])
        self.assertTrue(row[1].startswith('2009-'))
        expression = year_expression(self.runner.main)
        self.assertEqual(2010, self.runner.main.execute('SELECT ' + expression + ' FROM astar_articles a WHERE a.id=?', (aid,)).fetchone()[0])

    def test_month_only_record_retains_month_without_a_placeholder_day(self):
        article = parse_crossref(work(None, "A month-only repository article", 2026), self.journal)
        article.update({"publication_date": None, "publication_month": "2026-08", "date_precision": "month",
                        "source_type": "publisher_metadata", "source_raw_id": "/month-repository-article"})
        aid, disposition = self.runner.ingest_article(article, self.journal)
        self.runner.main.commit()
        row = self.runner.main.execute("SELECT publication_year,publication_date,publication_month FROM astar_articles WHERE id=?", (aid,)).fetchone()
        self.assertEqual("INSERTED", disposition)
        self.assertEqual((2026, None, "2026-08"), tuple(row))

    def test_invalid_or_inconsistent_partial_month_is_excluded(self):
        for month in ("2026-13", "2026-8", "2025-08", "2027-01"):
            with self.subTest(month=month):
                article = parse_crossref(work(None, "A bad partial-date record", 2026), self.journal)
                article.update({"publication_date": None, "publication_month": month, "date_precision": "month"})
                aid, disposition = self.runner.ingest_article(article, self.journal)
                self.assertIsNone(aid)
                self.assertEqual("EXCLUDED_CANONICAL_PUBLICATION_DATE", disposition)

    def test_repository_parser_retains_each_date_precision(self):
        from scripts.import_tax_repository_metadata import parse_publication_date
        self.assertEqual((2026, None, None, "year"), parse_publication_date("2026"))
        self.assertEqual((2026, None, "2026-08", "month"), parse_publication_date("2026/08"))
        self.assertEqual((2026, "2026-08-12", "2026-08", "day"), parse_publication_date("2026/08/12"))


class RepositoryParserTests(unittest.TestCase):
    def test_qut_bibliography_is_mapped_without_contact_metadata(self):
        from bs4 import BeautifulSoup
        from scripts.import_tax_repository_metadata import citation_fields
        soup = BeautifulSoup('''
            <meta name="eprints.title" content="A tracked journal article">
            <meta name="eprints.creators_name" content="First Author">
            <meta name="eprints.creators_name" content="Second Author">
            <meta name="eprints.date" content="2025">
            <meta name="eprints.publication" content="Australian Tax Forum: a journal of taxation policy, law and reform">
            <meta name="eprints.issn" content="0812-695X">
            <meta name="eprints.pagerange" content="399-430">
            <meta name="eprints.ispublished" content="pub">
            <meta name="eprints.type" content="article">
            <meta name="eprints.contact_email" content="not-to-import@example.org">
        ''', "html.parser")
        fields = citation_fields(soup, "eprints.qut.edu.au")
        self.assertEqual(["First Author", "Second Author"], fields["citation_author"])
        self.assertEqual(["2025"], fields["citation_publication_date"])
        self.assertEqual(["399"], fields["citation_firstpage"])
        self.assertEqual(["430"], fields["citation_lastpage"])
        self.assertNotIn("not-to-import@example.org", str(fields))

    def test_qut_unpublished_item_is_not_a_published_journal_record(self):
        from bs4 import BeautifulSoup
        from scripts.import_tax_repository_metadata import citation_fields
        soup = BeautifulSoup('<meta name="eprints.ispublished" content="unpub"><meta name="eprints.type" content="article">', "html.parser")
        with self.assertRaises(ValueError):
            citation_fields(soup, "eprints.qut.edu.au")


if __name__ == "__main__":
    unittest.main()
