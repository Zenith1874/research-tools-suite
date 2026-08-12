# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from services.regional_fiscal_service import (
    ensure_regional_fiscal_table, parse_asfin_dat, import_china_official_csv,
    build_regional_fiscal_payload, parse_china_final_account_text,
    parse_mof_regional_debt_html, parse_nbs_regional_fiscal_sheet, CN_PROVINCES,
    parse_nbs_regional_fiscal_image,
    _upsert,
)
from services.nbs_yearbook_ocr import parse_ocr_numeric_rows


class RegionalFiscalServiceTests(unittest.TestCase):
    def test_upsert_refreshes_source_lineage_on_canonical_overlap(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        ensure_regional_fiscal_table(conn)
        base = {'country_code': 'CN', 'government_scope': 'province_total',
                'region_code': '110000', 'region_name': '北京',
                'indicator_code': 'general_budget_revenue', 'period': '2023',
                'value': 1, 'unit': '亿元', 'frequency': 'annual',
                'period_type': 'calendar_year', 'source_title': 'old',
                'parser_notes': 'old'}
        _upsert(conn, {**base, 'source_name': '省级财政部门',
                       'source_url': 'https://czj.beijing.gov.cn/old'})
        _upsert(conn, {**base, 'value': 2,
                       'source_name': '国家统计局《中国统计年鉴》',
                       'source_url': 'https://www.stats.gov.cn/new',
                       'source_title': 'new', 'parser_notes': 'new'})
        row = conn.execute('SELECT * FROM regional_fiscal_observations').fetchone()
        self.assertEqual(row['value'], 2)
        self.assertEqual(row['source_name'], '国家统计局《中国统计年鉴》')
        self.assertEqual(row['source_url'], 'https://www.stats.gov.cn/new')

    def test_nbs_ocr_rows_skip_aggregate_and_enforce_confidence(self):
        def box(x, y): return [[x, y], [x + 8, y], [x + 8, y + 4], [x, y + 4]]
        ocr = []
        for row in range(32):
            y = 100 + row * 20
            for column, value in enumerate((1000 + row, 700 + row, 10 + row)):
                ocr.append([box(100 + column * 80, y), str(value), 0.99])
        rows = parse_ocr_numeric_rows(ocr, needed_columns=2)
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[0]['values'], [1001.0, 701.0])
        ocr[-3][2] = 0.5
        with self.assertRaisesRegex(ValueError, 'confidence'):
            parse_ocr_numeric_rows(ocr, needed_columns=2)

    def test_nbs_fiscal_image_maps_revenue_tax_and_rejects_inversion(self):
        extracted = [{'values': [1000 + i, 700 + i], 'confidence': 0.99}
                     for i in range(31)]
        with patch('services.regional_fiscal_service.extract_nbs_yearbook_image_values',
                   return_value=extracted):
            rows = parse_nbs_regional_fiscal_image(
                b'jpeg', '2024', 'revenue', 'https://stats.gov.cn/table.jpg')
        self.assertEqual(len(rows), 62)
        self.assertEqual(rows[0]['region_name'], '北京')
        self.assertEqual(rows[1]['indicator_code'], 'tax_revenue')
        extracted[4]['values'] = [100, 101]
        with patch('services.regional_fiscal_service.extract_nbs_yearbook_image_values',
                   return_value=extracted):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                parse_nbs_regional_fiscal_image(
                    b'jpeg', '2024', 'revenue', 'https://stats.gov.cn/table.jpg')

    def test_nbs_fiscal_sheet_maps_revenue_tax_and_expenditure(self):
        class Sheet:
            ncols = 3
            data = [[name, i + 100, i + 50] for i, name in enumerate(CN_PROVINCES)]
            nrows = len(data)
            def cell_value(self, row, col): return self.data[row][col]
        revenue = parse_nbs_regional_fiscal_sheet(
            Sheet(), '2020', 'revenue', 'https://stats.gov.cn/revenue.xls')
        expenditure = parse_nbs_regional_fiscal_sheet(
            Sheet(), '2020', 'expenditure', 'https://stats.gov.cn/expenditure.xls')
        self.assertEqual(len(revenue), 62)
        self.assertEqual(len(expenditure), 31)
        self.assertEqual({r['indicator_code'] for r in revenue},
                         {'general_budget_revenue', 'tax_revenue'})

    def test_mof_debt_parser_requires_all_provinces_and_skips_subregions(self):
        body = ''.join(f'<tr><td>{name}省</td><td>100</td><td>{i + 1}</td></tr>'
                       for i, name in enumerate(CN_PROVINCES))
        body += '<tr><td>广东省（不含深圳市）</td><td>90</td><td>80</td></tr>'
        rows = parse_mof_regional_debt_html(
            f'<table>{body}</table>', 'general_debt_outstanding', '2024', 'https://mof.gov.cn/x')
        self.assertEqual(len(rows), 31)
        self.assertEqual(len({r['region_code'] for r in rows}), 31)
        self.assertEqual(rows[0]['value'], 1.0)

    def test_mof_debt_parser_rejects_partial_table(self):
        with self.assertRaisesRegex(ValueError, 'expected 31'):
            parse_mof_regional_debt_html(
                '<table><tr><td>北京市</td><td>2</td><td>1</td></tr></table>',
                'general_debt_outstanding', '2024', 'https://mof.gov.cn/x')

    def test_parse_shanghai_final_account_narrative(self):
        text = '''全 市 一般公共预算收入 8312.5 亿元，全市一般公共预算支出9638.5亿元。
        全市政府性基金预算收入3466.7亿元，全市政府性基金预算支出2997.7亿元。
        市级国有土地使用权出让收入774.4亿元。截至2023年底，本市政府债务余额为8832.3亿元。'''
        rows = parse_china_final_account_text(text, 'shanghai_2023')
        values = {(r['government_scope'], r['indicator_code']): r['value'] for r in rows}
        self.assertEqual(values[('province_total', 'general_budget_revenue')], 8312.5)
        self.assertEqual(values[('province_total', 'debt_outstanding')], 8832.3)
        self.assertEqual(values[('province_level', 'land_transfer_revenue')], 774.4)

    def test_parse_guangdong_final_account_table_and_debt(self):
        text = '''全省一般公共预算收入13850.78亿元，全省一般公共预算支出18527.03亿元。
        全省政府性基金预算收入4501.88亿元，全省政府性基金预算支出8244.75亿元。
        全省政府债务余额29879.6亿元，其中一般债务7628.77亿元、专项债务22250.82亿元。
        全省偿还地方政府债券本金2054.53亿元；支付地方政府债券利息899.13亿元。
        国有土地使用权出让收入59,546,504 40,960,318 38,101,623'''
        values = {r['indicator_code']: r['value']
                  for r in parse_china_final_account_text(text, 'guangdong_2023')}
        self.assertEqual(values['land_transfer_revenue'], 3810.1623)
        self.assertEqual(values['special_debt_outstanding'], 22250.82)
        self.assertEqual(values['interest_expenditure'], 899.13)

    def test_beijing_parser_uses_full_city_appendix(self):
        text = '''收入合计 34,316,000 33,916,000 31,508,712 92.9
        收入合计 57,143,583 注：2022年全市一般公共预算收入。
        国有土地使用权出让收入 6,329,500 6,329,500 6,596,581 104.2
        国有土地使用权出让收入 21,007,854'''
        values = {r['indicator_code']: r['value']
                  for r in parse_china_final_account_text(text, 'beijing_2022')}
        self.assertAlmostEqual(values['general_budget_revenue'], 5714.3583)
        self.assertAlmostEqual(values['land_transfer_revenue'], 2100.7854)

    def test_asfin_parser_maps_units_and_skips_us_and_missing(self):
        text = ('#YEAR|GEO_ID|GEO_LABEL|ST|AGG_DESC|AGG_DESC_LABEL|GOVTYPE|AMOUNT\n'
                '2024|x|Alabama|01|SF0001|Revenue - Total Revenue|002|1234000\n'
                '2024|x|Alabama|01|SF0132|Expenditure - Total Expenditure|002|X\n'
                '2024|x|United States|00|SF0001|Revenue - Total Revenue|002|999\n')
        rows = parse_asfin_dat(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['indicator_code'], 'total_revenue')
        self.assertEqual(rows[0]['value'], 1234.0)
        self.assertEqual(rows[0]['period'], '2024')

    def test_china_import_requires_official_url_and_is_idempotent(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        ensure_regional_fiscal_table(conn)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cn.csv'
            path.write_text('region_code,region_name,period,indicator_code,value,unit,source_url\n'
                            '11,北京,2023,general_budget_revenue,6181.1,亿元,https://czj.beijing.gov.cn/a\n', encoding='utf-8')
            self.assertEqual(import_china_official_csv(conn, str(path))['rows'], 1)
            self.assertEqual(import_china_official_csv(conn, str(path))['rows'], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0], 1)

    def test_payload_builds_balance_tax_share_and_interest_burden(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        ensure_regional_fiscal_table(conn)
        base = ('US','state_government','01','Alabama','2023','million current US$','annual','fiscal_year','official','Census','https://census.gov','t','n','now')
        for code,value in [('total_revenue',100),('total_expenditure',110),('tax_revenue',60),('interest_expenditure',5)]:
            conn.execute('''INSERT INTO regional_fiscal_observations(country_code,government_scope,region_code,region_name,
              indicator_code,period,value,unit,frequency,period_type,data_status,source_name,source_url,source_title,parser_notes,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', base[:4]+(code,base[4],value)+base[5:])
        payload = build_regional_fiscal_payload(conn)
        values={r['indicator_code']:r['value'] for r in payload['rows']}
        self.assertEqual(values['fiscal_balance'], -10)
        self.assertEqual(values['tax_share'], 60)
        self.assertEqual(values['interest_burden'], 5)

    def test_page_has_real_regional_fiscal_controls(self):
        page=(Path(__file__).resolve().parents[1]/'static'/'gdp.html').read_text(encoding='utf-8')
        for token in ('data-tab="fiscal"','id="fiscalCountry"','id="fiscalMetric"',
                      'id="fiscalStart"','id="fiscalEnd"','id="fiscalRanking"'):
            self.assertIn(token,page)


if __name__ == '__main__': unittest.main()
