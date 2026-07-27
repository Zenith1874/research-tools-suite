# -*- coding: utf-8 -*-
"""债务限额抽取：句式取自 2026 年预算报告原文。"""
import sqlite3
import tempfile
import unittest
import os

from services.debt_ceiling_service import parse_budget_report, build_ceiling_payload

REPORT_2026 = (
    '2025年年末，国债余额412317.68亿元，控制在全国人大批准的国债限额418608.35亿元以内；'
    '地方政府债务余额548230.82亿元（含用于置换存量隐性债务的地方政府债务），'
    '包括一般债务余额175120.36亿元、专项债务余额373110.46亿元，'
    '控制在全国人大批准的地方政府债务限额以内。'
    '2026年，国债限额485508.35亿元；地方政府一般债务限额188689.22亿元、'
    '专项债务限额443185.08亿元。'
)


class BudgetReportParsingTests(unittest.TestCase):
    def setUp(self):
        self.rows = {(r['period'], r['indicator_code']): r['value']
                     for r in parse_budget_report(REPORT_2026, '2025', '2026')}

    def test_execution_year_balance_and_limit(self):
        self.assertEqual(self.rows[('2025', 'treasury_debt_balance_yearend')], 412317.68)
        self.assertEqual(self.rows[('2025', 'treasury_debt_limit')], 418608.35)
        self.assertEqual(self.rows[('2025', 'local_debt_balance_yearend')], 548230.82)
        self.assertEqual(self.rows[('2025', 'local_general_debt_balance_yearend')], 175120.36)
        self.assertEqual(self.rows[('2025', 'local_special_debt_balance_yearend')], 373110.46)

    def test_budget_year_limits_are_attributed_to_the_next_year(self):
        self.assertEqual(self.rows[('2026', 'treasury_debt_limit')], 485508.35)
        self.assertEqual(self.rows[('2026', 'local_general_debt_limit')], 188689.22)
        self.assertEqual(self.rows[('2026', 'local_special_debt_limit')], 443185.08)

    def test_execution_year_limit_is_not_confused_with_next_year_limit(self):
        """两句都含"国债限额"，执行年那句必须取 418608.35 而非 485508.35。"""
        self.assertNotEqual(self.rows[('2025', 'treasury_debt_limit')],
                            self.rows[('2026', 'treasury_debt_limit')])


class HeadroomGuardTests(unittest.TestCase):
    """2024 年 11 月人大常委会追加了地方债务限额，年初限额已过时，
    此时余额会超过年初限额——绝不能呈现为负的剩余空间。"""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = handle.name
        handle.close()
        conn = sqlite3.connect(self.db_path)
        conn.execute('''CREATE TABLE fiscal_debt_observations (
          indicator_code TEXT, indicator_name TEXT, period TEXT, value REAL,
          source_url TEXT, source_title TEXT, module_code TEXT)''')
        conn.executemany(
            "INSERT INTO fiscal_debt_observations VALUES (?,?,?,?,'u','t','debt_ceiling')",
            [('local_general_debt_limit', '一般限额', '2024', 172890.0),
             ('local_special_debt_limit', '专项限额', '2024', 294980.0),
             ('local_debt_balance_yearend', '地方余额', '2024', 475371.0),
             ('treasury_debt_limit', '国债限额', '2024', 352008.35),
             ('treasury_debt_balance_yearend', '国债余额', '2024', 345724.0)])
        conn.commit(); conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_negative_headroom_is_reported_as_superseded_not_as_a_number(self):
        year = build_ceiling_payload(self.db_path)['years'][0]
        self.assertEqual(year['local_limit_status'], 'superseded')
        self.assertIsNone(year['local_headroom'])
        # 国债当年未被追加，正常给出剩余空间
        self.assertEqual(year['treasury_limit_status'], 'as_approved')
        self.assertAlmostEqual(year['treasury_headroom'], 6284.35, places=2)

    def test_missing_side_yields_no_headroom(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM fiscal_debt_observations WHERE indicator_code='treasury_debt_limit'")
        conn.commit(); conn.close()
        year = build_ceiling_payload(self.db_path)['years'][0]
        self.assertEqual(year['treasury_limit_status'], 'incomplete')
        self.assertIsNone(year['treasury_headroom'])


if __name__ == '__main__':
    unittest.main()
