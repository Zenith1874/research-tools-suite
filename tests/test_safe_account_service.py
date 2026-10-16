import io
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook

from services.safe_account_service import parse_safe_workbook,period_from_header,update_safe_accounts
from services.china_macro_service import connect,ensure_china_macro_tables


def workbook_bytes(sheets):
    book=Workbook();book.remove(book.active)
    for name,rows in sheets.items():
        sheet=book.create_sheet(name)
        for row in rows:sheet.append(row)
    stream=io.BytesIO();book.save(stream);return stream.getvalue()


class SafeAccountTests(unittest.TestCase):
    def test_bop_original_currencies_signs_and_annual_quarter_separation(self):
        data=workbook_bytes({
            '季度BOP（美元）':[['中国国际收支平衡表'],['单位:亿美元'],['项目','2026Q1','2026Q2'],
                ['1. 经常账户',1843.1,1937.24],['2.2.1.1 直接投资',-88,-70],
                ['2.2.1.1.1资产',-300,-336],['2.2.1.1.2负债',212,266],['备注：'],['未知',999,999]],
            '年度BOP（人民币）':[['中国国际收支平衡表'],['单位:亿元人民币'],['项目',2025],['1. 经常账户',51433.6]]})
        result=parse_safe_workbook(data,'bop')
        values={(row['indicator_code'],row['period']):row['value'] for row in result['observations']}
        self.assertEqual(values['CN_SAFE_BOP_DI_ASSETS_USD_Q','2026-06'],-336)
        self.assertEqual(values['CN_SAFE_BOP_DI_LIABILITIES_USD_Q','2026-06'],266)
        self.assertEqual(values['CN_SAFE_BOP_CA_CNY_A','2025'],51433.6)
        self.assertNotIn(('CN_SAFE_BOP_CA_CNY_Q','2025-12'),values)
        self.assertFalse(any(row['value']==999 for row in result['details']))

    def test_iip_stock_context_and_pre2015_regime_do_not_merge(self):
        data=workbook_bytes({'季度IIP(美元)':[['中国国际投资头寸表'],['单位:亿美元'],
            ['项目','2014年末','2015年3月末'],['净头寸',19000,20000],['资产',60000,63000],
            ['1直接投资',10000,11000],['负债',41000,43000],['1直接投资',20000,21000]]})
        result=parse_safe_workbook(data,'iip')
        values={(row['indicator_code'],row['period']):row['value'] for row in result['observations']}
        self.assertEqual(values['CN_SAFE_IIP_LEGACY_NET_USD_Q','2014-12'],19000)
        self.assertEqual(values['CN_SAFE_IIP_NET_USD_Q','2015-03'],20000)
        self.assertEqual(values['CN_SAFE_IIP_DI_ASSETS_USD_Q','2015-03'],11000)
        self.assertEqual(values['CN_SAFE_IIP_DI_LIABILITIES_USD_Q','2015-03'],21000)

    def test_unit_and_header_failures_stay_visible(self):
        bad=workbook_bytes({'季度BOP（美元）':[['单位:亿元人民币'],['项目','2026Q2'],['1.经常账户',1937]]})
        with self.assertRaises(ValueError):parse_safe_workbook(bad,'bop')
        self.assertIsNone(period_from_header('上半年', 'quarterly','bop'))
        self.assertEqual(period_from_header('2011年末','quarterly','iip'),'2011-12')
        no_period=workbook_bytes({'季度BOP（美元）':[['单位:亿美元'],['项目','上半年'],['1.经常账户',1937]]})
        with self.assertRaisesRegex(ValueError,'No explicit usable periods'):
            parse_safe_workbook(no_period,'bop')

    def archived_source(self,directory,amount=1937.24,vintage='v1',release='2026-09-29'):
        directory.mkdir()
        manifest=[]
        for kind,sheet,rows in (
            ('bop','季度BOP（美元）',[['1.经常账户',amount]]),
            ('iip','季度IIP(美元)',[['净头寸',4000],['资产',12000],['负债',8000]])):
            page=f'<p>发布日期：{release}</p><a href="/safe/file/{kind}-{vintage}.xlsx">官方原表</a>'
            files={f'{kind}-page.html':page.encode('utf-8'),
                   f'{kind}.xlsx':workbook_bytes({sheet:[['单位:亿美元'],['项目','2026Q2'],*rows]})}
            for name,content in files.items():
                (directory/name).write_bytes(content)
                manifest.append({'raw_path':name,'raw_sha256':hashlib.sha256(content).hexdigest(),
                                 'retrieved_at':'2026-10-12T00:00:00Z'})
        (directory/'audit.json').write_text(json.dumps({'source_manifest':manifest}),encoding='utf-8')

    def test_idempotent_replay_and_changed_vintage_preserves_prior_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'test.db';source=root/'v1'
            self.archived_source(source)
            first=update_safe_accounts(db,source_dir=source)
            self.assertTrue(first['success']);self.assertEqual(first['records_upserted'],4)
            second=update_safe_accounts(db,source_dir=source)
            self.assertEqual(second['records_upserted'],0);self.assertEqual(second['raw_cells_inserted'],0)
            newer=root/'v2';self.archived_source(newer,amount=1940,vintage='v2',release='2026-10-01')
            self.assertTrue(update_safe_accounts(db,source_dir=newer)['success'])
            conn=connect(db)
            try:
                revised=conn.execute("SELECT value,release_date FROM china_macro_observations WHERE indicator_code='CN_SAFE_BOP_CA_USD_Q'").fetchone()
                self.assertEqual(tuple(revised),(1940,'2026-10-01'))
                old=conn.execute("SELECT old_row_json FROM safe_account_revisions WHERE indicator_code='CN_SAFE_BOP_CA_USD_Q'").fetchone()
                self.assertEqual(json.loads(old[0])['value'],1937.24)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0],4)
            finally:conn.close()

    def test_failed_book_rolls_back_and_does_not_report_uncommitted_raw_cells(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'test.db';source=root/'source'
            self.archived_source(source)
            conn=connect(db);ensure_china_macro_tables(conn)
            conn.execute("""CREATE TRIGGER reject_iip BEFORE INSERT ON china_macro_observations
                WHEN NEW.indicator_code LIKE 'CN_SAFE_IIP_%'
                BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
            conn.commit();conn.close()
            result=update_safe_accounts(db,source_dir=source)
            self.assertFalse(result['success']);self.assertEqual(result['records_upserted'],1)
            self.assertEqual(result['raw_cells_inserted'],1)
            conn=connect(db)
            try:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM safe_account_cells').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM china_macro_observations').fetchone()[0],1)
            finally:conn.close()

    def test_tampered_archive_is_rejected_without_creating_observations(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'test.db';source=root/'source';self.archived_source(source)
            (source/'bop.xlsx').write_bytes(b'not the archived workbook')
            result=update_safe_accounts(db,source_dir=source)
            self.assertFalse(result['success'])
            self.assertTrue(any('hash mismatch' in row['error'] for row in result['errors']))
            conn=connect(db)
            try:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM china_macro_observations WHERE indicator_code LIKE 'CN_SAFE_BOP_%'").fetchone()[0],0)
            finally:conn.close()


if __name__=='__main__':unittest.main()
