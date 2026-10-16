"""Household scopes, official population shares and survey breaks remain explicit."""
import unittest
from services.china_macro_extended_service import parse_annual_livelihood_article
from services.china_macro_dashboard_service import income_survey_groups


class AnnualLivelihoodHistoryTests(unittest.TestCase):
    def test_official_population_share_column_not_recomputed_from_counts(self):
        html = '<table><tr><td>2014年年末人口数及其构成 单位：万人</td></tr>'
        html += '<tr><td>指标</td><td>年末数（万人）</td><td>比重（%）</td></tr>'
        html += '<tr><td>其中：城镇</td><td>74916</td><td>54.77</td></tr>'
        html += '<tr><td>16-59岁（含不满60周岁）</td><td>91583</td><td>67.0</td></tr></table>'
        result = parse_annual_livelihood_article(html)
        self.assertEqual(result['CN_URBANIZATION_RATE'], 54.77)
        self.assertEqual(result['CN_WORKING_AGE_POP'], 91583)

    def test_unlabelled_third_column_or_rural_share_does_not_supply_urbanization(self):
        for heading, label in (('同比增长', '城镇'), ('比重', '乡村')):
            html = f'<table><tr><td>年末人口数 单位：万人</td></tr><tr><td>指标</td><td>年末数</td><td>{heading}</td></tr><tr><td>{label}</td><td>74916</td><td>54.77</td></tr></table>'
            self.assertNotIn('CN_URBANIZATION_RATE', parse_annual_livelihood_article(html))

    def test_rural_net_income_and_urban_median_are_not_national_values(self):
        values = parse_annual_livelihood_article('农村居民人均纯收入9892元。城镇居民人均可支配收入中位数26635元。')
        self.assertNotIn('CN_INCOME_RURAL', values)
        self.assertNotIn('CN_DISPOSABLE_INCOME_MEDIAN', values)

    def test_new_survey_urban_value_not_old_footnote_estimate(self):
        values = parse_annual_livelihood_article('<p>城镇居民人均可支配收入<sup>[34]</sup>28844元。</p><p>[34]按老口径推算，全年全国城镇居民人均可支配收入为29381元。</p>')
        self.assertEqual(values['CN_INCOME_URBAN'], 28844)

    def test_outside_migrant_wage_not_substituted_for_all_migrants(self):
        self.assertNotIn('CN_MIGRANT_MONTHLY_INCOME', parse_annual_livelihood_article('外出农民工月均收入水平2609元。'))
        self.assertEqual(parse_annual_livelihood_article('全国农民工人均月收入3072元。')['CN_MIGRANT_MONTHLY_INCOME'], 3072)

    def test_only_legacy_urban_line_breaks_without_mutating_the_group(self):
        group = {'code': 'employment', 'charts': [{'code': 'income_distribution', 'series': ['CN_INCOME_URBAN','CN_INCOME_RURAL']}]}
        legacy = {'CN_INCOME_URBAN': [{'period': '2013', 'value': 26955, 'source_url': 'https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1898455.html'}]}
        result = income_survey_groups([group], legacy)[0]['charts'][0]
        self.assertEqual(result['series_breaks'], {'CN_INCOME_URBAN': ['2014']})
        self.assertNotIn('series_breaks', group['charts'][0])
        modern = {'CN_INCOME_URBAN': [{'period': '2013', 'value': 26467, 'source_url': 'https://www.stats.gov.cn/yearbook.html'}]}
        self.assertEqual(income_survey_groups([group], modern), [group])


if __name__ == '__main__':
    unittest.main()
