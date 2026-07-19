# -*- coding: utf-8 -*-
import unittest

from services.china_macro_service import (
    parse_cpi_article, parse_ppi_article, parse_pmi_article,
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


if __name__ == '__main__':
    unittest.main()
