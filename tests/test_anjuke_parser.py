# -*- coding: utf-8 -*-
import os
import unittest

from services.anjuke_listing_service import is_blocked_response, parse_anjuke_city_page
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


if __name__ == '__main__':
    unittest.main()
