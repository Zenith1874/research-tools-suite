# -*- coding: utf-8 -*-
import unittest

from services.housing_price_service import (
    extract_70city_search_releases, parse_70city_article, parse_dual_column_table,
    parse_period_from_title, _norm_city,
)
from services.anjuke_city_map import ANJUKE_CITY_SLUGS
from bs4 import BeautifulSoup

# 模拟统计局 70 城双列版式(城市名含全角空格是官方原样)
_TABLE = """
<table>
  <tr><td>城市</td><td>环比</td><td>同比</td><td>1-6月平均</td><td>城市</td><td>环比</td><td>同比</td><td>1-6月平均</td></tr>
  <tr><td>上月=100</td><td>上年同月=100</td><td>上年同期=100</td><td>上月=100</td><td>上年同月=100</td><td>上年同期=100</td></tr>
  <tr><td>北　　京</td><td>99.7</td><td>97.9</td><td>97.8</td><td>唐　　山</td><td>99.5</td><td>93.9</td><td>93.8</td></tr>
  <tr><td>上　　海</td><td>100.3</td><td>103.1</td><td>103.5</td><td>秦皇岛</td><td>99.2</td><td>92.9</td><td>93.0</td></tr>
</table>"""


class HousingParserTests(unittest.TestCase):
    def test_period_from_title(self):
        self.assertEqual(parse_period_from_title('2026年6月份70个大中城市商品住宅销售价格变动情况'), '2026-06')
        self.assertIsNone(parse_period_from_title('其他新闻'))

    def test_norm_city_removes_fullwidth_spaces(self):
        self.assertEqual(_norm_city('北　　京'), '北京')
        self.assertEqual(_norm_city('北　　京*'), '北京')

    def test_dual_column_table(self):
        t = BeautifulSoup(_TABLE, 'html.parser').find('table')
        d = parse_dual_column_table(t)
        self.assertEqual(d['北京'], (99.7, 97.9))
        self.assertEqual(d['唐山'], (99.5, 93.9))
        self.assertEqual(d['上海'], (100.3, 103.1))
        self.assertEqual(len(d), 4)
        self.assertNotIn('城市', d)          # 表头不混入

    def test_article_rejects_too_few_cities(self):
        # 只有 4 城的表 → 判定异常而不是静默入库
        html = '<html><body>' + _TABLE + _TABLE + '</body></html>'
        with self.assertRaises(ValueError):
            parse_70city_article(html)

    def test_old_six_table_layout_uses_labels_not_table_position(self):
        def full_table(label, mom, yoy):
            rows = ''.join(
                f'<tr><td>{city}</td><td>{mom}</td><td>{yoy}</td><td>100.0</td></tr>'
                for city in ANJUKE_CITY_SLUGS)
            return f'<table><tr><th>{label}</th></tr>{rows}</table>'

        new_residential = full_table('新建住宅价格指数', 100.8, 106.8)
        new_commodity = full_table('新建商品住宅价格指数', 101.0, 109.1)
        second = full_table('二手住宅价格指数', 100.3, 102.6)
        html = '<html><body>' + new_residential + new_commodity + second
        html += new_residential + new_commodity + second + '</body></html>'
        parsed = parse_70city_article(html)
        self.assertEqual(len(parsed['new']), 70)
        self.assertEqual(len(parsed['second']), 70)
        self.assertEqual(parsed['new']['北京'], (101.0, 109.1))
        self.assertEqual(parsed['second']['北京'], (100.3, 102.6))

    def test_search_release_extraction_is_strict_and_prefers_release_page(self):
        payload = {'resultDocs': [
            {'data': {'titleO': '2011年1月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/old.html'}},
            {'data': {'titleO': '2011年1月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/sj/zxfb/release.html'}},
            {'data': {'titleO': '#数据发布# 2011年1月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/sj/zxfb/social.html'}},
            {'data': {'titleO': '2010年12月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/sj/zxfb/old-regime.html'}},
        ]}
        rows = extract_70city_search_releases(payload, 2011, 2011)
        self.assertEqual(rows, [('2011-01', 'https://www.stats.gov.cn/sj/zxfb/release.html',
                                 '2011年1月份70个大中城市住宅销售价格变动情况')])

    def test_search_release_extraction_accepts_2016_hot_city_suffix(self):
        title = ('2016年9月份70个大中城市及10月上半月一线和热点二线城市'
                 '住宅销售价格变动情况')
        payload = {'resultDocs': [{'data': {
            'titleO': title,
            'url': 'https://www.stats.gov.cn/sj/zxfb/2016-09.html',
        }}]}
        rows = extract_70city_search_releases(payload, 2016, 2016)
        self.assertEqual(rows, [('2016-09',
                                 'https://www.stats.gov.cn/sj/zxfb/2016-09.html',
                                 title)])

    def test_search_release_extraction_filters_by_year_window(self):
        # 窗口外的年份(2010/2012)必须被排除,只保留 2011。
        payload = {'resultDocs': [
            {'data': {'titleO': '2010年12月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/sj/zxfb/201012.html'}},
            {'data': {'titleO': '2011年1月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/sj/zxfb/201101.html'}},
            {'data': {'titleO': '2012年1月份70个大中城市住宅销售价格变动情况',
                      'url': 'https://www.stats.gov.cn/sj/zxfb/201201.html'}},
        ]}
        rows = extract_70city_search_releases(payload, start_year=2011, end_year=2011)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], '2011-01')

    def test_article_reads_caption_before_wrapping_div(self):
        def wrapped_table(caption, mom, yoy):
            rows = ''.join(
                f'<tr><td>{city}</td><td>{mom}</td><td>{yoy}</td><td>100.0</td></tr>'
                for city in ANJUKE_CITY_SLUGS)
            return f'<p>{caption}</p><div><table>{rows}</table></div>'

        html = '<html><body>'
        html += wrapped_table('表2 新建商品住宅销售价格指数', 100.4, 104.2)
        html += wrapped_table('表3 二手住宅销售价格指数', 99.8, 101.5)
        html += '</body></html>'
        parsed = parse_70city_article(html)
        self.assertEqual(len(parsed['new']), 70)
        self.assertEqual(len(parsed['second']), 70)
        self.assertEqual(parsed['new']['北京'], (100.4, 104.2))
        self.assertEqual(parsed['second']['北京'], (99.8, 101.5))


if __name__ == '__main__':
    unittest.main()
