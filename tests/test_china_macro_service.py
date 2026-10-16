# -*- coding: utf-8 -*-
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from services.china_macro_service import (
    parse_cpi_article, parse_ppi_article, parse_pmi_article,
    parse_ip_article, parse_retail_article, parse_fai_article, parse_gdp_article,
    parse_econ_article, _month_period, _fai_period, _gdp_period, _econ_period,
    discover_releases, discover_release_list_releases, _RELEASE_LIST_PAGE_CACHE,
)


class ChinaMacroParserTests(unittest.TestCase):
    def test_alternative_main_release_titles_keep_the_statistical_year(self):
        self.assertEqual(_econ_period('2025年经济发展向新向优 预期目标圆满实现',
            'https://www.stats.gov.cn/sj/zxfb/202601/t20260119_1962330.html'),'2025-12')
        self.assertEqual(_econ_period('上半年经济运行在合理区间 新动能快速成长',
            'https://www.stats.gov.cn/sj/xwfbh/fbhwd/202607/t20260715_1964121.html'),'2026-06')
        self.assertIsNone(_econ_period('上半年经济运行在合理区间',
            'https://www.stats.gov.cn/sj/zxfb/202302/t20230202_123.html'))

    def test_reviewed_economic_manifest_survives_search_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            manifest=Path(temp)/'releases.csv'
            manifest.write_text('period,source_url,source_title\n2025-12,https://www.stats.gov.cn/sj/zxfb/202601/fixture.html,2025年经济发展向新向优\n',encoding='utf-8')
            with patch('services.china_macro_service.requests.post',side_effect=RuntimeError('fixture search unavailable')), \
                 patch('services.china_macro_service.discover_release_list_releases',return_value={}), \
                 patch('services.china_macro_service.ECON_RELEASE_MANIFEST_PATH',manifest):
                result=discover_releases('econ',2025,2026)
            self.assertIn('2025-12',result)

    def test_cpi_up_yoy_down_mom(self):
        html = '<p>2026年6月份，全国居民消费价格同比上涨1.0%。……全国居民消费价格环比下降0.3%。</p>'
        self.assertEqual(parse_cpi_article(html),
                         {'CN_CPI_YOY': 1.0, 'CN_CPI_MOM': -0.3})

    def test_cpi_flat_is_zero_not_missing(self):
        html = '全国居民消费价格同比持平。环比持平。'
        self.assertEqual(parse_cpi_article(html),
                         {'CN_CPI_YOY': 0.0, 'CN_CPI_MOM': 0.0})

    def test_ppi_down_yoy(self):
        html = ('2023年6月份，全国工业生产者出厂价格同比下降5.4%，环比下降0.8%。'
                '工业生产者购进价格同比下降6.5%，环比下降1.1%。'
                '生产资料价格同比下降7.5%，生活资料价格下降0.5%。')
        self.assertEqual(parse_ppi_article(html),
                         {'CN_PPI_YOY': -5.4, 'CN_PPI_MOM': -0.8,
                          'CN_PPIRM_YOY': -6.5, 'CN_PPIRM_MOM': -1.1,
                          'CN_PPI_PRODUCTION_YOY': -7.5,
                          'CN_PPI_LIVING_YOY': -0.5})

    def test_ppi_post_base_year_wording_without_yoy(self):
        # 2021 年后部分新闻稿在同比段省略“同比”二字；环比段会再次出现
        # 同一标签，解析必须只取同比段，不能抓到环比的 1.2%。
        html = ('一、工业生产者价格同比变动情况。生产资料价格由降转涨，上涨0.5%，'
                '生活资料价格下降0.2%。二、工业生产者价格环比变动情况。'
                '生产资料价格上涨1.2%。生活资料价格下降0.1%。')
        parsed = parse_ppi_article(html)
        self.assertEqual(parsed['CN_PPI_PRODUCTION_YOY'], 0.5)
        self.assertEqual(parsed['CN_PPI_LIVING_YOY'], -0.2)

    def test_ppi_early_headline_can_put_mom_before_yoy(self):
        html = ('2016年1月份，全国工业生产者出厂价格环比下降0.5%，同比下降5.3%。'
                '工业生产者购进价格环比下降0.7%，同比下降6.3%。'
                '一、工业生产者价格同比变动情况。生产资料价格同比下降6.9%。')
        parsed = parse_ppi_article(html)
        self.assertEqual(parsed['CN_PPI_YOY'], -5.3)
        self.assertEqual(parsed['CN_PPI_MOM'], -0.5)
        self.assertEqual(parsed['CN_PPIRM_YOY'], -6.3)
        self.assertEqual(parsed['CN_PPIRM_MOM'], -0.7)

    def test_ppi_legacy_comparisons_and_explicit_same_month_flat(self):
        parsed=parse_ppi_article('全国工业生产者出厂价格比上月上涨0.9%，比去年同月上涨6.6%；'
                                 '工业生产者购进价格比上月上涨1.2%，比去年同月上涨9.7%。')
        self.assertEqual(parsed['CN_PPI_YOY'],6.6)
        self.assertEqual(parsed['CN_PPI_MOM'],0.9)
        self.assertEqual(parsed['CN_PPIRM_YOY'],9.7)
        self.assertEqual(parsed['CN_PPIRM_MOM'],1.2)
        flat=parse_ppi_article('全国工业生产者出厂价格与去年同月持平，环比上涨0.1%。'
                               '工业生产者购进价格同比上涨1.0%，环比上涨0.1%。')
        self.assertEqual(flat['CN_PPI_YOY'],0)
        self.assertEqual(flat['CN_PPI_MOM'],0.1)

    def test_flat_ppi_does_not_steal_later_purchase_price_mom(self):
        for direction,value in (('下降','0.1'),('上涨','0.1')):
            text=('全国工业生产者出厂价格同比下降1.9%，环比持平（涨跌幅度为0）。'
                  f'工业生产者购进价格同比下降2.0%，环比{direction}{value}%。')
            parsed=parse_ppi_article(text)
            self.assertEqual(parsed['CN_PPI_MOM'],0)
            self.assertEqual(parsed['CN_PPIRM_MOM'],-0.1 if direction=='下降' else 0.1)

    def test_earlier_legacy_monthly_headline_wins_over_a_later_ytd_sentence(self):
        parsed=parse_ppi_article('2016年8月份，全国工业生产者出厂价格环比上涨0.2%，同比下降0.8%。'
                                 '工业生产者购进价格环比上涨0.2%，同比下降1.7%。'
                                 '1-8月平均，工业生产者出厂价格同比下降3.2%，工业生产者购进价格同比下降4.1%。')
        self.assertEqual(parsed['CN_PPI_YOY'],-0.8)
        self.assertEqual(parsed['CN_PPIRM_YOY'],-1.7)
        self.assertEqual(parsed['CN_PPIRM_MOM'],0.2)

    def test_price_turning_phrases_use_current_not_previous_month_values(self):
        parsed=parse_ppi_article('全国工业生产者出厂价格同比下降0.8%，环比由上月上涨0.2%转为下降0.2%；'
                                 '工业生产者购进价格同比下降0.5%，环比上涨0.1%。'
                                 '一、工业生产者价格同比变动情况。生活资料价格同比由上月上涨0.6%转为下降0.1%。')
        self.assertEqual(parsed['CN_PPI_MOM'],-0.2)
        self.assertEqual(parsed['CN_PPIRM_MOM'],0.1)
        self.assertEqual(parsed['CN_PPI_LIVING_YOY'],-0.1)

    def test_paired_current_headlines_keep_explicit_pair_order_and_flat_values(self):
        for suffix,expected in (
                ('环比分别下降0.2%、0.3%。',(-0.2,-0.3)),
                ('环比分别持平和上涨0.1%。',(0,0.1)),
                ('环比分别下降0.2%、上涨0.3%。',(-0.2,0.3)),
                ('环比均下降0.2%。',(-0.2,-0.2))):
            parsed=parse_ppi_article('全国工业生产者出厂价格和购进价格同比均下降2.3%，'+suffix+
                                     '一、工业生产者价格同比变动情况。生产资料价格下降2.6%。')
            self.assertEqual(parsed['CN_PPI_YOY'],-2.3)
            self.assertEqual(parsed['CN_PPIRM_YOY'],-2.3)
            self.assertEqual((parsed['CN_PPI_MOM'],parsed['CN_PPIRM_MOM']),expected)

    def test_later_shared_ytd_statement_does_not_replace_separate_monthly_yoy(self):
        parsed=parse_ppi_article('全国工业生产者出厂价格同比下降1.0%，环比上涨0.1%。'
                                 '工业生产者购进价格同比下降2.0%，环比上涨0.2%。'
                                 '1-9月平均，工业生产者出厂价格和购进价格同比均下降1.5%。')
        self.assertEqual(parsed['CN_PPI_YOY'],-1.0)
        self.assertEqual(parsed['CN_PPIRM_YOY'],-2.0)

    def test_separate_yoy_sentence_after_national_mom_is_not_missing(self):
        parsed=parse_ppi_article('全国工业生产者出厂价格环比下降0.2%，工业生产者购进价格环比下降0.3%。'
                                 '工业生产者出厂价格同比下降3.6%，工业生产者购进价格同比下降4.5%。')
        self.assertEqual(parsed['CN_PPI_YOY'],-3.6)
        self.assertEqual(parsed['CN_PPI_MOM'],-0.2)

    def test_continued_flat_mom_does_not_become_purchase_price_change(self):
        parsed=parse_ppi_article('全国工业生产者出厂价格同比下降2.3%，环比继续持平。'
                                 '工业生产者购进价格同比下降3.1%，环比上涨0.1%。')
        self.assertEqual(parsed['CN_PPI_MOM'],0)

    def test_turning_without_repeated_previous_month_and_separate_mom_sentence(self):
        flat=parse_ppi_article('全国工业生产者出厂价格同比下降2.9%，环比由下降0.2%转为持平。'
                               '工业生产者购进价格同比下降4.0%，环比持平。')
        self.assertEqual(flat['CN_PPI_MOM'],0)
        parsed=parse_ppi_article('全国工业生产者出厂价格同比下降2.9%，工业生产者购进价格同比下降2.7%。'
                                 '工业生产者出厂价格环比下降0.1%，工业生产者购进价格环比下降0.3%。')
        self.assertEqual(parsed['CN_PPI_MOM'],-0.1)

    def test_missing_headline_mom_does_not_take_a_different_named_series(self):
        parsed=parse_ppi_article('全国工业生产者出厂价格同比下降1.9%。'
                                 '工业生产者购进价格同比下降2.0%，环比下降0.1%。')
        self.assertNotIn('CN_PPI_MOM',parsed)
        self.assertEqual(parsed['CN_PPIRM_MOM'],-0.1)

    def test_bare_component_flat_is_yoy_only_inside_the_yoy_section(self):
        parsed=parse_ppi_article('一、工业生产者价格同比变动情况。生产资料价格同比下降1.8%。'
                                 '生活资料价格持平。二、各类产品价格环比变动情况。'
                                 '生活资料价格上涨0.2%。')
        self.assertEqual(parsed['CN_PPI_LIVING_YOY'],0)
        missing=parse_ppi_article('一、工业生产者价格同比变动情况。生产资料价格同比下降1.8%。'
                                  '二、各类产品价格环比变动情况。生活资料价格持平。')
        self.assertNotIn('CN_PPI_LIVING_YOY',missing)

    def test_ppi_combined_headline_wording(self):
        html = ('2024年4月份，全国工业生产者出厂价格同比下降2.5%，工业生产者购进价格同比下降3.0%；'
                '工业生产者出厂价格和购进价格环比分别下降0.2%、0.3%。')
        self.assertEqual(parse_ppi_article(html), {
            'CN_PPI_YOY': -2.5, 'CN_PPI_MOM': -0.2,
            'CN_PPIRM_YOY': -3.0, 'CN_PPIRM_MOM': -0.3,
        })
        same = ('2019年2月份，全国工业生产者出厂价格同比上涨0.1%，环比下降0.1%；'
                '工业生产者购进价格同比和环比均下降0.1%。')
        parsed = parse_ppi_article(same)
        self.assertEqual(parsed['CN_PPIRM_YOY'], -0.1)
        self.assertEqual(parsed['CN_PPIRM_MOM'], -0.1)
        equal_mom = ('2025年11月份，全国工业生产者出厂价格同比下降2.2%，'
                     '工业生产者购进价格同比下降2.5%；工业生产者出厂价格和购进价格环比均上涨0.1%。')
        parsed = parse_ppi_article(equal_mom)
        self.assertEqual(parsed['CN_PPI_MOM'], 0.1)
        self.assertEqual(parsed['CN_PPIRM_MOM'], 0.1)

    def test_ppi_component_flat_is_zero(self):
        html = ('2016年7月份，全国工业生产者出厂价格同比下降1.7%，环比上涨0.2%。'
                '工业生产者购进价格同比下降4.5%，环比上涨0.3%。'
                '一、工业生产者价格同比变动情况。生产资料价格同比下降2.3%。'
                '生活资料价格同比持平（涨跌幅度为0，下同）。')
        parsed = parse_ppi_article(html)
        self.assertEqual(parsed['CN_PPI_LIVING_YOY'], 0.0)

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

    def test_cpi_month_on_month_flat_with_previous_month_wording(self):
        html = '2018年12月份，全国居民消费价格同比上涨1.9%。12月份，全国居民消费价格环比与上月持平。'
        self.assertEqual(parse_cpi_article(html), {'CN_CPI_YOY': 1.9, 'CN_CPI_MOM': 0.0})

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

    def test_retail_table_amounts_auto_and_online(self):
        html = '''<table>
          <tr><td>指标</td><td>6月</td><td></td><td>1—6月</td><td></td></tr>
          <tr><td>社会消费品零售总额</td><td>42691</td><td>1.0</td><td>248722</td><td>1.3</td></tr>
          <tr><td>其中：除汽车以外的消费品零售额</td><td>38900</td><td>3.0</td><td>229034</td><td>2.8</td></tr>
          <tr><td>其中：网上商品零售额</td><td>-</td><td>-</td><td>64296</td><td>4.8</td></tr>
          <tr><td>汽车类</td><td>3791</td><td>-16.1</td><td>19688</td><td>-12.6</td></tr>
        </table>'''
        parsed = parse_retail_article(html)
        self.assertEqual(parsed['CN_RETAIL_MONTH'], 42691)
        self.assertEqual(parsed['CN_RETAIL_YTD'], 248722)
        self.assertEqual(parsed['CN_RETAIL_EX_AUTO_MONTH_YOY'], 3.0)
        self.assertEqual(parsed['CN_RETAIL_ONLINE_GOODS_YTD'], 64296)
        self.assertEqual(parsed['CN_AUTO_RETAIL_YTD_YOY'], -12.6)

    def test_fai_cumulative_decline(self):
        html = '1—5月份，全国固定资产投资（不含农户）178512亿元，同比下降4.1%。'
        self.assertEqual(parse_fai_article(html),
                         {'CN_FAI_YTD': 178512.0, 'CN_FAI_YTD_YOY': -4.1})

    def test_fai_annual_release_maps_to_december(self):
        title = '2022年全国固定资产投资（不含农户）增长5.1%'
        html = '2022年，全国固定资产投资（不含农户）572138亿元，比上年增长5.1%。'
        self.assertEqual(_fai_period(title, 'https://www.stats.gov.cn/sj/zxfb/202301/t20230101_1.html'),
                         '2022-12')
        self.assertEqual(parse_fai_article(html),
                         {'CN_FAI_YTD': 572138.0, 'CN_FAI_YTD_YOY': 5.1})

    def test_fai_components_and_industrial_products(self):
        fai = ('1—6月份，全国固定资产投资（不含农户）226370亿元，同比下降5.7%。'
               '制造业投资下降1.2%。基础设施投资同比下降2.4%。'
               '1—6月份，民间固定资产投资同比下降8.5%。')
        parsed = parse_fai_article(fai)
        self.assertEqual(parsed['CN_FAI_MANUFACTURING_YTD_YOY'], -1.2)
        self.assertEqual(parsed['CN_FAI_INFRA_YTD_YOY'], -2.4)
        self.assertEqual(parsed['CN_FAI_PRIVATE_YTD_YOY'], -8.5)
        products = '''<table>
          <tr><td>粗钢（万吨）</td><td>8367</td><td>0.4</td><td>49995</td><td>-3.0</td></tr>
          <tr><td>原煤（万吨）</td><td>38088</td><td>-9.7</td><td>236508</td><td>-1.7</td></tr>
          <tr><td>新能源汽车（万辆）</td><td>162.4</td><td>29.4</td><td>739.9</td><td>6.0</td></tr>
        </table>'''
        industrial = parse_ip_article(products)
        self.assertEqual(industrial['CN_CRUDE_STEEL_OUTPUT_YTD'], 49995)
        self.assertEqual(industrial['CN_COAL_OUTPUT_MONTH_YOY'], -9.7)
        self.assertEqual(industrial['CN_NEV_OUTPUT_YTD_YOY'], 6.0)

    def test_fai_legacy_private_investment_amount_between_label_and_rate(self):
        html = ('1—6月份，全国固定资产投资（不含农户）281603亿元，同比下降3.1%。'
                '民间固定资产投资157867亿元，下降7.3%，降幅收窄2.3个百分点。')
        self.assertEqual(parse_fai_article(html)['CN_FAI_PRIVATE_YTD_YOY'], -7.3)

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

    def test_econ_parses_unemployment_and_trade(self):
        html = ('5月份，全国城镇调查失业率为5.1%，比上月下降0.1个百分点。'
                '货物进出口总额44516亿元，同比增长16.9%。其中，出口25878亿元，增长13.8%；'
                '进口18638亿元，增长21.5%。1—5月份，出口119137亿元，增长11.8%。')
        self.assertEqual(parse_econ_article(html),
                         {'CN_UNEMP_SURVEY': 5.1, 'CN_TRADE_YOY': 16.9,
                          'CN_EXPORT_YOY': 13.8, 'CN_IMPORT_YOY': 21.5})

    def test_econ_period_year_from_url_with_rollover(self):
        self.assertEqual(_econ_period('5月份国民经济运行总体平稳',
                                      'https://www.stats.gov.cn/sj/zxfb/202606/t20260616_1.html'),
                         '2026-05')
        # A true publication path can infer the year; the 2023-02 migration cannot.
        self.assertEqual(_econ_period('11月份国民经济运行稳中有进',
                                      'https://www.stats.gov.cn/sj/zxfb/202212/t20221215_1.html'),
                         '2022-11')
        self.assertIsNone(_econ_period('11月份国民经济运行稳中有进',
                                      'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1.html'))
        self.assertEqual(_econ_period('2026年上半年国民经济运行情况', 'https://x/202607/t2026_1.html'),
                         '2026-06')
        self.assertIsNone(_econ_period('能源生产情况', 'https://x/202607/t2026_1.html'))

    def test_period_mapping_titles(self):
        self.assertEqual(_month_period('2026年1—2月份社会消费品零售总额增长2%', '社会消费品零售总额'),
                         '2026-02')  # 1-2月合并记2月
        self.assertEqual(_month_period('2026年上半年社会消费品零售总额增长1.3%', '社会消费品零售总额'),
                         '2026-06')
        self.assertEqual(_gdp_period('2025年四季度和全年国内生产总值初步核算结果'), '2025-12')
        self.assertEqual(_gdp_period('2026年三季度和前三季度国内生产总值初步核算结果'), '2026-09')
        self.assertIsNone(_gdp_period('2026年国民经济运行情况'))

    @patch('services.china_macro_service.time.sleep', return_value=None)
    @patch('services.china_macro_service.requests.post')
    def test_year_search_rejects_relevant_old_release(self, mock_post, _mock_sleep):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    'ok': True, 'currentHits': 2, 'totalHits': 2,
                    'resultDocs': [
                        {'data': {'title': '2016年7月份居民消费价格同比上涨1.8%',
                                  'url': 'https://www.stats.gov.cn/sj/zxfb/201608/t_old.html'}},
                        {'data': {'title': '2026年7月份居民消费价格同比上涨0.5%',
                                  'url': 'https://www.stats.gov.cn/sj/zxfb/202608/t_new.html'}},
                    ],
                }

        mock_post.return_value = Response()
        found = discover_releases('cpi', 2026, end_year=2026, max_pages=1,
                                  sleep_seconds=0)
        self.assertEqual(set(found), {'2026-07'})

    @patch('services.china_macro_service.time.sleep', return_value=None)
    @patch('services.china_macro_service.requests.get')
    def test_public_release_list_fallback_maps_strict_period(self, mock_get, _mock_sleep):
        class Response:
            status_code = 200
            text = ('<a href="./202301/t20230110_1.html">'
                    '2022年12月份工业生产者出厂价格同比下降0.7%</a>')

            def raise_for_status(self):
                return None

        _RELEASE_LIST_PAGE_CACHE.clear()
        mock_get.return_value = Response()
        found = discover_release_list_releases('ppi', 2022, end_year=2022,
                                               max_pages=1, sleep_seconds=0)
        self.assertEqual(set(found), {'2022-12'})


if __name__ == '__main__':
    unittest.main()
