# -*- coding: utf-8 -*-
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from services.gdp_service import (
    parse_bea_sagdp_csv, parse_fred_csv, derive_yoy, build_gdp_payload,
    parse_nbs_province_gdp_sheet,
    parse_nbs_province_gdp_image,
)
from services.regional_fiscal_service import CN_PROVINCES


class GdpServiceTests(unittest.TestCase):
    def test_nbs_yearbook_image_maps_fixed_31_province_order(self):
        extracted = [{'values': [1000 + i, 2000 + i], 'confidence': 0.99}
                     for i in range(31)]
        with patch('services.gdp_service.extract_nbs_yearbook_image_values',
                   return_value=extracted):
            rows = parse_nbs_province_gdp_image(b'jpeg', '2024', value_column=1)
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[0]['region_name'], '北京')
        self.assertEqual(rows[-1]['region_name'], '新疆')
        self.assertEqual(rows[-1]['value'], 2030.0)

    def test_nbs_yearbook_sheet_requires_and_maps_all_31_provinces(self):
        class Sheet:
            ncols = 2
            data = [['地  区', '地区生产总值']] + [
                [name[0] + '  ' + name[1:] if len(name) > 1 else name, i + 100]
                for i, name in enumerate(CN_PROVINCES)
            ]
            nrows = len(data)
            def cell_value(self, row, col): return self.data[row][col]
        rows = parse_nbs_province_gdp_sheet(Sheet(), '2020')
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[0]['region_code'], '110000')
        self.assertEqual(rows[0]['indicator_code'], 'nominal_gdp')

    def test_fred_parser(self):
        self.assertEqual(parse_fred_csv('observation_date,X\n1960-01-01,10\n1961-01-01,.\n'), [('1960', 10.0)])

    def test_bea_parser_keeps_states_and_lines_one_three(self):
        text = 'GeoFIPS,GeoName,LineCode,1997,1998\n"01000","Alabama ",1,100,110\n"01000","Alabama ",3,200,220\n"91000","New England",1,9,10\n'
        rows = parse_bea_sagdp_csv(text)
        self.assertEqual(len(rows), 4)
        self.assertEqual({r['indicator_code'] for r in rows}, {'real_gdp', 'nominal_gdp'})
        self.assertTrue(all(r['region_name'] == 'Alabama' for r in rows))

    def test_bea_parser_sic_line_map(self):
        # SIC 表(SAGDP2S)只有 LineCode 1 名义值,经 line_map 落成独立指标,不混入 NAICS
        text = 'GeoFIPS,GeoName,LineCode,1963,1997\n"06000","California ",1,67808.6,1037091.2\n"06000","California ",3,999,999\n'
        rows = parse_bea_sagdp_csv(text, line_map={'1': 'nominal_gdp_sic'})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r['indicator_code'] == 'nominal_gdp_sic' for r in rows))
        self.assertEqual(rows[0]['value'], 67808.6)

    def test_derived_yoy(self):
        self.assertEqual(derive_yoy([{'period':'2020','value':100},{'period':'2021','value':110}]),
                         [{'period':'2021','value':10.0}])

    def test_empty_payload_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = build_gdp_payload(directory + '/empty.db')
        self.assertIsNone(payload['national']['CN']['latest'])
        self.assertEqual(payload['coverage']['US']['regions'], 0)
        self.assertEqual(payload['china_region_source']['status'], 'source_blocked')
        self.assertIn('regional_fiscal', payload)

    def test_region_page_uses_full_width_sections_and_period_range(self):
        page = (Path(__file__).resolve().parents[1] / 'static' / 'gdp.html').read_text(encoding='utf-8')
        self.assertIn('class="region-stack"', page)
        self.assertNotIn('class="region-layout"', page)
        self.assertIn('id="periodStart"', page)
        self.assertIn('id="periodEnd"', page)
        self.assertIn('refreshPeriodRange', page)
        self.assertIn('src="/gdp-series.js"', page)
        self.assertIn("fetch('/province-gdp-provenance-2025.json')", page)
        self.assertNotIn('src="/static/gdp-series.js"', page)
        self.assertIn('a.period===b.period', page)


class ChinaProvincialViewTests(unittest.TestCase):
    """gdp_region_observations 同表混存省级与地级市，省级视图必须只取省级码。"""

    def test_city_rows_are_excluded_from_the_china_provincial_view(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/mixed.db'
            conn = sqlite3.connect(path)
            conn.execute('''CREATE TABLE gdp_region_observations (
              id INTEGER PRIMARY KEY, country_code TEXT, region_code TEXT,
              region_name TEXT, indicator_code TEXT, period TEXT, value REAL,
              unit TEXT, data_status TEXT, source_name TEXT, source_url TEXT,
              parser_notes TEXT, updated_at TEXT,
              UNIQUE(country_code, region_code, indicator_code, period))''')
            conn.executemany(
                '''INSERT INTO gdp_region_observations
                   (country_code,region_code,region_name,indicator_code,period,value,unit)
                   VALUES (?,?,?,?,?,?,'亿元')''',
                [('CN', '310000', '上海', 'nominal_gdp', '2024', 53926.7),
                 ('CN', '310100', '上海', 'nominal_gdp', '2024', 53759.5),
                 ('CN', '440300', '深圳', 'nominal_gdp', '2024', 36801.87),
                 ('US', '06000', 'California', 'nominal_gdp', '2024', 1.0)])
            conn.commit(); conn.close()
            payload = build_gdp_payload(path)
        codes = {row['region_code'] for row in payload['regions']['CN']}
        self.assertEqual(codes, {'310000'})           # 上海不重复、深圳不混入
        self.assertEqual(payload['coverage']['CN']['regions'], 1)
        self.assertEqual(len(payload['regions']['US']), 1)   # 美国侧不受影响




class MethodsNoteTests(unittest.TestCase):
    def test_china_methods_note_warns_against_mixing_vintages(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = build_gdp_payload(directory + '/empty.db')
        note = payload['methods']['CN']
        for token in ('不同版年鉴', '城市经济页', '不可混用', '上调也可能下调'):
            self.assertIn(token, note)
        self.assertNotIn('数值更高', note)


if __name__ == '__main__':
    unittest.main()
