"""Library issue dates and item boundaries are independent of blog dates."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.import_verified_library_contents import apply, load_verified
from scripts.import_verified_publisher_contents import apply as apply_publisher
from scripts.prepare_library_issue_metadata import JOURNAL, extract_post, reconcile_publisher
from services import abdc_astar_research_service as radar
from services.astar_history_service import digest, init_run


def post(html):
    return {'id': 99, 'date': '2026-02-01T10:00:00',
            'link': 'https://www.lawsociety.sk.ca/2026/02/01/library/',
            'content': {'rendered': html}}


class LibraryMetadataTests(unittest.TestCase):
    def test_inline_text_sibling_and_next_journal_boundaries(self):
        source = post('<p><b>' + JOURNAL + '</b></p><p><b>Volume 68, Number 1 (December 2023)</b></p>'
                      '<p>Title about <i>M&amp;A</i> / Alice Green and Bob Brown</p>'
                      '<ul><li>[Book Review] Book by Someone / Clara White</li></ul>'
                      '<p><strong>Other Journal</strong><br/>Volume 99, Number 1 (January 2026)</p>'
                      '<p>Wrong paper / Someone Else</p>')
        rows, issue = extract_post(source, Path('source.json'), 'hash')
        self.assertEqual(2, issue['record_count'])
        self.assertEqual('Title about M&A', rows[0]['title'])
        self.assertEqual(['Alice Green', 'Bob Brown'], rows[0]['authors'])
        self.assertEqual((2023, '2023-12', None),
                         (rows[0]['publication_year'], rows[0]['publication_month'], rows[0]['publication_date']))
        self.assertEqual(['Clara White'], rows[1]['authors'])
        self.assertEqual('book-review', rows[1]['record_type'])

    def test_missing_issue_year_does_not_use_blog_date(self):
        with self.assertRaises(ValueError):
            extract_post(post('<p>' + JOURNAL + '<br/>Volume 68, Number 1</p><p>Title / Author</p>'),
                         Path('source.json'), 'hash')

    def test_same_title_year_different_issues_have_distinct_identity(self):
        rows = [extract_post(post('<p>' + JOURNAL + '<br/>Volume 68, Number ' + str(i) +
                   ' (December 2023)<br/>Editorial / Alice Green</p>'), Path('source.json'), 'hash')[0][0]
                for i in (1, 2)]
        self.assertNotEqual(rows[0]['source_raw_id'], rows[1]['source_raw_id'])

    def test_publisher_matching_requires_issue_and_supplied_authors(self):
        row = extract_post(post('<p>' + JOURNAL + '<br/>Volume 68, Number 1 (December 2023)'
                                '<br/>Title / Alice Green</p>'), Path('source.json'), 'hash')[0][0]
        prior = dict(row, source_raw_id='publisher:item', authors=['Different Author'])
        with self.assertRaises(ValueError):
            reconcile_publisher([row], [prior])

    def test_import_replay_and_raw_change_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / 'corpus.db'
            journal = {'journal_title': JOURNAL, 'issn_print': '0319-3322', 'issn_online': '',
                'abdc_rating': 'A', 'abdc_version': '2025', 'discipline': 'Law',
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
            raw = root / 'source.json'
            source = post('<p>' + JOURNAL + '<br/>Volume 68, Number 1 (December 2023)'
                          '<br/>Editorial / Alice Green</p>')
            raw.write_text(json.dumps([source]), encoding='utf-8')
            rows, _ = extract_post(source, raw, digest(raw))
            rows[0]['status'] = 'VERIFIED_PUBLIC_LIBRARY_CONTENTS_ITEM'
            records = root / 'records.json'
            records.write_text(json.dumps(rows), encoding='utf-8')
            self.assertEqual([['INSERTED', 1]], apply(records, run, root / 'first')['dispositions'])
            self.assertEqual([['EXISTING_PRESERVED', 1]], apply(records, run, root / 'replay')['dispositions'])
            conn = sqlite3.connect(db)
            self.assertEqual([(2023, '2023-12', None)], conn.execute(
                'SELECT publication_year,publication_month,publication_date FROM astar_articles').fetchall())
            self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM astar_article_sources').fetchone()[0])
            self.assertEqual('institutional_library_metadata', conn.execute(
                'SELECT source_type FROM astar_article_sources').fetchone()[0])
            conn.close()
            raw.write_text('[]', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_verified(records)

    def test_corroborrated_publisher_item_is_preserved_with_higher_year_priority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            db = root / 'corpus.db'
            journal = {'journal_title': JOURNAL, 'issn_print': '0319-3322', 'issn_online': '',
                'abdc_rating': 'A', 'abdc_version': '2025', 'discipline': 'Law',
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
            pdf = root / 'contents.pdf'
            pdf.write_bytes(b'%PDF-fixture public contents')
            publisher = {'status': 'VERIFIED_PUBLIC_CONTENTS_ITEM', 'source_raw_id': 'publisher:item',
                'journal_title': JOURNAL, 'title': 'TITLE', 'publication_year': 2023,
                'publication_date': None, 'publication_month': '2023-12', 'date_precision': 'month',
                'volume': 68, 'issue': '1', 'authors': ['Alice Green'], 'abstract': None,
                'pdf_path': str(pdf), 'pdf_sha256': digest(pdf), 'source_url': 'https://publisher.example/contents.pdf'}
            publisher_path = root / 'publisher.json'
            publisher_path.write_text(json.dumps([publisher]), encoding='utf-8')
            apply_publisher(publisher_path, run, root / 'publisher-import')
            conn = sqlite3.connect(db)
            before_article = conn.execute('SELECT * FROM astar_articles').fetchall()
            before_class = conn.execute('SELECT * FROM astar_article_classifications').fetchall()
            before_year = conn.execute('SELECT * FROM astar_article_archive_years').fetchall()
            conn.close()
            source = post('<p>' + JOURNAL + '<br/>Volume 68, Number 1 (December 2023)'
                          '<br/>Title / Alice Green</p>')
            raw = root / 'source.json'
            raw.write_text(json.dumps([source]), encoding='utf-8')
            rows, _ = extract_post(source, raw, digest(raw))
            rows[0].update(status='VERIFIED_PUBLIC_LIBRARY_CONTENTS_ITEM',
                           corroborated_publisher_source_raw_id='publisher:item')
            records = root / 'records.json'
            records.write_text(json.dumps(rows), encoding='utf-8')
            self.assertEqual([['EXISTING_PRESERVED', 1]], apply(records, run, root / 'library-import')['dispositions'])
            conn = sqlite3.connect(db)
            self.assertEqual(before_article, conn.execute('SELECT * FROM astar_articles').fetchall())
            self.assertEqual(before_class, conn.execute('SELECT * FROM astar_article_classifications').fetchall())
            self.assertEqual(before_year, conn.execute('SELECT * FROM astar_article_archive_years').fetchall())
            self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM astar_article_sources').fetchone()[0])
            conn.close()
