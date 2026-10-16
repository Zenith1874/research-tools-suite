"""Count-drift recovery preserves the original scope, cursors and raw evidence."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_astar_count_recovery import prepare
from scripts.bridge_astar_count_recovery import bridge
from services.astar_history_service import digest


class CountRecoveryTests(unittest.TestCase):
    def fixture(self, root, attempts=3):
        parent = root / 'parent'
        parent.mkdir()
        snapshot = root / 'original.db'
        snapshot.write_bytes(b'fixture immutable baseline')
        (parent / 'journals.json').write_text(json.dumps([{'history_key': 'fixture', 'journal_title': 'Fixture Journal'}]), encoding='utf-8')
        (parent / 'manifest.json').write_text(json.dumps({'snapshot_path': str(snapshot), 'snapshot_sha256': digest(snapshot),
            'from_date': '2010-01-01', 'to_date': '2026-10-06', 'journal_count': 1}), encoding='utf-8')
        raw = parent / 'raw/openalex-fixture'
        raw.mkdir(parents=True)
        (raw / 'page_000002.json.gz').write_bytes(b'original failed raw response retained')
        state = sqlite3.connect(parent / 'checkpoint.sqlite3')
        state.execute('CREATE TABLE units(unit_key TEXT PRIMARY KEY,journal_key TEXT,provider TEXT,status TEXT,cursor TEXT,next_page INTEGER,expected_count INTEGER,observed_count INTEGER,not_before REAL,error TEXT,updated_at TEXT,attempts INTEGER)')
        state.execute('INSERT INTO units VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            ('openalex-fixture', 'fixture', 'openalex', 'ERROR', 'original-cursor', 2, 3, 1, 0,
             'RuntimeError: source count changed during pagination: 3 -> 4', 'old timestamp', attempts))
        state.commit()
        state.close()
        return parent

    def test_fresh_auxiliary_cursor_retains_original_parent_and_reuses_original_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self.fixture(root)
            prepare(parent, 'openalex-fixture', root / 'recovery')
            old = sqlite3.connect(parent / 'checkpoint.sqlite3')
            self.assertEqual(('ERROR', 'original-cursor', 2), old.execute('SELECT status,cursor,next_page FROM units').fetchone())
            old.close()
            new = sqlite3.connect(root / 'recovery/checkpoint.sqlite3')
            self.assertEqual(('PENDING', '*', 1, 0), new.execute('SELECT status,cursor,next_page,observed_count FROM units').fetchone())
            new.close()
            manifest = json.loads((root / 'recovery/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(str(root / 'original.db'), manifest['snapshot_path'])
            self.assertEqual('2026-10-06', manifest['to_date'])
            self.assertEqual(b'original failed raw response retained', (parent / 'raw/openalex-fixture/page_000002.json.gz').read_bytes())

    def test_an_automatically_retryable_unit_cannot_be_forked_as_terminal_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self.fixture(root, attempts=1)
            with self.assertRaises(ValueError):
                prepare(parent, 'openalex-fixture', root / 'recovery')
            self.assertFalse((root / 'recovery').exists())

    def bridge_fixture(self, root, replace_original_mapping=False):
        parent = self.fixture(root)
        state = sqlite3.connect(parent / 'checkpoint.sqlite3')
        state.executescript('CREATE TABLE pages(unit_key TEXT,page INTEGER,path TEXT,sha256 TEXT,row_count INTEGER,expected_count INTEGER,next_cursor TEXT,committed_at TEXT,PRIMARY KEY(unit_key,page));'
                            'CREATE TABLE records(unit_key TEXT,source_id TEXT,article_id INTEGER,disposition TEXT,publication_year INTEGER,record_type TEXT,date_precision TEXT,PRIMARY KEY(unit_key,source_id));'
                            'CREATE TABLE events(id INTEGER PRIMARY KEY,created_at TEXT,event TEXT,details TEXT);')
        old_page = parent / 'raw/openalex-fixture/page_000001.json.gz'
        old_page.write_bytes(b'original first page')
        state.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?)', ('openalex-fixture', 1,
            'raw/openalex-fixture/page_000001.json.gz', digest(old_page), 1, 3, 'old-cursor', 'old-time'))
        state.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)', ('openalex-fixture','W1',1,'ORIGINAL',2020,'article','year'))
        state.commit()
        state.close()
        recovery = parent / 'recovery'
        prepare(parent, 'openalex-fixture', recovery)
        state = sqlite3.connect(recovery / 'checkpoint.sqlite3')
        for page in (1, 2):
            raw = recovery / ('page' + str(page) + '.gz')
            raw.write_bytes(('full recovered page ' + str(page)).encode())
            state.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?)',
                ('openalex-fixture',page,raw.name,digest(raw),2,4,None,'new-time'))
        for source in range(1, 5):
            aid = 99 if source == 1 and replace_original_mapping else source
            state.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)', ('openalex-fixture','W'+str(source),aid,'RECOVERED',2020,'article','year'))
        state.execute("UPDATE units SET status='COMPLETE',cursor=NULL,next_page=3,expected_count=4,observed_count=4,error=NULL")
        state.commit()
        state.close()
        return parent, recovery

    def test_full_rescan_bridge_preserves_original_rows_and_evidence_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent, recovery = self.bridge_fixture(Path(temporary))
            result = bridge(parent, recovery, parent / 'bridge-audit')
            self.assertEqual(4, result['unique_source_records'])
            state = sqlite3.connect(parent / 'checkpoint.sqlite3')
            self.assertEqual(('COMPLETE',4,5), state.execute('SELECT status,expected_count,observed_count FROM units').fetchone())
            self.assertEqual('ORIGINAL', state.execute("SELECT disposition FROM records WHERE source_id='W1'").fetchone()[0])
            self.assertEqual(3, state.execute('SELECT COUNT(*) FROM pages').fetchone()[0])
            state.close()
            self.assertEqual(b'original failed raw response retained', (parent / 'raw/openalex-fixture/page_000002.json.gz').read_bytes())

    def test_bridge_rejects_changed_original_mapping_without_parent_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent, recovery = self.bridge_fixture(Path(temporary), replace_original_mapping=True)
            with self.assertRaisesRegex(ValueError, 'mappings'):
                bridge(parent, recovery, parent / 'bridge-audit')
            state = sqlite3.connect(parent / 'checkpoint.sqlite3')
            self.assertEqual(('ERROR','original-cursor'), state.execute('SELECT status,cursor FROM units').fetchone())
            self.assertEqual(1, state.execute('SELECT COUNT(*) FROM records').fetchone()[0])
            state.close()
