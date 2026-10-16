"""Guard table scope, vintage and exact-source exceptions for fiscal annexes."""
import unittest

from services.provincial_fiscal_report_profiles import parse_provincial_fiscal_annex_pages
from services.fiscal_source_authority import (
    HUBEI_ANNEX_URL,HUBEI_ANNEX_SHA256,HUBEI_ANNEX_TITLE,
    official_fiscal_download_url,reviewed_issuer_fiscal_source)


def hubei_pages():
    return {1:'附件2 湖北省（区、市）经济、财政和债务有关数据 一、地方经济状况',
            2:'''二、财政收支状况（亿元） 年份 项目 2024年 2025年 2026年
            省本级 全省 省本级 全省 省本级 全省
            一般公共预算收入 168 3938 159 4211 164 4398
            一般公共预算支出 1291 9976 1320 9791 1336 9885
            地 方 政 府 一 般 债 券 收入 747 747 943 943 877 877
            （二）近三年政府性基金预算收支
            政府性基金收入 66 2880 55 2860 51 2892
            政府性基金支出 203 4483 253 4950 124 4876
            地 方 政 府 专 项 债 券 收入 3385 3385 3551 3551 2992 2992
            三、地方政府债务状况（亿元）截至2025年底地方政府债务余额 21621
            2024年地方政府债务限额21373
            2025年地方政府债务限额23397
            注：财政收支情况中，2024年数据为决算数，2025年和2026年数据来源于《湖北省2025年预算执行情况和2026年预算（草案）》。
            六项数据不包含债券收支数和转移性收支数。'''}


def zhejiang_pages():
    return {1:'关于2024年全省和省级预算执行情况及2025年全省和省级预算草案的报告 2025年1月14日 浙江省财政厅 一、2024年预算执行情况',
            2:'''（一）2024年预算收支执行情况1.一般公共预算执行情况（1）全省
            2024年全省一般公共预算收入8705.61亿元，其中，税收收入6993.71亿元。收入合计14835.95亿元。
            全省一般公共预算支出12564.61亿元。（2）省级 收入355.67亿元。''',
            3:'''2.政府性基金预算执行情况（1）全省 2024年全省政府性基金预算收入6168.85亿元。
            收入合计13521.38亿元。全省政府性基金预算支出9095.76亿元。
            （2）省级2024年省级政府性基金预算收入62.10亿元，省级政府性基金预算支出107.43亿元。
            2025年全省政府性基金预算收入预期5819.08亿元。'''}


class ProvincialFiscalAnnexProfileTests(unittest.TestCase):
    def parse(self,pages,province='湖北',year='2025'):
        return parse_provincial_fiscal_annex_pages(pages,province,year,
                   'hubei_2026_fiscal_annex' if province=='湖北' else 'zhejiang_2024_execution_pdf')

    def test_hubei_uses_full_province_actual_columns_not_own_or_budget(self):
        for year,revenue,spending,status in [('2024',2880,4483,'official_final'),('2025',2860,4950,'official_preliminary')]:
            rows=self.parse(hubei_pages(),year=year);values={r['indicator_code']:r['value'] for r in rows}
            self.assertEqual(values['gov_fund_revenue'],revenue);self.assertEqual(values['gov_fund_expenditure'],spending)
            self.assertTrue(all(r['data_status']==status and r['evidence_page']==2 for r in rows))
            self.assertNotIn('land_transfer_revenue',values);self.assertNotIn('principal_repayment',values)
            if year=='2025':self.assertEqual(values['debt_outstanding'],21621)
            else:self.assertNotIn('debt_outstanding',values)

    def test_hubei_rejects_shifted_extra_missing_or_zero_filled_cells(self):
        for old,new in [('省本级 全省','全省 省本级'),('55 2860','0 55 2860'),('55 2860','55 -'),
                        ('二、财政收支状况（亿元）','二、财政收支状况（万元）'),
                        ('2024年数据为决算数','2024年数据为预算数'),
                        ('六项数据不包含债券收支数和转移性收支数','六项数据包含债券收支数'),
                        ('截至2025年底地方政府债务余额','截至2026年底地方政府债务余额'),
                        ('余额 21621','余额 0 21621')]:
            pages=hubei_pages();pages[2]=pages[2].replace(old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):self.parse(pages)

    def test_hubei_identity_pages_and_2026_budget_are_rejected(self):
        with self.assertRaises(ValueError):self.parse(hubei_pages(),year='2026')
        for pages in ({2:hubei_pages()[2]}, {**hubei_pages(),3:'unreviewed'},
                      {**hubei_pages(),1:hubei_pages()[1].replace('湖北省','河南省')}):
            with self.assertRaises(ValueError):self.parse(pages)

    def test_zhejiang_actual_fund_values_not_totals_own_or_next_year(self):
        rows=self.parse(zhejiang_pages(),'浙江','2024')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},
                         {'general_budget_revenue':8705.61,'tax_revenue':6993.71,'general_budget_expenditure':12564.61,
                          'gov_fund_revenue':6168.85,'gov_fund_expenditure':9095.76})
        self.assertTrue(all(r['data_status']=='official_preliminary' for r in rows))
        with self.assertRaises(ValueError):self.parse(zhejiang_pages(),'浙江','2025')

    def test_zhejiang_rejects_scope_year_units_and_report_identity(self):
        for page,old,new in [(1,'浙江省财政厅','评级公司'),(1,'2025年1月14日','2026年1月14日'),
                             (2,'税收收入6993.71','税收收入9993.71'),
                             (3,'2024年全省政府性基金预算收入','2025年全省政府性基金预算收入'),
                             (3,'6168.85亿元','6168.85万元'),(3,'（2）省级','（2）其他')]:
            pages=zhejiang_pages();pages[page]=pages[page].replace(old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):self.parse(pages,'浙江','2024')

    def test_hubei_source_policy_is_exact_not_general_exchange_access(self):
        self.assertTrue(official_fiscal_download_url(HUBEI_ANNEX_URL,'government_issuer_filing'))
        self.assertFalse(official_fiscal_download_url(HUBEI_ANNEX_URL,'government_website'))
        row={'region_code':'420000','region_name':'湖北','period':'2025','indicator_code':'gov_fund_revenue',
             'source_url':HUBEI_ANNEX_URL+'#page=2','source_title':HUBEI_ANNEX_TITLE,
             'source_name':'湖北省地方政府债券披露附件（上交所原始文件）','data_status':'official_preliminary',
             'parser_notes':'access_type=government_issuer_filing; raw_sha256='+HUBEI_ANNEX_SHA256+'; unit_evidence=explicit_source_heading'}
        self.assertTrue(reviewed_issuer_fiscal_source(row))
        for key,value in [('period','2026'),('region_name','河南'),('source_url',HUBEI_ANNEX_URL+'#page=1'),
                          ('data_status','official_final'),('indicator_code','land_transfer_revenue'),('parser_notes','unit_evidence=inferred')]:
            with self.subTest(key=key):self.assertFalse(reviewed_issuer_fiscal_source({**row,key:value}))


if __name__=='__main__':unittest.main()
