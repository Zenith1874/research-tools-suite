"""A validated backend resumes only unfinished rows in the existing pack."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts.stage_astar_history_embeddings import build
from services.astar_semantic_input_fingerprints import input_fingerprint


class OnnxPackResumeTests(unittest.TestCase):
    def test_completed_vectors_are_untouched_and_pending_input_uses_original_document_template(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / 'pack'
            pack.mkdir()
            (pack / 'seed').mkdir()
            db = Path(temporary) / 'corpus.db'
            conn = sqlite3.connect(db)
            conn.executescript('CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,title TEXT,abstract TEXT,is_duplicate INTEGER);')
            conn.executemany('INSERT INTO astar_articles VALUES(?,?,?,?)',
                             [(1, 'Already encoded', None, 0), (2, 'New title', 'Actual supplied abstract', 0)])
            conn.commit()
            conn.close()
            (pack / 'manifest.json').write_text(json.dumps({'db_path': str(db), 'target_count': 2}), encoding='utf-8')
            values = np.zeros((2, 384), dtype=np.float32)
            values[0, 4] = 1
            np.save(pack / 'astar_emb.npy', values)
            np.save(pack / 'astar_emb_ids.npy', np.array([1, 2], dtype=np.int64))
            np.save(pack / 'completed.npy', np.array([1, 0], dtype=np.uint8))
            np.save(pack / 'title_only_mask.npy', np.array([1, 0], dtype=np.uint8))
            np.save(pack / 'seed/astar_emb_ids.npy', np.array([1], dtype=np.int64))
            np.save(pack / 'seed/astar_emb.npy', values[:1])
            state = sqlite3.connect(pack / 'checkpoint.sqlite3')
            state.executescript('CREATE TABLE runs(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,pid INTEGER,status TEXT,details TEXT);'
                               'CREATE TABLE batches(id INTEGER PRIMARY KEY,first_position INTEGER,last_position INTEGER,copied_rows INTEGER,encoded_rows INTEGER,committed_at TEXT);')
            state.close()
            captured = []
            class FixtureEncoder:
                def __init__(self, *args):
                    pass
                def encode(self, texts, batch_size=4):
                    captured.extend(texts)
                    output = np.zeros((len(texts), 384), dtype=np.float32)
                    output[:, 7] = 1
                    return output
            with patch('services.astar_onnx_validation.validate_receipt', return_value={'sample_count': 128}), \
                 patch('services.astar_onnx_encoder.OnnxBgeEncoder', FixtureEncoder), \
                 patch('services.system_memory_gate.require_headroom', return_value=None):
                result = build(Path(temporary), pack, batch_size=4, threads=2, encoder_backend='onnx',
                               onnx_model='fixture.onnx', tokenizer_dir='fixture', backend_validation='proof.json')
            self.assertEqual(['New title. Actual supplied abstract'], captured)
            actual = np.load(pack / 'astar_emb.npy')
            np.testing.assert_array_equal(values[0], actual[0])
            self.assertEqual(1, actual[1, 7])
            np.testing.assert_array_equal([1, 1], np.load(pack / 'completed.npy'))
            self.assertEqual(2, result['completed_rows'])
            self.assertEqual('onnx', result['encoder_backend'])
            fingerprints = np.load(pack / 'astar_emb_input_hashes.npy')
            self.assertFalse(fingerprints[0].any())
            np.testing.assert_array_equal(input_fingerprint('New title', 'Actual supplied abstract'), fingerprints[1])

    def test_missing_backend_proof_is_rejected_before_pack_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary) / 'new-pack'
            with self.assertRaisesRegex(ValueError, 'verified numerical'):
                build(Path(temporary), pack, encoder_backend='onnx')
            self.assertFalse(pack.exists())

    def test_changed_nonempty_input_is_reencoded_and_unknown_seed_is_not_reused(self):
        for known_seed in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                pack = Path(temporary) / 'pack'
                pack.mkdir()
                (pack / 'seed').mkdir()
                db = Path(temporary) / 'corpus.db'
                conn = sqlite3.connect(db)
                conn.executescript("CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,title TEXT,abstract TEXT,is_duplicate INTEGER); INSERT INTO astar_articles VALUES(1,'Title','Changed nonempty abstract',0);")
                conn.commit()
                conn.close()
                (pack / 'manifest.json').write_text(json.dumps({'db_path': str(db), 'target_count': 1}), encoding='utf-8')
                values = np.zeros((1, 384), dtype=np.float32)
                values[0, 4] = 1
                np.save(pack / 'astar_emb.npy', values)
                np.save(pack / 'astar_emb_ids.npy', np.array([1], dtype=np.int64))
                np.save(pack / 'completed.npy', np.array([1 if known_seed else 0], dtype=np.uint8))
                np.save(pack / 'title_only_mask.npy', np.array([0], dtype=np.uint8))
                np.save(pack / 'seed/astar_emb_ids.npy', np.array([1], dtype=np.int64))
                np.save(pack / 'seed/astar_emb.npy', values)
                if known_seed:
                    previous = input_fingerprint('Title', 'Original nonempty abstract')[None, :]
                    np.save(pack / 'astar_emb_input_hashes.npy', previous)
                    np.save(pack / 'seed/astar_emb_input_hashes.npy', previous)
                state = sqlite3.connect(pack / 'checkpoint.sqlite3')
                state.executescript('CREATE TABLE runs(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,pid INTEGER,status TEXT,details TEXT); CREATE TABLE batches(id INTEGER PRIMARY KEY,first_position INTEGER,last_position INTEGER,copied_rows INTEGER,encoded_rows INTEGER,committed_at TEXT);')
                state.close()
                captured = []
                class FixtureEncoder:
                    def __init__(self, *args):
                        pass
                    def encode(self, texts, batch_size=4):
                        captured.extend(texts)
                        output = np.zeros((len(texts), 384), dtype=np.float32)
                        output[:, 7] = 1
                        return output
                with patch('services.astar_onnx_validation.validate_receipt', return_value={'sample_count': 128}), \
                     patch('services.astar_onnx_encoder.OnnxBgeEncoder', FixtureEncoder), \
                     patch('services.system_memory_gate.require_headroom', return_value=None):
                    result = build(Path(temporary), pack, batch_size=4, threads=2, encoder_backend='onnx',
                                   onnx_model='fixture.onnx', tokenizer_dir='fixture', backend_validation='proof.json')
                self.assertEqual(['Title. Changed nonempty abstract'], captured)
                self.assertEqual(0, result['copied_this_pass'])
                self.assertEqual(1, result['encoded_this_pass'])
                self.assertEqual(1, np.load(pack / 'astar_emb.npy')[0, 7])
