"""Guard annual/full-province scope and archived fiscal report identities."""
import copy
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from services.provincial_fiscal_report_profiles import (
    parse_hunan_final_report, parse_jiangsu_gazette_pages)
from scripts.review_province_fiscal_supplement import review_documents


def hunan_html(year='2025'):
    fund_heading = '2．政府性基金预算' if year == '2025' else '（二）政府性基金预算收支决算情况'
    capital_heading = '3．国有资本经营预算' if year == '2025' else '（三）国有资本经营预算收支决算情况'
    debts = {'2023': '（五）地方政府债务情况2023年，全省发行新增债券1717.5亿元，年底政府债务余额18216.6亿元。',
             '2024': '（五）地方政府债务情况截至2024年底，全省政府债务余额21246.9亿元。',
             '2025': '9．地方政府债务情况。截至2025年底，全省法定债务余额24289亿元，限额25916.3亿元。'}
    return f'''<title>关于湖南省{year}年省级决算草案和{int(year)+1}年上半年预算执行情况的报告</title>
      <article>一、{year}年全省及省级财政决算情况<p>{fund_heading}</p>
      <p>{year}年，全省收入１，７９３．１亿元，加上补助452亿元，收入合计6345.6亿元；支出3468.8亿元，支出合计6345.6亿元。
      省级收入58.9亿元；支出135.3亿元。</p><p>{capital_heading}全省收入380.2亿元；支出52.1亿元。</p>
      <p>{debts[year]}</p>二、{year}年预算执行效果及落实人大决议情况
      <p>其他三本预算：政府性基金预算方面，全省收入463.7亿元，全省支出1069.8亿元。</p></article>'''


def jiangsu_pages(final=False):
    header = '江苏省人民代表大会常务委员会公报2026·5、6' if final else '江苏省人民代表大会常务委员会公报2026·2'
    if final:
        return {712: header + '关于江苏省2025年省级财政决算草案及2026年上半年预算执行情况的报告2026年7月30日一、2025年省级财政决算情况',
                713: header + '''省级政府性基金预算总收入7111.45亿元。
                （五）经批准举借政府债务情况2025年财政部核准债务限额37106.24亿元。
                2025年末，全省政府债务余额33927.54亿元，其中，一般债务8538.10亿元、专项债务25389.44亿元；
                省本级政府债务余额1261.76亿元，其中，一般债务583.41亿元、专项债务678.35亿元。（六）部门决算'''}
    return {123: header + '关于江苏省2025年预算执行情况与2026年预算草案的报告2026年2月3日一、2025年预算执行顶压前行、稳中有进',
            124: header + '''（二）政府性基金预算执行情况。全省政府性基金预算收入6472.47亿元，完成预算97.0%，
            其中国有土地使用权出让收入5588.93亿元；收入总计15448.08亿元。
            政府性基金预算支出8533.59亿元，支出总计13383.31亿元。
            省级政府性基金预算收入77.82亿元，政府性基金预算支出569.03亿元。
            年末债务余额预计为33927.54亿元。2026年预算草案政府性基金预算收入9999亿元。'''}


class ProvincialFiscalReportProfilesTests(unittest.TestCase):
    def parse_hunan(self, text, year='2025'):
        return parse_hunan_final_report(text, '湖南', year, 'hunan_annual_final_report')

    def parse_jiangsu(self, pages, final=False):
        return parse_jiangsu_gazette_pages(pages, '江苏', '2025',
                 'jiangsu_2026_gazette_final_debt' if final else 'jiangsu_2026_gazette_execution')

    def test_hunan_annual_final_not_h1_own_totals_or_other_budgets(self):
        for year, debt in [('2023',18216.6),('2024',21246.9),('2025',24289)]:
            rows = self.parse_hunan(hunan_html(year), year)
            self.assertEqual({r['indicator_code']:r['value'] for r in rows},
                             {'gov_fund_revenue':1793.1,'gov_fund_expenditure':3468.8,'debt_outstanding':debt})
            self.assertTrue(all(r['period']==year and r['government_scope']=='province_total'
                                and r['data_status']=='official_final' for r in rows))
            self.assertNotIn('principal_repayment', {r['indicator_code'] for r in rows})

    def test_hunan_rejects_wrong_year_scope_units_duplicate_and_missing_boundaries(self):
        changes = [('2026年上半年','2025年上半年'),('一、2025年全省及省级财政决算情况','一、2026年预算安排'),
                   ('全省收入１','省本级收入１'),('１，７９３．１亿元','１，７９３．１万元'),
                   ('省级收入58.9亿元','县级收入58.9亿元'),('3．国有资本经营预算','3．其他预算'),
                   ('截至2025年底，全省法定债务余额','截至2026年底，预计全省法定债务余额'),
                   ('全省收入１，７９３．１亿元','全省收入1793.1亿元。全省收入1793.1亿元')]
        for old,new in changes:
            with self.subTest(new=new), self.assertRaises(ValueError):
                self.parse_hunan(hunan_html().replace(old,new))

    def test_hunan_profile_identity_is_closed(self):
        for province,year,profile in [('湖北','2025','hunan_annual_final_report'),('湖南','2022','hunan_annual_final_report'),
                                      ('湖南','2025','unreviewed')]:
            with self.assertRaises(ValueError):parse_hunan_final_report(hunan_html(),province,year,profile)

    def test_jiangsu_execution_fund_land_and_spending_only(self):
        rows = self.parse_jiangsu(jiangsu_pages())
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},
                         {'gov_fund_revenue':6472.47,'land_transfer_revenue':5588.93,'gov_fund_expenditure':8533.59})
        self.assertTrue(all(r['data_status']=='official_preliminary' and r['evidence_page']==124 for r in rows))

    def test_jiangsu_final_debt_uses_full_province_not_own_or_limit(self):
        rows = self.parse_jiangsu(jiangsu_pages(True), True)
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},
                         {'debt_outstanding':33927.54,'general_debt_outstanding':8538.1,'special_debt_outstanding':25389.44})
        self.assertTrue(all(r['data_status']=='official_final' and r['evidence_page']==713 for r in rows))

    def test_jiangsu_rejects_scope_vintage_units_conflicts_and_unreconciled_debt(self):
        for final,page,old,new in [(False,123,'2026年2月3日','2027年2月3日'),
                                  (False,124,'全省政府性基金预算收入','省本级政府性基金预算收入'),
                                  (False,124,'5588.93','6588.93'),(False,124,'8533.59亿元','8533.59万元'),
                                  (False,124,'6472.47亿元','总计15448.08亿元'),
                                  (True,712,'2025年省级财政决算情况','2026年预算安排'),
                                  (True,713,'2025年末，全省','2026年末，预计全省'),
                                  (True,713,'8538.10','9538.10')]:
            pages=jiangsu_pages(final);pages[page]=pages[page].replace(old,new)
            with self.subTest(new=new), self.assertRaises(ValueError):self.parse_jiangsu(pages,final)

    def test_jiangsu_requires_exact_physical_page_set_and_official_header(self):
        for final in (False,True):
            pages=jiangsu_pages(final)
            for bad in ({k:v for k,v in pages.items() if k!=min(pages)}, {**pages,1:'not reviewed'},
                        {k:v.replace('江苏省人民代表大会常务委员会公报','commercial report') for k,v in pages.items()}):
                with self.assertRaises(ValueError):self.parse_jiangsu(bad,final)

    def test_html_review_binds_raw_bytes_source_and_exact_import_subset(self):
        with tempfile.TemporaryDirectory() as tmp, closing(sqlite3.connect(':memory:')) as conn, \
                patch('scripts.review_province_fiscal_supplement.ROOT', Path(tmp)):
            directory=Path(tmp);content=hunan_html().encode('utf8');(directory/'raw.html').write_bytes(content)
            digest=hashlib.sha256(content).hexdigest();url='https://czt.hunan.gov.cn/test.html'
            source={'id':'hunan','format':'html','profile':'hunan_annual_final_report','region_name':'湖南',
                    'raw_sha256':digest,'source_url':url,'source_name':'湖南省财政厅','source_title':'Inspected final report',
                    'reviewed_sections':['Annual government-fund/debt sections'],'scope_notes':'Annual/full province only.',
                    'periods':{'2025':{'expected_values':{'gov_fund_revenue':1793.1,'gov_fund_expenditure':3468.8,
                                                       'debt_outstanding':24289},'import_codes':['gov_fund_revenue']}}}
            archives={'hunan':(directory,{'raw_path':'raw.html','raw_sha256':digest,'source_url':url})}
            rows,proof,checks=review_documents({'documents':[source]},archives,conn)
            self.assertEqual(len(rows['2025']),1);self.assertEqual(rows['2025'][0]['source_url'],url)
            self.assertEqual(proof['2025'][0]['format'],'html');self.assertIsNone(proof['2025'][0]['pdf_pages'])
            self.assertEqual(checks,[])
            for field,new in [('raw_sha256','0'*64),('source_url',url+'/different')]:
                invalid=copy.deepcopy(source);invalid[field]=new
                with self.assertRaises(ValueError):review_documents({'documents':[invalid]},archives,conn)


if __name__=='__main__':unittest.main()
