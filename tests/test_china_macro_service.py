# -*- coding: utf-8 -*-
import unittest

from services.china_macro_service import (
    parse_cpi_article, parse_ppi_article, parse_pmi_article,
    parse_ip_article, parse_retail_article, parse_fai_article, parse_gdp_article,
    _month_period, _gdp_period,
)


class ChinaMacroParserTests(unittest.TestCase):
    def test_cpi_up_yoy_down_mom(self):
        html = '<p>2026年6月份，全国居民消费价格同比上涨1.0%。……全国居民消费价格环比下降0.3%。</p>'
        self.assertEqual(parse_cpi_article(html),
                         {'CN_CPI_YOY': 1.0, 'CN_CPI_MOM': -0.3})

    def test_cpi_flat_is_zero_not_missing(self):
        html = '全国居民消费价格同比持平。环比持平。'
        self.assertEqual(parse_cpi_article(html),
                         {'CN_CPI_YOY': 0.0, 'CN_CPI_MOM': 0.0})

    def test_ppi_down_yoy(self):
        html = '2023年6月份，全国工业生产者出厂价格同比下降5.4%，环比下降0.8%。'
        self.assertEqual(parse_ppi_article(html),
                         {'CN_PPI_YOY': -5.4, 'CN_PPI_MOM': -0.8})

    def test_pmi_three_indices_fullwidth_parens(self):
        html = ('6月份，制造业采购经理指数（PMI）为50.3%。'
                '非制造业商务活动指数为50.2%。综合PMI产出指数为50.6%。')
        self.assertEqual(parse_pmi_article(html),
                         {'CN_PMI_MFG': 50.3, 'CN_PMI_NONMFG': 50.2, 'CN_PMI_COMP': 50.6})

    def test_pmi_without_parenthetical(self):
        html = '制造业采购经理指数为35.7%。'
        self.assertEqual(parse_pmi_article(html), {'CN_PMI_MFG': 35.7})

    def test_cpi_legacy_zongshuiping_wording(self):
        # 2011-2015 措辞:"总水平",同比环比可同句
        html = '2012年12月份，全国居民消费价格总水平同比上涨2.5%，环比上涨0.8%。'
        self.assertEqual(parse_cpi_article(html),
                         {'CN_CPI_YOY': 2.5, 'CN_CPI_MOM': 0.8})

    def test_cpi_mom_never_grabs_component_number(self):
        # 分项环比在前:全篇任意匹配会错抓 2.9,必须锚定标题句
        html = '食品价格环比上涨2.9%。2012年12月份，全国居民消费价格总水平同比上涨2.5%，环比上涨0.8%。'
        self.assertEqual(parse_cpi_article(html)['CN_CPI_MOM'], 0.8)

    def test_unrelated_text_yields_nothing(self):
        self.assertEqual(parse_cpi_article('能源生产情况新闻稿'), {})
        self.assertEqual(parse_pmi_article('与指数无关'), {})

    def test_ip_monthly_real_and_cumulative(self):
        html = '5月份，规模以上工业增加值同比实际增长4.5%。……1—5月份，规模以上工业增加值同比增长5.4%。'
        self.assertEqual(parse_ip_article(html),
                         {'CN_IP_YOY': 4.5, 'CN_IP_YTD_YOY': 5.4})

    def test_retail_monthly_not_confused_with_cumulative(self):
        html = ('1—5月份，社会消费品零售总额206031亿元，同比增长1.4%。'
                '5月份，社会消费品零售总额41090亿元，同比下降0.6%。')
        self.assertEqual(parse_retail_article(html),
                         {'CN_RETAIL_YOY': -0.6, 'CN_RETAIL_YTD_YOY': 1.4})

    def test_fai_cumulative_decline(self):
        html = '1—5月份，全国固定资产投资（不含农户）178512亿元，同比下降4.1%。'
        self.assertEqual(parse_fai_article(html), {'CN_FAI_YTD_YOY': -4.1})

    def test_gdp_table_four_columns_takes_single_quarter(self):
        html = ('<table><tr><td>指标</td><td>二季度</td><td>上半年</td><td>二季度</td><td>上半年</td></tr>'
                '<tr><td>GDP</td><td>361511</td><td>695704</td><td>4.3</td><td>4.7</td></tr>'
                '<tr><td>第一产业</td><td>19581</td><td>31522</td><td>3.7</td><td>3.7</td></tr></table>')
        self.assertEqual(parse_gdp_article(html),
                         {'CN_GDP_Q_NOMINAL': 361511.0, 'CN_GDP_Q_REAL_YOY': 4.3})

    def test_gdp_table_two_columns_q1(self):
        html = '<table><tr><td>GDP</td><td>327789</td><td>5.4</td></tr></table>'
        self.assertEqual(parse_gdp_article(html),
                         {'CN_GDP_Q_NOMINAL': 327789.0, 'CN_GDP_Q_REAL_YOY': 5.4})

    def test_period_mapping_titles(self):
        self.assertEqual(_month_period('2026年1—2月份社会消费品零售总额增长2%', '社会消费品零售总额'),
                         '2026-02')  # 1-2月合并记2月
        self.assertEqual(_month_period('2026年上半年社会消费品零售总额增长1.3%', '社会消费品零售总额'),
                         '2026-06')
        self.assertEqual(_gdp_period('2025年四季度和全年国内生产总值初步核算结果'), '2025-12')
        self.assertEqual(_gdp_period('2026年三季度和前三季度国内生产总值初步核算结果'), '2026-09')
        self.assertIsNone(_gdp_period('2026年国民经济运行情况'))


if __name__ == '__main__':
    unittest.main()
