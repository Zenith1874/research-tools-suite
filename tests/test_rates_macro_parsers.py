import unittest
import tempfile
from pathlib import Path

from services.china_rates_service import parse_lpr_announcement_text, parse_shibor_records, parse_ccpr_records
from services.us_macro_service import (
    SERIES,
    build_us_macro_payload,
    derive_change_series,
    derive_aligned_spread,
    derive_difference_series,
    parse_fred_csv,
)


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

    def test_macro_series_cover_five_decision_groups(self):
        groups = {row[5] for row in SERIES}
        self.assertEqual(groups, {'labor', 'inflation', 'growth', 'fiscal', 'financial'})
        codes = {row[0] for row in SERIES}
        for code in ('PAYEMS', 'CPIAUCSL', 'PCEPILFE', 'GDPC1', 'INDPRO',
                     'U6RATE', 'ICSA', 'FGRECPT', 'GFDEBTN', 'DFF', 'DGS3MO', 'DGS30',
                     'T10Y2Y', 'T10Y3M', 'T10YIE', 'MORTGAGE30US'):
            self.assertIn(code, codes)

    def test_year_over_year_change_is_derived_not_official(self):
        rows = [{'period': f'2025-{month:02d}-01', 'value': 100.0}
                for month in range(1, 13)]
        rows.append({'period': '2026-01-01', 'value': 103.0})
        result = derive_change_series(rows, lag=12)
        self.assertEqual(result[-1]['value'], 3.0)
        self.assertEqual(result[-1]['data_status'], 'derived')

    def test_gdp_quarterly_change_is_annualized(self):
        rows = [{'period': '2025-10-01', 'value': 100.0},
                {'period': '2026-01-01', 'value': 101.0}]
        result = derive_change_series(rows, lag=1, annualize=True)
        self.assertAlmostEqual(result[-1]['value'], 4.0604, places=4)

    def test_payroll_monthly_change_is_level_difference(self):
        rows = [{'period': '2026-05-01', 'value': 159000.0},
                {'period': '2026-06-01', 'value': 159147.0}]
        result = derive_difference_series(rows)
        self.assertEqual(result[-1]['value'], 147.0)

    def test_aligned_fiscal_balance_uses_matching_periods(self):
        receipts = [{'period': '2026-01-01', 'value': 5800.0}]
        outlays = [{'period': '2025-10-01', 'value': 7500.0},
                   {'period': '2026-01-01', 'value': 7600.0}]
        self.assertEqual(derive_aligned_spread(receipts, outlays)[0]['value'], -1800.0)

    def test_empty_payload_keeps_five_group_contract_without_mock(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = build_us_macro_payload(str(Path(tmp) / 'macro.db'))
        self.assertEqual([group['code'] for group in payload['groups']],
                         ['labor', 'inflation', 'growth', 'fiscal', 'financial'])
        self.assertEqual(payload['data_status'], 'missing')
        self.assertTrue(all(card['data_status'] == 'missing'
                            for card in payload['cards']))


if __name__ == '__main__':
    unittest.main()
