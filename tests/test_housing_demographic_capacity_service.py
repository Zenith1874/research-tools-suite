# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.housing_demographic_capacity_service import (
    build_capacity_scenarios,
    build_demographic_capacity_payload,
    city_concentration_multiplier,
    load_demographic_projection_inputs,
    normalise_formation_adjustments,
)


class HousingDemographicCapacityDataTests(unittest.TestCase):
    def test_official_projection_snapshot_has_complete_unique_anchors(self):
        grouped = load_demographic_projection_inputs()
        self.assertEqual(set(grouped), {2025, 2030, 2040, 2050})
        self.assertAlmostEqual(
            grouped[2025]['un_total_population_1jan']['value'], 1417733.636, 3)
        self.assertAlmostEqual(
            grouped[2050]['un_population_age_20_39']['value'], 257868.130, 3)
        self.assertTrue(all(
            row['data_status'] == 'official_projection'
            for values in grouped.values() for row in values.values()))
        self.assertTrue(all(
            row['source_url'].startswith('https://population.un.org/')
            for values in grouped.values() for row in values.values()))


class HousingDemographicCapacityModelTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        handle.close()
        self.path = handle.name
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('''CREATE TABLE city_indicator_observations (
          region_code TEXT,region_name TEXT,indicator_code TEXT,period TEXT,value REAL,
          unit TEXT,data_status TEXT,source_name TEXT,source_url TEXT)''')
        for year, value in zip(range(2022, 2026), (530.0, 532.0, 535.0, 540.0)):
            self.conn.execute('INSERT INTO city_indicator_observations VALUES (?,?,?,?,?,?,?,?,?)',
                              ('320400', '常州', 'resident_population', str(year), value,
                               '万人', 'official', '常州统计局',
                               f'https://example.test/changzhou/{year}'))
        self.conn.execute('INSERT INTO city_indicator_observations VALUES (?,?,?,?,?,?,?,?,?)',
                          ('110000', '北京', 'resident_population', '2024', 2183.2,
                           '万人', 'official', '北京统计局',
                           'https://example.test/beijing/2024'))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        Path(self.path).unlink(missing_ok=True)

    def test_capacity_paths_start_at_100_and_keep_scenario_order(self):
        grouped = load_demographic_projection_inputs()
        base = grouped[2025]
        projections = []
        for year in (2025, 2030, 2040, 2050):
            values = grouped[year]
            projections.append({
                'year': year,
                'population_20_39_index': (
                    values['un_population_age_20_39']['value'] /
                    base['un_population_age_20_39']['value'] * 100),
            })
        scenarios = build_capacity_scenarios(projections)
        by_key = {row['key']: row for row in scenarios}
        self.assertTrue(all(row['points'][0]['demand_capacity_index'] == 100.0
                            for row in scenarios))
        terminal = {key: row['points'][-1]['demand_capacity_index']
                    for key, row in by_key.items()}
        self.assertGreater(terminal['optimistic'], terminal['base'])
        self.assertGreater(terminal['base'], terminal['stress'])
        self.assertAlmostEqual(terminal['base'], 67.0, delta=0.1)
        burden = by_key['base']['points'][-1]['fixed_stock_burden_index']
        self.assertAlmostEqual(burden, 10000 / terminal['base'], places=2)

    def test_city_trend_is_bounded_and_single_point_falls_back(self):
        payload = build_demographic_capacity_payload(
            self.conn, cities=['常州', '北京'])
        cities = {row['city']: row for row in payload['cities']}
        self.assertEqual(cities['常州']['coverage_status'], 'city_trend')
        self.assertEqual(cities['北京']['coverage_status'], 'national_fallback')
        self.assertEqual(cities['北京']['applied_relative_growth_pp'], 0.0)
        national_terminal = payload['national']['scenarios'][1]['points'][-1]
        beijing_terminal = cities['北京']['scenarios'][1]['points'][-1]
        changzhou_terminal = cities['常州']['scenarios'][1]['points'][-1]
        self.assertEqual(beijing_terminal['demand_capacity_index'],
                         national_terminal['demand_capacity_index'])
        self.assertGreater(changzhou_terminal['demand_capacity_index'],
                           national_terminal['demand_capacity_index'])
        self.assertLessEqual(abs(cities['常州']['applied_relative_growth_pp']), 2.0)

    def test_payload_discloses_sources_coverage_and_no_price_projection(self):
        payload = build_demographic_capacity_payload(
            self.conn, cities=['常州', '北京'])
        self.assertEqual(payload['data_status'], 'scenario')
        self.assertEqual(payload['projection_data_status'], 'official_projection')
        self.assertEqual(payload['coverage']['city_trend_cities'], 1)
        self.assertEqual(payload['coverage']['national_fallback_cities'], 1)
        self.assertIn('不直接换算房价', ' '.join(payload['caveats']))
        self.assertNotIn('price', str(payload['national']['scenarios']).lower())
        self.assertTrue(all(source['url'].startswith('https://')
                            for source in payload['sources']))

    def test_assumption_order_and_city_decay_are_explicit(self):
        with self.assertRaisesRegex(ValueError, '乐观'):
            normalise_formation_adjustments(
                {'optimistic': -20, 'base': 0, 'stress': -10})
        early = city_concentration_multiplier(2030, 1.0)
        late = city_concentration_multiplier(2050, 1.0)
        self.assertGreater(early, 1.0)
        self.assertGreater(late, early)
        self.assertLess(late, 1.20)


if __name__ == '__main__':
    unittest.main()
