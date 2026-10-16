"""Recurring queue, public-link discovery and candidate evidence boundaries."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.enrich_faculty_priority import collect, posting_url
from services.faculty_job_fit_service import default_profile, validate_profile
from services.faculty_jobs_gap import compare_candidate
from services.faculty_jobs_maintenance import due_queue
from services.faculty_jobs_requirements import empty_fields, parse_posting, public_url
from services.faculty_jobs_actions import posting_kind_filter


class QueueTests(unittest.TestCase):
    def test_pool_filter_uses_official_evidence_and_keeps_unread_advertisements(self):
        conn=sqlite3.connect(':memory:')
        conn.executescript("CREATE TABLE jobs(id,title_raw,description_excerpt); CREATE TABLE reads(job_id,status,identity_verified,source_kind,fields_json); INSERT INTO jobs VALUES(1,'Assistant Professor',''),(2,'Lecturer Pool',''),(3,'Lecturer','');")
        conn.execute('INSERT INTO reads VALUES(3,?,?,?,?)',('ok',1,'official_posting',json.dumps({'posting_kind':{'status':'supported','value':'pool'}})))
        base='SELECT j.id FROM jobs j LEFT JOIN reads rq ON rq.job_id=j.id WHERE '
        self.assertEqual([1],[r[0] for r in conn.execute(base+posting_kind_filter('advertisement'))])
        self.assertEqual([2,3],[r[0] for r in conn.execute(base+posting_kind_filter('pool'))])
        conn.close()
    def test_failed_attempt_backoff_and_urgent_priority(self):
        now = datetime(2026, 10, 2, tzinfo=timezone.utc)
        jobs = [
            {"id": 1, "requirements": {}, "timing": {}, "actions": []},
            {"id": 2, "requirements": {"latest_attempt": {"status": "blocked", "captured_at": "2026-10-01T00:00:00Z"}}},
            {"id": 3, "requirements": {}, "timing": {"review_date": "2026-10-03"}},
        ]
        self.assertEqual([3, 1], [j['id'] for j in due_queue(jobs, now=now)])
        self.assertEqual([3, 1, 2], [j['id'] for j in due_queue(jobs, now=now, force=True)])

    def test_failed_read_does_not_reset_official_refresh_time(self):
        job = {"id": 1, "last_verified_at": "2026-09-01T00:00:00Z", "requirements": {
            "latest_attempt": {"status": "blocked", "captured_at": "2026-09-23T00:00:00Z"}}}
        self.assertEqual([job], due_queue([job], now=datetime(2026, 10, 2, tzinfo=timezone.utc)))
        self.assertEqual("2026-09-01T00:00:00Z", job['last_verified_at'])


class DiscoveryTests(unittest.TestCase):
    def test_literal_board_apply_redirect_reaches_verified_employer(self):
        pages = {
            "https://jobs.chronicle.com/job/1": '<h1>Assistant Professor of Information Systems</h1><p>Example University</p><p>Candidates must conduct research and teach Information Systems courses. Applications are open for this faculty position.</p><a href="/apply/1">Apply on website</a>',
            "https://jobs.chronicle.com/apply/1": '<meta http-equiv="refresh" content="0;url=https://example.edu/job/1"><p>Continue to the employer website</p>',
            "https://example.edu/job/1": '<h1>Assistant Professor of Information Systems</h1><p>Example University</p><p>Candidates must maintain a productive research program. The appointment begins in August 2027.</p><a href="/apply/1">Apply now</a>',
        }
        class Adapter:
            def request(self, url):
                html = pages[url]
                return SimpleNamespace(text=html, content=html.encode(), encoding='utf-8', headers={},url=url,status_code=200)
        job = {"id": 1, "title_raw": "Assistant Professor of Information Systems", "institution_name": "Example University", "sources": [{"active": True, "source_url": "https://jobs.chronicle.com/job/1"}]}
        with tempfile.TemporaryDirectory() as temp, patch('scripts.enrich_faculty_priority.SourceAdapter', return_value=Adapter()), patch('scripts.enrich_faculty_priority.time.sleep'):
            result = collect(Path(temp)/'new',jobs=[job],max_pages=3,progress=lambda event: None)
        employer = result['reads'][-1]
        self.assertEqual('official_posting', employer['source_kind'])
        self.assertEqual('ok', employer['status'])
        self.assertEqual('https://example.edu/job/1', employer['source_url'])
        self.assertTrue(employer['identity_verified'])

    def test_board_redirect_is_not_assumed_official_and_private_links_are_rejected(self):
        url, kind = posting_url({'id': 1, 'official_url': 'https://www.higheredjobs.com/clickthru/redirect.cfm?JobCode=1'})
        self.assertEqual('job_board',kind)
        for url in ('http://127.0.0.1:5001/profile','http://10.0.0.1/','http://localhost/private'):
            self.assertFalse(public_url(url))


class GapTests(unittest.TestCase):
    def job(self):
        fields = empty_fields('not_stated')
        for key, quote in {'phd_requirement':'A Ph.D. is required by the start date.',
                           'start_date':'The appointment begins in August 2027.',
                           'research_requirements':'Candidates must demonstrate a record of peer-reviewed publications.'}.items():
            fields[key] = {'status':'supported','quote':quote,'value':quote}
        return {'id':1,'requirements':{'status':'ok','source_kind':'official_posting','identity_verified':True,
            'source_url':'https://example.edu/job/1','captured_at':'2026-10-02T01:00:00Z','fields':fields}}

    def test_preferences_do_not_establish_qualifications(self):
        profile = default_profile()
        profile['research_keywords']=['peer-reviewed publications']
        result = compare_candidate(self.job(),profile)
        self.assertFalse(result['profile_configured'])
        self.assertEqual('profile_needed',next(r for r in result['rows'] if r['field']=='research_requirements')['status'])

    def test_user_reported_2029_and_zero_publications_make_specific_preparation_items(self):
        profile = default_profile()
        profile['qualification_evidence']={'doctoral_status':'doctoral_student','expected_completion_date':'2029',
            'research_record':'Three projects in progress; no publications.','teaching_record':'Teaching OB online.',
            'peer_reviewed_publications':0,'independent_courses_taught':None}
        result = compare_candidate(self.job(),profile)
        statuses = {r['field']:r['status'] for r in result['rows']}
        self.assertEqual('timeline_gap',statuses['start_date'])
        self.assertEqual('preparation_needed',statuses['research_requirements'])
        self.assertEqual('2029',validate_profile(profile)['qualification_evidence']['expected_completion_date'])

    def test_board_requirements_are_not_promoted_to_official_candidate_gaps(self):
        job = self.job();job['requirements']['source_kind']='job_board'
        result=compare_candidate(job,default_profile())
        self.assertTrue(all(r['status']=='source_needed' for r in result['rows']))
        self.assertTrue(all(r['official_quote'] is None for r in result['rows']))

    def test_plural_until_filled_and_degree_alternatives_preserve_literal_conditions(self):
        html='<h1>Associate Lecturer in Management</h1><p>Example University</p><p>Required Qualifications:</p><p>A master’s degree or PhD candidacy in the area of instruction.</p><p>Applications will be reviewed on a rolling basis until the positions are filled.</p><p>Please apply online and with the following:</p><p>Cover letter and curriculum vitae.</p>'
        result=parse_posting(html,{'title_raw':'Associate Lecturer in Management','institution_name':'Example University'},'https://example.edu/job/8')
        self.assertEqual('open_until_filled',result['fields']['recruitment_mode']['value'])
        self.assertIn('master’s degree or PhD candidacy',result['fields']['phd_requirement']['quote'])
        self.assertEqual('supported',result['fields']['materials']['status'])

    def test_contract_comes_from_this_position_not_the_faculty_description(self):
        job={'title_raw':'Assistant Professor of Information Systems','institution_name':'Example University'}
        header='<h1>Assistant Professor of Information Systems</h1><p>Example University</p>'
        actual=parse_posting(header+'<p>The position is a dual-mission tenure-track appointment.</p><p>Candidates must conduct scholarly research and teach in the business school.</p>',job,'https://example.edu/job/1')
        self.assertEqual('tenure_track',actual['fields']['appointment_contract']['value'])
        general=parse_posting(header+'<p>Our faculty includes tenured and tenure-track faculty. All faculty members support a collegial atmosphere and the school mission in research and teaching.</p>',job,'https://example.edu/job/1')
        self.assertEqual('not_stated',general['fields']['appointment_contract']['status'])


class GapRouteSecurityTests(unittest.TestCase):
    def test_private_gap_route_requires_private_access(self):
        import http.client
        import threading
        import server
        httpd=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        worker=threading.Thread(target=httpd.serve_forever,daemon=True)
        worker.start()
        try:
            with patch.object(server,'_faculty_jobs_private_access_allowed',return_value=False):
                for path in ('/api/faculty-jobs/9/gap','/api/faculty-jobs/profile'):
                    client=http.client.HTTPConnection('127.0.0.1',httpd.server_port,timeout=10)
                    client.request('GET',path)
                    response=client.getresponse();body=response.read();client.close()
                    self.assertEqual(403,response.status)
                    self.assertNotIn(b'candidate_record',body)
        finally:
            httpd.shutdown();httpd.server_close();worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
