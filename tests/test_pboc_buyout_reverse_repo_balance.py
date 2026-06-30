import unittest

from services.pboc_buyout_reverse_repo_service import calculate_outstanding_at


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


if __name__ == '__main__':
    unittest.main()
