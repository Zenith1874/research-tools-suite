import unittest

from services.china_rates_service import parse_lpr_announcement_text, parse_shibor_records, parse_ccpr_records
from services.us_macro_service import parse_fred_csv


class ChinaRatesParserTests(unittest.TestCase):
    def test_lpr_announcement_parses_spaced_digits(self):
        # 官方正文数字里常夹空格："1年期LPR为 3. 0 %，5年期以上LPR为 3.5 %"
        text = '2025年5月20日贷款市场报价利率（ LPR）为：1年期LPR为 3. 0 %，5年期以上LPR为 3.5 %。'
        v1, v5 = parse_lpr_announcement_text(text)
        self.assertEqual(v1, 3.0)
        self.assertEqual(v5, 3.5)

    def test_lpr_announcement_normal_wording(self):
        v1, v5 = parse_lpr_announcement_text('1年期LPR为3.85%，5年期以上LPR为4.85%。')
        self.assertEqual((v1, v5), (3.85, 4.85))

    def test_lpr_announcement_no_match(self):
        self.assertEqual(parse_lpr_announcement_text('与利率无关的正文'), (None, None))

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
