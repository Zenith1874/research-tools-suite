# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.macro_scenario_service import (
    GAP_CATALOG,
    build_macro_scenario_payload,
)


def _month(step):
    total = 2020 * 12 + step
    return f'{total // 12:04d}-{total % 12 + 1:02d}'


class MacroScenarioServiceTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        handle.close()
        self.path = handle.name
        conn = sqlite3.connect(self.path)
        conn.execute('''CREATE TABLE china_macro_observations (
            indicator_code TEXT, period TEXT, value REAL, data_status TEXT,
            source_name TEXT, source_url TEXT)''')
        conn.execute('''CREATE TABLE monthly_data (
            month TEXT, M2y REAL, M1y REAL, loany REAL, SFy REAL)''')
        conn.execute('''CREATE TABLE china_rates_observations (
            indicator_code TEXT, period TEXT, value REAL, data_status TEXT,
            source_name TEXT, source_url TEXT)''')
        conn.execute('''CREATE TABLE housing_national_observations (
            indicator_code TEXT, period TEXT, value REAL, data_status TEXT,
            source_name TEXT, source_url TEXT)''')

        # 36 monthly points with a mild cycle; the model must use only this
        # history and produce deterministic paths for a fixed seed.
        for step in range(36):
            period = _month(step)
            for code, value in (
                    ('CN_IP_YOY', 5.0 + (step % 6) * 0.12 - (0.04 if step > 24 else 0)),
                    ('CN_RETAIL_YOY', 6.0 + (step % 5) * 0.16),
                    ('CN_CPI_YOY', 1.2 - (step % 7) * 0.04)):
                conn.execute('INSERT INTO china_macro_observations VALUES (?,?,?,?,?,?)',
                             (code, period, value, 'official', '测试官方源',
                              f'https://example.test/{code}/{period}'))
            conn.execute('INSERT INTO monthly_data VALUES (?,?,?,?,?)',
                         (period, 8.0 + step * 0.02, 4.0 + step * 0.03,
                          10.0 - step * 0.01, 9.0 + step * 0.01))
            conn.execute('INSERT INTO china_rates_observations VALUES (?,?,?,?,?,?)',
                         ('LPR_5Y', period + '-20', 4.2 - step * 0.01, 'official',
                          '测试利率源', f'https://example.test/lpr/{period}'))
        # 24 quarterly points stored in the same YYYY-MM convention as the
        # current China GDP service (03/06/09/12).
        for step in range(24):
            year = 2018 + step // 4
            month = (step % 4 + 1) * 3
            period = f'{year:04d}-{month:02d}'
            value = 6.0 - step * 0.04 + (0.08 if step % 3 == 0 else 0)
            conn.execute('INSERT INTO china_macro_observations VALUES (?,?,?,?,?,?)',
                         ('CN_GDP_Q_REAL_YOY', period, value, 'official', '测试官方源',
                          f'https://example.test/gdp/{period}'))
        for step in range(36):
            period = _month(step)
            conn.execute('INSERT INTO housing_national_observations VALUES (?,?,?,?,?,?)',
                         ('sales_area_ytd_yoy_official', period, -8 + step * 0.05,
                          'official', '测试地产源', f'https://example.test/sales/{period}'))
        conn.commit()
        conn.close()

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def test_quarterly_selection_preserves_quarter_end_periods(self):
        payload = build_macro_scenario_payload(
            self.path, indicator='CN_GDP_Q_REAL_YOY', horizon=4,
            simulations=200, seed=7)
        selected = payload['selected']
        self.assertEqual(selected['status'], 'ok')
        self.assertEqual(selected['sample_start'], '2018-03')
        self.assertEqual(selected['sample_end'], '2023-12')
        self.assertEqual(len(selected['scenarios']), 3)
        self.assertEqual(selected['scenarios'][0]['path'][0]['period'], '2024-03')
        self.assertEqual(selected['scenarios'][0]['path'][-1]['period'], '2024-12')

    def test_scenarios_simulation_and_backtest_are_reproducible(self):
        first = build_macro_scenario_payload(
            self.path, indicator='CN_IP_YOY', horizon=6,
            simulations=250, seed=123)
        second = build_macro_scenario_payload(
            self.path, indicator='CN_IP_YOY', horizon=6,
            simulations=250, seed=123)
        selected = first['selected']
        self.assertEqual(selected['status'], 'ok')
        self.assertEqual(selected['simulation'], second['selected']['simulation'])
        self.assertEqual(selected['backtest']['status'], 'ok')
        self.assertGreater(selected['backtest']['n_origins'], 0)
        self.assertGreaterEqual(selected['backtest']['mae'], 0)
        self.assertEqual(selected['simulation']['simulations'], 250)
        paths = selected['scenarios']
        self.assertLessEqual(paths[0]['end_value'], paths[1]['end_value'] * 2)
        self.assertGreaterEqual(paths[0]['end_value'], paths[1]['end_value'])
        self.assertGreaterEqual(paths[1]['end_value'], paths[2]['end_value'])
        for point in selected['simulation']['points']:
            self.assertLessEqual(point['p10'], point['p50'])
            self.assertLessEqual(point['p50'], point['p90'])

    def test_catalog_exposes_available_series_and_explicit_gaps(self):
        payload = build_macro_scenario_payload(self.path, indicator='M2y', horizon=3)
        catalog = {row['code']: row for row in payload['catalog']}
        self.assertEqual(catalog['M2y']['status'], 'ok')
        self.assertEqual(catalog['LPR_5Y']['status'], 'ok')
        self.assertIn('CN_INDUSTRIAL_PROFIT', {row['code'] for row in payload['gaps']})
        self.assertEqual(len(payload['gaps']), len(GAP_CATALOG))
        self.assertEqual(payload['selected']['code'], 'M2y')
        self.assertEqual(payload['data_status'], 'scenario')

    def test_unknown_indicator_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '未知宏观情景指标'):
            build_macro_scenario_payload(self.path, indicator='not-real')


if __name__ == '__main__':
    unittest.main()
