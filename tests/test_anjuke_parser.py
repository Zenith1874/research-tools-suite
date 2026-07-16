# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from services.anjuke_listing_service import (
    _recompute_city_changes,
    build_anjuke_payload,
    connect,
    ensure_tables,
    is_blocked_response,
    parse_anjuke_city_page,
    parse_anjuke_ranking_page,
    parse_anjuke_year_page,
)
from services.anjuke_city_map import city_history_url, city_market_url

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'anjuke_beijing_market_excerpt.html')


class AnjukeParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, 'rb') as fh:
            cls.html = fh.read()

    def test_synthetic_nuxt_fixture_extracts_current_and_history(self):
        payload = parse_anjuke_city_page(
            self.html, 'https://example.invalid/market/', '2026-07-16T01:35:38',
            allow_small_fixture=True)
        self.assertEqual(payload['city'], '示例城')
        self.assertEqual(payload['current_period'], '2026-07')
        rows = {r['period']: r for r in payload['records']}
        self.assertEqual(rows['2026-07']['avg_price'], 20000.0)
        self.assertEqual(rows['2026-07']['mom_pct'], 2.5)
        self.assertEqual(rows['2026-07']['yoy_pct'], -20.0)
        self.assertEqual(rows['2026-06']['avg_price'], 19512.0)

    def test_small_verification_shell_is_blocked(self):
        shell = '<html><title>请输入验证码</title><body>访问验证</body></html>'
        self.assertTrue(is_blocked_response(shell, 'https://callback.58.com/antibot/verifycode'))
        with self.assertRaises(PermissionError):
            parse_anjuke_city_page(shell, 'https://beijing.anjuke.com/market/')

    def test_price_guard_rejects_abnormal_current_value(self):
        bad = self.html.replace(b'"20000","2.50"', b'"999999","2.50"', 1)
        with self.assertRaisesRegex(ValueError, '越界'):
            parse_anjuke_city_page(bad, 'https://example.invalid/market/', '2026-07-16T01:35:38',
                                    allow_small_fixture=True)

    def test_extra_city_uses_reconnaissance_slug(self):
        self.assertEqual(city_market_url('常州'), 'https://cz.anjuke.com/market/')
        self.assertEqual(city_market_url('苏州'), 'https://suzhou.anjuke.com/market/')
        self.assertEqual(city_history_url('厦门', 2010),
                         'https://www.anjuke.com/fangjia/xm2010/')

    def test_synthetic_year_page_extracts_monthly_prices_and_skips_missing(self):
        html = '''<html><head><title>2010年示例城房价走势图</title></head><body><script>
        window.__NUXT__=(function(a,b){return {data:[{yearAreaData:{
        yearList:[{title:"2010年12月房价",actionUrl:a,avgPrice:"12000",monthChange:"1.20"},
        {title:"2010年2月房价",actionUrl:a,avgPrice:"10100",monthChange:"1.00"},
        {title:"2010年1月房价",actionUrl:a,avgPrice:"10000",monthChange:b}],
        otherCitiesInSameProvince:[]}}]}}("/fangjia/example2010/","-"));
        </script></body></html>'''
        parsed = parse_anjuke_year_page(
            html, 'https://example.invalid/fangjia/example2010/', '示例城', 2010,
            allow_small_fixture=True)
        self.assertEqual(parsed['history_points'], 3)
        self.assertEqual([row['period'] for row in parsed['records']],
                         ['2010-01', '2010-02', '2010-12'])
        self.assertEqual(parsed['records'][1]['avg_price'], 10100.0)
        self.assertEqual(parsed['records'][1]['mom_pct'], 1.0)

    def test_year_page_missing_prices_is_not_zero_filled(self):
        html = '''<html><head><title>2010年示例城房价走势图</title></head><body><script>
        window.__NUXT__=(function(a,b){return {data:[{yearAreaData:{
        yearList:[{title:"2010年1月房价",actionUrl:a,avgPrice:b,monthChange:b}],
        otherCitiesInSameProvince:[]}}]}}("/fangjia/example2010/","-"));
        </script></body></html>'''
        with self.assertRaisesRegex(ValueError, '逐月挂牌字段为空'):
            parse_anjuke_year_page(
                html, 'https://example.invalid/fangjia/example2010/', '示例城', 2010,
                allow_small_fixture=True)

    def test_ranking_page_is_parsed_as_one_snapshot_per_year(self):
        html = '''<html><body><script>
        window.__NUXT__=(function(a,b,c,d){return {data:[{},{avgPriceData:[
        {title:a,actionUrl:b,avgPrice:"22491",monthChange:"1.68"},
        {title:c,actionUrl:d,avgPrice:"52557",monthChange:"-5.87"}]}],fetch:[]}}("2010年上海房价","https://www.anjuke.com/fangjia/shanghai2010/",
        "2026年深圳房价","https://www.anjuke.com/fangjia/shenzhen2026/"));
        </script></body></html>'''
        parsed = parse_anjuke_ranking_page(
            html, fetched_at='2026-07-16T12:00:00', cities=('上海', '深圳'),
            allow_small_fixture=True)
        rows = {(row['city'], row['year']): row for row in parsed['records']}
        self.assertEqual(rows[('上海', 2010)]['snapshot_period'], '2010-12')
        self.assertEqual(rows[('上海', 2010)]['avg_price'], 22491.0)
        self.assertEqual(rows[('深圳', 2026)]['snapshot_period'], '2026-07')
        self.assertEqual(rows[('深圳', 2026)]['source_change_pct'], -5.87)

    def test_recompute_changes_connects_year_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'listing.db')
            conn = connect(db_path)
            try:
                ensure_tables(conn)
                conn.executemany('''INSERT INTO anjuke_city_listings
                    (city,period,avg_price,data_status) VALUES (?,?,?,?)''', [
                    ('示例城', '2009-12', 10000, 'listing_reference'),
                    ('示例城', '2010-01', 11000, 'listing_reference'),
                    ('示例城', '2011-01', 12100, 'listing_reference'),
                ])
                _recompute_city_changes(conn, ['示例城'])
                jan_2010 = conn.execute('''SELECT mom_pct,yoy_pct FROM anjuke_city_listings
                    WHERE city='示例城' AND period='2010-01' ''').fetchone()
                jan_2011 = conn.execute('''SELECT mom_pct,yoy_pct FROM anjuke_city_listings
                    WHERE city='示例城' AND period='2011-01' ''').fetchone()
                self.assertEqual(jan_2010['mom_pct'], 10.0)
                self.assertIsNone(jan_2010['yoy_pct'])
                self.assertEqual(jan_2011['yoy_pct'], 10.0)
            finally:
                conn.close()

    def test_payload_exposes_complete_city_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'listing.db')
            conn = connect(db_path)
            try:
                ensure_tables(conn)
                conn.executemany('''INSERT INTO anjuke_city_listings
                    (city,period,avg_price,mom_pct,yoy_pct,data_status,source_url,fetched_at,raw_cached)
                    VALUES (?,?,?,?,?,?,?,?,?)''', [
                    ('示例城', '2026-05', 19000, 1.0, -4.0, 'listing_reference',
                     'https://example.invalid', '2026-07-16', 'synthetic-1.html'),
                    ('示例城', '2026-06', 19500, 2.63, -2.5, 'listing_reference',
                     'https://example.invalid', '2026-07-16', 'synthetic-2.html'),
                ])
                conn.commit()
            finally:
                conn.close()
            payload = build_anjuke_payload(db_path)
            self.assertEqual(payload['history_cities'], ['示例城'])
            self.assertEqual([r['period'] for r in payload['city_history']['示例城']],
                             ['2026-05', '2026-06'])
            self.assertEqual(payload['coverage']['records'], 2)
            self.assertEqual(payload['coverage_by_city'][0]['earliest'], '2026-05')

    def test_payload_keeps_yearly_snapshot_separate_and_fills_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'listing.db')
            conn = connect(db_path)
            try:
                ensure_tables(conn)
                conn.execute('''INSERT INTO anjuke_city_listings
                    (city,period,avg_price,data_status,source_url)
                    VALUES (?,?,?,?,?)''',
                    ('北京', '2010-12', 24733, 'listing_reference',
                     'https://www.anjuke.com/fangjia/beijing2010/'))
                conn.execute('''INSERT INTO anjuke_city_yearly_rankings
                    (city,year,snapshot_period,avg_price,source_change_pct,data_status,
                     source_url,detail_url,fetched_at,raw_cached)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    ('上海', 2010, '2010-12', 22491, 1.68, 'listing_year_snapshot',
                     'https://www.anjuke.com/fangjia/',
                     'https://www.anjuke.com/fangjia/shanghai2010/',
                     '2026-07-16', 'synthetic.html'))
                conn.commit()
            finally:
                conn.close()
            payload = build_anjuke_payload(db_path)
            self.assertEqual(payload['yearly_history_by_city']['北京'][0]['source_grain'],
                             'monthly_year_end')
            self.assertEqual(payload['yearly_history_by_city']['上海'][0]['avg_price'], 22491)
            self.assertEqual(payload['yearly_coverage_by_city'][1]['ranking_points'], 1)
            shanghai = next(card for card in payload['cards'] if card['city'] == '上海')
            self.assertEqual(shanghai['data_status'], 'listing_year_snapshot')
            self.assertEqual(shanghai['period'], '2010-12')
            self.assertIsNone(shanghai['mom_pct'])


if __name__ == '__main__':
    unittest.main()
