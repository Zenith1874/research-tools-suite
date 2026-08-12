# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.housing_scenario_service import project
from services.housing_structural_driver_service import (
    build_structural_driver_snapshot,
    build_structural_scenarios,
    driver_contribution,
    load_national_structural_drivers,
)


class HousingStructuralDriverDataTests(unittest.TestCase):
    def test_official_national_snapshot_has_unique_full_history_and_anchors(self):
        grouped = load_national_structural_drivers()
        self.assertEqual(len(grouped['national_population']), 16)
        self.assertEqual(len(grouped['national_disposable_income']), 8)
        self.assertEqual(len(grouped['national_marriages']), 15)
        self.assertEqual(grouped['national_population'][0]['period'], '2010')
        self.assertEqual(grouped['national_population'][-1]['value'], 140489.0)
        self.assertEqual(grouped['national_disposable_income'][-1]['value'], 43377.0)
        self.assertEqual(grouped['national_marriages'][-1]['value'], 610.56)
        keys = [(code, row['period']) for code, rows in grouped.items() for row in rows]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(row['source_url'].startswith('https://www.stats.gov.cn/')
                            for rows in grouped.values() for row in rows))


class HousingStructuralDriverModelTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        handle.close()
        self.path = handle.name
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('''CREATE TABLE city_indicator_observations (
          region_code TEXT,region_name TEXT,indicator_code TEXT,period TEXT,value REAL,
          unit TEXT,data_status TEXT,source_name TEXT,source_url TEXT)''')
        self.conn.execute('''CREATE TABLE china_rates_observations (
          indicator_code TEXT,period TEXT,value REAL,unit TEXT,data_status TEXT,
          source_name TEXT,source_url TEXT)''')
        values = {
            'avg_wage': [100000, 104000, 109000, 113000],
            'resident_population': [530, 532, 531, 529],
            'commercial_housing_sold_area': [1000, 900, 780, 680],
            'housing_completed_area': [700, 800, 850, 920],
            'urban_new_jobs': [20, 19, 18, 17],
            'household_deposits': [6000, 6800, 7600, 8500],
        }
        units = {
            'avg_wage': '元', 'resident_population': '万人',
            'commercial_housing_sold_area': '万平方米',
            'housing_completed_area': '万平方米', 'urban_new_jobs': '万人',
            'household_deposits': '亿元',
        }
        for code, series in values.items():
            for year, value in zip(range(2022, 2026), series):
                self.conn.execute('INSERT INTO city_indicator_observations VALUES (?,?,?,?,?,?,?,?,?)',
                                  ('350200', '厦门', code, str(year), value, units[code],
                                   'official', '测试官方源', f'https://example.test/{code}/{year}'))
        for year, value in zip(range(2013, 2017), (900, 850, 780, 700)):
            self.conn.execute('INSERT INTO city_indicator_observations VALUES (?,?,?,?,?,?,?,?,?)',
                              ('350200', '厦门', 'real_estate_investment', str(year),
                               value, '亿元', 'official', '测试官方源',
                               f'https://example.test/investment/{year}'))
        for period, value in [('2024-01-20', 4.2), ('2025-01-20', 3.8),
                              ('2026-01-20', 3.5), ('2026-07-20', 3.5)]:
            self.conn.execute('INSERT INTO china_rates_observations VALUES (?,?,?,?,?,?,?)',
                              ('LPR_5Y', period, value, '%', 'official',
                               '中国货币网', f'https://example.test/lpr/{period}'))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        Path(self.path).unlink(missing_ok=True)

    def test_snapshot_uses_fresh_city_series_and_keeps_ambiguous_context_out(self):
        snapshot = build_structural_driver_snapshot(self.conn, '厦门', '2026-06')
        by_key = {row['key']: row for row in snapshot['drivers']}
        self.assertEqual(snapshot['status'], 'ok')
        self.assertEqual(by_key['income_growth']['scope'], 'city')
        self.assertEqual(by_key['population_growth']['scope'], 'city')
        self.assertIn('sales_area_growth', by_key)
        self.assertIn('completion_sales_ratio', by_key)
        self.assertIn('lpr_change', by_key)
        self.assertEqual(by_key['marriage_growth']['scope'], 'national_common')
        self.assertEqual(by_key['marriage_growth']['indicator_code'],
                         'national_crude_marriage_rate')
        self.assertEqual(by_key['marriage_growth']['unit'], '‰')
        self.assertAlmostEqual(by_key['marriage_growth']['latest_value'],
                               610.56 / 140828 * 1000, places=4)
        latest_national = next(row for row in snapshot['national_history']
                               if row['period'] == '2024')
        self.assertAlmostEqual(latest_national['national_crude_marriage_rate'],
                               610.56 / 140828 * 1000, places=4)
        context = {row['key']: row for row in snapshot['context_drivers']}
        self.assertEqual(context['urban_new_jobs']['role'], 'context_only')
        self.assertEqual(context['household_deposits']['role'], 'context_only')
        self.assertEqual(context['registered_population']['role'], 'context_only')
        self.assertEqual(context['real_estate_investment']['role'], 'context_only')
        self.assertEqual(context['college_students']['role'], 'context_only')
        self.assertTrue(context['real_estate_investment']['is_stale'])
        self.assertFalse(context['urban_new_jobs']['is_stale'])
        self.assertNotIn('urban_new_jobs', by_key)
        self.assertTrue(all(driver_contribution(row, 'optimistic') is not None
                            for row in snapshot['drivers']))

    def test_small_sample_guardrails_include_demographic_and_income_downside(self):
        snapshot = build_structural_driver_snapshot(self.conn, '厦门', '2026-06')
        by_key = {row['key']: row for row in snapshot['drivers']}
        self.assertLessEqual(by_key['income_growth']['scenario_values']['stress'], 0.0)
        self.assertLess(by_key['population_growth']['scenario_values']['stress'], 0.0)
        self.assertEqual(by_key['marriage_growth']['scenario_values']['optimistic'], 0.0)
        self.assertEqual(by_key['marriage_growth']['scenario_values']['stress'],
                         by_key['marriage_growth']['latest_growth'])
        self.assertGreaterEqual(by_key['lpr_change']['scenario_values']['stress'], 0.0)
        self.assertGreaterEqual(by_key['sales_area_growth']['scenario_values']['optimistic'],
                                0.0)
        self.assertTrue(all(row.get('scenario_guardrail') for row in snapshot['drivers']))
        self.assertIn('15城可比出生与年龄结构序列',
                      snapshot['coverage']['unavailable_comparable_fields'])

    def test_stale_or_short_city_series_falls_back_only_where_allowed(self):
        self.conn.execute("DELETE FROM city_indicator_observations WHERE indicator_code='resident_population'")
        self.conn.execute('''INSERT INTO city_indicator_observations VALUES (?,?,?,?,?,?,?,?,?)''',
                          ('350200', '厦门', 'resident_population', '2024', 531, '万人',
                           'official', '测试官方源', 'https://example.test/pop'))
        self.conn.commit()
        snapshot = build_structural_driver_snapshot(self.conn, '厦门', '2026-06')
        population = next(row for row in snapshot['drivers']
                          if row['key'] == 'population_growth')
        self.assertEqual(population['scope'], 'national_fallback')
        self.assertIn('不足2个近期年点', population['fallback_reason'])

    def test_structural_overlay_widens_tail_and_zero_strength_recovers_momentum(self):
        snapshot = build_structural_driver_snapshot(self.conn, '厦门', '2026-06')
        series = [{'period': f'2025-{month:02d}', 'index': 100 + month}
                  for month in range(1, 13)]
        series.append({'period': '2026-01', 'index': 113.0})
        momentum = []
        for key, annual in [('optimistic', 4.0), ('base', -2.0), ('stress', -8.0)]:
            monthly = ((1 + annual / 100) ** (1 / 12) - 1) * 100
            momentum.append({
                'key': key, 'annualised': annual, 'monthly_rate': monthly,
                'path': project(series, monthly, 24),
            })
        adjusted = build_structural_scenarios(series, momentum, snapshot, 0.40)
        by_key = {row['key']: row for row in adjusted}
        self.assertGreater(by_key['optimistic']['annualised'], 4.0)
        self.assertAlmostEqual(by_key['base']['annualised'], -2.0, places=6)
        self.assertLess(by_key['stress']['annualised'], -8.0)
        self.assertGreaterEqual(by_key['optimistic']['annualised'], by_key['base']['annualised'])
        self.assertGreaterEqual(by_key['base']['annualised'], by_key['stress']['annualised'])
        recovered = build_structural_scenarios(series, momentum, snapshot, 0.0)
        for original, row in zip(momentum, recovered):
            self.assertEqual(row['annualised'], original['annualised'])
            self.assertEqual(row['monthly_rate'], round(original['monthly_rate'], 4))
            self.assertEqual(row['path'], original['path'])

    def test_missing_optional_city_volume_data_does_not_become_zero(self):
        self.conn.execute("DELETE FROM city_indicator_observations WHERE indicator_code IN ('commercial_housing_sold_area','housing_completed_area')")
        self.conn.commit()
        snapshot = build_structural_driver_snapshot(self.conn, '厦门', '2026-06')
        keys = {row['key'] for row in snapshot['drivers']}
        self.assertNotIn('sales_area_growth', keys)
        self.assertNotIn('completion_sales_ratio', keys)
        self.assertIn('商品房销售面积近期连续值', snapshot['coverage']['missing_optional'])
        self.assertGreaterEqual(snapshot['coverage']['model_drivers_used'], 4)


if __name__ == '__main__':
    unittest.main()
