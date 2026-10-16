# -*- coding: utf-8 -*-
import unittest
import http.client
import json
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import server
from services.faculty_jobs_service import ensure_faculty_jobs_tables


NOW = '2026-08-28T00:00:00Z'


class FacultyJobSecurityTests(unittest.TestCase):
    def test_private_access_is_loopback_only_by_default(self):
        self.assertTrue(server._faculty_jobs_private_access_allowed('127.0.0.1'))
        self.assertTrue(server._faculty_jobs_private_access_allowed('::1'))
        self.assertFalse(server._faculty_jobs_private_access_allowed('192.0.2.40'))

    def test_server_exposes_private_route_guard_and_patch_method(self):
        source = __import__('pathlib').Path(server.__file__).read_text(encoding='utf-8')
        self.assertIn('academic_career_local_only', source)
        self.assertIn('def do_PATCH(self)', source)
        self.assertIn("path == '/api/faculty-jobs/profile'", source)
        self.assertIn("path == '/api/my-applications'", source)

    def test_real_http_public_response_omits_private_fields(self):
        with tempfile.TemporaryDirectory(prefix='faculty-security-http-') as directory:
            db = Path(directory) / 'faculty_jobs.db'
            ensure_faculty_jobs_tables(db)
            conn = sqlite3.connect(db)
            conn.execute("""
                INSERT INTO jobs
                  (canonical_key,title_raw,title_normalized,derived_quality,business_scope,
                   faculty_market_role,faculty_market_eligible,status,first_seen_at,last_seen_at,
                   created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, ('security-fixture', 'Assistant Professor of Finance',
                  'assistant professor of finance', 'accepted', 'business_discipline',
                  'faculty', 1, 'open', NOW, NOW, NOW, NOW))
            conn.commit()
            conn.close()

            httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(server, 'FACULTY_DB_PATH', db):
                    connection = http.client.HTTPConnection(
                        '127.0.0.1', httpd.server_port, timeout=20)
                    # The fixture is a business-discipline posting and the
                    # default view is now explicit business-school evidence.
                    # This test is about private fields never leaving the
                    # server, so it asks for a view that contains a row.
                    connection.request('GET', '/api/faculty-jobs?scope=business&limit=1')
                    response = connection.getresponse()
                    body = json.loads(response.read().decode('utf-8'))
                    self.assertEqual(200, response.status)
                    self.assertTrue(body.get('jobs'))
                    self.assertNotIn('personal_state', body['jobs'][0])
                    self.assertNotIn('fit', body['jobs'][0])
                    connection.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)

    def test_real_http_private_route_rejects_when_access_policy_denies(self):
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(server, '_faculty_jobs_private_access_allowed', return_value=False):
                connection = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=20)
                connection.request('GET', '/api/faculty-jobs/profile')
                response = connection.getresponse()
                payload = json.loads(response.read().decode('utf-8'))
                self.assertEqual(403, response.status)
                self.assertEqual('academic_career_local_only', payload.get('code'))
                connection.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
