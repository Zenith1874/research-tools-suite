# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest

from services.city_bulletin_official_service import (
    VERIFIED_OFFICIAL_ROWS,
    _upsert_official_indicator,
    update_city_bulletin_official,
)
from services.city_nbs_service import ensure_city_indicator_table


class CityBulletinOfficialTests(unittest.TestCase):
    def test_rows_are_direct_source_backed_and_have_expected_anchors(self):
        self.assertEqual(len(VERIFIED_OFFICIAL_ROWS), 101)
        values = {(row['region_name'], row['indicator_code'], row['period']): row['value']
                  for row in VERIFIED_OFFICIAL_ROWS}
        self.assertEqual(values[('北京', 'resident_population', '2024')], 2183.2)
        self.assertEqual(values[('上海', 'urban_new_jobs', '2024')], 62.17)
        self.assertEqual(values[('厦门', 'resident_population', '2024')], 535.0)
        self.assertEqual(values[('合肥', 'urban_new_jobs', '2024')], 21.43)
        self.assertEqual(values[('长沙', 'resident_population', '2024')], 1061.65)
        self.assertEqual(values[('深圳', 'urban_new_jobs', '2024')], 20.7)
        self.assertEqual(values[('常州', 'resident_population', '2025')], 541.54)
        self.assertEqual(values[('常州', 'new_commercial_housing_filing_area', '2025')], 445.6)
        self.assertEqual(values[('苏州', 'urban_new_jobs', '2024')], 41.75)
        self.assertEqual(values[('苏州', 'real_estate_investment', '2024')], 2508.6)
        self.assertEqual(values[('无锡', 'urban_new_jobs', '2025')], 14.59)
        self.assertEqual(values[('无锡', 'household_deposits', '2024')], 13396.20)
        self.assertEqual(values[('常州', 'avg_wage', '2024')], 135233)
        self.assertEqual(values[('苏州', 'avg_wage', '2025')], 148364)
        self.assertEqual(values[('无锡', 'avg_wage', '2024')], 140941)
        self.assertEqual(values[('苏州', 'retail_sales', '2024')], 10043.7)
        for row in VERIFIED_OFFICIAL_ROWS:
            self.assertIn(row['period'], ('2023', '2024', '2025'))
            self.assertTrue(row['source_url'].startswith('https://'))
            self.assertIn(row['data_status'], ('official', 'official_preliminary'))

    def test_direct_source_replaces_mirror_but_not_official(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        path = handle.name
        handle.close()
        try:
            conn = sqlite3.connect(path)
            ensure_city_indicator_table(conn)
            row = VERIFIED_OFFICIAL_ROWS[0]
            conn.execute('''INSERT INTO city_indicator_observations
              (country_code,region_code,region_name,indicator_code,period,value,unit,
               data_status,source_name,source_url,source_title,parser_notes,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              ('CN', row['region_code'], row['region_name'], row['indicator_code'],
               row['period'], 1.0, row['unit'], 'official_mirror', '镜像',
               'https://mirror.example', 'mirror', 'fixture', 'now'))
            self.assertEqual(_upsert_official_indicator(conn, row), 'replaced')
            self.assertEqual(conn.execute('''SELECT value,data_status FROM city_indicator_observations
              WHERE region_code=? AND indicator_code=? AND period=?''',
              (row['region_code'], row['indicator_code'], row['period'])).fetchone(),
              (row['value'], 'official_preliminary'))

            conn.execute('''UPDATE city_indicator_observations SET data_status='official', value=999
              WHERE region_code=? AND indicator_code=? AND period=?''',
              (row['region_code'], row['indicator_code'], row['period']))
            self.assertEqual(_upsert_official_indicator(conn, row), 'skipped')
            self.assertEqual(conn.execute('''SELECT value FROM city_indicator_observations
              WHERE region_code=? AND indicator_code=? AND period=?''',
              (row['region_code'], row['indicator_code'], row['period'])).fetchone()[0], 999)
            conn.close()
        finally:
            os.unlink(path)

    def test_update_is_idempotent(self):
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        path = handle.name
        handle.close()
        try:
            first = update_city_bulletin_official(path)
            second = update_city_bulletin_official(path)
            self.assertEqual(first['inserted'], len(VERIFIED_OFFICIAL_ROWS))
            self.assertEqual(second['inserted'], 0)
            self.assertEqual(second['replaced'], 0)
            self.assertEqual(second['skipped'], len(VERIFIED_OFFICIAL_ROWS))
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
