import copy
import json
import tempfile
import unittest
from pathlib import Path

from services.china_macro_service import connect, ensure_china_macro_tables
from services.mofcom_fdi_bulletin_service import (
    annual_snapshot_observations, parse_fdi_annual_appendix, sync_mofcom_fdi_annual,
)
from scripts.collect_mofcom_bulletin import bulletin_pdf_links, official_mofcom_url


def fixture_appendix():
    rows = '\n'.join(f'{year} 1 1.0' for year in range(1983, 2026))
    return '附表1 截至2025年外商直接投资情况\n金额单位：亿美元\n总计 44 44.0\n1979—1982 1 1.0\n' + rows


def fixture_snapshot():
    return {'schema_version': 1, **parse_fdi_annual_appendix(fixture_appendix()),
            'source_url': 'https://hzfimage.mofcom.gov.cn/fixture.pdf', 'source_title': 'Official test fixture',
            'release_date': '2026-09-16', 'retrieved_at': '2026-10-13', 'reviewed_at': '2026-10-13',
            'raw_sha256': 'a' * 64, 'parser_notes': 'Annual fixture; not real observations.'}


class MofcomFdiBulletinTests(unittest.TestCase):
    def test_annual_rows_and_combined_block_have_different_grain(self):
        parsed = parse_fdi_annual_appendix(fixture_appendix())
        self.assertEqual(len(parsed['annual_rows']), 43)
        self.assertEqual(parsed['combined_early_block']['period'], '1979-1982')
        self.assertEqual(parsed['annual_rows'][0]['year'], 1983)
        rows = annual_snapshot_observations(fixture_snapshot())
        self.assertEqual(len(rows), 86)
        self.assertEqual({row['frequency'] for row in rows}, {'annual'})
        self.assertNotIn('1982', {row['period'] for row in rows})

    def test_missing_duplicate_or_unbalanced_source_rows_fail(self):
        original = fixture_appendix()
        for text in (original.replace('1983 1 1.0\n', ''), original + '\n2025 1 1.0',
                     original.replace('总计 44 44.0', '总计 45 44.0'),
                     original.replace('金额单位：亿美元', '金额单位：人民币')):
            with self.assertRaises(ValueError):
                parse_fdi_annual_appendix(text)

    def test_snapshot_needs_official_host_and_complete_actual_years(self):
        for field, value in (('source_url', 'https://evil.example/mofcom.gov.cn/fixture.pdf'),
                             ('raw_sha256', 'missing'), ('reviewed_at', None)):
            snapshot = fixture_snapshot()
            snapshot[field] = value
            with self.assertRaises(ValueError):
                annual_snapshot_observations(snapshot)
        snapshot = fixture_snapshot()
        snapshot['annual_rows'].pop()
        with self.assertRaises(ValueError):
            annual_snapshot_observations(snapshot)

    def test_source_link_discovery_accepts_only_observed_official_pdf(self):
        page = 'https://wzs.mofcom.gov.cn/source.html'
        html = '<a href="https://hzfimage.mofcom.gov.cn/report.pdf">中国外资统计公报2026.pdf</a>'
        self.assertEqual(bulletin_pdf_links(html, page), 'https://hzfimage.mofcom.gov.cn/report.pdf')
        self.assertFalse(official_mofcom_url('https://evil.example/mofcom.gov.cn/report.pdf'))
        self.assertFalse(official_mofcom_url('https://user:secret@wzs.mofcom.gov.cn/report.pdf'))
        with self.assertRaises(ValueError):
            bulletin_pdf_links('<a href="https://evil.example/report.pdf">中国外资统计公报.pdf</a>', page)

    def test_annual_sync_is_idempotent_retains_vintages_and_never_changes_monthly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            snapshot = fixture_snapshot()
            (path / 'v1.json').write_text(json.dumps(snapshot), encoding='utf-8')
            conn = connect(path / 'source.db')
            ensure_china_macro_tables(conn)
            conn.execute('INSERT INTO china_macro_observations (indicator_code,period,value) VALUES (?,?,?)',
                         ('CN_MOFCOM_FDI_USD_YTD', '2021-12', 1734.8))
            conn.commit()
            self.assertEqual(sync_mofcom_fdi_annual(conn, path)['records_changed'], 86)
            self.assertEqual(sync_mofcom_fdi_annual(conn, path)['records_changed'], 0)
            second = copy.deepcopy(snapshot)
            second.update(raw_sha256='b' * 64, reviewed_at='2026-10-14')
            second['annual_rows'][-1]['amount_usd'] = 2.0
            (path / 'v2.json').write_text(json.dumps(second), encoding='utf-8')
            self.assertEqual(sync_mofcom_fdi_annual(conn, path)['records_changed'], 86)
            previous = json.loads(conn.execute('SELECT previous_row_json FROM mofcom_fdi_annual_revisions '
                'WHERE indicator_code=? AND period=?', ('CN_MOFCOM_FDI_USD_ANNUAL', '2025')).fetchone()[0])
            self.assertEqual(previous['value'], 1)
            self.assertEqual(conn.execute('SELECT value FROM china_macro_observations WHERE indicator_code=? '
                'AND period=?', ('CN_MOFCOM_FDI_USD_YTD', '2021-12')).fetchone()[0], 1734.8)
            conn.close()


if __name__ == '__main__':
    unittest.main()
