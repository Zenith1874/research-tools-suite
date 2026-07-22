# -*- coding: utf-8 -*-
import tempfile
import unittest
from services.gdp_service import parse_bea_sagdp_csv, parse_fred_csv, derive_yoy, build_gdp_payload


class GdpServiceTests(unittest.TestCase):
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


if __name__ == '__main__': unittest.main()
