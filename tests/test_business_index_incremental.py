"""Entity input cache updates preserve source data, identities and author state."""

from contextlib import closing
import ast
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from services import business_research_service as business
from services.business_index_incremental import NeedsReview, update_index


class IncrementalEntityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.db'
        self.state = self.root / 'state.db'
        self.catalog = {
            'theories': [{'id': 'signaling-theory', 'name': 'Signaling Theory', 'tags': ['signaling']}],
            'methods': [],
            'constructs': [{'id': 'autonomy', 'name': 'Autonomy', 'keywords': ['autonomy']}],
        }
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript('''
                CREATE TABLE astar_articles (id INTEGER PRIMARY KEY,title TEXT,abstract TEXT,
                    is_duplicate INTEGER,updated_at TEXT,created_at TEXT);
                CREATE TABLE astar_article_classifications (article_id INTEGER PRIMARY KEY,
                    theory_tags_json TEXT,method_tags_json TEXT,classification_method TEXT,
                    classified_at TEXT,semantic_relevance REAL);
                INSERT INTO astar_articles VALUES
                    (1,'Signaling at work','Employee autonomy',0,'2026-10-11T01:00:00','2026-10-11T01:00:00'),
                    (2,'Unrelated paper',NULL,0,'2026-10-11T01:00:00','2026-10-11T01:00:00'),
                    (3,'Signaling in firms','Organization',0,'2026-10-11T01:00:00','2026-10-11T01:00:00');
                INSERT INTO astar_article_classifications VALUES
                    (1,'["signaling"]','[]','rules','2026-10-11T01:00:00',37.5),
                    (2,'[]','[]','rules','2026-10-11T01:00:00',NULL),
                    (3,'["signaling"]','[]','rules','2026-10-11T01:00:00',82.0);
            ''')
        business.rebuild_link_index(self.source, self.state, self.catalog, force=True)
        with closing(business._state_connect(self.state)) as connection, connection:
            connection.execute("INSERT INTO research_library_state VALUES (1,'reading',1,NULL,'human-time')")
            connection.execute("INSERT INTO research_notes(paper_id,note_text,tags_json,created_at,updated_at) "
                               "VALUES (1,'Preserve this note','[]','human-time','human-time')")

    def tearDown(self):
        self.temporary.cleanup()

    def update(self, apply=True, **kwargs):
        return update_index(business, self.source, self.state, catalog=self.catalog, apply=apply, **kwargs)

    def modify_source(self, statement, values=()):
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.execute(statement, values)

    def state_snapshot(self):
        with closing(sqlite3.connect(self.state)) as connection:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                      if row[0] != 'sqlite_sequence']
            return {table: connection.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall() for table in tables}

    def source_snapshot(self):
        with closing(sqlite3.connect(self.source)) as connection:
            return {table: connection.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                    for table in ('astar_articles', 'astar_article_classifications')}

    def logical_projection(self, path):
        with closing(sqlite3.connect(path)) as connection:
            connection.row_factory = sqlite3.Row
            links = {tuple(row) for row in connection.execute('SELECT * FROM research_paper_links')}
            assertions = {json.dumps({name: row[name] for name in row.keys()
                                     if name not in ('id', 'created_at', 'updated_at')}, sort_keys=True)
                          for row in connection.execute('SELECT * FROM research_entity_assertions')}
            return links, assertions

    def assert_matches_full_reference(self):
        path = self.root / 'reference.db'
        business.rebuild_link_index(self.source, path, self.catalog, force=True)
        self.assertEqual(self.logical_projection(self.state), self.logical_projection(path))

    def test_readonly_cache_plan_creates_no_files_or_state_changes(self):
        before = self.state_snapshot()
        result = self.update(apply=False)
        self.assertEqual(result['mode'], 'initialize_input_cache')
        self.assertFalse(result['database_written'])
        self.assertEqual(before, self.state_snapshot())
        self.assertFalse((self.root / 'business_research_incremental.lock').exists())
        self.assertFalse((self.root / 'business_research_index_updates').exists())

    def test_bootstrap_preserves_entities_sources_human_state_and_old_generation(self):
        before = self.state_snapshot()
        source = self.source_snapshot()
        result = self.update()
        after = self.state_snapshot()
        self.assertEqual(result['mode'], 'initialize_input_cache')
        self.assertEqual(result['affected_papers'], 0)
        self.assertEqual(result['source_records_written'], 0)
        for table in ('research_paper_links', 'research_entity_assertions', 'research_notes', 'research_library_state'):
            self.assertEqual(before[table], after[table])
        self.assertEqual(source, self.source_snapshot())
        self.assertTrue((Path(result['run_dir']) / 'state_before.sqlite3').exists())
        self.assertEqual(len(after['research_index_inputs']), 3)
        self.assertTrue(dict(before['research_index_meta']).items() <= dict(after['research_index_meta']).items())

    def test_changed_tags_and_new_record_match_complete_reference(self):
        self.update()
        self.modify_source("UPDATE astar_article_classifications SET theory_tags_json='[]', "
                           "classified_at='2026-10-12T02:00:00' WHERE article_id=1")
        self.modify_source("UPDATE astar_articles SET abstract='No construct',updated_at='2026-10-12T02:00:00' WHERE id=1")
        self.modify_source("INSERT INTO astar_articles VALUES (4,'Autonomy study','Employee autonomy',0,'2026-10-12','2026-10-12')")
        source_before = self.source_snapshot()
        untouched = self.state_snapshot()['research_entity_assertions'][-1]
        result = self.update()
        self.assertEqual(result['affected_papers'], 2)
        self.assertEqual(source_before, self.source_snapshot())
        self.assertIn(untouched, self.state_snapshot()['research_entity_assertions'])
        self.assert_matches_full_reference()

    def test_duplicate_without_timestamp_change_is_detected(self):
        self.update()
        self.modify_source('UPDATE astar_articles SET is_duplicate=1 WHERE id=1')
        result = self.update()
        self.assertEqual(result['affected_papers'], 1)
        self.assertGreater(result['deleted_assertions'], 0)
        self.assert_matches_full_reference()

    def test_backdated_title_edit_is_detected(self):
        self.update()
        self.modify_source("UPDATE astar_articles SET title='Signals',abstract='No construct' WHERE id=1")
        result = self.update()
        self.assertEqual(result['affected_papers'], 1)
        self.assert_matches_full_reference()

    def test_timestamp_only_update_preserves_every_assertion_field(self):
        self.update()
        before = self.state_snapshot()
        self.modify_source("UPDATE astar_article_classifications SET classified_at='2026-10-12T02:00:00'")
        result = self.update()
        self.assertEqual(result['affected_papers'], 0)
        for table in ('research_paper_links', 'research_entity_assertions', 'research_notes', 'research_library_state'):
            self.assertEqual(before[table], self.state_snapshot()[table])

    def test_reviewed_affected_assertion_blocks_without_changing_state(self):
        self.update()
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("UPDATE research_entity_assertions SET verification_status='VERIFIED',reviewed_at='human' WHERE paper_id=1")
        self.modify_source("UPDATE astar_articles SET abstract='New evidence text' WHERE id=1")
        before = self.state_snapshot()
        with self.assertRaisesRegex(NeedsReview, 'reviewed'):
            self.update()
        self.assertEqual(before, self.state_snapshot())

    def test_reviewed_unaffected_assertion_and_human_notes_are_preserved(self):
        self.update()
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("UPDATE research_entity_assertions SET verification_status='VERIFIED',reviewed_at='human' WHERE paper_id=3")
        before = self.state_snapshot()
        self.modify_source("UPDATE astar_articles SET abstract='No construct' WHERE id=1")
        self.update()
        for table in ('research_notes', 'research_library_state'):
            self.assertEqual(before[table], self.state_snapshot()[table])
        reviewed = [row for row in before['research_entity_assertions'] if row[1] == 3]
        self.assertTrue(all(row in self.state_snapshot()['research_entity_assertions'] for row in reviewed))

    def test_modified_accepted_fingerprint_is_held(self):
        self.update()
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute('UPDATE research_index_inputs SET input_hash=? WHERE paper_id=1', (b'x' * 32,))
        before = self.state_snapshot()
        with self.assertRaisesRegex(NeedsReview, 'cache was modified'):
            self.update()
        self.assertEqual(before, self.state_snapshot())

    def test_source_commit_during_staging_preserves_live_generation(self):
        self.update()
        self.modify_source("UPDATE astar_articles SET abstract='New autonomy' WHERE id=1")
        before = self.state_snapshot()
        original = business._assertions_for_row
        committed = False
        def concurrent(row, *args):
            nonlocal committed
            if not committed:
                self.modify_source("UPDATE astar_articles SET title='Concurrent change' WHERE id=2")
                committed = True
            return original(row, *args)
        with patch.object(business, '_assertions_for_row', side_effect=concurrent):
            with self.assertRaisesRegex(NeedsReview, 'Source changed'):
                self.update()
        self.assertEqual(before, self.state_snapshot())

    def test_mid_transaction_failure_rolls_back_cache_and_entity_rows(self):
        self.update()
        self.modify_source("UPDATE astar_articles SET abstract='Remove construct' WHERE id=1")
        before = self.state_snapshot()
        with patch.object(business, '_set_index_meta', side_effect=RuntimeError('injected metadata failure')):
            with self.assertRaisesRegex(RuntimeError, 'injected metadata'):
                self.update()
        self.assertEqual(before, self.state_snapshot())

    def test_missing_source_row_removes_only_its_unreviewed_projection(self):
        self.update()
        self.modify_source('DELETE FROM astar_articles WHERE id=1')
        result = self.update()
        self.assertEqual(result['affected_papers'], 1)
        self.assert_matches_full_reference()

    def test_delta_cap_refuses_an_expanded_write_scope(self):
        self.update()
        self.modify_source("UPDATE astar_articles SET abstract='New abstract'")
        before = self.state_snapshot()
        with self.assertRaisesRegex(NeedsReview, 'limit'):
            self.update(max_changed=2)
        self.assertEqual(before, self.state_snapshot())

    def test_noop_retains_all_existing_state(self):
        self.update()
        before = self.state_snapshot()
        result = self.update()
        self.assertFalse(result['applied'])
        self.assertEqual(before, self.state_snapshot())

    def test_staged_candidate_tampering_is_refused_before_any_live_write(self):
        from services import business_index_incremental
        self.update()
        self.modify_source("UPDATE astar_articles SET abstract='New autonomy' WHERE id=1")
        before = self.state_snapshot()
        original = business_index_incremental._apply
        def altered(*args):
            candidate = args[-2]
            with closing(sqlite3.connect(candidate)) as connection, connection:
                row = connection.execute('SELECT rowid,payload FROM assertions LIMIT 1').fetchone()
                changed = json.loads(row[1])
                changed['verification_status'] = 'VERIFIED'
                connection.execute('UPDATE assertions SET payload=? WHERE rowid=?', (json.dumps(changed), row[0]))
            return original(*args)
        with patch.object(business_index_incremental, '_apply', side_effect=altered):
            with self.assertRaisesRegex(NeedsReview, 'candidate changed'):
                self.update()
        self.assertEqual(before, self.state_snapshot())

    def test_changed_projection_binding_refuses_cached_inference(self):
        self.update()
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("UPDATE research_index_meta SET value='different-code' WHERE key='input_projection_sha256'")
        before = self.state_snapshot()
        with self.assertRaisesRegex(NeedsReview, 'projection code changed'):
            self.update()
        self.assertEqual(before, self.state_snapshot())

    def test_full_activation_cannot_replace_a_reviewed_assertion(self):
        from services import business_index_refresh
        staged = self.root / 'full_candidate.db'
        business.rebuild_link_index(self.source, staged, self.catalog, force=True)
        with closing(sqlite3.connect(self.state)) as connection, connection:
            connection.execute("UPDATE research_entity_assertions SET verification_status='VERIFIED',reviewed_at='human' WHERE paper_id=1")
        before = self.state_snapshot()
        with self.assertRaisesRegex(RuntimeError, 'reviewed'):
            business_index_refresh.activate(business, self.state, staged)
        self.assertEqual(before, self.state_snapshot())

    def test_scheduler_serializes_entity_updates_even_when_embeddings_are_paused(self):
        from services import business_index_incremental, astar_semantic_service
        class EndCycle(Exception):
            pass
        class Clock:
            def __init__(self): self.sleeps = 0
            def monotonic(self): return 0.0
            def sleep(self, delay):
                self.sleeps += 1
                if self.sleeps > 1: raise EndCycle()
        server = Path(__file__).resolve().parents[1] / 'server.py'
        functions = [node for node in ast.parse(server.read_text(encoding='utf-8')).body
                     if isinstance(node, ast.FunctionDef) and node.name in ('_run_update_job', 'astar_scheduler_thread')]
        for automatic in ('0', '1'):
            with self.subTest(embedding_auto=automatic):
                namespace = {'threading': threading, 'datetime': datetime, 'time': Clock(),
                    'os': SimpleNamespace(environ={'ASTAR_INITIAL_DELAY_SECONDS': '0', 'LLM_AUTO': '0',
                                                  'AFFIL_AUTO': '0', 'EMB_AUTO': automatic},
                                          path=SimpleNamespace(exists=lambda path: True)),
                    'log': Mock(), '_UPDATE_LOCK': threading.Lock(), '_JOBS_LOCK': threading.Lock(), '_JOBS': {},
                    '_data_cache_clear': Mock(), 'check_and_record_new_periods': Mock(), 'DB_PATH': 'never-opened',
                    'update_astar_recent_articles': Mock(return_value={'success': True}),
                    'deduplicate_articles': Mock(), 'llm_classify_articles': Mock()}
                exec(compile(ast.Module(body=functions, type_ignores=[]), str(server), 'exec'), namespace)
                def entity_job(*args, **kwargs):
                    self.assertTrue(namespace['_UPDATE_LOCK'].locked())
                    self.assertEqual(namespace['_JOBS']['astar_metadata']['status'], 'done')
                    self.assertEqual(namespace['_JOBS']['astar_entity_index']['status'], 'running')
                    if automatic == '1':
                        self.assertEqual(namespace['_JOBS']['astar_semantic']['status'], 'done')
                    self.assertTrue(kwargs['apply'])
                    return {'success': True, 'mode': 'delta', 'affected_papers': 0}
                with patch.object(business_index_incremental, 'update_index', side_effect=entity_job) as update, \
                        patch.object(astar_semantic_service, 'build_embeddings', return_value={'success': True}):
                    with self.assertRaises(EndCycle):
                        namespace['astar_scheduler_thread']()
                update.assert_called_once()
                self.assertEqual(namespace['_JOBS']['astar_entity_index']['status'], 'done')
                self.assertFalse(namespace['_UPDATE_LOCK'].locked())


if __name__ == '__main__':
    unittest.main()
