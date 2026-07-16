# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

from services.anjuke_listing_service import (
    build_anjuke_payload,
    connect,
    ensure_tables,
    is_blocked_response,
    parse_anjuke_city_page,
)
from services.anjuke_city_map import city_market_url

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


if __name__ == '__main__':
    unittest.main()
