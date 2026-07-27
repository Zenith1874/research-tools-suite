# -*- coding: utf-8 -*-
import sqlite3
import unittest

from services.city_nbs_service import (
    NBS_CITIES,
    NBS_SOURCE_NAME,
    parse_nbs_periods,
    store_nbs_rows,
)
from services.regional_fiscal_service import ensure_regional_fiscal_table, _upsert


class CityNbsParserTests(unittest.TestCase):
    def test_xiamen_fiscal_values_are_parsed_from_official_payload(self):
        specs = {
            'rev': ('general_budget_revenue', '亿元', 'fiscal'),
            'exp': ('general_budget_expenditure', '亿元', 'fiscal'),
        }
        data = [
            {'code': '2021YY', 'name': '2021年', 'values': [
                {'_id': 'rev', 'value': '880.96'},
                {'_id': 'exp', 'value': '1060.00'},
            ]},
            {'code': '2020YY', 'name': '2020年', 'values': [
                {'_id': 'rev', 'value': '783.94'},
                {'_id': 'exp', 'value': '976.91'},
            ]},
        ]
        rows = parse_nbs_periods(
            data, '厦门', NBS_CITIES['厦门'], specs, '财政和金融')
        values = {(row['period'], row['indicator_code']): row['value'] for row in rows}
        self.assertEqual(values[('2020', 'general_budget_revenue')], 783.94)
        self.assertEqual(values[('2021', 'general_budget_revenue')], 880.96)
        self.assertTrue(all(row['data_status'] == 'official_revised' for row in rows))
        self.assertTrue(all(row['government_scope'] == 'city_total' for row in rows))

    def test_nonnumeric_and_unknown_indicator_values_are_skipped(self):
        rows = parse_nbs_periods(
            [{'code': '2024YY', 'values': [
                {'_id': 'known', 'value': ''},
                {'_id': 'other', 'value': '999'},
            ]}],
            '南京', NBS_CITIES['南京'],
            {'known': ('nominal_gdp', '亿元', 'gdp')}, '国民经济核算')
        self.assertEqual(rows, [])


class CityNbsPriorityTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        ensure_regional_fiscal_table(self.conn)
        self.conn.execute('''CREATE TABLE gdp_region_observations (
          id INTEGER PRIMARY KEY, country_code TEXT, region_code TEXT, region_name TEXT,
          indicator_code TEXT, period TEXT, value REAL, unit TEXT, data_status TEXT,
          source_name TEXT, source_url TEXT, parser_notes TEXT, updated_at TEXT,
          UNIQUE(country_code,region_code,indicator_code,period))''')

    def tearDown(self):
        self.conn.close()

    @staticmethod
    def _row(indicator, period, value, destination='fiscal'):
        return {
            'city': '厦门', 'region_code': '350200', 'government_scope': 'city_total',
            'indicator_code': indicator, 'period': period, 'value': value, 'unit': '亿元',
            'destination': destination, 'data_status': 'official_revised',
            'source_name': NBS_SOURCE_NAME, 'source_url': 'https://data.stats.gov.cn/',
            'source_title': '主要城市年度数据', 'parser_notes': 'fixture',
        }

    def test_nbs_replaces_mirror_value(self):
        _upsert(self.conn, {
            'country_code': 'CN', 'government_scope': 'city_total',
            'region_code': '350200', 'region_name': '厦门',
            'indicator_code': 'general_budget_revenue', 'period': '2020',
            'value': 236.92, 'unit': '亿元', 'frequency': 'annual',
            'period_type': 'calendar_year', 'data_status': 'official_mirror',
            'source_name': '第三方镜像', 'source_url': 'https://mirror.invalid',
        })
        result = store_nbs_rows(
            self.conn, [self._row('general_budget_revenue', '2020', 783.94)])
        row = self.conn.execute('''SELECT value,data_status,source_name
          FROM regional_fiscal_observations''').fetchone()
        self.assertEqual(row[0], 783.94)
        self.assertEqual(row[1], 'official_revised')
        self.assertEqual(row[2], NBS_SOURCE_NAME)
        self.assertEqual(result['replaced_mirror'], 1)

    def test_nbs_does_not_silently_overwrite_city_bulletin(self):
        _upsert(self.conn, {
            'country_code': 'CN', 'government_scope': 'city_total',
            'region_code': '350200', 'region_name': '厦门',
            'indicator_code': 'general_budget_revenue', 'period': '2024',
            'value': 930.0, 'unit': '亿元', 'frequency': 'annual',
            'period_type': 'calendar_year', 'data_status': 'official',
            'source_name': '厦门市财政局', 'source_url': 'https://cz.xm.gov.cn/',
        })
        result = store_nbs_rows(
            self.conn, [self._row('general_budget_revenue', '2024', 933.35)])
        row = self.conn.execute(
            'SELECT value,source_name FROM regional_fiscal_observations').fetchone()
        self.assertEqual(row[0], 930.0)
        self.assertEqual(row[1], '厦门市财政局')
        self.assertEqual(result['kept_published'], 1)


if __name__ == '__main__':
    unittest.main()


class NbsConflictPersistenceTests(unittest.TestCase):
    """保留城市已发布值时，被舍弃的统计局修订值必须落库，收敛后自动消失。"""

    ROW = {
        'city': '深圳', 'region_code': '440300', 'government_scope': 'city_total',
        'indicator_code': 'general_budget_expenditure', 'period': '2016',
        'value': 4211.04, 'unit': '亿元', 'destination': 'fiscal',
        'data_status': 'official_revised', 'source_name': NBS_SOURCE_NAME,
        'source_url': 'https://data.stats.gov.cn/x',
        'source_title': '主要城市年度数据—财政和金融', 'parser_notes': 'fixture',
    }

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        ensure_regional_fiscal_table(self.conn)
        _upsert(self.conn, {
            'country_code': 'CN', 'government_scope': 'city_total',
            'region_code': '440300', 'region_name': '深圳',
            'indicator_code': 'general_budget_expenditure', 'period': '2016',
            'value': 4178.04, 'unit': '亿元', 'frequency': 'annual',
            'period_type': 'calendar_year', 'source_name': '深圳市统计局',
            'source_url': 'https://tjj.sz.gov.cn/x', 'source_title': '公报',
            'parser_notes': 'fixture',
        })
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _conflicts(self):
        from services.data_conflict_service import list_conflicts
        return list_conflicts(self.conn, domain='city_economy')

    def test_kept_published_value_records_a_persistent_conflict(self):
        counts = store_nbs_rows(self.conn, [self.ROW])
        self.assertEqual(counts['kept_published'], 1)
        rows = self._conflicts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kept_value'], 4178.04)
        self.assertEqual(rows[0]['candidate_value'], 4211.04)
        self.assertEqual(rows[0]['kept_source_name'], '深圳市统计局')
        # 库里取值不受影响，仍是城市公报值
        kept = self.conn.execute(
            "SELECT value FROM regional_fiscal_observations "
            "WHERE region_code='440300' AND period='2016'").fetchone()
        self.assertEqual(kept[0], 4178.04)

    def test_conflict_disappears_once_values_converge(self):
        store_nbs_rows(self.conn, [self.ROW])
        self.assertEqual(len(self._conflicts()), 1)
        store_nbs_rows(self.conn, [{**self.ROW, 'value': 4178.5}])   # 差 0.01%
        self.assertEqual(self._conflicts(), [])

    def test_within_tolerance_never_records(self):
        store_nbs_rows(self.conn, [{**self.ROW, 'value': 4190.0}])   # 差 0.29%
        self.assertEqual(self._conflicts(), [])

    def test_conflict_cleared_when_nbs_value_is_adopted(self):
        """镜像值被统计局替换时，该键上的旧分歧记录必须清掉。"""
        from services.data_conflict_service import record_conflict
        record_conflict(self.conn, {
            'domain': 'city_economy', 'region_code': '440300', 'region_name': '深圳',
            'government_scope': 'city_total',
            'indicator_code': 'general_budget_revenue', 'period': '2016',
            'kept_value': 1.0, 'candidate_value': 2.0, 'relative_diff': 1.0,
            'candidate_source_name': NBS_SOURCE_NAME, 'resolution': 'kept_published',
        })
        _upsert(self.conn, {
            'country_code': 'CN', 'government_scope': 'city_total',
            'region_code': '440300', 'region_name': '深圳',
            'indicator_code': 'general_budget_revenue', 'period': '2016',
            'value': 1.0, 'unit': '亿元', 'frequency': 'annual',
            'period_type': 'calendar_year', 'data_status': 'official_mirror',
            'source_name': '镜像', 'source_url': 'https://mirror/x',
            'source_title': 'm', 'parser_notes': 'fixture',
        })
        self.conn.commit()
        store_nbs_rows(self.conn, [{**self.ROW,
                                    'indicator_code': 'general_budget_revenue',
                                    'value': 2.0}])
        self.assertEqual(self._conflicts(), [])


class MunicipalityGdpTargetTests(unittest.TestCase):
    """直辖市 GDP 落城市码：省级排行必须保持 31 省同一口径。"""

    SPECS = {'g': ('nominal_gdp', '亿元', 'gdp'),
             'r': ('general_budget_revenue', '亿元', 'fiscal')}
    DATA = [{'code': '2023YY', 'values': [{'_id': 'g', 'value': '47353.7'},
                                          {'_id': 'r', 'value': '6181.1'}]}]

    def test_gdp_goes_to_city_code_while_fiscal_stays_on_province_code(self):
        rows = parse_nbs_periods(self.DATA, '北京', NBS_CITIES['北京'],
                                 self.SPECS, '国民经济核算')
        by_code = {row['indicator_code']: row['region_code'] for row in rows}
        self.assertEqual(by_code['nominal_gdp'], '110100')
        self.assertEqual(by_code['general_budget_revenue'], '110000')

    def test_non_municipality_uses_one_code_for_both(self):
        rows = parse_nbs_periods(self.DATA, '广州', NBS_CITIES['广州'],
                                 self.SPECS, '国民经济核算')
        self.assertEqual({row['region_code'] for row in rows}, {'440100'})

    def test_purge_removes_only_nbs_rows_left_on_the_province_code(self):
        from services.city_nbs_service import purge_misplaced_gdp, _ensure_gdp_table
        conn = sqlite3.connect(':memory:')
        _ensure_gdp_table(conn)
        conn.executemany(
            '''INSERT INTO gdp_region_observations
               (country_code,region_code,region_name,indicator_code,period,value,unit,
                data_status,source_name) VALUES ('CN',?,?,?,?,?,'亿元',?,?)''',
            [('110000', '北京', 'nominal_gdp', '2025', 52073.4, 'official_revised',
              NBS_SOURCE_NAME),                                  # 错落点，应删
             ('110000', '北京', 'nominal_gdp', '2024', 49843.1, 'official',
              '国家统计局《中国统计年鉴》'),                        # 年鉴值，必须留
             ('440100', '广州', 'nominal_gdp', '2024', 31032.5, 'official_revised',
              NBS_SOURCE_NAME)])                                 # 非直辖市，落点正确
        conn.commit()
        self.assertEqual(purge_misplaced_gdp(conn), 1)
        kept = {(r[0], r[1]) for r in conn.execute(
            'SELECT region_code,period FROM gdp_region_observations')}
        self.assertEqual(kept, {('110000', '2024'), ('440100', '2024')})
        conn.close()
