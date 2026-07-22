# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest

from services.housing_compare_service import build_housing_compare_payload


class HousingCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.official = os.path.join(self.tmp.name, 'official.db')
        self.listing = os.path.join(self.tmp.name, 'listing.db')
        conn = sqlite3.connect(self.official)
        try:
            conn.execute('''CREATE TABLE housing_city_observations (
                city TEXT, period TEXT, indicator_code TEXT, value REAL)''')
            conn.executemany('INSERT INTO housing_city_observations VALUES (?,?,?,?)', [
                ('北京', '2026-05', 'second_home_yoy_idx', 102.0),
                ('北京', '2026-06', 'new_home_yoy_idx', 103.1),
                ('北京', '2026-06', 'second_home_yoy_idx', 101.2),
                ('上海', '2026-06', 'new_home_yoy_idx', 98.5),
                ('上海', '2026-06', 'second_home_yoy_idx', 99.0),
            ])
            conn.commit()
        finally:
            conn.close()
        conn = sqlite3.connect(self.listing)
        try:
            conn.execute('''CREATE TABLE anjuke_city_listings (
                city TEXT, period TEXT, avg_price REAL, mom_pct REAL, yoy_pct REAL,
                data_status TEXT, source_url TEXT, fetched_at TEXT, raw_cached TEXT)''')
            conn.executemany('INSERT INTO anjuke_city_listings VALUES (?,?,?,?,?,?,?,?,?)', [
                ('北京', '2026-05', 39000, 0.5, 3.5, 'listing_reference', 'https://bj', '2026-07-01', 'bj-05.html'),
                ('北京', '2026-06', 40000, 1.0, 4.2, 'listing_reference', 'https://bj', '2026-07-01', 'bj.html'),
                ('上海', '2026-06', 42000, -0.5, -2.0, 'listing_reference', 'https://sh', '2026-07-01', 'sh.html'),
                ('成都', '2026-06', 15000, 0.2, 1.0, 'listing_reference', 'https://cd', '2026-07-01', 'cd.html'),
            ])
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_join_conversion_divergence_and_missing_side(self):
        payload = build_housing_compare_payload(self.official, self.listing, '2026-06')
        rows = {r['city']: r for r in payload['comparison_table']}
        self.assertAlmostEqual(rows['北京']['official_new_yoy_pct'], 3.1)
        self.assertAlmostEqual(rows['北京']['official_second_yoy_pct'], 1.2)
        self.assertAlmostEqual(rows['北京']['divergence'], 3.0)
        self.assertEqual(rows['北京']['data_status'], 'derived')
        missing = {r['city']: r['missing'] for r in payload['not_comparable']}
        self.assertIn('成都', missing)
        self.assertIn('official_second_yoy', missing['成都'])

    def test_no_comparable_cities_for_period(self):
        # 请求一个两侧都无数据的月份 → 优雅返回空,而非崩溃或造数。
        payload = build_housing_compare_payload(self.official, self.listing, '2099-12')
        self.assertEqual(payload['comparison_table'], [])
        self.assertEqual(payload['summary']['comparable_cities'], 0)
        self.assertIsNone(payload['summary']['pearson_correlation'])
        self.assertIsNone(payload['summary']['direction_agreement_pct'])

    def test_summary_and_scatter_contract(self):
        payload = build_housing_compare_payload(self.official, self.listing, '2026-06')
        self.assertEqual(payload['summary']['comparable_cities'], 2)
        self.assertEqual(payload['summary']['direction_agreement_pct'], 100.0)
        self.assertIsNotNone(payload['summary']['pearson_correlation'])
        self.assertEqual({p['city'] for p in payload['scatter_data']}, {'北京', '上海'})

    def test_history_series_uses_all_common_months(self):
        payload = build_housing_compare_payload(self.official, self.listing, '2026-06')
        beijing = payload['history_by_city']['北京']
        self.assertEqual([r['period'] for r in beijing], ['2026-05', '2026-06'])
        self.assertAlmostEqual(beijing[0]['official_second_yoy_pct'], 2.0)
        self.assertAlmostEqual(beijing[0]['divergence'], 1.5)
        self.assertEqual(payload['history_summary']['cities'], 2)
        self.assertEqual(payload['history_summary']['points'], 3)
        self.assertEqual(payload['history_summary']['earliest'], '2026-05')

    def test_official_history_is_available_without_listing_history(self):
        payload = build_housing_compare_payload(self.official, self.listing, '2026-06')
        official = payload['official_history_by_city']
        self.assertEqual([r['period'] for r in official['北京']], ['2026-05', '2026-06'])
        self.assertAlmostEqual(official['上海'][0]['official_second_yoy_pct'], -1.0)
        self.assertEqual(official['上海'][0]['data_status'], 'official')


if __name__ == '__main__':
    unittest.main()
