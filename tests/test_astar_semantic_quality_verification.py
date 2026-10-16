"""Coverage by ID is insufficient when a title-only row acquired an abstract."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import numpy as np
from scripts.stage_astar_history_embeddings import verify


class SemanticQualityVerificationTests(unittest.TestCase):
    def test_verifier_detects_late_abstract_without_losing_valid_id_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            db_path = folder / 'articles.db'
            with closing(sqlite3.connect(db_path)) as db:
                db.executescript('''CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,
                    title TEXT,abstract TEXT,is_duplicate INTEGER,publication_year INTEGER);
                    INSERT INTO astar_articles VALUES(1,'A 2010 paper',NULL,0,2010);''')
            (folder / 'manifest.json').write_text(json.dumps({'db_path': str(db_path), 'target_count': 1}), encoding='utf-8')
            vector = np.zeros((1, 384), dtype='float32')
            vector[0, 0] = 1.0
            np.save(folder / 'astar_emb.npy', vector)
            np.save(folder / 'astar_emb_ids.npy', np.array([1], dtype='int64'))
            np.save(folder / 'completed.npy', np.ones(1, dtype='uint8'))
            np.save(folder / 'astar_emb_titleonly_ids.npy', np.array([1], dtype='int64'))
            first = verify(folder)
            self.assertEqual(0, first['title_only_vectors_with_new_abstract'])
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("UPDATE astar_articles SET abstract='An actual supplied abstract' WHERE id=1")
                db.commit()
            second = verify(folder)
            self.assertEqual(1, second['title_only_vectors_with_new_abstract'])
            self.assertEqual(0, second['live_ids_not_yet_in_pack'])
            self.assertEqual(0, second['invalid_or_unnormalized_rows'])


if __name__ == '__main__':
    unittest.main()
