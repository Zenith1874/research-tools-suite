"""Column-position tests for four visually reviewed official final-account PDFs."""
import unittest

from services.regional_fiscal_service import parse_china_fiscal_pdf_pages


HEADER = '''单位：亿元 项    目 年初预算数 经人大批准的
调整后预算数 决算数 决算数为调整后预算数的% 决算数为上年决算数的%'''


class ShanghaiFinalTableTests(unittest.TestCase):
    def parse(self, text, profile):
        return parse_china_fiscal_pdf_pages({1:text}, '上海', '2025', 'shanghai_2025_'+profile+'_final')

    def revenue(self):
        return HEADER + '''
税收收入 7,328.0 7,328.0 7,318.5 99.9 103.3
一般公共预算收入合计 8,540.0 8,540.0 8,500.9 99.5 101.5
总 计 10,682.2 10,997.2 11,869.8 107.9 104.8
上海市2025年一般公共预算收入决算情况表'''

    def debt(self):
        return '''单位：亿元
小计 一般债务 专项债务 小计 一般债务 专项债务
上海市合计 11,446.2 4,465.2 6,981.0 10,420.1 4,211.0 6,209.1
一、市级 4,106.9 1,263.3 2,843.6 3,729.0 1,110.9 2,618.1
上海市2025年地方政府债务限额和余额决算情况表
地区 2025年债务限额 2025年债务余额决算数'''

    def test_reads_final_third_amount_not_budget_gross_or_growth(self):
        rows = self.parse(self.revenue(), 'revenue')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'general_budget_revenue':8500.9, 'tax_revenue':7318.5})
        self.assertTrue(all(r['data_status']=='official_final' and r['evidence_page']==1 and
                            r['government_scope']=='province_total' for r in rows))

    def test_fund_subtotals_exclude_transfers_borrowing_and_land_spending(self):
        income = HEADER + '''
国有土地使用权出让收入 2,800.0 2,800.0 2,804.3 100.2 94.2
政府性基金收入合计 3,090.5 3,090.5 3,039.6 98.4 94.9
总 计 4,044.4 5,158.4 5,310.8 103.0 116.6
上海市2025年政府性基金收入决算情况表'''
        spending = HEADER + '''
国有土地使用权出让支出 3,028.0 3,894.3 3,432.5 88.1 132.5
政府性基金支出合计 3,321.4 4,394.4 4,005.1 91.1 139.0
总 计 4,044.4 5,158.4 5,310.8 103.0 116.6
上海市2025年政府性基金支出决算情况表'''
        self.assertEqual({r['indicator_code']:r['value'] for r in self.parse(income, 'fund_revenue')},
                         {'gov_fund_revenue':3039.6, 'land_transfer_revenue':2804.3})
        self.assertEqual(self.parse(spending, 'fund_expenditure')[0]['value'], 4005.1)
        with self.assertRaises(ValueError):
            self.parse(income.replace('2,804.3', '3,804.3'), 'fund_revenue')

    def test_debt_uses_balance_not_limit_and_whole_city_not_city_own(self):
        rows = self.parse(self.debt(), 'debt_balances')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'debt_outstanding':10420.1, 'general_debt_outstanding':4211.0,
            'special_debt_outstanding':6209.1})
        for text in (self.debt().replace('上海市合计', '市级合计'),
                     self.debt().replace('4,211.0', '8,211.0'),
                     self.debt().replace('10,420.1 4,211.0', '10,420.1 0 4,211.0'),
                     self.debt().replace('2025年债务限额 2025年债务余额决算数',
                                         '2025年债务余额决算数 2025年债务限额')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text, 'debt_balances')

    def test_rejects_unit_year_scope_and_column_order_changes(self):
        for text in (self.revenue().replace('单位：亿元', '单位：万元'),
                     self.revenue().replace('上海市2025年', '上海市2024年'),
                     self.revenue().replace('一般公共预算收入决算情况表', '市级一般公共预算收入决算情况表'),
                     self.revenue().replace('调整后预算数 决算数', '决算数 调整后预算数'),
                     self.revenue().replace('7,318.5', '9,318.5'),
                     self.revenue().replace('7,328.0 7,328.0 7,318.5', '7,328.0 7,318.5')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text, 'revenue')

    def test_extra_missing_pages_or_unreviewed_profiles_are_rejected(self):
        for pages, province, period, profile in (
            ({2:self.revenue()},'上海','2025','shanghai_2025_revenue_final'),
            ({1:self.revenue(),2:'other'},'上海','2025','shanghai_2025_revenue_final'),
            ({1:self.revenue()},'江苏','2025','shanghai_2025_revenue_final'),
            ({1:self.revenue()},'上海','2024','shanghai_2025_revenue_final'),
            ({1:self.revenue()},'上海','2025','shanghai_2025_debt_service_final')):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                parse_china_fiscal_pdf_pages(pages, province, period, profile)


if __name__ == '__main__':
    unittest.main()
