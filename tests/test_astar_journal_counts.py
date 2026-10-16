"""Journal counts must retain ISSN-union semantics with the covering count index."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import abdc_astar_research_service as radar


class JournalCountTests(unittest.TestCase):
    def test_payload_counts_both_issns_once_and_excludes_hidden_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'journal_counts.db'
            conn = sqlite3.connect(path)
            radar.ensure_astar_tables(conn)
            conn.executemany('''INSERT INTO abdc_astar_journals
                (journal_title,issn_print,issn_online,abdc_rating,abdc_version,is_active)
                VALUES(?,?,?,'A','2025',1)''', [
                    ('Two ISSNs', '1111-1111', '2222-2222'),
                    ('Repeated ISSN', '3333-3333', '3333-3333'),
                    ('Empty Journal', '4444-4444', None)])
            conn.executemany('INSERT INTO astar_articles(journal_issn,is_duplicate) VALUES(?,?)', [
                ('1111-1111', 0), ('2222-2222', 0), ('2222-2222', 1),
                ('3333-3333', 0), ('3333-3333', 0), ('9999-9999', 0)])
            conn.commit()
            plan = list(conn.execute('''EXPLAIN QUERY PLAN SELECT j.id,COUNT(a.id)
                FROM abdc_astar_journals j LEFT JOIN astar_articles a
                ON (a.journal_issn=j.issn_print OR a.journal_issn=j.issn_online) AND a.is_duplicate=0
                WHERE j.abdc_version=? GROUP BY j.id''', ('2025',)))
            self.assertTrue(any('idx_astar_journal_visible' in row[3] for row in plan))
            conn.close()
            with patch.object(radar, 'DB_PATH', path):
                result = radar.build_astar_journals_payload()
            self.assertEqual({'Two ISSNs': 2, 'Repeated ISSN': 2, 'Empty Journal': 0},
                             {row['journal_title']: row['articles_in_db'] for row in result['journals']})
            self.assertEqual(2, result['with_articles_count'])
