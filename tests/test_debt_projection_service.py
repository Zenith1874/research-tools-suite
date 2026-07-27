# -*- coding: utf-8 -*-
"""推演的边界行为：结论必须随假设变化，且不能凭空断言。"""
import unittest

from services.debt_projection_service import (
    project_limit_constraint, project_interest_burden, parse_overrides, _cagr,
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


if __name__ == '__main__':
    unittest.main()
