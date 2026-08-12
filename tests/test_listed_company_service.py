# -*- coding: utf-8 -*-
"""上市公司城市归属与落库纪律。地址样本取自巨潮实际返回。"""
import sqlite3
import unittest

from services.listed_company_service import (
    parse_city, parse_province, ensure_tables, upsert_company,
    upsert_observation, SOURCE_CNINFO, SOURCE_EASTMONEY, _market_symbol,
    _select_report_period, _concentration_summary, _parse_profit_history_records,
    _build_city_annual_history, _upsert_fetch_status,
)


class AddressParsingTests(unittest.TestCase):
    CASES = [
        # 常规省市
        ('广东省深圳市罗湖区深南东路5047号', '深圳', '广东'),
        ('江苏省苏州市工业园区星湖街218号', '苏州', '江苏'),
        ('福建省厦门市思明区', '厦门', '福建'),
        # 直辖市没有下一级市名
        ('北京市东城区建国门内大街69号', '北京', '北京'),
        ('重庆市渝北区龙山街道', '重庆', '重庆'),
        # 县级市直属省管：不能误归到省会
        ('贵州省仁怀市茅台镇', '仁怀', '贵州'),
        # 自治区前缀若不先剥，会把"治区呼和浩特"当成市名
        ('内蒙古自治区呼和浩特市新城区', '呼和浩特', '内蒙古'),
        ('西藏自治区拉萨市金珠西路', '拉萨', '西藏'),
        # 省与市之间还夹一级州/盟
        ('新疆维吾尔自治区伊犁州霍尔果斯市亚欧路', '霍尔果斯', '新疆'),
        ('湖北省恩施州利川市', '利川', '湖北'),
        ('内蒙古自治区兴安盟乌兰浩特市', '乌兰浩特', '内蒙古'),
        # 州内是县而非市，地级单位即该州
        ('四川省阿坝藏族羌族自治州汶川县', '阿坝', '四川'),
    ]

    def test_city_and_province_are_parsed(self):
        for address, city, province in self.CASES:
            self.assertEqual(parse_city(address), city, address)
            self.assertEqual(parse_province(address), province, address)

    def test_unparseable_returns_none_rather_than_guessing(self):
        for address in (None, '', '   ', '详见公司公告', '本公司办公地址见年报'):
            self.assertIsNone(parse_city(address), address)
            self.assertIsNone(parse_province(address), address)

    def test_market_symbol_prefix(self):
        self.assertEqual(_market_symbol('600519'), 'SH600519')
        self.assertEqual(_market_symbol('000001'), 'SZ000001')
        self.assertEqual(_market_symbol('300750'), 'SZ300750')
        self.assertEqual(_market_symbol('830799'), 'BJ830799')
        self.assertEqual(_market_symbol('920799'), 'BJ920799')
        self.assertEqual(_market_symbol('900901'), 'SH900901')

    def test_report_period_selector_uses_latest_full_year_for_flows(self):
        rows = [
            {'REPORT_DATE': '2026-06-30 00:00:00'},
            {'REPORT_DATE': '2025-12-31 00:00:00'},
            {'REPORT_DATE': '2026-03-31 00:00:00'},
            {'REPORT_DATE': '2024-12-31 00:00:00'},
        ]
        self.assertEqual(_select_report_period(rows), '2026-06-30')
        self.assertEqual(_select_report_period(rows, annual_only=True), '2025-12-31')

    def test_multi_year_profit_parser_keeps_only_full_year_records(self):
        rows = [
            {'REPORT_DATE': '2025-12-31', 'TOTAL_OPERATE_INCOME': 100.0,
             'PARENT_NETPROFIT': 10.0},
            {'REPORT_DATE': '2025-09-30', 'TOTAL_OPERATE_INCOME': 80.0,
             'PARENT_NETPROFIT': 8.0},
            {'REPORT_DATE': '2024-12-31', 'TOTAL_OPERATE_INCOME': 90.0,
             'PARENT_NETPROFIT': None},
        ]
        parsed = _parse_profit_history_records(rows, company_type=4)
        self.assertEqual([row['period'] for row in parsed],
                         ['2024-12-31', '2025-12-31'])
        self.assertEqual(parsed[0]['values'], {'revenue': 90.0})
        self.assertEqual(parsed[1]['values']['net_profit'], 10.0)


class StorageDisciplineTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_company_upsert_keeps_both_address_scopes(self):
        upsert_company(self.conn, {
            'code': '600519', 'name': '贵州茅台', 'org_id': 'gssh0600519',
            'category': 'A股',
            'register_address': '贵州省仁怀市茅台镇',
            'office_address': '贵州省仁怀市茅台镇',
            'register_city': '仁怀', 'register_province': '贵州',
            'office_city': '仁怀', 'office_province': '贵州',
            'industry': '酒制造', 'listed_date': '2001-08-27',
        }, '2026-07-28T00:00:00')
        row = self.conn.execute(
            'SELECT register_city,office_city,data_status,source_name '
            'FROM listed_companies WHERE code=?', ('600519',)).fetchone()
        self.assertEqual(row[0], '仁怀')
        self.assertEqual(row[1], '仁怀')
        self.assertEqual(row[2], 'official')
        self.assertIn('巨潮', row[3])

    def test_same_indicator_from_two_sources_coexists(self):
        """巨潮与东财的同一指标必须并存，才能互相校验；不得互相覆盖。"""
        for source, value, status in ((SOURCE_CNINFO, 100.0, 'official'),
                                      (SOURCE_EASTMONEY, 101.0, 'third_party')):
            upsert_observation(self.conn, '000001', '平安银行', 'revenue', '2026-03-31',
                               value, status, source, 'https://x', 'fixture',
                               '2026-07-28T00:00:00')
        rows = self.conn.execute(
            'SELECT source_name,value,data_status FROM listed_company_observations '
            'WHERE code=? AND indicator_code=? ORDER BY source_name',
            ('000001', 'revenue')).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r[2] for r in rows}, {'official', 'third_party'})

    def test_reupsert_same_source_updates_in_place(self):
        for value in (100.0, 123.0):
            upsert_observation(self.conn, '000001', '平安银行', 'revenue', '2026-03-31',
                               value, 'official', SOURCE_CNINFO, 'https://x', 'f',
                               '2026-07-28T00:00:00')
        rows = self.conn.execute(
            'SELECT value FROM listed_company_observations WHERE code=?',
            ('000001',)).fetchall()
        self.assertEqual(rows, [(123.0,)])

    def test_fetch_status_is_idempotent_and_updates_result(self):
        for status, records in (('error', 0), ('ok', 10)):
            _upsert_fetch_status(
                self.conn, '000001', 'profit_history', '2021-12-31',
                '2025-12-31', status, records, None,
                '2026-07-30T00:00:00')
        rows = self.conn.execute(
            'SELECT status,records_stored FROM listed_company_fetch_status').fetchall()
        self.assertEqual(rows, [('ok', 10)])


class ConcentrationTests(unittest.TestCase):
    def test_concentration_summary_reports_shares_hhi_and_coverage(self):
        rows = [
            {'code': 'a', 'name': '甲', 'value': 70e8},
            {'code': 'b', 'name': '乙', 'value': 20e8},
            {'code': 'c', 'name': '丙', 'value': 10e8},
            {'code': 'd', 'name': '零值', 'value': 0},
        ]
        result = _concentration_summary(rows, company_count=5)
        self.assertEqual(result['n_obs'], 3)
        self.assertEqual(result['coverage_pct'], 60.0)
        self.assertEqual(result['top1_share_pct'], 70.0)
        self.assertEqual(result['top5_share_pct'], 100.0)
        self.assertEqual(result['hhi'], 5400.0)
        self.assertEqual(result['top_companies'][0]['name'], '甲')
        self.assertEqual(result['top_companies'][0]['value_yi'], 70.0)

    def test_annual_history_distinguishes_available_and_balanced_samples(self):
        annual = {
            'revenue': {
                'a': {'2021': {'value': 100e8}, '2022': {'value': 120e8}},
                'b': {'2022': {'value': 80e8}},
            },
            'net_profit': {
                'a': {'2021': {'value': 10e8}, '2022': {'value': 12e8}},
                'b': {'2022': {'value': 8e8}},
            },
        }
        result = _build_city_annual_history(['a', 'b'], annual, ['2021', '2022'])
        self.assertEqual(result['available'][0]['revenue_coverage'], 1)
        self.assertEqual(result['available'][1]['revenue_coverage'], 2)
        self.assertEqual(result['available'][1]['revenue_yi'], 200.0)
        self.assertEqual(result['balanced_company_count'], 1)
        self.assertEqual(result['balanced'][1]['revenue_yi'], 120.0)
        self.assertEqual(result['balanced'][1]['profit_margin_pct'], 10.0)


class AggregationTests(unittest.TestCase):
    """聚合口径：陈旧报表不与当期混加；市值是行情快照不受报告期下限约束。"""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        ensure_tables(self.conn)
        now = '2026-07-29T00:00:00'
        for code, name, city, register_city in (
                ('000001', '甲公司', '深圳', '上海'),
                ('000002', '乙公司', '深圳', '深圳'),
                ('600000', '丙公司', '上海', '上海')):
            upsert_company(self.conn, {
                'code': code, 'name': name, 'org_id': None, 'category': 'A股',
                'register_address': None, 'office_address': None,
                'register_city': register_city, 'register_province': None,
                'office_city': city, 'office_province': None,
                'industry': '制造业', 'listed_date': None}, now)
        self.conn.execute('''CREATE TABLE gdp_region_observations (
            country_code TEXT, region_name TEXT, indicator_code TEXT,
            period TEXT, value REAL)''')
        self.conn.executemany(
            'INSERT INTO gdp_region_observations VALUES (?,?,?,?,?)',
            [('CN', '深圳', 'nominal_gdp', '2025', 1000.0),
             ('CN', '上海', 'nominal_gdp', '2024', 2000.0)])
        # 甲：2025 完整年度；2026Q1 是累计流量，不得替代年度值。
        # 乙：停在 2013 年应被剔除；丙：2025 完整年度。
        rows = [('000001', 'revenue', '2025-12-31', 100e8),
                ('000001', 'net_profit', '2025-12-31', 10e8),
                ('000001', 'revenue', '2026-03-31', 40e8),
                ('000001', 'market_cap', '2026-07-28', 500e8),
                ('000002', 'revenue', '2013-12-31', 999e8),
                ('000002', 'market_cap', '2026-07-28', 30e8),
                ('600000', 'revenue', '2025-12-31', 200e8),
                ('600000', 'net_profit', '2025-12-31', 20e8),
                ('600000', 'market_cap', '2026-07-28', 800e8)]
        for code, ind, period, value in rows:
            upsert_observation(self.conn, code, None, ind, period, value,
                               'third_party', SOURCE_EASTMONEY, 'u', 'f', now)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _payload(self, path):
        from services.listed_company_service import build_city_listed_payload
        return build_city_listed_payload(path)

    def test_stale_report_excluded_but_market_cap_kept(self):
        import tempfile, os
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        path = handle.name
        handle.close()
        disk = sqlite3.connect(path)
        self.conn.backup(disk)
        disk.close()
        try:
            payload = self._payload(path)
        finally:
            os.unlink(path)
        by_city = {row['city']: row for row in payload['cities']}
        shenzhen = by_city['深圳']
        # 乙公司 2013 年的 999 亿营收不得进入合计
        self.assertAlmostEqual(shenzhen['totals_yi']['revenue'], 100.0, places=2)
        self.assertEqual(shenzhen['coverage']['revenue'], 1)
        self.assertEqual(shenzhen['report_periods']['revenue']['start'], '2025-12-31')
        self.assertEqual(shenzhen['report_periods']['revenue']['end'], '2025-12-31')
        self.assertAlmostEqual(shenzhen['derived']['listed_revenue_to_gdp'], 10.0)
        self.assertEqual(shenzhen['concentration']['market_cap']['n_obs'], 2)
        self.assertAlmostEqual(
            shenzhen['concentration']['market_cap']['top1_share_pct'], 94.34)
        self.assertEqual(
            shenzhen['concentration']['market_cap']['top_companies'][0]['name'],
            '甲公司')
        self.assertEqual(shenzhen['annual_history']['periods'], ['2025'])
        self.assertEqual(shenzhen['annual_history']['balanced_company_count'], 1)
        self.assertEqual(shenzhen['annual_history']['balanced'][0]['profit_margin_pct'], 10.0)
        # 市值是行情快照，两家都要算上
        self.assertAlmostEqual(shenzhen['totals_yi']['market_cap'], 530.0, places=2)
        self.assertEqual(shenzhen['coverage']['market_cap'], 2)
        self.assertIn('000002', payload['stale_excluded'])
        self.assertEqual(payload['period_floor'], '2025-06-30')
        # 上海营收为 2025 年、GDP 为 2024 年，年份不一致时不得生成比率。
        self.assertNotIn('listed_revenue_to_gdp', by_city['上海']['derived'])
        scopes = {row['city']: row for row in payload['scope_comparison']}
        self.assertEqual(scopes['深圳']['office_count'], 2)
        self.assertEqual(scopes['深圳']['register_count'], 1)
        self.assertEqual(scopes['深圳']['delta'], 1)
        self.assertEqual(scopes['上海']['delta'], -1)

    def test_city_filter_and_ordering(self):
        import tempfile, os
        handle = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        path = handle.name
        handle.close()
        disk = sqlite3.connect(path)
        self.conn.backup(disk)
        disk.close()
        try:
            payload = self._payload(path)
        finally:
            os.unlink(path)
        # 按总市值降序：上海 800 > 深圳 530
        self.assertEqual([row['city'] for row in payload['cities']], ['上海', '深圳'])


if __name__ == '__main__':
    unittest.main()
