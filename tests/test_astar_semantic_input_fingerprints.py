"""Input identity tracks effective text, including nonempty-to-nonempty changes."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.stage_astar_history_embeddings import verify
from services.astar_semantic_input_fingerprints import input_fingerprint, seed_input_matches, forced_ids


class SemanticInputFingerprintTests(unittest.TestCase):
    def test_nonempty_title_and_abstract_changes_invalidate_seed_vectors(self):
        before = input_fingerprint('Old title', 'Old nonempty abstract')
        self.assertFalse(seed_input_matches(before, input_fingerprint('New title', 'Old nonempty abstract')))
        self.assertFalse(seed_input_matches(before, input_fingerprint('Old title', 'Different nonempty abstract')))
        self.assertTrue(seed_input_matches(before, input_fingerprint('Old title', 'Old nonempty abstract')))

    def test_text_outside_original_truncation_does_not_invalidate_a_matching_input(self):
        prefix = 'a' * 1500
        self.assertTrue(seed_input_matches(input_fingerprint('Title', prefix + 'old tail'),
                                          input_fingerprint('Title', prefix + 'new tail')))

    def test_unknown_hash_is_never_certified_by_current_metadata(self):
        current = input_fingerprint('Title', 'Abstract')
        self.assertFalse(seed_input_matches(None, current))
        self.assertFalse(seed_input_matches(np.zeros(32, dtype=np.uint8), current))

    def test_forced_input_drift_ledger_uses_actual_positive_article_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'drift.json'
            path.write_text(json.dumps([{'article_id': 7}, {'article_id': 12}]), encoding='utf-8')
            self.assertEqual({7, 12}, forced_ids(path))
            path.write_text('[{"article_id": "7"}]', encoding='utf-8')
            with self.assertRaises(ValueError):
                forced_ids(path)

    def test_verifier_detects_changed_nonempty_abstract_with_unchanged_quality_mask(self):
        with tempfile.TemporaryDirectory() as temporary:
            pack = Path(temporary)
            db = pack / 'corpus.db'
            conn = sqlite3.connect(db)
            conn.executescript("CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,title TEXT,abstract TEXT,is_duplicate INTEGER,publication_year INTEGER); INSERT INTO astar_articles VALUES(1,'Title','Original nonempty abstract',0,2010);")
            conn.commit()
            conn.close()
            (pack / 'manifest.json').write_text(json.dumps({'db_path': str(db), 'target_count': 1}), encoding='utf-8')
            vector = np.zeros((1, 384), dtype=np.float32)
            vector[0, 0] = 1
            np.save(pack / 'astar_emb.npy', vector)
            np.save(pack / 'astar_emb_ids.npy', np.array([1], dtype=np.int64))
            np.save(pack / 'completed.npy', np.ones(1, dtype=np.uint8))
            np.save(pack / 'astar_emb_titleonly_ids.npy', np.array([], dtype=np.int64))
            np.save(pack / 'astar_emb_input_hashes.npy', input_fingerprint('Title', 'Original nonempty abstract')[None, :])
            first = verify(pack)
            self.assertEqual(0, first['input_fingerprints_changed'])
            conn = sqlite3.connect(db)
            conn.execute("UPDATE astar_articles SET abstract='Changed nonempty abstract'")
            conn.commit()
            conn.close()
            second = verify(pack)
            self.assertEqual(0, second['title_only_vectors_with_new_abstract'])
            self.assertEqual(1, second['input_fingerprints_changed'])
            self.assertEqual(0, second['input_fingerprints_missing_or_unknown'])
