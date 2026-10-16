"""Explicit city monthly rates are not national rates, averages or allocated flows."""
import unittest

from services.china_macro_extended_service import parse_reported_city_survey_month_details
from services.china_macro_service import parse_econ_unemployment_observations


class CitySurveyHistoryTests(unittest.TestCase):
    def parse(self, text, year=2018):
        return parse_reported_city_survey_month_details('<p>' + text + '</p>', year, year_is_validated=True)

    def test_shared_quarter_month_list_has_its_own_city_values(self):
        rows = self.parse('1至3月份，全国城镇调查失业率分别为5.0%、5.0%和5.1%；'
                          '31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。')['rows']
        self.assertEqual(rows, [('2018-01', 'CN_UNEMP_31_CITIES', 4.9),
                                ('2018-02', 'CN_UNEMP_31_CITIES', 4.8),
                                ('2018-03', 'CN_UNEMP_31_CITIES', 4.9)])

    def test_combined_release_with_one_february_city_rate_does_not_create_january(self):
        rows = self.parse('1-2月份新增就业174万人。2月份，全国城镇调查失业率为5.3%；'
                          '31个大城市城镇调查失业率为5.0%。', 2019)['rows']
        self.assertEqual(rows, [('2019-02', 'CN_UNEMP_31_CITIES', 5.0)])

    def test_averages_ranges_and_mismatched_lists_remain_missing(self):
        for sentence in ('1至3月份，31个大城市城镇调查失业率平均为5.0%。',
                         '1至3月份，31个大城市城镇调查失业率为5.0%。',
                         '1至3月份，31个大城市城镇调查失业率分别为4.9%和5.0%。',
                         '31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。'):
            with self.subTest(sentence=sentence):
                self.assertEqual(self.parse(sentence)['rows'], [])

    def test_past_or_conflicting_year_is_not_reassigned(self):
        for prefix in ('2017年', '上年', '去年'):
            self.assertEqual(self.parse(prefix + '1至3月份，31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。')['rows'], [])

    def test_conflicting_duplicate_month_is_excluded(self):
        result = self.parse('3月份，31个大城市城镇调查失业率为4.9%。3月份，31个大城市城镇调查失业率为5.0%。')
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['conflicts'], [('2018-03', 'CN_UNEMP_31_CITIES')])

    def test_ingestion_never_adds_months_after_verified_release_period(self):
        html = '<p>1至3月份，31个大城市城镇调查失业率分别为4.9%、4.8%和4.9%。</p>'
        self.assertEqual(parse_econ_unemployment_observations(html, '2018-02'),
                         [('2018-01', 'CN_UNEMP_31_CITIES', 4.9), ('2018-02', 'CN_UNEMP_31_CITIES', 4.8)])

    def test_national_rates_are_not_copied_into_city_series(self):
        self.assertEqual(self.parse('1至3月份，全国城镇调查失业率分别为5.0%、5.0%和5.1%。')['rows'], [])

    def test_previous_month_comparison_does_not_shift_city_observation(self):
        html = ('<p>3月份，全国城镇调查失业率为5.9%，比2月份下降0.3个百分点；'
                '25-59岁群体人口调查失业率为5.4%，比2月份下降0.2个百分点。'
                '31个大城市城镇调查失业率为5.7%，与上月持平。</p>')
        rows = parse_reported_city_survey_month_details(html, 2020, year_is_validated=True)['rows']
        self.assertEqual(rows, [('2020-03', 'CN_UNEMP_31_CITIES', 5.7)])

    def test_full_width_digits_and_percent_keep_the_same_unit(self):
        self.assertEqual(self.parse('１、２月份，３１个大城市城镇调查失业率分别为４．９％和４．８％。')['rows'],
                         [('2018-01', 'CN_UNEMP_31_CITIES', 4.9), ('2018-02', 'CN_UNEMP_31_CITIES', 4.8)])

    def test_caller_must_validate_a_missing_source_year(self):
        self.assertEqual(parse_reported_city_survey_month_details(
            '<p>3月份，31个大城市城镇调查失业率为4.9%。</p>', 2018)['rows'], [])


if __name__ == '__main__':
    unittest.main()
