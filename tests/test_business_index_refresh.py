"""Concurrent requests cannot clear or duplicate a served research index."""

import sqlite3
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from services import business_index_refresh as refresh
from services import business_research_service as business


class IndexRefreshTests(unittest.TestCase):
    def test_completed_generation_preserves_user_notes_and_reading_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'live.db'
            staged = Path(temporary) / 'stage.db'
            for path in (target, staged):
                connection = business._state_connect(path)
                connection.close()
            live = business._state_connect(target)
            live.execute("INSERT INTO research_library_state(paper_id,reading_status,favorite,updated_at) VALUES (1,'reading',1,'before')")
            live.execute("INSERT INTO research_paper_links VALUES (1,'theory','old','old')")
            live.commit()
            live.close()
            stage = business._state_connect(staged)
            stage.execute("INSERT INTO research_paper_links VALUES (2,'theory','new','new')")
            business._set_index_meta(stage, 'max_article_id', '2')
            stage.commit()
            stage.close()
            refresh.activate(business, target, staged)
            live = business._state_connect(target)
            self.assertEqual(('reading', 1), tuple(live.execute("SELECT reading_status,favorite FROM research_library_state WHERE paper_id=1").fetchone()))
            self.assertEqual([(2, 'theory', 'new', 'new')], [tuple(row) for row in live.execute('SELECT * FROM research_paper_links')])
            live.close()

    def test_failed_build_does_not_activate_or_clear_served_tables(self):
        module = types.SimpleNamespace(rebuild_link_index=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('build failed')))
        with tempfile.TemporaryDirectory() as temporary, patch.object(refresh, 'activate') as activate:
            key = ('unused', str(Path(temporary) / 'live.db'))
            refresh.refresh(module, key, {})
            activate.assert_not_called()
            self.assertEqual('error', refresh._STATES[key])

    def test_two_large_requests_launch_only_one_background_build(self):
        started, finish = threading.Event(), threading.Event()
        calls = []
        def rebuild(*args, **kwargs):
            calls.append(args)
            started.set()
            finish.wait(5)
        with tempfile.TemporaryDirectory() as temporary:
            module = types.SimpleNamespace(DEFAULT_ARTICLE_DB_PATH=Path(temporary) / 'articles.db',
                                           DEFAULT_STATE_DB_PATH=Path(temporary) / 'state.db',
                                           rebuild_link_index=rebuild)
            expected = {'max_article_id': '10001'}
            with patch.object(refresh, 'signature', return_value=expected), \
                 patch.object(refresh, 'is_current', return_value=False), \
                 patch.object(refresh, 'activate'):
                self.assertFalse(refresh.ensure(module, catalog={'test': True}))
                self.assertTrue(started.wait(2))
                self.assertFalse(refresh.ensure(module, catalog={'test': True}))
                self.assertEqual(1, len(calls))
                finish.set()
                refresh._JOBS[refresh.key_for(module, None, None)].join(2)


if __name__ == '__main__':
    unittest.main()
