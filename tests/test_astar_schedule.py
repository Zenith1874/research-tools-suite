"""Elapsed work and off-peak waits must not drift the next metadata slot."""

import unittest
from datetime import datetime
from services.astar_schedule import advance_slot, initial_delay


class ScheduleTests(unittest.TestCase):
    def test_absolute_due_time_ignores_service_startup_duration(self):
        now = datetime(2026, 10, 7, 8, 0, 15)
        due = datetime(2026, 10, 8, 4, 1, 15)
        self.assertEqual((due - now).total_seconds(), initial_delay(due.isoformat(), now, 600))

    def test_legacy_delay_is_preserved_without_absolute_target(self):
        self.assertEqual(321, initial_delay(None, datetime.now(), 321))
    def test_two_hour_job_preserves_the_next_daily_slot(self):
        self.assertEqual((86400, 79200), advance_slot(0, 7200, 86400))

    def test_multiple_missed_slots_roll_forward_without_a_burst(self):
        self.assertEqual((259200, 3600), advance_slot(0, 255600, 86400))

    def test_finished_exactly_at_a_slot_skips_that_missed_slot(self):
        self.assertEqual((172800, 86400), advance_slot(0, 86400, 86400))

    def test_invalid_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            advance_slot(0, 0, 0)
