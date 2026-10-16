import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from unittest.mock import patch

from services.portfolio_analytics_service import (
    build_portfolio_analytics,
    is_automated_agent,
    record_portfolio_event,
    record_portfolio_visit,
)

CRAWLER_UA = 'Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)'
HUMAN_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')


class PortfolioAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'portfolio.db')

    def tearDown(self):
        self.tmp.cleanup()

    def record_at(self, timestamp, session, site='portfolio'):
        with patch('services.portfolio_analytics_service.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat(timestamp)
            record_portfolio_visit(self.db, {'session_id': session, 'path': '/'},
                                   '203.0.113.1', HUMAN_UA, site=site)
            record_portfolio_event(self.db, {
                'session_id': session, 'path': '/',
                'event': 'contact_click' if site == 'portfolio' else 'page_view'},
                '203.0.113.1', site=site)

    def analytics_at(self, timestamp, **filters):
        with patch('services.portfolio_analytics_service.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat(timestamp)
            return build_portfolio_analytics(self.db, **filters)

    def test_today_uses_local_midnight_after_utc_has_changed_day(self):
        for timestamp, session in (
                ('2026-09-13T05:59:59+00:00', 'yesterday'),
                ('2026-09-13T06:00:00+00:00', 'midnight'),
                ('2026-09-14T01:59:59+00:00', 'evening'),
                ('2026-09-14T02:00:01+00:00', 'future')):
            self.record_at(timestamp, session)
        result = self.analytics_at('2026-09-14T02:00:00+00:00',
                                   days=1, tz='America/Denver', view='visitor')
        self.assertEqual(result['overview']['page_views']['views'], 2)
        self.assertEqual(result['events']['total']['events'], 2)
        self.assertEqual(result['daily'], [
            {'date': '2026-09-13', 'views': 2, 'visitors': 1, 'events': 2}])
        self.assertEqual(result['time_range']['start'], '2026-09-13T00:00:00-06:00')

    def test_today_handles_both_daylight_saving_transitions(self):
        for before, midnight, now, expected_start in (
                ('2026-03-08T06:59:59+00:00', '2026-03-08T07:00:00+00:00',
                 '2026-03-09T05:30:00+00:00', '2026-03-08T00:00:00-07:00'),
                ('2026-11-01T05:59:59+00:00', '2026-11-01T06:00:00+00:00',
                 '2026-11-02T06:30:00+00:00', '2026-11-01T00:00:00-06:00')):
            with self.subTest(midnight=midnight):
                self.record_at(before, 'before-' + before)
                self.record_at(midnight, 'midnight-' + midnight)
                result = self.analytics_at(now, days=1, tz='America/Denver')
                self.assertEqual(result['overview']['page_views']['views'], 1)
                self.assertEqual(result['events']['total']['events'], 1)
                self.assertEqual(result['time_range']['start'], expected_start)

    def test_positive_offset_timezone_and_site_filter_share_the_same_boundary(self):
        self.record_at('2026-09-20T15:59:59+00:00', 'before')
        self.record_at('2026-09-20T16:00:00+00:00', 'midnight')
        self.record_at('2026-09-20T16:30:00+00:00', 'other-site', 'research')
        result = self.analytics_at('2026-09-20T17:00:00+00:00',
                                   days=1, tz='Asia/Shanghai', site='portfolio')
        self.assertEqual(result['overview']['page_views']['views'], 1)
        self.assertEqual(result['events']['total']['events'], 1)
        self.assertEqual(result['daily'][0]['date'], '2026-09-21')

    def test_full_selected_trend_keeps_old_records_and_zero_record_days(self):
        self.record_at('2026-07-10T12:00:00+00:00', 'older')
        self.record_at('2026-09-19T02:00:00+00:00', 'recent')
        for view in ('visitor', 'diagnostics'):
            with self.subTest(view=view):
                result = self.analytics_at('2026-09-20T14:00:00+00:00',
                                           days=90, tz='America/Denver', view=view)
                self.assertEqual(len(result['daily']), 90)
                self.assertEqual(result['daily'][0]['date'], '2026-06-23')
                self.assertEqual(result['daily'][-1]['date'], '2026-09-20')
                self.assertEqual(sum(day['views'] for day in result['daily']), 2)
                self.assertEqual(sum(day['events'] for day in result['daily']), 2)
                self.assertEqual(result['trend']['sample_days'], 2)
                recent = next(day for day in result['daily'] if day['date'] == '2026-09-18')
                self.assertEqual(recent['views'], 1)
                self.assertEqual(result['daily'][-1]['views'], 0)
        all_history = self.analytics_at('2026-09-20T14:00:00+00:00',
                                        days='all', tz='America/Denver')
        self.assertEqual(all_history['daily'][0]['date'], '2026-07-10')
        self.assertEqual(sum(day['views'] for day in all_history['daily']), 2)

    def test_empty_days_do_not_inflate_trend_sample_size(self):
        result = self.analytics_at('2026-09-20T14:00:00+00:00',
                                   days=30, tz='America/Denver')
        self.assertEqual(len(result['daily']), 30)
        self.assertEqual(result['trend']['sample_days'], 0)
        self.assertEqual(result['trend']['status'], 'empty')

    def test_even_dwell_median_averages_the_two_middle_samples(self):
        for index, seconds in enumerate((5, 40, 100, 600)):
            record_portfolio_event(self.db, {
                'session_id': f'median-{index}', 'path': '/',
                'event': 'session_end', 'dwell_seconds': seconds}, '203.0.113.3')
        for filters in ({}, {'days': 30, 'view': 'visitor'},
                        {'days': 30, 'view': 'diagnostics'}):
            with self.subTest(filters=filters):
                dwell = build_portfolio_analytics(self.db, **filters)['events']['dwell']
                self.assertEqual(dwell['sessions'], 4)
                self.assertEqual(dwell['median_seconds'], 70)

    def test_records_anonymized_visit_and_builds_private_summary(self):
        result = record_portfolio_visit(self.db, {
            'session_id': 'session-1', 'path': '/', 'title': 'Zheng Cui',
            'referrer': 'https://www.google.com/search?q=zheng',
            'language': 'en-US', 'timezone': 'America/Denver',
            'screen_width': 1440, 'screen_height': 900,
        }, '203.0.113.42', 'Browser/1.0', 'US', 'ray-1', geo={
            'city': 'Las Cruces', 'region': 'New Mexico', 'region_code': 'NM',
            'postal_code': '88001', 'timezone': 'America/Denver',
            'latitude': '32.31', 'longitude': '-106.78',
        })
        self.assertTrue(result['recorded'])
        summary = build_portfolio_analytics(self.db)
        self.assertEqual(summary['overview']['total']['views'], 1)
        self.assertEqual(summary['recent'][0]['site'], 'portfolio')
        self.assertEqual(summary['recent'][0]['ip_prefix'], '203.0.113.0/24')
        self.assertEqual(summary['recent'][0]['ip_address'], '203.0.113.42')
        self.assertEqual(summary['recent'][0]['region_code'], 'NM')
        self.assertEqual(summary['recent'][0]['referrer_host'], 'www.google.com')
        with closing(sqlite3.connect(self.db)) as connection:
            columns = [row[1] for row in connection.execute('PRAGMA table_info(portfolio_visits)')]
        self.assertIn('ip_address', columns)

    def test_deduplicates_same_session_path_for_thirty_minutes(self):
        payload = {'session_id': 'same', 'path': '/'}
        self.assertTrue(record_portfolio_visit(self.db, payload, '203.0.113.2')['recorded'])
        self.assertFalse(record_portfolio_visit(self.db, payload, '203.0.113.2')['recorded'])
        self.assertEqual(build_portfolio_analytics(self.db)['overview']['total']['views'], 1)

    def test_rejects_invalid_path_and_missing_session(self):
        with self.assertRaises(ValueError):
            record_portfolio_visit(self.db, {'session_id': 'x', 'path': '//evil'}, '203.0.113.1')
        with self.assertRaises(ValueError):
            record_portfolio_visit(self.db, {'path': '/'}, '203.0.113.1')

    def test_separates_research_and_portfolio_visits(self):
        record_portfolio_visit(self.db, {'session_id': 'p', 'path': '/'},
                               '203.0.113.1', site='portfolio')
        record_portfolio_visit(self.db, {'session_id': 'r', 'path': '/faculty-jobs'},
                               '203.0.113.2', site='research')
        summary = build_portfolio_analytics(self.db)
        self.assertEqual(summary['overview']['total']['views'], 2)
        self.assertEqual({row['label'] for row in summary['sites']},
                         {'portfolio', 'research'})

    def test_filtered_visitor_view_uses_one_site_and_remote_interactions(self):
        record_portfolio_visit(self.db, {'session_id': 'p', 'path': '/portfolio'},
                               '203.0.113.1', site='portfolio', geo={
                                   'city': 'Las Cruces', 'region': 'New Mexico',
                                   'region_code': 'NM'})
        record_portfolio_visit(self.db, {'session_id': 'r', 'path': '/research'},
                               '203.0.113.2', site='research')
        record_portfolio_event(self.db, {
            'session_id': 'local', 'path': '/portfolio', 'event': 'contact_click'},
            '127.0.0.1', site='portfolio', scope='local')
        record_portfolio_event(self.db, {
            'session_id': 'remote', 'path': '/portfolio', 'event': 'contact_click'},
            '203.0.113.3', site='portfolio', scope='remote')
        result = build_portfolio_analytics(
            self.db, days=30, site='portfolio', view='visitor')
        self.assertEqual(result['overview']['page_views']['views'], 1)
        self.assertEqual(result['overview']['external_interactions']['events'], 1)
        self.assertEqual({row['label'] for row in result['pages']},
                         {'portfolio: /portfolio'})
        self.assertEqual({row['scope'] for row in result['events']['recent']},
                         {'remote'})
        self.assertEqual(
            next(row for row in result['recent'] if row['path'] == '/portfolio')['city'],
            'Las Cruces')
        self.assertNotIn('ip_address', result['recent'][0])
        self.assertNotIn('visitor_hash', result['recent'][0])

    def test_research_request_needs_a_nearby_browser_page_view_to_be_confirmed(self):
        record_portfolio_visit(
            self.db, {'session_id': 'server-get', 'path': '/faculty-jobs'},
            '203.0.113.20', HUMAN_UA, site='research')
        unknown = build_portfolio_analytics(
            self.db, days=30, site='research', view='visitor')
        self.assertEqual(unknown['overview']['page_views']['views'], 0)
        self.assertEqual(
            unknown['overview']['traffic_quality']['unknown_request']['views'], 1)

        record_portfolio_event(self.db, {
            'session_id': 'browser-session', 'path': '/faculty-jobs',
            'event': 'page_view'}, '203.0.113.20', site='research', scope='remote')
        confirmed = build_portfolio_analytics(
            self.db, days=30, site='research', view='visitor')
        self.assertEqual(confirmed['overview']['page_views']['views'], 1)
        self.assertEqual(
            confirmed['recent'][0]['traffic_class'], 'confirmed_browser')
        self.assertEqual(
            confirmed['recent'][0]['classification_reasons'],
            ['nearby_client_page_view'])

    def test_distributed_rotating_user_agent_burst_is_suspected_automation(self):
        networks = ('203.0.113.', '198.51.100.', '192.0.2.')
        for index in range(12):
            record_portfolio_visit(self.db, {
                'session_id': f'burst-{index}', 'path': '/',
                'referrer': 'https://research.zhengresearch.com/'},
                f'{networks[index % 3]}{index + 1}',
                f'Mozilla/5.0 Chrome/151.0.{index}.0 Safari/537.36',
                site='research')
        visitor = build_portfolio_analytics(
            self.db, days=30, site='research', view='visitor')
        quality = visitor['overview']['traffic_quality']
        self.assertEqual(visitor['overview']['page_views']['views'], 0)
        self.assertEqual(quality['suspected_automation']['views'], 12)
        self.assertEqual(quality['known_bot']['views'], 0)

        diagnostics = build_portfolio_analytics(
            self.db, days=30, site='research', view='diagnostics')
        cluster = diagnostics['diagnostics']['suspected_clusters'][0]
        self.assertEqual(cluster['requests'], 12)
        self.assertEqual(cluster['network_prefixes'], 3)
        self.assertEqual(cluster['user_agents'], 12)
        self.assertTrue(all(
            row['traffic_class'] == 'suspected_automation'
            for row in diagnostics['recent']))

    def test_self_referrer_is_not_reported_as_external_acquisition(self):
        record_portfolio_visit(self.db, {
            'session_id': 'self', 'path': '/',
            'referrer': 'https://research.zhengresearch.com/faculty-jobs'},
            '203.0.113.30', HUMAN_UA, site='portfolio')
        result = build_portfolio_analytics(
            self.db, days=30, site='portfolio', view='visitor')
        self.assertEqual(result['referrers'][0]['label'], 'Internal / Self')

    def test_diagnostics_are_filtered_and_only_return_coarse_sensitive_fields(self):
        record_portfolio_visit(self.db, {'session_id': 'bot', 'path': '/'},
                               '203.0.113.8', CRAWLER_UA, site='portfolio', geo={
                                   'latitude': '32.31', 'longitude': '-106.78'})
        record_portfolio_event(self.db, {
            'session_id': 'owner', 'path': '/', 'event': 'scroll_75'},
            '127.0.0.1', site='portfolio', scope='local')
        result = build_portfolio_analytics(
            self.db, days=30, site='portfolio', view='diagnostics')
        self.assertEqual(result['overview']['bots']['total']['views'], 1)
        self.assertEqual(result['overview']['local_events'], 1)
        visit = result['recent'][0]
        self.assertEqual(visit['ip_prefix'], '203.0.113.0/24')
        self.assertEqual(visit['user_agent_summary'], '自动化/爬虫 · 桌面设备')
        self.assertEqual(visit['coordinates_approx'], '32.3, -106.8（约 0.1°）')
        for field in ('ip_address', 'user_agent', 'visitor_hash', 'postal_code',
                      'latitude', 'longitude'):
            self.assertNotIn(field, visit)

    def test_filter_validation_rejects_unknown_values(self):
        with self.assertRaises(ValueError):
            build_portfolio_analytics(self.db, days=2)
        with self.assertRaises(ValueError):
            build_portfolio_analytics(self.db, site='other')
        with self.assertRaises(ValueError):
            build_portfolio_analytics(self.db, view='raw')

    def test_all_history_is_supported_and_old_rows_are_not_purged(self):
        record_portfolio_visit(self.db, {'session_id': 'old', 'path': '/old'},
                               '203.0.113.21')
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute(
                "UPDATE portfolio_visits SET visited_at='2020-01-01T00:00:00+00:00'")
            connection.commit()
        record_portfolio_visit(self.db, {'session_id': 'new', 'path': '/new'},
                               '203.0.113.22')
        result = build_portfolio_analytics(
            self.db, days='all', site='all', view='visitor')
        self.assertEqual(result['filters']['days'], 'all')
        self.assertEqual(result['overview']['page_views']['views'], 2)
        self.assertEqual(result['retention_policy'], 'permanent')


class AutomatedAgentTests(unittest.TestCase):
    def test_separates_crawlers_and_agent_browsers_from_real_ones(self):
        for agent in (CRAWLER_UA,
                      'Mozilla/5.0 (X11; Linux x86_64) HeadlessChrome/146.0.0.0',
                      'Mozilla/5.0 Claude/1.40609.0 Chrome/148.0.7778.280 MSIX',
                      'curl/8.4.0'):
            self.assertTrue(is_automated_agent(agent), agent)
        for agent in (HUMAN_UA, '',
                      'Mozilla/5.0 (iPhone; CPU iPhone OS 26_6 like Mac OS X) '
                      'Mobile/15E148 MicroMessenger'):
            self.assertFalse(is_automated_agent(agent), agent)


class PortfolioCrawlerVisitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'portfolio.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_crawler_visits_are_kept_but_never_counted_as_visitors(self):
        record_portfolio_visit(self.db, {'session_id': 'human', 'path': '/'},
                               '203.0.113.1', HUMAN_UA)
        record_portfolio_visit(self.db, {'session_id': 'bot', 'path': '/'},
                               '203.0.113.2', CRAWLER_UA)
        summary = build_portfolio_analytics(self.db)
        self.assertEqual(summary['overview']['total'], {'views': 1, 'visitors': 1})
        self.assertEqual(summary['bots']['total']['views'], 1)
        self.assertEqual(summary['bots']['agents'][0]['label'], CRAWLER_UA)
        self.assertEqual([row['is_bot'] for row in summary['recent']], [1, 0])
        self.assertEqual(sum(row['views'] for row in summary['pages']), 1)
        self.assertEqual(sum(row['views'] for row in summary['daily']), 1)

    def test_is_bot_is_backfilled_from_user_agents_already_stored(self):
        record_portfolio_visit(self.db, {'session_id': 'a', 'path': '/'},
                               '203.0.113.3', CRAWLER_UA)
        record_portfolio_visit(self.db, {'session_id': 'b', 'path': '/'},
                               '203.0.113.4', HUMAN_UA)
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('ALTER TABLE portfolio_visits DROP COLUMN is_bot')
            connection.commit()
        summary = build_portfolio_analytics(self.db)
        self.assertEqual(summary['overview']['total']['views'], 1)
        self.assertEqual(summary['bots']['total']['views'], 1)


class PortfolioEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'portfolio.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_whitelisted_event_and_summarises_it(self):
        result = record_portfolio_event(self.db, {
            'session_id': 'session-1', 'path': '/', 'event': 'contact_click',
            'target': 'email',
        }, '203.0.113.42', country_code='US')
        self.assertTrue(result['recorded'])
        events = build_portfolio_analytics(self.db)['events']
        self.assertEqual(events['total']['events'], 1)
        self.assertEqual(events['by_name'][0]['label'], 'remote · portfolio: contact_click')
        self.assertEqual(events['recent'][0]['event_target'], 'email')
        self.assertEqual(events['recent'][0]['country_code'], 'US')

    def test_event_row_holds_no_ip_user_agent_or_coordinates(self):
        record_portfolio_event(self.db, {
            'session_id': 's', 'path': '/', 'event': 'scroll_75'}, '203.0.113.7')
        with closing(sqlite3.connect(self.db)) as connection:
            columns = {row[1] for row in connection.execute(
                'PRAGMA table_info(portfolio_events)')}
        self.assertFalse(columns & {'ip_address', 'ip_prefix', 'user_agent',
                                    'latitude', 'longitude'})

    def test_rejects_unknown_event_and_event_from_the_wrong_site(self):
        with self.assertRaises(ValueError):
            record_portfolio_event(self.db, {
                'session_id': 's', 'path': '/', 'event': 'keystroke'}, '203.0.113.1')
        with self.assertRaises(ValueError):
            record_portfolio_event(self.db, {
                'session_id': 's', 'path': '/', 'event': 'tab_view'},
                '203.0.113.1', site='portfolio')
        record_portfolio_event(self.db, {
            'session_id': 's', 'path': '/gdp', 'event': 'tab_view',
            'target': '/gdp · 中国省级'}, '203.0.113.1', site='research')
        self.assertEqual(
            build_portfolio_analytics(self.db)['events']['total']['events'], 1)

    def test_outbound_click_keeps_host_and_path_but_drops_query(self):
        record_portfolio_event(self.db, {
            'session_id': 's', 'path': '/', 'event': 'outbound_click',
            'target': 'https://github.com/Zenith1874/CS509-Fall2023?utm_source=cv#readme',
        }, '203.0.113.1')
        recent = build_portfolio_analytics(self.db)['events']['recent'][0]
        self.assertEqual(recent['event_target'], 'github.com/Zenith1874/CS509-Fall2023')

    def test_deduplicates_identical_event_for_thirty_minutes(self):
        payload = {'session_id': 'same', 'path': '/', 'event': 'scroll_75'}
        self.assertTrue(record_portfolio_event(self.db, payload, '203.0.113.2')['recorded'])
        self.assertFalse(record_portfolio_event(self.db, payload, '203.0.113.2')['recorded'])
        payload_other = dict(payload, event='contact_click')
        self.assertTrue(record_portfolio_event(self.db, payload_other, '203.0.113.2')['recorded'])
        self.assertEqual(
            build_portfolio_analytics(self.db)['events']['total']['events'], 2)

    def test_dwell_summary_reports_median_and_mean(self):
        for index, seconds in enumerate((5, 40, 600)):
            record_portfolio_event(self.db, {
                'session_id': f'session-{index}', 'path': f'/p{index}',
                'event': 'session_end', 'dwell_seconds': seconds}, '203.0.113.3')
        dwell = build_portfolio_analytics(self.db)['events']['dwell']
        self.assertEqual(dwell['sessions'], 3)
        self.assertEqual(dwell['median_seconds'], 40)
        self.assertEqual(dwell['mean_seconds'], 215.0)

    def test_event_deduplication_keeps_path_visitor_and_scope_separate(self):
        payload = {'session_id': 'same', 'path': '/first', 'event': 'outbound_click',
                   'target': 'https://example.org/paper?private=query#secret'}
        for path, ip, scope in (('/first', '203.0.113.1', 'remote'),
                                ('/second', '203.0.113.1', 'remote'),
                                ('/second', '203.0.113.2', 'remote'),
                                ('/second', '203.0.113.2', 'automation')):
            self.assertTrue(record_portfolio_event(
                self.db, dict(payload, path=path), ip, site='research', scope=scope)['recorded'])
        self.assertFalse(record_portfolio_event(
            self.db, payload, '203.0.113.1', site='research')['recorded'])

    def test_behavior_checkpoints_use_maximum_per_page_load_and_hide_keys(self):
        payload = {'session_id': 'tab-1', 'path': '/housing', 'event': 'engagement',
                   'page_id': 'random-load-0001'}
        for seconds in (15, 30, 40):
            self.assertTrue(record_portfolio_event(self.db, dict(payload, dwell_seconds=seconds),
                                                  '203.0.113.1', site='research')['recorded'])
        for seconds in (15, 40):
            self.assertFalse(record_portfolio_event(self.db, dict(payload, dwell_seconds=seconds),
                                                   '203.0.113.1', site='research')['recorded'])
        record_portfolio_event(self.db, dict(payload, page_id='random-load-0002', dwell_seconds=10),
                               '203.0.113.1', site='research')
        record_portfolio_event(self.db, dict(payload, page_id='random-load-0003', dwell_seconds=60),
                               '127.0.0.1', site='research', scope='local')
        record_portfolio_event(self.db, dict(payload, page_id='random-load-0004', dwell_seconds=90),
                               '203.0.113.2', site='portfolio')
        record_portfolio_event(self.db, {'session_id': 'legacy', 'path': '/housing',
                                        'event': 'session_end', 'dwell_seconds': 500},
                               '203.0.113.1', site='research')
        result = build_portfolio_analytics(self.db, days=30, site='research', view='visitor')
        self.assertEqual(result['events']['behavior']['foreground'], {
            'samples': 2, 'mean_seconds': 25.0, 'median_seconds': 25.0, 'over_30_seconds': 1})
        self.assertEqual(result['events']['dwell']['median_seconds'], 500)
        self.assertNotIn('foreground-v1:', str(result))
        self.assertNotIn('random-load-', str(result))
        diagnostic = build_portfolio_analytics(self.db, days=30, site='research', view='diagnostics')
        self.assertEqual(diagnostic['events']['behavior']['foreground']['samples'], 3)
        self.assertEqual(diagnostic['events']['behavior']['foreground']['median_seconds'], 40)
        self.assertNotIn('foreground-v1:', str(diagnostic))
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM portfolio_events WHERE event_name='engagement'").fetchone()[0], 6)

    def test_behavior_whitelist_and_navigation_query_minimization(self):
        base = {'session_id': 's', 'path': '/housing'}
        for depth in ('25', '50', '75', '90'):
            record_portfolio_event(self.db, dict(base, event='scroll_depth', target=depth),
                                   '203.0.113.1', site='research')
        record_portfolio_event(self.db, dict(base, event='internal_navigation',
                                           target='/gdp?search=private#secret'),
                               '203.0.113.1', site='research')
        for values in ({'event': 'scroll_depth', 'target': 'private text'},
                       {'event': 'internal_navigation', 'target': '//evil.org/x'},
                       {'event': 'internal_navigation', 'target': '/\\evil.org/x'},
                       {'event': 'engagement', 'page_id': 'too short', 'dwell_seconds': 10},
                       {'event': 'engagement', 'page_id': 'random-load-1', 'dwell_seconds': -1},
                       {'event': 'engagement', 'page_id': 'random-load-1', 'dwell_seconds': float('inf')}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                record_portfolio_event(self.db, dict(base, **values), '203.0.113.1', site='research')
        result = build_portfolio_analytics(self.db, days=30, view='visitor')
        self.assertEqual([x['label'] for x in result['events']['behavior']['scroll_depth']],
                         ['25', '50', '75', '90'])
        self.assertEqual(result['events']['behavior']['navigation'][0]['label'], '/housing → /gdp')
        self.assertNotIn('private', str(result['events']['recent']))

    def test_behavior_uses_selected_reporting_window_and_empty_is_not_zero_duration(self):
        for timestamp, page, seconds in (('2026-09-20T05:59:59+00:00', 'page-before', 99),
                                          ('2026-09-20T06:00:00+00:00', 'page-midnight', 15)):
            with patch('services.portfolio_analytics_service.datetime', wraps=datetime) as clock:
                clock.now.return_value = datetime.fromisoformat(timestamp)
                record_portfolio_event(self.db, {'session_id': 's', 'path': '/', 'event': 'engagement',
                                                'page_id': page, 'dwell_seconds': seconds},
                                       '203.0.113.1', site='research')
        with patch('services.portfolio_analytics_service.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat('2026-09-20T15:00:00+00:00')
            result = build_portfolio_analytics(self.db, days=1, tz='America/Denver')
            self.assertEqual(result['events']['behavior']['foreground']['median_seconds'], 15)
            empty = build_portfolio_analytics(self.db, days=1, site='portfolio')
            self.assertIsNone(empty['events']['behavior']['foreground']['median_seconds'])

    def test_local_events_are_labelled_and_counted_separately(self):
        record_portfolio_event(self.db, {
            'session_id': 'owner', 'path': '/city-economy', 'event': 'tab_view',
            'target': '/city-economy · 上市公司'},
            '127.0.0.1', site='research', scope='local')
        record_portfolio_event(self.db, {
            'session_id': 'guest', 'path': '/gdp', 'event': 'page_view',
            'target': '/gdp'}, '203.0.113.8', site='research')
        events = build_portfolio_analytics(self.db)['events']
        self.assertEqual(events['total']['events'], 2)
        self.assertEqual({row['label']: row['events'] for row in events['by_scope']},
                         {'local': 1, 'remote': 1})
        self.assertEqual({row['scope'] for row in events['recent']}, {'local', 'remote'})

    def test_rejects_an_unknown_scope(self):
        with self.assertRaises(ValueError):
            record_portfolio_event(self.db, {
                'session_id': 's', 'path': '/', 'event': 'scroll_75'},
                '203.0.113.1', scope='everywhere')

    def test_accepts_the_widened_research_vocabulary(self):
        for name in ('page_view', 'tab_view', 'data_export', 'outbound_click',
                     'session_end'):
            self.assertTrue(record_portfolio_event(self.db, {
                'session_id': 's', 'path': '/housing', 'event': name,
                'target': f'target-{name}'}, '203.0.113.4', site='research')['recorded'])
        self.assertEqual(
            build_portfolio_analytics(self.db)['events']['total']['events'], 5)

    def test_scope_column_is_added_to_an_older_events_table(self):
        record_portfolio_event(self.db, {
            'session_id': 's', 'path': '/', 'event': 'scroll_75'}, '203.0.113.5')
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('ALTER TABLE portfolio_events RENAME TO old_events')
            connection.execute("""CREATE TABLE portfolio_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
                site TEXT NOT NULL, visitor_hash TEXT NOT NULL,
                session_hash TEXT NOT NULL, path TEXT NOT NULL,
                event_name TEXT NOT NULL, event_target TEXT NOT NULL DEFAULT '',
                dwell_seconds INTEGER, country_code TEXT NOT NULL DEFAULT '')""")
            connection.execute(
                "INSERT INTO portfolio_events SELECT id, occurred_at, site, "
                "visitor_hash, session_hash, path, event_name, event_target, "
                "dwell_seconds, country_code FROM old_events")
            connection.execute('DROP TABLE old_events')
            connection.commit()
        self.assertTrue(record_portfolio_event(self.db, {
            'session_id': 's2', 'path': '/', 'event': 'contact_click'},
            '203.0.113.5')['recorded'])
        events = build_portfolio_analytics(self.db)['events']
        self.assertEqual(events['total']['events'], 2)
        self.assertEqual({row['label'] for row in events['by_scope']}, {'remote'})

    def test_events_survive_a_database_created_before_the_events_table(self):
        record_portfolio_visit(self.db, {'session_id': 'v', 'path': '/'}, '203.0.113.9')
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('DROP TABLE portfolio_events')
            connection.commit()
        self.assertTrue(record_portfolio_event(self.db, {
            'session_id': 'v', 'path': '/', 'event': 'scroll_75'},
            '203.0.113.9')['recorded'])


if __name__ == '__main__':
    unittest.main()
