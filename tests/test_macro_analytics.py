import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.macro_analytics_service import (
    annualized_change, build_macro_analytics_payload, calculate_sahm,
    cross_correlation, identify_inversion_episodes, pct_rank, rolling_z, yoy,
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


class PayloadContractTests(unittest.TestCase):
    def _db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript('''
        CREATE TABLE monthly_data(month TEXT PRIMARY KEY,M2y REAL,SFy REAL,loany REAL);
        CREATE TABLE china_rates_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE fiscal_budget_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE fiscal_debt_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE housing_national_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE us_macro_observations(indicator_code TEXT,period TEXT,value REAL);
        ''')
        conn.commit(); conn.close()

    def test_empty_payload_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'x.db'); self._db(path)
            payload = build_macro_analytics_payload(path)
        for section in ('china', 'us', 'cross'):
            for item in payload[section].get('positioning', []) + payload[section].get('analyses', []):
                for key in ('method','sample_start','sample_end','n_obs','data_status'):
                    self.assertIn(key, item)


if __name__ == '__main__':
    unittest.main()
