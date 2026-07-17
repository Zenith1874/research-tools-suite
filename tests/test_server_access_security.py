# -*- coding: utf-8 -*-
"""Access-boundary tests for LAN viewing and state-changing API routes."""
import unittest
from unittest.mock import patch
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parents[1]


class ServerAccessSecurityTests(unittest.TestCase):
    def test_loopback_addresses_can_write(self):
        self.assertTrue(server._write_request_allowed('127.0.0.1'))
        self.assertTrue(server._write_request_allowed('::1'))
        self.assertTrue(server._write_request_allowed('::ffff:127.0.0.1'))

    def test_lan_address_is_read_only_by_default(self):
        with patch.object(server, 'ALLOW_REMOTE_WRITES', False), \
             patch.object(server, 'ADMIN_TOKEN', ''):
            self.assertFalse(server._write_request_allowed('192.168.1.25'))
            self.assertFalse(server._write_request_allowed('128.123.212.99'))

    def test_remote_token_uses_exact_match(self):
        with patch.object(server, 'ALLOW_REMOTE_WRITES', False), \
             patch.object(server, 'ADMIN_TOKEN', 'correct-horse'):
            self.assertTrue(server._write_request_allowed('128.123.212.99', 'correct-horse'))
            self.assertFalse(server._write_request_allowed('128.123.212.99', 'correct'))

    def test_explicit_remote_write_override(self):
        with patch.object(server, 'ALLOW_REMOTE_WRITES', True), \
             patch.object(server, 'ADMIN_TOKEN', ''):
            self.assertTrue(server._write_request_allowed('128.123.212.99'))

    def test_cors_is_not_open_by_default(self):
        with patch.object(server, 'CORS_ORIGIN', ''):
            self.assertNotIn('Access-Control-Allow-Origin',
                             server.cors_headers('https://untrusted.example'))

    def test_configured_cors_origin_is_exact(self):
        with patch.object(server, 'CORS_ORIGIN', 'https://trusted.example'):
            self.assertEqual(
                server.cors_headers('https://trusted.example')['Access-Control-Allow-Origin'],
                'https://trusted.example')
            self.assertNotIn('Access-Control-Allow-Origin',
                             server.cors_headers('https://untrusted.example'))

    def test_post_limit_is_bounded(self):
        self.assertEqual(server.MAX_POST_BYTES, 1024 * 1024)

    def test_update_pages_stop_on_http_error_before_polling(self):
        for relative_path in ('dashboard.html', 'china_rates.html',
                              'us_macro.html', 'housing.html'):
            html = (ROOT / 'static' / relative_path).read_text(encoding='utf-8')
            self.assertRegex(html, r'if\s*\(\s*!\s*(?:response|r)\.ok\s*\)\s*throw',
                             relative_path)


if __name__ == '__main__':
    unittest.main()
