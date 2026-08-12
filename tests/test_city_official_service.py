# -*- coding: utf-8 -*-
"""城市公报抽取的三个真实陷阱，全部取自实际公报原文。"""
import unittest

from services.city_official_service import (
    CITY_SOURCES, extract_value, find_bulletins, parse_bulletin, drop_yoy_outliers,
)


class CityOfficialExtractionTests(unittest.TestCase):
    def test_local_subtotal_never_wins_over_city_total(self):
        """常州 2023 公报里开发区口径排在全市值前面，取第一个匹配会抓错 410.8。"""
        text = ('全市开发区完成一般公共预算收入410.8亿元，增长15.9%。'
                '八、财政 全年实现一般公共预算收入680.3亿元，比上年增长7.7%。')
        self.assertEqual(extract_value(text, 'general_budget_revenue'), 680.3)

    def test_ratio_clause_in_previous_sentence_does_not_disqualify(self):
        """广州 2022：上一句的"占…比重"不能把下一句的全市支出排除掉。"""
        text = ('分别占全市一般公共预算收入比重为67.7%、32.3%。'
                '全年一般公共预算支出3014.22亿元，下降0.2%。'
                '其中，教育支出626.94亿元。')
        self.assertEqual(extract_value(text, 'general_budget_expenditure'), 3014.22)

    def test_milestone_number_is_skipped_for_the_precise_value(self):
        """苏州 2005："突破4000亿元，达4026.52亿元"，要后者。"""
        text = '全市地区生产总值突破4000亿元，达4026.52亿元，按可比价格计算比上年增长15.3%。'
        self.assertEqual(extract_value(text, 'nominal_gdp'), 4026.52)

    def test_per_capita_and_share_are_not_totals(self):
        text = ('全市实现地区生产总值31032.50亿元，增长2.1%。'
                '人均地区生产总值达164171元。'
                '民营经济增加值占地区生产总值比重为42.3%。')
        self.assertEqual(extract_value(text, 'nominal_gdp'), 31032.5)

    def test_pre_2015_wording_maps_to_the_same_indicator(self):
        text = '全年完成公共财政预算收入379.0亿元，增长12%。公共财政预算支出384.1亿元。'
        self.assertEqual(extract_value(text, 'general_budget_revenue'), 379.0)
        self.assertEqual(extract_value(text, 'general_budget_expenditure'), 384.1)

    def test_industry_and_tax_values_are_city_totals(self):
        text = ('全年地区生产总值7050.3亿元。第一产业实现增加值156.3亿元，'
                '第二产业实现增加值3263.3亿元，第三产业实现增加值3630.7亿元。'
                '一般公共预算收入592.0亿元，其中税收收入487.5亿元。')
        self.assertEqual(extract_value(text, 'primary_industry_value'), 156.3)
        self.assertEqual(extract_value(text, 'secondary_industry_value'), 3263.3)
        self.assertEqual(extract_value(text, 'tertiary_industry_value'), 3630.7)
        self.assertEqual(extract_value(text, 'tax_revenue'), 487.5)

    def test_window_never_crosses_a_sentence_boundary(self):
        """常州 2013：收入名第二次出现后接的是比重句，跨句会把下一句的支出数当收入。"""
        text = ('全年实现公共财政预算收入408.9亿元，比上年增长7.9%。'
                '公共财政预算收入占GDP的比重为9.4%。'
                '全年公共财政预算支出417.9亿元，比上年增长6.8%。')
        self.assertEqual(extract_value(text, 'general_budget_revenue'), 408.9)
        self.assertEqual(extract_value(text, 'general_budget_expenditure'), 417.9)

    def test_out_of_range_values_are_rejected(self):
        self.assertIsNone(extract_value('地区生产总值 3.5亿元，', 'nominal_gdp'))
        self.assertIsNone(extract_value('地区生产总值 999999亿元，', 'nominal_gdp'))

    def test_bulletin_links_need_city_name_and_year(self):
        html = ('<a href="/a.html">2024年常州市国民经济和社会发展统计公报</a>'
                '<a href="/d.html">2020年苏州经济和社会发展概况</a>'
                '<a href="/b.html">2024年江苏省国民经济和社会发展统计公报</a>'
                '<a href="/c.html">常州市第五次全国经济普查公报</a>')
        found = find_bulletins(html, 'https://tjj.changzhou.gov.cn/', '常州')
        self.assertEqual(list(found), ['2024'])
        self.assertTrue(found['2024'][0].endswith('/a.html'))
        suzhou = find_bulletins(html, 'https://tjj.suzhou.gov.cn/', '苏州')
        self.assertEqual(list(suzhou), ['2020'])
        self.assertTrue(suzhou['2020'][0].endswith('/d.html'))

    def test_gdp_smaller_than_three_times_revenue_is_rejected(self):
        """抽错列时 GDP 会落到财政量级，用这条比例关系整篇丢弃。"""
        html = '<p>地区生产总值1000.0亿元，一般公共预算收入900.0亿元。</p>'
        self.assertEqual(parse_bulletin(html, '常州', '2024', 'https://x', 't'), [])

    def test_isolated_year_spike_is_dropped(self):
        rows = [{'city': '常州', 'indicator_code': 'nominal_gdp', 'period': p, 'value': v}
                for p, v in (('2021', 8800.0), ('2022', 30000.0), ('2023', 10116.4))]
        kept = {row['period'] for row in drop_yoy_outliers(rows)}
        self.assertEqual(kept, {'2021', '2023'})

    def test_every_configured_city_is_a_known_city_economy_city(self):
        from services.city_economy_service import CITY_CONFIG
        known = {item['city']: item['city_code'] for item in CITY_CONFIG}
        for city, config in CITY_SOURCES.items():
            self.assertEqual(config['region_code'], known[city], city)


class CityMirrorTests(unittest.TestCase):
    """镜像通道的纪律：值可以用，但绝不能标成直连官方。"""

    def test_mirror_rows_are_stored_as_official_mirror(self):
        import sqlite3
        from services.city_official_service import store_rows
        from services.city_mirror_service import ALL_MIRROR_CODES
        conn = sqlite3.connect(':memory:')
        rows = [{'city': '厦门', 'period': '2024', 'indicator_code': 'nominal_gdp',
                 'value': 8589.01, 'unit': '亿元', 'source_url': 'https://mirror/x',
                 'source_title': '厦门市2024年国民经济和社会发展统计公报'},
                {'city': '厦门', 'period': '2024',
                 'indicator_code': 'general_budget_revenue', 'value': 800.0,
                 'unit': '亿元', 'source_url': 'https://mirror/x', 'source_title': 't'}]
        store_rows(conn, rows, region_codes=ALL_MIRROR_CODES,
                   data_status='official_mirror',
                   source_name_fmt='{city}市统计局（经红黑统计公报库镜像）',
                   notes_prefix='本机网络无法直连该市官方原站，')
        gdp = conn.execute('SELECT data_status,source_name,region_code,parser_notes '
                           'FROM gdp_region_observations').fetchone()
        self.assertEqual(gdp[0], 'official_mirror')
        self.assertIn('镜像', gdp[1])
        self.assertEqual(gdp[2], '350200')
        self.assertIn('无法直连', gdp[3])
        fiscal = conn.execute('SELECT data_status,source_name '
                              'FROM regional_fiscal_observations').fetchone()
        self.assertEqual(fiscal[0], 'official_mirror')
        self.assertIn('镜像', fiscal[1])
        conn.close()

    def test_official_channel_keeps_plain_official_status(self):
        import sqlite3
        from services.city_official_service import store_rows
        conn = sqlite3.connect(':memory:')
        store_rows(conn, [{'city': '苏州', 'period': '2024',
                           'indicator_code': 'nominal_gdp', 'value': 26727.0,
                           'unit': '亿元', 'source_url': 'https://tjj.suzhou.gov.cn/x',
                           'source_title': 't'}])
        row = conn.execute('SELECT data_status,source_name FROM gdp_region_observations').fetchone()
        self.assertEqual(row[0], 'official')
        self.assertNotIn('镜像', row[1])
        conn.close()

    def test_industry_rows_go_to_gdp_table_not_fiscal_table(self):
        import sqlite3
        from services.city_official_service import store_rows
        conn = sqlite3.connect(':memory:')
        store_rows(conn, [{
            'city': '无锡', 'period': '2024',
            'indicator_code': 'secondary_industry_value', 'value': 7716.02,
            'unit': '亿元', 'source_url': 'https://www.wuxi.gov.cn/x',
            'source_title': '2024年无锡市国民经济和社会发展统计公报',
        }])
        row = conn.execute('SELECT indicator_code,value FROM gdp_region_observations').fetchone()
        self.assertEqual(row[0], 'secondary_industry_value')
        self.assertEqual(row[1], 7716.02)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0], 0)
        conn.close()

    def test_official_bulletin_replaces_a_mirror_and_is_idempotent(self):
        import sqlite3
        from services.city_official_service import store_rows
        conn = sqlite3.connect(':memory:')
        row = {
            'city': '无锡', 'period': '2024',
            'indicator_code': 'nominal_gdp', 'value': 16263.29,
            'unit': '亿元', 'source_url': 'https://www.wuxi.gov.cn/official',
            'source_title': '2024年无锡市国民经济和社会发展统计公报',
        }
        store_rows(conn, [{**row, 'value': 16000.0, 'source_url': 'https://mirror.invalid'}],
                   data_status='official_mirror', source_name_fmt='第三方镜像')
        store_rows(conn, [row])
        store_rows(conn, [row])
        rows = conn.execute('SELECT value,data_status,source_url FROM gdp_region_observations').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 16263.29)
        self.assertEqual(rows[0][1], 'official')
        self.assertEqual(rows[0][2], 'https://www.wuxi.gov.cn/official')
        conn.close()

    def test_mirror_only_covers_cities_without_official_access(self):
        from services.city_mirror_service import MIRROR_CITIES, VERIFY_CITIES
        from services.city_official_service import CITY_SOURCES
        self.assertEqual(set(MIRROR_CITIES) & set(CITY_SOURCES), set())
        self.assertEqual(set(VERIFY_CITIES), set(CITY_SOURCES))
        self.assertIn('无锡', CITY_SOURCES)

    def test_mirror_cannot_overwrite_higher_priority_official_value(self):
        import sqlite3
        from services.city_official_service import store_rows
        from services.city_mirror_service import ALL_MIRROR_CODES
        conn = sqlite3.connect(':memory:')
        store_rows(conn, [{
            'city': '厦门', 'period': '2020',
            'indicator_code': 'general_budget_revenue', 'value': 783.94,
            'unit': '亿元', 'source_url': 'https://data.stats.gov.cn/',
            'source_title': '国家统计局主要城市年度数据',
        }], region_codes=ALL_MIRROR_CODES, data_status='official_revised',
            source_name_fmt='国家统计局')
        result = store_rows(conn, [{
            'city': '厦门', 'period': '2020',
            'indicator_code': 'general_budget_revenue', 'value': 236.92,
            'unit': '亿元', 'source_url': 'https://mirror.invalid',
            'source_title': '第三方镜像公报',
        }], region_codes=ALL_MIRROR_CODES, data_status='official_mirror',
            source_name_fmt='第三方镜像')
        row = conn.execute('''SELECT value,data_status FROM regional_fiscal_observations
          WHERE region_code='350200' AND indicator_code='general_budget_revenue'
          AND period='2020' ''').fetchone()
        self.assertEqual(row[0], 783.94)
        self.assertEqual(row[1], 'official_revised')
        self.assertEqual(result['skipped_lower_priority'], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
