"""A watchdog restart must retain the reviewed embedding hold and daily slot."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from services.astar_schedule import apply_runtime_controls


class RuntimeControlsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profile = Path(self.directory.name) / 'controls.json'
        self.now = datetime(2026, 10, 8, 1, 47)

    def write_profile(self, **changes):
        value = {'schema_version': 1, 'embedding_auto': '0',
                 'daily_anchor_local': '2026-10-08T04:01:15.430245',
                 'reason': 'Private full-corpus generation is unfinished'}
        value.update(changes)
        self.profile.write_text(json.dumps(value), encoding='utf-8')

    def test_absent_profile_preserves_existing_environment(self):
        environment = {'UNCHANGED': 'value'}
        self.assertEqual({}, apply_runtime_controls(self.profile, environment, self.now))
        self.assertEqual({'UNCHANGED': 'value'}, environment)

    def test_restart_keeps_embedding_hold_and_absolute_due_time(self):
        self.write_profile()
        environment = {}
        result = apply_runtime_controls(self.profile, environment, self.now)
        self.assertEqual('0', environment['EMB_AUTO'])
        self.assertEqual('2026-10-08T04:01:15.430245', environment['ASTAR_NEXT_DUE_LOCAL'])
        self.assertEqual(environment, result['applied'])

    def test_explicit_process_settings_take_precedence(self):
        self.write_profile()
        environment = {'EMB_AUTO': '1', 'ASTAR_NEXT_DUE_LOCAL': '2026-10-09T08:00:00'}
        expected = dict(environment)
        result = apply_runtime_controls(self.profile, environment, self.now)
        self.assertEqual(expected, environment)
        self.assertEqual({}, result['applied'])

    def test_past_anchor_keeps_daily_clock_instead_of_startup_delay(self):
        self.write_profile(daily_anchor_local='2026-10-06T04:01:15.430245')
        environment = {}
        apply_runtime_controls(self.profile, environment, datetime(2026, 10, 8, 7, 2))
        self.assertEqual('2026-10-09T04:01:15.430245', environment['ASTAR_NEXT_DUE_LOCAL'])

    def test_unknown_fields_cannot_set_unrelated_environment(self):
        self.write_profile(unrelated_setting='value')
        environment = {'UNCHANGED': 'value'}
        with self.assertRaises(ValueError):
            apply_runtime_controls(self.profile, environment, self.now)
        self.assertEqual({'UNCHANGED': 'value'}, environment)

    def test_invalid_profile_is_rejected_before_partial_application(self):
        for changes in ({'embedding_auto': 0}, {'schema_version': True},
                        {'daily_anchor_local': '2026-10-08T04:01:15+00:00'}):
            with self.subTest(changes=changes):
                self.write_profile(**changes)
                environment = {'UNCHANGED': 'value'}
                with self.assertRaises(ValueError):
                    apply_runtime_controls(self.profile, environment, self.now)
                self.assertEqual({'UNCHANGED': 'value'}, environment)


if __name__ == '__main__':
    unittest.main()
