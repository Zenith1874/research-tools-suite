# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.lgfv_bond_market_service import (
    build_lgfv_market_payload,
    ensure_lgfv_market_tables,
    fetch_notice_page,
    fetch_bond_detail,
    frequency_months,
    infer_notice_event_type,
    parse_bond_terms,
    scheduled_cashflows,
    update_lgfv_bond_details,
    update_lgfv_bond_notices,
)
from services.lgfv_bond_service import ensure_lgfv_inventory_tables


DETAIL_PAYLOAD = {
    'data': {'bondBaseInfo': {
        'bondDefinedCode': 'abc',
        'bondCode': '102500001',
        'bondName': '25测试MTN001',
        'bondFullName': '测试城市建设投资有限公司2025年度第一期中期票据',
        'bondTypeCode': '100010',
        'bondType': '中期票据',
        'entyFullName': '测试城市建设投资有限公司',
        'issueDate': '2025-01-15',
        'mrtyDate': '2028-01-15',
        'frstValueDate': '2025-01-15',
        'frstCpnDt': '2026-01-15',
        'frstPayDt': '---',
        'plndIssueAmnt': '1,200.50',
        'issueAmnt': '1,000.25',
        'parValue': '100',
        'issuePrice': '99.8',
        'parCouponRate': '3.60',
        'couponType': '附息式固定利率',
        'couponFrqncy': '年',
        'bondPeriod': '3年',
        'ntnlPrncplAmnt': '---',
        'exerciseInfoList': [],
        'bondRisInfoList': [],
    }}
}


class LgfvBondMarketServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'test.db')
        conn = sqlite3.connect(self.db_path)
        ensure_lgfv_inventory_tables(conn)
        conn.execute('''
            INSERT INTO lgfv_bond_inventory (
                snapshot_date,source_type,bond_defined_code,bond_code,bond_name,
                bond_type_code,bond_type,issuer,source_url,raw_json,data_status,
                current_balance,current_balance_status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            '2026-08-05', 'chinamoney_lgfv_inventory', 'abc', '102500001',
            '25测试MTN001', '100010', '中期票据', '测试城市建设投资有限公司',
            'https://example.invalid/bond', '{}', 'official_metadata', None,
            'not_disclosed_in_list', '2026-08-05T00:00:00', '2026-08-05T00:00:00',
        ))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_frequency_and_schedule_are_explicitly_derived(self):
        self.assertEqual(frequency_months('每半年'), 6)
        self.assertEqual(frequency_months('每年'), 12)
        terms = parse_bond_terms(
            '2026-08-05',
            {'bond_defined_code': 'abc', 'bond_name': '25测试MTN001',
             'bond_type_code': '100010', 'bond_type': '中期票据',
             'issuer': '测试城市建设投资有限公司'},
            DETAIL_PAYLOAD,
        )
        rows = scheduled_cashflows(terms, as_of='2026-08-05')
        self.assertEqual(terms['actual_issue_amount'], 1000.25)
        self.assertEqual(terms['planned_issue_amount'], 1200.50)
        self.assertEqual(len(rows), 4)  # three coupons plus maturity principal
        self.assertEqual(rows[-1]['event_type'], 'scheduled_principal')
        self.assertAlmostEqual(rows[0]['interest_amount'], 36.009)
        self.assertEqual(rows[0]['data_status'], 'derived_schedule')

    def test_detail_update_is_idempotent_and_payload_separates_estimate(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return DETAIL_PAYLOAD

        with patch('services.lgfv_bond_market_service.requests.post',
                   return_value=FakeResponse()):
            first = update_lgfv_bond_details(
                self.db_path, request_pause=0, snapshot_date='2026-08-05')
            second = update_lgfv_bond_details(
                self.db_path, request_pause=0, snapshot_date='2026-08-05')
        self.assertTrue(first['success'])
        self.assertEqual(first['succeeded'], 1)
        self.assertTrue(second['success'])
        conn = sqlite3.connect(self.db_path)
        term_count = conn.execute('SELECT COUNT(*) FROM lgfv_bond_terms').fetchone()[0]
        cashflow_count = conn.execute('SELECT COUNT(*) FROM lgfv_bond_cashflows').fetchone()[0]
        conn.close()
        self.assertEqual(term_count, 1)
        self.assertEqual(cashflow_count, 4)
        payload = build_lgfv_market_payload(self.db_path, as_of='2026-08-05')
        self.assertEqual(payload['data_status'], 'market_estimate')
        self.assertEqual(payload['active_issue_amount_total'], 1000.25)
        self.assertEqual(payload['estimated_current_balance_upper_bound'], 1000.25)
        self.assertNotIn('official_balance', payload)

    def test_detail_fetch_retries_transient_oserror(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return DETAIL_PAYLOAD

        with patch('services.lgfv_bond_market_service.requests.post',
                   side_effect=[OSError(22, 'Invalid argument'),
                                FakeResponse()]) as post, \
             patch('services.lgfv_bond_market_service.time.sleep') as sleep:
            payload = fetch_bond_detail('abc', timeout=1, retries=1)
        self.assertEqual(payload['data']['bondBaseInfo']['bondDefinedCode'], 'abc')
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1.0)

    def test_detail_update_retries_before_recording_missing(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return DETAIL_PAYLOAD

        with patch('services.lgfv_bond_market_service.requests.post',
                   side_effect=[OSError(22, 'Invalid argument'),
                                FakeResponse()]), \
             patch('services.lgfv_bond_market_service.time.sleep'):
            result = update_lgfv_bond_details(
                self.db_path, request_pause=0, timeout=1,
                retries=1, snapshot_date='2026-08-05')
        self.assertTrue(result['success'])
        self.assertEqual(result['failed'], 0)
        conn = sqlite3.connect(self.db_path)
        self.assertEqual(
            conn.execute('SELECT detail_status FROM lgfv_bond_terms').fetchone()[0],
            'success',
        )
        self.assertEqual(
            conn.execute(
                'SELECT status FROM lgfv_bond_detail_progress'
            ).fetchone()[0],
            'done',
        )
        conn.close()

    def test_resume_join_indexes_exist(self):
        conn = sqlite3.connect(self.db_path)
        ensure_lgfv_market_tables(conn)
        index_rows = conn.execute(
            "select name from sqlite_master where type='index'"
        ).fetchall()
        names = {row[0] for row in index_rows}
        conn.close()
        self.assertIn('idx_lgfv_terms_snapshot_code', names)
        self.assertIn('idx_lgfv_inventory_snapshot_code', names)

    def test_notice_event_type_and_page_shape(self):
        self.assertEqual(infer_notice_event_type('某债券2026年付息兑付公告'),
                         'interest_and_principal_notice')
        self.assertEqual(infer_notice_event_type('某债券2026年付息公告'),
                         'interest_notice')
        session = Mock()
        response = Mock()
        response.json.return_value = {
            'data': {'total': 30, 'pageTotalSize': 1},
            'records': [{'contentId': '1', 'title': '测试债券付息公告'}],
        }
        session.post.return_value = response
        page = fetch_notice_page('100010', 1, session=session)
        self.assertEqual(page['total_count'], 30)
        self.assertEqual(page['records'][0]['contentId'], '1')
        response.raise_for_status.assert_called_once_with()

    def test_notice_update_is_idempotent(self):
        ensure = sqlite3.connect(self.db_path)
        ensure_lgfv_market_tables(ensure)
        ensure.commit()
        ensure.close()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'data': {'total': 1, 'pageTotalSize': 1},
                    'records': [{
                        'contentId': 'notice-1',
                        'title': '测试城市建设投资有限公司2026年付息公告',
                        'releaseDate': '2026-08-05',
                        'draftPath': '/chinese/fxdf/20260805/1.html',
                        'suffix': 'pdf', 'attSize': 1, 'txt': 0,
                    }],
                }

        with patch('services.lgfv_bond_market_service.requests.post',
                   return_value=FakeResponse()):
            first = update_lgfv_bond_notices(
                self.db_path, bond_types=(('100010', '中期票据'),),
                request_pause=0, snapshot_date='2026-08-05')
            second = update_lgfv_bond_notices(
                self.db_path, bond_types=(('100010', '中期票据'),),
                request_pause=0, snapshot_date='2026-08-05')
        self.assertTrue(first['success'])
        self.assertTrue(second['success'])
        conn = sqlite3.connect(self.db_path)
        count = conn.execute('SELECT COUNT(*) FROM lgfv_bond_notices').fetchone()[0]
        row = conn.execute(
            'SELECT event_type,parse_status FROM lgfv_bond_notices'
        ).fetchone()
        conn.close()
        self.assertEqual(count, 1)
        self.assertEqual(row, ('interest_notice', 'metadata_only_attachment_not_parsed'))

    def test_empty_notice_type_is_marked_done(self):
        class EmptyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {'data': {'total': 0, 'pageTotalSize': 0}, 'records': []}

        with patch('services.lgfv_bond_market_service.requests.post',
                   return_value=EmptyResponse()):
            result = update_lgfv_bond_notices(
                self.db_path, bond_types=(('100025', '集合票据'),),
                request_pause=0, snapshot_date='2026-08-05')
        self.assertTrue(result['success'])
        self.assertEqual(result['types'][0]['status'], 'done')


if __name__ == '__main__':
    unittest.main()
