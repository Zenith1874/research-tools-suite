# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.city_economy_service import (
    CITY_CONFIG,
    CITY_ECONOMY_BOARDS,
    METRIC_CATALOG,
    _build_city_derived_rows,
    build_city_economy_payload,
)
from services.regional_fiscal_service import ensure_regional_fiscal_table, _upsert
from services.city_nbs_service import ensure_city_indicator_table


class CityEconomyServiceTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = handle.name
        handle.close()
        conn = sqlite3.connect(self.db_path)
        ensure_regional_fiscal_table(conn)
        conn.execute('''CREATE TABLE gdp_region_observations (
          country_code TEXT,region_code TEXT,region_name TEXT,indicator_code TEXT,
          period TEXT,value REAL,unit TEXT,data_status TEXT,source_name TEXT,source_url TEXT)''')
        conn.execute('''CREATE TABLE housing_city_observations (
          city TEXT,period TEXT,indicator_code TEXT,value REAL,data_status TEXT,
          source_name TEXT,source_url TEXT)''')
        for region_code, region_name, revenue, expenditure in (
                ('110000', '北京', 6372.7, 8396.5),
                ('440000', '广东', 13534.0, 18500.0)):
            for code, value in (('general_budget_revenue', revenue),
                                ('general_budget_expenditure', expenditure)):
                _upsert(conn, {
                    'country_code': 'CN', 'government_scope': 'province_total',
                    'region_code': region_code, 'region_name': region_name,
                    'indicator_code': code, 'period': '2024', 'value': value,
                    'unit': '亿元', 'frequency': 'annual',
                    'period_type': 'calendar_year', 'source_name': '官方决算',
                    'source_url': 'https://example.gov.cn/final',
                    'source_title': '2024决算', 'parser_notes': 'fixture',
                })
        conn.execute("""INSERT INTO gdp_region_observations VALUES
          ('CN','110000','北京','nominal_gdp','2024',49843.1,'亿元','official','统计局','https://stats.gov.cn'),
          ('CN','440000','广东','nominal_gdp','2024',141633.8,'亿元','official','统计局','https://stats.gov.cn')""")
        conn.execute("""INSERT INTO housing_city_observations VALUES
          ('北京','2024-12','second_home_yoy_idx',95.0,'official','统计局','https://stats.gov.cn/housing')""")
        ensure_city_indicator_table(conn)
        conn.execute('''INSERT INTO city_indicator_observations
          (country_code,region_code,region_name,indicator_code,period,value,unit,
           data_status,source_name,source_url,source_title,parser_notes,updated_at)
          VALUES ('CN','110000','北京','resident_population','2024',2183.2,'万人',
           'official_preliminary','北京市统计局','https://beijing.gov.cn/bulletin',
           '2024公报','fixture','now')''')
        conn.commit(); conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_province_values_never_fill_a_city_row(self):
        """库里有广东省的财政与 GDP，但广州行必须是缺口，不能借省值充数。"""
        listing = {'city_history': {
            '北京': [{'period': '2024-12', 'avg_price': 50000, 'mom_pct': -1,
                    'yoy_pct': -10, 'data_status': 'listing_reference',
                    'source_url': 'https://anjuke.com/beijing'}]}}
        payload = build_city_economy_payload(self.db_path, listing_payload=listing)
        by_city = {row['city']: row for row in payload['cities']}
        self.assertEqual(by_city['北京']['fiscal_scope'], 'city_total')
        self.assertEqual(by_city['北京']['latest']['general_budget_revenue']['region_name'], '北京')
        self.assertEqual(by_city['北京']['latest']['gdp']['value'], 49843.1)

        self.assertEqual(by_city['广州']['fiscal_scope'], 'missing')
        self.assertEqual(by_city['广州']['gdp_scope'], 'missing')
        self.assertIsNone(by_city['广州']['latest']['general_budget_revenue'])
        self.assertIsNone(by_city['广州']['latest']['gdp'])
        self.assertEqual(by_city['广州']['coverage']['fiscal_records'], 0)
        # 深圳与广州同属广东：省值也不得出现在任何一行
        self.assertEqual([r for r in payload['gdp_rows'] if r['city'] in ('广州', '深圳')], [])
        self.assertEqual([r for r in payload['fiscal_rows'] if r['region_name'] == '广东'], [])
        self.assertNotIn('province_context',
                         {r['geographic_scope'] for r in payload['gdp_rows'] + payload['fiscal_rows']})
        self.assertEqual(payload['coverage']['direct_city_fiscal_cities'], 1)
        self.assertIn('广州', payload['coverage']['pending_fiscal_cities'])

    def test_housing_index_is_converted_to_percent_and_listing_stays_private_reference(self):
        listing = {'city_history': {'北京': [{
            'period': '2024-12', 'avg_price': 50000, 'mom_pct': -1,
            'yoy_pct': -10, 'data_status': 'listing_reference',
            'source_url': 'https://anjuke.com/beijing'}]}}
        payload = build_city_economy_payload(self.db_path, listing_payload=listing)
        row = next(r for r in payload['official_housing']
                   if r['city'] == '北京' and r['indicator_code'] == 'second_home_yoy_pct')
        self.assertEqual(row['value'], -5.0)
        self.assertEqual(payload['listing_housing'][0]['value'], 50000)
        self.assertIn('本地独立库', ' '.join(payload['caveats']))

    def test_municipality_city_total_decision_rows_are_not_dropped(self):
        conn = sqlite3.connect(self.db_path)
        _upsert(conn, {
            'country_code': 'CN', 'government_scope': 'city_total',
            'region_code': '110000', 'region_name': '北京',
            'indicator_code': 'gov_fund_revenue', 'period': '2024',
            'value': 2094.9, 'unit': '亿元', 'frequency': 'annual',
            'period_type': 'calendar_year', 'data_status': 'official_preliminary',
            'source_name': '北京市财政局',
            'source_url': 'https://example.gov.cn/beijing-budget',
            'source_title': '2024年预算执行报告', 'parser_notes': 'fixture',
        })
        conn.commit(); conn.close()

        payload = build_city_economy_payload(self.db_path, listing_payload={})
        row = next(r for r in payload['fiscal_rows']
                   if r['city'] == '北京' and
                   r['indicator_code'] == 'gov_fund_revenue')
        self.assertEqual(row['value'], 2094.9)
        self.assertEqual(row['government_scope'], 'city_total')
        self.assertEqual(row['parser_notes'], 'fixture')
        city = next(r for r in payload['cities'] if r['city'] == '北京')
        self.assertEqual(city['latest']['gov_fund_revenue']['value'], 2094.9)

    def test_municipality_indicator_rows_accept_province_code(self):
        payload = build_city_economy_payload(self.db_path, listing_payload={})
        row = next(r for r in payload['indicator_rows']
                   if r['city'] == '北京' and
                   r['indicator_code'] == 'resident_population')
        self.assertEqual(row['region_code'], '110000')
        self.assertEqual(row['value'], 2183.2)

    def test_page_exposes_multi_city_multi_metric_and_period_controls(self):
        page = (Path(__file__).resolve().parents[1] / 'static' / 'city_economy.html').read_text(
            encoding='utf-8')
        script = (Path(__file__).resolve().parents[1] / 'static' / 'city-economy.js').read_text(
            encoding='utf-8')
        for token in ('城市经济', 'id="city"', 'id="start"', 'id="end"',
                      '十五城 × 五板块', 'id="boardTabs"', 'id="cityChips"',
                      'id="metricChips"', 'id="comparisonCharts"', 'id="matrixBody"',
                      'id="detailCityTitle"', 'id="detailFiscalMetricChart"',
                      'id="detailFiscalMetricNote"', 'id="fiscalTableCity"',
                      'id="fiscalTableStart"', 'id="fiscalTableEnd"',
                      'id="fiscalTableCsv"', '城市财政动态表',
                      'id="metricCoverageTable"', '暂不做城市综合得分', '/housing'):
            self.assertIn(token, page)
        for token in ('/api/city-economy/data', 'payload.metric_catalog', 'payload.boards',
                      'selectedCities', 'selectedMetricsByBoard', 'renderBoardTabs',
                      'payload.derived_rows', '首期=100', '自定义', '待入库',
                      '统计局修订', '开发区', "periods.includes('2010')", '挂牌参考',
                      'renderFiscalMetricChart', 'fiscalTableRows',
                      'normalizeFiscalTableRange', 'downloadFiscalTableCsv',
                      '缺失年份', '不代表零值'):
            self.assertIn(token, script)
        # 省级背景渲染逻辑必须彻底移除，避免省值以任何形式重新出现在城市视图
        for banned in ('province_context', 'province:${row.region_code}', '省背景'):
            self.assertNotIn(banned, script)

    def test_payload_has_five_transparent_boards_and_fifteen_cities(self):
        payload = build_city_economy_payload(self.db_path, listing_payload={})
        self.assertEqual(len(payload['cities']), 15)
        self.assertEqual(
            {row['city'] for row in payload['cities']},
            {'北京', '上海', '广州', '深圳', '厦门', '南京', '合肥', '常州',
             '苏州', '无锡', '武汉', '长沙', '成都', '杭州', '福州'})
        self.assertEqual([board['label'] for board in payload['boards']],
                         ['增长总览', '人口就业', '产业投资', '金融财政', '住房与城市承载力'])
        metric_keys = {metric['key'] for metric in payload['metric_catalog']}
        for board in payload['boards']:
            self.assertTrue(set(board['defaults']).issubset(board['metrics']))
            self.assertTrue(set(board['metrics']).issubset(metric_keys))
        self.assertNotIn('composite_score', metric_keys)
        self.assertIn('metric_coverage', payload)




class VintageNoteTests(unittest.TestCase):
    """口径提示必须由实际 data_status 推导，不写死城市名。"""

    def test_note_lists_only_cities_actually_on_the_revised_series(self):
        from services.city_economy_service import _vintage_note
        note = _vintage_note([
            {'city': '北京', 'indicator_code': 'nominal_gdp', 'data_status': 'official_revised'},
            {'city': '苏州', 'indicator_code': 'nominal_gdp', 'data_status': 'official'},
            {'city': '无锡', 'indicator_code': 'nominal_gdp', 'data_status': 'official_mirror'},
            # 非 GDP 指标不应把城市带进提示
            {'city': '常州', 'indicator_code': 'primary_industry_value',
             'data_status': 'official_revised'},
        ])
        self.assertEqual(note['cities'], ['北京'])
        self.assertIn('不可混用', note['text'])

    def test_no_note_when_nothing_is_on_the_revised_series(self):
        from services.city_economy_service import _vintage_note
        self.assertIsNone(_vintage_note([
            {'city': '苏州', 'indicator_code': 'nominal_gdp', 'data_status': 'official'}]))


class CityDerivedMetricTests(unittest.TestCase):
    @staticmethod
    def row(code, period, value):
        return {'city': '武汉', 'region_code': '420100', 'region_name': '武汉',
                'indicator_code': code, 'period': period, 'value': value,
                'source_url': f'https://stats.gov.cn/{code}/{period}'}

    def test_calendar_yoy_and_transparent_ratios_do_not_bridge_missing_years(self):
        gdp = [self.row('nominal_gdp', '2021', 100),
               self.row('nominal_gdp', '2022', 120),
               self.row('nominal_gdp', '2024', 180),
               self.row('tertiary_industry_value', '2022', 72)]
        fiscal = [self.row('general_budget_revenue', '2022', 60),
                  self.row('general_budget_expenditure', '2022', 100)]
        indicators = [self.row('commercial_housing_sold_area', '2022', 90),
                      self.row('registered_population', '2022', 10),
                      self.row('avg_wage', '2022', 120000),
                      self.row('residential_avg_price', '2022', 20000)]
        rows = _build_city_derived_rows(gdp, fiscal, indicators)
        by_key = {(row['indicator_code'], row['period']): row for row in rows}
        self.assertAlmostEqual(by_key[('nominal_gdp_yoy', '2022')]['value'], 20.0)
        self.assertNotIn(('nominal_gdp_yoy', '2024'), by_key)
        self.assertAlmostEqual(by_key[('tertiary_share', '2022')]['value'], 60.0)
        self.assertAlmostEqual(by_key[('fiscal_self_sufficiency', '2022')]['value'], 60.0)
        self.assertAlmostEqual(
            by_key[('housing_sales_area_per_registered_person', '2022')]['value'], 9.0)
        self.assertAlmostEqual(by_key[('annual_wage_buyable_area', '2022')]['value'], 6.0)
        self.assertTrue(all(row['data_status'] == 'derived' for row in rows))
        self.assertTrue(all(row.get('formula') for row in rows))


if __name__ == '__main__':
    unittest.main()
