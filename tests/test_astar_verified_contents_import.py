"""Year-only metadata and publisher identifiers must survive import/replay."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.import_verified_publisher_contents import (
    apply, validate_metadata_source, validate_publication_fields,
)
from services import abdc_astar_research_service as radar
from services.astar_history_service import digest, init_run


class VerifiedContentsImportTests(unittest.TestCase):
    def test_browser_readback_is_hash_checked_and_binds_publisher_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readback_path = root / 'issue_readback.json'
            issue_url = 'https://publisher.example/issue/2010-2'
            article_url = 'https://publisher.example/article/2922'
            item = {
                'publisher_article_id': 2922,
                'title': 'A Critical Appraisal of Remedies in the E.U. Microsoft Cases',
                'doi': '10.7916/cblr.v2010i2.2922',
                'authors': ['Nicholas Economides', 'Joannis Lianos'],
                'issue': '2',
                'issue_url': issue_url,
                'article_url': article_url,
                'publication_date': '2011-01-22',
                'publication_year': 2011,
                'publication_month': '2011-01',
                'date_precision': 'day',
                'archive_year': 2010,
            }
            snapshot = {
                'capture_method': 'browser_visible_issue_page_metadata_readback',
                'raw_html_saved': False,
                'source_urls': [issue_url, article_url],
                'items': [item],
            }
            readback_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
            row = {
                'metadata_format': 'publisher_browser_readback',
                'browser_readback_path': str(readback_path),
                'browser_readback_sha256': digest(readback_path),
                'publisher_article_id': 2922,
                'title': item['title'],
                'doi': item['doi'],
                'authors': item['authors'],
                'issue': '2',
                'issue_url': issue_url,
                'publisher_article_url': article_url,
                'source_url': issue_url,
                'publication_date': '2011-01-22',
                'publication_year': 2011,
                'publication_month': '2011-01',
                'date_precision': 'day',
                'archive_year': 2010,
            }
            self.assertEqual(digest(readback_path), validate_metadata_source(row))
            row['title'] = 'A different title'
            with self.assertRaises(ValueError):
                validate_metadata_source(row)

    def test_publication_year_and_archive_year_can_be_separate_with_evidence(self):
        row = {
            'publication_year': 2011,
            'publication_date': '2011-01-22',
            'publication_month': '2011-01',
            'date_precision': 'day',
            'archive_year': 2010,
            'issue_year_evidence': {
                'archive_year': 2010,
                'year_basis': 'publisher_issue_heading_and_recorded_issue_citation_year',
                'source_url': 'https://publisher.example/issue/2010-2',
            },
        }
        self.assertEqual(2010, validate_publication_fields(row))

        row['issue_year_evidence'] = {
            'archive_year': 2010,
            'year_basis': 'publisher_issue_heading_and_recorded_issue_citation_year',
        }
        with self.assertRaises(ValueError):
            validate_publication_fields(row)

        row['issue_year_evidence']['source_url'] = 'https://publisher.example/issue/2010-2'
        row['publication_year'] = 2012
        with self.assertRaises(ValueError):
            validate_publication_fields(row)

    def test_import_preserves_exact_publisher_date_and_distinct_issue_year(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / 'corpus.db'
            journal = {
                'journal_title': 'Columbia Business Law Review',
                'issn_print': '0898-0721',
                'issn_online': '1930-7934',
                'abdc_rating': 'A',
                'abdc_version': '2025',
                'discipline': 'Law',
                'is_active': 1,
                'source_table': 'fixture',
            }
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
            source_url = 'https://journals.library.columbia.edu/index.php/CBLR/issue/view/259'
            article_url = 'https://journals.library.columbia.edu/index.php/CBLR/article/view/2922'
            readback = {
                'capture_method': 'browser_visible_issue_page_metadata_readback',
                'raw_html_saved': False,
                'source_urls': [source_url, article_url],
                'items': [{
                    'publisher_article_id': 2922,
                    'title': 'A Critical Appraisal of Remedies in the E.U. Microsoft Cases',
                    'doi': '10.7916/cblr.v2010i2.2922',
                    'authors': ['Nicholas Economides', 'Joannis Lianos'],
                    'issue': '2',
                    'issue_url': source_url,
                    'article_url': article_url,
                    'publication_date': '2011-01-22',
                    'publication_year': 2011,
                    'publication_month': '2011-01',
                    'date_precision': 'day',
                    'archive_year': 2010,
                }],
            }
            readback_path = root / 'issue_readback.json'
            readback_path.write_text(json.dumps(readback, ensure_ascii=False), encoding='utf-8')
            record = {
                'status': 'VERIFIED_PUBLIC_CONTENTS_ITEM',
                'source_raw_id': 'cblr_ojs_article_id:2922',
                'publisher_article_id': 2922,
                'doi': '10.7916/cblr.v2010i2.2922',
                'journal_title': journal['journal_title'],
                'title': 'A Critical Appraisal of Remedies in the E.U. Microsoft Cases',
                'publication_year': 2011,
                'publication_date': '2011-01-22',
                'publication_month': '2011-01',
                'date_precision': 'day',
                'archive_year': 2010,
                'issue_year_evidence': {
                    'archive_year': 2010,
                    'year_basis': 'publisher_issue_heading_and_recorded_issue_citation_year',
                    'source_url': source_url,
                },
                'volume': 2010,
                'issue': '2',
                'authors': ['Nicholas Economides', 'Joannis Lianos'],
                'abstract': None,
                'record_type': 'journal-article',
                'metadata_format': 'publisher_browser_readback',
                'browser_readback_path': str(readback_path),
                'browser_readback_sha256': digest(readback_path),
                'source_url': source_url,
                'publisher_article_url': article_url,
                'source_name': 'Columbia Business Law Review official issue archive',
            }
            records = root / 'records.json'
            records.write_text(json.dumps([record], ensure_ascii=False), encoding='utf-8')

            result = apply(records, run, root / 'output')
            self.assertEqual(1, result['record_count'])
            self.assertEqual(0, result['exact_days_imputed'])
            self.assertEqual(1, result['publisher_publication_dates_supplied'])
            self.assertEqual(1, result['distinct_archive_years_supplied'])

            conn = sqlite3.connect(db)
            article = conn.execute(
                'SELECT doi,publication_date,publication_year,publication_month '
                'FROM astar_articles'
            ).fetchone()
            self.assertEqual(
                ('10.7916/cblr.v2010i2.2922', '2011-01-22', 2011, '2011-01'),
                article,
            )
            archive = conn.execute(
                'SELECT archive_year,year_basis,source_name FROM astar_article_archive_years'
            ).fetchone()
            self.assertEqual(
                (2010, 'publisher_issue_heading_and_recorded_issue_citation_year',
                 'Columbia Business Law Review official issue archive'),
                archive,
            )
            raw_json, parser_notes = conn.execute(
                'SELECT raw_json,parser_notes FROM astar_article_sources'
            ).fetchone()
            self.assertEqual(record, json.loads(raw_json))
            self.assertIn('publisher-reported publication_date=2011-01-22', parser_notes)
            self.assertNotIn('exact day unknown', parser_notes)
            conn.close()

    def test_html_and_year_anchor_are_independently_hash_checked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            html = root / 'contents.html'
            html.write_text('<dt>Paper title</dt>', encoding='utf-8')
            anchor = root / 'period.pdf'
            anchor.write_bytes(b'%PDF-fixture printed period')
            row = {'metadata_format': 'publisher_issue_html', 'source_html_path': str(html),
                'source_html_sha256': digest(html), 'archive_year_priority': 20,
                'issue_year_evidence': {'printed_year_document': str(anchor), 'printed_year_sha256': digest(anchor)}}
            self.assertEqual(digest(html), validate_metadata_source(row))
            anchor.write_bytes(b'%PDF-changed anchor')
            with self.assertRaises(ValueError):
                validate_metadata_source(row)

    def test_unsupported_metadata_or_priority_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.pdf'
            path.write_bytes(b'%PDF-fixture')
            row = {'pdf_path': str(path), 'pdf_sha256': digest(path), 'archive_year_priority': 99}
            with self.assertRaises(ValueError):
                validate_metadata_source(row)
            row.update(metadata_format='unverified_external_text', archive_year_priority=30)
            with self.assertRaises(ValueError):
                validate_metadata_source(row)

    def test_same_title_distinct_publisher_ids_stay_separate_and_dates_unknown(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);db = root / 'corpus.db'
            journal = {'journal_title': 'Australian Journal of Labour Law', 'issn_print': '1030-7222',
                'issn_online': '', 'abdc_rating': 'A', 'abdc_version': '2025', 'discipline': 'Law',
                'is_active': 1, 'source_table': 'fixture'}
            conn = sqlite3.connect(db);radar.ensure_astar_tables(conn)
            conn.execute('INSERT INTO abdc_astar_journals(%s) VALUES(%s)' %
                         (','.join(journal), ','.join('?' for _ in journal)), list(journal.values()))
            conn.commit();conn.close()
            scope = root / 'scope.json';scope.write_text(json.dumps([journal]), encoding='utf-8')
            run = root / 'run';init_run(run, db, 2010, '2026-10-06', scope)
            pdf = root / 'contents.pdf';pdf.write_bytes(b'%PDF-fixture public source')
            records = [{'status': 'VERIFIED_PUBLIC_CONTENTS_ITEM', 'source_raw_id': 'lexis_publication:item-'+str(i),
                'journal_title': journal['journal_title'], 'title': 'Editorial', 'publication_year': 2021,
                'publication_date': None, 'publication_month': None, 'date_precision': 'year',
                'volume': 34, 'issue': str(i), 'authors': [], 'abstract': None,
                'pdf_path': str(pdf), 'pdf_sha256': digest(pdf), 'source_url': 'https://publisher.example/same.pdf'} for i in (1, 2)]
            html = root / 'contents.html'
            html.write_text('<dt>Editorial</dt>', encoding='utf-8')
            records[1].pop('pdf_path')
            records[1].pop('pdf_sha256')
            records[1].update(metadata_format='publisher_issue_html', source_html_path=str(html),
                              source_html_sha256=digest(html), source_url='https://publisher.example/contents',
                              archive_year_priority=20)
            path = root / 'records.json';path.write_text(json.dumps(records), encoding='utf-8')
            first = apply(path, run, root / 'first')
            self.assertEqual([['INSERTED', 2]], first['dispositions'])
            apply(path, run, root / 'replay')
            conn = sqlite3.connect(db)
            self.assertEqual([(2021, None, None), (2021, None, None)], conn.execute('SELECT publication_year,publication_date,publication_month FROM astar_articles ORDER BY id').fetchall())
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM astar_article_sources WHERE raw_json IS NOT NULL').fetchone()[0])
            conn.close()
