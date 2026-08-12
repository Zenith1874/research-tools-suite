# -*- coding: utf-8 -*-
"""推演的边界行为：结论必须随假设变化，且不能凭空断言。"""
import unittest
import sqlite3
import os
import tempfile
from pathlib import Path

from services.debt_projection_service import (
    project_limit_constraint, project_interest_burden, parse_overrides, _cagr,
    _growth_sample, current_local_limit_monitor, build_sensitivity,
    estimate_hidden_debt_range, build_broad_government_debt,
    audit_lgfv_records, upsert_broad_debt_anchors,
)


def _years(pairs):
    return [{'period': p, 'treasury_limit': l, 'treasury_balance': b,
             'local_limit': None, 'local_balance': None} for p, l, b in pairs]


class LimitConstraintTests(unittest.TestCase):
    def test_headroom_closes_when_balance_outgrows_limit(self):
        result = project_limit_constraint(_years([
            ('2022', 100.0, 90.0), ('2023', 110.0, 101.0),
            ('2024', 121.0, 113.0), ('2025', 133.1, 127.0)]))['treasury']
        self.assertEqual(result['status'], 'projected')
        self.assertGreater(result['balance_growth'], result['limit_growth'])
        self.assertIsNotNone(result['hit_year'])

    def test_headroom_never_closes_when_limit_outgrows_balance(self):
        """限额涨得比余额快时不得编造一个归零年份。"""
        result = project_limit_constraint(_years([
            ('2022', 100.0, 95.0), ('2023', 120.0, 100.0),
            ('2024', 144.0, 105.0), ('2025', 172.8, 110.0)]))['treasury']
        self.assertIsNone(result['hit_year'])
        self.assertLess(result['balance_growth'], result['limit_growth'])

    def test_single_year_is_not_enough_to_extrapolate(self):
        result = project_limit_constraint(_years([('2025', 100.0, 90.0)]))['treasury']
        self.assertEqual(result['status'], 'insufficient_history')

    def test_missing_side_is_skipped_not_guessed(self):
        result = project_limit_constraint(_years([
            ('2024', None, 90.0), ('2025', 100.0, 95.0)]))['treasury']
        self.assertEqual(result['status'], 'insufficient_history')

    def test_window_is_a_natural_year_span_not_a_point_count(self):
        years = _years([(str(year), 100.0 * 1.1 ** (year - 2020),
                         90.0 * 1.12 ** (year - 2020))
                        for year in range(2020, 2026)])
        sample = _growth_sample(years, 'treasury_limit', window=4)
        self.assertEqual(sample['sample_start'], '2021')
        self.assertEqual(sample['sample_end'], '2025')
        self.assertEqual(sample['n_obs'], 5)
        self.assertEqual(sample['span_years'], 4)

    def test_next_year_official_limit_is_used_with_scenario_balance(self):
        years = _years([
            ('2022', 100.0, 90.0), ('2023', 110.0, 101.0),
            ('2024', 121.0, 113.0), ('2025', 133.1, 127.0),
            ('2026', 150.0, None),
        ])
        result = project_limit_constraint(years, window=4)['treasury']
        self.assertEqual(result['base_year'], '2026')
        self.assertEqual(result['base_limit'], 150.0)
        self.assertEqual(result['base_limit_data_status'], 'official')
        self.assertEqual(result['base_balance_data_status'], 'scenario')
        self.assertEqual(result['latest_official_limit_year'], '2026')
        self.assertEqual(result['latest_actual_balance_year'], '2025')


class CurrentMonitorTests(unittest.TestCase):
    def test_latest_month_is_compared_with_limit_without_filling_missing_month(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('''CREATE TABLE fiscal_debt_observations
                        (indicator_code TEXT,period TEXT,value REAL,source_url TEXT)''')
        conn.executemany('INSERT INTO fiscal_debt_observations VALUES (?,?,?,?)', [
            ('local_debt_balance_total', '2026-01', 555774.0, 'u1'),
            ('local_debt_balance_total', '2026-02', 565936.0, 'u2'),
            ('local_debt_balance_total', '2026-04', 576139.0, 'u4'),
            ('local_debt_balance_total', '2026-06', 587706.0, 'u6'),
        ])
        monitor = current_local_limit_monitor(conn, [{
            'period': '2026', 'local_limit': 631874.30,
            'local_limit_status': 'incomplete',
        }])
        conn.close()
        self.assertEqual(monitor['latest_period'], '2026-06')
        self.assertEqual([row['period'] for row in monitor['series']],
                         ['2026-01', '2026-02', '2026-04', '2026-06'])
        self.assertAlmostEqual(monitor['latest_headroom'], 44168.30, places=2)
        self.assertAlmostEqual(monitor['latest_utilisation'], 93.010, places=3)
        self.assertEqual(monitor['n_obs'], 4)
        self.assertEqual(monitor['sample_start'], '2026-01')
        self.assertEqual(monitor['sample_end'], '2026-06')
        self.assertEqual(monitor['balance_data_status'], 'official')
        self.assertEqual(monitor['headroom_data_status'], 'derived')


class SensitivityTests(unittest.TestCase):
    def test_higher_growth_does_not_move_limit_hit_later(self):
        years = []
        for year in range(2018, 2026):
            step = year - 2018
            years.append({
                'period': str(year),
                'treasury_limit': 100.0 * 1.08 ** step,
                'treasury_balance': 90.0 * 1.10 ** step,
                'local_limit': 200.0 * 1.07 ** step,
                'local_balance': 170.0 * 1.10 ** step,
            })
        revenue = {str(year): 100.0 * 1.03 ** (year - 2018)
                   for year in range(2018, 2026)}
        interest = {str(year): 5.0 * 1.09 ** (year - 2018)
                    for year in range(2018, 2026)}
        rows = build_sensitivity(years, revenue, interest, 4, 7, 25)['rows']
        easing, base, stress = rows

        def year_or_infinity(value):
            return int(value) if value else float('inf')

        for key in ('treasury_hit_year', 'local_hit_year', 'interest_10_hit_year'):
            self.assertGreaterEqual(year_or_infinity(easing[key]),
                                    year_or_infinity(base[key]))
            self.assertGreaterEqual(year_or_infinity(base[key]),
                                    year_or_infinity(stress[key]))


class InterestBurdenTests(unittest.TestCase):
    REVENUE = {'2018': 100.0, '2019': 105.0, '2020': 110.25, '2021': 115.76}
    INTEREST = {'2018': 5.0, '2019': 6.0, '2020': 7.2, '2021': 8.64}

    def test_thresholds_are_reached_in_increasing_order(self):
        result = project_interest_burden(self.REVENUE, self.INTEREST, window=3)
        self.assertEqual(result['status'], 'projected')
        years = [result['threshold_years'][k] for k in ('10%', '15%', '20%')]
        self.assertTrue(all(years), years)
        self.assertLessEqual(years[0], years[1])
        self.assertLessEqual(years[1], years[2])

    def test_flat_ratio_never_crosses(self):
        """付息与收入同速增长时占比恒定，不得给出触线年份。"""
        revenue = {str(2018 + i): 100.0 * 1.05 ** i for i in range(5)}
        interest = {str(2018 + i): 5.0 * 1.05 ** i for i in range(5)}
        result = project_interest_burden(revenue, interest, window=4)
        self.assertEqual(result['base_ratio'], 5.0)
        self.assertEqual(set(result['threshold_years'].values()), {None})

    def test_history_is_reported_alongside_projection(self):
        result = project_interest_burden(self.REVENUE, self.INTEREST, window=3)
        self.assertEqual(len(result['history']), 4)
        self.assertAlmostEqual(result['history'][0]['ratio'], 5.0)

    def test_insufficient_history(self):
        self.assertEqual(project_interest_burden({'2025': 1.0}, {'2025': 0.1})['status'],
                         'insufficient_history')


class OverrideTests(unittest.TestCase):
    YEARS = _years([('2022', 100.0, 90.0), ('2023', 110.0, 101.0),
                    ('2024', 121.0, 113.0), ('2025', 133.1, 127.0)])

    def test_override_replaces_derived_growth_but_keeps_it_visible(self):
        base = project_limit_constraint(self.YEARS)['treasury']
        tuned = project_limit_constraint(
            self.YEARS, overrides={'treasury_balance_growth': 0.01})['treasury']
        self.assertEqual(tuned['balance_growth'], 0.01)
        self.assertEqual(tuned['derived_balance_growth'], base['balance_growth'])
        self.assertEqual(tuned['overridden'], ['balance_growth'])
        # 余额几乎不涨而限额继续涨 → 不再归零
        self.assertIsNotNone(base['hit_year'])
        self.assertIsNone(tuned['hit_year'])

    def test_interest_override_moves_the_threshold_year_later(self):
        revenue = {str(2018 + i): 100.0 * 1.02 ** i for i in range(8)}
        interest = {str(2018 + i): 5.0 * 1.09 ** i for i in range(8)}
        base = project_interest_burden(revenue, interest)
        tuned = project_interest_burden(revenue, interest,
                                        overrides={'revenue_growth': 0.08})
        self.assertEqual(tuned['overridden'], ['revenue_growth'])
        self.assertLess(base['threshold_years']['10%'], tuned['threshold_years']['10%'])

    def test_parse_overrides_converts_percent_and_rejects_junk(self):
        parsed = parse_overrides({'revenue_growth': '5', 'interest_growth': '2.5',
                                  'treasury_limit_growth': 'abc',
                                  'local_limit_growth': '999',
                                  'local_balance_growth': '-80',
                                  'unknown_key': '3'})
        self.assertAlmostEqual(parsed['revenue_growth'], 0.05)
        self.assertAlmostEqual(parsed['interest_growth'], 0.025)
        self.assertNotIn('treasury_limit_growth', parsed)   # 非数字
        self.assertNotIn('local_limit_growth', parsed)      # 超过 100%
        self.assertNotIn('local_balance_growth', parsed)    # 低于 -50%
        self.assertNotIn('unknown_key', parsed)             # 不在白名单

    def test_empty_and_none_are_ignored(self):
        self.assertEqual(parse_overrides({'revenue_growth': ''}), {})
        self.assertEqual(parse_overrides(None), {})


class CagrTests(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(_cagr(100.0, 121.0, 2), 0.10, places=9)

    def test_guards(self):
        self.assertIsNone(_cagr(0.0, 10.0, 2))
        self.assertIsNone(_cagr(10.0, 0.0, 2))
        self.assertIsNone(_cagr(10.0, 20.0, 0))


class BroadGovernmentDebtTests(unittest.TestCase):
    YEARS = [
        {'period': '2023', 'treasury_balance': 300325.50,
         'local_balance': 407372.93},
        {'period': '2024', 'treasury_balance': 345723.62,
         'local_balance': 475370.55},
        {'period': '2025', 'treasury_balance': 412317.68,
         'local_balance': 548230.82},
    ]

    def test_hidden_debt_range_is_a_non_probabilistic_policy_bridge(self):
        result = estimate_hidden_debt_range(105000.0, 20000.0, 8000.0)
        self.assertEqual(result['status'], 'scenario')
        self.assertEqual(result['low'], 77000.0)
        self.assertEqual(result['mid'], 81000.0)
        self.assertEqual(result['high'], 85000.0)
        self.assertIn('无概率含义', result['assumption'])

    def test_2024_is_official_anchor_and_2025_is_scenario_range(self):
        payload = build_broad_government_debt(self.YEARS)
        by_period = {row['period']: row for row in payload['records']}
        official = by_period['2024']
        scenario = by_period['2025']
        self.assertEqual(official['hidden_debt_mid'], 105000.0)
        self.assertEqual(official['hidden_data_status'], 'official')
        self.assertEqual(scenario['legal_debt_total'], 960548.5)
        self.assertEqual(scenario['hidden_debt_low'], 77000.0)
        self.assertEqual(scenario['hidden_debt_high'], 85000.0)
        self.assertEqual(scenario['broad_total_low'], 1037548.5)
        self.assertEqual(scenario['broad_total_high'], 1045548.5)
        self.assertEqual(scenario['data_status'], 'scenario')
        self.assertGreater(scenario['debt_to_gdp_high_pct'],
                           scenario['debt_to_gdp_low_pct'])

    def test_lgfv_placeholder_is_not_treated_as_data(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('''CREATE TABLE fiscal_debt_observations
                        (debt_line TEXT,indicator_code TEXT,period TEXT,
                         source_type TEXT,source_url TEXT)''')
        audit = audit_lgfv_records(conn)
        conn.close()
        self.assertEqual(audit['record_count'], 0)
        self.assertEqual(audit['data_status'], 'missing')
        self.assertFalse(audit['included_in_broad_total'])
        self.assertIn('不等于', audit['scope_note'])

    def test_official_anchor_upsert_is_idempotent_and_sourced(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        db_path = handle.name
        handle.close()
        try:
            first = upsert_broad_debt_anchors(db_path)
            second = upsert_broad_debt_anchors(db_path)
            self.assertTrue(first['success'])
            self.assertTrue(second['success'])
            conn = sqlite3.connect(db_path)
            rows = conn.execute('''
                SELECT indicator_code,period,value,data_status,source_url
                FROM fiscal_debt_observations
                WHERE module_code='broad_government_debt'
                ORDER BY period,indicator_code
            ''').fetchall()
            conn.close()
            self.assertEqual(len(rows), 12)
            self.assertTrue(all(row[3] == 'official' for row in rows))
            self.assertTrue(all(row[4].startswith('https://') for row in rows))
        finally:
            os.unlink(db_path)


class DebtCeilingPageContractTests(unittest.TestCase):
    def test_page_separates_current_actual_monitor_from_yearend_scenario(self):
        page = (Path(__file__).resolve().parents[1] / 'static' /
                'debt_ceiling.html').read_text(encoding='utf-8')
        self.assertIn('id="localMonitorChart"', page)
        self.assertIn('id="sensitivityBody"', page)
        self.assertIn('缺月不插值、不连线', page)
        self.assertIn('两者不可混同', page)
        self.assertIn('年末余额尚未公布，基期余额为情景值', page)
        self.assertIn('年度限额原文', page)
        self.assertIn('id="broadDebtChart"', page)
        self.assertIn('复合年增速（CAGR）', page)
        self.assertIn('不等同城投债', page)
        self.assertIn('id="lgfvMaturityChart"', page)
        self.assertIn('id="lgfvBalanceChart"', page)
        self.assertIn('id="lgfvCashChart"', page)
        self.assertIn('id="lgfv_scope"', page)
        self.assertIn('缺失不机械放大', page)
        self.assertIn('绝不进入官方法定债务', page)


if __name__ == '__main__':
    unittest.main()
