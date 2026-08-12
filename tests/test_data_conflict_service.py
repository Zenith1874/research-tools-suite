# -*- coding: utf-8 -*-
"""跨来源分歧的落库与消解。"""
import sqlite3
import unittest

from services.data_conflict_service import (
    ensure_conflict_table, record_conflict, clear_conflict, list_conflicts,
)

BASE = {
    'domain': 'city_economy', 'region_code': '440300', 'region_name': '深圳',
    'government_scope': 'city_total', 'indicator_code': 'general_budget_expenditure',
    'period': '2016', 'candidate_source_name': '国家统计局“主要城市年度数据”',
}


def _conflict(**over):
    return {**BASE, 'kept_value': 4178.04, 'kept_data_status': 'official',
            'kept_source_name': '深圳市统计局', 'candidate_value': 4211.04,
            'candidate_data_status': 'official_revised',
            'candidate_source_url': 'https://data.stats.gov.cn/x',
            'relative_diff': 0.0079, 'resolution': 'kept_published',
            'note': 'fixture', **over}


class ConflictPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        ensure_conflict_table(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_conflict_survives_the_call_that_found_it(self):
        record_conflict(self.conn, _conflict())
        rows = list_conflicts(self.conn, domain='city_economy')
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['region_name'], '深圳')
        self.assertEqual(row['kept_value'], 4178.04)
        self.assertEqual(row['candidate_value'], 4211.04)
        self.assertEqual(row['resolution'], 'kept_published')
        self.assertIn('data.stats.gov.cn', row['candidate_source_url'])

    def test_re_recording_updates_values_but_keeps_first_seen(self):
        record_conflict(self.conn, _conflict())
        first_seen = list_conflicts(self.conn)[0]['first_seen_at']
        record_conflict(self.conn, _conflict(candidate_value=4300.0, relative_diff=0.0292))
        rows = list_conflicts(self.conn)
        self.assertEqual(len(rows), 1)                      # 不产生重复行
        self.assertEqual(rows[0]['candidate_value'], 4300.0)
        self.assertEqual(rows[0]['first_seen_at'], first_seen)

    def test_clear_removes_a_resolved_conflict(self):
        record_conflict(self.conn, _conflict())
        clear_conflict(self.conn, BASE)
        self.assertEqual(list_conflicts(self.conn), [])

    def test_clear_is_safe_when_nothing_recorded(self):
        clear_conflict(self.conn, BASE)
        self.assertEqual(list_conflicts(self.conn), [])

    def test_different_indicator_is_a_separate_conflict(self):
        record_conflict(self.conn, _conflict())
        record_conflict(self.conn, _conflict(indicator_code='nominal_gdp'))
        self.assertEqual(len(list_conflicts(self.conn)), 2)

    def test_listing_is_ordered_by_absolute_difference(self):
        record_conflict(self.conn, _conflict(relative_diff=0.006))
        record_conflict(self.conn, _conflict(indicator_code='nominal_gdp',
                                             relative_diff=-0.031))
        self.assertEqual([r['indicator_code'] for r in list_conflicts(self.conn)],
                         ['nominal_gdp', 'general_budget_expenditure'])

    def test_domain_filter(self):
        record_conflict(self.conn, _conflict())
        record_conflict(self.conn, _conflict(domain='other'))
        self.assertEqual(len(list_conflicts(self.conn, domain='city_economy')), 1)
        self.assertEqual(len(list_conflicts(self.conn)), 2)


if __name__ == '__main__':
    unittest.main()
