# -*- coding: utf-8 -*-
import unittest

from services.housing_price_service import (
    parse_70city_article, parse_dual_column_table, parse_period_from_title, _norm_city,
)
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


if __name__ == '__main__':
    unittest.main()
