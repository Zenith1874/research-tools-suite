import unittest
from pathlib import Path

from services.fiscal_monitor_service import (
    _median_balance_growth,
    align_interest_income_scenario,
    build_liquidity_timeline,
    build_local_borrow_repay_panorama,
    build_omo_cumulative_step,
    estimate_local_maturity,
    project_interest_path,
)


class FiscalCashflowPrimitiveTests(unittest.TestCase):
    def test_interest_projection_uses_latest_three_growth_median_and_fixed_rate(self):
        annual = {
            2021: {'balance': 100.0}, 2022: {'balance': 110.0},
            2023: {'balance': 132.0}, 2024: {'balance': 145.2},
        }
        growth = _median_balance_growth(annual, 'balance', lookback=3)
        self.assertAlmostEqual(growth, 0.10)
        rows = project_interest_path(145.2, growth, 2.5, 2024, horizon=3)
        self.assertEqual([row['period'] for row in rows], ['2025', '2026', '2027'])
        self.assertEqual({row['interest_rate_pct'] for row in rows}, {2.5})
        self.assertAlmostEqual(rows[0]['projected_interest'], 4.0, places=1)
        self.assertTrue(all(row['data_status'] == 'scenario' for row in rows))

    def test_interest_scenario_aligns_income_by_exact_year(self):
        local = [{'period': '2026', 'projected_interest': 60.0}]
        treasury = [{'period': '2026', 'projected_interest': 40.0}]
        income = [{'period': '2026', 'general_budget_revenue_ytd': 2000.0},
                  {'period': '2027', 'general_budget_revenue_ytd': 2100.0}]
        rows = align_interest_income_scenario(local, treasury, income, 'baseline')
        self.assertEqual(rows[0]['interest_to_revenue_pct'], 5.0)
        self.assertIsNone(rows[1]['interest_to_revenue_pct'])
        self.assertEqual(rows[0]['data_status'], 'scenario')

    def test_local_maturity_requires_remaining_term(self):
        self.assertEqual(estimate_local_maturity(581453.0, 10.7), 54341.4)
        self.assertIsNone(estimate_local_maturity(581453.0, None))
        self.assertIsNone(estimate_local_maturity(581453.0, 0))

    def test_local_borrow_repay_panorama_reconciles_issuance(self):
        source = [{
            'period': '2025-12', 'local_new_bond_issuance_ytd': 53817.0,
            'local_refinancing_bond_issuance_ytd': 49284.0,
            'official_principal_repayment_ytd': 30254.0,
            'official_interest_payment_ytd': 14843.0,
            'source_url': 'https://example.test/official',
        }]
        row = build_local_borrow_repay_panorama(source, 2025, 2025)[0]
        self.assertEqual(row['local_issuance'], 103101.0)
        self.assertEqual(row['local_net_increase'], 72847.0)
        self.assertAlmostEqual(row['local_refinancing_share_pct'], 47.8017)
        self.assertEqual(row['data_status'], 'official')

    def test_omo_step_holds_not_conducted_and_does_not_create_missing_month(self):
        rows = build_omo_cumulative_step([
            {'period': '2024-12', 'net_purchase_amount': 3000.0, 'operation_status': 'conducted'},
            {'period': '2025-01', 'net_purchase_amount': 0.0, 'operation_status': 'not_conducted'},
            {'period': '2025-03', 'net_purchase_amount': 0.0, 'operation_status': 'not_conducted'},
        ])
        self.assertEqual([row['period'] for row in rows], ['2024-12', '2025-01', '2025-03'])
        self.assertEqual([row['omo_cumulative_net_purchase'] for row in rows], [3000.0, 3000.0, 3000.0])

    def test_buyout_timeline_marks_completed_and_projected_separately(self):
        rows = build_liquidity_timeline([], [
            {'period': '2026-06', 'outstanding_amount': 54000.0},
        ], [
            {'period': '2026-07', 'outstanding_amount': 61000.0},
        ], [])
        self.assertEqual(rows[0]['buyout_repo_status'], 'derived')
        self.assertEqual(rows[1]['buyout_repo_status'], 'projected')
        self.assertNotIn('buyout_repo_projected_stock', rows[0])
        self.assertNotIn('buyout_repo_completed_stock', rows[1])

    def test_panorama_has_no_lgfv_numeric_field(self):
        row = build_local_borrow_repay_panorama([], 2025, 2025)[0]
        numeric_keys = [key.lower() for key, value in row.items()
                        if isinstance(value, (int, float))]
        self.assertFalse(any('lgfv' in key for key in numeric_keys))
        self.assertFalse(any('城投' in key for key in row))

    def test_page_exposes_cashflow_panorama_timeline_and_neutral_language(self):
        page = (Path(__file__).resolve().parents[1] / 'static' / 'fiscal_debt.html').read_text(
            encoding='utf-8')
        for expected in ('还本付息压力路径', '每年借多少、还多少', '新型流动性工具时间线',
                         '已知到期推算', '⬇ CSV'):
            self.assertIn(expected, page)
        for prohibited in ('印' + '钞', '货币' + '化', '认购' + '国债'):
            self.assertNotIn(prohibited, page)


if __name__ == '__main__':
    unittest.main()
