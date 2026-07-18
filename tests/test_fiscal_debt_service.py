import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.fiscal_debt_service import (
    ensure_fiscal_tables,
    parse_local_debt_text,
    upsert_local_debt_record,
)


LOCAL_REPORT = '''
2024年12月地方政府债券发行和债务余额情况
一、全国地方政府债券发行情况
（一）当月发行情况。全国发行地方政府债券合计１，０００亿元。
（二）1-12月发行情况。全国发行新增地方政府债券４，７００亿元，
全国发行再融资债券３，３００亿元，全国发行地方政府债券合计８，０００亿元，
其中一般债券３，０００亿元、专项债券５，０００亿元。
地方政府债券平均发行期限12.5年，地方政府债券平均发行利率2.35%。
二、还本付息情况。1-12月地方政府债券到期偿还本金３，２００亿元，
发行再融资债券偿还本金２，７００亿元，安排财政资金等偿还本金５００亿元。
当月到期偿还本金100亿元。1-12月地方政府债券支付利息１，５００亿元，当月地方政府债券支付利息200亿元。
二、全国地方政府债务余额情况 2024年12月末，地方政府债务余额４７，５００亿元，
其中一般债务１６，０００亿元、专项债务３１，５００亿元，政府债券４７，０００亿元。注:
'''


class FiscalDebtParserTests(unittest.TestCase):
    def test_legacy_report_anchors_ytd_instead_of_current_month(self):
        text = '''2019年4月地方政府债券发行和债务余额情况
        2019年4月发行新增债券1093亿元，发行置换债券和再融资债券1174亿元。
        2019年1-4月全国发行地方政府债券16333亿元，按用途划分发行新增债券12940亿元，
        发行置换债券和再融资债券3393亿元。
        2019年1-4月地方政府债券平均发行期限7.8年，地方政府债券平均发行利率3.39%。
        二、全国地方政府债务余额情况 地方政府债务余额196794亿元。注:'''
        values = parse_local_debt_text(text, 'https://yss.mof.gov.cn/legacy')
        self.assertEqual(values['local_new_bond_issuance_ytd'], 12940.0)
        self.assertEqual(values['local_refinancing_bond_issuance_ytd'], 3393.0)
        self.assertEqual(values['local_bond_issuance_ytd'], 16333.0)
        self.assertEqual(values['local_bond_avg_issue_rate'], 3.39)

    def test_local_report_parses_ytd_service_and_balance_fields(self):
        values = parse_local_debt_text(LOCAL_REPORT, 'https://www.mof.gov.cn/test')
        expected = {
            'local_new_bond_issuance_ytd': 4700.0,
            'local_refinancing_bond_issuance_ytd': 3300.0,
            'official_principal_repayment_ytd': 3200.0,
            'official_interest_payment_ytd': 1500.0,
            'local_debt_balance_total': 47500.0,
            'local_general_debt_balance': 16000.0,
            'local_special_debt_balance': 31500.0,
            'local_bond_avg_issue_rate': 2.35,
            'local_bond_avg_issue_term': 12.5,
        }
        for code, value in expected.items():
            self.assertEqual(values[code], value, code)

    def test_local_report_upsert_is_idempotent(self):
        values = parse_local_debt_text(LOCAL_REPORT, 'https://www.mof.gov.cn/test')
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'debt.db')
            conn = sqlite3.connect(db)
            try:
                conn.row_factory = sqlite3.Row
                ensure_fiscal_tables(conn)
                upsert_local_debt_record(conn, values)
                count1 = conn.execute('SELECT COUNT(*) FROM fiscal_debt_observations').fetchone()[0]
                upsert_local_debt_record(conn, values)
                count2 = conn.execute('SELECT COUNT(*) FROM fiscal_debt_observations').fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count1, count2)


if __name__ == '__main__':
    unittest.main()
