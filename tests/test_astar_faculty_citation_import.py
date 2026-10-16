"""Source-only citation years remain explicit, reproducible fallback evidence."""

import gzip
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.collect_nyu_publication_metadata import parse_citations
from scripts.import_verified_faculty_citations import apply, load_verified, make_record
from services import abdc_astar_research_service as radar
from services.astar_archive_year_service import put_year
from services.astar_history_service import init_run


class FacultyCitationImportTests(unittest.TestCase):
    def test_replay_preserves_stronger_publisher_year_and_never_imputes_a_day(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / 'faculty.html.gz'
            html = '<h1>Listed Author</h1><li>"<a href="https://go.openathens.net/auth">Paper</a>," 40 Virginia Tax Review 395 (2021)</li>'
            raw.write_bytes(gzip.compress(html.encode('utf-8'), mtime=0))
            source = {'source_url': 'https://its.law.nyu.edu/facultyprofiles/index.cfm?personid=1',
                'raw_path': str(raw), 'sha256': hashlib.sha256(raw.read_bytes()).hexdigest()}
            observed, _ = parse_citations(html, source)
            record = make_record(observed[0])
            path = root / 'records.json'
            path.write_text(json.dumps([record]), encoding='utf-8')
            db = root / 'corpus.db'
            journal = {'journal_title': 'Virginia Tax Review', 'issn_print': '0734-3043', 'issn_online': '',
                'abdc_rating': 'A', 'abdc_version': '2025', 'discipline': 'Law', 'is_active': 1, 'source_table': 'fixture'}
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
            self.assertEqual([['INSERTED', 1]], apply(path, run, root / 'first')['dispositions'])
            conn = sqlite3.connect(db)
            aid = conn.execute('SELECT id FROM astar_articles').fetchone()[0]
            put_year(conn, aid, 2020, 'fixture_actual_print_year', 'publisher', 'https://publisher.example', {}, 30)
            conn.commit()
            before = conn.execute('SELECT * FROM astar_article_archive_years').fetchone()
            conn.close()
            self.assertEqual([['EXISTING_PRESERVED', 1]], apply(path, run, root / 'replay')['dispositions'])
            conn = sqlite3.connect(db)
            self.assertEqual(before, conn.execute('SELECT * FROM astar_article_archive_years').fetchone())
            self.assertEqual((2021, None, None), conn.execute('SELECT publication_year,publication_date,publication_month FROM astar_articles').fetchone())
            conn.close()
            raw.write_bytes(gzip.compress(b'<h1>Changed</h1>'))
            with self.assertRaises(ValueError):
                load_verified(path)

    def test_available_published_pdf_uses_the_stronger_metadata_workflow(self):
        with self.assertRaises(ValueError):
            make_record({'observed_article_url': 'https://its.law.nyu.edu/faculty/profiles/representiveFiles/file.pdf'})
