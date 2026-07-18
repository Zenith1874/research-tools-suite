import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.macro_analytics_service import (
    annualized_change, build_housing_analytics, build_macro_analytics_payload,
    build_inversion_analysis, calculate_sahm, cumulative_share, curve_snapshots,
    cross_correlation, _diffusion_from_rows, identify_inversion_episodes,
    interest_burden_series, loan_stock_structure, pct_rank, rolling_z,
    land_fiscal_dependency, preferred_official_yoy, ytd_to_monthly_increment, yoy,
)
from services.whats_new_service import make_anomaly_event


class StatisticalPrimitiveTests(unittest.TestCase):
    def test_pct_rank_inclusive(self):
        self.assertEqual(pct_rank([1, 2, 3, 4], 3), 75.0)

    def test_rolling_z_latest(self):
        self.assertAlmostEqual(rolling_z([1, 2, 3], 3), (3 - 2) / math.sqrt(2 / 3), places=4)

    def test_annualized_change(self):
        monthly = [100 * (1.01 ** i) for i in range(13)]
        self.assertAlmostEqual(annualized_change(monthly, 3), (1.01 ** 12 - 1) * 100, places=4)

    def test_yoy_does_not_bridge_missing_calendar_period(self):
        rows = [{'period': '2024-01', 'value': 100}, {'period': '2025-02', 'value': 110}]
        self.assertEqual(yoy(rows, 12), [])

    def test_cross_correlation_positive_lag_means_x_leads_y(self):
        x = list(range(40))
        y = [0, 0, 0] + x[:-3]
        result = cross_correlation(x, y, 6, min_n=24)
        self.assertEqual(result['peak_lag'], 3)
        self.assertAlmostEqual(result['peak_corr'], 1.0, places=4)

    def test_sahm_three_month_average_trigger(self):
        values = [4.0] * 14 + [4.3, 4.6, 4.9]
        rows = [{'period': f'2024-{i+1:02d}', 'value': v} for i, v in enumerate(values[:12])]
        rows += [{'period': f'2025-{i+1:02d}', 'value': v} for i, v in enumerate(values[12:])]
        result = calculate_sahm(rows)
        self.assertEqual(result[-1]['value'], 0.6)
        self.assertTrue(result[-1]['triggered'])

    def test_inversion_ignores_one_month_fragment(self):
        rows = [{'period': f'2024-{i+1:02d}', 'value': v}
                for i, v in enumerate([1, -0.1, 0.1, -0.2, -0.4, -0.3, 0.2])]
        episodes = identify_inversion_episodes(rows)
        self.assertEqual(len(episodes), 1)
        self.assertEqual((episodes[0]['start'], episodes[0]['end']), ('2024-04', '2024-06'))

    def test_insufficient_cross_correlation_guard(self):
        result = cross_correlation(range(20), range(20), 3, min_n=24)
        self.assertEqual(result['data_status'], 'insufficient_sample')

    def test_diffusion_index_counts_rising_cities(self):
        # 上月=100 口径：>100 上涨，<100 下跌，==100 持平
        rows = [{'period': '2026-06', 'value': v} for v in (101.0, 100.5, 100.0, 99.5, 99.0)]
        series = _diffusion_from_rows(rows)
        self.assertEqual(len(series), 1)
        point = series[0]
        self.assertEqual((point['up'], point['flat'], point['down']), (2, 1, 2))
        self.assertEqual(point['value'], 40.0)  # 2/5 上涨

    def test_diffusion_index_separates_periods(self):
        rows = [{'period': '2026-05', 'value': 101.0}, {'period': '2026-05', 'value': 99.0},
                {'period': '2026-06', 'value': 101.0}, {'period': '2026-06', 'value': 101.0}]
        series = _diffusion_from_rows(rows)
        self.assertEqual([p['value'] for p in series], [50.0, 100.0])

    def test_ytd_increment_reset_gap_and_year_boundary(self):
        rows = [{'period': '2024-12', 'value': 12}, {'period': '2025-01', 'value': 2},
                {'period': '2025-02', 'value': 5}, {'period': '2025-04', 'value': 9},
                {'period': '2025-05', 'value': 12}]
        self.assertEqual(ytd_to_monthly_increment(rows), [
            {'period': '2025-01', 'value': 2}, {'period': '2025-02', 'value': 3},
            {'period': '2025-05', 'value': 3}])

    def test_february_combined_yoy_does_not_invent_january(self):
        rows = [{'period': '2025-02', 'value': 100}, {'period': '2026-02', 'value': 90}]
        self.assertEqual(yoy(rows, 12), [{'period': '2026-02', 'value': -10.0}])
        self.assertEqual(yoy(rows + [{'period': '2026-03', 'value': 95}], 12),
                         [{'period': '2026-02', 'value': -10.0}])

    def test_cumulative_share_requires_both_same_month(self):
        hh = [{'period': '2026-01', 'value': 2}, {'period': '2026-02', 'value': 3}]
        corp = [{'period': '2026-01', 'value': 6}, {'period': '2026-03', 'value': 7}]
        self.assertEqual(cumulative_share(hh, corp), [
            {'period': '2026-01', 'value': 25.0, 'household': 2, 'corporate': 6}])

    def test_curve_snapshots_align_three_exact_months(self):
        periods = [f'2025-{m:02d}' for m in range(1, 13)] + ['2026-01']
        data = {tenor: [{'period': p, 'value': base + i / 100} for i, p in enumerate(periods)]
                for tenor, base in zip(('3M','2Y','5Y','10Y','30Y'), (1,2,3,4,5))}
        snap = curve_snapshots(data)
        self.assertEqual(snap['periods'], {'latest':'2026-01','m3_ago':'2025-10','y1_ago':'2025-01'})
        self.assertEqual(snap['latest'][0], 1.12)
        self.assertEqual(snap['m3_ago'][4], 5.09)

    def test_interest_burden_aligns_same_quarter(self):
        interest = [{'period':'2025-01-01','value':100}, {'period':'2025-04-01','value':120}]
        receipts = [{'period':'2025-01-01','value':1000}, {'period':'2025-07-01','value':1100}]
        self.assertEqual(interest_burden_series(interest, receipts),
                         [{'period':'2025-01-01','value':10.0}])

    def test_official_yoy_is_preferred_over_level_ratio(self):
        official = [{'period': '2022-02', 'value': -9.6}]
        levels = [{'period': '2021-02', 'value': 100}, {'period': '2022-02', 'value': 80}]
        selected, derived, source = preferred_official_yoy(official, levels)
        self.assertEqual(selected, official)
        self.assertEqual(derived[0]['value'], -20.0)
        self.assertEqual(source, 'official')

    def test_land_dependency_uses_december_only(self):
        land = [{'period':'2024-11','value':50}, {'period':'2024-12','value':80}]
        fund = [{'period':'2024-11','value':70}, {'period':'2024-12','value':100}]
        general = [{'period':'2024-12','value':300}]
        fund_share, combined = land_fiscal_dependency(land, fund, general)
        self.assertEqual(fund_share, [{'period':'2024','value':80.0}])
        self.assertEqual(combined, [{'period':'2024','value':20.0}])

    def test_shared_inversion_analysis_supports_both_spreads(self):
        spread = [{'period':f'2025-{m:02d}','value':v} for m,v in enumerate((1,-.2,-.3,1),1)]
        rec = [{'period':f'2025-{m:02d}','value':0} for m in range(1,13)]
        a = build_inversion_analysis(spread, rec, 'T10Y2Y倒挂经验表', 'T10Y2Y')
        b = build_inversion_analysis(spread, rec, 'T10Y3M倒挂经验表', 'T10Y3M')
        self.assertEqual(a['value']['episodes'], b['value']['episodes'])
        self.assertIn('T10Y2Y', a['method']); self.assertIn('T10Y3M', b['method'])

    def test_loan_stock_structure_requires_all_six_components(self):
        row = {'loan':100, 'loan_hh_st_bal':10, 'loan_hh_lt_bal':20,
               'loan_corp_st_bal':15, 'loan_corp_lt_bal':40,
               'loan_bill_bal':10, 'loan_nbfi_bal':5}
        self.assertEqual(sum(x['value'] for x in loan_stock_structure(row)), 100.0)
        row['loan_bill_bal'] = None
        self.assertIsNone(loan_stock_structure(row))

    def test_anomaly_probe_triggers_only_above_threshold(self):
        normal = [{'period': f'2020-{i+1:02d}', 'value': float(i % 3)} for i in range(12)]
        self.assertIsNone(make_anomaly_event('x', '指标', normal, 12, 2.0))
        extreme = [{'period': f'{2020+i//12:04d}-{i%12+1:02d}', 'value': 0.0} for i in range(59)]
        extreme.append({'period': '2024-12', 'value': 10.0})
        event = make_anomaly_event('x', '指标', extreme, 60, 2.0)
        self.assertIsNotNone(event)
        self.assertGreater(event['z_score'], 2.0)


class PayloadContractTests(unittest.TestCase):
    def _db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript('''
        CREATE TABLE monthly_data(month TEXT PRIMARY KEY,M1y REAL,M2y REAL,SFy REAL,loany REAL,
          loan REAL,loan_hh_ytd REAL,loan_corp_ytd REAL,loan_hh_lt_ytd REAL,
          loan_hh_st_bal REAL,loan_hh_lt_bal REAL,loan_corp_st_bal REAL,
          loan_corp_lt_bal REAL,loan_bill_bal REAL,loan_nbfi_bal REAL);
        CREATE TABLE china_rates_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE fiscal_budget_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE fiscal_debt_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE housing_national_observations(indicator_code TEXT,period TEXT,value REAL);
        CREATE TABLE housing_city_observations(city TEXT,period TEXT,indicator_code TEXT,value REAL);
        CREATE TABLE us_macro_observations(indicator_code TEXT,period TEXT,value REAL);
        ''')
        conn.commit(); conn.close()

    def test_empty_payload_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'x.db'); self._db(path)
            payload = build_macro_analytics_payload(path)
        for section in ('china', 'us', 'cross', 'housing'):
            for item in payload[section].get('positioning', []) + payload[section].get('analyses', []):
                for key in ('method','sample_start','sample_end','n_obs','data_status'):
                    self.assertIn(key, item)

    def test_sparse_social_financing_position_is_guarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'sf.db'); self._db(path)
            conn = sqlite3.connect(path)
            conn.executemany('INSERT INTO monthly_data(month,SFy) VALUES (?,?)',
                             [(f'2025-{month:02d}', 8.0) for month in range(1, 13)])
            conn.commit(); conn.close()
            payload = build_macro_analytics_payload(path)
        card = next(item for item in payload['china']['positioning']
                    if item['title'] == '社融存量同比定位')
        self.assertEqual(card['data_status'], 'insufficient_sample')
        self.assertIsNone(card['value'])

    def test_housing_diffusion_analytics_from_city_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'h.db'); self._db(path)
            conn = sqlite3.connect(path)
            cities = ['北京', '上海', '广州', '深圳', '成都', '西安', '大连', '厦门']
            for pi, period in enumerate(('2026-05', '2026-06')):
                for ci, city in enumerate(cities):
                    # 让一线城市多数上涨、其余多数下跌，构造可判定的分化
                    tier1 = city in ('北京', '上海', '广州', '深圳')
                    val = 100.5 if tier1 else 99.5
                    conn.execute("INSERT INTO housing_city_observations VALUES(?,?,?,?)",
                                 (city, period, 'new_home_mom_idx', val))
                    conn.execute("INSERT INTO housing_city_observations VALUES(?,?,?,?)",
                                 (city, period, 'second_home_mom_idx', val - 0.3))
            conn.commit(); conn.close()
            block = build_housing_analytics(path)
        titles = {i['title'] for i in block['positioning'] + block['analyses']}
        self.assertIn('70城新房扩散指数', titles)
        split = next(i for i in block['analyses'] if i['title'] == '一线-非一线分化')
        self.assertGreater(split['value'], 0)  # 一线扩散(100%) 高于其余(0%)

    def test_housing_triangle_payload_contract_when_data_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'triangle.db'); self._db(path)
            block = build_macro_analytics_payload(path)['housing']
        by_title = {item['title']: item for item in block['positioning'] + block['analyses']}
        for title in ('商品房销售面积累计同比', '土地出让收入累计同比',
                      '销售与房价扩散领先滞后', '销售与土地收入领先滞后',
                      '销售额与土地收入24月滚动相关', '土地财政依赖度'):
            self.assertIn(title, by_title)
            for field in ('method','sample_start','sample_end','n_obs','data_status'):
                self.assertIn(field, by_title[title])


if __name__ == '__main__':
    unittest.main()
