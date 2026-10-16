"""A-rated scope/preservation and selected-history regression fixtures."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services import abdc_astar_research_service as radar
from services.abdc_a_extension import acquisition_group, apply_plan, prepare_plan
from services.astar_history_service import init_run


class AExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.db = self.folder / 'source.db'
        conn = sqlite3.connect(self.db)
        radar.ensure_astar_tables(conn)
        conn.execute('''INSERT INTO abdc_astar_journals
            (journal_title,journal_title_normalized,issn_print,issn_l,abdc_rating,
             abdc_version,discipline,is_active,source_table,created_at)
            VALUES('Original Journal','original journal','0001-0001','0001-0001',
                   'A*','2025','Information Systems',1,'original','original date')''')
        conn.execute('''INSERT INTO astar_articles
            (id,title,title_normalized,publication_year,abstract,is_duplicate)
            VALUES(9,'Original article','original article',2020,'Original abstract',0)''')
        conn.execute('''INSERT INTO astar_article_classifications
            (article_id,classification_method,classification_notes)
            VALUES(9,'llm','Protected paid decision')''')
        conn.commit()
        self.original_journal = conn.execute('SELECT * FROM abdc_astar_journals').fetchone()
        self.original_article = conn.execute('SELECT * FROM astar_articles').fetchone()
        self.original_classification = conn.execute('SELECT * FROM astar_article_classifications').fetchone()
        conn.close()
        self.catalog = self.folder / 'catalog.json'
        self.items = [
            {'title': 'New IS Journal', 'issn': '0002-0002', 'for': '4609', 'rating': 'A', 'source_row': 10},
            {'title': 'New Psychology Journal', 'issn': '0003-0003', 'for': '3507', 'rating': 'A', 'source_row': 11},
            {'title': 'Excluded B Journal', 'issn': '0004-0004', 'for': '3507', 'rating': 'B', 'source_row': 12},
        ]
        self.catalog.write_text(json.dumps(self.items), encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def plan(self):
        return prepare_plan(self.catalog, self.db, self.folder / 'plan')

    def assert_originals(self):
        conn = sqlite3.connect(self.db)
        self.assertEqual(self.original_journal, conn.execute('SELECT * FROM abdc_astar_journals WHERE journal_title=?', ('Original Journal',)).fetchone())
        self.assertEqual(self.original_article, conn.execute('SELECT * FROM astar_articles WHERE id=9').fetchone())
        self.assertEqual(self.original_classification, conn.execute('SELECT * FROM astar_article_classifications WHERE article_id=9').fetchone())
        conn.close()

    def test_only_A_is_appended_and_original_values_are_preserved(self):
        plan = self.plan()
        self.assertEqual(2, plan['A_target_count'])
        receipt = apply_plan(self.folder / 'plan/scope.json')
        self.assertEqual(2, len(receipt['inserted']))
        self.assert_originals()

    def test_repeat_application_is_idempotent(self):
        self.plan()
        apply_plan(self.folder / 'plan/scope.json')
        receipt = apply_plan(self.folder / 'plan/scope.json')
        self.assertEqual([], receipt['inserted'])
        self.assertEqual(2, len(receipt['retained']))
        self.assert_originals()

    def test_existing_A_is_retained_and_not_queued_again(self):
        conn = sqlite3.connect(self.db)
        conn.execute('''INSERT INTO abdc_astar_journals
            (journal_title,journal_title_normalized,issn_print,issn_l,abdc_rating,
             abdc_version,is_active,source_table)
            VALUES('New IS Journal','new is journal','0002-0002','0002-0002',
                   'A','2025',1,'prestige_extra')''')
        conn.commit()
        original = conn.execute('SELECT * FROM abdc_astar_journals WHERE source_table=?', ('prestige_extra',)).fetchone()
        conn.close()
        plan = self.plan()
        self.assertEqual(1, plan['already_tracked_A_count'])
        self.assertEqual(1, plan['new_tracking_count'])
        apply_plan(self.folder / 'plan/scope.json')
        conn = sqlite3.connect(self.db)
        self.assertEqual(original, conn.execute('SELECT * FROM abdc_astar_journals WHERE source_table=?', ('prestige_extra',)).fetchone())
        conn.close()

    def test_changed_official_source_prevents_writes(self):
        self.plan()
        self.catalog.write_text(json.dumps(self.items) + '\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            apply_plan(self.folder / 'plan/scope.json')
        self.assert_originals()

    def test_selected_history_does_not_refetch_other_journals(self):
        plan = self.plan()
        apply_plan(self.folder / 'plan/scope.json')
        manifest = init_run(self.folder / 'run', self.db, 2010, '2026-10-06', self.folder / 'plan/scope.json')
        journals = json.loads((self.folder / 'run/journals.json').read_text(encoding='utf-8'))
        self.assertEqual(2, manifest['journal_count'])
        self.assertEqual([row['journal_title'] for row in plan['journals']], [row['journal_title'] for row in journals])
        self.assertEqual([0, 3], [row['collection_priority'] for row in journals])
        self.assertTrue(manifest['journal_scope_sha256'])
        self.assert_originals()

    def test_conflicting_existing_journal_rolls_back_all_inserts(self):
        conn = sqlite3.connect(self.db)
        conn.execute('''INSERT INTO abdc_astar_journals
            (journal_title,journal_title_normalized,issn_print,abdc_rating,
             abdc_version,is_active,source_table)
            VALUES('New Psychology Journal','new psychology journal','0003-0003',
                   'A','2025',0,'existing inactive')''')
        conn.commit()
        conn.close()
        self.plan()
        with self.assertRaisesRegex(ValueError, 'inactive/conflicting'):
            apply_plan(self.folder / 'plan/scope.json')
        conn = sqlite3.connect(self.db)
        self.assertEqual(0, conn.execute("SELECT COUNT(*) FROM abdc_astar_journals WHERE journal_title='New IS Journal'").fetchone()[0])
        conn.close()
        self.assert_originals()

    def test_acquisition_groups_do_not_change_official_discipline(self):
        self.assertEqual(0, acquisition_group({'title': 'AIS Transactions on Human-Computer Interaction', 'for': '4609'})[0])
        self.assertEqual(2, acquisition_group({'title': 'Computers & Industrial Engineering', 'for': '3503'})[0])
        self.assertEqual(3, acquisition_group({'title': 'Journal of Business and Psychology', 'for': '3507'})[0])
        self.assertEqual(('Strategy, Management & Organisational Behaviour', 'OB / HR'), radar.discipline_for({'title': 'Journal of Business and Psychology', 'for': '3507'}))

    def test_daily_upsert_does_not_overwrite_same_title_with_a_new_DOI(self):
        from services.abdc_a_extension import journal_row
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        article = {'title': 'Original article', 'doi': '10.1234/distinct',
                   'publication_year': 2020, 'journal_issn': '0002-0002'}
        status, identifier = radar._upsert_article(conn, article, journal_row(self.items[0]))
        conn.commit()
        conn.close()
        self.assertEqual('inserted', status)
        self.assertNotEqual(9, identifier)
        self.assert_originals()

    def test_daily_match_retains_conflicting_DOIs_on_a_shared_OpenAlex_ID(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE astar_articles SET doi='10.1234/first',openalex_id='W123' WHERE id=9")
        incoming = {'doi': '10.1234/second', 'openalex_id': 'W123',
                    'title': 'Original article', 'publication_year': 2020}
        self.assertIsNone(radar._find_existing(conn, incoming))
        conn.close()

    def test_anonymous_title_match_cannot_cross_journals(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE astar_articles SET journal_issn='0001-0001' WHERE id=9")
        incoming = {'title': 'Original article', 'publication_year': 2020, 'journal_issn': '0002-0002'}
        self.assertIsNone(radar._find_existing(conn, incoming))
        incoming['journal_issn'] = '0001-0001'
        self.assertEqual(9, radar._find_existing(conn, incoming))
        conn.close()

    def test_daily_match_normalizes_DOI_and_OpenAlex_URL_forms(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE astar_articles SET doi='10.1234/first',openalex_id='W123' WHERE id=9")
        self.assertEqual(9, radar._find_existing(conn, {'doi': 'https://doi.org/10.1234/FIRST'}))
        self.assertEqual(9, radar._find_existing(conn, {'openalex_id': 'https://openalex.org/W123'}))
        conn.close()

    def test_daily_Crossref_retains_year_and_month_precision_without_fake_days(self):
        from unittest.mock import patch
        items = [{'DOI': '10.1234/' + str(index), 'title': ['Date precision'],
                  'published': {'date-parts': [parts]}}
                 for index, parts in enumerate(([2020], [2020, 9], [2020, 9, 15]))]
        with patch.object(radar, '_http_get_json', return_value={'message': {'items': items}}):
            articles = radar.fetch_crossref('0002-0002', '2010-01-01', '2026-10-06')
        self.assertEqual([2020, 2020, 2020], [article['publication_year'] for article in articles])
        self.assertEqual([None, None, '2020-09-15'], [article['publication_date'] for article in articles])


if __name__ == '__main__':
    unittest.main()
