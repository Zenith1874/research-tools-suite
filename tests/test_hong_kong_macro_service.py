# -*- coding: utf-8 -*-
"""香港宏观纯解析、口径和 lead-lag 契约测试。"""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.china_external_service import (
    parse_safe_reserve_html,
    upsert_external_observations,
)
from services.china_macro_service import ensure_china_macro_tables
from services.hong_kong_macro_service import (
    CSD_CURATED_MAPPINGS,
    CSD_WEB_TABLES,
    DEPRECATED_CSD_CURATED_MAPPINGS,
    HKMA_QUARTER_END_INDICATORS,
    INDICATORS,
    TRADE_DIMENSION_REQUESTS,
    build_lead_lag_payload,
    build_hong_kong_macro_debug,
    build_hong_kong_macro_payload,
    build_hong_kong_macro_csv,
    build_hong_kong_macro_csd_web_table_payload,
    build_hong_kong_macro_csd_web_table_csv,
    build_hong_kong_macro_trade_dimensions_payload,
    build_saved_lead_lag_payload,
    compute_lead_lag,
    ensure_hong_kong_macro_tables,
    migrate_hkma_period_frequency_rows,
    migrate_safe_reserve_release_metadata,
    normalize_hkma_period,
    parse_csd_ctt_payload,
    parse_csd_web_table_payload,
    derive_trade_rows,
    parse_hkma_records,
    parse_landreg_primary_rows,
    parse_rvd_index_matrix,
    parse_rvd_private_annual_matrix,
    parse_rvd_sales_matrix,
    parse_trade_idds_payload,
    parse_trade_dimension_payload,
    persist_lead_lag_payload,
    reingest_rvd_private_annual_from_raw,
    _period_bounds,
    _identity_check,
    _transform_rows,
    upsert_csd_web_table_rows,
    _trade_dimension_code_chunks,
    upsert_trade_dimensions,
    upsert_hong_kong_observations,
)


class HongKongParserTests(unittest.TestCase):
    def test_sitc2_top_n_uses_complete_code_universe(self):
        request = TRADE_DIMENSION_REQUESTS['top_sitc2_exports']
        chunks = _trade_dimension_code_chunks(request)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(sum(len(chunk) for chunk in chunks), 68)
        self.assertEqual(chunks[0][0], '00')
        self.assertEqual(chunks[-1][-1], '98')
        self.assertEqual(len({code for chunk in chunks for code in chunk}), 68)
        self.assertNotIn('10', {code for chunk in chunks for code in chunk})
        self.assertNotIn('99', {code for chunk in chunks for code in chunk})
        self.assertEqual(TRADE_DIMENSION_REQUESTS['top_origins']['params']['co'], 'ALL')
        self.assertEqual(TRADE_DIMENSION_REQUESTS['top_destinations']['params']['cc'], 'ALL')
        self.assertEqual(TRADE_DIMENSION_REQUESTS['top_origins']['dimension_type'], 'origin_top')
        self.assertEqual(TRADE_DIMENSION_REQUESTS['top_destinations']['dimension_type'], 'destination_top')

    def test_rvd_index_and_sales_keep_official_months(self):
        index_matrix = [
            ['', '', '', '', '', '', '', 'All Classes'],
            ['', '2026', '', '', '', '6', '', '323.2*'],
            ['', '2026', '', '', '', '7', '', '', ''],
        ]
        rows = parse_rvd_index_matrix(index_matrix, 'HK_RVD_PRICE_INDEX',
                                      'HK_RVD_PRICE_INDEX', 'https://example/price.xls')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['period'], '2026-06')
        self.assertEqual(rows[0]['data_status'], 'official_revised')

        header = [''] * 20
        header[1], header[5], header[8], header[12], header[15], header[19] = (
            'Year', 'Month', 'No.', 'Consideration ($ million)', 'No.', 'Consideration ($ million)')
        sales = [header, [''] * 20]
        sales[1][1], sales[1][5] = 2026, 6
        sales[1][8], sales[1][12], sales[1][15], sales[1][19] = 10, 100.5, 20, 200.5
        parsed = parse_rvd_sales_matrix(sales, 'HK_RVD_DOMESTIC_SALES', 'https://example/sales.xls')
        values = {row['indicator_code']: row['value'] for row in parsed}
        self.assertEqual(values['HK_RVD_TOTAL_SALES_COUNT'], 30)
        self.assertEqual(values['HK_RVD_TOTAL_SALES_VALUE'], 301.0)

    def test_rvd_index_frequency_split_preserves_low_frequency_history(self):
        matrix = [
            ['', 'Year', '/', 'Month', '', '', '', '', 'All Classes'],
            ['', '', '', '', '', '', '', '', ''],
            ['', 1979, '', 10, '', 12, '', '', 17.5],
            ['', 1980, '', 1, '', 3, '', '', 18.4],
        ]
        quarterly = parse_rvd_index_matrix(matrix, 'HK_RVD_PRICE_INDEX_QUARTERLY',
                                            'HK_RVD_PRICE_INDEX', 'https://example',
                                            frequency='quarterly')
        self.assertEqual([row['period'] for row in quarterly], ['1979-Q4', '1980-Q1'])
        self.assertTrue(all(row['frequency'] == 'quarterly' for row in quarterly))

    def test_rvd_vacancy_units_and_rate_are_separate(self):
        matrix = [['', '', 'Year', '', 'Total'], ['', '', 2025, '', 56081, 0.043]]
        units = parse_rvd_private_annual_matrix(matrix, 'HK_RVD_VACANCY_UNITS',
                                                'HK_RVD_PRIVATE_STOCK_FLOW', 'https://example', 'vacancy_units')
        rate = parse_rvd_private_annual_matrix(matrix, 'HK_RVD_VACANCY_RATE',
                                               'HK_RVD_PRIVATE_STOCK_FLOW', 'https://example', 'rate')
        self.assertEqual(units[0]['value'], 56081)
        self.assertAlmostEqual(rate[0]['value'], 4.3)

    def test_rvd_annual_parser_skips_footnotes_and_uses_canonical_year(self):
        matrix = [
            ['', 'Completions', 'Year', 'Total'],
            ['', 'official', 2025, 18448],
            ['', 'Note: since 2003 the series definition changed', '', 2003],
        ]
        rows = parse_rvd_private_annual_matrix(
            matrix, 'HK_RVD_COMPLETIONS', 'HK_RVD_PRIVATE_STOCK_FLOW',
            'https://example', 'units')
        self.assertEqual([row['period'] for row in rows], ['2025'])
        self.assertEqual(rows[0]['value'], 18448)

    def test_csd_ctt_annual_parser_uses_y_frequency_period(self):
        rows = parse_csd_ctt_payload(
            {'MDT': [{'TV01': 2025, 'SV01': 123.4}]},
            'HK_CSD_CTT_6', ['HK_CSD_GDP_REAL_ANNUAL'])
        self.assertEqual(rows[0]['period'], '2025')

    def test_cross_frequency_transform_uses_calendar_step(self):
        quarterly = [
            {'indicator_code': 'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT', 'frequency': 'quarterly', 'period': '2024-Q1', 'value': 100},
            {'indicator_code': 'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT', 'frequency': 'quarterly', 'period': '2024-Q2', 'value': 110},
            {'indicator_code': 'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT', 'frequency': 'quarterly', 'period': '2025-Q1', 'value': 120},
        ]
        result = _transform_rows(quarterly, 'qoq')
        self.assertEqual(result[0]['value'], None)
        self.assertAlmostEqual(result[1]['value'], 10.0)
        self.assertEqual(result[2]['value'], None)
        annual = [
            {'indicator_code': 'HK_RVD_COMPLETIONS', 'frequency': 'annual', 'period': '2023', 'value': 100},
            {'indicator_code': 'HK_RVD_COMPLETIONS', 'frequency': 'annual', 'period': '2024', 'value': 120},
        ]
        annual_result = _transform_rows(annual, 'difference')
        self.assertEqual([row['value'] for row in annual_result], [None, 20])
        self.assertEqual(_period_bounds('2024-Q2', 'quarterly'),
                         {'period_start': '2024-04', 'period_end': '2024-06'})

    def test_official_json_and_api_parsers(self):
        land = parse_landreg_primary_rows([{
            'Year': 2026, 'Month': 6,
            'Number of Primary Sales for ASP Residential Building Units': 10,
            'Number of Secondary Sales for ASP Residential Building Units': 20,
            'Number of ASP for Residential Building Units': 30,
            'Consideration of Primary Sales for ASP Residential Building Units': 100.5,
            'Consideration of Secondary Sales for ASP Residential Building Units': 200.5,
            'Consideration of ASP for Residential Building Units': 301.0,
        }])
        self.assertEqual({row['period'] for row in land}, {'2026-06'})
        land_values = {row['indicator_code']: row['value'] for row in land
                       if row['indicator_code'].endswith('_VALUE')}
        self.assertEqual(land_values['HK_LR_TOTAL_SALES_VALUE'], 301.0)

        hkma = parse_hkma_records([{
            'end_of_month': '2026-06', 'fc_resv_assets_total': 445923,
            'fc_resv_assets_ef': 400000, 'fc_resv_assets_lf': 45923,
            'unsettle_fx_contracts_total': -300,
        }], 'HK_HKMA_FC_RESERVE_ASSETS')
        self.assertEqual(next(row['value'] for row in hkma
                              if row['indicator_code'] == 'HK_HKMA_FC_RESERVE_ASSETS_TOTAL'), 445923)
        self.assertEqual(next(row['value'] for row in hkma
                              if row['indicator_code'] == 'HK_HKMA_UNSETTLED_FX_CONTRACTS_TOTAL'), -300)

        monetary = parse_hkma_records([{
            'end_of_month': '2026-06', 'hibor_fixing_3m': 2.9,
            'aggr_balance': 53981, 'exrate_hkd_usd': 7.844,
            'nominal_eff_exrate_index': 101.9,
        }], 'HK_HKMA_MONETARY')
        monetary_values = {row['indicator_code']: row['value'] for row in monetary}
        self.assertEqual(monetary_values['HK_HKMA_HIBOR_3M'], 2.9)
        self.assertEqual(monetary_values['HK_HKMA_AGGREGATE_BALANCE'], 53981)
        self.assertEqual(monetary_values['HK_HKMA_EXRATE_HKD_USD'], 7.844)

        banking = parse_hkma_records([{
            'end_of_month': '2026-06', 'no_of_ais': 174,
            'total_assets': 33140031.688, 'cust_deposites_hkd': 8567402.859,
            'cust_deposits_fc': 11813615.909, 'cust_deposits_total': 20381018.768,
            'loans_total': 10787902.403, 'deli_ratio_resid_mort_lend': 0.11,
        }], 'HK_HKMA_BANKING_STATS')
        banking_values = {row['indicator_code']: row['value'] for row in banking}
        self.assertEqual(banking_values['HK_HKMA_BANKING_NO_AIS'], 174)
        self.assertAlmostEqual(banking_values['HK_HKMA_BANKING_CUSTOMER_DEPOSITS_TOTAL'], 20381018.768)
        self.assertAlmostEqual(banking_values['HK_HKMA_BANKING_MORTGAGE_DELINQUENCY_RATIO'], 0.11)

        deposits = parse_hkma_records([{
            'end_of_month': '2026-06', 'lb_demand_total': 2835494.193,
            'lb_savings_total': 5996986.638, 'lb_time_total': 11520187.009,
            'lb_total': 20352667.84, 'all_ais_total': 20381018.768,
        }], 'HK_HKMA_CUSTOMER_DEPOSITS')
        self.assertEqual({row['indicator_code'] for row in deposits}, {
            'HK_HKMA_DEPOSITS_LB_DEMAND_TOTAL', 'HK_HKMA_DEPOSITS_LB_SAVINGS_TOTAL',
            'HK_HKMA_DEPOSITS_LB_TIME_TOTAL', 'HK_HKMA_DEPOSITS_LB_TOTAL',
            'HK_HKMA_DEPOSITS_ALL_AIS_TOTAL'})

        rmb = parse_hkma_records([{
            'end_of_month': '2026-06', 'demand_savings_deposits': 505830.306,
            'time_deposits': 587692.352, 'total_deposits': 1093522.658,
            'no_of_ais_engaged': 141,
        }], 'HK_HKMA_RMB_DEPOSITS')
        rmb_values = {row['indicator_code']: row['value'] for row in rmb}
        self.assertEqual(rmb_values['HK_HKMA_RMB_DEPOSITS_AIS_COUNT'], 141)
        self.assertAlmostEqual(rmb_values['HK_HKMA_RMB_DEPOSITS_TOTAL'], 1093522.658)

        loans = parse_hkma_records([{
            'end_of_month': '2026-06', 'imp_exp_reexp_fromhk_total': 261708.339,
            'merch_trade_nonhk_total': 173272.034, 'loans_inhk_total': 7627734.232,
            'other_loans_outhk_total': 2647500.899,
            'other_loans_unkplace_total': 31.342, 'total_loans': 10710246.846,
        }], 'HK_HKMA_LOANS_BY_TYPE')
        loans_values = {row['indicator_code']: row['value'] for row in loans}
        self.assertAlmostEqual(loans_values['HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_TOTAL'], 261708.339)
        self.assertAlmostEqual(loans_values['HK_HKMA_LOANS_TOTAL_BY_TYPE'], 10710246.846)

        mortgage = parse_hkma_records([{
            'end_of_month': '2026-06', 'outstanding_loans_amt': 1870600,
            'delinquency_ratio': 0.11, 'new_loans_app_received': 6306,
            'new_loans_approved_amt': 25500, 'new_loans_approved': 1000,
            'new_loans_approved_lv_ratio': 60.5,
            'ir_new_loans_approved_hibor': 91.3,
        }], 'HK_HKMA_MORTGAGE_SURVEY')
        mortgage_values = {row['indicator_code']: row['value'] for row in mortgage}
        self.assertEqual(mortgage_values['HK_HKMA_MORTGAGE_NEW_APPLICATIONS'], 6306)
        self.assertAlmostEqual(mortgage_values['HK_HKMA_MORTGAGE_NEW_APPROVED_LTV'], 60.5)
        self.assertEqual(mortgage_values['HK_HKMA_MORTGAGE_RATE_HIBOR'], 91.3)

        negative_equity = parse_hkma_records([{
            'end_of_quarter': '2026-Q2', 'outstanding_loans': 11123,
            'outstanding_loans_ratio': 0.5, 'outstanding_loans_amt': 59300,
            'outstanding_loans_amt_ratio': 0.3, 'unsecured_portion_amt': 2000,
            'lv_ratio': 120.0,
        }], 'HK_HKMA_NEGATIVE_EQUITY')
        negative_values = {row['indicator_code']: row['value'] for row in negative_equity}
        self.assertEqual(negative_equity[0]['period'], '2026-Q2')
        self.assertEqual(negative_values['HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT'], 11123)
        self.assertAlmostEqual(negative_values['HK_HKMA_NEGATIVE_EQUITY_LTV'], 120.0)

        trade = parse_trade_idds_payload({'dataSet': [
            {'period': '202606', 'ttype': 3, 'figure': '123456', 'unit': "$'000"},
            {'period': '202606', 'ttype': 1, 'figure': '--', 'unit': "$'000"},
        ]})
        self.assertEqual(len(trade), 1)
        self.assertEqual(trade[0]['indicator_code'], 'HK_TRADE_RE_EXPORTS')

        origin = parse_trade_dimension_payload({'dataSet': [{
            'period': '202606', 'ttype': 1, 'co': 'CN',
            'coDescEN': 'CHINESE MAINLAND', 'figure': '237634807',
            'unitEN': "HK$ '000", 'sv': 'VCm'}]}, 'mainland_origin')
        self.assertEqual(origin[0]['dimension_type'], 'origin')
        self.assertEqual(origin[0]['dimension_code'], 'CN')
        self.assertEqual(origin[0]['statistic'], 'value_monthly')

        commodity = parse_trade_dimension_payload({'dataSet': [{
            'period': '202606', 'ttype': 4, 'code': '77',
            'codeDescEN': 'MACHINERY', 'figure': '1000',
            'unitEN': "HK$ '000", 'sv': 'VCm'}]}, 'top_sitc2_exports')
        self.assertEqual(commodity[0]['dimension_type'], 'commodity_sitc2')
        self.assertEqual(commodity[0]['dimension_label'], 'MACHINERY')

        csd = parse_csd_ctt_payload({'MDT': [{'TV01': 2025, 'SV01': 108.9, 'SV02': 3301474,
                                              'SV03': 15.4, 'SV04': 3.7}]},
                                     'HK_CSD_CTT_6', [
                                         'HK_CSD_COMPOSITE_CPI_INDEX', 'HK_CSD_GDP_REAL_ANNUAL',
                                         'HK_CSD_TOTAL_EXPORTS_YOY_ANNUAL', 'HK_CSD_UNEMPLOYMENT_RATE_ANNUAL'])
        self.assertEqual(len(csd), 4)
        self.assertEqual(csd[1]['value'], 3301474)
        self.assertEqual(csd[2]['value'], 15.4)
        self.assertEqual(csd[3]['value'], 3.7)

        csd_web = parse_csd_web_table_payload({'dataset': [{
            'period': '2026-06', 'series_code': 'retail_total',
            'series_label': 'Total retail sales', 'value': '100.5',
            'unit': 'HK$ million'}]}, '620-67001')
        self.assertEqual(csd_web[0]['period'], '2026-06')
        self.assertEqual(csd_web[0]['series_code'], 'retail_total')
        self.assertEqual(csd_web[0]['value'], 100.5)

        csd_live_shape = parse_csd_web_table_payload({'dataSet': [{
            'REGION': 'CN', 'REGIONDesc': 'Chinese Mainland', 'freq': 'M',
            'period': '202606', 'sv': 'VIS_ARR', 'svDesc': 'Number',
            'figure': 1234, 'sd_value': ''}]}, '650-80001')
        self.assertEqual(csd_live_shape[0]['period'], '2026-06')
        self.assertEqual(csd_live_shape[0]['series_code'],
                         'REGION=CN|freq=M|sv=VIS_ARR|stat=Number')
        self.assertIn('Chinese Mainland', csd_live_shape[0]['series_label'])
        self.assertEqual(csd_live_shape[0]['frequency'], 'monthly')

        csd_mixed_frequency = parse_csd_web_table_payload({'dataSet': [
            {'freq': 'M', 'period': '202606', 'sv': 'VAL',
             'svDesc': 'HK$ million', 'figure': 10},
            {'freq': 'M', 'period': '202606', 'sv': 'VAL',
             'svDesc': 'Year-on-year % change', 'figure': 2},
            {'freq': 'Y', 'period': '2026', 'sv': 'VAL',
             'svDesc': 'HK$ million', 'figure': 120},
        ]}, '620-67001')
        self.assertEqual(len({(row['period'], row['series_code'])
                              for row in csd_mixed_frequency}), 3)
        self.assertEqual({row['period'] for row in csd_mixed_frequency},
                         {'2026-06', '2026'})
        yoy = next(row for row in csd_mixed_frequency if row['period'] == '2026-06'
                   and row['unit'] == '%')
        self.assertEqual(yoy['statistic'], 'yoy')
        self.assertEqual(yoy['unit'], '%')

        csd_half_year = parse_csd_web_table_payload({'dataSet': [{
            'freq': 'H', 'period': '200006', 'sv': 'PG', 'svDesc': "('000)",
            'figure': 6.8,
        }]}, '110-01003')
        self.assertEqual(csd_half_year[0]['period'], '2000-H1')
        self.assertEqual(csd_half_year[0]['frequency'], 'semiannual')
        self.assertEqual(csd_half_year[0]['unit'], "('000)")
        self.assertIn('Population growth', csd_half_year[0]['series_label'])
        self.assertNotIn('Population stock', csd_half_year[0]['series_label'])

        csd_unknown = parse_csd_web_table_payload({'dataSet': [{
            'freq': 'Z', 'period': '202506', 'sv': 'X', 'svDesc': 'Unknown field',
            'figure': 1,
        }]}, '620-67001')
        self.assertEqual(csd_unknown[0]['frequency'], 'unknown')
        self.assertEqual(csd_unknown[0]['data_status'], 'metadata_unknown')
        self.assertNotEqual(csd_unknown[0]['period'], '2025')

        trade_rows = parse_trade_idds_payload({'dataSet': [
            {'period': '202606', 'ttype': 1, 'figure': '100', 'unitEN': "HK$ '000"},
            {'period': '202606', 'ttype': 3, 'figure': '60', 'unitEN': "HK$ '000"},
            {'period': '202606', 'ttype': 4, 'figure': '80', 'unitEN': "HK$ '000"},
        ]})
        derived = derive_trade_rows(trade_rows)
        derived_values = {row['indicator_code']: row['value'] for row in derived}
        self.assertEqual(derived_values['HK_TRADE_BALANCE'], -20)
        self.assertEqual(derived_values['HK_TRADE_RE_EXPORT_SHARE'], 75)

    def test_safe_official_reserve_assets_do_not_use_sdr_conversion(self):
        html = '''<table>
          <tr><td>Item</td><td>Jan</td><td>SDR</td><td>Feb</td><td>SDR</td></tr>
          <tr><td>Foreign currency reserves</td><td x:num="100">100</td><td x:num="70">70</td><td x:num="101">101</td><td x:num="71">71</td></tr>
          <tr><td>IMF reserve position</td><td x:num="2">2</td><td x:num="1">1</td><td x:num="2.1">2.1</td><td x:num="1.1">1.1</td></tr>
          <tr><td>SDRs</td><td x:num="3">3</td><td x:num="2">2</td><td x:num="3.1">3.1</td><td x:num="2.1">2.1</td></tr>
          <tr><td>Gold</td><td x:num="4">4</td><td x:num="3">3</td><td x:num="4.1">4.1</td><td x:num="3.1">3.1</td></tr>
          <tr><td>Gold quantity (10,000 fine troy ounces)</td><td x:num="720">720</td><td></td><td x:num="721">721</td><td></td></tr>
          <tr><td>Other reserve assets</td><td x:num="5">5</td><td x:num="4">4</td><td x:num="5.1">5.1</td><td x:num="4.1">4.1</td></tr>
          <tr><td>Total</td><td x:num="114">114</td><td x:num="80">80</td><td x:num="116.4">116.4</td><td x:num="82.4">82.4</td></tr>
        </table>'''
        rows = parse_safe_reserve_html(html, 'https://www.safe.gov.cn/safe/2026/0206/27116.html', '2026 官方储备资产')
        values = {(row['indicator_code'], row['period']): row['value'] for row in rows}
        self.assertEqual(values[('CN_SAFE_FX_RESERVES_USD', '2026-01')], 100)
        self.assertEqual(values[('CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD', '2026-02')], 116.4)
        self.assertEqual(values[('CN_SAFE_MONETARY_GOLD_QUANTITY', '2026-01')], 720)
        self.assertNotEqual(values[('CN_SAFE_FX_RESERVES_USD', '2026-01')], 70)

        unlabeled_quantity = '''<table>
          <tr><td>Item</td><td>Jan</td><td>SDR</td><td>Feb</td><td>SDR</td></tr>
          <tr><td>Foreign currency reserves</td><td x:num="100">100</td><td>70</td><td x:num="101">101</td><td>71</td></tr>
          <tr><td>Gold</td><td x:num="4">4</td><td>3</td><td x:num="4.1">4.1</td><td>3.1</td></tr>
          <tr><td></td><td x:num="720">720</td><td>万盎司</td><td x:num="721">721</td><td>万盎司</td></tr>
          <tr><td>Total</td><td x:num="104">104</td><td>80</td><td x:num="105">105</td><td>82</td></tr>
        </table>'''
        unlabeled = parse_safe_reserve_html(unlabeled_quantity, 'https://example/2026/0206/27116.html', '2026')
        self.assertEqual({row['period'] for row in unlabeled
                          if row['indicator_code'] == 'CN_SAFE_MONETARY_GOLD_QUANTITY'},
                         {'2026-01', '2026-02'})

        unlabeled_without_unit = unlabeled_quantity.replace('万盎司', '')
        without_unit = parse_safe_reserve_html(unlabeled_without_unit, 'https://example/2026/0206/27116.html', '2026')
        self.assertFalse(any(row['indicator_code'] == 'CN_SAFE_MONETARY_GOLD_QUANTITY'
                             for row in without_unit))

        months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul')
        header = '<tr><td>Item</td>' + ''.join(
            f'<td>{month}</td><td>SDR</td>' for month in months) + '</tr>'
        def safe_row(label, values, unit=''):
            cells = ''.join(f'<td x:num="{value}">{value}</td><td>{unit}</td>'
                            for value in values)
            return f'<tr><td>{label}</td>{cells}</tr>'
        real_shape = '<table>' + header + safe_row(
            'Foreign currency reserves', [3000 + i for i in range(7)], '70') + safe_row(
            'Gold', [2800, 2850, 2900, 2950, 3000, 3050, 3063.54], '3') + safe_row(
            '', [7419, 7422, 7438, 7464, 7496, 7544, 7608], '万盎司') + safe_row(
            'Total', [10000 + i for i in range(7)], '80') + '</table>'
        real_rows = parse_safe_reserve_html(
            real_shape, 'https://www.safe.gov.cn/safe/2026/0206/27116.html', '2026')
        real_values = {(row['indicator_code'], row['period']): row['value']
                       for row in real_rows}
        self.assertEqual(real_values[('CN_SAFE_MONETARY_GOLD_QUANTITY', '2026-01')], 7419)
        self.assertEqual(real_values[('CN_SAFE_MONETARY_GOLD_QUANTITY', '2026-07')], 7608)
        self.assertEqual(real_values[('CN_SAFE_MONETARY_GOLD_USD', '2026-07')], 3063.54)

        # A continuously updated annual page has a path/creation date, not a
        # per-month release date.  The parser must keep those fields distinct.
        july = next(row for row in real_rows
                    if row['indicator_code'] == 'CN_SAFE_FX_RESERVES_USD'
                    and row['period'] == '2026-07')
        self.assertIsNone(july['release_date'])
        self.assertEqual(july['source_page_created_date'], '2026-02-06')
        self.assertTrue(july['release_date_not_provided'])
        self.assertEqual(july['source_page_last_updated_date'], None)
        self.assertIn('not expose', july['release_date_reason'])

    def test_csd_population_growth_is_not_population_stock(self):
        self.assertEqual(CSD_WEB_TABLES['110-01003']['title'],
                         'Population growth by component')
        mapping = CSD_CURATED_MAPPINGS['HK_CSD_WEB_POPULATION_GROWTH_SEMIANNUAL']
        self.assertIn('增长', mapping['name'])
        self.assertIn('不是人口存量', mapping['note'])
        self.assertIn('HK_CSD_WEB_POPULATION_SEMIANNUAL', DEPRECATED_CSD_CURATED_MAPPINGS)
        payload = {'dataSet': [{
            'freq': 'H', 'period': '202512', 'sv': 'PG',
            'svDesc': "('000)", 'figure': 10.2, 'sd_value': 'p',
        }]}
        rows = parse_csd_web_table_payload(payload, '110-01003')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['period'], '2025-H2')
        self.assertEqual(rows[0]['frequency'], 'semiannual')
        self.assertEqual(rows[0]['unit'], "('000)")
        self.assertEqual(rows[0]['data_status'], 'provisional')
        self.assertEqual(rows[0]['construct_label'], 'Population growth')
        self.assertIn('Population growth', rows[0]['series_label'])
        self.assertNotIn('population stock', rows[0]['series_label'].lower())

    def test_hkma_period_normalization_rejects_non_quarter_and_annual_sentinel(self):
        self.assertEqual(normalize_hkma_period('HK_HKMA_NOMINAL_GDP', '2025-06'), '2025-Q2')
        self.assertEqual(normalize_hkma_period('HK_HKMA_REAL_GDP', '2025-12'), '2025-Q4')
        self.assertEqual(normalize_hkma_period('HK_HKMA_CURRENT_ACCOUNT_BALANCE', '2026-03'), '2026-Q1')
        self.assertIsNone(normalize_hkma_period('HK_HKMA_NOMINAL_GDP', '2025-05'))
        self.assertIsNone(normalize_hkma_period('HK_HKMA_NOMINAL_GDP', '2025-00'))
        self.assertEqual(normalize_hkma_period('HK_HKMA_GOV_CONSOLIDATED_BALANCE', '2025-05'), '2025-05')
        parsed = parse_hkma_records([
            {'end_of_month': '2025-06', 'nominal_gdp': 100, 'gov_consol_bal': -5},
            {'end_of_month': '2025-05', 'nominal_gdp': 99, 'gov_consol_bal': -4},
            {'end_of_month': '2025-00', 'nominal_gdp': 999, 'gov_consol_bal': -99},
        ], 'HK_HKMA_ECONOMIC')
        by_code = {(row['indicator_code'], row['period']): row['value'] for row in parsed}
        self.assertEqual(by_code[('HK_HKMA_NOMINAL_GDP', '2025-Q2')], 100)
        self.assertNotIn(('HK_HKMA_NOMINAL_GDP', '2025-05'), by_code)
        self.assertEqual(by_code[('HK_HKMA_GOV_CONSOLIDATED_BALANCE', '2025-05')], -4)
        self.assertNotIn(('HK_HKMA_GOV_CONSOLIDATED_BALANCE', '2025-00'), by_code)

    def test_rvd_partial_year_is_semiannual_provisional_not_annual(self):
        matrix = [
            ['', 'Completions', 'Year', 'Total'],
            ['', '# Provisional figures (up to 30.06.2026).', '', ''],
            ['', 'official', 2025, 18448],
            ['', 'provisional', 2026, 7914],
        ]
        rows = parse_rvd_private_annual_matrix(
            matrix, 'HK_RVD_COMPLETIONS', 'HK_RVD_PRIVATE_STOCK_FLOW',
            'https://example/private_domestic.xls', 'units')
        annual = [row for row in rows if row['indicator_code'] == 'HK_RVD_COMPLETIONS']
        partial = [row for row in rows if row['indicator_code'] == 'HK_RVD_COMPLETIONS_YTD']
        self.assertEqual([(row['period'], row['value']) for row in annual], [('2025', 18448)])
        self.assertEqual(len(partial), 1)
        self.assertEqual(partial[0]['period'], '2026-H1')
        self.assertEqual(partial[0]['frequency'], 'semiannual')
        self.assertEqual(partial[0]['value'], 7914)
        self.assertEqual(partial[0]['data_status'], 'provisional')
        self.assertEqual(partial[0]['source_period_end'], '2026-06-30')
        self.assertIn('Not a full-year annual value', partial[0]['note'])

    def test_server_page_and_route_contracts(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / 'static' / 'hong_kong_macro.html').read_text(encoding='utf-8')
        server = (root / 'server.py').read_text(encoding='utf-8')
        nav = (root / 'static' / 'research-nav.js').read_text(encoding='utf-8')
        for fragment in ('/api/hong-kong-macro/data', '/api/hong-kong-macro/update',
                         '/api/hong-kong-macro/debug', '/api/hong-kong-macro/lead-lag',
                         '/api/hong-kong-macro/export.csv', '/api/hong-kong-macro/trade-dimensions.csv',
                         '/api/hong-kong-macro/trade-dimensions', 'reserves_finance',
                         'china_linkage', 'corr_at_lag(k)', 'CSD Web Table 细表',
                         '/api/hong-kong-macro/csd-web-table', 'CSD 细表',
                         'CN_NATIONAL_SALES_AREA_YTD_YOY',
                         'CN_NATIONAL_SALES_AREA_MONTHLY_DERIVED', 'def.warning'):
            self.assertIn(fragment, page)
        for fragment in ('/api/hong-kong-macro/data', '/api/hong-kong-macro/update',
                         '/api/hong-kong-macro/retry-hkma',
                         '/api/hong-kong-macro/debug', '/api/hong-kong-macro/lead-lag',
                         '/api/hong-kong-macro/lead-lag/save',
                         '/api/hong-kong-macro/lead-lag/saved',
                         '/api/hong-kong-macro/csd-web-table',
                         '/api/hong-kong-macro/export.csv', '/api/hong-kong-macro/trade-dimensions.csv',
                         '/api/hong-kong-macro/trade-dimensions', '/hong-kong-macro'):
            self.assertIn(fragment, server)
        self.assertIn("href: '/hong-kong-macro'", nav)
        self.assertIn("data/hong_kong_macro_raw/", (root / '.gitignore').read_text(encoding='utf-8'))


class HongKongPersistenceAndLeadLagTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        ensure_hong_kong_macro_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def test_schema_upsert_is_idempotent_and_debuggable(self):
        row = {'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
               'period': '2026-06', 'frequency': 'monthly', 'value': 323.2,
               'unit': 'index', 'data_status': 'official', 'source_id': 'HK_RVD_PRICE_INDEX',
               'source_url': 'https://example'}
        upsert_hong_kong_observations(self.conn, [row])
        upsert_hong_kong_observations(self.conn, [row])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM hong_kong_macro_observations').fetchone()[0], 1)
        debug = build_hong_kong_macro_debug(self.path)
        self.assertEqual(debug['database_quick_check'], 'ok')
        self.assertEqual(debug['superseded_observation_count'], 0)
        self.assertEqual(debug['raw_root'], 'data/hong_kong_macro_raw/')
        tables = {row[0] for row in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('hong_kong_macro_trade_dimensions', tables)
        self.assertIn('hong_kong_macro_web_table_observations', tables)

    def test_hkma_period_migration_is_idempotent_and_has_no_active_duplicates(self):
        rows = [
            {'indicator_code': 'HK_HKMA_NOMINAL_GDP', 'category': 'economy',
             'period': '2025-06', 'frequency': 'quarterly', 'value': 100,
             'unit': 'HK$ million', 'data_status': 'official',
             'source_id': 'HK_HKMA_ECONOMIC', 'source_url': 'https://example'},
            {'indicator_code': 'HK_HKMA_GOV_CONSOLIDATED_BALANCE', 'category': 'reserves_finance',
             'period': '2025-05', 'frequency': 'quarterly', 'value': -5,
             'unit': 'HK$ million', 'data_status': 'official',
             'source_id': 'HK_HKMA_ECONOMIC', 'source_url': 'https://example'},
            {'indicator_code': 'HK_HKMA_REAL_GDP', 'category': 'economy',
             'period': '2025-00', 'frequency': 'quarterly', 'value': 99,
             'unit': 'HK$ million', 'data_status': 'official',
             'source_id': 'HK_HKMA_ECONOMIC', 'source_url': 'https://example'},
        ]
        upsert_hong_kong_observations(self.conn, rows)
        first = migrate_hkma_period_frequency_rows(self.conn)
        second = migrate_hkma_period_frequency_rows(self.conn)
        self.assertEqual(first['legacy_rows_superseded'], 3)
        self.assertEqual(first['canonical_rows_written'], 2)
        self.assertEqual(second['legacy_rows_superseded'], 0)
        self.assertEqual(second['canonical_rows_written'], 0)
        active = self.conn.execute('''SELECT indicator_code,period,frequency,value
            FROM hong_kong_macro_observations
            WHERE COALESCE(data_status,'') <> 'superseded'
            ORDER BY indicator_code,period''').fetchall()
        self.assertEqual([(row['indicator_code'], row['period'], row['frequency']) for row in active], [
            ('HK_HKMA_GOV_CONSOLIDATED_BALANCE', '2025-05', 'monthly'),
            ('HK_HKMA_NOMINAL_GDP', '2025-Q2', 'quarterly'),
        ])
        self.assertEqual(self.conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
            WHERE indicator_code='HK_HKMA_REAL_GDP' AND data_status='superseded'
              AND missing_reason='superseded_hkma_period_frequency_repair' ''').fetchone()[0], 1)

    def test_safe_release_metadata_migration_is_value_preserving_and_idempotent(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            ensure_china_macro_tables(conn)
            rows = parse_safe_reserve_html('''<table>
              <tr><td>Item</td><td>2026-07</td><td>SDR</td><td>2026-08</td><td>SDR</td></tr>
              <tr><td>Foreign currency reserves</td><td x:num="34187.76">34187.76</td><td>—</td><td x:num="34188">34188</td><td>—</td></tr>
              <tr><td>IMF reserve position</td><td x:num="1">1</td><td>—</td><td x:num="1">1</td><td>—</td></tr>
              <tr><td>SDRs</td><td x:num="2">2</td><td>—</td><td x:num="2">2</td><td>—</td></tr>
              <tr><td>Gold</td><td x:num="3">3</td><td>—</td><td x:num="3">3</td><td>—</td></tr>
              <tr><td>Other reserve assets</td><td x:num="4">4</td><td>—</td><td x:num="4">4</td><td>—</td></tr>
              <tr><td>Total</td><td x:num="34197.76">34197.76</td><td>—</td><td x:num="34198">34198</td><td>—</td></tr>
            </table>''',
                'https://www.safe.gov.cn/safe/2026/0206/27116.html', '2026 官方储备资产')
            upsert_external_observations(conn, rows)
            conn.execute('''UPDATE china_macro_observations SET release_date='2026-02-06'
                WHERE indicator_code='CN_SAFE_FX_RESERVES_USD' ''')
            conn.commit()
            before = conn.execute('''SELECT value FROM china_macro_observations
                WHERE indicator_code='CN_SAFE_FX_RESERVES_USD' AND period='2026-07' ''').fetchone()[0]
            first = migrate_safe_reserve_release_metadata(conn)
            second = migrate_safe_reserve_release_metadata(conn)
            row = conn.execute('''SELECT value,release_date,source_page_created_date,
                source_page_last_updated_date,release_date_not_provided,release_date_reason
                FROM china_macro_observations WHERE indicator_code='CN_SAFE_FX_RESERVES_USD'
                AND period='2026-07' ''').fetchone()
            self.assertEqual(first['rows_changed'], 12)
            self.assertEqual(second['rows_changed'], 0)
            self.assertEqual(row['value'], before)
            self.assertIsNone(row['release_date'])
            self.assertEqual(row['source_page_created_date'], '2026-02-06')
            self.assertEqual(row['source_page_last_updated_date'], '2026-08-07')
            self.assertEqual(row['release_date_not_provided'], 1)
            self.assertIn('per-observation release date', row['release_date_reason'])
        finally:
            conn.close()
            os.remove(path)

    def test_get_builders_are_read_only(self):
        row = {'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
               'period': '2026-06', 'frequency': 'monthly', 'value': 323.2,
               'unit': 'index', 'data_status': 'official', 'source_id': 'HK_RVD_PRICE_INDEX',
               'source_url': 'https://example'}
        upsert_hong_kong_observations(self.conn, [row])
        self.conn.commit()
        import hashlib
        db_before = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        counts_before = {table: self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                         for table in ('hong_kong_macro_observations', 'hong_kong_macro_sources',
                                       'hong_kong_macro_lead_lag_results',
                                       'hong_kong_macro_lead_lag_snapshots')}
        updated_before = [item[0] for item in self.conn.execute(
            'SELECT updated_at FROM hong_kong_macro_sources ORDER BY source_id')]
        self.assertTrue(build_hong_kong_macro_payload(self.path, {'indicator': 'HK_RVD_PRICE_INDEX'})['success'])
        self.assertEqual(build_hong_kong_macro_debug(self.path)['success'], True)
        self.assertEqual(build_lead_lag_payload(self.path, hk_indicator='HK_RVD_PRICE_INDEX')['status'], 'mainland_no_data')
        self.assertTrue(build_saved_lead_lag_payload(self.path)['success'])
        db_after = hashlib.sha256(Path(self.path).read_bytes()).hexdigest()
        counts_after = {table: self.conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                        for table in counts_before}
        updated_after = [item[0] for item in self.conn.execute(
            'SELECT updated_at FROM hong_kong_macro_sources ORDER BY source_id')]
        self.assertEqual(db_after, db_before)
        self.assertEqual(counts_after, counts_before)
        self.assertEqual(updated_after, updated_before)

    def test_debug_catalog_exposes_audit_fields(self):
        upsert_hong_kong_observations(self.conn, [{
            'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
            'period': '2025-01', 'frequency': 'monthly', 'value': 100,
            'unit': 'index', 'data_status': 'official',
            'source_id': 'HK_RVD_PRICE_INDEX', 'source_url': 'https://example',
        }])
        debug = build_hong_kong_macro_debug(self.path)
        item = next(row for row in debug['indicator_catalog']
                    if row['code'] == 'HK_RVD_PRICE_INDEX')
        for field in ('n_obs', 'start_period', 'end_period', 'supported_transforms',
                      'latest_status', 'source_status', 'source_freshness'):
            self.assertIn(field, item)
        self.assertIn('identity_checks', debug)
        self.assertIn('source_metadata_gaps', debug)
        self.assertIn('schema', debug)
        self.assertIn('release_lag_not_provided_count', debug['source_metadata_gaps'])

    def test_main_api_and_csv_share_filters_and_transform_metadata(self):
        rows = []
        for period, value in (('2026-01', 100), ('2026-02', 110), ('2026-03', 121)):
            rows.append({'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
                         'period': period, 'frequency': 'monthly', 'value': value,
                         'unit': 'index', 'data_status': 'official',
                         'source_id': 'HK_RVD_PRICE_INDEX', 'source_url': 'https://example'})
        upsert_hong_kong_observations(self.conn, rows)
        query = {'indicator': 'HK_RVD_PRICE_INDEX', 'start': '2026-01',
                 'end': '2026-03', 'frequency': 'monthly', 'transform': 'difference'}
        payload = build_hong_kong_macro_payload(self.path, query)
        series = payload['series']['HK_RVD_PRICE_INDEX']
        self.assertEqual([row['value'] for row in series], [None, 10, 11])
        self.assertEqual(payload['filters']['start'], '2026-01')
        self.assertEqual(payload['filters']['end'], '2026-03')
        self.assertFalse(payload['dashboard_preview'])
        self.assertEqual(payload['csd_web_table_preview'], [])
        csv_rows = build_hong_kong_macro_csv(self.path, query).splitlines()
        self.assertIn('indicator_name', csv_rows[0])
        self.assertIn('HK_RVD_PRICE_INDEX,私人住宅价格指数', csv_rows[1])
        self.assertIn(',difference,difference: x[t]-x[t-1 calendar months]', csv_rows[2])

    def test_transform_semantics_cover_mom_qoq_gaps_zero_and_semiannual(self):
        monthly = [
            {'indicator_code': 'HK_RVD_PRICE_INDEX', 'frequency': 'monthly', 'period': '2026-01', 'value': 100},
            {'indicator_code': 'HK_RVD_PRICE_INDEX', 'frequency': 'monthly', 'period': '2026-02', 'value': 110},
            {'indicator_code': 'HK_RVD_PRICE_INDEX', 'frequency': 'monthly', 'period': '2026-04', 'value': 121},
        ]
        mom = _transform_rows(monthly, 'mom')
        self.assertIsNone(mom[0]['value'])
        self.assertAlmostEqual(mom[1]['value'], 10.0)
        self.assertEqual(mom[1]['unit'], '%')
        self.assertIn('(x[t]/x[t-1 calendar months]-1)*100', mom[1]['formula'])
        self.assertEqual(mom[2]['value'], None)
        self.assertEqual(mom[2]['missing_reason'], 'adjacent_period_missing')

        zero = _transform_rows([
            {'indicator_code': 'HK_RVD_PRICE_INDEX', 'frequency': 'monthly', 'period': '2026-01', 'value': 0},
            {'indicator_code': 'HK_RVD_PRICE_INDEX', 'frequency': 'monthly', 'period': '2026-02', 'value': 10},
        ], 'mom')
        self.assertIsNone(zero[1]['value'])
        self.assertEqual(zero[1]['missing_reason'], 'zero_denominator')

        quarterly = [
            {'indicator_code': 'HK_HKMA_NOMINAL_GDP', 'frequency': 'quarterly', 'period': '2024-Q4', 'value': 100},
            {'indicator_code': 'HK_HKMA_NOMINAL_GDP', 'frequency': 'quarterly', 'period': '2025-Q1', 'value': 121},
        ]
        qoq = _transform_rows(quarterly, 'qoq')
        self.assertIsNone(qoq[0]['value'])
        self.assertAlmostEqual(qoq[1]['value'], 21.0)
        self.assertEqual(qoq[1]['unit'], '%')
        self.assertIn('x[t]/x[t-3 calendar months]', qoq[1]['formula'])

        semiannual = [
            {'indicator_code': 'HK_RVD_COMPLETIONS_YTD', 'frequency': 'semiannual', 'period': '2025-H2', 'value': 100},
            {'indicator_code': 'HK_RVD_COMPLETIONS_YTD', 'frequency': 'semiannual', 'period': '2026-H1', 'value': 110},
        ]
        difference = _transform_rows(semiannual, 'difference')
        self.assertEqual([row['value'] for row in difference], [None, 10])

    def test_identity_check_has_tolerance_statuses_and_missing_table_status(self):
        self.conn.execute('''CREATE TABLE identity_fixture (
            period TEXT, indicator_code TEXT, value REAL, data_status TEXT)''')
        self.conn.executemany('INSERT INTO identity_fixture VALUES (?,?,?,?)', [
            ('2026-01', 'total', 100, 'official'),
            ('2026-01', 'left', 60, 'official'),
            ('2026-01', 'right', 40.4, 'official'),
            ('2026-02', 'total', 100, 'official'),
            ('2026-02', 'left', 60, 'official'),
            ('2026-02', 'right', 39.5, 'official'),
            ('2026-03', 'total', 100, 'official'),
            ('2026-03', 'left', 60, 'official'),
            ('2026-03', 'right', 38, 'official'),
        ])
        fail = _identity_check(
            self.conn, 'fixture', 'identity_fixture',
            {'total': 'total', 'left': 'left', 'right': 'right'},
            lambda v: v['total'] - v['left'] - v['right'],
            absolute_tolerance=0.1, warning_tolerance=0.5, unit='units')
        self.assertEqual(fail['status'], 'fail')
        self.assertEqual(fail['checked_periods'], 3)
        self.assertGreater(fail['max_abs_residual'], 0.5)
        self.assertTrue(any(item['period'] == '2026-02' for item in fail['offending_periods']))
        self.conn.execute("UPDATE identity_fixture SET value=40.4 WHERE period='2026-03' AND indicator_code='right'")
        self.conn.commit()
        warning = _identity_check(
            self.conn, 'fixture', 'identity_fixture',
            {'total': 'total', 'left': 'left', 'right': 'right'},
            lambda v: v['total'] - v['left'] - v['right'],
            absolute_tolerance=0.1, warning_tolerance=1.0, unit='units')
        self.assertEqual(warning['status'], 'warning')
        insufficient = _identity_check(
            self.conn, 'fixture', 'identity_fixture',
            {'total': 'none', 'left': 'none2', 'right': 'none3'},
            lambda v: 0, absolute_tolerance=0.1, unit='units')
        self.assertEqual(insufficient['status'], 'insufficient_overlap')
        unavailable = _identity_check(
            self.conn, 'fixture', 'missing_identity_table',
            {'total': 'total', 'left': 'left', 'right': 'right'},
            lambda v: 0, absolute_tolerance=0.1, unit='units')
        self.assertEqual(unavailable['status'], 'table_unavailable')

    def test_dashboard_preview_bounds_series_without_changing_filters(self):
        rows = []
        for offset in range(240):
            year, month = divmod(offset, 12)
            rows.append({'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
                         'period': f'{2010 + year:04d}-{month + 1:02d}',
                         'frequency': 'monthly', 'value': offset + 1,
                         'unit': 'index', 'data_status': 'official',
                         'source_id': 'HK_RVD_PRICE_INDEX', 'source_url': 'https://example'})
        upsert_hong_kong_observations(self.conn, rows)
        payload = build_hong_kong_macro_payload(self.path, {
            'indicator': 'HK_RVD_PRICE_INDEX', 'dashboard': '1'})
        self.assertTrue(payload['dashboard_preview'])
        self.assertTrue(payload['filters']['dashboard'])
        self.assertEqual(len(payload['series']['HK_RVD_PRICE_INDEX']), 60)

    def test_china_linkage_group_exposes_eligible_hk_candidates(self):
        rows = []
        for offset in range(60):
            year, month = divmod(offset, 12)
            rows.append({'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
                         'period': f'{2021 + year:04d}-{month + 1:02d}',
                         'frequency': 'monthly', 'value': offset + 1,
                         'unit': 'index', 'data_status': 'official',
                         'source_id': 'HK_RVD_PRICE_INDEX', 'source_url': 'https://example'})
        upsert_hong_kong_observations(self.conn, rows)
        payload = build_hong_kong_macro_payload(self.path, {
            'group': 'china_linkage', 'dashboard': '1'})
        self.assertEqual(payload['filters']['group'], 'china_linkage')
        self.assertEqual(payload['metrics']['HK_RVD_PRICE_INDEX']['n_obs'], 60)
        self.assertEqual(len(payload['series']['HK_RVD_PRICE_INDEX']), 60)

    def test_query_contract_validates_source_transform_and_index_base(self):
        rows = []
        for period, value in (('2026-01', 100), ('2026-02', 110), ('2026-03', 121)):
            rows.append({'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
                         'period': period, 'frequency': 'monthly', 'value': value,
                         'unit': 'index', 'data_status': 'official',
                         'source_id': 'HK_RVD_PRICE_INDEX', 'source_url': 'https://example'})
        upsert_hong_kong_observations(self.conn, rows)
        indexed = build_hong_kong_macro_payload(self.path, {
            'indicator': 'HK_RVD_PRICE_INDEX', 'transform': 'index100',
            'base_period': '2026-02'})
        self.assertEqual(indexed['filters']['base_period'], '2026-02')
        values = [row['value'] for row in indexed['series']['HK_RVD_PRICE_INDEX']]
        self.assertEqual(values, [100 / 110 * 100, 100, 121 / 110 * 100])
        with self.assertRaises(ValueError):
            build_hong_kong_macro_payload(self.path, {
                'indicator': 'HK_RVD_PRICE_INDEX', 'source': 'NOT_A_SOURCE'})
        with self.assertRaises(ValueError):
            build_hong_kong_macro_payload(self.path, {
                'indicator': 'HK_RVD_PRICE_INDEX', 'transform': 'qoq'})

    def test_csd_endpoint_is_independent_bounded_and_frequency_aware(self):
        upsert_csd_web_table_rows(self.conn, [
            {'source_id': 'HK_CSD_WEB_110-01003', 'table_id': '110-01003',
             'period': '2000-H1', 'period_raw': '200006',
             'series_code': 'freq=H|sv=PG|stat=000', 'series_label': 'Population growth',
             'construct_label': 'Population growth', 'value': 6.8, 'unit': "('000)", 'frequency': 'semiannual',
             'statistic': 'level', 'data_status': 'official',
             'source_url': 'https://example', 'dimension_json': '{}'},
            {'source_id': 'HK_CSD_WEB_110-01003', 'table_id': '110-01003',
             'period': '2000-H2', 'period_raw': '200012',
             'series_code': 'freq=H|sv=PG|stat=000', 'series_label': 'Population growth',
             'construct_label': 'Population growth', 'value': 6.1, 'unit': "('000)", 'frequency': 'semiannual',
             'statistic': 'level', 'data_status': 'official',
             'source_url': 'https://example', 'dimension_json': '{}'},
        ])
        payload = build_hong_kong_macro_csd_web_table_payload(
            self.path, '110-01003', {'frequency': 'semiannual', 'limit': 1})
        self.assertEqual(payload['n_rows'], 1)
        self.assertEqual(payload['total_rows'], 2)
        self.assertTrue(payload['has_more'])
        self.assertEqual(payload['rows'][0]['period'], '2000-H1')
        self.assertEqual(payload['rows'][0]['unit'], "('000)")
        self.assertIn('Population growth', payload['rows'][0]['series_label'])
        self.assertNotIn('香港人口', payload['rows'][0]['series_label'])

        upsert_csd_web_table_rows(self.conn, [{
            'source_id': 'HK_CSD_WEB_620-67001', 'table_id': '620-67001',
            'period': '2026-01', 'period_raw': '202601',
            'series_code': 'freq=M|sv=VAL_RS|stat=HK_million',
            'series_label': 'HK$ million', 'value': 100,
            'unit': 'HK$ million', 'frequency': 'monthly',
            'statistic': 'level', 'data_status': 'official',
            'source_url': 'https://example', 'dimension_json': '{}'},
        ])
        main = build_hong_kong_macro_payload(
            self.path, {'indicator': 'HK_CSD_WEB_RETAIL_TOTAL_VALUE'})
        self.assertEqual(main['meta']['observation_count'], 1)
        self.assertEqual(main['series']['HK_CSD_WEB_RETAIL_TOTAL_VALUE'][0]['value'], 100)
        self.assertEqual(main['metrics']['HK_CSD_WEB_RETAIL_TOTAL_VALUE']['mapping_version'], 'csd_curated_v1')

    def test_csd_endpoint_supports_dimension_latest_and_lossless_csv(self):
        rows = []
        for period, value, code, label in (
                ('2024', 100, 'A', 'Total'), ('2025', 110, 'A', 'Total'),
                ('2024', 80, 'B', 'Other'), ('2025', 90, 'B', 'Other')):
            rows.append({'source_id': 'HK_CSD_WEB_310-31002', 'table_id': '310-31002',
                         'period': period, 'period_raw': period,
                         'series_code': f'GDP_COMPONENT={code}|freq=Y|sv=CUR|stat=HK_million',
                         'series_label': label, 'construct_label': label,
                         'value': value, 'unit': 'HK$ million', 'frequency': 'annual',
                         'statistic': 'level', 'data_status': 'official',
                         'source_url': 'https://example',
                         'dimension_json': f'{{"GDP_COMPONENT":"{code}","GDP_COMPONENTDesc":"{label}"}}'})
        upsert_csd_web_table_rows(self.conn, rows)
        latest = build_hong_kong_macro_csd_web_table_payload(
            self.path, '310-31002',
            {'dimension': 'GDP_COMPONENT:A', 'latest': '1', 'limit': 10})
        self.assertEqual(latest['n_rows'], 1)
        self.assertEqual(latest['rows'][0]['period'], '2025')
        self.assertEqual(latest['filters']['dimensions'], [('GDP_COMPONENT', 'A')])
        csv_text = build_hong_kong_macro_csd_web_table_csv(
            self.path, '310-31002', {'dimension': 'GDP_COMPONENT:A'})
        self.assertIn('dimension_json', csv_text.splitlines()[0])
        self.assertEqual(len(csv_text.splitlines()), 3)

    def test_trade_dimension_payload_is_bounded_but_full_history_is_available(self):
        rows = []
        for period in ('2026-05', '2026-06'):
            for code, value in (('A', 30), ('B', 20), ('C', 10)):
                rows.append({'source_id': 'HK_TRADE_IDDS_TOP_ORIGINS',
                             'dimension_type': 'origin_top', 'trade_type': '1',
                             'period': period, 'dimension_code': code,
                             'dimension_label': code, 'statistic': 'value_monthly',
                             'value': value + (40 if period == '2026-06' and code == 'C' else 0),
                             'unit': "HK$ '000", 'source_url': 'https://example'})
        upsert_trade_dimensions(self.conn, rows)
        bounded = build_hong_kong_macro_trade_dimensions_payload(
            self.path, dimension_type='origin_top', latest_only=True, top_n=2)
        self.assertEqual(bounded['n_rows'], 2)
        self.assertEqual([row['dimension_code'] for row in bounded['rows']], ['C', 'A'])
        full = build_hong_kong_macro_trade_dimensions_payload(
            self.path, dimension_type='origin_top', latest_only=False, top_n=None)
        self.assertEqual(full['n_rows'], 6)

    def test_lead_lag_snapshot_is_explicitly_persisted_and_retrievable(self):
        payload = {
            'success': True, 'status': 'ok', 'hk_indicator_code': 'HK_RVD_PRICE_INDEX',
            'mainland_indicator_code': 'CN_FIRST_TIER_NEW_HOME_INDEX',
            'transform': 'yoy', 'window_type': 'full', 'window_start': None,
            'window_end': None, 'note': 'test snapshot',
            'input_hash': 'input-hash', 'hk_input_hash': 'hk-hash',
            'mainland_input_hash': 'mainland-hash',
            'hk_start': '2015-01', 'hk_end': '2020-12',
            'mainland_start': '2015-01', 'mainland_end': '2020-12',
            'hk_n_obs': 72, 'mainland_n_obs': 72, 'min_overlap': 60,
            'source_vintages': {'HK_RVD_PRICE_INDEX': {'raw_sha256': 'raw-hk', 'retrieved_at': '2026-08-12T00:00:00'}},
            'parser_versions': {'hk': ['hk_macro_v3'], 'mainland': ['nbs_v1']},
            'calculation_version': 'hk_lead_lag_v2', 'code_revision': 'git:test',
            'rolling_window_specs': {'window_months': [60, 120], 'step_months': 12,
                                     'lag_min': -24, 'lag_max': 24},
            'results': [{'lag_months': -1, 'corr': 0.2, 'n_obs': 60, 'status': 'ok'},
                        {'lag_months': 0, 'corr': 0.5, 'n_obs': 61, 'status': 'ok'}],
            'rolling_windows': [],
        }
        saved = persist_lead_lag_payload(self.path, payload)
        self.assertTrue(saved['snapshot_id'])
        self.assertEqual(saved['rows_written'], 2)
        selected = build_saved_lead_lag_payload(self.path, snapshot_id=saved['snapshot_id'])
        self.assertEqual(selected['n_rows'], 2)
        self.assertEqual(selected['rows'][1]['lag_months'], 0)
        snapshots = build_saved_lead_lag_payload(self.path)
        self.assertEqual(snapshots['n_snapshots'], 1)
        self.assertEqual(selected['metadata']['computation_version'], 'hk_lead_lag_v2')
        self.assertTrue(selected['metadata']['input_hash'])
        self.assertIn('rolling_windows_json', selected['metadata'])
        self.assertIn('parser_versions_json', selected['metadata'])

    def test_legacy_lead_lag_groups_are_not_presented_as_reproducible_snapshots(self):
        self.conn.executemany('''INSERT INTO hong_kong_macro_lead_lag_results
            (result_id,pair_code,hk_indicator_code,mainland_indicator_code,transform,
             lag_months,corr,n_obs,window_start,window_end,window_type,computed_at,status,note,snapshot_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', [
            ('legacy-result-1', 'legacy-pair', 'HK_RVD_PRICE_INDEX',
             'CN_FIRST_TIER_NEW_HOME_INDEX', 'yoy', 0, 0.2, 60,
             None, None, 'full', '2026-08-12T00:00:00', 'ok', 'legacy',
             'legacy-snapshot-id'),
        ])
        self.conn.commit()
        inventory = build_saved_lead_lag_payload(self.path)
        self.assertEqual(inventory['n_snapshots'], 1)
        self.assertEqual(inventory['reproducible_snapshot_count'], 0)
        self.assertEqual(inventory['legacy_result_group_count'], 1)
        self.assertEqual(inventory['snapshots'][0]['reproducibility_status'], 'legacy_unreproducible')
        detail = build_saved_lead_lag_payload(self.path, snapshot_id='legacy-snapshot-id')
        self.assertEqual(detail['reproducibility_status'], 'legacy_unreproducible')
        self.assertFalse(detail['metadata_complete'])

    def test_lead_lag_top_level_status_contract_and_catalog_gate(self):
        empty = build_lead_lag_payload(self.path, hk_indicator='HK_RVD_PRICE_INDEX')
        self.assertFalse(empty['success'])
        self.assertEqual(empty['status'], 'hk_no_data')

        invalid = build_lead_lag_payload(self.path, hk_indicator='NOT_A_HK_INDICATOR')
        self.assertFalse(invalid['success'])
        self.assertEqual(invalid['status'], 'invalid_request')

        invalid_mainland = build_lead_lag_payload(
            self.path, mainland_indicator='NOT_A_MAINLAND_INDICATOR')
        self.assertFalse(invalid_mainland['success'])
        self.assertEqual(invalid_mainland['status'], 'invalid_request')

        unsupported = build_lead_lag_payload(
            self.path, hk_indicator='HK_RVD_PRICE_INDEX', transform='qoq')
        self.assertFalse(unsupported['success'])
        self.assertEqual(unsupported['status'], 'unsupported_transform')

        rows = []
        for index in range(15):
            year, month0 = divmod(index, 12)
            period = f'{2025 + year:04d}-{month0 + 1:02d}'
            rows.append({'indicator_code': 'HK_RVD_PRICE_INDEX', 'category': 'housing',
                         'period': period, 'frequency': 'monthly', 'value': 100 + index,
                         'unit': 'index', 'data_status': 'official',
                         'source_id': 'HK_RVD_PRICE_INDEX', 'source_url': 'https://example'})
        upsert_hong_kong_observations(self.conn, rows)
        short = build_lead_lag_payload(self.path, hk_indicator='HK_RVD_PRICE_INDEX')
        self.assertFalse(short['success'])
        self.assertEqual(short['status'], 'mainland_no_data')
        catalog = build_hong_kong_macro_payload(
            self.path, {'indicator': 'HK_RVD_PRICE_INDEX'})
        self.assertEqual(catalog['metrics']['HK_RVD_PRICE_INDEX']['n_obs'], 15)
        self.assertFalse(catalog['metrics']['HK_RVD_PRICE_INDEX']['eligible_for_lead_lag'])
        self.assertIn('supported_transforms', catalog['metrics']['HK_RVD_PRICE_INDEX'])

        # Populate both sides with only 15 months: the request is valid, but
        # no lag can satisfy the 60-month overlap gate.
        self.conn.execute('''CREATE TABLE housing_city_observations (
            city TEXT, period TEXT, indicator_code TEXT, value REAL)''')
        for index in range(15):
            year, month0 = divmod(index, 12)
            period = f'{2025 + year:04d}-{month0 + 1:02d}'
            self.conn.execute('''INSERT INTO housing_city_observations
                (city,period,indicator_code,value) VALUES (?,?,?,?)''',
                ('北京', period, 'new_home_mom_idx', 100 + index))
        self.conn.commit()
        overlap = build_lead_lag_payload(self.path, hk_indicator='HK_RVD_PRICE_INDEX')
        self.assertFalse(overlap['success'])
        self.assertEqual(overlap['status'], 'insufficient_overlap')

    def test_save_rejects_success_payload_without_valid_full_curve(self):
        before = build_saved_lead_lag_payload(self.path)['n_snapshots']
        with self.assertRaises(ValueError):
            persist_lead_lag_payload(self.path, {
                'success': True, 'status': 'ok',
                'hk_indicator_code': 'HK_RVD_PRICE_INDEX',
                'mainland_indicator_code': 'CN_FIRST_TIER_NEW_HOME_INDEX',
                'results': [{'lag_months': 0, 'corr': None, 'n_obs': 15,
                             'status': 'insufficient_sample'}],
            })
        after = build_saved_lead_lag_payload(self.path)['n_snapshots']
        self.assertEqual(before, after)

    def test_lead_lag_save_gate_and_positive_lag_exclusion(self):
        with self.assertRaises(ValueError):
            persist_lead_lag_payload(self.path, {'success': False, 'status': 'no_data'})
        for index in range(72):
            year, month0 = divmod(index, 12)
            period = f'{2015 + year:04d}-{month0 + 1:02d}'
            self.conn.execute('''INSERT INTO hong_kong_macro_observations
                (indicator_code,category,period,frequency,value,unit,data_status,source_id,source_url,retrieved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                ('HK_RVD_PRICE_INDEX', 'housing', period, 'monthly', 100 + index,
                 'index', 'official', 'HK_RVD_PRICE_INDEX', 'https://example', 'now'))
            self.conn.execute('''CREATE TABLE IF NOT EXISTS housing_city_observations (
                city TEXT, period TEXT, indicator_code TEXT, value REAL)''')
            self.conn.execute('''INSERT INTO housing_city_observations
                (city,period,indicator_code,value) VALUES (?,?,?,?)''',
                ('北京', period, 'new_home_mom_idx', 100 + index))
        self.conn.commit()
        payload = build_lead_lag_payload(self.path, min_overlap=60)
        self.assertTrue(payload['success'])
        if payload['best_hong_kong_lead']:
            self.assertGreater(payload['best_hong_kong_lead']['lag_months'], 0)

    def test_six_month_lead_lag_sign_and_full_curve(self):
        hk = [{'period': f'2020-{month:02d}', 'value': month} for month in range(1, 7)]
        mainland = [{'period': f'2020-{month:02d}', 'value': month - 1} for month in range(2, 8)]
        result = compute_lead_lag(hk, mainland, lags=range(-24, 25), min_overlap=2)
        self.assertEqual(len(result['results']), 49)
        at_plus_one = next(item for item in result['results'] if item['lag_months'] == 1)
        self.assertEqual(at_plus_one['status'], 'ok')
        self.assertAlmostEqual(at_plus_one['corr'], 1.0)
        self.assertIn('k>0 means Hong Kong leads', result['sign_convention'])
        self.assertEqual(next(item for item in result['results'] if item['lag_months'] == 24)['status'], 'insufficient_sample')

    def test_default_sample_floor_marks_short_series_missing(self):
        result = compute_lead_lag([{'period': '2020-01', 'value': 1}],
                                  [{'period': '2020-01', 'value': 1}], lags=[0], min_overlap=60)
        self.assertIsNone(result['results'][0]['corr'])
        self.assertEqual(result['results'][0]['status'], 'insufficient_sample')

    def test_rolling_window_respects_calendar_bounds(self):
        hk = [{'period': f'{year}-{month:02d}', 'value': year * 12 + month}
              for year in range(2015, 2021) for month in range(1, 13)]
        mainland = [{'period': item['period'], 'value': item['value'] + 1} for item in hk]
        from services.hong_kong_macro_service import _rolling_lead_lag
        windows = _rolling_lead_lag(hk, mainland, transform='level', min_overlap=60,
                                    window_months=(60,), step_months=12)
        self.assertTrue(windows)
        self.assertEqual(windows[0]['window_start'], '2015-01')
        self.assertEqual(windows[0]['window_end'], '2019-12')
        self.assertEqual(len(windows[0]['results']), 49)

    def test_first_tier_housing_comparison_is_explicitly_derived(self):
        self.conn.execute('''CREATE TABLE housing_city_observations (
            city TEXT, period TEXT, indicator_code TEXT, value REAL)''')
        cities = ('北京', '上海', '广州', '深圳')
        for index in range(72):
            year, month0 = divmod(index, 12)
            period = f'{2015 + year:04d}-{month0 + 1:02d}'
            self.conn.execute('''INSERT INTO hong_kong_macro_observations
                (indicator_code,category,period,frequency,value,unit,data_status,source_id,source_url,retrieved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                ('HK_RVD_PRICE_INDEX', 'housing', period, 'monthly', 100 + index,
                 'index', 'official', 'HK_RVD_PRICE_INDEX', 'https://example', 'now'))
            for city in cities:
                self.conn.execute('''INSERT INTO housing_city_observations
                    (city,period,indicator_code,value) VALUES (?,?,?,?)''',
                    (city, period, 'new_home_mom_idx', 100.1))
        self.conn.commit()
        payload = build_lead_lag_payload(self.path,
                                         mainland_indicator='CN_FIRST_TIER_NEW_HOME_INDEX',
                                         transform='yoy', min_overlap=60)
        self.assertEqual(payload['mainland_n_obs'], 72)
        self.assertEqual(payload['mainland_definition']['cities'], list(cities))
        self.assertEqual(payload['comparison_mode'], 'normalized_zscore')
        self.assertEqual(len(payload['results']), 49)

    def test_national_housing_transaction_pairings_keep_ytd_definition(self):
        self.conn.execute('''CREATE TABLE housing_national_observations (
            indicator_code TEXT, period TEXT, value REAL)''')
        for index in range(72):
            year, month0 = divmod(index, 12)
            period = f'{2015 + year:04d}-{month0 + 1:02d}'
            self.conn.execute('''INSERT INTO hong_kong_macro_observations
                (indicator_code,category,period,frequency,value,unit,data_status,source_id,source_url,retrieved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                ('HK_RVD_TOTAL_SALES_COUNT', 'housing', period, 'monthly', 100 + index,
                 'agreements', 'official', 'HK_RVD_DOMESTIC_SALES', 'https://example', 'now'))
            self.conn.execute('''INSERT INTO housing_national_observations
                (indicator_code,period,value) VALUES (?,?,?)''',
                ('sales_area_ytd_yoy_official', period, -10 + index * 0.1))
        self.conn.commit()
        payload = build_lead_lag_payload(
            self.path, hk_indicator='HK_RVD_TOTAL_SALES_COUNT',
            mainland_indicator='CN_NATIONAL_SALES_AREA_YTD_YOY',
            transform='level', min_overlap=60)
        self.assertEqual(payload['mainland_n_obs'], 72)
        self.assertEqual(payload['mainland_transform'], 'level')
        self.assertIn('YTD', payload['mainland_definition']['aggregation'])
        self.assertIn('不是月度流量', payload['mainland_definition']['aggregation'])

    def test_national_housing_monthly_flow_pairing_keeps_derived_definition(self):
        self.conn.execute('''CREATE TABLE housing_national_observations (
            indicator_code TEXT, period TEXT, value REAL)''')
        for index in range(24):
            year, month0 = divmod(index, 12)
            period = f'{2025 + year:04d}-{month0 + 1:02d}'
            self.conn.execute('''INSERT INTO hong_kong_macro_observations
                (indicator_code,category,period,frequency,value,unit,data_status,source_id,source_url,retrieved_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)''',
                ('HK_RVD_TOTAL_SALES_COUNT', 'housing', period, 'monthly', 100 + index,
                 'agreements', 'official', 'HK_RVD_DOMESTIC_SALES', 'https://example', 'now'))
            self.conn.execute('''INSERT INTO housing_national_observations
                (indicator_code,period,value) VALUES (?,?,?)''',
                ('sales_area_monthly_derived', period, 100 + index))
        self.conn.commit()
        payload = build_lead_lag_payload(
            self.path, hk_indicator='HK_RVD_TOTAL_SALES_COUNT',
            mainland_indicator='CN_NATIONAL_SALES_AREA_MONTHLY_DERIVED',
            transform='yoy', min_overlap=2)
        self.assertEqual(payload['mainland_transform'], 'yoy')
        self.assertIn('derived', payload['mainland_definition']['warning'])
        self.assertIn('相邻月份', payload['mainland_definition']['aggregation'])


if __name__ == '__main__':
    unittest.main()
