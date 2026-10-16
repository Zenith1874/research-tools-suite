# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from services.china_external_service import (
    _mofcom_period,
    _parse_gacc_listing_page,
    parse_gacc_article,
    parse_gacc_title,
    parse_mofcom_fdi_text,
    quarantine_mofcom_period_mismatches,
    parse_mofcom_odi_text,
    parse_safe_wide_rows,
    upsert_external_observations,
)
from services.china_macro_dashboard_service import build_china_macro_payload
from services.china_macro_service import ensure_china_macro_tables


class ChinaExternalParserTests(unittest.TestCase):
    def test_fdi_headline_year_beats_later_comparison_year(self):
        rows = parse_mofcom_fdi_text('2023年全国吸收外资1.1万亿元人民币',
            '2023年，全国新设立外商投资企业53766家，同比增长39.7%；'
            '实际使用外资金额11339.1亿元人民币，同比下降8.0%。'
            '高技术产业占比为37.3%，较2022年全年提升1.2个百分点。', 'https://example')
        self.assertEqual({row['period'] for row in rows}, {'2023-12'})
        self.assertEqual(next(row['value'] for row in rows if row['indicator_code']=='CN_MOFCOM_FDI_CNY_YTD'), 11339.1)

    def test_fdi_bare_year_title_keeps_explicit_same_year_body_month(self):
        rows = parse_mofcom_fdi_text('2026年全国吸收外资情况',
            '2026年1-8月，全国实际使用外资金额5000亿元人民币，同比下降1.0%。')
        self.assertEqual({row['period'] for row in rows}, {'2026-08'})

    def test_fdi_original_usd_and_comparable_growth_are_not_exchange_rate_conversion(self):
        rows = parse_mofcom_fdi_text('2022年全国实际使用外资稳定增长',
            '2022年，全国实际使用外资金额12326.8亿元人民币，按可比口径同比增长6.3%'
            '（折合1891.3亿美元，增长8%）。')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['CN_MOFCOM_FDI_CNY_YTD'], 12326.8)
        self.assertEqual(values['CN_MOFCOM_FDI_CNY_YTD_YOY'], 6.3)
        self.assertEqual(values['CN_MOFCOM_FDI_USD_YTD'], 1891.3)
        self.assertEqual(values['CN_MOFCOM_FDI_USD_YTD_YOY'], 8)
        cny_only = parse_mofcom_fdi_text('2024年全国吸收外资',
            '实际使用外资金额8262.5亿元人民币，同比下降27.1%。')
        self.assertFalse(any('USD' in row['indicator_code'] for row in cny_only))

    def test_gacc_dual_currency_title_and_table(self):
        self.assertEqual(
            parse_gacc_title("(1) China's Total Export & Import Values, Jul 2026(in CNY)"),
            ('2026-07', 'CNY'))
        self.assertEqual(
            parse_gacc_title("(1) China's Total Export & Import Values, January-February 2025 (in USD)"),
            ('2025-02', 'USD'))
        html = '''<table>
          <tr><td>Total Export &amp; Import</td><td>46,579.6</td><td>301,263.6</td><td>-2.5</td><td>19.2</td><td>17.3</td></tr>
          <tr><td>Total Export</td><td>27,125.1</td><td>174,399.6</td><td>-3.7</td><td>17.8</td><td>14.0</td></tr>
          <tr><td>Total Import</td><td>19,454.4</td><td>126,864.0</td><td>-0.7</td><td>21.2</td><td>22.0</td></tr>
          <tr><td>Export-Import Balance</td><td>7,670.7</td><td>47,535.7</td><td>-</td><td>-</td><td>-</td></tr>
        </table>'''
        rows = parse_gacc_article(
            html, "(1) China's Total Export & Import Values, Jul 2026(in CNY)", 'http://example')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['CN_GACC_TRADE_CNY_MONTH'], 46579.6)
        self.assertEqual(values['CN_GACC_EXPORT_CNY_MONTH_YOY'], 17.8)
        self.assertEqual(values['CN_GACC_BALANCE_CNY_YTD'], 47535.7)
        self.assertNotIn('CN_GACC_TRADE_USD_MONTH', values)  # 禁止自动币种换算

    def test_gacc_listing_keeps_only_total_table_one(self):
        html = '''<a href="/cny">(1) China's Total Export &amp; Import Values, Jul 2026(in CNY)</a>
                  <a href="/usd">(1) China's Total Export &amp; Import Values, Jul 2026 (in USD)</a>
                  <a href="/mode">(2) China's Total Export &amp; Import Values by Trade Mode, Jul 2026 (in CNY)</a>'''
        periods, links = _parse_gacc_listing_page(html)
        self.assertEqual(periods, ['2026-07', '2026-07'])
        self.assertEqual({item[1] for item in links}, {'CNY', 'USD'})

    def test_mofcom_period_and_fdi_sign(self):
        self.assertEqual(_mofcom_period('2026年1—2月全国吸收外资'), '2026-02')
        self.assertEqual(_mofcom_period('商务部谈2020年一季度全国吸收外资情况'), '2020-03')
        self.assertEqual(_mofcom_period('2024年前三季度我国吸收外资情况'), '2024-09')
        self.assertEqual(_mofcom_period('2025年全国吸收外资'), '2025-12')
        rows = parse_mofcom_fdi_text(
            '2026年1-4月全国吸收外资2876.9亿元人民币',
            '全国新设立外商投资企业20113家，同比增长6.8%；'
            '实际使用外资金额2876.9亿元人民币，同比下降10.3%。', 'https://example')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['CN_MOFCOM_FDI_CNY_YTD'], 2876.9)
        self.assertEqual(values['CN_MOFCOM_FDI_CNY_YTD_YOY'], -10.3)
        self.assertEqual(values['CN_MOFCOM_FDI_NEW_FIRMS_YTD_YOY'], 6.8)

    def test_mofcom_fdi_annual_ignores_following_december_current_month(self):
        summary = (
            '2017年，全国新设立外商投资企业35652家，同比增长27.8%；'
            '实际使用外资8775.6亿元人民币，同比增长7.9%。'
            '12月当月，全国新设立外商投资企业4837家，同比增长36.5%；'
            '实际使用外资金额739.4亿元人民币，同比下降9.2%。')
        rows = parse_mofcom_fdi_text(
            '商务部外资司负责人谈2017年全年全国吸收外资情况', summary,
            'https://example')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual({row['period'] for row in rows}, {'2017-12'})
        self.assertEqual(values['CN_MOFCOM_FDI_CNY_YTD'], 8775.6)
        self.assertEqual(values['CN_MOFCOM_FDI_CNY_YTD_YOY'], 7.9)
        self.assertEqual(values['CN_MOFCOM_FDI_NEW_FIRMS_YTD'], 35652)

    def test_mofcom_odi_four_original_currency_values(self):
        summary = ('据商务部、外汇局统计，2026年1-4月，我国全行业对外直接投资4294.2亿元人民币，'
                   '同比增长3.9%（以美元计为619.9亿美元，增长7.7%）。其中，我国境内投资者'
                   '进行了非金融类直接投资，累计投资3157.4亿元人民币，下降13.9%'
                   '（以美元计为455.8亿美元，下降10.7%）。')
        rows = parse_mofcom_odi_text('2026年1-4月我国全行业对外直接投资简明统计', summary)
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['CN_MOFCOM_ODI_ALL_CNY_YTD'], 4294.2)
        self.assertEqual(values['CN_MOFCOM_ODI_ALL_USD_YTD'], 619.9)
        self.assertEqual(values['CN_MOFCOM_ODI_NONFIN_CNY_YTD_YOY'], -13.9)
        self.assertEqual(values['CN_MOFCOM_ODI_NONFIN_USD_YTD_YOY'], -10.7)

    def test_mofcom_odi_half_year_wording(self):
        summary = ('据商务部、外汇局统计，2026年1-6月，我国全行业对外直接投资5964.2亿元人民币，'
                   '同比增长3.8%（以美元计为865.3亿美元，增长8.1%）。其中，进行了非金融类'
                   '直接投资，累计投资4530.6亿元人民币，下降12.7%（以美元计为657.3亿美元，'
                   '下降9%）。')
        rows = parse_mofcom_odi_text('2026年1-6月我国全行业对外直接投资简明统计', summary)
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['CN_MOFCOM_ODI_ALL_CNY_YTD'], 5964.2)
        self.assertEqual(values['CN_MOFCOM_ODI_NONFIN_CNY_YTD'], 4530.6)
        self.assertEqual(values['CN_MOFCOM_ODI_NONFIN_USD_YTD_YOY'], -9.0)

    def test_mofcom_statistical_period_beats_publication_year(self):
        summary = ('据商务部、外汇局统计， 2025 年 ，我国全行业对外直接投资 12455.8 亿元人民币，'
                   '比上年增长 7.4%（以美元计为1743.8亿美元，增长7.1%）。其中，进行了非金融类'
                   '直接投资，累计投资10404.2亿元人民币，增长1.6%（以美元计为1456.6亿美元，增长1.3%）。')
        rows = parse_mofcom_odi_text('2026年发布的全行业对外直接投资简明统计', summary)
        self.assertTrue(rows)
        self.assertEqual({row['period'] for row in rows}, {'2025-12'})

    def test_safe_wide_months_and_official_net_row(self):
        headers = ['项目', datetime(2025, 1, 1), datetime(2025, 2, 1)]
        values = {
            'receipts': ['一、收入', 100, 120],
            'payments': ['二、支出', 80, 130],
            'net': ['三、收支差额', 20, -10],
        }
        codes = {
            'receipts': 'CN_SAFE_XB_RECEIPTS_CNY',
            'payments': 'CN_SAFE_XB_PAYMENTS_CNY',
            'net': 'CN_SAFE_XB_NET_CNY',
        }
        rows = parse_safe_wide_rows(
            headers, values, codes, '国家外汇管理局', 'safe', 'https://example', '时间序列')
        keyed = {(row['indicator_code'], row['period']): row['value'] for row in rows}
        self.assertEqual(keyed[('CN_SAFE_XB_NET_CNY', '2025-01')], 20)
        self.assertEqual(keyed[('CN_SAFE_XB_NET_CNY', '2025-02')], -10)


class ChinaExternalPersistenceTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        ensure_china_macro_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        os.remove(self.path)

    def test_upsert_is_idempotent(self):
        row = parse_mofcom_fdi_text(
            '2025年全国吸收外资7476.9亿元', '', 'https://example')[0]
        upsert_external_observations(self.conn, [row])
        upsert_external_observations(self.conn, [row])
        count = self.conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0]
        self.assertEqual(count, 1)

    def test_wrong_year_is_quarantined_with_original_row_not_deleted(self):
        wrong = parse_mofcom_fdi_text('2022年全国吸收外资11339.1亿元', '',
                                     'http://www.mofcom.gov.cn/source.html')[0]
        upsert_external_observations(self.conn, [wrong])
        correct = parse_mofcom_fdi_text('2023年全国吸收外资11339.1亿元', '',
                                       'https://www.mofcom.gov.cn/source.html')[0]
        self.assertEqual(quarantine_mofcom_period_mismatches(self.conn, [correct]), 1)
        self.conn.commit()
        old = self.conn.execute('SELECT value,original_value,data_status FROM china_macro_observations '
                                'WHERE period=?', ('2022-12',)).fetchone()
        self.assertEqual(tuple(old), (None, 11339.1, 'invalidated_source_period'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM mofcom_period_corrections').fetchone()[0], 1)
        self.assertEqual(quarantine_mofcom_period_mismatches(self.conn, [correct]), 0)
        upsert_external_observations(self.conn, [correct])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0], 2)

    def test_empty_dashboard_payload_contract(self):
        payload = build_china_macro_payload(self.path)
        self.assertTrue(payload['success'])
        self.assertEqual(payload['ingestion_runtime']['capture_version'],'nbs-release-evidence-v1')
        self.assertEqual(len(payload['ingestion_runtime']['parser_code_sha256']),64)
        self.assertEqual({group['code'] for group in payload['groups']},
            {'growth','enterprise','banking','demand','prices','employment','demography','trade','capital'})
        capital=next(group for group in payload['groups'] if group['code']=='capital')
        accounts=[chart for chart in capital['charts'] if chart['code'].startswith(('safe_bop_','safe_iip_'))]
        self.assertEqual(len(accounts),8)
        for chart in accounts:
            self.assertTrue(chart['series'])
            self.assertIn('unit',chart)
        self.assertIn('currency_options', payload)
        self.assertIn('coverage', payload)


if __name__ == '__main__':
    unittest.main()
