# -*- coding: utf-8 -*-
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.housing_scenario_service import (
    _add_months,
    _forward_fill_isolated_listing_gaps,
    backtest_scenarios,
    build_housing_scenario_comparison,
    build_housing_scenario_payload,
    build_scenarios,
    build_sparse_scenarios,
    list_housing_scenario_cities,
    monthly_momentum,
    sparse_trailing_momentum,
    simulate_sensitivity,
)


def synthetic_series(months=84, rates=None):
    rates = rates or [0.2, -0.1, 0.3, -0.2]
    index = 100.0
    rows = []
    for step in range(months):
        index *= 1 + rates[step % len(rates)] / 100
        rows.append({'period': _add_months('2018-01', step), 'index': index})
    return rows


class HousingScenarioPureFunctionTests(unittest.TestCase):
    def test_listing_forward_fill_is_limited_to_one_missing_month(self):
        one_gap = _forward_fill_isolated_listing_gaps([
            {'city': '常州', 'period': '2015-02', 'avg_price': 6384},
            {'city': '常州', 'period': '2015-04', 'avg_price': 10328},
        ])
        self.assertEqual([row['period'] for row in one_gap],
                         ['2015-02', '2015-03', '2015-04'])
        self.assertTrue(one_gap[1]['imputed'])
        self.assertEqual(one_gap[1]['avg_price'], 6384)
        self.assertEqual(one_gap[1]['mom_pct'], 0.0)

        long_gap = _forward_fill_isolated_listing_gaps([
            {'city': '常州', 'period': '2015-02', 'avg_price': 6384},
            {'city': '常州', 'period': '2015-05', 'avg_price': 6998},
        ])
        self.assertEqual([row['period'] for row in long_gap],
                         ['2015-02', '2015-05'])
        self.assertFalse(any(row.get('imputed') for row in long_gap))

    def test_monthly_momentum_is_compound_rate(self):
        series = [
            {'period': '2024-01', 'index': 100.0},
            {'period': '2024-02', 'index': 110.0},
            {'period': '2024-03', 'index': 121.0},
        ]
        self.assertAlmostEqual(monthly_momentum(series, 2), 10.0, places=4)

    def test_scenario_labels_are_sorted_by_observed_speed(self):
        series = []
        index = 100.0
        for step in range(49):
            if step < 37:
                rate = 1.0
            elif step < 43:
                rate = -1.0
            else:
                rate = -2.0
            index *= 1 + rate / 100
            series.append({'period': _add_months('2020-01', step), 'index': index})
        scenarios = build_scenarios(series, horizon=12)
        by_key = {item['key']: item for item in scenarios}
        self.assertGreaterEqual(by_key['optimistic']['monthly_rate'],
                                by_key['base']['monthly_rate'])
        self.assertGreaterEqual(by_key['base']['monthly_rate'],
                                by_key['stress']['monthly_rate'])
        self.assertEqual(by_key['stress']['window_months'], 6)

    def test_sparse_annual_momentum_uses_actual_elapsed_months(self):
        series = [
            {'period': '2021-12', 'index': 100.0},
            {'period': '2022-12', 'index': 110.0},
            {'period': '2023-12', 'index': 121.0},
            {'period': '2024-12', 'index': 133.1},
            {'period': '2025-12', 'index': 146.41},
            {'period': '2026-07', 'index': 153.0},
        ]
        item = sparse_trailing_momentum(series, 36)
        self.assertEqual(item['start_period'], '2023-12')
        self.assertEqual(item['actual_months'], 31)
        scenarios = build_sparse_scenarios(series, horizon=12, windows=(12, 24, 36))
        self.assertEqual(len([row for row in scenarios if not row.get('status')]), 3)
        self.assertTrue(all(len(row['path']) == 12 for row in scenarios))
        # 历史输入仍只有真实年点；逐月点只属于未来 scenario。
        self.assertEqual(len(series), 6)
        self.assertFalse(any(row['period'] == '2024-01' for row in series))

    def test_contradictory_custom_rates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '乐观'):
            build_scenarios(synthetic_series(), horizon=12,
                            overrides={'optimistic': -1, 'base': 0, 'stress': -2})

    def test_simulation_is_reproducible_and_quantiles_are_ordered(self):
        series = synthetic_series()
        first = simulate_sensitivity(series, 0.1, 12, simulations=500, seed=7)
        second = simulate_sensitivity(series, 0.1, 12, simulations=500, seed=7)
        self.assertEqual(first['points'], second['points'])
        self.assertEqual(first['data_status'], 'scenario')
        for point in first['points']:
            self.assertLessEqual(point['p10'], point['p50'])
            self.assertLessEqual(point['p50'], point['p90'])

    def test_backtest_reports_derived_contract(self):
        result = backtest_scenarios(synthetic_series(120), horizon=24)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['data_status'], 'derived')
        self.assertGreater(result['n_obs'], 0)
        self.assertLess(result['latest']['as_of'], result['latest']['target_period'])
        self.assertTrue(math.isfinite(result['median_absolute_error_pp']))


class HousingScenarioDatabaseTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        handle.close()
        self.db_path = handle.name
        conn = sqlite3.connect(self.db_path)
        conn.execute('''CREATE TABLE housing_city_observations (
          city TEXT,period TEXT,indicator_code TEXT,value REAL,data_status TEXT,
          source_name TEXT,source_url TEXT,
          UNIQUE(city,period,indicator_code))''')
        conn.execute('''CREATE TABLE city_indicator_observations (
          region_code TEXT,indicator_code TEXT,period TEXT,value REAL)''')
        for city in ('厦门', '北京'):
            for step in range(84):
                period = _add_months('2019-01', step)
                rate = (0.35 if step < 36 else -0.25 if step < 72 else 0.05)
                for code in ('second_home_mom_idx', 'new_home_mom_idx'):
                    conn.execute('INSERT INTO housing_city_observations VALUES (?,?,?,?,?,?,?)',
                                 (city, period, code, 100 + rate, 'official',
                                  '国家统计局', f'https://example.test/{period}'))
        # Rename boundary: one canonical city, not two catalog cities.
        for step in range(6):
            conn.execute('INSERT INTO housing_city_observations VALUES (?,?,?,?,?,?,?)',
                         ('襄樊', _add_months('2011-01', step), 'second_home_mom_idx',
                          100.1, 'official', '国家统计局', 'https://example.test/old'))
        for step in range(6, 48):
            conn.execute('INSERT INTO housing_city_observations VALUES (?,?,?,?,?,?,?)',
                         ('襄阳', _add_months('2011-01', step), 'second_home_mom_idx',
                          100.1, 'official', '国家统计局', 'https://example.test/new'))
        for year in range(2019, 2026):
            conn.execute('INSERT INTO city_indicator_observations VALUES (?,?,?,?)',
                         ('350200', 'avg_wage', str(year), 60000 + (year - 2019) * 4000))
        conn.commit()
        conn.close()
        listing_rows = []
        price = 8000.0
        for step in range(12):
            period = _add_months('2016-01', step)
            price *= 1.002
            listing_rows.append({
                'city': '常州', 'period': period, 'avg_price': round(price, 2),
                'mom_pct': 0.2, 'yoy_pct': None,
                'data_status': 'listing_reference',
                'source_url': f'https://example.test/cz/{period}',
            })
        # 2017-01 故意缺失：新版规则只对这种孤立单月缺口以前值法补齐并标记。
        for step in range(84):
            period = _add_months('2017-02', step)
            price *= 1 + (0.3 if step < 42 else -0.2) / 100
            listing_rows.append({
                'city': '常州', 'period': period, 'avg_price': round(price, 2),
                'mom_pct': 0.3 if step < 42 else -0.2, 'yoy_pct': None,
                'data_status': 'listing_reference',
                'source_url': f'https://example.test/cz/{period}',
            })
        self.listing_payload = {
            'city_history': {'常州': listing_rows},
            'latest_period': listing_rows[-1]['period'], 'warnings': [],
        }
        yearly = {}
        cities = ('北京', '上海', '广州', '深圳', '厦门',
                  '南京', '合肥', '常州', '苏州', '无锡')
        for city_index, city in enumerate(cities):
            rows = []
            for year in range(2010, 2027):
                period = f'{year}-12' if year < 2026 else '2026-07'
                rows.append({
                    'city': city, 'year': year, 'period': period,
                    'avg_price': 10000 + city_index * 700 + (year - 2010) * 350,
                    'source_change_pct': None,
                    'data_status': ('listing_year_snapshot' if city == '上海'
                                    else 'listing_year_end_from_monthly'),
                    'source_grain': ('ranking_page_snapshot' if city == '上海'
                                     else 'monthly_year_end'),
                    'source_url': 'https://www.anjuke.com/fangjia/',
                    'detail_url': f'https://example.test/{city}/{year}',
                })
            yearly[city] = rows
        self.listing_payload['yearly_history_by_city'] = yearly

    def tearDown(self):
        Path(self.db_path).unlink(missing_ok=True)

    def test_catalog_merges_xiangfan_and_xiangyang(self):
        payload = list_housing_scenario_cities(self.db_path)
        names = [item['city'] for item in payload['cities']]
        self.assertIn('襄阳', names)
        self.assertNotIn('襄樊', names)
        row = next(item for item in payload['cities'] if item['city'] == '襄阳')
        self.assertEqual(row['second_records'], 48)

    def test_payload_has_source_simulation_backtest_and_method(self):
        payload = build_housing_scenario_payload(
            self.db_path, '厦门', horizon=24, simulations=300)
        series = payload['series']['second']
        self.assertEqual(payload['data_status'], 'scenario')
        self.assertEqual(series['status'], 'ok')
        self.assertEqual(series['source']['data_status'], 'official')
        self.assertEqual(series['simulation']['simulations'], 300)
        self.assertEqual(series['backtest']['data_status'], 'derived')
        self.assertIn('scenario', payload['method'])
        self.assertEqual(payload['structural_drivers']['status'], 'ok')
        self.assertEqual(len(series['structural_scenarios']), 3)
        self.assertIn('structural_equity', series)
        momentum_by = {item['key']: item for item in series['scenarios']}
        structural_by = {item['key']: item for item in series['structural_scenarios']}
        self.assertAlmostEqual(structural_by['base']['annualised'],
                               momentum_by['base']['annualised'])
        rates = [item['monthly_rate'] for item in series['scenarios']]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_comparison_keeps_city_rows_separate(self):
        payload = build_housing_scenario_comparison(
            self.db_path, cities=['厦门', '北京'], kind='second', horizon=12)
        self.assertEqual([row['city'] for row in payload['rows']], ['厦门', '北京'])
        self.assertTrue(all(row['status'] == 'ok' for row in payload['rows']))
        self.assertTrue(all(len(row['structural_scenarios']) == 3
                            for row in payload['rows']))
        self.assertTrue(all('driver_coverage' in row for row in payload['rows']))

    def test_end_period_mode_reaches_2030_from_each_source_latest_period(self):
        official = build_housing_scenario_payload(
            self.db_path, '厦门', horizon=120, end_period='2030-12', simulations=300)
        self.assertEqual(official['end_period'], '2030-12')
        self.assertEqual(official['horizon_months'], 60)
        self.assertEqual(official['series']['second']['scenarios'][0]['path'][-1]['period'],
                         '2030-12')

        listing = build_housing_scenario_payload(
            self.db_path, '常州', source='anjuke', horizon=120,
            end_period='2030-12', simulations=300, listing_payload=self.listing_payload)
        self.assertEqual(listing['end_period'], '2030-12')
        self.assertEqual(listing['series']['listing']['scenarios'][0]['path'][-1]['period'],
                         '2030-12')

        comparison = build_housing_scenario_comparison(
            self.db_path, cities=['厦门', '北京'], kind='second', horizon=120,
            end_period='2030-12')
        self.assertEqual(comparison['end_period'], '2030-12')
        for row in comparison['rows']:
            self.assertTrue(all(item['end_period'] == '2030-12'
                                for item in row['scenarios']))

    def test_anjuke_catalog_forward_fills_one_isolated_month_and_marks_it(self):
        payload = list_housing_scenario_cities(
            self.db_path, source='anjuke', listing_payload=self.listing_payload)
        self.assertEqual(payload['data_status'], 'listing_reference')
        self.assertEqual(payload['city_count'], 15)
        self.assertEqual(payload['available_city_count'], 1)
        self.assertEqual(payload['tracked_city_count'], 15)
        self.assertEqual(payload['added_cities'], ['武汉', '长沙', '成都', '杭州', '福州'])
        row = next(item for item in payload['cities'] if item['city'] == '常州')
        self.assertEqual(row['city'], '常州')
        self.assertEqual(row['status'], 'available')
        self.assertEqual(row['available_start'], '2016-01')
        self.assertEqual(row['sample_start'], '2016-01')
        self.assertEqual(row['contiguous_records'], 97)
        self.assertEqual(row['imputed_records'], 1)
        self.assertEqual(row['imputed_periods'], ['2017-01'])
        self.assertEqual(row['excluded_before_latest_gap'], 0)
        wuhan = next(item for item in payload['cities'] if item['city'] == '武汉')
        self.assertEqual(wuhan['status'], 'missing')
        self.assertEqual(wuhan['listing_records'], 0)

    def test_anjuke_payload_keeps_listing_reference_separate_from_official_series(self):
        payload = build_housing_scenario_payload(
            self.db_path, '常州', source='anjuke', horizon=24,
            simulations=300, listing_payload=self.listing_payload)
        self.assertEqual(payload['history_source'], 'anjuke')
        self.assertEqual(payload['history_data_status'], 'listing_reference')
        self.assertEqual(set(payload['series']), {'listing'})
        series = payload['series']['listing']
        self.assertEqual(series['status'], 'ok')
        self.assertEqual(series['source']['data_status'], 'listing_reference')
        self.assertEqual(series['sample_start'], '2016-01')
        self.assertEqual(series['n_obs'], 97)
        self.assertEqual(series['value_kind'], 'price_level')
        self.assertAlmostEqual(series['current']['price'],
                               self.listing_payload['city_history']['常州'][-1]['avg_price'])
        self.assertIn('price', series['scenarios'][0]['path'][0])
        self.assertEqual(series['imputation']['count'], 1)
        self.assertEqual(series['imputation']['periods'], ['2017-01'])
        imputed = next(point for point in series['points']
                       if point['period'] == '2017-01')
        previous = next(point for point in series['points']
                        if point['period'] == '2016-12')
        self.assertTrue(imputed['imputed'])
        self.assertEqual(imputed['data_status'], 'derived_imputed')
        self.assertEqual(imputed['price'], previous['price'])
        self.assertIsNone(payload['valuation_anchor'])
        self.assertTrue(any('不写入主库' in note for note in payload['caveats']))
        self.assertTrue(any('前值法' in note for note in payload['caveats']))
        conn = sqlite3.connect(self.db_path)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertNotIn('anjuke_city_listings', tables)

    def test_anjuke_comparison_uses_listing_kind(self):
        payload = build_housing_scenario_comparison(
            self.db_path, cities=['常州'], source='anjuke', horizon=12,
            listing_payload=self.listing_payload)
        self.assertEqual(payload['kind'], 'listing')
        self.assertEqual(payload['history_data_status'], 'listing_reference')
        self.assertEqual(payload['rows'][0]['status'], 'ok')
        self.assertIsNotNone(payload['rows'][0]['current_price'])
        for scenario in payload['rows'][0]['scenarios']:
            self.assertIsNotNone(scenario['end_price'])
            expected = payload['rows'][0]['current_price'] * (
                1 + scenario['end_vs_now'] / 100)
            self.assertAlmostEqual(scenario['end_price'], expected, delta=1.0)

    def test_anjuke_yearly_catalog_and_payload_include_shanghai_without_month_fill(self):
        catalog = list_housing_scenario_cities(
            self.db_path, source='anjuke_yearly', listing_payload=self.listing_payload)
        self.assertEqual(catalog['city_count'], 15)
        self.assertEqual(catalog['available_city_count'], 10)
        self.assertEqual(catalog['history_grain'], 'annual')
        self.assertIn('上海', [row['city'] for row in catalog['cities']])
        self.assertEqual(catalog['missing_cities'], ['武汉', '长沙', '成都', '杭州', '福州'])

        payload = build_housing_scenario_payload(
            self.db_path, '上海', source='anjuke_yearly', horizon=24,
            listing_payload=self.listing_payload)
        series = payload['series']['listing']
        self.assertEqual(payload['history_data_status'], 'listing_annual_reference')
        self.assertEqual(series['history_grain'], 'annual')
        self.assertEqual(series['n_obs'], 17)
        self.assertEqual(series['sample_start'], '2010-12')
        self.assertFalse(any(point['period'] == '2011-01' for point in series['points']))
        self.assertEqual(series['momentum_windows']['36m']['actual_months'], 31)
        self.assertEqual(series['simulation']['status'], 'not_applicable')
        self.assertEqual(series['backtest']['status'], 'not_applicable')
        self.assertEqual(series['imputation']['count'], 0)
        self.assertEqual(series['source']['source_grain'], 'ranking_page_snapshot')
        self.assertTrue(all('price' in point for item in series['scenarios']
                            for point in item['path']))

    def test_anjuke_yearly_comparison_keeps_fifteen_city_rows_and_missingness(self):
        payload = build_housing_scenario_comparison(
            self.db_path, source='anjuke_yearly', horizon=12,
            listing_payload=self.listing_payload)
        self.assertEqual(payload['history_grain'], 'annual')
        self.assertEqual(len(payload['rows']), 15)
        self.assertTrue(all(row['status'] == 'ok' for row in payload['rows'][:10]))
        self.assertTrue(all(row['current_price'] is not None for row in payload['rows'][:10]))
        self.assertTrue(all(row['status'] == 'insufficient_history'
                            for row in payload['rows'][10:]))
        self.assertTrue(all(row['n_obs'] == 0 for row in payload['rows'][10:]))
        demographic = payload['demographic_capacity']
        self.assertEqual(demographic['coverage']['tracked_cities'], 15)
        self.assertEqual(demographic['target_years'], [2025, 2030, 2040, 2050])
        self.assertEqual(len(demographic['national']['scenarios']), 3)

    def test_demographic_assumptions_are_passed_without_changing_price_horizon(self):
        baseline = build_housing_scenario_comparison(
            self.db_path, cities=['常州'], source='anjuke', horizon=24,
            listing_payload=self.listing_payload)
        payload = build_housing_scenario_comparison(
            self.db_path, cities=['常州'], source='anjuke', horizon=24,
            listing_payload=self.listing_payload,
            formation_adjustments={'optimistic': 20, 'base': 5, 'stress': -25})
        parameters = payload['demographic_capacity']['parameters']
        self.assertEqual(parameters['formation_adjustment_2050_pct'],
                         {'optimistic': 20.0, 'base': 5.0, 'stress': -25.0})
        self.assertEqual(payload['horizon_months'], 24)
        self.assertEqual(payload['rows'][0]['scenarios'][0]['end_period'],
                         baseline['rows'][0]['scenarios'][0]['end_period'])
        with self.assertRaisesRegex(ValueError, '乐观'):
            build_housing_scenario_comparison(
                self.db_path, cities=['常州'], source='anjuke', horizon=24,
                listing_payload=self.listing_payload,
                formation_adjustments={'optimistic': -20, 'base': 0, 'stress': -10})

    def test_official_comparison_does_not_invent_absolute_prices(self):
        payload = build_housing_scenario_comparison(
            self.db_path, cities=['北京'], source='official', horizon=12)
        row = payload['rows'][0]
        self.assertIsNone(row['current_price'])
        self.assertTrue(all(item['end_price'] is None for item in row['scenarios']))

    def test_unknown_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'source'):
            list_housing_scenario_cities(self.db_path, source='unknown')


class HousingScenarioPageContractTests(unittest.TestCase):
    def test_housing_page_makes_national_and_city_2030_scenarios_visible(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / 'static' / 'housing.html').read_text(encoding='utf-8')
        for token in ('id="scenario-2030-quick"',
                      'id="city-scenario-2030"',
                      'id="national-scenario-2030"',
                      '/api/housing-scenario/compare?',
                      "horizon:'2030'",
                      '十五城挂牌价结构情景至2030年',
                      '打开常州单城2030曲线',
                      '#single-city-scenario'):
            self.assertIn(token, page)
        self.assertIn("source:'anjuke'", page)
        self.assertIn("structural_weight:'0.4'", page)
        self.assertIn("source,city,horizon:'2030'", page)

    def test_standalone_page_has_required_controls_and_provenance(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / 'static' / 'housing_scenario.html').read_text(encoding='utf-8')
        script = (root / 'static' / 'housing-scenario.js').read_text(encoding='utf-8')
        server = (root / 'server.py').read_text(encoding='utf-8')
        for token in ('cityChips', 'dataSource', 'horizon', 'compareValueMode',
                      'axisMode', 'axisMin', 'axisMax',
                      'rateOptimistic', 'backtestKpis', 'sourceInfo',
                      'forecastMode', 'structuralWeight', 'driverContributionChart',
                      'nationalDriverChart', 'driverTable', 'contextDriverCards',
                      'demographic-capacity', 'formationOptimistic', 'formationBase',
                      'formationStress', 'capacityYear', 'capacityCityMode',
                      'capacityScenario', 'capacityAxisMode',
                      'demographicCapacityChart', 'cityCapacityChart',
                      'demographicTable', 'demographicMethod'):
            self.assertIn(f'id="{token}"', page)
        self.assertIn('id="single-city-scenario"', page)
        self.assertIn('单城2030曲线', page)
        self.assertIn('焦点城市（当前来源全部目录）', page)
        self.assertIn('housing-scenario.js?v=', page)
        for token in ('/api/housing-scenario/cities', '/api/housing-scenario/compare',
                      '/api/housing-scenario/data', 'P10', 'P50', 'P90'):
            self.assertIn(token, page + script + server)
        self.assertIn("'/housing-scenario'", server)
        self.assertIn('安居客年度·15城目录', page)
        self.assertIn('data-group="added"', page)
        for city in ('武汉', '长沙', '成都', '杭州', '福州'):
            self.assertIn(f"'{city}'", script)
        self.assertIn('<option value="anjuke" selected>', page)
        self.assertIn('data-source-mode="anjuke"', page)
        self.assertIn('data-source-mode="anjuke_yearly"', page)
        self.assertIn('data-source-mode="official"', page)
        self.assertIn("'常州'", script)
        self.assertIn("INITIAL_PARAMS.get('city')||'常州'", script)
        self.assertIn('function selectSource(source)', script)
        self.assertIn("const available=catalog.filter(item=>item.status!=='missing')", script)
        self.assertIn("item.status==='missing'?'disabled':''", script)
        self.assertIn('期末挂牌价（元/㎡）', page)
        self.assertIn('value="2030" selected', page)
        self.assertIn('到2030年末', page)
        self.assertNotIn('value="24" selected', page)
        self.assertIn('id="detailHorizonBadge"', page)
        self.assertIn('function detailXAxisLabel', script)
        self.assertIn('autoSkip:false', script)
        self.assertIn('index===labels.length-1', script)
        self.assertIn('情景路径（终点 ${lastPeriod}）', script)
        self.assertIn("rawWeight!==null&&rawWeight!==''", script)
        self.assertIn('function scrollToPageAnchor', script)
        self.assertIn('${params}${location.hash}', script)
        self.assertIn('end_price', script)
        self.assertIn('前值插补', script)
        self.assertIn("source=q.get('source')", server)
        self.assertIn('_parse_housing_scenario_horizon', server)
        self.assertIn('structural_weight', server)
        self.assertIn('function renderStructuralDrivers', script)
        self.assertIn('function scenarioItems', script)
        self.assertIn('function renderDemographicCapacity', script)
        self.assertIn('function renderCityCapacityChart', script)
        self.assertIn('formation_optimistic', script + server)
        self.assertIn('demographic_capacity', script + server)
        self.assertIn('不写回上方2030房价路径', page)

    def test_city_economy_scenario_is_not_nested_in_coverage(self):
        root = Path(__file__).resolve().parents[1]
        page = (root / 'static' / 'city_economy.html').read_text(encoding='utf-8')
        scenario_start = page.index('<section id="scenario"')
        scenario_end = page.index('</section>', scenario_start)
        coverage_start = page.index('<section id="coverage"')
        self.assertLess(scenario_end, coverage_start)


if __name__ == '__main__':
    unittest.main()
