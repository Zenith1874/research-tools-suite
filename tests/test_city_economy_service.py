# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.city_economy_service import build_city_economy_payload
from services.regional_fiscal_service import ensure_regional_fiscal_table, _upsert


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

    def test_page_exposes_multi_city_multi_metric_and_period_controls(self):
        page = (Path(__file__).resolve().parents[1] / 'static' / 'city_economy.html').read_text(
            encoding='utf-8')
        script = (Path(__file__).resolve().parents[1] / 'static' / 'city-economy.js').read_text(
            encoding='utf-8')
        for token in ('城市经济', 'id="city"', 'id="start"', 'id="end"',
                      '多城多指标', 'id="cityChips"', 'id="metricChips"',
                      'id="comparisonCharts"', 'id="matrixBody"', '/housing'):
            self.assertIn(token, page)
        for token in ('/api/city-economy/data', 'DEFAULT_METRICS', 'selectedCities',
                      '政府性基金收入', '政府性基金支出', '卖地收入',
                      '首期=100', '自定义', '待入库'):
            self.assertIn(token, script)
        # 省级背景渲染逻辑必须彻底移除，避免省值以任何形式重新出现在城市视图
        for banned in ('province_context', 'province:${row.region_code}', '省背景'):
            self.assertNotIn(banned, script)


if __name__ == '__main__':
    unittest.main()
