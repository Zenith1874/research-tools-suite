# -*- coding: utf-8 -*-
"""Access-boundary tests for LAN viewing and state-changing API routes."""
import unittest
from unittest.mock import patch
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parents[1]


class ServerAccessSecurityTests(unittest.TestCase):
    def test_gpu_backed_modules_are_available_and_never_auto_connect(self):
        """The modules are open again; idleness is enforced by on-demand probing.

        They were shut off wholesale because reading their config endpoint
        health-checked the cluster.  That probe is now an explicit user action,
        so the kill switch is no longer the thing keeping the GPU untouched.
        """
        self.assertTrue(server.PAPER_TRANSLATION_ENABLED)
        self.assertTrue(server.AUDIO_TRANSCRIPTION_ENABLED)
        self.assertIsNotNone(server.PAPER_TRANSLATION)
        self.assertIsNotNone(server.AUDIO_TRANSCRIPTION)
        self.assertEqual(
            server.PAPER_TRANSLATION.config()['connection_policy'], 'on_demand_only')
        self.assertEqual(
            server.AUDIO_TRANSCRIPTION.config()['connection_policy'], 'on_demand_only')

    def test_disabled_gpu_module_paths_cover_pages_static_files_and_apis(self):
        """The kill switch must still cover every entry point when set."""
        translation_paths = (
            '/paper-translation', '/paper-translation/', '/paper_translation.html',
            '/api/translation/config', '/api/translation/probe',
            '/api/translation/jobs/' + ('a' * 32),
        )
        audio_paths = (
            '/audio-transcription', '/audio-transcription/results/' + ('a' * 32),
            '/audio_transcription.html', '/audio_transcription_result.html',
            '/api/audio/config', '/api/audio/probe',
            '/api/audio/jobs/' + ('a' * 32),
        )
        with patch.object(server, 'PAPER_TRANSLATION_ENABLED', False), \
             patch.object(server, 'AUDIO_TRANSCRIPTION_ENABLED', False):
            for path in translation_paths:
                self.assertEqual(
                    server._disabled_gpu_module_for_path(path), 'paper_translation')
            for path in audio_paths:
                self.assertEqual(
                    server._disabled_gpu_module_for_path(path), 'audio_transcription')
            self.assertIsNone(server._disabled_gpu_module_for_path('/'))
            self.assertIsNone(server._disabled_gpu_module_for_path('/api/health'))
            self.assertIsNone(server._disabled_gpu_module_for_path('/api/ebook/config'))

    def test_enabled_modules_are_not_intercepted_by_the_kill_switch(self):
        for path in ('/paper-translation', '/api/translation/probe',
                     '/audio-transcription', '/api/audio/probe'):
            self.assertIsNone(server._disabled_gpu_module_for_path(path))

    def test_loopback_addresses_can_write(self):
        self.assertTrue(server._write_request_allowed('127.0.0.1'))
        self.assertTrue(server._write_request_allowed('::1'))
        self.assertTrue(server._write_request_allowed('::ffff:127.0.0.1'))

    def test_cloudflare_proxy_header_turns_loopback_origin_into_remote(self):
        headers = {'CF-Connecting-IP': '203.0.113.10'}
        with patch.object(server, 'TRUST_CLOUDFLARE_HEADERS', True), \
             patch.object(server, 'ALLOW_REMOTE_WRITES', False), \
             patch.object(server, 'ADMIN_TOKEN', ''):
            effective = server._effective_client_ip('127.0.0.1', headers)
            self.assertEqual(effective, '203.0.113.10')
            self.assertFalse(server._write_request_allowed(effective))

    def test_cloudflare_proxy_header_requires_explicit_opt_in(self):
        headers = {'CF-Connecting-IP': '203.0.113.10'}
        with patch.object(server, 'TRUST_CLOUDFLARE_HEADERS', False):
            self.assertEqual(
                server._effective_client_ip('127.0.0.1', headers), '127.0.0.1')

    def test_invalid_cloudflare_proxy_header_does_not_change_loopback(self):
        with patch.object(server, 'TRUST_CLOUDFLARE_HEADERS', True):
            self.assertEqual(
                server._effective_client_ip(
                    '127.0.0.1', {'CF-Connecting-IP': 'not-an-ip'}),
                '127.0.0.1')

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

    def test_translation_upload_has_separate_bounded_limit(self):
        self.assertEqual(server.TRANSLATION_MAX_UPLOAD_BYTES, 50 * 1024 * 1024)

    def test_audio_upload_has_separate_bounded_limit(self):
        self.assertEqual(server.AUDIO_MAX_UPLOAD_BYTES, 1024 * 1024 * 1024)

    def test_translation_files_are_loopback_only_by_default(self):
        with patch.object(server, 'TRANSLATION_ALLOW_REMOTE', False):
            self.assertTrue(server._translation_access_allowed('127.0.0.1'))
            self.assertFalse(server._translation_access_allowed('192.168.1.25'))

    def test_audio_files_are_loopback_only_by_default(self):
        with patch.object(server, 'AUDIO_TRANSCRIPTION_ALLOW_REMOTE', False):
            self.assertTrue(server._audio_access_allowed('127.0.0.1'))
            self.assertFalse(server._audio_access_allowed('192.168.1.25'))

    def test_yuedu_fm_files_are_loopback_only_by_default(self):
        with patch.object(server, 'YUEDU_FM_ALLOW_REMOTE', False):
            self.assertTrue(server._yuedu_fm_access_allowed('127.0.0.1'))
            self.assertFalse(server._yuedu_fm_access_allowed('192.168.1.25'))

    def test_cardcookie_monitor_is_loopback_only_by_default(self):
        with patch.object(server, 'CARDCOOKIE_MONITOR_ALLOW_REMOTE', False):
            self.assertTrue(server._cardcookie_monitor_access_allowed('127.0.0.1'))
            self.assertFalse(server._cardcookie_monitor_access_allowed('192.168.1.25'))

    def test_cardcookie_runtime_is_off_after_server_import(self):
        runtime = server.CARDCOOKIE_MONITOR.runtime_status()
        self.assertFalse(runtime['running'])
        self.assertFalse(runtime['checking'])

    def test_cardcookie_routes_and_private_cache_contract(self):
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("elif path == '/api/cardcookie-monitor/status':", source)
        self.assertGreaterEqual(
            source.count("elif path == '/api/cardcookie-monitor/email-settings':"), 2)
        self.assertIn("elif path == '/api/cardcookie-monitor/start':", source)
        self.assertIn("elif path == '/api/cardcookie-monitor/stop':", source)
        self.assertIn("elif path == '/api/cardcookie-monitor/check-now':", source)
        block = source[source.index("elif path == '/api/cardcookie-monitor/status':"):
                       source.index("elif path == '/api/abdc/data':")]
        self.assertIn("cache_control='no-store, private'", block)
        post_block = source[source.rindex(
            "elif path == '/api/cardcookie-monitor/email-settings':"):]
        self.assertIn("cache_control='no-store, private'", post_block)

    def test_yuedu_fm_media_route_supports_private_ranges(self):
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("r'^/api/yuedu-fm/episodes/[0-9a-f]{24}/(audio|image)$'", source)
        self.assertIn("self.send_header('Accept-Ranges', 'bytes')", source)
        self.assertIn("self.send_header('Cache-Control', 'no-store, private')", source)

    def test_audio_result_route_uses_private_no_store_response(self):
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("r'^/api/audio/jobs/[0-9a-f]{32}/result$'", source)
        self.assertIn("cache_control='no-store, private'", source)
        self.assertIn('audio_transcription_result.html', source)

    def test_translation_metadata_and_text_routes_use_private_no_store(self):
        source = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("elif path == '/api/translation/jobs':", source)
        self.assertIn("r'^/api/translation/jobs/[0-9a-f]{32}/view$'", source)
        self.assertIn("r'^/api/translation/jobs/[0-9a-f]{32}/questions$'", source)
        translation_block = source[source.index("elif path == '/api/translation/config'"):
                                   source.index("elif path == '/api/audio/config'")]
        self.assertGreaterEqual(
            translation_block.count("cache_control='no-store, private'"), 5)

    def test_update_pages_stop_on_http_error_before_polling(self):
        for relative_path in ('dashboard.html', 'china_rates.html',
                              'us_macro.html', 'housing.html'):
            html = (ROOT / 'static' / relative_path).read_text(encoding='utf-8')
            self.assertRegex(html, r'if\s*\(\s*!\s*(?:response|r)\.ok\s*\)\s*throw',
                             relative_path)


if __name__ == '__main__':
    unittest.main()
