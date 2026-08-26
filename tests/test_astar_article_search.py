import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import abdc_astar_research_service as astar


class AstarArticleSearchTests(unittest.TestCase):
    def test_q_search_matches_titles_and_authors(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / 'astar.db'
            conn = sqlite3.connect(db_path)
            astar.ensure_astar_tables(conn)
            conn.execute(
                '''INSERT INTO astar_articles
                   (title, abstract, journal_title, authors_json,
                    publication_date, publication_year, is_duplicate)
                   VALUES (?, ?, ?, ?, ?, ?, 0)''',
                (
                    'Activating civic wealth creation in devitalized communities',
                    'A study of community entrepreneurship.',
                    'Journal of Business Venturing',
                    json.dumps(['Yanan Song', 'Rebecca Franklin']),
                    '2026-04-30', 2026,
                ),
            )
            conn.commit()
            conn.close()

            with patch.object(astar, 'DB_PATH', str(db_path)):
                for query in (
                    'Activating civic wealth', 'Yanan Song',
                    'Rebecca Franklin', 'franklin',
                ):
                    with self.subTest(query=query):
                        payload = astar.build_astar_articles_payload({
                            'q': query, 'limit': 50,
                        })
                        self.assertEqual(payload['total'], 1)
                        self.assertEqual(len(payload['articles']), 1)
                        self.assertEqual(payload['articles'][0]['authors'], [
                            'Yanan Song', 'Rebecca Franklin',
                        ])


if __name__ == '__main__':
    unittest.main()
