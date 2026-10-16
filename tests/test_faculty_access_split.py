"""HTTP enforcement of public academic data versus direct-local operations."""
import http.client
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import server
from services.faculty_jobs_service import ensure_faculty_jobs_tables

CANARY = 'LOCAL_APPLICATION_NOTE_NOT_PUBLIC'


class LocalRequestTests(unittest.TestCase):
    def test_direct_loopback_hosts_and_same_origin(self):
        for peer, host in (('127.0.0.1','127.0.0.1:5001'),('::1','[::1]:5001'),
                           ('::ffff:127.0.0.1','localhost:5001')):
            self.assertTrue(server._faculty_jobs_direct_local_allowed(peer,{'Host':host}))
            self.assertTrue(server._faculty_jobs_direct_local_allowed(peer,{'Host':host,'Origin':'http://'+host}))

    def test_proxy_headers_rebinding_and_cross_site_fail_closed(self):
        bad_headers = [{'Host':'research.zhengresearch.com'}, {'Host':'evil.example'},
            {'Host':'127.0.0.1:5001','Origin':'https://evil.example'},
            {'Host':'127.0.0.1:5001','Origin':'null'},
            {'Host':'127.0.0.1:5001','Sec-Fetch-Site':'cross-site'}, {'Host':'localhost:bad'}]
        for name in ('CF-Connecting-IP','CF-Ray','X-Forwarded-For','X-Forwarded-Host',
                     'X-Forwarded-Proto','Forwarded','X-Real-IP'):
            for value in ('','bad','127.0.0.1','203.0.113.1'):
                bad_headers.append({'Host':'127.0.0.1:5001',name:value})
        for headers in bad_headers:
            self.assertFalse(server._faculty_jobs_direct_local_allowed('127.0.0.1',headers),headers)
        self.assertFalse(server._faculty_jobs_direct_local_allowed('192.0.2.1',{'Host':'localhost:5001'}))

    def test_global_admin_overrides_do_not_grant_academic_private_access(self):
        with patch.object(server,'ADMIN_TOKEN','test-admin'), patch.object(server,'ALLOW_REMOTE_WRITES',True), patch.object(server,'FACULTY_JOBS_ALLOW_REMOTE_PRIVATE',True):
            self.assertFalse(server._faculty_jobs_private_access_allowed('203.0.113.10','test-admin'))


class AccessHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db=Path(cls.temp.name)/'jobs.db'
        ensure_faculty_jobs_tables(cls.db)
        conn=sqlite3.connect(cls.db)
        conn.execute("""INSERT INTO jobs(id,canonical_key,title_raw,title_normalized,derived_quality,business_scope,
            faculty_market_role,faculty_market_eligible,status,country_code,first_seen_at,last_seen_at,created_at,updated_at)
            VALUES(1,'access-test','Assistant Professor of Management','assistant professor of management','accepted','business_school',
            'faculty',1,'open','US','2026-10-02','2026-10-02','2026-10-02','2026-10-02')""")
        conn.execute("INSERT INTO user_job_state(job_id,state,priority,notes,saved_at,updated_at) VALUES(1,'Saved',1,?,'2026-10-02','2026-10-02')",(CANARY,))
        conn.commit();conn.close()
        cls.db_patch=patch.object(server,'FACULTY_DB_PATH',cls.db);cls.db_patch.start()
        cls.httpd=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.worker=threading.Thread(target=cls.httpd.serve_forever,daemon=True);cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown();cls.httpd.server_close();cls.worker.join(timeout=3)
        cls.db_patch.stop();cls.temp.cleanup()

    def request(self,path,method='GET',headers=None,body=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.httpd.server_port,timeout=20)
        conn.request(method,path,body=body,headers=headers or {})
        r=conn.getresponse();data=r.read().decode('utf8');result=(r.status,dict(r.getheaders()),data)
        conn.close();return result

    def test_public_data_and_export_remain_available_without_personal_state(self):
        headers={'Host':'research.zhengresearch.com','CF-Connecting-IP':'203.0.113.10'}
        for path in ('/faculty-jobs','/school-explorer','/api/faculty-jobs?scope=business_school',
                     '/api/faculty-jobs/summary','/api/faculty-jobs/filters',
                     '/api/faculty-jobs/1','/api/faculty-jobs/export.csv',
                     '/api/faculty-jobs/requirements-comparison'):
            status,_,body=self.request(path,headers=headers)
            self.assertEqual(200,status,path)
            self.assertNotIn(CANARY,body)
            if path.startswith('/api/'):
                self.assertNotIn('candidate_record',body)
                self.assertNotIn('"personal_state"',body)
                self.assertNotIn('"fit"',body)

    def test_private_pages_exports_and_apis_reject_all_remote_modes(self):
        routes=('/my-applications','/my_applications.html','/api/faculty-jobs/profile',
            '/api/faculty-jobs/1/gap','/api/my-applications','/api/faculty-jobs/saved-searches',
            '/api/faculty-jobs/alerts','/api/faculty-jobs/duplicates','/api/institution-aliases',
            '/api/faculty-jobs?private=1','/api/faculty-jobs/1?private=true','/api/faculty-jobs/export.csv?private=1')
        modes=({'Host':'research.zhengresearch.com','CF-Connecting-IP':'203.0.113.10'},
               {'CF-Connecting-IP':'bad'}, {'CF-Connecting-IP':'127.0.0.1'},
               {'X-Forwarded-For':'203.0.113.10'})
        with patch.object(server,'ADMIN_TOKEN','test-admin'),patch.object(server,'ALLOW_REMOTE_WRITES',True),patch.object(server,'FACULTY_JOBS_ALLOW_REMOTE_PRIVATE',True),patch.object(server,'TRUST_CLOUDFLARE_HEADERS',False):
            for mode in modes:
                for path in routes:
                    status,h,body=self.request(path,headers={**mode,'X-Research-Admin-Token':'test-admin'})
                    self.assertEqual(403,status,(path,mode))
                    self.assertEqual('academic_career_local_only',json.loads(body)['code'])
                    self.assertIn('private',h.get('Cache-Control',''))
                    self.assertNotIn(CANARY,body)

    def test_remote_mutations_are_denied_before_any_side_effect(self):
        routes=(('POST','/api/faculty-jobs/update'),('POST','/api/faculty-jobs/aacsb/update'),
            ('POST','/api/faculty-jobs/profile'),('POST','/api/my-applications'),
            ('PATCH','/api/my-applications/1'),('POST','/api/faculty-jobs/saved-searches'),
            ('POST','/api/faculty-jobs/saved-searches/run'),('POST','/api/faculty-jobs/alerts/seen'),
            ('PATCH','/api/faculty-jobs/duplicates/1'),('POST','/api/faculty-jobs/duplicates/batch'),
            ('POST','/api/schools/1/enrich'),('POST','/api/schools/1/override'),
            ('POST','/api/faculty-jobs/1/scope-override'),('POST','/api/institution-aliases'))
        with patch.object(server,'ADMIN_TOKEN','test-admin'),patch.object(server,'ALLOW_REMOTE_WRITES',True),patch.object(server,'FACULTY_JOBS_ALLOW_REMOTE_PRIVATE',True),patch.object(server,'_run_update_job') as update,patch.object(server,'save_profile_payload') as save:
            for method,path in routes:
                status,_,_=self.request(path,method,{'Host':'research.zhengresearch.com','CF-Connecting-IP':'203.0.113.10','X-Research-Admin-Token':'test-admin','Content-Type':'application/json'},'{}')
                self.assertEqual(403,status,(method,path))
            update.assert_not_called();save.assert_not_called()

    def test_local_and_remote_capabilities_and_local_private_data(self):
        status,_,body=self.request('/api/faculty-jobs/capabilities')
        self.assertEqual(200,status);self.assertTrue(json.loads(body)['personal'])
        status,_,body=self.request('/api/faculty-jobs/capabilities',headers={'Host':'research.zhengresearch.com'})
        self.assertEqual(200,status);self.assertEqual('public',json.loads(body)['mode'])
        self.assertFalse(json.loads(body)['personal']);self.assertFalse(json.loads(body)['manage'])
        status,h,body=self.request('/my-applications')
        self.assertEqual(200,status);self.assertIn('private',h['Cache-Control'])
        status,_,body=self.request('/api/my-applications')
        self.assertEqual(200,status);self.assertIn(CANARY,body)

    def test_local_management_routes_remain_available(self):
        with patch.object(server,'_run_update_job',return_value={'status':'fixture-accepted'}) as update:
            status,_,_=self.request('/api/faculty-jobs/update','POST',{'Content-Type':'application/json'},'{"sources":["ais"],"max_pages":1}')
            self.assertEqual(200,status);update.assert_called_once()
        with patch.object(server,'patch_application',return_value={'ok':True}) as edit:
            status,_,_=self.request('/api/my-applications/1','PATCH',{'Content-Type':'application/json'},'{"notes":"fixture"}')
            self.assertEqual(200,status);edit.assert_called_once()


if __name__=='__main__':
    unittest.main()
