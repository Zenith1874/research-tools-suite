# -*- coding: utf-8 -*-
"""债务限额抽取：句式取自 2026 年预算报告原文。"""
import sqlite3
import tempfile
import unittest
import os
from unittest.mock import patch

from services.debt_ceiling_service import (
    parse_budget_report, build_ceiling_payload, update_debt_ceiling,
)
from services.fiscal_debt_service import ensure_fiscal_tables

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


class WordingVariantTests(unittest.TestCase):
    """2022 年报告用"中央财政国债余额…债务限额"，且把地方年末有效限额也写了出来。"""

    REPORT_2023 = (
        '2022年末，中央财政国债余额258692.76亿元，控制在全国人大批准的债务限额267008.35亿元'
        '以内，主要是适当调减国债发行额度；地方政府债务余额350651亿元，包括一般债务余额'
        '143944.69亿元、专项债务余额206706.31亿元，控制在全国人大批准的债务限额376474.3亿元'
        '以内，主要是一些地区消化了部分存量政府债务。'
        '2023年，中央财政国债限额298608.35亿元；地方政府一般债务限额165489.22亿元、'
        '专项债务限额256185.08亿元。'
    )

    def test_older_wording_still_yields_both_limits(self):
        rows = {(r['period'], r['indicator_code']): r['value']
                for r in parse_budget_report(self.REPORT_2023, '2022', '2023')}
        self.assertEqual(rows[('2022', 'treasury_debt_limit')], 267008.35)
        self.assertEqual(rows[('2022', 'local_debt_limit_effective')], 376474.3)
        self.assertEqual(rows[('2022', 'local_debt_balance_yearend')], 350651.0)
        # 次年限额句带"中央财政"前缀，仍须归到 2023
        self.assertEqual(rows[('2023', 'treasury_debt_limit')], 298608.35)

    def test_treasury_clause_limit_is_not_taken_from_the_local_clause(self):
        """两个分句都写"债务限额"，国债那句必须取 267008.35 而非地方的 376474.3。"""
        rows = {(r['period'], r['indicator_code']): r['value']
                for r in parse_budget_report(self.REPORT_2023, '2022', '2023')}
        self.assertNotEqual(rows[('2022', 'treasury_debt_limit')],
                            rows[('2022', 'local_debt_limit_effective')])


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

    def test_amendment_limit_restores_a_real_headroom(self):
        """人大常委会追加后的专项限额写入库中，2024 年就不再是 superseded。"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE fiscal_debt_observations SET value=355185.08 "
                     "WHERE indicator_code='local_special_debt_limit'")
        conn.commit(); conn.close()
        year = build_ceiling_payload(self.db_path)['years'][0]
        self.assertEqual(year['local_limit_status'], 'as_approved')
        self.assertAlmostEqual(year['local_headroom'], 52704.08, places=2)

    def test_missing_side_yields_no_headroom(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM fiscal_debt_observations WHERE indicator_code='treasury_debt_limit'")
        conn.commit(); conn.close()
        year = build_ceiling_payload(self.db_path)['years'][0]
        self.assertEqual(year['treasury_limit_status'], 'incomplete')
        self.assertIsNone(year['treasury_headroom'])


class UpdateRetentionTests(unittest.TestCase):
    """网络或解析失败不得清掉上一轮已经核验的官方值。"""

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.db_path = handle.name
        handle.close()
        conn = sqlite3.connect(self.db_path)
        ensure_fiscal_tables(conn)
        conn.execute('''INSERT INTO fiscal_debt_observations
          (indicator_code,indicator_name,value,period,source_type,source_url,
           data_status,module_code)
          VALUES ('treasury_debt_limit','国债限额',418608.35,'2025',
                  'mof_budget_report','https://example.test/verified',
                  'official','debt_ceiling')''')
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    @patch('services.debt_ceiling_service.LIMIT_AMENDMENTS', ())
    @patch('services.debt_ceiling_service.BUDGET_REPORTS', ({
        'execution_year': '2025', 'budget_year': '2026',
        'url': 'https://example.test/fails', 'title': '失败样本报告'},))
    @patch('services.debt_ceiling_service.fetch', side_effect=RuntimeError('network down'))
    def test_failed_refresh_keeps_verified_rows(self, _fetch):
        result = update_debt_ceiling(self.db_path)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute('''SELECT value,source_url FROM fiscal_debt_observations
                              WHERE indicator_code='treasury_debt_limit'
                                AND period='2025' ''').fetchone()
        conn.close()
        self.assertEqual(row, (418608.35, 'https://example.test/verified'))
        self.assertFalse(result['success'])
        self.assertTrue(result['retained_existing_on_failure'])
        self.assertIn('network down', result['errors'][0])


class DebtResolutionPackageTests(unittest.TestCase):
    """化债方案三段性质不同，不能相加成一个"12万亿"就完事。"""

    def test_package_components_are_stored_separately(self):
        from services.debt_ceiling_service import DEBT_RESOLUTION_PACKAGE
        by_code = {row['indicator_code']: row for row in DEBT_RESOLUTION_PACKAGE}
        self.assertEqual(by_code['debt_swap_new_limit']['value'], 60000.0)
        self.assertEqual(by_code['debt_swap_special_bond_allocation']['value'], 40000.0)
        # 官方表述的"直接增加化债资源"是前两段之和，不含棚改那 2 万亿
        self.assertEqual(by_code['debt_resolution_direct_resources']['value'], 100000.0)
        self.assertEqual(
            by_code['debt_swap_new_limit']['value']
            + by_code['debt_swap_special_bond_allocation']['value'],
            by_code['debt_resolution_direct_resources']['value'])
        self.assertIn('棚改', by_code['debt_resolution_direct_resources']['note'])

    def test_hidden_debt_disclosure_reconciles_with_official_debt_ratio(self):
        """法定债务＋隐性债务再除以 GDP，须复现财政部披露的 67.5%。

        这是对三个独立抽取值（国债余额、地方债余额、隐性债务余额）的交叉验证：
        任何一个抽错，这个等式都不会成立。
        """
        from services.debt_ceiling_service import HIDDEN_DEBT_DISCLOSURES
        by_code = {row['indicator_code']: row for row in HIDDEN_DEBT_DISCLOSURES}
        hidden = by_code['hidden_debt_balance']['value']
        ratio = by_code['government_debt_to_gdp_incl_hidden']['value']
        treasury_2023 = 300325.5      # 2024 年预算报告原文
        local_2023 = 407372.9         # 同上
        gdp_2023 = 1260600.0          # 议案说明原文：126.06 万亿元
        computed = (treasury_2023 + local_2023 + hidden) / gdp_2023 * 100
        self.assertAlmostEqual(computed, ratio, places=1)

    def test_percent_indicator_is_not_stored_as_yuan(self):
        from services.debt_ceiling_service import PERCENT_INDICATORS
        self.assertIn('government_debt_to_gdp_incl_hidden', PERCENT_INDICATORS)
        self.assertNotIn('hidden_debt_balance', PERCENT_INDICATORS)


if __name__ == '__main__':
    unittest.main()
