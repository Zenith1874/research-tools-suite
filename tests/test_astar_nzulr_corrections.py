"""Correction imports retain original evidence and refuse baseline retirement."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.apply_nzulr_source_corrections import apply
from scripts.import_nzulr_metadata import apply_records
from services import abdc_astar_research_service as radar
from services.astar_history_service import digest, init_run


class NzulrCorrectionTests(unittest.TestCase):
    def fixture(self, root, seed_baseline=False):
        db = root / 'articles.db'
        raw = root / 'issue.html.gz'
        raw.write_bytes(b'Preserved issue evidence')
        pdf = root / 'abstracts.pdf'
        pdf.write_bytes(b'%PDF-fixture preserved abstract source')
        journal = {'journal_title': 'New Zealand Universities Law Review', 'issn_print': '0549-0618',
                   'issn_online': '', 'abdc_rating': 'A', 'abdc_version': '2025',
                   'discipline': 'Law', 'is_active': 1, 'source_table': 'fixture'}
        def record(identifier, title):
            return {'status': 'VERIFIED_ISSUE_HTML_METADATA', 'journal_title': journal['journal_title'],
                'source_raw_id': identifier, 'source_url': 'https://nzulr.com/archives/fixture.htm',
                'title': title, 'authors': ['An Author'], 'publication_year': 2020,
                'publication_month': '2020-06', 'publication_date': None, 'date_precision': 'month',
                'archive_year': 2020, 'year_basis': 'publisher_issue_heading_year', 'volume': 29,
                'issue': '1', 'record_type': 'journal-metadata-item', 'source_html_path': str(raw),
                'source_html_sha256': digest(raw), 'source_issue_heading': 'Vol 29, No 1 June 2020'}
        original = record('old-combined-item', 'First Title Second Title')
        corrected = [record('first-item', 'First Title'), record('second-item', 'Second Title')]
        conn = sqlite3.connect(db)
        radar.ensure_astar_tables(conn)
        conn.execute('INSERT INTO abdc_astar_journals(%s) VALUES(%s)' %
                     (','.join(journal), ','.join('?' for _ in journal)), list(journal.values()))
        if seed_baseline:
            conn.execute('INSERT INTO astar_articles(id,title,journal_title,is_duplicate) VALUES(1,?,?,0)',
                         (original['title'], journal['journal_title']))
            conn.execute("INSERT INTO astar_article_sources(article_id,source_type,raw_id) VALUES(1,'publisher_metadata',?)",
                         (original['source_raw_id'],))
        conn.commit(); conn.close()
        scope = root / 'scope.json'
        scope.write_text(json.dumps([journal]), encoding='utf-8')
        run = root / 'run'
        init_run(run, db, 2010, '2026-10-06', scope)
        old_file, corrected_file, abstract_file = (root / name for name in ('old.json', 'corrected.json', 'abstracts.json'))
        old_file.write_text(json.dumps([original]), encoding='utf-8')
        corrected_file.write_text(json.dumps(corrected), encoding='utf-8')
        abstracts = [{'source_raw_id': row['source_raw_id'], 'status': 'VERIFIED_PUBLISHER_ABSTRACT',
            'source_url': 'https://nzulr.com/abstracts/fixture.pdf', 'pdf_path': str(pdf),
            'pdf_sha256': digest(pdf), 'abstract': 'The verified abstract for ' + row['title']} for row in corrected]
        abstract_file.write_text(json.dumps(abstracts), encoding='utf-8')
        return db, run, old_file, corrected_file, abstract_file

    def test_corrected_items_precede_retirement_and_original_rows_remain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db, run, old_file, corrected_file, abstract_file = self.fixture(root)
            apply_records(old_file, run, root / 'old_import')
            result = apply(old_file, corrected_file, abstract_file, run, root / 'correction')
            self.assertEqual(2, result['abstract_counts']['abstracts_filled'])
            self.assertEqual([1], result['superseded_parse_article_ids'])
            conn = sqlite3.connect(db)
            self.assertEqual(('First Title Second Title', 1), conn.execute('SELECT title,is_duplicate FROM astar_articles WHERE id=1').fetchone())
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0 AND abstract IS NOT NULL').fetchone()[0])
            self.assertEqual(1, conn.execute("SELECT COUNT(*) FROM astar_article_sources WHERE raw_id='old-combined-item'").fetchone()[0])
            conn.close()

    def test_a_baseline_article_cannot_be_retired(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db, run, old_file, corrected_file, abstract_file = self.fixture(root, seed_baseline=True)
            with self.assertRaisesRegex(ValueError, 'baseline'):
                apply(old_file, corrected_file, abstract_file, run, root / 'refused')
            conn = sqlite3.connect(db)
            self.assertEqual([(1, 'First Title Second Title', 0)], conn.execute('SELECT id,title,is_duplicate FROM astar_articles').fetchall())
            conn.close()

    def test_verified_pdf_only_item_uses_the_actual_ingestion_interface(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db, run, old_file, corrected_file, abstract_file = self.fixture(root)
            apply_records(old_file, run, root / 'old_import')
            rows = json.loads(abstract_file.read_text(encoding='utf-8'))
            rows.append(dict(rows[0], source_raw_id='nzulr_abstract_item:additional', is_new_pdf_item=True,
                issue_title='Additional Case Note', verified_authors=['Anita Killeen'], archive_year=2020,
                month_label='June', source_issue_heading='Vol 29, No 1 June 2020'))
            abstract_file.write_text(json.dumps(rows), encoding='utf-8')
            result = apply(old_file, corrected_file, abstract_file, run, root / 'correction')
            self.assertEqual(1, result['abstract_counts']['new_pdf_items'])
            conn = sqlite3.connect(db)
            self.assertEqual(('Additional Case Note', None, '2020-06'),
                             conn.execute("SELECT title,publication_date,publication_month FROM astar_articles WHERE title='Additional Case Note'").fetchone())
            conn.close()
