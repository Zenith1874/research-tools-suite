# -*- coding: utf-8 -*-
import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.china_demography_service import (
    DATA_PATH,
    read_demography_rows,
    sync_china_demography,
    update_china_demography,
)
from services.china_macro_dashboard_service import build_china_macro_payload
from services.china_macro_service import ensure_china_macro_tables, sync_annual_macro_snapshots


class ChinaDemographyTests(unittest.TestCase):
    def _write_csv(self, rows):
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        fieldnames = list(rows[0].keys())
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_snapshot_has_auditable_rows_and_expected_coverage(self):
        rows, skipped = read_demography_rows(DATA_PATH)
        self.assertEqual(skipped, 0)
        self.assertGreater(len(rows), 150)
        codes = {row['indicator_code'] for row in rows}
        self.assertEqual(codes, {
            'CN_BIRTHS', 'CN_MARRIAGES',
            'CN_DIVORCES_AGREEMENT', 'CN_DIVORCES_COURT',
        })
        self.assertEqual(
            min(row['period'] for row in rows if row['indicator_code'] == 'CN_MARRIAGES'),
            '1978')
        self.assertEqual(
            max(row['period'] for row in rows if row['indicator_code'] == 'CN_MARRIAGES'),
            '2025')
        self.assertEqual(
            max(row['period'] for row in rows if row['indicator_code'] == 'CN_DIVORCES_COURT'),
            '2024')
        self.assertTrue(all(row['source_url'].startswith('http') for row in rows))
        self.assertTrue(all(row['unit'] in {'万人', '万对'} for row in rows))
        by_key = {(row['indicator_code'], row['period']): row for row in rows}
        self.assertEqual(by_key[('CN_BIRTHS', '2025')]['value'], 792.0)
        self.assertEqual(by_key[('CN_BIRTHS', '2025')]['data_status'], 'official')
        self.assertEqual(by_key[('CN_MARRIAGES', '2025')]['value'], 676.3)
        self.assertEqual(by_key[('CN_MARRIAGES', '2025')]['data_status'], 'official_relayed')
        self.assertEqual(by_key[('CN_DIVORCES_AGREEMENT', '2025')]['value'], 274.3)
        self.assertEqual(by_key[('CN_DIVORCES_COURT', '2024')]['value'], 89.1)
        self.assertIsNone(by_key[('CN_BIRTHS', '2025')]['release_date'])
        self.assertIsNone(by_key[('CN_BIRTHS', '2025')]['retrieved_at'])

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        ensure_china_macro_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_sync_is_idempotent_and_preserves_partial_2025(self):
        first = sync_china_demography(self.conn, sync_at='2026-08-13T10:00:00')
        second = sync_china_demography(self.conn, sync_at='2026-08-13T11:00:00')
        self.assertEqual(first['rows_skipped'], 0)
        self.assertEqual(first['records_changed'], first['rows_read'])
        self.assertEqual(second['records_changed'], 0)
        self.assertEqual(second['records_unchanged'], second['rows_read'])
        updated_at = self.conn.execute(
            "SELECT updated_at FROM china_macro_observations "
            "WHERE indicator_code='CN_BIRTHS' AND period='2025'").fetchone()[0]
        self.assertEqual(updated_at, '2026-08-13T10:00:00')
        timing = self.conn.execute(
            "SELECT release_date,retrieved_at,release_date_not_provided,release_date_reason "
            "FROM china_macro_observations WHERE indicator_code='CN_BIRTHS' AND period='2025'"
        ).fetchone()
        self.assertEqual(tuple(timing),
                         (None, None, 1, 'CSV 未提供逐行来源发布日期'))
        count = self.conn.execute(
            "SELECT COUNT(*) FROM china_macro_observations "
            "WHERE indicator_code IN ('CN_BIRTHS','CN_MARRIAGES',"
            "'CN_DIVORCES_AGREEMENT','CN_DIVORCES_COURT')").fetchone()[0]
        self.assertEqual(count, first['rows_read'])
        court_2025 = self.conn.execute(
            "SELECT 1 FROM china_macro_observations "
            "WHERE indicator_code='CN_DIVORCES_COURT' AND period='2025'").fetchone()
        self.assertIsNone(court_2025)

    def test_sync_preserves_optional_source_timing_fields(self):
        rows, _ = read_demography_rows(DATA_PATH)
        row = dict(rows[0])
        row['release_date'] = '2026-02-28'
        row['retrieved_at'] = '2026-08-13T12:00:00'
        path = self._write_csv([row])
        result = sync_china_demography(self.conn, path=path, sync_at='2026-08-13T12:05:00')
        self.assertEqual(result['records_changed'], 1)
        saved = self.conn.execute(
            "SELECT release_date,retrieved_at,release_date_not_provided,release_date_reason "
            "FROM china_macro_observations "
            "WHERE indicator_code=? AND period=?", (row['indicator_code'], row['period'])).fetchone()
        self.assertEqual(tuple(saved),
                         ('2026-02-28', '2026-08-13T12:00:00', 0, None))

    def test_parser_rejects_structural_provenance_errors(self):
        rows, _ = read_demography_rows(DATA_PATH)
        cases = (
            ('unit', 'unit 应为', {'unit': '万对'}),
            ('status', 'data_status', {'data_status': 'estimated'}),
            ('url', 'source_url', {'source_url': 'not-a-url'}),
            ('duplicate', '重复观测键', {}),
        )
        for label, message, changes in cases:
            with self.subTest(label=label):
                row = dict(rows[0])
                row.update(changes)
                bad_rows = [row, dict(row)] if label == 'duplicate' else [row]
                path = self._write_csv(bad_rows)
                with self.assertRaisesRegex(ValueError, message):
                    read_demography_rows(path)

    def test_dashboard_derives_divorce_total_without_filling_2025(self):
        sync_china_demography(self.conn)
        self.conn.close()
        payload = build_china_macro_payload(self.path)
        total = {row['period']: row['value']
                 for row in payload['series']['CN_DIVORCES_TOTAL_DERIVED']}
        self.assertAlmostEqual(total['1978'], 28.5)
        self.assertAlmostEqual(total['2024'], 351.3)
        self.assertNotIn('2025', total)
        ratio = {row['period']: row['value']
                 for row in payload['series']['CN_DIVORCE_MARRIAGE_RATIO_DERIVED']}
        self.assertEqual(len(ratio), 47)
        self.assertAlmostEqual(ratio['1978'], 28.5 / 597.8 * 100, places=8)
        self.assertAlmostEqual(ratio['2024'], 351.3 / 610.56 * 100, places=8)
        self.assertNotIn('2025', ratio)
        ratio_rows = payload['series']['CN_DIVORCE_MARRIAGE_RATIO_DERIVED']
        self.assertTrue(all(row['data_status'] == 'derived' for row in ratio_rows))
        self.assertTrue(all(row['value'] >= 0 for row in ratio_rows))
        self.assertTrue(all(row['unit'] == '%' and row['frequency'] == 'annual'
                            for row in ratio_rows))
        groups = {group['code']: group for group in payload['groups']}
        self.assertEqual(groups['employment']['title'], '就业与收入')
        self.assertEqual(groups['demography']['title'], '人口与家庭')
        chart_codes = {chart['code'] for chart in groups['demography']['charts']}
        self.assertIn('family_flows', chart_codes)
        self.assertIn('divorce_routes', chart_codes)
        self.assertIn('divorce_marriage_ratio', chart_codes)
        family = next(chart for chart in groups['demography']['charts']
                      if chart['code'] == 'family_flows')
        self.assertEqual(family['unit'], '万对')
        self.assertEqual(set(family['series']), {'CN_MARRIAGES', 'CN_DIVORCES_TOTAL_DERIVED'})
        self.assertNotIn('CN_BIRTHS', family['series'])
        ratio_chart = next(chart for chart in groups['demography']['charts']
                           if chart['code'] == 'divorce_marriage_ratio')
        self.assertEqual(ratio_chart['unit'], '%')
        self.assertEqual(ratio_chart['series'], ['CN_DIVORCE_MARRIAGE_RATIO_DERIVED'])
        self.assertIn('不是同一婚姻队列', ratio_chart['note'])
        birth = next(row for row in payload['series']['CN_BIRTHS'] if row['period'] == '2025')
        self.assertEqual(birth['evidence_tier'], '一手官方')
        self.assertIsNone(birth['release_date'])
        self.assertEqual(birth['release_date_not_provided'], 1)
        marriage_coverage = next(row for row in payload['coverage']
                                 if row['code'] == 'CN_MARRIAGES')
        self.assertEqual(marriage_coverage['latest_source_tier'], '官方数据转引')
        self.assertEqual(payload['local_sync_at'], payload['updated_at'])
        self.assertTrue(any('万对' in warning for warning in payload['warnings']))

    def test_birth_history_estimate_is_separate_and_starts_from_1978(self):
        inserted = sync_annual_macro_snapshots(self.conn)
        self.assertGreater(inserted, 0)
        self.conn.close()
        payload = build_china_macro_payload(self.path)
        estimated = payload['series']['CN_BIRTHS_ESTIMATED']
        self.assertEqual(estimated[0]['period'], '1978')
        self.assertEqual(estimated[-1]['period'], '2025')
        self.assertEqual(len(estimated), 48)
        row_1978 = next(row for row in estimated if row['period'] == '1978')
        self.assertAlmostEqual(row_1978['value'], 1745.0, places=1)
        self.assertEqual(row_1978['data_status'], 'derived')
        self.assertIn('出生率', row_1978['formula'])
        self.assertIsNone(row_1978['source_url'])
        charts = {chart['code']: chart for group in payload['groups']
                  if group['code'] == 'demography' for chart in group['charts']}
        self.assertEqual(charts['birth_history']['series'],
                         ['CN_BIRTHS', 'CN_BIRTHS_ESTIMATED'])
        self.assertIn('不替代官方绝对数', charts['birth_history']['note'])
        self.assertTrue(any('历史估算覆盖1978—2025' in warning
                            for warning in payload['warnings']))

    def test_frontend_contract_keeps_units_and_freshness_explicit(self):
        html = (Path(__file__).resolve().parents[1] / 'static' / 'china_macro.html').read_text(
            encoding='utf-8')
        self.assertIn('<title>中国宏观经济、人口与家庭</title>', html)
        self.assertIn('同步本地整理快照', html)
        self.assertIn('来源发布日期', html)
        self.assertIn('当前范围内仅 1 期的序列未绘制趋势', html)
        self.assertIn("groupCode==='demography'", html)
        self.assertNotIn('万人/万对', html)
        self.assertNotIn('出生、结婚与离婚合计', html)

    def test_file_update_entrypoint(self):
        self.conn.close()
        result = update_china_demography(self.path)
        self.assertTrue(result['success'])
        self.assertGreater(result['records_upserted'], 150)


if __name__ == '__main__':
    unittest.main()
