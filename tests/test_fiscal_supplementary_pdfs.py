"""Preserve local/whole-territory, year, table columns and primary-source boundaries."""
import copy
import sqlite3
import unittest

from services.regional_fiscal_service import parse_china_fiscal_pdf_pages
from services.fiscal_source_authority import (
    SHAANXI_ISSUER_URL, SHAANXI_ISSUER_SHA256, SHAANXI_ISSUER_TITLE,
    official_fiscal_download_url, reviewed_issuer_fiscal_source)
from scripts.review_province_fiscal_supplement import merge_new_observations, verify_issuer_unit_overlap


def fujian_pages():
    return {
        1:'''福建省财政厅 2025年全省财政预算执行情况 一、一般公共预算收入情况
2025年，全省一般公共预算总收入6093.16亿元，完成预算99.3%。地方一般公共预算收入3723.35亿元。
税收收入4741.71亿元。地方级税收收入2371.90亿元，非税收入1351.45亿元。''',
        3:'从地市看，晋江市159.80亿元。二、一般公共预算支出情况 一般公共预算支出6148.7亿元，增',
        4:'''长1.1%。三、政府性基金收入情况 政府性基金收入合计1680.45亿元。
其中，国有土地使用权出让收入1514.81亿元。专项债务对应项目专项收入50.97亿元。''',
        5:'''四、政府性基金支出情况 全省政府性基金支出3971.63亿元。
土地出让收入安排的支出1173.18亿元。专项债付息支出391.08亿元。福建省财政厅2026年1月26日'''}


def shaanxi_pages():
    return {
        1:'2026年陕西省政府专项债券（四至九期）信息披露文件',
        7:'''四、陕西省财政收支状况
2023年 2024年 2025年
省本级 全省 省本级 全省 省本级 全省
一般公共预算收入 1158.89 3437.6 1126.8 3393.28 1098.2 3289.4
一般公共预算支出 1028.49 7175.08 1046.2 7297.73 1031.8 7093.4
政府性基金收入 50.9 1785.54 48.15 1671.6 61.3 1072.1
政府性基金支出 182.67 2621.78 154.54 2673.95 102 1972.5
地方政府一般债券还本支出 161.31 547.32 176.05 374.01 109.44 426.83''',
        8:'''国有土地使用权出让收入 - 1568.15 - 1467.43 - 855.8
注：2023-2024年数据为决算数，2025年数据为执行数。
截至2025年底，全省政府债务余额14349.24亿元，控制在债务限额15,365.45亿元内。
全省一般债务余额5528.92亿元；专项债务余额8820.32亿元。分级次看，省本级债务余额2203.13亿元。''',
        10:'陕西省财政厅 2026年4月22日'}


class FiscalSupplementPdfTests(unittest.TestCase):
    def parse(self,pages,province,period='2025'):
        profile={'福建':'fujian_2025_annual_completion_pdf','陕西':'shaanxi_2026_primary_issuer_fiscal'}[province]
        return parse_china_fiscal_pdf_pages(pages,province,period,profile)

    def test_fujian_local_tax_not_territorial_and_land_not_spending(self):
        rows=self.parse(fujian_pages(),'福建')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},{
            'general_budget_revenue':3723.35,'tax_revenue':2371.9,
            'general_budget_expenditure':6148.7,'gov_fund_revenue':1680.45,
            'land_transfer_revenue':1514.81,'gov_fund_expenditure':3971.63})
        self.assertTrue(all(r['data_status']=='official_preliminary' and r['period']=='2025' for r in rows))
        self.assertNotIn('interest_expenditure',{r['indicator_code'] for r in rows})

    def test_fujian_rejects_wrong_local_scope_units_or_components(self):
        for page,old,new in [(1,'地方级税收收入','税务部门税收收入'),
                             (1,'2371.90','4371.90'),(4,'1514.81','2514.81'),
                             (4,'1514.81亿元','1514.81万元'),(5,'2026年1月26日','2025年1月26日')]:
            pages=fujian_pages();pages[page]=pages[page].replace(old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):self.parse(pages,'福建')

    def test_shaanxi_full_province_columns_and_historical_vintages(self):
        expected={'2023':(1785.54,1568.15,'official_final'),
                  '2024':(1671.6,1467.43,'official_final'),
                  '2025':(1072.1,855.8,'official_preliminary')}
        for period,(fund,land,status) in expected.items():
            rows=self.parse(shaanxi_pages(),'陕西',period);values={r['indicator_code']:r['value'] for r in rows}
            self.assertEqual(values['gov_fund_revenue'],fund)
            self.assertEqual(values['land_transfer_revenue'],land)
            self.assertTrue(all(r['data_status']==status for r in rows))
            self.assertNotIn('principal_repayment',values)
        self.assertEqual(values['debt_outstanding'],14349.24)
        self.assertEqual(values['general_debt_outstanding'],5528.92)

    def test_shaanxi_rejects_column_shift_zero_filled_dashes_and_wrong_vintage(self):
        for page,old,new in [(7,'省本级 全省','全省 省本级'),
                             (7,'61.3 1072.1','0 61.3 1072.1'),
                             (8,'- 1568.15','0 1568.15'),
                             (8,'执行数','预算数'),(8,'5528.92','6528.92'),
                             (10,'陕西省财政厅','中债资信评估有限责任公司')]:
            pages=shaanxi_pages();pages[page]=pages[page].replace(old,new)
            with self.subTest(new=new),self.assertRaises(ValueError):self.parse(pages,'陕西')

    def test_missing_extra_pages_years_and_provinces_fail_closed(self):
        for province,factory in [('福建',fujian_pages),('陕西',shaanxi_pages)]:
            for pages in ({**factory(),2:'unreviewed'}, {k:v for k,v in factory().items() if k!=1}):
                with self.assertRaises(ValueError):self.parse(pages,province)
        with self.assertRaises(ValueError):self.parse(shaanxi_pages(),'陕西','2022')
        with self.assertRaises(ValueError):self.parse(fujian_pages(),'福建','2024')

    def test_transport_exception_is_one_declared_primary_filing_only(self):
        self.assertTrue(official_fiscal_download_url('https://czt.fj.gov.cn/example.pdf'))
        self.assertTrue(official_fiscal_download_url(SHAANXI_ISSUER_URL,'government_issuer_filing'))
        for url,kind in [(SHAANXI_ISSUER_URL,'government_website'),
                         (SHAANXI_ISSUER_URL+'?x=1','government_issuer_filing'),
                         (SHAANXI_ISSUER_URL.replace('X55R','RATING'),'government_issuer_filing'),
                         (SHAANXI_ISSUER_URL.replace('https:','http:'),'government_issuer_filing')]:
            self.assertFalse(official_fiscal_download_url(url,kind))

    def test_observation_exception_requires_hash_issuer_page_vintage_and_unit_check(self):
        row={'region_code':'610000','region_name':'陕西','period':'2025','indicator_code':'gov_fund_revenue',
             'source_url':SHAANXI_ISSUER_URL+'#page=7','source_title':SHAANXI_ISSUER_TITLE,
             'source_name':'陕西省财政厅（上交所政府债券发行人原始披露）','data_status':'official_preliminary',
             'parser_notes':'access_type=government_issuer_filing; raw_sha256='+SHAANXI_ISSUER_SHA256+'; unit_overlap_verified=4'}
        self.assertTrue(reviewed_issuer_fiscal_source(row))
        for field,value in [('region_name','安徽'),('period','2026'),('data_status','official_final'),
                            ('indicator_code','principal_repayment'),('source_url',SHAANXI_ISSUER_URL+'#page=1'),
                            ('source_name','评级机构'),('parser_notes','unreviewed')]:
            self.assertFalse(reviewed_issuer_fiscal_source({**row,field:value}))

    def test_supplement_merge_preserves_old_rows_and_rejects_revisions(self):
        old=[{'region_code':'350000','indicator_code':'general_budget_revenue','period':'2025','value':3723.35}]
        before=copy.deepcopy(old)
        new={'region_code':'350000','indicator_code':'tax_revenue','period':'2025','value':2371.9}
        self.assertEqual(merge_new_observations(old,[new]),old+[new]);self.assertEqual(old,before)
        with self.assertRaises(ValueError):merge_new_observations(old,[{**old[0],'value':999}])
        with self.assertRaises(ValueError):merge_new_observations(old,[new,new])

    def test_unit_overlap_requires_distinct_nbs_history_with_exact_values_and_units(self):
        parsed={p:{r['indicator_code']:r['value'] for r in self.parse(shaanxi_pages(),'陕西',p)} for p in ('2023','2024')}
        checks=[{'period':p,'indicator_code':c,'value':parsed[p][c]} for p in parsed for c in
                ('general_budget_revenue','general_budget_expenditure')]
        source={'source_class':'government_issuer_filing','region_name':'陕西','unit_overlap_checks':checks}
        with sqlite3.connect(':memory:') as conn:
            conn.row_factory=sqlite3.Row
            conn.execute('CREATE TABLE regional_fiscal_observations(country_code,government_scope,region_code,indicator_code,period,value,unit,source_url)')
            conn.executemany('INSERT INTO regional_fiscal_observations VALUES (?,?,?,?,?,?,?,?)',[
                ('CN','province_total','610000',c['indicator_code'],c['period'],c['value'],'亿元','https://www.stats.gov.cn/yearbook.jpg') for c in checks])
            self.assertEqual(len(verify_issuer_unit_overlap(source,parsed,conn)),4)
            for changes in ({'unit_overlap_checks':[checks[0]]*4}, {'unit_overlap_checks':checks[:3]}):
                with self.assertRaises(ValueError):verify_issuer_unit_overlap({**source,**changes},parsed,conn)
            for field,value in [('unit','万元'),('value',1),('source_url','https://example.org/')]:
                conn.execute('SAVEPOINT mutation')
                conn.execute('UPDATE regional_fiscal_observations SET '+field+'=?',(value,))
                with self.assertRaises(ValueError):verify_issuer_unit_overlap(source,parsed,conn)
                conn.execute('ROLLBACK TO mutation');conn.execute('RELEASE mutation')


if __name__=='__main__':unittest.main()
