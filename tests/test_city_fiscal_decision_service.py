# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest

from services.city_fiscal_decision_service import (
    VERIFIED_OFFICIAL_ROWS,
    update_city_fiscal_decisions,
)


class CityFiscalDecisionTests(unittest.TestCase):
    def test_all_rows_are_city_total_and_source_backed(self):
        self.assertTrue(VERIFIED_OFFICIAL_ROWS)
        for row in VERIFIED_OFFICIAL_ROWS:
            self.assertEqual(row['government_scope'], 'city_total')
            self.assertTrue(row['source_url'].startswith('https://'))
            self.assertIn(row['data_status'], ('official', 'official_preliminary'))
            self.assertGreater(row['value'], 0)

    def test_verified_2024_anchors(self):
        values = {(row['region_name'], row['period'], row['indicator_code']): row['value']
                  for row in VERIFIED_OFFICIAL_ROWS}
        self.assertEqual(values[('北京', '2024', 'gov_fund_revenue')], 2094.8526)
        self.assertEqual(values[('北京', '2024', 'land_transfer_revenue')], 1920.5376)
        self.assertEqual(values[('南京', '2024', 'land_transfer_revenue')], 840.0334)
        self.assertEqual(values[('广州', '2024', 'debt_outstanding')], 6482.8)
        self.assertEqual(values[('苏州', '2024', 'gov_fund_revenue')], 1048.0795)
        self.assertEqual(values[('无锡', '2024', 'debt_outstanding')], 2609.72)
        self.assertEqual(values[('无锡', '2024', 'gov_fund_revenue')], 799.3)
        self.assertEqual(values[('深圳', '2024', 'gov_fund_revenue')], 475.0)
        self.assertEqual(values[('武汉', '2024', 'land_transfer_revenue')], 1224.7129)
        self.assertEqual(values[('福州', '2024', 'debt_outstanding')], 2760.74)
        self.assertEqual(values[('杭州', '2024', 'special_debt_outstanding')], 3148.291)
        self.assertEqual(values[('长沙', '2024', 'debt_outstanding')], 3211.59)
        self.assertEqual(values[('成都', '2024', 'debt_outstanding')], 6206.6)
        self.assertEqual(values[('广州', '2024', 'land_transfer_revenue')], 1087.1)
        self.assertEqual(values[('合肥', '2024', 'tax_revenue')], 675.21)
        self.assertEqual(values[('厦门', '2024', 'gov_fund_revenue')], 423.7)
        self.assertEqual(values[('厦门', '2024', 'gov_fund_expenditure')], 868.6)
        self.assertEqual(values[('厦门', '2024', 'debt_outstanding')], 2639.7)
        self.assertEqual(values[('厦门', '2024', 'special_debt_outstanding')], 2222.0)
        self.assertEqual(values[('常州', '2023', 'gov_fund_revenue')], 1396.2)
        self.assertEqual(values[('常州', '2024', 'gov_fund_expenditure')], 1023.2)
        self.assertEqual(values[('常州', '2024', 'general_budget_expenditure')], 890.0)

    def test_historical_fund_and_land_anchors(self):
        values = {(row['region_name'], row['period'], row['indicator_code']): row['value']
                  for row in VERIFIED_OFFICIAL_ROWS}
        self.assertEqual(values[('北京', '2021', 'gov_fund_revenue')], 2705.7)
        self.assertEqual(values[('北京', '2022', 'land_transfer_revenue')], 2100.7854)
        self.assertEqual(values[('上海', '2020', 'gov_fund_revenue')], 3175.0)
        self.assertEqual(values[('上海', '2025', 'gov_fund_expenditure')], 4005.1)
        self.assertEqual(values[('常州', '2020', 'gov_fund_revenue')], 1161.7)
        self.assertEqual(values[('常州', '2025', 'gov_fund_revenue')], 413.7)
        self.assertEqual(values[('苏州', '2022', 'gov_fund_revenue')], 1735.6769)
        self.assertEqual(values[('苏州', '2023', 'land_transfer_revenue')], 1284.8598)
        self.assertEqual(values[('无锡', '2021', 'land_transfer_revenue')], 1194.2)
        self.assertEqual(values[('成都', '2023', 'gov_fund_revenue')], 1886.6)

    def test_manifest_keys_are_unique_and_land_does_not_exceed_fund_total(self):
        keys = [(row['country_code'], row['government_scope'], row['region_code'],
                 row['indicator_code'], row['period'])
                for row in VERIFIED_OFFICIAL_ROWS]
        self.assertEqual(len(keys), len(set(keys)))
        values = {(row['region_name'], row['period'], row['indicator_code']): row['value']
                  for row in VERIFIED_OFFICIAL_ROWS}
        for city, period, code in values:
            if code != 'land_transfer_revenue':
                continue
            fund = values.get((city, period, 'gov_fund_revenue'))
            if fund is not None:
                self.assertLessEqual(values[(city, period, code)], fund,
                                     f'{city} {period} 卖地收入不得超过基金收入总额')

    def test_new_city_rows_keep_explicit_provenance(self):
        rows = {(row['region_name'], row['indicator_code']): row
                for row in VERIFIED_OFFICIAL_ROWS}
        self.assertEqual(rows[('武汉', 'land_transfer_revenue')]['source_url'],
                         'https://czj.wuhan.gov.cn/FBJD/XXGKML/CZGK/CZYJS/202509/P020250915363469148977.pdf')
        self.assertEqual(rows[('长沙', 'debt_outstanding')]['source_name'],
                         '湖南省财政厅（长沙市财政局提供）')
        self.assertEqual(rows[('成都', 'debt_outstanding')]['data_status'],
                         'official_preliminary')

    def test_import_is_idempotent(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        path = handle.name
        handle.close()
        try:
            first = update_city_fiscal_decisions(path)
            second = update_city_fiscal_decisions(path)
            self.assertEqual(first['new_rows'], len(VERIFIED_OFFICIAL_ROWS))
            self.assertEqual(second['new_rows'], 0)
            conn = sqlite3.connect(path)
            self.assertEqual(conn.execute(
                'SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0],
                len(VERIFIED_OFFICIAL_ROWS))
            conn.close()
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
