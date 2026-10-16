"""Completed staged assets must replace cached search IDs without a restart."""

import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from services import astar_semantic_service as semantic


class SemanticGenerationTests(unittest.TestCase):
    def test_search_cards_preserve_string_and_object_author_formats(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture.db'
            with closing(sqlite3.connect(path)) as db:
                db.executescript('''
                    CREATE TABLE astar_articles(id INTEGER,title TEXT,abstract TEXT,journal_title TEXT,
                        publication_date TEXT,publication_year INTEGER,publication_month TEXT,
                        doi TEXT,url TEXT,cited_by_count INTEGER,authors_json TEXT);
                    CREATE TABLE astar_article_classifications(article_id INTEGER,relevance_score REAL,broad_area TEXT);
                ''')
                for identifier, authors in ((1, ['First Author', 'Second Author']), (2, [{'name': 'Object Author'}])):
                    db.execute('INSERT INTO astar_articles VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                               (identifier, 'A paper', None, 'A journal', None, 2026, '2026-08', None, None, 0, json.dumps(authors)))
                db.commit()
            with patch.object(semantic, 'DB_PATH', str(path)):
                cards = semantic._hydrate_articles([1, 2], {1: 0.9, 2: 0.8})
            self.assertEqual(['First Author', 'Second Author'], cards[0]['authors'])
            self.assertEqual(['Object Author'], cards[1]['authors'])
            self.assertIsNone(cards[0]['publication_date'])
            self.assertEqual(2026, cards[0]['publication_year'])
            self.assertEqual('2026-08', cards[0]['publication_month'])

    def test_metadata_last_generation_reloads_cached_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            emb, ids, meta = directory / 'emb.npy', directory / 'ids.npy', directory / 'meta.json'
            np.save(emb, np.ones((2, 384), dtype='float32'))
            np.save(ids, np.array([1, 2]))
            meta.write_text(json.dumps({'count': 2}), encoding='utf-8')
            state = {'model': object(), 'emb': None, 'ids': None, 'id2idx': None, 'asset_signature': None}
            with patch.object(semantic, 'EMB_PATH', str(emb)), patch.object(semantic, 'IDS_PATH', str(ids)), \
                 patch.object(semantic, 'META_PATH', str(meta)), patch.object(semantic, '_STATE', state):
                self.assertTrue(semantic._ensure_loaded())
                self.assertEqual([1, 2], state['ids'].tolist())
                np.save(emb, np.ones((3, 384), dtype='float32'))
                np.save(ids, np.array([1, 2, 3]))
                meta.write_text(json.dumps({'count': 3, 'generation': 'new'}), encoding='utf-8')
                self.assertTrue(semantic._ensure_loaded())
                self.assertEqual([1, 2, 3], state['ids'].tolist())

    def test_incomplete_replacement_retains_loaded_generation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            emb, ids, meta = directory / 'emb.npy', directory / 'ids.npy', directory / 'meta.json'
            np.save(emb, np.ones((2, 384), dtype='float32'))
            np.save(ids, np.array([1, 2]))
            meta.write_text(json.dumps({'count': 2}), encoding='utf-8')
            state = {'model': object(), 'emb': None, 'ids': None, 'id2idx': None, 'asset_signature': None}
            with patch.object(semantic, 'EMB_PATH', str(emb)), patch.object(semantic, 'IDS_PATH', str(ids)), \
                 patch.object(semantic, 'META_PATH', str(meta)), patch.object(semantic, '_STATE', state):
                semantic._ensure_loaded()
                np.save(emb, np.ones((3, 384), dtype='float32'))
                meta.write_text(json.dumps({'count': 3, 'generation': 'incomplete'}), encoding='utf-8')
                self.assertTrue(semantic._ensure_loaded())
                self.assertEqual([1, 2], state['ids'].tolist())


if __name__ == '__main__':
    unittest.main()
