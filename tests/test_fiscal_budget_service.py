import unittest
import sqlite3
import tempfile
from pathlib import Path

from services.fiscal_budget_service import (
    build_land_transfer_annual_series,
    build_land_transfer_half_year_analysis,
    build_budget_half_year_analysis,
    build_budget_monthly_coverage,
    build_budget_forecast,
    derive_monthly_budget_series,
    derive_budget_values,
    parse_budget_index_links,
    parse_budget_period_from_title,
    parse_budget_report_text,
    simulate_budget_uncertainty,
    upsert_land_transfer_annual_backfill,
)


class FiscalBudgetParserTests(unittest.TestCase):
    def test_budget_interest_expenditure_growth_and_decline(self):
        growth = parse_budget_report_text(
            '其中，债务付息支出６，８０１亿元，同比增长２．７５％。')
        self.assertEqual(growth['budget_interest_expenditure_ytd'], 6801.0)
        self.assertEqual(growth['budget_interest_expenditure_ytd_yoy_official'], 2.75)
        decline = parse_budget_report_text(
            '债务付息支出12345亿元，比上年同期下降10.25%。')
        self.assertEqual(decline['budget_interest_expenditure_ytd'], 12345.0)
        self.assertEqual(decline['budget_interest_expenditure_ytd_yoy_official'], -10.25)

    def test_land_transfer_revenue_fullwidth_growth_and_decline(self):
        decline = parse_budget_report_text(
            '其中，国有土地使用权出让收入６，８０１亿元，同比下降２７．２０％。')
        self.assertEqual(decline['govfund_land_transfer_revenue_ytd'], 6801.0)
        self.assertEqual(decline['govfund_land_transfer_revenue_ytd_yoy_official'], -27.2)
        growth = parse_budget_report_text(
            '其中，国有土地使用权出让收入12,345亿元，比上年同期增长10.25%。')
        self.assertEqual(growth['govfund_land_transfer_revenue_ytd'], 12345.0)
        self.assertEqual(growth['govfund_land_transfer_revenue_ytd_yoy_official'], 10.25)

    def test_total_fund_revenue_official_yoy_is_separate_from_land_revenue(self):
        values = parse_budget_report_text('''
            上半年，全国政府性基金预算收入１５，２４４亿元，同比下降２１．６％。
            地方政府性基金预算本级收入12847亿元，同比下降25.6%，其中，
            国有土地使用权出让收入9778亿元，同比下降31.5%。
        ''')
        self.assertEqual(values['gov_fund_revenue_ytd'], 15244.0)
        self.assertEqual(values['gov_fund_revenue_ytd_yoy_official'], -21.6)
        self.assertEqual(values['govfund_land_transfer_revenue_ytd'], 9778.0)
        self.assertEqual(values['govfund_land_transfer_revenue_ytd_yoy_official'], -31.5)

    def test_total_fiscal_official_yoys_are_parsed_separately(self):
        values = parse_budget_report_text('''
            上半年，全国一般公共预算收入121047亿元，同比增长4.7%。
            上半年，全国一般公共预算支出143329亿元，同比增长1.5%。
            上半年，全国政府性基金预算收入15244亿元，同比下降21.6%。
            上半年，全国政府性基金预算支出38705亿元，同比下降16.4%。
        ''')
        self.assertEqual(values['general_budget_revenue_ytd_yoy_official'], 4.7)
        self.assertEqual(values['general_budget_expenditure_ytd_yoy_official'], 1.5)
        self.assertEqual(values['gov_fund_revenue_ytd_yoy_official'], -21.6)
        self.assertEqual(values['gov_fund_expenditure_ytd_yoy_official'], -16.4)

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

    def test_monthly_flow_keeps_jan_feb_combined_and_does_not_bridge_gap(self):
        series = [
            {'period': '2025-02', 'source_url': 'u02',
             'general_budget_revenue_ytd': 100.0, 'general_budget_expenditure_ytd': 120.0,
             'gov_fund_revenue_ytd': 50.0, 'gov_fund_expenditure_ytd': 60.0},
            {'period': '2025-03', 'source_url': 'u03',
             'general_budget_revenue_ytd': 130.0, 'general_budget_expenditure_ytd': 145.0,
             'gov_fund_revenue_ytd': 65.0, 'gov_fund_expenditure_ytd': 75.0},
            # April is intentionally absent. May cannot be derived, but June
            # can use the adjacent May YTD value once May is present.
            {'period': '2025-05', 'source_url': 'u05',
             'general_budget_revenue_ytd': 180.0, 'general_budget_expenditure_ytd': 200.0,
             'gov_fund_revenue_ytd': 80.0, 'gov_fund_expenditure_ytd': 95.0},
            {'period': '2025-06', 'source_url': 'u06',
             'general_budget_revenue_ytd': 210.0, 'general_budget_expenditure_ytd': 240.0,
             'gov_fund_revenue_ytd': 90.0, 'gov_fund_expenditure_ytd': 110.0},
        ]
        rows = {row['period']: row for row in derive_monthly_budget_series(series)}
        self.assertEqual(rows['2025-02']['flow_window'], '1-2月')
        self.assertEqual(rows['2025-02']['months_covered'], 2)
        self.assertEqual(rows['2025-02']['combined_budget_revenue_monthly'], 150.0)
        self.assertEqual(rows['2025-03']['general_budget_revenue_monthly'], 30.0)
        self.assertEqual(rows['2025-03']['combined_budget_expenditure_monthly'], 40.0)
        self.assertEqual(rows['2025-04']['data_status'], 'missing')
        self.assertIsNone(rows['2025-05']['general_budget_revenue_monthly'])
        self.assertIsNotNone(rows['2025-05']['missing_reason'])
        self.assertEqual(rows['2025-06']['combined_budget_revenue_monthly'], 40.0)

    def test_monthly_flow_resets_at_new_year(self):
        series = [
            {'period': '2024-12', 'source_url': 'u24',
             'general_budget_revenue_ytd': 1000.0, 'general_budget_expenditure_ytd': 900.0,
             'gov_fund_revenue_ytd': 200.0, 'gov_fund_expenditure_ytd': 180.0},
            {'period': '2025-02', 'source_url': 'u25',
             'general_budget_revenue_ytd': 120.0, 'general_budget_expenditure_ytd': 130.0,
             'gov_fund_revenue_ytd': 30.0, 'gov_fund_expenditure_ytd': 40.0},
        ]
        rows = {row['period']: row for row in derive_monthly_budget_series(series)}
        self.assertEqual(rows['2025-02']['combined_budget_revenue_monthly'], 150.0)
        self.assertEqual(rows['2025-02']['months_covered'], 2)

    def test_monthly_coverage_reports_joint_total_periods(self):
        series = [
            {'period': '2025-02', 'general_budget_revenue_ytd': 100.0,
             'general_budget_expenditure_ytd': 120.0, 'gov_fund_revenue_ytd': 50.0,
             'gov_fund_expenditure_ytd': 60.0},
            {'period': '2025-03', 'general_budget_revenue_ytd': 130.0,
             'general_budget_expenditure_ytd': 145.0, 'gov_fund_revenue_ytd': 65.0,
             'gov_fund_expenditure_ytd': 75.0},
        ]
        monthly = derive_monthly_budget_series(series)
        coverage = build_budget_monthly_coverage(series, monthly)
        self.assertEqual(coverage['joint_total_flow_periods'], 2)
        self.assertEqual(coverage['joint_total_latest'], '2025-03')
        self.assertIn('1月没有单独官方观测', ' '.join(coverage['warnings']))

    def test_budget_archive_parser_accepts_main_site_links_and_skips_self_link(self):
        html = '''
          <a href="/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/">全国财政收支情况</a>
          <a href="http://gks.mof.gov.cn/tongjishuju/202503/t1.htm">2025年1-2月财政收支情况</a>
          <a href='./202504/t2.htm'><span>2025年一季度财政收支情况</span></a>
        '''
        links = parse_budget_index_links(html, 'https://www.mof.gov.cn/archive/index.html')
        self.assertEqual([title for _, title in links],
                         ['2025年1-2月财政收支情况', '2025年一季度财政收支情况'])
        self.assertEqual(links[1][0], 'https://www.mof.gov.cn/archive/202504/t2.htm')


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

    def test_forecast_prefers_official_fund_yoy_and_discloses_bound(self):
        annual = [
            {'period': '2024', 'year': 2024, 'general_budget_revenue_ytd': 200.0,
             'general_budget_expenditure_ytd': 240.0, 'gov_fund_revenue_ytd': 80.0,
             'gov_fund_expenditure_ytd': 100.0},
            {'period': '2025', 'year': 2025, 'general_budget_revenue_ytd': 205.0,
             'general_budget_expenditure_ytd': 250.0, 'gov_fund_revenue_ytd': 75.0,
             'gov_fund_expenditure_ytd': 105.0},
        ]
        series = [
            {'period': '2025-06', 'general_budget_revenue_ytd': 100.0,
             'general_budget_expenditure_ytd': 120.0, 'gov_fund_revenue_ytd': 50.0,
             'gov_fund_expenditure_ytd': 60.0},
            {'period': '2026-06', 'general_budget_revenue_ytd': 102.0,
             'general_budget_expenditure_ytd': 122.0, 'gov_fund_revenue_ytd': 45.0,
             'gov_fund_revenue_ytd_yoy_official': -21.6,
             'gov_fund_expenditure_ytd': 61.0},
        ]
        forecast = build_budget_forecast(annual, series, horizon=1)
        self.assertEqual(
            forecast['first_year_growth_rate_sources']['gov_fund_revenue_ytd'],
            'official_comparable_yoy')
        self.assertAlmostEqual(
            forecast['first_year_growth_rates_raw']['gov_fund_revenue_ytd'], -0.216)
        self.assertAlmostEqual(
            forecast['first_year_growth_rates']['gov_fund_revenue_ytd'], -0.20)

    def test_joint_bootstrap_is_reproducible_and_orders_balance_quantiles(self):
        annual = []
        for offset, year in enumerate(range(2019, 2026)):
            annual.append({
                'period': str(year), 'year': year,
                'general_budget_revenue_ytd': 180.0 * (1.025 ** offset),
                'general_budget_expenditure_ytd': 220.0 * (1.04 ** offset),
                'gov_fund_revenue_ytd': 100.0 * (0.96 ** offset),
                'gov_fund_expenditure_ytd': 115.0 * (0.98 ** offset),
            })
        anchor = annual[-1]
        first = {code: 0.02 for code in (
            'general_budget_revenue_ytd', 'general_budget_expenditure_ytd',
            'gov_fund_revenue_ytd', 'gov_fund_expenditure_ytd')}
        historical = dict(first)
        first_run = simulate_budget_uncertainty(
            annual, anchor, first, historical, simulations=400, seed=7)
        second_run = simulate_budget_uncertainty(
            annual, anchor, first, historical, simulations=400, seed=7)
        self.assertEqual(first_run['records'], second_run['records'])
        self.assertEqual(first_run['data_status'], 'scenario')
        self.assertEqual(first_run['n_growth_vectors'], 6)
        for row in first_run['records']:
            for code in ('general_budget_balance_ytd', 'gov_fund_balance_ytd',
                         'combined_budget_balance_ytd'):
                self.assertLessEqual(row[f'{code}_p10'], row[f'{code}_p50'])
                self.assertLessEqual(row[f'{code}_p50'], row[f'{code}_p90'])

    def test_joint_bootstrap_refuses_too_few_growth_vectors(self):
        annual = [{
            'period': str(year), 'year': year,
            'general_budget_revenue_ytd': 100.0 + year,
            'general_budget_expenditure_ytd': 120.0 + year,
            'gov_fund_revenue_ytd': 50.0 + year,
            'gov_fund_expenditure_ytd': 60.0 + year,
        } for year in range(2022, 2026)]
        rates = {code: 0.02 for code in (
            'general_budget_revenue_ytd', 'general_budget_expenditure_ytd',
            'gov_fund_revenue_ytd', 'gov_fund_expenditure_ytd')}
        result = simulate_budget_uncertainty(
            annual, annual[-1], rates, rates, simulations=400)
        self.assertEqual(result['data_status'], 'insufficient_sample')
        self.assertEqual(result['records'], [])

    def test_current_year_forecast_uses_h1_full_year_seasonality_when_available(self):
        annual = []
        series = []
        for year, share in ((2018, 0.50), (2019, 0.52), (2020, 0.48),
                            (2021, 0.51), (2022, 0.50)):
            values = {
                'general_budget_revenue_ytd': 1000 + (year - 2019) * 50,
                'general_budget_expenditure_ytd': 1200 + (year - 2019) * 60,
                'gov_fund_revenue_ytd': 500 + (year - 2019) * 20,
                'gov_fund_expenditure_ytd': 600 + (year - 2019) * 30,
            }
            annual.append({'period': str(year), 'year': year, **values})
            series.append({'period': f'{year}-06', **{
                code: value * share for code, value in values.items()}})
        current_h1 = {
            'general_budget_revenue_ytd': 700.0,
            'general_budget_expenditure_ytd': 800.0,
            'gov_fund_revenue_ytd': 300.0,
            'gov_fund_expenditure_ytd': 400.0,
        }
        series.append({'period': '2023-06', **current_h1})
        forecast = build_budget_forecast(annual, series, horizon=2)
        self.assertEqual(forecast['current_year_forecast_mode'], 'h1_seasonality')
        baseline = forecast['scenarios']['baseline']['records'][0]
        self.assertAlmostEqual(baseline['general_budget_revenue_ytd'], 1400.0)
        self.assertAlmostEqual(baseline['gov_fund_expenditure_ytd'], 800.0)
        self.assertEqual(forecast['uncertainty']['records'][0]['period'], '2023')
        self.assertEqual(forecast['half_year_analysis']['current']['year'], 2023)


class FiscalLandAnnualSeriesTests(unittest.TestCase):
    def test_land_annual_series_keeps_missing_years_and_computes_shares(self):
        rows = build_land_transfer_annual_series([
            {'period': '2007-12', 'govfund_land_transfer_revenue_ytd': 7285.0,
             'gov_fund_revenue_ytd': 10000.0, 'general_budget_revenue_ytd': 50000.0,
             'govfund_land_transfer_revenue_ytd_yoy_official': 12.5,
             'source_url': 'https://example.test/2007', 'source_title': '2007年财政收支情况'},
            # 2008 is intentionally absent: the table must expose the gap.
            {'period': '2009-12', 'govfund_land_transfer_revenue_ytd': 13964.76,
             'gov_fund_revenue_ytd': 15827.37, 'general_budget_revenue_ytd': 60000.0,
             'source_url': 'https://example.test/2009', 'source_title': '2009年财政收支情况'},
        ])
        self.assertEqual([row['period'] for row in rows], ['2007', '2008', '2009'])
        self.assertEqual(rows[0]['data_status'], 'official')
        self.assertAlmostEqual(rows[0]['land_share_of_fund_pct'], 72.85)
        self.assertIsNone(rows[1]['land_transfer_revenue'])
        self.assertEqual(rows[1]['data_status'], 'missing')
        self.assertIn('未用估算', rows[1]['missing_reason'])
        self.assertAlmostEqual(rows[2]['land_transfer_revenue'], 13964.76)

    def test_land_annual_series_uses_december_only_and_preserves_source(self):
        rows = build_land_transfer_annual_series([
            {'period': '2014-11', 'govfund_land_transfer_revenue_ytd': 30000.0},
            {'period': '2014-12', 'govfund_land_transfer_revenue_ytd': 42940.3,
             'source_url': 'https://example.test/2014', 'source_urls': ['https://example.test/2014']},
        ], start_year=2014)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['source_period'], '2014-12')
        self.assertEqual(rows[0]['source_urls'], ['https://example.test/2014'])
        self.assertEqual(rows[0]['land_transfer_revenue'], 42940.3)

    def test_land_annual_backfill_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / 'fiscal.db')
            first = upsert_land_transfer_annual_backfill(db_path)
            second = upsert_land_transfer_annual_backfill(db_path)
            conn = sqlite3.connect(db_path)
            count = conn.execute(
                "SELECT COUNT(*) FROM fiscal_budget_observations "
                "WHERE indicator_code='govfund_land_transfer_revenue_ytd'"
            ).fetchone()[0]
            row = conn.execute(
                "SELECT value,data_status,source_url FROM fiscal_budget_observations "
                "WHERE indicator_code='govfund_land_transfer_revenue_ytd' AND period='2019-12'"
            ).fetchone()
            conn.close()
            self.assertEqual(first['records_upserted'], len(first['years']))
            self.assertEqual(second['records_upserted'], len(second['years']))
            self.assertEqual(count, len(first['years']))
            self.assertEqual(row[0], 72584.42)
            self.assertEqual(row[1], 'official')
            self.assertTrue(row[2].startswith('https://'))


class FiscalLandHalfYearAnalysisTests(unittest.TestCase):
    def test_half_year_matches_same_year_full_year_and_backtests_without_lookahead(self):
        series = [
            {'period': '2014-06', 'govfund_land_transfer_revenue_ytd': 50.0,
             'source_url': 'https://example.test/2014-06'},
            {'period': '2014-12', 'govfund_land_transfer_revenue_ytd': 100.0,
             'source_url': 'https://example.test/2014-12'},
            {'period': '2015-06', 'govfund_land_transfer_revenue_ytd': 60.0},
            {'period': '2015-12', 'govfund_land_transfer_revenue_ytd': 120.0},
            {'period': '2016-06', 'govfund_land_transfer_revenue_ytd': 70.0},
            {'period': '2016-12', 'govfund_land_transfer_revenue_ytd': 140.0},
            {'period': '2017-06', 'govfund_land_transfer_revenue_ytd': 80.0},
            {'period': '2017-12', 'govfund_land_transfer_revenue_ytd': 200.0},
            {'period': '2018-06', 'govfund_land_transfer_revenue_ytd': 90.0,
             'govfund_land_transfer_revenue_ytd_yoy_official': 12.5,
             'source_url': 'https://example.test/2018-06'},
            # A December-only year is retained but cannot enter the H1 share sample.
            {'period': '2019-12', 'govfund_land_transfer_revenue_ytd': 210.0},
        ]
        result = build_land_transfer_half_year_analysis(series, start_year=2014)
        by_year = {row['year']: row for row in result['rows']}
        self.assertEqual(result['n_obs'], 4)
        self.assertEqual(by_year[2014]['analysis_status'], 'matched')
        self.assertAlmostEqual(by_year[2014]['h1_share_of_full_year_pct'], 50.0)
        self.assertEqual(by_year[2019]['analysis_status'], 'full_year_only')
        # 2017 uses only 2014-2016's 50% median, so the 2017 estimate is 160,
        # not a value calibrated with 2017/2018 future observations.
        self.assertEqual(by_year[2017]['full_year_estimate_by_prior_median'], 160.0)
        self.assertAlmostEqual(by_year[2017]['estimate_error_pct'], -20.0)
        self.assertEqual(result['current']['year'], 2018)
        self.assertEqual(result['current']['half_year_yoy_official'], 12.5)
        self.assertEqual(result['current']['implied_full_year_median'], 180.0)
        self.assertEqual(result['predictive_power']['directional_n'], 3)
        self.assertEqual(result['predictive_power']['directional_same_pct'], 100.0)
        self.assertEqual(result['predictive_power']['backtest']['n_obs'], 1)
        self.assertEqual(result['predictive_power']['backtest']['error_unit'],
                         'relative_pct_of_actual_full_year')
        self.assertAlmostEqual(result['predictive_power']['backtest']['mae_relative_pct'], 20.0)

    def test_half_year_analysis_is_explicitly_insufficient_when_no_matched_pair(self):
        result = build_land_transfer_half_year_analysis([
            {'period': '2026-06', 'govfund_land_transfer_revenue_ytd': 9778.0,
             'govfund_land_transfer_revenue_ytd_yoy_official': -31.5,
             'source_url': 'https://example.test/2026-06'},
        ], start_year=2026)
        self.assertEqual(result['n_obs'], 0)
        self.assertEqual(result['current']['half_year_revenue'], 9778.0)
        self.assertIsNone(result['current']['implied_full_year_median'])
        self.assertEqual(result['predictive_power']['data_status'], 'insufficient_sample')


class FiscalBudgetPageContractTests(unittest.TestCase):
    def test_page_exposes_account_and_scenario_switches(self):
        page = (Path(__file__).resolve().parents[1] / 'static' / 'fiscal_debt.html').read_text(
            encoding='utf-8')
        for text in ('财政收入与支出', '一般公共预算', '政府性基金', '两本账简单相加',
                     "useState('baseline')", 'forecast?.scenarios', '年度财政收支',
                     '财政月度实际流量', '由YTD相邻差分', '最可能（基准）',
                     '历史波动模拟区间', 'P10较差', 'P50中位', 'P90较好'):
            self.assertIn(text, page)
        self.assertIn('全国土地出让收入年度历史', page)
        self.assertIn('上半年土地出让收入与全年回测', page)
        self.assertIn('halfYear.cards', page)
        self.assertIn('本年上半年累计→全年推演', page)
        self.assertIn('half_year_analysis', page)


if __name__ == '__main__':
    unittest.main()
