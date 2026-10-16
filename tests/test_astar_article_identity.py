"""Prevent year/title deduplication from hiding distinct scholarly works."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.astar_article_identity import duplicate_ids
from services.abdc_astar_research_service import deduplicate_articles


def article(identifier, doi=None, openalex_id=None, journal='journal-a'):
    return {'id': identifier, 'doi': doi, 'openalex_id': openalex_id,
            'title_normalized': 'same book review title', 'publication_year': 2011,
            'journal_issn': journal}


class BibliographicIdentityTests(unittest.TestCase):
    def test_same_title_year_and_venue_with_distinct_dois_stay_visible(self):
        rows = [article(1, '10.1016/j.bar.2011.06.002'),
                article(2, '10.2308/accr.00000032')]
        self.assertEqual(duplicate_ids(rows), ([], 0))

    def test_same_title_in_distinct_journals_without_identifiers_stays_visible(self):
        self.assertEqual(duplicate_ids([article(1), article(2, journal='journal-b')]), ([], 0))

    def test_normalized_shared_doi_keeps_earliest_id(self):
        rows = [article(20, 'HTTPS://DOI.ORG/10.1234/ABC'), article(3, '10.1234/abc')]
        self.assertEqual(duplicate_ids(rows), ([20], 0))

    def test_identifier_bridge_reconciles_all_rows(self):
        rows = [article(1, '10.1234/abc'), article(2, openalex_id='W123'),
                article(3, '10.1234/abc', 'https://openalex.org/W123')]
        self.assertEqual(duplicate_ids(rows), ([2, 3], 0))

    def test_conflicting_dois_on_shared_openalex_id_are_retained(self):
        rows = [article(1, '10.1234/a', 'W123'), article(2, '10.1234/b', 'W123'),
                article(3, '10.1234/a', 'W123')]
        self.assertEqual(duplicate_ids(rows), ([3], 1))

    def test_placeholder_identifiers_do_not_establish_identity(self):
        self.assertEqual(duplicate_ids([article(1, 'unknown', 'unknown'),
                                        article(2, 'unknown', 'unknown')]), ([], 0))

    def test_database_application_preserves_distinct_reviews_and_existing_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'articles.db'
            conn = sqlite3.connect(path)
            conn.execute('''CREATE TABLE astar_articles (
                id INTEGER PRIMARY KEY,doi TEXT,openalex_id TEXT,
                title TEXT,is_duplicate INTEGER)''')
            conn.executemany('INSERT INTO astar_articles VALUES (?,?,?,?,?)', [
                (1, '10.1016/j.bar.2011.06.002', None, 'Same review title', 0),
                (2, '10.2308/accr.00000032', None, 'Same review title', 0),
                (3, 'https://doi.org/10.2308/ACCR.00000032', None, 'Other supplied title', 0),
                (4, '10.5678/already-hidden', None, 'Existing hidden record', 1)])
            conn.commit()
            conn.close()
            result = deduplicate_articles(path)
            self.assertEqual(result['duplicates_marked'], 1)
            conn = sqlite3.connect(path)
            self.assertEqual(conn.execute('SELECT id,is_duplicate FROM astar_articles ORDER BY id').fetchall(),
                             [(1, 0), (2, 0), (3, 1), (4, 1)])
            self.assertEqual(conn.execute('SELECT title FROM astar_articles WHERE id=3').fetchone()[0],
                             'Other supplied title')
            conn.close()

    def test_database_graph_omits_a_large_singleton_population(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'articles.db'
            conn = sqlite3.connect(path)
            conn.execute('CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,doi TEXT,openalex_id TEXT,is_duplicate INTEGER)')
            conn.executemany('INSERT INTO astar_articles VALUES(?,?,?,0)',
                             [(identifier, f'10.1234/unique-{identifier}', f'W{identifier}') for identifier in range(1, 5001)])
            conn.executemany('INSERT INTO astar_articles VALUES(?,?,?,0)',
                             [(6001, '10.1234/unique-1', None), (6002, None, 'https://openalex.org/W2')])
            conn.commit(); conn.close()
            sizes = []
            def checked_graph(rows):
                sizes.append(len(rows))
                return duplicate_ids(rows)
            with patch('services.astar_article_identity.duplicate_ids', side_effect=checked_graph):
                result = deduplicate_articles(path)
            self.assertEqual(sizes, [4])
            self.assertEqual(result['duplicates_marked'], 2)
            self.assertEqual(result['identity_graph_candidate_rows'], 4)

    def test_database_candidate_selection_preserves_cross_identifier_bridges(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'articles.db'
            conn = sqlite3.connect(path)
            conn.execute('CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,doi TEXT,openalex_id TEXT,is_duplicate INTEGER)')
            conn.executemany('INSERT INTO astar_articles VALUES(?,?,?,0)',
                             [(1, '10.1234/bridge', None), (2, None, 'W123'), (3, 'HTTPS://DOI.ORG/10.1234/BRIDGE', 'W123')])
            conn.commit(); conn.close()
            result = deduplicate_articles(path)
            self.assertEqual(result['duplicates_marked'], 2)


if __name__ == '__main__':
    unittest.main()
