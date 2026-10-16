"""Derived scores must never modify the original research classifications."""

import sqlite3
import json
import sys
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.score_astar_history_semantics import apply_scores, score_pack
from services.astar_semantic_input_fingerprints import input_fingerprint


class HistoryScoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'fixture.db'
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript('''
                CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,is_duplicate INTEGER,title TEXT);
                CREATE TABLE astar_article_classifications(article_id INTEGER PRIMARY KEY,
                    semantic_relevance REAL,classification_method TEXT);
                INSERT INTO astar_articles VALUES(1,0,'Original'),(2,0,'New'),(3,1,'Duplicate');
                INSERT INTO astar_article_classifications VALUES(1,NULL,'llm'),(2,NULL,'rules'),(3,NULL,'rules');
            ''')

    def rows(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM astar_article_classifications ORDER BY article_id').fetchall()

    def test_new_score_leaves_original_null_and_paid_decision_untouched(self):
        self.assertEqual(1, apply_scores(self.path, 1, [(73.4, 2)]))
        self.assertEqual([(1, None, 'llm'), (2, 73.4, 'rules'), (3, None, 'rules')], self.rows())

    def test_protected_id_rejects_and_rolls_back_the_whole_application(self):
        before = self.rows()
        with self.assertRaises(ValueError):
            apply_scores(self.path, 1, [(73.4, 2), (82.0, 1)])
        self.assertEqual(before, self.rows())

    def test_ineligible_id_rejects_and_rolls_back_the_whole_application(self):
        before = self.rows()
        with self.assertRaises(ValueError):
            apply_scores(self.path, 1, [(73.4, 2), (82.0, 3)])
        self.assertEqual(before, self.rows())

    def scoring_pack(self, unknown=False):
        import numpy as np
        root = Path(self.temporary.name)
        run_dir, pack_dir = root / 'run', root / 'pack'
        run_dir.mkdir()
        pack_dir.mkdir()
        (run_dir / 'manifest.json').write_text('{}', encoding='utf-8')
        (pack_dir / 'manifest.json').write_text(json.dumps(
            {'db_path': str(self.path), 'target_count': 2}), encoding='utf-8')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('ALTER TABLE astar_articles ADD COLUMN abstract TEXT')
            db.execute('ALTER TABLE astar_articles ADD COLUMN publication_year INTEGER')
            db.execute("UPDATE astar_articles SET abstract='Current nonempty abstract',publication_year=2020")
            db.commit()
        np.save(pack_dir / 'astar_emb_ids.npy', np.array([1, 2], dtype=np.int64))
        vectors = np.zeros((2, 384), dtype=np.float32)
        vectors[:, 0] = 1
        np.save(pack_dir / 'astar_emb.npy', vectors)
        np.save(pack_dir / 'completed.npy', np.ones(2, dtype=np.uint8))
        np.save(pack_dir / 'title_only_mask.npy', np.zeros(2, dtype=np.uint8))
        hashes = np.stack([input_fingerprint('Original', 'Earlier nonempty abstract'),
                           input_fingerprint('New', 'Current nonempty abstract')])
        if unknown:
            hashes[0] = 0
        np.save(pack_dir / 'astar_emb_input_hashes.npy', hashes)
        return run_dir, pack_dir

    def test_changed_nonempty_input_blocks_scores_before_model_loading(self):
        run_dir, pack_dir = self.scoring_pack()
        before = self.rows()
        with patch.dict(sys.modules, {'torch': None, 'sentence_transformers': None}):
            with self.assertRaisesRegex(ValueError, 'complete verified pack'):
                score_pack(run_dir, pack_dir, apply=True)
        evidence = json.loads(next(pack_dir.glob('verification_*.json')).read_text(encoding='utf-8'))
        self.assertEqual(1, evidence['input_fingerprints_changed'])
        self.assertEqual(0, evidence['live_ids_not_yet_in_pack'])
        self.assertEqual(before, self.rows())
        self.assertFalse((run_dir / 'semantic_score_runs').exists())

    def test_unknown_legacy_input_blocks_scores_before_model_loading(self):
        run_dir, pack_dir = self.scoring_pack(unknown=True)
        with patch.dict(sys.modules, {'torch': None, 'sentence_transformers': None}):
            with self.assertRaisesRegex(ValueError, 'complete verified pack'):
                score_pack(run_dir, pack_dir)
        evidence = json.loads(next(pack_dir.glob('verification_*.json')).read_text(encoding='utf-8'))
        self.assertEqual(1, evidence['input_fingerprints_missing_or_unknown'])
        self.assertEqual(0, evidence['input_fingerprints_changed'])


if __name__ == '__main__':
    unittest.main()
