"""Isolated preservation, failure and new-only score contracts for routine deltas."""

import ast
from contextlib import ExitStack, closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from datetime import datetime

import numpy as np

from services import astar_safe_semantic_update as safe
from services import astar_semantic_backend as backend
from services import astar_semantic_service as semantic


class FixtureEncoder:
    validation = {'fixture': True}
    runtime_paths = {}

    def encode(self, texts, batch_size=4, normalize_embeddings=True):
        rows = np.zeros((len(texts), 384), dtype=np.float32)
        for index, text in enumerate(texts):
            rows[index, int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], 'little') % 384] = 1
        return rows


class SafeSemanticUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.db = self.root / 'fixture.db'
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,title TEXT,abstract TEXT,
                    is_duplicate INTEGER,updated_at TEXT,created_at TEXT);
                CREATE TABLE astar_article_classifications(article_id INTEGER PRIMARY KEY,
                    semantic_relevance REAL,classified_at TEXT,label TEXT);
                INSERT INTO astar_articles VALUES(1,'First',NULL,0,'old','old');
                INSERT INTO astar_articles VALUES(3,'Third','Original abstract',0,'old','old');
                INSERT INTO astar_article_classifications VALUES(1,72,'old','reviewed');
                INSERT INTO astar_article_classifications VALUES(3,NULL,'old','pending');
            ''')
        self.encoder = FixtureEncoder()
        self.base_ids = np.array([1, 3], dtype=np.int64)
        self.base_vectors = self.encoder.encode(['First', 'Third. Original abstract'])
        np.save(self.data / 'astar_emb.npy', self.base_vectors)
        np.save(self.data / 'astar_emb_ids.npy', self.base_ids)
        np.save(self.data / 'astar_emb_input_hashes.npy', np.stack([
            np.frombuffer(safe.fingerprint('First', None), dtype=np.uint8),
            np.frombuffer(safe.fingerprint('Third', 'Original abstract'), dtype=np.uint8)]))
        np.save(self.data / 'astar_emb_titleonly_ids.npy', np.array([1], dtype=np.int64))
        (self.data / 'astar_emb_meta.json').write_text(json.dumps({
            'model': 'BAAI/bge-small-en-v1.5', 'encoder_backend': 'onnx', 'dim': 384,
            'count': 2, 'title_only_count': 1, 'input_fingerprint_schema': safe.SCHEMA,
            'safe_update_receipt': str(self.data / 'seed_receipt.json')}), encoding='utf-8')
        (self.data / 'seed_receipt.json').write_text(json.dumps({'success': True,
            'active_asset_hashes': self.asset_hashes()}), encoding='utf-8')
        self.factory = Mock(return_value=self.encoder)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(safe, 'require_encoder_headroom', return_value=None))
        self.stack.enter_context(patch.object(safe.shutil, 'disk_usage', return_value=SimpleNamespace(free=20 * 2**30)))

    def change_source(self, new_score=None):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE astar_articles SET abstract='Filled abstract',updated_at='new' WHERE id=1")
            conn.execute("UPDATE astar_articles SET abstract='Changed full abstract',updated_at='new' WHERE id=3")
            conn.execute("INSERT INTO astar_articles VALUES(5,'New title',NULL,0,'new','new')")
            conn.execute('INSERT INTO astar_article_classifications VALUES(5,?,?,?)', (new_score, 'new', 'candidate'))

    def run_update(self, **kwargs):
        return safe.update_embeddings(self.db, self.data, encoder_factory=self.factory, **kwargs)

    def asset_hashes(self):
        return {name: safe.digest(self.data / name) for name in safe.NAMES}

    def test_unchanged_plan_is_read_only_and_never_loads_model(self):
        before = self.asset_hashes()
        result = self.run_update(apply=False)
        self.assertEqual(0, result['delta_rows'])
        self.assertFalse(result['model_loaded'])
        self.assertFalse((self.data / 'astar_semantic_update.lock').exists())
        self.assertEqual(before, self.asset_hashes())
        self.factory.assert_not_called()

    def test_changed_full_abstracts_new_rows_and_baseline_scores_are_preserved(self):
        self.change_source()
        original_load = np.load

        def no_full_matrix_load(path, *args, **kwargs):
            if Path(path).name == 'astar_emb.npy':
                raise AssertionError('Routine update must stream the matrix instead of loading it')
            return original_load(path, *args, **kwargs)

        with patch.object(safe.np, 'load', side_effect=no_full_matrix_load):
            result = self.run_update()
        self.assertEqual((1, 2, 1), (result['encoded'], result['refreshed'], result['scored_new']))
        self.assertEqual([1, 3, 5], np.load(self.data / 'astar_emb_ids.npy').tolist())
        self.assertEqual([5], np.load(self.data / 'astar_emb_titleonly_ids.npy').tolist())
        expected = self.encoder.encode(['First. Filled abstract', 'Third. Changed full abstract', 'New title'])
        np.testing.assert_array_equal(expected, np.load(self.data / 'astar_emb.npy'))
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual([(1, 72.0, 'reviewed'), (3, None, 'pending')], conn.execute(
                'SELECT article_id,semantic_relevance,label FROM astar_article_classifications WHERE article_id<5 ORDER BY article_id').fetchall())
            self.assertIsNotNone(conn.execute('SELECT semantic_relevance FROM astar_article_classifications WHERE article_id=5').fetchone()[0])
        before = Path(result['backup_dir'])
        np.testing.assert_array_equal(self.base_vectors, np.load(before / 'astar_emb.npy'))
        calls = self.factory.call_count
        again = self.run_update()
        self.assertEqual(0, again['delta_rows'])
        self.assertEqual(calls, self.factory.call_count)

    def test_external_before_image_root_preserves_atomic_candidate_layout(self):
        self.change_source()
        base_hashes = self.asset_hashes()
        external_backup_root = self.root / 'external_backups'
        result = self.run_update(backup_root=external_backup_root)
        before = Path(result['backup_dir'])
        run = Path(result['run_dir'])
        self.assertTrue(before.is_relative_to(external_backup_root))
        self.assertFalse((run / 'before').exists())
        self.assertEqual(base_hashes, {
            name: safe.digest(before / name) for name in safe.NAMES
        })
        intent = json.loads((run / 'activation_intent.json').read_text(encoding='utf-8'))
        self.assertEqual(str(before), intent['before_directory'])

    def test_existing_new_score_is_not_overwritten(self):
        self.change_source(new_score=93)
        result = self.run_update()
        self.assertEqual(0, result['scored_new'])
        self.assertEqual(1, result['existing_new_scores_preserved'])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(93, conn.execute('SELECT semantic_relevance FROM astar_article_classifications WHERE article_id=5').fetchone()[0])

    def test_accepted_empty_input_is_preserved_but_new_empty_input_is_held(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE astar_articles SET title='',abstract=NULL WHERE id=3")
        hashes = np.load(self.data / 'astar_emb_input_hashes.npy')
        hashes[1] = np.frombuffer(safe.fingerprint('', None), dtype=np.uint8)
        np.save(self.data / 'astar_emb_input_hashes.npy', hashes)
        np.save(self.data / 'astar_emb.npy', self.encoder.encode(['First', '']))
        np.save(self.data / 'astar_emb_titleonly_ids.npy', np.array([1, 3], dtype=np.int64))
        path = self.data / 'astar_emb_meta.json'
        metadata = json.loads(path.read_text(encoding='utf-8'))
        metadata['title_only_count'] = 2
        path.write_text(json.dumps(metadata), encoding='utf-8')
        self.assertEqual(0, self.run_update(apply=False)['delta_rows'])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("INSERT INTO astar_articles VALUES(5,'',NULL,0,'new','new')")
        with self.assertRaisesRegex(ValueError, 'no encodable text'):
            self.run_update(apply=False)
        self.factory.assert_not_called()

    def test_unknown_fingerprints_and_large_delta_never_trigger_model(self):
        self.change_source()
        before = self.asset_hashes()
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.run_update(max_delta_rows=1)
        self.assertEqual(before, self.asset_hashes())
        values = np.load(self.data / 'astar_emb_input_hashes.npy')
        values[0] = 0
        np.save(self.data / 'astar_emb_input_hashes.npy', values)
        with self.assertRaisesRegex(ValueError, 'unknown'):
            self.run_update()
        self.factory.assert_not_called()

    def test_ineligible_old_record_is_held_for_review(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('UPDATE astar_articles SET is_duplicate=1 WHERE id=1')
        before = self.asset_hashes()
        with self.assertRaisesRegex(ValueError, 'reviewed recovery'):
            self.run_update()
        self.assertEqual(before, self.asset_hashes())
        self.factory.assert_not_called()

    def test_changed_but_normalized_matrix_cannot_become_an_accepted_seed(self):
        self.change_source()
        values = self.base_vectors.copy()
        values[0] = np.roll(values[0], 1)
        np.save(self.data / 'astar_emb.npy', values)
        before = self.asset_hashes()
        with self.assertRaisesRegex(ValueError, 'seed asset hash mismatch'):
            self.run_update()
        self.assertEqual(before, self.asset_hashes())
        self.factory.assert_not_called()

    def test_external_source_commit_during_staging_leaves_live_assets_unchanged(self):
        self.change_source()
        before = self.asset_hashes()
        original = safe.stage_pack

        def change_after_stage(*args, **kwargs):
            original(*args, **kwargs)
            with closing(sqlite3.connect(self.db)) as conn, conn:
                conn.execute("UPDATE astar_articles SET title='Concurrent writer',updated_at='later' WHERE id=3")

        with patch.object(safe, 'stage_pack', side_effect=change_after_stage):
            with self.assertRaisesRegex(RuntimeError, 'changed during'):
                self.run_update()
        self.assertEqual(before, self.asset_hashes())
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertIsNone(conn.execute('SELECT semantic_relevance FROM astar_article_classifications WHERE article_id=5').fetchone()[0])

    def test_partial_file_activation_rolls_back_vectors_and_score_transaction(self):
        self.change_source()
        before = self.asset_hashes()
        original = safe.os.replace
        count = 0

        def fail_second_candidate(source, target):
            nonlocal count
            if Path(source).parent.name == 'candidate':
                count += 1
                if count == 2:
                    raise OSError('fixture replacement failure')
            return original(source, target)

        with patch.object(safe.os, 'replace', side_effect=fail_second_candidate):
            with self.assertRaisesRegex(OSError, 'replacement failure'):
                self.run_update()
        self.assertEqual(before, self.asset_hashes())
        self.assertEqual(1, len(list((self.data / 'astar_semantic_updates').glob('*/rolled_back.json'))))
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertIsNone(conn.execute('SELECT semantic_relevance FROM astar_article_classifications WHERE article_id=5').fetchone()[0])
        self.assertTrue(self.run_update()['success'])

    def test_unfinished_journal_stops_a_second_writer(self):
        run = self.data / 'astar_semantic_updates' / 'interrupted'
        run.mkdir(parents=True)
        (run / 'activation_intent.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'needs review'):
            self.run_update()
        self.factory.assert_not_called()


class SafeBackendAndSchedulerTests(unittest.TestCase):
    def test_accepted_onnx_generation_does_not_import_pytorch_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            metadata = Path(temporary) / 'meta.json'
            metadata.write_text(json.dumps({'encoder_backend': 'onnx'}), encoding='utf-8')
            selected = object()
            with patch.object(semantic, 'META_PATH', str(metadata)), patch.object(backend, 'load_verified_model', return_value=selected) as loader:
                self.assertIs(selected, semantic._load_model())
                loader.assert_called_once_with(semantic.DATA_DIR, threads=2)

    def test_onnx_adapter_keeps_batches_bounded_and_normalized(self):
        fake = Mock()
        fake.encode.return_value = np.ones((1, 384), dtype=np.float32)
        with patch.object(backend, 'require_encoder_headroom'), patch.object(backend, 'OnnxBgeEncoder', return_value=fake):
            model = backend.VerifiedOnnxModel('model', 'tokenizer', {})
            model.encode(['query'], batch_size=256, normalize_embeddings=True)
            fake.encode.assert_called_once_with(['query'], batch_size=4)
            with self.assertRaisesRegex(ValueError, 'normalized'):
                model.encode(['query'], normalize_embeddings=False)

    def test_scheduler_registers_and_serializes_the_safe_semantic_job(self):
        class EndIteration(Exception):
            pass

        class Clock:
            sleeps = 0
            def monotonic(self): return 0
            def sleep(self, seconds):
                self.sleeps += 1
                if self.sleeps > 1: raise EndIteration()

        server = Path(__file__).resolve().parents[1] / 'server.py'
        tree = ast.parse(server.read_text(encoding='utf-8'))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('_run_update_job', 'astar_scheduler_thread')]
        namespace = {'threading': threading, 'datetime': datetime, 'time': Clock(),
            'os': SimpleNamespace(environ={'ASTAR_INITIAL_DELAY_SECONDS': '0', 'LLM_AUTO': '0', 'AFFIL_AUTO': '0', 'EMB_AUTO': '1'},
                                  path=SimpleNamespace(exists=lambda path: True)),
            'log': Mock(), '_UPDATE_LOCK': threading.Lock(), '_JOBS_LOCK': threading.Lock(), '_JOBS': {},
            '_data_cache_clear': Mock(), 'check_and_record_new_periods': Mock(), 'DB_PATH': 'not-opened',
            'update_astar_recent_articles': lambda days: {'articles_inserted': 1, 'articles_updated': 2},
            'deduplicate_articles': Mock(), 'llm_classify_articles': Mock()}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(server), 'exec'), namespace)

        def semantic_job():
            self.assertTrue(namespace['_UPDATE_LOCK'].locked())
            self.assertEqual('running', namespace['_JOBS']['astar_semantic']['status'])
            return {'success': True, 'encoded': 1, 'refreshed': 2, 'scored_new': 1}

        with patch.object(semantic, 'build_embeddings', side_effect=semantic_job), patch.object(
                semantic, 'compute_semantic_relevance', side_effect=AssertionError('Legacy full score pass must not run')):
            with self.assertRaises(EndIteration):
                namespace['astar_scheduler_thread']()
        self.assertEqual('done', namespace['_JOBS']['astar_semantic']['status'])
        self.assertFalse(namespace['_UPDATE_LOCK'].locked())


if __name__ == '__main__':
    unittest.main()
