"""Reviewed restoration preserves enrichments and rejects stale plans atomically."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.reconcile_astar_baseline import apply_plan, prepare


class BaselineRestorationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db_path = self.root / 'live.db'
        self.snapshot = self.root / 'baseline.db'
        self.run = self.root / 'run'
        self.run.mkdir()
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript('''
                CREATE TABLE astar_articles(id INTEGER PRIMARY KEY,title TEXT,abstract TEXT,
                    abstract_status TEXT,cited_by_count INTEGER,updated_at TEXT);
                CREATE TABLE astar_article_classifications(id INTEGER PRIMARY KEY,article_id INTEGER,
                    classification_method TEXT,relevance_score REAL,classified_at TEXT);
                CREATE TABLE astar_article_sources(id INTEGER PRIMARY KEY,article_id INTEGER,raw_json TEXT);
                INSERT INTO astar_articles VALUES(1,'Original title','Original abstract','present',3,'old'),
                    (2,'Original title two',NULL,'missing',0,'old');
                INSERT INTO astar_article_classifications VALUES(11,1,'llm',90,'old'),(12,2,'rules',40,'old');
                INSERT INTO astar_article_sources VALUES(1,1,'preserved original payload');
            ''')
        shutil.copyfile(self.db_path, self.snapshot)
        (self.run / 'manifest.json').write_text(json.dumps({
            'db_path': str(self.db_path), 'snapshot_path': str(self.snapshot),
            'snapshot_sha256': hashlib.sha256(self.snapshot.read_bytes()).hexdigest()}), encoding='utf-8')
        with closing(sqlite3.connect(self.db_path)) as db:
            db.executescript('''
                UPDATE astar_articles SET title='Provider title',abstract='Provider abstract',
                    abstract_status='provider present',updated_at='new' WHERE id=1;
                UPDATE astar_articles SET abstract='New blank-field enrichment',abstract_status='present',
                    cited_by_count=4,updated_at='new' WHERE id=2;
                UPDATE astar_article_classifications SET relevance_score=82,classified_at='new' WHERE id=12;
                INSERT INTO astar_articles VALUES(3,'New article','New abstract','present',1,'new');
                INSERT INTO astar_article_classifications VALUES(13,3,'rules',70,'new');
            ''')

    def rows(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return {table: db.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                    for table in ('astar_articles', 'astar_article_classifications', 'astar_article_sources')}

    def make_plan(self):
        output = self.root / 'prepared'
        report = prepare(self.run, output)
        return output, report

    def test_preparation_is_read_only_and_retains_observed_full_rows(self):
        before = self.rows()
        output, report = self.make_plan()
        self.assertEqual(before, self.rows())
        self.assertEqual({'astar_articles': 2, 'astar_article_classifications': 1}, report['rows_by_table'])
        saved = json.loads((output / 'observed_rows_preserved.json').read_text(encoding='utf-8'))
        self.assertEqual('Provider abstract', saved['astar_articles'][0]['abstract'])
        self.assertEqual(82, saved['astar_article_classifications'][0]['relevance_score'])
        plan = json.loads((output / 'repair_plan.json').read_text(encoding='utf-8'))
        second = next(action for action in plan['actions'] if action['table'] == 'astar_articles' and action['row_id'] == 2)
        self.assertNotIn('abstract', second['changes'])
        self.assertNotIn('abstract_status', second['changes'])

    def test_approved_restore_keeps_blank_enrichment_paid_decision_sources_and_new_rows(self):
        before = self.rows()
        output, report = self.make_plan()
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute("UPDATE astar_articles SET abstract='Later blank-field enrichment' WHERE id=2")
            db.commit()
        applied = apply_plan(output / 'repair_plan.json', report['plan_sha256'])
        after = self.rows()
        self.assertEqual(('Original title', 'Original abstract', 'present'), after['astar_articles'][0][1:4])
        self.assertEqual('Later blank-field enrichment', after['astar_articles'][1][2])
        self.assertEqual(0, after['astar_articles'][1][4])
        self.assertEqual((12, 2, 'rules', 40, 'old'), after['astar_article_classifications'][1])
        self.assertEqual(before['astar_article_classifications'][0], after['astar_article_classifications'][0])
        self.assertEqual(before['astar_articles'][2], after['astar_articles'][2])
        self.assertEqual(before['astar_article_classifications'][2], after['astar_article_classifications'][2])
        self.assertEqual(before['astar_article_sources'], after['astar_article_sources'])
        self.assertFalse(applied['new_articles_updated'])
        snapshot = json.loads(Path(applied['immediate_input_snapshot']).read_text(encoding='utf-8'))
        second = next(row for row in snapshot['rows']['astar_articles'] if row['id'] == 2)
        self.assertEqual('Later blank-field enrichment', second['abstract'])

    def test_unapproved_or_stale_plan_restores_nothing(self):
        output, report = self.make_plan()
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'explicitly approved'):
            apply_plan(output / 'repair_plan.json', '0' * 64)
        self.assertEqual(before, self.rows())
        with closing(sqlite3.connect(self.db_path)) as db:
            db.execute('UPDATE astar_article_classifications SET relevance_score=65 WHERE id=12')
            db.commit()
        changed = self.rows()
        with self.assertRaisesRegex(ValueError, 'changed since review'):
            apply_plan(output / 'repair_plan.json', report['plan_sha256'])
        self.assertEqual(changed, self.rows())


if __name__ == '__main__':
    unittest.main()
