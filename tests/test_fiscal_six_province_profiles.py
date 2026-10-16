"""Guard the exact years, currency scale, scope columns and source exceptions."""
import hashlib
import json
import unittest
from pathlib import Path

from services.fiscal_source_authority import (
    APPROVED_VISUAL_FILINGS, official_fiscal_download_url, reviewed_issuer_fiscal_source)
from services.provincial_fiscal_report_profiles import parse_provincial_fiscal_annex_pages
from services.provincial_fiscal_six_profiles import (
    SIX_VISUAL_PROFILES, parse_six_province_text_pages)
from services.provincial_issuer_visual_profiles import parse_provincial_issuer_visual_pages

ROOT = Path(__file__).resolve().parents[1]


def shandong_pages():
    return {
        1: '2026年山东省地方政府再融资专项债券（四十期）信息披露文件',
        4: ('表3 2023—2025年山东省（含青岛市）财政收支情况（亿元）\n'
            '2023年 2024年 2025年\n全省 省本级 全省 省本级 全省 省本级\n'
            '一般公共预算支出 12581.74 1033.89 13077.19 1131.56 1317.82 1150.06\n'
            '政府性基金收入 4925.37 93.83 4832.12 84.99 4254.49 93.66\n'
            '政府性基金支出 9790.27 182.51 9238.97 455.66 8799.80 266.63'),
        5: ('国有土地使用权出让收入 4156.13 35.23 3972.53 10.74 3258.36 26.29\n'
            '2025年底地方政府债务余额 38543.75\n2025年底地方政府债务限额 40118.60\n'
            '注：2023年、2024年、2025年数据均为决算数'),
        8: '山东省财政厅2026年9月29日',
    }


def heilongjiang_pages():
    return {
        1: '2025年黑龙江省和省本级财政决算 2026年10月',
        10: ('截至2025年底，全省政府债务限额为11407.4亿元，其中一般债务6025.4亿元、专项债务5382亿元；'
             '全省政府债务余额10819.5亿元，其中一般债务5953.2亿元、专项债务4866.3亿元。'
             '省本级政府债务限额为1689.1亿元，省本级政府债务余额1187.3亿元。'),
        23: ('2.1 2025年黑龙江省财政收支决算总表\n单位：万元\n'
             '预算科目 2024年决算数 2025年决算数 比上年（同比）+-%\n'
             '政府性基金预算收入 1671989 1808838 8.2\n'
             '政府性基金预算支出 5378590 11485305 113.5'),
        27: ('2.3 2025年黑龙江省一般公共预算收入决算表\n单位：万元\n'
             '预算数 调整预算数 决算数 完成调整预算数的% 比上年（同比）+-%\n'
             '一、税收收入 9427710 9438559 8597448 91.1 -1.4'),
        79: ('2.10 2025年黑龙江省政府性基金预算收支总表\n单位：万元\n'
             '项目 决算数 项目 决算数\n政府性基金收入 1808838 政府性基金支出 11485305\n'
             '债务收入 10325504 债务还本支出 6401890\n收入总计 22913431 支出总计 22913431'),
        80: ('2.11 2025年黑龙江省政府性基金预算收入决算表\n单位：万元\n'
             '项目 预算数 决算数 完成预算数的% 比上年（同比）+-%\n'
             '三、国有土地使用权出让收入 2936476 1080025 36.8 0.3'),
        99: ('2.21 2025年黑龙江省地方政府债务限额和余额情况表（分地区）\n单位：万元\n'
             '一般债务 专项债务\n2024年末余额 2025年限额 2025年末余额 2024年末余额 2025年限额 2025年末余额\n'
             '全省 56329519 60254302 59532156 39945976 53819762 48663257\n'
             '省本级 6978147 7527723 7390944 4104186 9363112 4482544'),
    }


class FiscalSixProvinceProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.visual = json.loads((ROOT/'data/province_fiscal_six_visual_declarations_20261015.json').read_text(encoding='utf8'))['documents']
        cls.text = json.loads((ROOT/'data/province_fiscal_six_text_review_20261015.json').read_text(encoding='utf8'))['documents']

    def source(self, province):
        return next(s for s in self.visual if s['region_name'] == province)

    def parse(self, source, year, pages=None):
        return parse_provincial_issuer_visual_pages(
            pages if pages is not None else {int(n): t for n, t in source['transcript_texts'].items()},
            source['region_name'], year, source['profile'])

    def test_all_visual_inspected_values_and_29_selected_observations(self):
        self.assertEqual(sum(len(p['import_codes']) for s in self.visual for p in s['periods'].values()), 29)
        for source in self.visual:
            for year, expected in source['periods'].items():
                with self.subTest(source=source['id'], year=year):
                    rows = self.parse(source, year)
                    self.assertEqual({r['indicator_code']: r['value'] for r in rows}, expected['expected_values'])
                    self.assertTrue(all(r['government_scope']=='province_total' and r['unit']=='亿元'
                                        and r['parse_mode']=='reviewed_visual_transcript' for r in rows))

    def test_visual_actual_years_and_exact_page_sets(self):
        for source in self.visual:
            year = next(iter(source['periods']))
            pages = {int(n): t for n, t in source['transcript_texts'].items()}
            for bad in ({**pages, 100: 'extra'}, {n: t for n, t in pages.items() if n != 1}):
                with self.assertRaises(ValueError): self.parse(source, year, bad)
            with self.assertRaises(ValueError): self.parse(source, '2026')
            with self.assertRaises(ValueError): parse_provincial_issuer_visual_pages(pages, '浙江', year, source['profile'])

    def test_visual_currency_columns_issuer_signatures_and_vintage_notes(self):
        for source in self.visual:
            year = next(iter(source['periods']))
            spec = SIX_VISUAL_PROFILES[source['profile']]
            for old, new in [('亿元', '万元'), ('省本级 全省', '全省 省本级'),
                             (spec['issuer'], '评级公司'), (spec['signature_date'], '2026年1月1日')]:
                pages = {int(n): t.replace(old, new) for n, t in source['transcript_texts'].items()}
                with self.subTest(source=source['id'], old=old), self.assertRaises(ValueError):
                    self.parse(source, year, pages)

    def test_henan_negative_own_spending_and_government_level_debt_are_not_imported(self):
        source = self.source('河南')
        rows = self.parse(source, '2024')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}['gov_fund_expenditure'], 3689.4)
        debt = {r['indicator_code']:r for r in self.parse(source, '2025')}
        self.assertEqual(debt['general_debt_outstanding']['value'], 6874)
        self.assertEqual(debt['general_debt_outstanding']['data_status'], 'official')
        self.assertEqual(debt['gov_fund_revenue']['data_status'], 'official_preliminary')
        pages = {int(n):t.replace('18010.3亿元），', '19010.3亿元），') for n,t in source['transcript_texts'].items()}
        with self.assertRaises(ValueError): self.parse(source, '2025', pages)

    def test_guangdong_blank_land_cells_are_positioned_and_vintages_differ(self):
        source = self.source('广东')
        values = {r['indicator_code']:r for r in self.parse(source, '2025')}
        self.assertEqual(values['land_transfer_revenue']['value'], 2415.81)
        self.assertEqual(values['land_transfer_revenue']['data_status'], 'official_preliminary')
        self.assertEqual(values['debt_outstanding']['value'], 41459.48)
        self.assertEqual(values['debt_outstanding']['data_status'], 'official_final')
        for old, new in [('— ', ''), ('— ', '0 '), ('均包含深圳', '不含深圳'),
                         ('数据为执行数', '数据为决算数')]:
            pages = {int(n):t.replace(old,new) for n,t in source['transcript_texts'].items()}
            with self.assertRaises(ValueError): self.parse(source, '2025', pages)

    def test_older_heilongjiang_visual_profile_cannot_override_2025_final_book(self):
        with self.assertRaises(ValueError): self.parse(self.source('黑龙江'), '2025')

    def test_visual_authority_is_bound_to_exact_raw_transcript_page_year_and_status(self):
        for source in self.visual:
            policy = APPROVED_VISUAL_FILINGS[source['source_url']]
            transcript = hashlib.sha256(json.dumps(source['transcript_texts'], ensure_ascii=False,
                                                   sort_keys=True, separators=(',',':')).encode()).hexdigest()
            self.assertEqual(transcript, policy['transcript_sha256'])
            for year in source['periods']:
                for row in self.parse(source, year):
                    row.update(source_name=source['source_name'], source_title=source['source_title'],
                               source_url=source['source_url']+'#page='+str(row['evidence_page']),
                               parser_notes='access_type=official_platform_document; raw_sha256='+source['raw_sha256']+
                               '; visual_transcript_sha256='+transcript+'; parse_mode=reviewed_visual_transcript; unit_evidence=explicit_source_heading')
                    self.assertTrue(reviewed_issuer_fiscal_source(row))
                    for field, value in [('source_url',source['source_url']+'#page=999'),('source_title','Credit rating'),
                                         ('parser_notes','wrong hashes'),('period','2026'),('data_status','scenario')]:
                        self.assertFalse(reviewed_issuer_fiscal_source({**row,field:value}))

    def test_shandong_full_first_columns_include_qingdao_and_exclude_printed_spending_anomaly(self):
        source = next(s for s in self.text if s['region_name']=='山东')
        for year, expected in source['periods'].items():
            rows = parse_provincial_fiscal_annex_pages(shandong_pages(),'山东',year,source['profile'])
            self.assertEqual({r['indicator_code']:r['value'] for r in rows}, expected['expected_values'])
            self.assertNotIn('general_budget_expenditure', {r['indicator_code'] for r in rows})

    def test_shandong_rejects_scope_unit_identity_vintage_and_incomplete_cells(self):
        for page, old, new in [(4,'含青岛市','不含青岛市'),(4,'亿元','万元'),
                               (4,'全省 省本级','省本级 全省'),(4,'4832.12','—'),
                               (5,'均为决算数','均为预算数'),(8,'9月29日','9月28日')]:
            pages = shandong_pages(); pages[page] = pages[page].replace(old,new)
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_six_province_text_pages(pages,'山东','2025','shandong_2026_issuer_text')

    def test_shandong_text_authority_requires_normalized_method_and_exact_source(self):
        source = next(s for s in self.text if s['region_name']=='山东')
        for row in parse_six_province_text_pages(shandong_pages(),'山东','2025',source['profile']):
            row.update(source_name=source['source_name'], source_title=source['source_title'],
                       source_url=source['source_url']+'#page='+str(row['evidence_page']),
                       parser_notes='access_type=official_platform_document; raw_sha256='+source['raw_sha256']+
                       '; parse_mode=reviewed_text_layer; unit_evidence=explicit_source_heading')
            self.assertTrue(reviewed_issuer_fiscal_source(row))
            for field, value in [('source_url',source['source_url'].replace('3a8e','3a8f')),
                                 ('data_status','official_preliminary'),('region_name','青岛'),('parser_notes','no proof')]:
                self.assertFalse(reviewed_issuer_fiscal_source({**row,field:value}))

    def test_heilongjiang_final_wanyuan_scale_actual_columns_and_18_text_additions(self):
        self.assertEqual(sum(len(p['import_codes']) for s in self.text for p in s['periods'].values()),18)
        source = next(s for s in self.text if s['region_name']=='黑龙江')
        for year, expected in source['periods'].items():
            rows = parse_provincial_fiscal_annex_pages(heilongjiang_pages(),'黑龙江',year,source['profile'])
            self.assertEqual({r['indicator_code']:r['value'] for r in rows},expected['expected_values'])
        rows = parse_six_province_text_pages(heilongjiang_pages(),'黑龙江','2025',source['profile'])
        values = {r['indicator_code']:r['value'] for r in rows}
        self.assertEqual(values['land_transfer_revenue'],108.0025)
        self.assertNotEqual(values['land_transfer_revenue'],293.6476)
        self.assertEqual(values['tax_revenue'],859.7448)
        self.assertNotEqual(values['debt_outstanding'],values['general_debt_outstanding']+values['special_debt_outstanding'])
        self.assertNotIn('principal_repayment',values)
        self.assertNotIn('interest_expenditure',values)

    def test_heilongjiang_unit_actual_vintage_scope_and_stock_headers_fail_closed(self):
        for page, old, new in [(23,'单位：万元','单位：亿元'),(23,'2024年决算数','2024年预算数'),
                               (27,'预算数 调整预算数 决算数','预算数 决算数 调整预算数'),
                               (80,'预算数 决算数','决算数 预算数'),(99,'全省 56329519','省本级 56329519'),
                               (99,'2025年末余额','2025年限额'),(10,'省本级政府债务限额','本级限额')]:
            pages = heilongjiang_pages();pages[page] = pages[page].replace(old,new)
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_six_province_text_pages(pages,'黑龙江','2025','heilongjiang_2025_final_book')

    def test_heilongjiang_summary_crosscheck_and_missing_cells_do_not_become_zero(self):
        for page,old,new in [(79,'收入 1808838','收入 1808839'),(23,'1808838','—'),
                             (99,'59532156','69532156'),(80,'1080025','2080025')]:
            pages = heilongjiang_pages();pages[page] = pages[page].replace(old,new)
            with self.subTest(old=old), self.assertRaises(ValueError):
                parse_six_province_text_pages(pages,'黑龙江','2025','heilongjiang_2025_final_book')

    def test_text_parsers_reject_future_years_wrong_province_and_extra_repayment_pages(self):
        pages = heilongjiang_pages()
        for province,year,bad in [('黑龙江','2026',pages),('浙江','2025',pages),
                                  ('黑龙江','2025',{**pages,101:'repayment components are unresolved'})]:
            with self.assertRaises(ValueError):
                parse_six_province_text_pages(bad,province,year,'heilongjiang_2025_final_book')

    def test_excluding_ningbo_annex_is_acquisition_only_not_observation_authority(self):
        url = 'https://www.governbond.org.cn/uploadFiles/33/attachFiles/202609/56d2cb39-74f1-435e-9aa0-b857cdb397c6.pdf'
        self.assertTrue(official_fiscal_download_url(url,'official_platform_document'))
        self.assertFalse(reviewed_issuer_fiscal_source({'source_url':url+'#page=2','region_name':'浙江',
                         'period':'2025','indicator_code':'gov_fund_revenue','value':5334.65,'data_status':'official_final'}))
        self.assertFalse(official_fiscal_download_url(url.replace('56d2','66d2'),'official_platform_document'))
        self.assertFalse(official_fiscal_download_url(url,'government_website'))


if __name__ == '__main__':
    unittest.main()
