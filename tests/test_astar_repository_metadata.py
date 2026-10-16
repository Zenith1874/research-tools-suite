"""Repository dates, submission status and actual access scope are distinct."""

import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_repository_metadata import osgoode_record, transcribed_record
from scripts.import_verified_repository_metadata import apply, load_verified
from services import abdc_astar_research_service as radar
from services.astar_history_service import init_run


SOURCE = {'source_url': 'https://digitalcommons.osgoode.yorku.ca/scholarly_works/1/',
          'raw_path': 'source.html.gz', 'sha256': 'fixture'}


class RepositoryMetadataTests(unittest.TestCase):
    def html(self, citation, date='2018', document_type='Article'):
        return ('<meta name="bepress_citation_title" content="Actual Title">'
                '<meta name="bepress_citation_author" content="Craig, Carys">'
                '<meta name="bepress_citation_online_date" content="2026/10/07">'
                '<h4>Document Type</h4><p>' + document_type + '</p>'
                '<h4>Publication Date</h4><p>' + date + '</p>'
                '<h4>Source Publication</h4><p>' + citation + '</p>'
                '<h4>Abstract</h4><p>Supplied description.</p>')

    def test_complete_citation_and_year_date_ignore_repository_online_date(self):
        row, reason = osgoode_record(self.html('30(2) Intellectual Property Journal 217 (2018)'), SOURCE)
        self.assertIsNone(reason)
        self.assertEqual((2018, None, None), (row['publication_year'], row['publication_month'], row['publication_date']))
        self.assertEqual(['Carys Craig'], row['authors'])
        self.assertEqual('Supplied description.', row['abstract'])

    def test_month_is_supplied_and_no_exact_day_is_invented(self):
        row, _ = osgoode_record(self.html('Intellectual Property Journal, 35(1), 7-35.', '11-2022'), SOURCE)
        self.assertEqual('2022-11', row['publication_month'])
        self.assertIsNone(row['publication_date'])

    def test_submitted_and_conflicting_year_items_are_not_admitted(self):
        row, reason = osgoode_record(self.html('Submitted to Intellectual Property Journal (IPJ)'), SOURCE)
        self.assertIsNone(row)
        self.assertEqual('UNCONFIRMED_JOURNAL_PUBLICATION', reason)
        row, reason = osgoode_record(self.html('30(2) Intellectual Property Journal 217 (2017)'), SOURCE)
        self.assertIsNone(row)
        self.assertEqual('REPORTED_YEAR_CONFLICT_NEEDS_RECONCILIATION', reason)

    def test_web_transcription_never_claims_downloaded_html_or_full_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'transcription.json'
            path.write_text('[]', encoding='utf-8')
            source = {'source_kind': 'WEB_PRIMARY_METADATA_TRANSCRIPTION', 'reading_scope': 'primary_page_rendered_metadata_only',
                'journal_title': 'New Zealand Journal of Taxation Law and Policy', 'title': 'Editorial',
                'reported_year': 2022, 'citation': 'Sawyer A, Tan LM (2022). Editorial. New Zealand Journal of Taxation Law and Policy. 28(2). 119-123.',
                'publisher_issue_notice_excerpt': 'Volume 28:2 June 2022', 'canonical_authors': ['Adrian Sawyer', 'Lin Mei Tan'],
                'authors_as_supplied': ['Sawyer, Adrian', 'Tan LM'], 'access_scope': {'direct_HTML_HTTP_status': 403},
                'source_url': 'https://ir.canterbury.ac.nz/items/fixture', 'full_text_reviewed': False}
            row = transcribed_record(source, path)
            self.assertEqual('2022-06', row['publication_month'])
            self.assertEqual(403, row['source_access_scope']['direct_HTML_HTTP_status'])
            self.assertEqual('primary_web_metadata_transcription', row['source_format'])
            with self.assertRaises(ValueError):
                transcribed_record(dict(source, full_text_reviewed=True), path)

    def test_distinct_item_ids_survive_import_replay_and_source_tampering_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / 'corpus.db'
            journal = {'journal_title': 'Intellectual Property Journal', 'issn_print': '0824-7064',
                'issn_online': '', 'abdc_rating': 'A', 'abdc_version': '2025', 'discipline': 'Law',
                'is_active': 1, 'source_table': 'fixture'}
            conn = sqlite3.connect(db)
            radar.ensure_astar_tables(conn)
            conn.execute('INSERT INTO abdc_astar_journals(%s) VALUES(%s)' %
                         (','.join(journal), ','.join('?' for _ in journal)), list(journal.values()))
            conn.commit()
            conn.close()
            scope = root / 'scope.json'
            scope.write_text(json.dumps([journal]), encoding='utf-8')
            run = root / 'run'
            init_run(run, db, 2010, '2026-10-06', scope)
            records = []
            for issue in (1, 2):
                raw = root / (str(issue) + '.html.gz')
                raw.write_bytes(gzip.compress(self.html(f'30({issue}) Intellectual Property Journal 217 (2018)').encode('utf-8'), mtime=0))
                source = dict(SOURCE, source_url=f'https://digitalcommons.osgoode.yorku.ca/scholarly_works/{issue}/',
                              raw_path=str(raw), sha256=hashlib.sha256(raw.read_bytes()).hexdigest())
                row, reason = osgoode_record(gzip.decompress(raw.read_bytes()), source)
                self.assertIsNone(reason)
                records.append(row)
            path = root / 'records.json'
            path.write_text(json.dumps(records), encoding='utf-8')
            self.assertEqual([['INSERTED', 2]], apply(path, run, root / 'first')['dispositions'])
            conn = sqlite3.connect(db)
            before = conn.execute('SELECT * FROM astar_articles ORDER BY id').fetchall()
            classifications = conn.execute('SELECT * FROM astar_article_classifications ORDER BY article_id').fetchall()
            conn.close()
            self.assertEqual([['EXISTING_PRESERVED', 2]], apply(path, run, root / 'replay')['dispositions'])
            conn = sqlite3.connect(db)
            self.assertEqual(before, conn.execute('SELECT * FROM astar_articles ORDER BY id').fetchall())
            self.assertEqual(classifications, conn.execute('SELECT * FROM astar_article_classifications ORDER BY article_id').fetchall())
            self.assertEqual([(None, None), (None, None)], conn.execute('SELECT publication_date,publication_month FROM astar_articles').fetchall())
            conn.close()
            raw.write_bytes(gzip.compress(b'changed source'))
            with self.assertRaises(ValueError):
                load_verified(path)
