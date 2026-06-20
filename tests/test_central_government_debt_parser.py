import unittest

from services.fiscal_debt_service import _extract_central_debt_row


class CentralGovernmentDebtParserTests(unittest.TestCase):
    def test_extracts_exact_quarter_values_and_converts_units(self):
        values = _extract_central_debt_row(
            ['Debt 36055.7 37963.8 40007.1 41231.8'],
            'Debt',
            4,
            '2025 test',
        )
        self.assertEqual(values, [360557.0, 379638.0, 400071.0, 412318.0])

    def test_rejects_extra_values_instead_of_silently_truncating(self):
        with self.assertRaisesRegex(RuntimeError, '季度数异常'):
            _extract_central_debt_row(
                ['Debt 1 2 3 4 999'],
                'Debt',
                4,
                'bad test',
            )

    def test_does_not_match_financing_bonds_row_before_debt_table(self):
        values = _extract_central_debt_row(
            ['Domestic Debt By Maturity 1 2 3 4', 'Bonds 10 20 30 40'],
            'Bonds',
            4,
            'row test',
        )
        self.assertEqual(values, [100.0, 200.0, 300.0, 400.0])


if __name__ == '__main__':
    unittest.main()
