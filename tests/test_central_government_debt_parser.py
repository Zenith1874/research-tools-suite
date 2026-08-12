import unittest

from services.fiscal_debt_service import (
    _central_debt_records_from_text,
    _central_operations_records_from_text,
    _extract_central_debt_row,
)


SDDS_TEXT = '''
Central Government Revenue And Expenditure (Monthly)
Revenue 10.0 20.0
Central Government's General Public Budget Revenue 9.0 19.0
Central Government-managed Funds Revenue 1.0 1.0
Central Government's State Captial Operations Revenue 0.0 0.0
Expenditure 30.0 40.0
Central Level General Public Budget Expenditure 8.0 9.0
Central Level Government-managed Funds Expenditure 1.0 1.0
Central Level State Captial Operations Expenditure 0.0 0.0
Transfer Payments From Central Government To Local Governments 21.0 30.0
Balance -20.0 -20.0
Central Government Financing (Monthly)
Financing 5.0 6.0
Domestic Financing By Maturity 4.0 5.0
Foreign Financing By Maturity 1.0 1.0
Bonds 5.0 6.0
Domestic Currency 5.0 6.0
Foreign Currency 0.0 0.0
Domestic Creditors 4.0 5.0
External Creditors 1.0 1.0
Central Government Debt (Quarterly)
Debt 100.0
Bonds 99.0
'''


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

    def test_parses_official_monthly_operations_and_converts_billions(self):
        records = _central_operations_records_from_text(
            SDDS_TEXT, ['2026-01', '2026-02'], '2026-07-27', 'test', 'https://example.test/mof.pdf')
        values = {(row['indicator_code'], row['period']): row for row in records}
        self.assertEqual(values[('central_government_revenue_monthly', '2026-01')]['value'], 100.0)
        self.assertEqual(values[('central_government_expenditure_monthly', '2026-02')]['value'], 400.0)
        self.assertEqual(values[('central_government_financing_monthly', '2026-01')]['value'], 50.0)
        self.assertEqual(values[('central_government_bond_financing_monthly', '2026-02')]['value'], 60.0)
        self.assertEqual(values[('central_government_revenue_monthly', '2026-01')]['unit_raw'], '十亿元')
        self.assertEqual(values[('central_government_revenue_monthly', '2026-01')]['data_status'], 'official')
        self.assertEqual(values[('central_government_revenue_monthly', '2026-01')]['source_url'], 'https://example.test/mof.pdf')

    def test_parses_quarterly_debt_from_same_sdds_text(self):
        records = _central_debt_records_from_text(
            SDDS_TEXT, ['2026-03'], '2026-07-27', 'test', 'https://example.test/mof.pdf')
        values = {row['indicator_code']: row['value'] for row in records}
        self.assertEqual(values['central_government_debt_balance'], 1000.0)
        self.assertEqual(values['central_government_bond_balance'], 990.0)


if __name__ == '__main__':
    unittest.main()
