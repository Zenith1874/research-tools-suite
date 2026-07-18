import unittest
from pathlib import Path

from services.fiscal_budget_service import (
    build_budget_forecast,
    derive_budget_values,
    parse_budget_period_from_title,
    parse_budget_report_text,
)


class FiscalBudgetParserTests(unittest.TestCase):
    def test_land_transfer_revenue_fullwidth_growth_and_decline(self):
        decline = parse_budget_report_text(
            '其中，国有土地使用权出让收入６，８０１亿元，同比下降２７．２０％。')
        self.assertEqual(decline['govfund_land_transfer_revenue_ytd'], 6801.0)
        self.assertEqual(decline['govfund_land_transfer_revenue_ytd_yoy_official'], -27.2)
        growth = parse_budget_report_text(
            '其中，国有土地使用权出让收入12,345亿元，比上年同期增长10.25%。')
        self.assertEqual(growth['govfund_land_transfer_revenue_ytd'], 12345.0)
        self.assertEqual(growth['govfund_land_transfer_revenue_ytd_yoy_official'], 10.25)

    def test_land_revenue_does_not_parse_related_expenditure(self):
        values = parse_budget_report_text(
            '国有土地使用权出让收入相关支出53606亿元，同比下降15.4%。')
        self.assertNotIn('govfund_land_transfer_revenue_ytd', values)

    def test_period_parser_accepts_legacy_annual_title(self):
        self.assertEqual(parse_budget_period_from_title('2011年公共财政收支情况'), '2011-12')
        self.assertEqual(parse_budget_period_from_title('2026年1-5月财政收支情况'), '2026-05')
        self.assertEqual(parse_budget_period_from_title('2024年11月财政收支情况'), '2024-11')

    def test_legacy_report_prefers_cumulative_value_over_month_value(self):
        values = parse_budget_report_text('''
            12月份，全国财政收入6340亿元。
            1-12月累计，全国财政收入83080亿元。
            12月份，全国财政支出17982亿元。
            1-12月累计，全国财政支出89575亿元。
        ''')
        self.assertEqual(values['general_budget_revenue_ytd'], 83080.0)
        self.assertEqual(values['general_budget_expenditure_ytd'], 89575.0)
        self.assertEqual(values['general_budget_balance_ytd'], -6495.0)

    def test_full_width_legacy_labels_and_all_derived_balances(self):
        values = parse_budget_report_text('''
            １－１２月累计，全国公共财政收入１１７２１０亿元。
            １－１２月累计，全国公共财政支出１２５７１２亿元。
            １－１２月累计，全国政府性基金收入３７５１７亿元。
            １－１２月累计，全国政府性基金支出３６０６９亿元。
        ''')
        self.assertEqual(values['gov_fund_balance_ytd'], 1448.0)
        self.assertEqual(values['combined_budget_revenue_ytd'], 154727.0)
        self.assertEqual(values['combined_budget_expenditure_ytd'], 161781.0)
        self.assertEqual(values['combined_budget_balance_ytd'], -7054.0)

    def test_tax_subitem_not_mistaken_for_total_revenue(self):
        # "全国财政收入中，税收收入X" 的子项不得被当成总收入;
        # 且宽松变体'财政收入'不得吃掉'政府性基金收入'。
        text = ('1-5月，全国一般公共预算收入100465亿元。其中，全国税收收入82617亿元。'
                '全国政府性基金预算收入12518亿元。')
        vals = parse_budget_report_text(text)
        self.assertEqual(vals['general_budget_revenue_ytd'], 100465.0)
        self.assertEqual(vals['gov_fund_revenue_ytd'], 12518.0)

    def test_combined_values_require_both_accounts(self):
        values = derive_budget_values({
            'general_budget_revenue_ytd': 100.0,
            'general_budget_expenditure_ytd': 120.0,
        })
        self.assertEqual(values['general_budget_balance_ytd'], -20.0)
        self.assertNotIn('combined_budget_balance_ytd', values)


class FiscalBudgetForecastTests(unittest.TestCase):
    def test_forecast_keeps_scenarios_separate_from_official_history(self):
        annual = [
            {'period': '2023', 'year': 2023, 'general_budget_revenue_ytd': 200.0,
             'general_budget_expenditure_ytd': 250.0, 'gov_fund_revenue_ytd': 80.0,
             'gov_fund_expenditure_ytd': 100.0},
            {'period': '2024', 'year': 2024, 'general_budget_revenue_ytd': 204.0,
             'general_budget_expenditure_ytd': 260.0, 'gov_fund_revenue_ytd': 72.0,
             'gov_fund_expenditure_ytd': 105.0},
            {'period': '2025', 'year': 2025, 'general_budget_revenue_ytd': 206.0,
             'general_budget_expenditure_ytd': 270.0, 'gov_fund_revenue_ytd': 68.0,
             'gov_fund_expenditure_ytd': 110.0},
        ]
        series = [
            {'period': '2025-05', 'general_budget_revenue_ytd': 90.0,
             'general_budget_expenditure_ytd': 100.0, 'gov_fund_revenue_ytd': 30.0,
             'gov_fund_expenditure_ytd': 45.0},
            {'period': '2026-05', 'general_budget_revenue_ytd': 92.0,
             'general_budget_expenditure_ytd': 106.0, 'gov_fund_revenue_ytd': 27.0,
             'gov_fund_expenditure_ytd': 50.0},
        ]
        forecast = build_budget_forecast(annual, series, horizon=3)
        self.assertEqual(forecast['anchor_year'], 2025)
        self.assertEqual(forecast['latest_ytd_period'], '2026-05')
        self.assertEqual(set(forecast['scenarios']), {'baseline', 'improvement', 'pressure'})
        baseline = forecast['scenarios']['baseline']['records'][0]
        improvement = forecast['scenarios']['improvement']['records'][0]
        pressure = forecast['scenarios']['pressure']['records'][0]
        self.assertEqual(baseline['data_status'], 'scenario')
        self.assertGreater(improvement['combined_budget_balance_ytd'], baseline['combined_budget_balance_ytd'])
        self.assertLess(pressure['combined_budget_balance_ytd'], baseline['combined_budget_balance_ytd'])


class FiscalBudgetPageContractTests(unittest.TestCase):
    def test_page_exposes_account_and_scenario_switches(self):
        page = (Path(__file__).resolve().parents[1] / 'static' / 'fiscal_debt.html').read_text(
            encoding='utf-8')
        for text in ('财政收入与支出', '一般公共预算', '政府性基金', '两本账简单相加',
                     "useState('baseline')", 'forecast?.scenarios', '年度财政收支'):
            self.assertIn(text, page)


if __name__ == '__main__':
    unittest.main()
