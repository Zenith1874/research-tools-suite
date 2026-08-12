# -*- coding: utf-8 -*-
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from services.lgfv_bond_service import (
    CANDIDATE_BOND_TYPES,
    SOURCE_TYPE,
    build_lgfv_bond_inventory_payload,
    ensure_lgfv_inventory_tables,
    fetch_bond_type_page,
    update_lgfv_bond_inventory,
)


class LgfvBondServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, 'test.db')

    def tearDown(self):
        self.tmp.cleanup()

    def test_fetch_page_maps_api_shape(self):
        session = Mock()
        response = Mock()
        response.json.return_value = {
            'data': {
                'total': 15,
                'pageTotal': 1,
                'pageNo': 1,
                'resultList': [{'bondDefinedCode': 'abc', 'bondName': '25测试MTN001'}],
            }
        }
        session.post.return_value = response
        result = fetch_bond_type_page(session, '100010', 1)
        self.assertEqual(result['total_count'], 15)
        self.assertEqual(result['page_total'], 1)
        self.assertEqual(result['rows'][0]['bondDefinedCode'], 'abc')
        response.raise_for_status.assert_called_once_with()

    def test_smoke_update_is_idempotent_and_not_official(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'data': {
                        'total': 1,
                        'pageTotal': 1,
                        'pageNo': 1,
                        'resultList': [{
                            'bondDefinedCode': 'abc',
                            'bondCode': '102500001',
                            'bondName': '25测试MTN001',
                            'bondTypeCode': '100010',
                            'bondType': '中期票据',
                            'entyFullName': '测试城市建设投资有限公司',
                            'debtRtng': 'AAA',
                            'issueStartDate': '2025-01-01',
                            'issueEndDate': '---',
                        }],
                    }
                }

        with patch('services.lgfv_bond_service.requests.post', return_value=FakeResponse()):
            first = update_lgfv_bond_inventory(
                self.db_path, bond_types=(('100010', '中期票据'),),
                request_pause=0, snapshot_date='2026-08-05')
            second = update_lgfv_bond_inventory(
                self.db_path, bond_types=(('100010', '中期票据'),),
                request_pause=0, snapshot_date='2026-08-05')
        self.assertTrue(first['success'])
        self.assertEqual(first['rows_upserted'], 1)
        self.assertTrue(second['success'])
        conn = sqlite3.connect(self.db_path)
        count = conn.execute('SELECT COUNT(*) FROM lgfv_bond_inventory').fetchone()[0]
        official = conn.execute(
            'SELECT COUNT(*) FROM fiscal_debt_observations'
        ).fetchone() if self._table_exists(conn, 'fiscal_debt_observations') else (0,)
        conn.close()
        self.assertEqual(count, 1)
        self.assertEqual(official[0], 0)
        self.assertEqual(build_lgfv_bond_inventory_payload(self.db_path)['data_status'],
                         'metadata_only')

    def test_error_keeps_progress_and_reports_failure(self):
        class BrokenSession:
            def __init__(self):
                self.headers = {}

            def post(self, *args, **kwargs):
                raise TimeoutError('timeout')

        with patch('services.lgfv_bond_service.requests.post',
                   side_effect=TimeoutError('timeout')):
            result = update_lgfv_bond_inventory(
                self.db_path, bond_types=(('100010', '中期票据'),),
                request_pause=0, snapshot_date='2026-08-05')
        self.assertFalse(result['success'])
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT status,next_page,last_error FROM lgfv_bond_inventory_progress'
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 'error')
        self.assertEqual(row[1], 1)
        self.assertIn('TimeoutError', row[2])

    @staticmethod
    def _table_exists(conn, name):
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None


if __name__ == '__main__':
    unittest.main()
