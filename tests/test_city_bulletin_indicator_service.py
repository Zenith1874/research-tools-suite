# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest

from services.city_bulletin_indicator_service import (
    _upsert_indicator,
    parse_bulletin_indicators,
    TARGETS,
)
from services.city_nbs_service import ensure_city_indicator_table


class CityBulletinIndicatorTests(unittest.TestCase):
    def test_gap_city_targets_include_the_five_new_cities(self):
        self.assertEqual(TARGETS['武汉'], '420100')
        self.assertEqual(TARGETS['长沙'], '430100')
        self.assertEqual(TARGETS['成都'], '510100')
        self.assertEqual(TARGETS['杭州'], '330100')
        self.assertEqual(TARGETS['福州'], '350100')

    def test_parse_explicit_levels_and_keep_units_separate(self):
        text = (
            '年末常住人口1304.77万人。全年实现社会消费品零售总额9092.2亿元，'
            '全年实现货物进出口总额28119.3亿元。房地产开发投资988.74亿元，'
            '新建商品房销售备案面积445.6万平方米。年末拥有各类医疗卫生机构5027家，'
            '其中医院288家，拥有执业（助理）医师5.02万人。城镇新增就业12.3万人。')
        rows = parse_bulletin_indicators(
            text, '苏州', '2025', 'https://example.test/bulletin', '2025公报')
        values = {row['indicator_code']: (row['value'], row['unit']) for row in rows}
        self.assertEqual(values['resident_population'], (1304.77, '万人'))
        self.assertEqual(values['retail_sales'], (9092.2, '亿元'))
        self.assertEqual(values['trade_total_cny'], (28119.3, '亿元'))
        self.assertEqual(values['real_estate_investment'], (988.74, '亿元'))
        self.assertEqual(values['new_commercial_housing_filing_area'], (445.6, '万㎡'))
        self.assertEqual(values['hospitals'], (288.0, '个'))
        self.assertEqual(values['medical_institutions'], (5027.0, '个'))
        self.assertEqual(values['physicians'], (5.02, '万人'))
        self.assertEqual(values['urban_new_jobs'], (12.3, '万人'))

    def test_population_variants_with_city_qualifier_are_supported(self):
        rows = parse_bulletin_indicators(
            '年末全市常住总人口1072.14万人，年末全市户籍人口733.53万人。',
            '长沙', '2025', 'https://example.test/bulletin', '2025公报')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['resident_population'], 1072.14)
        self.assertEqual(values['registered_population'], 733.53)

    def test_growth_only_phrase_does_not_create_a_level(self):
        rows = parse_bulletin_indicators(
            '房地产开发投资下降41.1%，商品房销售面积下降10.2%。',
            '常州', '2025', 'https://example.test/bulletin', '2025公报')
        codes = {row['indicator_code'] for row in rows}
        self.assertNotIn('real_estate_investment', codes)
        self.assertNotIn('commercial_housing_sold_area', codes)

    def test_new_top_tier_hospital_count_is_not_total_hospital_count(self):
        rows = parse_bulletin_indicators(
            '年末全市各级各类医疗卫生机构1819个，其中医院、卫生院（含妇幼保健院）152家。'
            '新增三甲医院3家。', '常州', '2022',
            'https://example.test/bulletin', '2022公报')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['medical_institutions'], 1819.0)
        self.assertNotIn('hospitals', values)

    def test_full_width_numbers_are_supported(self):
        rows = parse_bulletin_indicators(
            '年末常住人口５３７．５万人，社会消费品零售总额２９１８．１亿元。',
            '常州', '2025', 'https://example.test/bulletin', '2025公报')
        values = {row['indicator_code']: row['value'] for row in rows}
        self.assertEqual(values['resident_population'], 537.5)
        self.assertEqual(values['retail_sales'], 2918.1)

    def test_mirror_cannot_replace_existing_official_indicator(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        path = handle.name
        handle.close()
        try:
            conn = sqlite3.connect(path)
            ensure_city_indicator_table(conn)
            conn.execute('''INSERT INTO city_indicator_observations
              (country_code,region_code,region_name,indicator_code,period,value,unit,
               data_status,source_name,source_url,source_title,parser_notes,updated_at)
              VALUES ('CN','320500','苏州','retail_sales','2024',9000,'亿元',
               'official_revised','国家统计局','https://stats.gov.cn','在线序列','fixture','now')''')
            row = parse_bulletin_indicators(
                '社会消费品零售总额9092.2亿元。', '苏州', '2024',
                'https://example.test/bulletin', '2024公报')[0]
            self.assertFalse(_upsert_indicator(conn, row, 'now'))
            self.assertEqual(conn.execute('''SELECT value FROM city_indicator_observations
              WHERE region_code='320500' AND indicator_code='retail_sales' AND period='2024' ''').fetchone()[0], 9000)
        finally:
            try:
                conn.close()
            except UnboundLocalError:
                pass
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
