"""Guard the exact scope and annual period of inspected completion releases."""
import unittest

from services.regional_fiscal_service import parse_china_fiscal_completion_release


class FiscalAnnualReleaseTests(unittest.TestCase):
    def jiangxi(self):
        return '''<title>2025年1-12月份，全省一般公共预算收入完成3079.2亿元 | 会昌县信息公开</title>
        <div id="zoomcon">
        <p>12月份，全省一般公共预算收入152．1亿元；一般公共预算支出1070．7亿元。</p>
        <p>1－12月份，全省一般公共预算收入3079．2亿元，其中税收收入1969．7亿元；一般公共预算支出7426．9亿元。</p>
        <p>1－12月份，全省政府性基金预算收入1592．7亿元，其中国有土地使用权出让收入1096．6亿元；
        政府性基金预算支出3081．3亿元，其中国有土地使用权出让收入安排的支出758．5亿元。</p>
        <p>1－12月份，全省国有资本经营预算收入265．4亿元；国有资本经营预算支出34．4亿元。</p>
        </div>'''

    def qinghai(self):
        return '''<title>青海省2025年1—12月财政收支执行情况</title>
        <div id="html001"><p>一、全省财政收入情况</p>
        <p>1—12月，全省一般公共预算收入575.3亿元；地方一般公共预算收入354.9亿元。
        其中：税收收入254.5亿元；非税收入100.4亿元。增值税98亿元。</p>
        <p>二、全省财政支出情况</p>
        <p>1—12月，全省一般公共预算支出2164.2亿元，同比增支0.2亿元。社会保障和就业支出376.5亿元。</p></div>'''

    def parse(self, text, province='江西'):
        profile = {'江西':'jiangxi_2025_annual_completion',
                   '青海':'qinghai_2025_annual_completion'}[province]
        return parse_china_fiscal_completion_release(text, province, '2025', profile)

    def test_jiangxi_reads_annual_not_december_or_land_related_spending(self):
        rows = self.parse(self.jiangxi())
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'general_budget_revenue':3079.2, 'tax_revenue':1969.7,
            'general_budget_expenditure':7426.9, 'gov_fund_revenue':1592.7,
            'gov_fund_expenditure':3081.3, 'land_transfer_revenue':1096.6})
        self.assertTrue(all(r['period']=='2025' and r['frequency']=='annual' and
                            r['period_type']=='calendar_year' and
                            r['government_scope']=='province_total' and
                            r['data_status']=='official_preliminary' for r in rows))

    def test_qinghai_prefers_local_revenue_not_all_territorial_revenue(self):
        rows = self.parse(self.qinghai(), '青海')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'general_budget_revenue':354.9, 'tax_revenue':254.5,
            'general_budget_expenditure':2164.2})
        self.assertTrue(all(r['region_code']=='630000' for r in rows))

    def test_rejects_missing_annual_paragraphs_or_article_body(self):
        for text in (self.jiangxi().replace('1－12月份', '12月份'),
                     self.jiangxi().replace('1－12月份', '1－11月份'),
                     self.jiangxi().replace('id="zoomcon"', 'id="unknown"'),
                     self.qinghai().replace('1—12月，全省一般公共预算支出', '1—11月，全省一般公共预算支出')):
            province = '青海' if 'html001' in text else '江西'
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text, province)

    def test_rejects_scope_plans_components_and_duplicate_annual_statements(self):
        for text in (self.jiangxi().replace('全省政府性基金预算收入', '省本级政府性基金预算收入'),
                     self.jiangxi().replace('全省一般公共预算收入3079', '全省计划一般公共预算收入3079'),
                     self.jiangxi().replace('税收收入1969', '税收收入3969'),
                     self.jiangxi().replace('出让收入1096', '出让收入2096'),
                     self.jiangxi().replace('</div>', '<p>1-12月份，全省一般公共预算收入3000亿元。</p></div>')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_profile_identity_and_full_year_title_are_required(self):
        for province, year, profile in (
            ('安徽','2025','jiangxi_2025_annual_completion'),
            ('江西','2024','jiangxi_2025_annual_completion'),
            ('青海','2025','jiangxi_2025_annual_completion')):
            with self.subTest(province=province, year=year), self.assertRaises(ValueError):
                parse_china_fiscal_completion_release(self.jiangxi(), province, year, profile)
        for text in (self.jiangxi().replace('2025年1-12月份', '2024年1-12月份'),
                     self.qinghai().replace('2025年1—12月', '2025年1—11月')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text, '青海' if 'html001' in text else '江西')


if __name__ == '__main__':
    unittest.main()
