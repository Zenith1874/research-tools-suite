# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.macro_housing_link_service import (
    apply_macro_housing_linkage,
    build_macro_housing_linkage,
    default_track_map,
    normalize_selectors,
)


def _synthetic_linkage(selectors=None):
    rows = []
    for key, coefficient in (('growth', 0.20), ('lpr', -0.80)):
        rows.append({
            'key': key, 'label': key, 'frequency': 'monthly',
            'coefficient': coefficient, 'status': 'ok',
            'paths': {
                'upper': [{'period': f'2026-{month:02d}', 'value': value}
                          for month, value in enumerate(range(2, 14), 1)],
                'base': [{'period': f'2026-{month:02d}', 'value': 1.0}
                         for month in range(1, 13)],
                'lower': [{'period': f'2026-{month:02d}', 'value': value}
                          for month, value in enumerate(range(0, 12), 1)],
            },
        })
    normalized = normalize_selectors(selectors)
    return {
        'status': 'ok', 'selectors': normalized,
        'track_map': default_track_map(normalized), 'components': rows,
    }


def _series_and_scenarios():
    series = [{'period': f'{2025 + month // 12:04d}-{month % 12 + 1:02d}',
               'index': 100.0 + month} for month in range(0, 25)]
    scenarios = []
    for key, rate in (('optimistic', 0.4), ('base', 0.0), ('stress', -0.4)):
        index = series[-1]['index']
        path = []
        for step in range(1, 13):
            index *= 1.0 + rate / 100.0
            path.append({'period': f'2027-{step:02d}', 'index': round(index, 4)})
        scenarios.append({'key': key, 'label': key, 'monthly_rate': rate, 'path': path})
    return series, scenarios


class MacroHousingLinkServiceTests(unittest.TestCase):
    def test_selector_normalization_and_inverse_lpr_mapping(self):
        selectors = normalize_selectors({'growth': 'upper', 'unknown': 'lower', 'lpr': 'bad'})
        self.assertEqual(selectors['growth'], 'upper')
        self.assertEqual(selectors['lpr'], 'auto')
        mapping = default_track_map(selectors)
        self.assertEqual(mapping['optimistic']['growth'], 'upper')
        self.assertEqual(mapping['optimistic']['lpr'], 'lower')
        self.assertEqual(mapping['stress']['lpr'], 'upper')

    def test_default_overlay_changes_paths_in_expected_direction(self):
        series, scenarios = _series_and_scenarios()
        result = apply_macro_housing_linkage(
            series, scenarios, _synthetic_linkage())
        self.assertEqual([item['key'] for item in result],
                         ['optimistic', 'base', 'stress'])
        by_key = {item['key']: item for item in result}
        self.assertGreater(by_key['optimistic']['end_vs_now'],
                           by_key['base']['end_vs_now'])
        self.assertGreater(by_key['base']['end_vs_now'],
                           by_key['stress']['end_vs_now'])
        self.assertAlmostEqual(by_key['base']['macro_adjustment_end_pp'], 0.0, places=6)
        self.assertTrue(all(item['ordering_valid'] for item in result))

    def test_fixed_base_tracks_recover_raw_momentum_path(self):
        series, scenarios = _series_and_scenarios()
        result = apply_macro_housing_linkage(
            series, scenarios, _synthetic_linkage({key: 'base' for key in ('growth', 'lpr')}))
        raw_by_key = {item['key']: item for item in scenarios}
        for item in result:
            self.assertAlmostEqual(item['macro_adjustment_end_pp'], 0.0, places=6)
            self.assertAlmostEqual(item['end_vs_now'],
                                   (raw_by_key[item['key']]['path'][-1]['index'] /
                                    series[-1]['index'] - 1.0) * 100.0, places=4)

    def test_missing_database_components_are_reported_not_filled(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / 'empty.sqlite'
            sqlite3.connect(db_path).close()
            payload = build_macro_housing_linkage(str(db_path), horizon_months=12)
        self.assertIn(payload['status'], ('partial', 'insufficient_data'))
        growth = next(item for item in payload['components'] if item['key'] == 'growth')
        self.assertIn(growth['status'], ('missing', 'insufficient_sample'))
        self.assertNotEqual(growth['latest_value'], 0)


if __name__ == '__main__':
    unittest.main()
