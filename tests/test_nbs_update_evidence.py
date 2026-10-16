"""Exercise the existing normal updater/repair paths using isolated databases and bytes."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from services.china_macro_service import (
    update_china_macro,repair_existing_release_fields,connect,ensure_china_macro_tables,
    _fetch_macro_release,PARSER_CODE_SHA256,macro_ingestion_runtime,
)


class NbsUpdateEvidenceTests(unittest.TestCase):
    def cpi(self):
        rows=[('居民消费价格',0.2,0.9,0.9),('其中：食品',0.4,-1.7,-0.9),('非食品',0.2,1.5,1.3),
              ('其中：消费品',0.5,1,1),('服务',-0.2,0.8,0.8),('其中：不包括食品和能源',0,1,1.1)]
        table='<table><tr><td></td><td>环比</td><td>同比</td><td>1—9月同比</td></tr>'
        table+=''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
        return '<meta name="PubDate" content="2026/10/14 09:30">全国居民消费价格同比上涨0.9%。全国居民消费价格环比上涨0.2%。'+table

    def ppi(self):
        return ('<meta name="PubDate" content="2026/10/14 09:30">全国工业生产者出厂价格同比上涨5.0%，环比上涨1.2%。'
                '工业生产者购进价格同比上涨6.9%，环比上涨1.2%。一、工业生产者价格同比变动情况。'
                '生产资料价格同比上涨6.5%，生活资料价格下降0.1%。二、工业生产者价格环比变动情况。')

    def response(self,html,url):
        response=requests.Response();response.status_code=200;response._content=html.encode('utf-8');response.url=url
        response._content_consumed=True
        response.encoding='utf-8';return response

    def release(self,kind):
        return 'https://www.stats.gov.cn/'+kind+'.html',('2026年9月份居民消费价格同比上涨0.9%' if kind=='cpi' else '2026年9月份工业生产者出厂价格同比上涨5.0%')

    def test_existing_normal_update_archives_before_storing_all19_fields_and_skips_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'test.db';archive=Path(tmp)/'raw'
            def get(url,**kwargs):
                kind='cpi' if url.endswith('/cpi.html') else 'ppi'
                return self.response(self.cpi() if kind=='cpi' else self.ppi(),url)
            with patch('services.china_macro_service.discover_releases',side_effect=lambda kind,*args,**kwargs:{'2026-09':self.release(kind)}), \
                 patch('services.china_macro_service.sync_annual_macro_snapshots',return_value=0), \
                 patch('services.china_macro_service.requests.get',side_effect=get) as network:
                first=update_china_macro(database,start_year=2026,kinds=('cpi','ppi'),sleep_seconds=0,archive_root=archive)
                self.assertTrue(first['success']);self.assertEqual(first['records_upserted'],19)
                self.assertEqual(len(first['source_archives']),2)
                conn=connect(database);before=[dict(r) for r in conn.execute('select * from china_macro_observations order by id')];conn.close()
                self.assertTrue(all(r['release_date']=='2026-10-14' and r['retrieved_at'] and r['raw_sha256'] for r in before))
                receipts=list(archive.glob('*/receipt.json'));self.assertEqual(len(receipts),2)
                for file in receipts:
                    record=json.loads(file.read_text(encoding='utf-8'))
                    self.assertEqual(record['parser_code_sha256'],PARSER_CODE_SHA256)
                    self.assertEqual(hashlib.sha256((file.parent/record['raw_path']).read_bytes()).hexdigest(),record['raw_sha256'])
                self.assertNotIn(tmp,json.dumps(first))
                network.reset_mock()
                second=update_china_macro(database,start_year=2026,kinds=('cpi','ppi'),sleep_seconds=0,archive_root=archive)
                self.assertEqual(second['records_upserted'],0);network.assert_not_called()
                conn=connect(database);after=[dict(r) for r in conn.execute('select * from china_macro_observations order by id')];conn.close()
                self.assertEqual(before,after)

    def seed(self,database):
        conn=connect(database);ensure_china_macro_tables(conn)
        url,title=self.release('cpi')
        conn.execute('''insert into china_macro_observations
                     (indicator_code,indicator_name,period,value,unit,frequency,data_status,source_url,source_title,parser_version)
                     values (?,?,?,?,?,?,?,?,?,?)''',('CN_CPI_YOY','old fixture','2026-09',0.7,'%','monthly','official',url,title,'legacy'))
        conn.commit();old=dict(conn.execute('select * from china_macro_observations').fetchone());conn.close();return old

    def test_existing_repair_path_preserves_full_prior_row_and_first_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'test.db';archive=Path(tmp)/'raw';old=self.seed(database)
            with patch('services.china_macro_service.requests.get',return_value=self.response(self.cpi(),self.release('cpi')[0])):
                result=repair_existing_release_fields(database,'cpi',archive_root=archive)
            self.assertTrue(result['success']);self.assertEqual(result['records_upserted'],13)
            conn=connect(database);row=dict(conn.execute("select * from china_macro_observations where indicator_code='CN_CPI_YOY'").fetchone());conn.close()
            self.assertEqual(row['value'],0.9);self.assertEqual(row['original_value'],0.7)
            snapshots=list(archive.glob('*/before-*.json'));self.assertEqual(len(snapshots),1)
            self.assertEqual(json.loads(snapshots[0].read_text(encoding='utf-8')),old)

    def test_archive_failure_keeps_existing_values_and_metadata_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'test.db';old=self.seed(database);unwritable=Path(tmp)/'not-a-directory'
            unwritable.write_text('preserved fixture',encoding='utf-8')
            with patch('services.china_macro_service.requests.get',return_value=self.response(self.cpi(),self.release('cpi')[0])):
                result=repair_existing_release_fields(database,'cpi',archive_root=unwritable)
            self.assertFalse(result['success']);self.assertTrue(result['errors'])
            conn=connect(database);self.assertEqual(dict(conn.execute('select * from china_macro_observations').fetchone()),old);conn.close()

    def test_late_persistence_failure_rolls_back_the_whole_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'test.db';self.seed(database)
            conn=connect(database)
            conn.execute("update china_macro_observations set indicator_code='CN_CPI_FOOD_YOY',value=-2")
            conn.commit();old=dict(conn.execute('select * from china_macro_observations').fetchone());conn.close()
            with patch('services.china_macro_service.requests.get',return_value=self.response(self.cpi(),self.release('cpi')[0])), \
                 patch('services.china_macro_service.preserve_prior_observation',side_effect=OSError('fixture disk failure')):
                result=repair_existing_release_fields(database,'cpi',archive_root=Path(tmp)/'raw')
            self.assertFalse(result['success']);self.assertEqual(result['records_upserted'],0)
            conn=connect(database);rows=[dict(r) for r in conn.execute('select * from china_macro_observations')];conn.close()
            self.assertEqual(rows,[old])

    def test_one_release_persistence_failure_does_not_prevent_the_next_kind(self):
        from services import china_macro_service as service
        real_persist=service._persist_captured_release
        def persist(conn,period,url,title,values,survey,evidence,repair=False):
            if 'CN_CPI_YOY' in values:raise OSError('fixture CPI persistence failure')
            return real_persist(conn,period,url,title,values,survey,evidence,repair)
        def get(url,**kwargs):return self.response(self.cpi() if url.endswith('/cpi.html') else self.ppi(),url)
        with tempfile.TemporaryDirectory() as tmp, \
             patch('services.china_macro_service.discover_releases',side_effect=lambda kind,*args,**kwargs:{'2026-09':self.release(kind)}), \
             patch('services.china_macro_service.sync_annual_macro_snapshots',return_value=0), \
             patch('services.china_macro_service.requests.get',side_effect=get), \
             patch('services.china_macro_service._persist_captured_release',side_effect=persist):
            database=Path(tmp)/'test.db'
            result=update_china_macro(database,start_year=2026,kinds=('cpi','ppi'),sleep_seconds=0,archive_root=Path(tmp)/'raw')
            self.assertEqual(result['records_upserted'],6);self.assertTrue(result['errors'])
            conn=connect(database)
            self.assertEqual(conn.execute("select count(*) from china_macro_observations where indicator_code like 'CN_CPI_%'").fetchone()[0],0)
            self.assertEqual(conn.execute('select count(*) from china_macro_observations').fetchone()[0],6);conn.close()

    def test_existing_http_uri_is_securely_upgraded_without_using_another_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            original='http://www.stats.gov.cn/ppi.html';secure='https://www.stats.gov.cn/ppi.html'
            with patch('services.china_macro_service.requests.get',return_value=self.response(self.ppi(),secure)) as network:
                result=_fetch_macro_release('ppi','2026-09',original,self.release('ppi')[1],archive_root=tmp)
            self.assertIsNone(result[5]);self.assertEqual(result[1],secure)
            self.assertEqual(network.call_args.args[0],secure)
            record=json.loads(next(Path(tmp).glob('*/receipt.json')).read_text(encoding='utf-8'))
            self.assertEqual(record['original_requested_url'],original)

    def test_runtime_identity_is_the_loaded_constant_not_a_fresh_disk_read(self):
        with patch('services.china_macro_service.PARSER_CODE_SHA256','b'*64):
            info=macro_ingestion_runtime()
        self.assertEqual(info['parser_code_sha256'],'b'*64)
        self.assertEqual(info['capture_version'],'nbs-release-evidence-v1')
        self.assertEqual(len(info['capture_code_sha256']),64)
        self.assertNotIn('archive_root',info)

    def test_stream_limit_and_partial_response_cannot_publish_official_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            url,title=self.release('ppi')
            response=self.response(self.ppi(),url)
            with patch('services.china_macro_service.requests.get',return_value=response), \
                 patch('services.china_macro_service.NBS_RELEASE_MAX_BYTES',10):
                result=_fetch_macro_release('ppi','2026-09',url,title,archive_root=tmp)
            self.assertTrue(result[5]);self.assertEqual(result[3],{})
            self.assertEqual(list(Path(tmp).glob('*/receipt.json')),[])
            partial=self.response(self.ppi(),url);partial.status_code=206
            with patch('services.china_macro_service.requests.get',return_value=partial):
                result=_fetch_macro_release('ppi','2026-09',url,title,archive_root=tmp)
            self.assertTrue(result[5]);self.assertIsNone(result[6])

    def test_wrong_table_month_is_archived_but_never_ingested_as_another_month(self):
        with tempfile.TemporaryDirectory() as tmp:
            url,title=self.release('ppi')
            html=self.ppi()+'<h3>2026年8月工业生产者价格主要数据</h3>'
            with patch('services.china_macro_service.requests.get',return_value=self.response(html,url)):
                result=_fetch_macro_release('ppi','2026-09',url,title,archive_root=tmp)
            self.assertTrue(result[5]);self.assertEqual(result[3],{})
            record=json.loads(next(Path(tmp).glob('*/receipt.json')).read_text(encoding='utf-8'))
            self.assertEqual(record['reported_period'],'2026-08');self.assertEqual(record['period_hint'],'2026-09')


if __name__=='__main__':
    unittest.main()
