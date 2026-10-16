"""Issue-year projections must keep every original date/year intact."""

import sqlite3
import unittest
from services.astar_archive_year_service import ensure_tables, put_year, year_expression, attach_years


class ArchiveYearTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,publication_year INTEGER,publication_date TEXT)')
        self.db.execute("INSERT INTO astar_articles VALUES(1,2019,'2019-06-01')")

    def test_fixture_without_derived_table_keeps_reported_year(self):
        expression = year_expression(self.db)
        self.assertEqual([(2019,)], self.db.execute('SELECT ' + expression + ' FROM astar_articles a').fetchall())

    def test_archive_filter_uses_issue_year_without_rewriting_raw_dates(self):
        ensure_tables(self.db)
        put_year(self.db, 1, 2020, 'print', 'publisher', 'source', {'printed_year': 2020})
        expression = year_expression(self.db)
        self.assertEqual([(1,)], self.db.execute('SELECT a.id FROM astar_articles a WHERE ' + expression + '=2020').fetchall())
        self.assertEqual([], self.db.execute('SELECT a.id FROM astar_articles a WHERE ' + expression + '=2019').fetchall())
        self.assertEqual([(1, 2019, '2019-06-01')], self.db.execute('SELECT * FROM astar_articles').fetchall())

    def test_payload_exposes_original_and_archive_years(self):
        ensure_tables(self.db)
        put_year(self.db, 1, 2020, 'print', 'publisher', 'source', {})
        article = {'id': 1, 'publication_year': 2019, 'publication_date': '2019-06-01'}
        attach_years(self.db, [article])
        self.assertEqual(2020, article['archive_year'])
        self.assertEqual(2019, article['publication_year'])
        self.assertEqual('2019-06-01', article['publication_date'])

    def test_lower_priority_source_cannot_replace_publisher_imprint(self):
        ensure_tables(self.db)
        put_year(self.db, 1, 2025, 'publisher_imprint', 'publisher', 'header', {}, priority=30)
        put_year(self.db, 1, 2026, 'profile', 'institution', 'profile', {}, priority=10)
        self.assertEqual([(2025,)], self.db.execute('SELECT archive_year FROM astar_article_archive_years').fetchall())


if __name__ == '__main__':
    unittest.main()
