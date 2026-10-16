"""Calendar-precision regressions on isolated databases and source fixtures."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import abdc_astar_research_service as radar
from services.astar_history_service import HistoryRunner, init_run, parse_crossref
from services.astar_publication_precision_service import attach_precision, date_expression, ensure_tables


JOURNAL = {'journal_title': 'Precision Journal', 'issn_print': '0001-0001',
           'issn_online': '', 'abdc_rating': 'A', 'abdc_version': '2025',
           'discipline': 'Information Systems', 'is_active': 1, 'source_table': 'fixture'}


class DatePrecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'articles.db'
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        radar.ensure_astar_tables(conn)
        conn.execute('''INSERT INTO abdc_astar_journals(journal_title,issn_print,abdc_rating,
            abdc_version,discipline,is_active) VALUES(?,?,?,?,?,1)''',
            tuple(JOURNAL[key] for key in ('journal_title','issn_print','abdc_rating','abdc_version','discipline')))
        conn.commit()
        conn.close()
        self.run = Path(self.temp.name) / 'run'
        init_run(self.run, self.db, 2010, '2026-10-06')
        self.runner = HistoryRunner(self.run)
        self.journal = next(iter(self.runner.journals.values()))

    def tearDown(self):
        self.runner.close()
        self.temp.cleanup()

    def article(self, parts, print_parts=None):
        item = {'DOI': '10.1234/precision', 'title': ['Precision article'],
                'published': {'date-parts': [parts]}}
        if print_parts:
            item['published-print'] = {'date-parts': [print_parts]}
        return parse_crossref(item, self.journal)

    def test_year_only_has_no_fabricated_day_and_is_admitted(self):
        article = self.article([2020])
        self.assertIsNone(article['publication_date'])
        self.assertEqual('year', article['date_precision'])
        _, disposition = self.runner.ingest_article(article, self.journal)
        self.assertEqual('INSERTED', disposition)

    def test_month_only_retains_month_without_a_fabricated_day(self):
        article = self.article([2020, 9])
        self.assertIsNone(article['publication_date'])
        self.assertEqual('2020-09', article['publication_month'])
        identifier, disposition = self.runner.ingest_article(article, self.journal)
        self.assertEqual('INSERTED', disposition)
        row = self.runner.main.execute('SELECT publication_date,publication_month FROM astar_articles WHERE id=?', (identifier,)).fetchone()
        self.assertEqual((None, '2020-09'), tuple(row))

    def test_actual_first_day_is_retained(self):
        self.assertEqual('2020-09-01', self.article([2020, 9, 1])['publication_date'])

    def test_invalid_month_is_not_fabricated(self):
        article = self.article([2020, 13])
        self.assertIsNone(article['publication_date'])
        self.assertIsNone(article['publication_month'])
        self.assertEqual('EXCLUDED_CANONICAL_PUBLICATION_DATE', self.runner.ingest_article(article, self.journal)[1])

    def test_partial_early_date_can_be_admitted_by_verified_print_year(self):
        article = self.article([2009], [2010])
        article['_archive_scope_admission'] = True
        identifier, disposition = self.runner.ingest_article(article, self.journal)
        self.assertEqual('INSERTED', disposition)
        self.assertEqual(2009, self.runner.main.execute('SELECT publication_year FROM astar_articles WHERE id=?', (identifier,)).fetchone()[0])

    def test_precision_view_keeps_original_cache_and_excludes_unknown_days(self):
        conn = self.runner.main
        conn.execute("INSERT INTO astar_articles(id,title,publication_year,publication_date,is_duplicate) VALUES(10,'Monthly',2020,'2020-09-01',0)")
        ensure_tables(conn)
        conn.execute('INSERT INTO astar_publication_precision VALUES(?,?,?,?,?,?,?,?,?)',
                     (10,'month','2020-09','2020-09-01',2020,'{}','page','hash','now'))
        article = {'id':10,'publication_year':2020,'publication_date':'2020-09-01'}
        attach_precision(conn, [article])
        self.assertIsNone(article['publication_date'])
        self.assertEqual('2020-09', article['publication_month'])
        self.assertEqual('2020-09-01', article['cached_publication_date'])
        self.assertIsNone(conn.execute('SELECT '+date_expression(conn)+' FROM astar_articles a WHERE id=10').fetchone()[0])
        self.assertEqual('2020-09-01', conn.execute('SELECT publication_date FROM astar_articles WHERE id=10').fetchone()[0])

    def test_later_different_exact_date_is_not_masked_by_a_stale_overlay(self):
        conn = self.runner.main
        conn.execute("INSERT INTO astar_articles(id,title,publication_year,publication_date,is_duplicate) VALUES(10,'Updated',2020,'2020-09-12',0)")
        ensure_tables(conn)
        conn.execute('INSERT INTO astar_publication_precision VALUES(?,?,?,?,?,?,?,?,?)',
                     (10,'month','2020-09','2020-09-01',2020,'{}','page','hash','now'))
        article = {'id':10,'publication_date':'2020-09-12'}
        attach_precision(conn, [article])
        self.assertEqual('2020-09-12', article['publication_date'])

    def test_sql_alias_is_validated(self):
        with self.assertRaises(ValueError):
            date_expression(self.runner.main, 'a;DROP TABLE astar_articles')


if __name__ == '__main__':
    unittest.main()
