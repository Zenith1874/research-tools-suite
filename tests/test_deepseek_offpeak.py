# -*- coding: utf-8 -*-
"""DeepSeek 优惠时段 gating.

The windows are defined in Beijing time but only ever evaluated in UTC, and a
half-price window read in the wrong timezone costs real money silently -- there
is no error, just a doubled bill. So the boundaries are pinned here explicitly,
including the weekend, which is off-peak even during hours that would be
standard on a weekday.
"""

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services import abdc_astar_research_service as radar
from services.deepseek_offpeak import (
    SAFETY_MARGIN,
    describe,
    is_offpeak,
    next_standard_start,
    normalize_mode,
    offpeak_seconds_left,
    seconds_until_offpeak,
    wait_for_offpeak,
)


def utc(text):
    return datetime.strptime(text, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)


# 2026-09-07 is a Monday, so this week runs Mon 09-07 through Sun 09-13.
MON, FRI, SAT, SUN = '2026-09-07', '2026-09-11', '2026-09-12', '2026-09-13'


class WindowTests(unittest.TestCase):
    def test_weekday_standard_windows_are_the_two_beijing_blocks(self):
        # 北京 09:00-12:00 与 14:00-18:00 == UTC 01:00-04:00 与 06:00-10:00
        for hhmm in ('01:00', '02:30', '03:59', '06:00', '08:54', '09:59'):
            self.assertFalse(is_offpeak(utc(MON + ' ' + hhmm)),
                             hhmm + ' UTC 是标准时段，不该算成优惠')

    def test_weekday_hours_outside_those_blocks_are_offpeak(self):
        for hhmm in ('00:00', '00:59', '04:00', '05:59', '10:00', '18:00', '23:59'):
            self.assertTrue(is_offpeak(utc(MON + ' ' + hhmm)), hhmm + ' UTC 是优惠时段')

    def test_weekend_is_offpeak_even_during_weekday_standard_hours(self):
        for day in (SAT, SUN):
            for hhmm in ('01:00', '02:30', '06:00', '09:59'):
                self.assertTrue(is_offpeak(utc(day + ' ' + hhmm)),
                                day + ' ' + hhmm + ' 是周末，全天优惠')

    def test_naive_datetimes_are_read_as_utc_not_local(self):
        naive = datetime(2026, 9, 7, 2, 30)
        self.assertEqual(is_offpeak(naive), is_offpeak(utc(MON + ' 02:30')))


class RemainingTimeTests(unittest.TestCase):
    def test_seconds_until_offpeak_counts_to_the_end_of_the_current_window(self):
        self.assertAlmostEqual(3600.0, seconds_until_offpeak(utc(MON + ' 03:00')), places=3)
        self.assertAlmostEqual(3600.0, seconds_until_offpeak(utc(MON + ' 09:00')), places=3)

    def test_seconds_until_offpeak_is_zero_when_already_offpeak(self):
        self.assertEqual(0.0, seconds_until_offpeak(utc(MON + ' 12:00')))

    def test_friday_morning_opens_the_63_hour_weekend_block(self):
        # 周五 10:00 UTC 标准时段结束，下一个标准时段是周一 01:00 UTC。
        # 清空积压需要 11.8 小时，必须落在这种不会中途变价的窗口里。
        self.assertAlmostEqual(63.0, offpeak_seconds_left(utc(FRI + ' 10:00')) / 3600.0, places=3)
        self.assertEqual(utc('2026-09-14 01:00'), next_standard_start(utc(FRI + ' 10:00')))

    def test_offpeak_seconds_left_is_zero_during_standard_hours(self):
        self.assertEqual(0.0, offpeak_seconds_left(utc(MON + ' 02:00')))

    def test_next_standard_start_skips_the_weekend(self):
        self.assertEqual(utc('2026-09-14 01:00'), next_standard_start(utc(SAT + ' 12:00')))

    def test_describe_names_the_rate_in_both_windows(self):
        self.assertIn('标准时段', describe(utc(MON + ' 02:00')))
        self.assertIn('优惠时段', describe(utc(MON + ' 12:00')))


class ModeTests(unittest.TestCase):
    def test_absent_mode_means_no_gating(self):
        self.assertEqual('off', normalize_mode(None))
        self.assertEqual('off', normalize_mode(''))

    def test_a_typo_raises_instead_of_silently_paying_double(self):
        with self.assertRaises(ValueError):
            normalize_mode('waits')


class WaitTests(unittest.TestCase):
    def test_offpeak_returns_without_sleeping(self):
        slept = []
        waited = wait_for_offpeak(sleeper=slept.append, clock=lambda: utc(MON + ' 12:00'))
        self.assertEqual(0.0, waited)
        self.assertEqual([], slept)

    def ticking(self, start):
        """返回 (clock, sleeper, slept)：sleeper 推进 clock，模拟真实等待。"""
        clock = [start]
        slept = []

        def sleeper(seconds):
            slept.append(seconds)
            clock[0] += timedelta(seconds=seconds)

        return (lambda: clock[0]), sleeper, slept, clock

    def test_standard_hours_sleep_past_the_window_end(self):
        clock, sleeper, slept, box = self.ticking(utc(MON + ' 09:00'))  # 06:00-10:00 还剩一小时
        waited = wait_for_offpeak(sleeper=sleeper, clock=clock)
        self.assertAlmostEqual(3600.0 + SAFETY_MARGIN, waited, places=3)
        self.assertTrue(is_offpeak(box[0]))
        self.assertTrue(all(s <= 600.0 for s in slept),
                        '要分段睡，否则日志上看不出任务是在等还是卡死了')

    def test_wait_clears_the_boundary_instant(self):
        # 官方没写 9:00-12:00 的右端点算不算高峰。安全边际的意义就是不押这个宝：
        # 醒来的时刻必须明显晚于边界，而不是正好压在上面。
        clock, sleeper, _, box = self.ticking(utc(MON + ' 09:59'))
        wait_for_offpeak(sleeper=sleeper, clock=clock)
        self.assertGreater(box[0], utc(MON + ' 10:00'),
                           '不能停在边界那一秒上')
        self.assertAlmostEqual(SAFETY_MARGIN,
                               (box[0] - utc(MON + ' 10:00')).total_seconds(), places=3)

    def test_margin_is_not_added_when_already_offpeak(self):
        # 已经在优惠时段里就没有边界要跨，不该白等。
        clock, sleeper, slept, _ = self.ticking(utc(MON + ' 12:00'))
        self.assertEqual(0.0, wait_for_offpeak(sleeper=sleeper, clock=clock))
        self.assertEqual([], slept)


class ClassifyGateTests(unittest.TestCase):
    """The gate has to sit in the loop: a long run outlives one rate window."""

    def setUp(self):
        self.calls = []
        rows = [{'id': i, 'title': 'T%d' % i, 'abstract': 'a', 'concepts_json': '[]',
                 'journal_title': 'J', 'relevance_score': 50.0} for i in range(3)]
        self.patchers = [
            patch.object(radar, '_llm_provider', return_value=('deepseek', 'deepseek-v4-flash')),
            patch.object(radar, '_classification_candidates', return_value=rows),
            patch.object(radar, 'get_db', side_effect=self.fake_db),
            patch.object(radar, 'ensure_astar_tables'),
            patch.object(radar, '_llm_classify_one', side_effect=self.record),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def fake_db(self, *a, **k):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE astar_article_classifications (article_id INTEGER PRIMARY KEY,'
                     ' broad_area TEXT, research_topic TEXT, method_tags_json TEXT,'
                     ' data_type_tags_json TEXT, theory_tags_json TEXT, relevance_score REAL,'
                     ' is_related_to_my_research INT, classification_method TEXT,'
                     ' classification_status TEXT, classification_notes TEXT, classified_at TEXT)')
        return conn

    def record(self, *a, **k):
        self.calls.append(a)
        return {'broad_area': 'OB / HR', 'research_topic': [], 'method_tags': [],
                'data_type_tags': [], 'theory_tags': [], 'relevance_score': 70, 'reason': 'r'}

    def test_default_does_not_wait(self):
        with patch.object(radar, 'wait_for_offpeak') as wait:
            result = radar.llm_classify_articles(limit=3)
        wait.assert_not_called()
        self.assertEqual(3, result['classified'])
        self.assertEqual('off', result['offpeak'])

    def test_wait_holds_before_every_article_not_just_the_first(self):
        with patch.object(radar, 'wait_for_offpeak', return_value=60.0) as wait:
            result = radar.llm_classify_articles(limit=3, offpeak='wait')
        self.assertEqual(3, wait.call_count,
                         '一次 11.8 小时的任务会从优惠时段跑进标准时段，必须每篇都查')
        self.assertEqual(180, result['waited_seconds'])
        self.assertEqual(3, len(self.calls))

    def test_stop_spends_nothing_once_the_standard_rate_applies(self):
        with patch.object(radar, 'is_offpeak', return_value=False):
            result = radar.llm_classify_articles(limit=3, offpeak='stop')
        self.assertEqual([], self.calls, '标准时段下一次 API 都不该发')
        self.assertEqual(0, result['classified'])
        self.assertTrue(result['stopped_at_standard_rate'])

    def test_a_bad_mode_fails_before_any_api_call(self):
        with self.assertRaises(ValueError):
            radar.llm_classify_articles(limit=3, offpeak='cheap')
        self.assertEqual([], self.calls)


if __name__ == '__main__':
    unittest.main()
