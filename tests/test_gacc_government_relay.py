"""Quarter-to-date is September cumulative, not publication October or a monthly split."""
import unittest
from services.china_external_service import parse_gacc_q3_government_relay

URL='https://gxt.hunan.gov.cn/gxt/xxgk_71033/gzdt/rdjj/202610/t20261015_34081504.html'


def fixture():
    return '''<meta name="PubDate" content="2026-10-15 10:03:22"><meta name="others" content="页面生成时间 2026-10-15 10:03:22">
    <div id="j-show-body"><p>今年前三季度我国货物贸易进出口39.94万亿元，同比增长18.8%，连续6个月增长。
    10月14日，国新办举行新闻发布会，海关总署介绍2026年前三季度我国货物贸易进出口情况。</p>
    <p>据海关统计，今年前三季度，我国货物贸易出口23.2万亿元，增长16.4%，进口16.74万亿元，增长22.3%。</p>
    <p>一季度增长15.3%，三季度增长22.3%。9月份进出口5.16万亿元，首次突破5万亿元，增长27.5%。
    其中，出口3.03万亿元，增长29.6%；进口2.13万亿元，增长24.6%。</p>
    <p>前三季度对东盟进出口6.84万亿元，增长22.7%，外商投资企业进出口11.69万亿元。</p></div>'''


class GaccGovernmentRelayTests(unittest.TestCase):
    def test_twelve_native_cny_fields_exact_and_no_fx_or_derived_balance(self):
        rows=parse_gacc_q3_government_relay(fixture(),'2026-09',URL)
        values={r['indicator_code']:r['value'] for r in rows}
        self.assertEqual(values,{'CN_GACC_TRADE_CNY_YTD':399400.,'CN_GACC_TRADE_CNY_YTD_YOY':18.8,
            'CN_GACC_EXPORT_CNY_YTD':232000.,'CN_GACC_EXPORT_CNY_YTD_YOY':16.4,
            'CN_GACC_IMPORT_CNY_YTD':167400.,'CN_GACC_IMPORT_CNY_YTD_YOY':22.3,
            'CN_GACC_TRADE_CNY_MONTH':51600.,'CN_GACC_TRADE_CNY_MONTH_YOY':27.5,
            'CN_GACC_EXPORT_CNY_MONTH':30300.,'CN_GACC_EXPORT_CNY_MONTH_YOY':29.6,
            'CN_GACC_IMPORT_CNY_MONTH':21300.,'CN_GACC_IMPORT_CNY_MONTH_YOY':24.6})
        self.assertTrue(all(r['period']=='2026-09' and r['frequency']=='monthly' and r['data_status']=='official_relayed' for r in rows))
        self.assertTrue(all('USD' not in r['indicator_code'] and 'BALANCE' not in r['indicator_code'] for r in rows))

    def test_original_release_and_relay_generation_are_distinct(self):
        rows=parse_gacc_q3_government_relay(fixture(),'2026-09',URL)
        self.assertTrue(all(r['release_date']=='2026-10-14' and r['source_page_created_date']=='2026-10-15' for r in rows))

    def test_wrong_year_scope_body_or_publication_period_is_rejected(self):
        for old,new in [('2026年前三季度','2025年前三季度'),('2026-10-15','2025-10-15'),
                        ('我国货物贸易','湖南货物贸易'),('id="j-show-body"','id="unknown"')]:
            with self.subTest(new=new),self.assertRaises(ValueError):
                parse_gacc_q3_government_relay(fixture().replace(old,new),'2026-09',URL)
        with self.assertRaises(ValueError):parse_gacc_q3_government_relay(fixture(),'2026-10',URL)

    def test_missing_monthly_component_is_not_filled_from_cumulative_or_total(self):
        with self.assertRaises(ValueError):
            parse_gacc_q3_government_relay(fixture().replace('进口2.13万亿元，增长24.6%','进口未公布'),'2026-09',URL)

    def test_declines_keep_negative_sign_and_yoy_is_reported_not_divided(self):
        rows=parse_gacc_q3_government_relay(fixture().replace('增长29.6%','下降29.6%'),'2026-09',URL)
        self.assertEqual(next(r['value'] for r in rows if r['indicator_code']=='CN_GACC_EXPORT_CNY_MONTH_YOY'),-29.6)


if __name__=='__main__':unittest.main()
