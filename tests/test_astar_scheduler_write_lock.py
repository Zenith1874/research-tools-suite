"""Exercise the real scheduler and shared job lock without starting the server."""

import ast
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class EndIteration(Exception):
    pass


class OneIterationClock:
    def __init__(self):
        self.sleeps = 0

    def monotonic(self):
        return 0

    def sleep(self, seconds):
        self.sleeps += 1
        if self.sleeps > 1:
            raise EndIteration()


class SchedulerWriteLockTests(unittest.TestCase):
    def make_namespace(self, failure=False):
        server = Path(__file__).resolve().parents[1] / 'server.py'
        tree = ast.parse(server.read_text(encoding='utf-8'))
        # Run the actual function bodies with isolated provider/cache stubs;
        # imports and __main__ side effects from the rest of server.py are excluded.
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('_run_update_job', 'astar_scheduler_thread')]
        trace = []

        def update(days):
            trace.append(('metadata', days))
            if failure:
                raise RuntimeError('fixture metadata provider failed')
            return {'articles_inserted': 2, 'articles_updated': 3}

        namespace = {'threading': threading, 'datetime': datetime, 'time': OneIterationClock(),
                     'os': SimpleNamespace(environ={'ASTAR_INITIAL_DELAY_SECONDS': '0',
                                                   'LLM_AUTO': '0', 'AFFIL_AUTO': '0', 'EMB_AUTO': '0'}),
                     'log': Mock(), '_UPDATE_LOCK': threading.Lock(), '_JOBS_LOCK': threading.Lock(),
                     '_JOBS': {}, '_data_cache_clear': Mock(), 'check_and_record_new_periods': Mock(),
                     'DB_PATH': 'not-opened', 'update_astar_recent_articles': update,
                     'deduplicate_articles': lambda: trace.append(('deduplicate', None)),
                     'llm_classify_articles': Mock(), 'trace': trace}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(server), 'exec'), namespace)
        return namespace

    def test_metadata_and_deduplication_are_one_visible_serial_job(self):
        namespace = self.make_namespace()
        with self.assertRaises(EndIteration):
            namespace['astar_scheduler_thread']()
        self.assertEqual([('metadata', 14), ('deduplicate', None)], namespace['trace'])
        self.assertEqual('done', namespace['_JOBS']['astar_metadata']['status'])
        self.assertEqual(2, namespace['_JOBS']['astar_metadata']['result']['articles_inserted'])
        self.assertFalse(namespace['_UPDATE_LOCK'].locked())

    def test_scheduler_waits_for_an_existing_writer(self):
        namespace = self.make_namespace()
        finished = threading.Event()
        failures = []
        namespace['_UPDATE_LOCK'].acquire()

        def run():
            try:
                namespace['astar_scheduler_thread']()
            except EndIteration:
                pass
            except Exception as error:
                failures.append(error)
            finally:
                finished.set()

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            self.assertFalse(finished.wait(0.1))
            self.assertEqual([], namespace['trace'])
        finally:
            namespace['_UPDATE_LOCK'].release()
        self.assertTrue(finished.wait(2))
        worker.join(2)
        self.assertEqual([], failures)
        self.assertEqual([('metadata', 14), ('deduplicate', None)], namespace['trace'])

    def test_failed_metadata_is_visible_and_skips_downstream_jobs(self):
        namespace = self.make_namespace(failure=True)
        namespace['os'].environ['LLM_AUTO'] = '1'
        namespace['os'].environ['AFFIL_AUTO'] = '1'
        namespace['os'].environ['EMB_AUTO'] = '1'
        with self.assertRaises(EndIteration):
            namespace['astar_scheduler_thread']()
        self.assertEqual([('metadata', 14)], namespace['trace'])
        self.assertEqual('error', namespace['_JOBS']['astar_metadata']['status'])
        self.assertEqual('fixture metadata provider failed', namespace['_JOBS']['astar_metadata']['error'])
        namespace['llm_classify_articles'].assert_not_called()
        self.assertFalse(namespace['_UPDATE_LOCK'].locked())


if __name__ == '__main__':
    unittest.main()
