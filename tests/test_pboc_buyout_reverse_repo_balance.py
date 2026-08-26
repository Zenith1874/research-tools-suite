import unittest
from unittest.mock import patch

from services.pboc_buyout_reverse_repo_service import (
    build_buyout_reverse_repo_matrix,
    build_monthly_stock,
    calculate_outstanding_at,
    parse_operation_page,
)


class BuyoutReverseRepoBalanceTests(unittest.TestCase):
    def setUp(self):
        self.operations = [
            {
                'operation_id': 'a', 'operation_date': '2026-05-01',
                'maturity_date': '2026-08-01', 'maturity_date_status': 'official',
                'amount': 3000,
            },
            {
                'operation_id': 'b', 'operation_date': '2026-05-15',
                'maturity_date': '2026-06-15', 'maturity_date_status': 'derived',
                'amount': 2000,
            },
            {
                'operation_id': 'c', 'operation_date': '2026-07-01',
                'maturity_date': '2026-10-01', 'maturity_date_status': 'official',
                'amount': 1000,
            },
        ]

    def test_sums_only_started_and_not_matured_operations(self):
        result = calculate_outstanding_at(self.operations, '2026-06-01')
        self.assertEqual(result['outstanding_amount'], 5000)
        self.assertEqual(result['operation_count'], 2)
        self.assertEqual(result['derived_maturity_count'], 1)

    def test_excludes_operation_on_its_maturity_date(self):
        result = calculate_outstanding_at(self.operations, '2026-06-15')
        self.assertEqual(result['outstanding_amount'], 3000)
        self.assertEqual([row['operation_id'] for row in result['active_operations']], ['a'])

    def test_business_announcement_is_an_official_operation_source(self):
        html = '''
        <html><head><title>公开市场买断式逆回购业务公告 [2024]第1号</title></head>
        <body>2024年10月，为保持银行体系流动性合理充裕，开展5000亿元买断式逆回购操作，
        期限为6个月（182天）5000亿元。中国人民银行公开市场业务操作室</body></html>
        '''
        item = {
            'source_url': 'https://example.test/business',
            'source_title': '公开市场买断式逆回购业务公告 [2024]第1号',
            'listed_date': '2024-10-31',
        }
        with patch('services.pboc_buyout_reverse_repo_service.fetch_html',
                   return_value=(html, item['source_url'])):
            operations, detail = parse_operation_page(item)
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]['announcement_kind'], 'business')
        self.assertEqual(operations[0]['amount'], 5000.0)
        self.assertEqual(operations[0]['operation_date'], '2024-10-31')
        self.assertEqual(operations[0]['maturity_date'], '2025-04-30')
        self.assertIn('官方', detail['parser_notes'])

    def test_monthly_bucket_keeps_business_and_tender_start_rules_distinct(self):
        rows = build_monthly_stock([
            {
                'operation_id': 'business-1', 'operation_date': '2024-10-31',
                'buy_date': '2024-10-31', 'maturity_date': '2025-04-30',
                'maturity_date_status': 'official', 'amount': 5000,
                'term_months': 6, 'term_days': 182,
                'announcement_kind': 'business', 'source_title': 'business',
                'source_url': 'https://example.test/business',
            },
            {
                'operation_id': 'tender-1', 'operation_date': '2025-06-06',
                'buy_date': '2025-06-06', 'maturity_date': '2025-09-06',
                'maturity_date_status': 'derived', 'amount': 10000,
                'term_months': 3, 'term_days': 91,
                'announcement_kind': 'tender', 'source_title': 'tender',
                'source_url': 'https://example.test/tender',
            },
        ])
        by_period = {row['period']: row for row in rows}
        self.assertEqual(by_period['2024-10']['monthly_bucket_outstanding_amount'], 0)
        self.assertEqual(by_period['2024-11']['monthly_bucket_outstanding_amount'], 5000)
        self.assertEqual(by_period['2025-04']['monthly_bucket_outstanding_amount'], 5000)
        self.assertEqual(by_period['2025-05']['monthly_bucket_outstanding_amount'], 0)
        self.assertEqual(by_period['2025-06']['monthly_bucket_outstanding_amount'], 10000)
        self.assertEqual(by_period['2025-08']['monthly_bucket_outstanding_amount'], 10000)
        self.assertEqual(by_period['2025-09']['monthly_bucket_outstanding_amount'], 0)

    def test_operation_month_matrix_keeps_bucket_and_exact_totals_separate(self):
        operations = [
            {
                'operation_id': 'business-1', 'operation_date': '2024-10-31',
                'buy_date': '2024-10-31', 'maturity_date': '2025-04-30',
                'maturity_date_status': 'official', 'amount': 5000,
                'term_months': 6, 'term_days': 182,
                'announcement_kind': 'business', 'source_title': 'business',
                'source_url': 'https://example.test/business',
                'data_status': 'official',
            },
            {
                'operation_id': 'tender-1', 'operation_date': '2025-06-06',
                'buy_date': '2025-06-06', 'maturity_date': '2025-09-06',
                'maturity_date_status': 'derived', 'amount': 10000,
                'term_months': 3, 'term_days': 91,
                'announcement_kind': 'tender', 'source_title': 'tender',
                'source_url': 'https://example.test/tender',
                'data_status': 'official',
            },
        ]
        stocks = [
            {'period': '2024-10', 'outstanding_amount': 5000},
            {'period': '2024-11', 'outstanding_amount': 5000},
            {'period': '2025-06', 'outstanding_amount': 10000},
            {'period': '2025-07', 'outstanding_amount': 10000},
            {'period': '2025-08', 'outstanding_amount': 10000},
        ]
        matrix = build_buyout_reverse_repo_matrix(operations, stocks, '2025-08')
        self.assertEqual(matrix['periods'], [
            '2024-10', '2024-11', '2024-12', '2025-01', '2025-02',
            '2025-03', '2025-04', '2025-06', '2025-07', '2025-08',
        ])
        self.assertEqual(matrix['operation_count'], 2)
        self.assertEqual(matrix['bucket_totals']['2024-10'], 0)
        self.assertEqual(matrix['bucket_totals']['2024-11'], 5000)
        self.assertEqual(matrix['bucket_totals']['2025-06'], 10000)
        self.assertEqual(matrix['exact_totals']['2024-10'], 5000)
        self.assertEqual(matrix['difference']['2024-10'], -5000)
        self.assertEqual(matrix['operations'][0]['values']['2024-11'], 5000)
        self.assertEqual(matrix['operations'][1]['values']['2025-06'], 10000)


if __name__ == '__main__':
    unittest.main()
