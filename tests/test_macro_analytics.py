import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.macro_analytics_service import (
    annualized_change, build_housing_analytics, build_macro_analytics_payload,
    calculate_sahm, cross_correlation, _diffusion_from_rows,
    identify_inversion_episodes, pct_rank, rolling_z, yoy,
)


class StatisticalPrimitiveTests(unittest.TestCase):
    def test_pct_rank_inclusive(self):
        self.assertEqual(pct_rank([1, 2, 3, 4], 3), 75.0)

    def test_rolling_z_latest(self):
        self.assertAlmostEqual(rolling_z([1, 2, 3], 3), (3 - 2) / math.sqrt(2 / 3), places=4)

    def test_annualized_change(self):
        monthly = [100 * (1.01 ** i) for i in range(13)]
        self.assertAlmostEqual(annualized_change(monthly, 3), (1.01 ** 12 - 1) * 100, places=4)

    def test_yoy_does_not_bridge_missing_calendar_period(self):
        rows = [{'period': '2024-01', 'value': 100}, {'period': '2025-02', 'value': 110}]
        self.assertEqual(yoy(rows, 12), [])

    def test_cross_correlation_positive_lag_means_x_leads_y(self):
        x = list(range(40))
        y = [0, 0, 0] + x[:-3]
        result = cross_correlation(x, y, 6, min_n=24)
        self.assertEqual(result['peak_lag'], 3)
        self.assertAlmostEqual(result['peak_corr'], 1.0, places=4)

    def test_sahm_three_month_average_trigger(self):
        values = [4.0] * 14 + [4.3, 4.6, 4.9]
        rows = [{'period': f'2024-{i+1:02d}', 'value': v} for i, v in enumerate(values[:12])]
        rows += [{'period': f'2025-{i+1:02d}', 'value': v} for i, v in enumerate(values[12:])]
        result = calculate_sahm(rows)
        self.assertEqual(result[-1]['value'], 0.6)
        self.assertTrue(result[-1]['triggered'])

    def test_inversion_ignores_one_month_fragment(self):
        rows = [{'period': f'2024-{i+1:02d}', 'value': v}
                for i, v in enumerate([1, -0.1, 0.1, -0.2, -0.4, -0.3, 0.2])]
        episodes = identify_inversion_episodes(rows)
        self.assertEqual(len(episodes), 1)
        self.assertEqual((episodes[0]['start'], episodes[0]['end']), ('2024-04', '2024-06'))

    def test_insufficient_cross_correlation_guard(self):
        result = cross_correlation(range(20), range(20), 3, min_n=24)
        self.assertEqual(result['data_status'], 'insufficient_sample')

    def test_diffusion_index_counts_rising_cities(self):
        # 上月=100 口径：>100 上涨，<100 下跌，==100 持平
        rows = [{'period': '2026-06', 'value': v} for v in (101.0, 100.5, 100.0, 99.5, 99.0)]
        series = _diffusion_from_rows(rows)
        self.assertEqual(len(series), 1)
        point = series[0]
        self.assertEqual((point['up'], point['flat'], point['down']), (2, 1, 2))
        self.assertEqual(point['value'], 40.0)  # 2/5 上涨

    def test_diffusion_index_separates_periods(self):
        rows = [{'period': '2026-05', 'value': 101.0}, {'period': '2026-05', 'value': 99.0},
                {'period': '2026-06', 'value': 101.0}, {'period': '2026-06', 'value': 101.0}]
        series = _diffusion_from_rows(rows)
        self.assertEqual([p['value'] for p in series], [50.0, 100.0])


class PayloadContractTests(unittest.TestCase):
    def _db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript('''
        CREATE TABLE monthly_data(month TEXT PRIMARY KEY,M1y REAL,M2y REAL,SFy REAL,loany REAL);
        CREATE TABLE china_rates_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE fiscal_budget_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE fiscal_debt_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE housing_national_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE housing_city_observations(city TEXT,period TEXT,indicator_code TEXT,value REAL);
        CREATE TABLE us_macro_observations(indicator_code TEXT,period TEXT,value REAL);
        ''')
        conn.commit(); conn.close()

    def test_empty_payload_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'x.db'); self._db(path)
            payload = build_macro_analytics_payload(path)
        for section in ('china', 'us', 'cross', 'housing'):
            for item in payload[section].get('positioning', []) + payload[section].get('analyses', []):
                for key in ('method','sample_start','sample_end','n_obs','data_status'):
                    self.assertIn(key, item)

    def test_housing_diffusion_analytics_from_city_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'h.db'); self._db(path)
            conn = sqlite3.connect(path)
            cities = ['北京', '上海', '广州', '深圳', '成都', '西安', '大连', '厦门']
            for pi, period in enumerate(('2026-05', '2026-06')):
                for ci, city in enumerate(cities):
                    # 让一线城市多数上涨、其余多数下跌，构造可判定的分化
                    tier1 = city in ('北京', '上海', '广州', '深圳')
                    val = 100.5 if tier1 else 99.5
                    conn.execute("INSERT INTO housing_city_observations VALUES(?,?,?,?)",
                                 (city, period, 'new_home_mom_idx', val))
                    conn.execute("INSERT INTO housing_city_observations VALUES(?,?,?,?)",
                                 (city, period, 'second_home_mom_idx', val - 0.3))
            conn.commit(); conn.close()
            block = build_housing_analytics(path)
        titles = {i['title'] for i in block['positioning'] + block['analyses']}
        self.assertIn('70城新房扩散指数', titles)
        split = next(i for i in block['analyses'] if i['title'] == '一线-非一线分化')
        self.assertGreater(split['value'], 0)  # 一线扩散(100%) 高于其余(0%)


if __name__ == '__main__':
    unittest.main()
