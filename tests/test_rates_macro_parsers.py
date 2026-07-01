import unittest

from services.china_rates_service import parse_lpr_records, parse_shibor_records, parse_ccpr_records
from services.us_macro_service import parse_fred_csv


class ChinaRatesParserTests(unittest.TestCase):
    def test_lpr_parses_both_tenors(self):
        rows = parse_lpr_records([{'5Y': '3.50', '1Y': '3.00', 'showDateCN': '2026-06-22'}])
        self.assertEqual(len(rows), 2)
        by_code = {r['indicator_code']: r for r in rows}
        self.assertEqual(by_code['LPR_1Y']['value'], 3.00)
        self.assertEqual(by_code['LPR_5Y']['value'], 3.50)
        self.assertEqual(by_code['LPR_1Y']['period'], '2026-06-22')

    def test_lpr_skips_bad_values_and_missing_date(self):
        rows = parse_lpr_records([
            {'5Y': 'N/A', '1Y': '', 'showDateCN': '2026-06-22'},   # 值坏 → 全跳
            {'5Y': '3.50', '1Y': '3.00'},                          # 无日期 → 跳
        ])
        self.assertEqual(rows, [])

    def test_shibor_parses_all_tenors(self):
        rec = {'ON': '1.4030', '1W': '1.4630', '2W': '1.4590', '1M': '1.4260',
               '3M': '1.4380', '6M': '1.4500', '9M': '1.4700', '1Y': '1.4800',
               'showDateCN': '2026-07-01'}
        rows = parse_shibor_records([rec])
        self.assertEqual(len(rows), 8)
        self.assertEqual({r['indicator_code'] for r in rows},
                         {f'SHIBOR_{t}' for t in ('ON', '1W', '2W', '1M', '3M', '6M', '9M', '1Y')})

    def test_ccpr_parses_first_value(self):
        rows = parse_ccpr_records([{'date': '2026-07-01', 'values': ['6.8067']}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['value'], 6.8067)
        self.assertEqual(rows[0]['indicator_code'], 'USDCNY_CENTRAL_PARITY')

    def test_ccpr_skips_empty_values(self):
        self.assertEqual(parse_ccpr_records([{'date': '2026-07-01', 'values': []}]), [])


class FredCsvParserTests(unittest.TestCase):
    def test_parses_and_skips_missing_dot(self):
        text = 'observation_date,DGS10\n2026-06-27,4.06\n2026-06-28,.\n2026-06-29,4.03\n'
        rows = parse_fred_csv(text, 'DGS10')
        self.assertEqual([r['value'] for r in rows], [4.06, 4.03])

    def test_rejects_unexpected_header(self):
        with self.assertRaises(ValueError):
            parse_fred_csv('<html>error page</html>', 'UNRATE')


if __name__ == '__main__':
    unittest.main()
