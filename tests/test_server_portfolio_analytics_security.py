import http.client
import json
import os
import tempfile
import threading
import unittest

from http.server import ThreadingHTTPServer

import server


class PortfolioAnalyticsHttpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = server.PORTFOLIO_ANALYTICS_DB
        self.old_trust = server.TRUST_CLOUDFLARE_HEADERS
        server.PORTFOLIO_ANALYTICS_DB = os.path.join(self.tmp.name, 'analytics.db')
        server.TRUST_CLOUDFLARE_HEADERS = True
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.PORTFOLIO_ANALYTICS_DB = self.old_db
        server.TRUST_CLOUDFLARE_HEADERS = self.old_trust
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        content = response.read()
        connection.close()
        return response.status, json.loads(content) if content else None

    def request_text(self, path):
        connection = http.client.HTTPConnection(
            '127.0.0.1', self.httpd.server_port, timeout=5)
        connection.request('GET', path)
        response = connection.getresponse()
        content = response.read().decode('utf-8')
        connection.close()
        return response.status, content

    def test_public_portfolio_can_collect_but_cannot_read(self):
        payload = json.dumps({'session_id': 'browser-session', 'path': '/'})
        status, body = self.request('POST', '/api/portfolio-visit', payload, {
            'Content-Type': 'text/plain;charset=UTF-8',
            'Origin': 'https://zhengresearch.com',
            'CF-Connecting-IP': '203.0.113.25',
            'CF-IPCountry': 'US',
        })
        self.assertEqual(status, 202)
        self.assertTrue(body['recorded'])

        status, body = self.request('GET', '/api/portfolio-analytics', headers={
            'CF-Connecting-IP': '203.0.113.25',
        })
        self.assertEqual(status, 403)
        self.assertEqual(body['code'], 'portfolio_analytics_local_only')

        status, body = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual(status, 200)
        self.assertEqual(body['overview']['total']['views'], 1)

    def test_collection_rejects_untrusted_origin(self):
        status, body = self.request('POST', '/api/portfolio-visit',
                                    json.dumps({'session_id': 'x', 'path': '/'}), {
            'Content-Type': 'text/plain',
            'Origin': 'https://attacker.example',
            'CF-Connecting-IP': '203.0.113.30',
        })
        self.assertEqual(status, 403)
        self.assertEqual(body['code'], 'portfolio_origin_forbidden')

    def test_research_tracking_selects_pages_not_apis_or_assets(self):
        self.assertTrue(server._research_page_trackable('/'))
        self.assertTrue(server._research_page_trackable('/faculty-jobs'))
        self.assertFalse(server._research_page_trackable('/api/health'))
        self.assertFalse(server._research_page_trackable('/static/app.js'))
        self.assertFalse(server._research_page_trackable('/portfolio-analytics'))

    def test_behavior_asset_and_new_event_follow_existing_security_boundary(self):
        status, script = self.request_text('/analytics-behavior.js?v=20260920a')
        self.assertEqual(status, 200)
        self.assertIn('ZRAnalyticsBehavior', script)
        payload = json.dumps({'session_id': 'behavior-session', 'page_id': 'random-page-id-123',
                              'path': '/gdp', 'event': 'engagement', 'dwell_seconds': 30})
        status, result = self.request('POST', '/api/portfolio-event', payload, {
            'Content-Type': 'text/plain', 'Origin': self.same_origin()})
        self.assertEqual(status, 202)
        self.assertTrue(result['recorded'])
        status, data = self.request('GET', '/api/portfolio-analytics?view=visitor')
        self.assertEqual(data['events']['behavior']['foreground']['samples'], 0)
        status, data = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual(data['events']['behavior']['foreground']['median_seconds'], 30)
        self.assertNotIn('foreground-v1:', json.dumps(data))
        status, _ = self.request('POST', '/api/portfolio-event', payload, {
            'Content-Type': 'text/plain', 'Origin': 'https://attacker.example'})
        self.assertEqual(status, 403)

    def test_portfolio_capabilities_exposes_only_version_with_narrow_cors(self):
        for origin in ('https://zhengresearch.com', 'https://attacker.example'):
            with self.subTest(origin=origin):
                connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
                connection.request('GET', '/api/portfolio-capabilities', headers={'Origin': origin})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read()), {'analytics_behavior_version': 1})
                if origin == 'https://zhengresearch.com':
                    self.assertEqual(response.getheader('Access-Control-Allow-Origin'), origin)
                else:
                    self.assertIsNone(response.getheader('Access-Control-Allow-Origin'))
                connection.close()

    def test_robots_policy_keeps_public_pages_indexable_but_disallows_apis(self):
        status, body = self.request_text('/robots.txt')
        self.assertEqual(status, 200)
        self.assertIn('Allow: /', body)
        self.assertIn('Disallow: /api/', body)
        self.assertIn('Disallow: /portfolio-analytics', body)

    def same_origin(self):
        return f'http://127.0.0.1:{self.httpd.server_port}'

    def event(self, payload, headers):
        return self.request('POST', '/api/portfolio-event', json.dumps(payload),
                            dict({'Content-Type': 'text/plain;charset=UTF-8'}, **headers))

    def test_public_portfolio_can_post_events_but_still_cannot_read(self):
        status, body = self.event(
            {'session_id': 'browser-session', 'path': '/', 'event': 'contact_click',
             'target': 'email'},
            {'Origin': 'https://zhengresearch.com', 'CF-Connecting-IP': '203.0.113.25',
             'CF-IPCountry': 'US'})
        self.assertEqual(status, 202)
        self.assertTrue(body['recorded'])

        status, body = self.request('GET', '/api/portfolio-analytics', headers={
            'CF-Connecting-IP': '203.0.113.25'})
        self.assertEqual(status, 403)

        status, body = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual(status, 200)
        self.assertEqual(body['events']['total']['events'], 1)
        self.assertEqual(body['events']['recent'][0]['event_name'], 'contact_click')

    def test_default_read_is_visitor_only_and_redacted(self):
        payload = json.dumps({'session_id': 'visitor', 'path': '/research'})
        status, body = self.request('POST', '/api/portfolio-visit', payload, {
            'Content-Type': 'text/plain', 'Origin': 'https://zhengresearch.com',
            'CF-Connecting-IP': '203.0.113.45', 'CF-IPCountry': 'US',
            'CF-IPCity': 'Las Cruces', 'CF-Postal-Code': '88001',
            'CF-IPLatitude': '32.31', 'CF-IPLongitude': '-106.78',
            'User-Agent': 'Mozilla/5.0 Full-UA-Should-Not-Return',
        })
        self.assertEqual(status, 202)
        status, body = self.request('GET', '/api/portfolio-analytics')
        self.assertEqual(status, 200)
        self.assertEqual(body['view'], 'visitor')
        self.assertEqual(body['filters'], {'days': 30, 'site': 'all', 'view': 'visitor'})
        row = body['recent'][0]
        self.assertNotIn('ip_address', row)
        self.assertNotIn('user_agent', row)
        self.assertNotIn('visitor_hash', row)
        self.assertNotIn('postal_code', row)
        self.assertNotIn('latitude', row)
        self.assertNotIn('longitude', row)
        self.assertNotIn('coordinates_approx', row)
        self.assertEqual(row['city'], 'Las Cruces')
        self.assertEqual(row['region'], '')

        status, body = self.request(
            'GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual(status, 200)
        diagnostic_row = body['recent'][0]
        self.assertEqual(
            diagnostic_row['coordinates_approx'], '32.3, -106.8（约 0.1°）')
        self.assertNotIn('latitude', diagnostic_row)
        self.assertNotIn('longitude', diagnostic_row)

    def test_invalid_analytics_filter_returns_clear_400(self):
        status, body = self.request('GET', '/api/portfolio-analytics?days=2')
        self.assertEqual(status, 400)
        self.assertEqual(body['code'], 'invalid_portfolio_analytics_filter')
        self.assertIn('days', body['error'])

    def test_all_history_filter_reports_permanent_retention(self):
        status, body = self.request(
            'GET', '/api/portfolio-analytics?days=all&site=all&view=visitor')
        self.assertEqual(status, 200)
        self.assertEqual(body['filters']['days'], 'all')
        self.assertEqual(body['retention_policy'], 'permanent')

    def test_reporting_timezone_is_validated_and_remains_local_only(self):
        query = '/api/portfolio-analytics?days=1&tz=America%2FDenver'
        status, body = self.request('GET', query)
        self.assertEqual(status, 200)
        self.assertEqual(body['filters']['tz'], 'America/Denver')
        self.assertEqual(body['time_range']['timezone'], 'America/Denver')
        self.assertIn('T00:00:00', body['time_range']['start'])
        for invalid in ('Not_A_Zone', '..%2Fsecret', '%20'):
            status, body = self.request('GET', '/api/portfolio-analytics?tz=' + invalid)
            self.assertEqual(status, 400)
            self.assertEqual(body['code'], 'invalid_portfolio_analytics_filter')
        status, _ = self.request('GET', query, headers={
            'CF-Connecting-IP': '203.0.113.25'})
        self.assertEqual(status, 403)

    def test_site_filter_is_applied_to_diagnostics(self):
        status, _ = self.event(
            {'session_id': 'research-local', 'path': '/gdp', 'event': 'page_view'},
            {'Origin': self.same_origin()})
        self.assertEqual(status, 202)
        status, body = self.request(
            'GET', '/api/portfolio-analytics?days=30&site=portfolio&view=diagnostics')
        self.assertEqual(status, 200)
        self.assertEqual(body['filters']['site'], 'portfolio')
        self.assertEqual(body['events']['total']['events'], 0)

    def test_event_collection_rejects_untrusted_origin(self):
        status, body = self.event(
            {'session_id': 'x', 'path': '/', 'event': 'scroll_75'},
            {'Origin': 'https://attacker.example', 'CF-Connecting-IP': '203.0.113.30'})
        self.assertEqual(status, 403)
        self.assertEqual(body['code'], 'portfolio_origin_forbidden')

    def test_unknown_event_name_is_rejected(self):
        status, _ = self.event(
            {'session_id': 'x', 'path': '/', 'event': 'keystroke'},
            {'Origin': 'https://zhengresearch.com', 'CF-Connecting-IP': '203.0.113.31'})
        self.assertEqual(status, 400)

    def test_research_events_label_the_owner_rather_than_dropping_them(self):
        payload = {'session_id': 'r', 'path': '/gdp', 'event': 'tab_view',
                   'target': '/gdp · 中国省级'}
        status, body = self.event(payload, {'Origin': self.same_origin()})
        self.assertEqual(status, 202)
        self.assertTrue(body['recorded'])

        status, body = self.event({**payload, 'session_id': 'guest'},
                                  {'Origin': self.same_origin(),
                                   'CF-Connecting-IP': '203.0.113.40'})
        self.assertEqual(status, 202)
        self.assertTrue(body['recorded'])

        status, body = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual({row['label']: row['events']
                          for row in body['events']['by_scope']},
                         {'local': 1, 'remote': 1})
        self.assertEqual({row['scope'] for row in body['events']['recent']},
                         {'local', 'remote'})

    def test_a_driven_browser_is_split_off_from_the_owners_own_usage(self):
        base = {'session_id': 'bot', 'path': '/faculty-jobs', 'event': 'page_view',
                'target': '/faculty-jobs'}
        status, body = self.event({**base, 'automated': True},
                                  {'Origin': self.same_origin()})
        self.assertEqual(status, 202)
        self.assertTrue(body['recorded'])

        status, body = self.event({**base, 'session_id': 'human'},
                                  {'Origin': self.same_origin()})
        self.assertTrue(body['recorded'])

        # A public visitor claiming automation is still separated from real traffic.
        status, body = self.event(
            {**base, 'session_id': 'far', 'event': 'scroll_75', 'automated': True},
            {'Origin': 'https://zhengresearch.com',
             'CF-Connecting-IP': '203.0.113.55'})
        self.assertTrue(body['recorded'])

        status, body = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual({row['label']: row['events']
                          for row in body['events']['by_scope']},
                         {'automation': 2, 'local': 1})

    def test_an_agent_browser_is_caught_by_its_user_agent_alone(self):
        # navigator.webdriver is false in the agent browser that produced the
        # real traffic, so the server must not depend on the page saying so.
        base = {'session_id': 'agent', 'path': '/faculty-jobs',
                'event': 'page_view', 'target': '/faculty-jobs'}
        status, body = self.event(base, {
            'Origin': self.same_origin(),
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'Claude/1.40609.0 Chrome/148.0.7778.280 Safari/537.36 MSIX')})
        self.assertTrue(body['recorded'])

        status, body = self.event({**base, 'session_id': 'owner'}, {
            'Origin': self.same_origin(),
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36')})
        self.assertTrue(body['recorded'])

        status, body = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual({row['label']: row['events']
                          for row in body['events']['by_scope']},
                         {'automation': 1, 'local': 1})

    def test_a_non_boolean_automated_flag_does_not_hide_traffic(self):
        status, body = self.event(
            {'session_id': 'sneaky', 'path': '/gdp', 'event': 'page_view',
             'target': '/gdp', 'automated': 'true'},
            {'Origin': self.same_origin()})
        self.assertTrue(body['recorded'])
        status, body = self.request('GET', '/api/portfolio-analytics?view=diagnostics')
        self.assertEqual([row['label'] for row in body['events']['by_scope']],
                         ['local'])

    def test_research_origin_must_match_the_host_it_was_served_from(self):
        self.assertTrue(server._research_collection_origin_allowed(
            'https://research.zhengresearch.com', 'research.zhengresearch.com'))
        self.assertTrue(server._research_collection_origin_allowed('', 'anything'))
        self.assertFalse(server._research_collection_origin_allowed(
            'https://evil.example', 'research.zhengresearch.com'))
        self.assertEqual(server._portfolio_event_site(
            {'Origin': 'https://zhengresearch.com'}), 'portfolio')
        self.assertIsNone(server._portfolio_event_site(
            {'Origin': 'https://evil.example', 'Host': 'research.zhengresearch.com'}))

    def test_cloudflare_location_headers_are_mapped(self):
        geo = server._cloudflare_visitor_geo({
            'CF-IPCity': 'Las Cruces', 'CF-Region': 'New Mexico',
            'CF-Region-Code': 'NM', 'CF-Postal-Code': '88001',
            'CF-Timezone': 'America/Denver', 'CF-IPLatitude': '32.31',
            'CF-IPLongitude': '-106.78',
        })
        self.assertEqual(geo['region_code'], 'NM')
        self.assertEqual(geo['city'], 'Las Cruces')


if __name__ == '__main__':
    unittest.main()
