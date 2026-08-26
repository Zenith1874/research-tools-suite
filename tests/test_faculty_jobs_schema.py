# -*- coding: utf-8 -*-
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.faculty_jobs_service import (
    add_evidence,
    build_faculty_job_detail,
    build_faculty_job_summary,
    build_faculty_jobs_payload,
    create_application,
    ensure_faculty_jobs_tables,
    export_faculty_jobs_csv,
    list_my_applications,
    save_scope_override,
    save_override,
    school_detail,
    update_faculty_jobs,
    _extract_school_name,
)
from services.faculty_jobs_school_service import list_schools
from services.faculty_jobs_sources.base import AdapterResponse, SourceJob


class FakeAdapter:
    name = 'ais'
    adapter_name = 'ais'

    def __init__(self, responses=None, error=False, name=None):
        if name:
            self.name = name
            self.adapter_name = name
        self.responses = list(responses or [])
        self.error = error
        self.timeout = 5
        self.max_pages = 1

    def fetch(self):
        if self.error:
            raise RuntimeError('fixture source failed')
        jobs = self.responses.pop(0) if self.responses else []
        return AdapterResponse(jobs=list(jobs), pages_fetched=1)


def fixture_job(source_id='1', title='Assistant Professor of Management', institution='Example University', location='New York, NY'):
    return SourceJob(
        source='ais', source_job_id=source_id, source_url=f'https://board.example/job/{source_id}',
        title_raw=title, institution_raw=institution, location_raw=location,
        description_excerpt='Tenure-track appointment. PhD required.', captured_at='2026-08-23T00:00:00Z',
    )


class FacultyJobSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'faculty_jobs.db'
        ensure_faculty_jobs_tables(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_has_required_tables_and_source_link_key(self):
        conn = sqlite3.connect(self.db)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({'sources', 'ingestion_runs', 'jobs', 'job_sources', 'source_job_records', 'job_field_provenance', 'possible_duplicates', 'user_job_state', 'application_events'}.issubset(names))
        pk = [row[1] for row in conn.execute('PRAGMA table_info(job_sources)') if row[5]]
        self.assertEqual(['job_id', 'source_id', 'source_job_id'], pk)
        self.assertIn('description_excerpt', {row[1] for row in conn.execute('PRAGMA table_info(jobs)')})
        self.assertTrue({'business_scope', 'business_scope_confidence', 'business_scope_reason'}.issubset({row[1] for row in conn.execute('PRAGMA table_info(jobs)')}))
        self.assertTrue({'deadline_evidence', 'deadline_parse_reason', 'location_evidence', 'original_title', 'hiring_cycle_reason'}.issubset({row[1] for row in conn.execute('PRAGMA table_info(jobs)')}))
        self.assertTrue({'source_coverage_history', 'institution_aliases', 'faculty_job_repair_audit', 'faculty_job_migrations', 'job_scope_overrides'}.issubset(names))
        self.assertTrue({'is_current'}.issubset({row[1] for row in conn.execute('PRAGMA table_info(institutions)')}))
        self.assertTrue({'is_current'}.issubset({row[1] for row in conn.execute('PRAGMA table_info(business_schools)')}))
        conn.close()

    def test_public_payload_omits_private_state_and_detail_keeps_provenance(self):
        result = update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[fixture_job()]])])
        self.assertTrue(result['ok'])
        payload = build_faculty_jobs_payload(self.db, {'limit': 10})
        self.assertEqual(1, payload['pagination']['total'])
        job = payload['jobs'][0]
        self.assertEqual('business_discipline', job['business_scope'])
        self.assertNotIn('personal_state', job)
        self.assertNotIn('fit', job)
        self.assertTrue(job['sources'])
        detail = build_faculty_job_detail(self.db, job['id'])
        self.assertTrue(detail['job']['provenance'])
        self.assertTrue(detail['job']['status_history'])

        saved = create_application(self.db, job['id'], {'state': 'Saved', 'notes': 'local only'})
        self.assertTrue(saved['ok'])
        public_again = build_faculty_jobs_payload(self.db, {'limit': 10})['jobs'][0]
        self.assertNotIn('notes', public_again)
        private = list_my_applications(self.db)['applications'][0]
        self.assertEqual('local only', private['personal_state']['notes'])
        self.assertIn('score', private['fit'])

    def test_business_scope_is_default_and_all_scope_is_explicit(self):
        jobs = [
            fixture_job('business', 'Assistant Professor of Management'),
            fixture_job('medicine', 'Assistant Professor of Emergency Medicine'),
            fixture_job('technical', 'Product Manager, Money'),
        ]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        business = build_faculty_jobs_payload(self.db, {'limit': 20})
        all_jobs = build_faculty_jobs_payload(self.db, {'scope': 'all', 'limit': 20})
        self.assertEqual('business', business['meta']['scope'])
        self.assertEqual(1, business['pagination']['total'])
        self.assertEqual(3, all_jobs['pagination']['total'])
        self.assertEqual('business_discipline', business['jobs'][0]['business_scope'])

    def test_student_role_keeps_raw_record_but_never_creates_market_school_link(self):
        job = SourceJob(
            source='ais', source_job_id='ga-boundary',
            source_url='https://board.example/job/ga-boundary',
            title_raw='Graduate Assistant, Master of Accountancy',
            institution_raw='Example University', school_raw='College of Business',
            location_raw='New York, NY',
            description_excerpt='Student appointment in the College of Business.',
            captured_at='2026-08-24T00:00:00Z',
        )
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            'SELECT id,school_id,faculty_market_role,faculty_market_eligible,business_scope FROM jobs'
        ).fetchone()
        self.assertIsNone(row[1])
        self.assertEqual('student_role', row[2])
        self.assertEqual(0, row[3])
        self.assertEqual('non_academic', row[4])
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM source_job_records').fetchone()[0])
        conn.close()
        self.assertEqual(0, build_faculty_jobs_payload(self.db, {'limit': 20})['pagination']['total'])
        self.assertEqual(1, build_faculty_jobs_payload(self.db, {'scope': 'all', 'limit': 20})['pagination']['total'])

    def test_boundary_replay_clears_a_legacy_student_school_link(self):
        job = SourceJob(
            source='ais', source_job_id='legacy-ga',
            source_url='https://board.example/job/legacy-ga',
            title_raw='Graduate Assistant, MBA Program', institution_raw='Example University',
            school_raw='College of Business', location_raw='New York, NY',
            captured_at='2026-08-24T00:00:00Z',
        )
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        institution_id = conn.execute('SELECT institution_id FROM jobs').fetchone()[0]
        now = '2026-08-24T01:00:00Z'
        school_id = conn.execute(
            """INSERT INTO business_schools
               (institution_id,official_name,normalized_name,created_at,updated_at)
               VALUES (?,?,?,?,?)""",
            (institution_id, 'College of Business', 'college of business', now, now),
        ).lastrowid
        conn.execute(
            """UPDATE jobs SET school_id=?,business_scope='business_school',
               faculty_market_role='faculty',faculty_market_eligible=1,
               school_evidence_context='structured_posting'""",
            (school_id,),
        )
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=28')
        conn.commit()
        conn.close()
        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        repaired = conn.execute(
            'SELECT school_id,faculty_market_role,faculty_market_eligible,business_scope FROM jobs'
        ).fetchone()
        self.assertIsNone(repaired[0])
        self.assertEqual(('student_role', 0, 'non_academic'), repaired[1:])
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM faculty_job_migrations WHERE version=28').fetchone()[0])
        conn.close()

    def test_ihe_structured_school_link_survives_boundary_replay(self):
        job = SourceJob(
            source='inside_higher_ed', source_job_id='ihe-structured-school',
            source_url='https://careers.insidehighered.com/job/ihe-structured-school/example/',
            title_raw='Assistant Professor of Organizational Behavior',
            institution_raw='The Ohio State University',
            school_raw='Fisher College of Business',
            department_raw='Fisher College | Management and Human Resources-Interim',
            location_raw='Columbus, Ohio, US',
            description_excerpt=(
                'The Department of Management and Human Resources at The Ohio State '
                "University's Fisher College of Business invites applications."
            ),
            captured_at='2026-08-24T00:00:00Z',
            extra={
                'detail_schema': True,
                'detail_school_found': True,
                'school_evidence_context': 'structured_posting',
            },
        )
        update_faculty_jobs(
            self.db,
            source_names=['inside_higher_ed'],
            adapters=[FakeAdapter([[job]], name='inside_higher_ed')],
        )
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE jobs SET school_id=NULL,business_scope='business_discipline',"
            "business_scope_confidence='medium',school_evidence_context='unknown'"
        )
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=29')
        conn.commit()
        conn.close()

        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        repaired = conn.execute(
            'SELECT school_id,business_scope,school_evidence_context FROM jobs'
        ).fetchone()
        school = conn.execute(
            'SELECT official_name FROM business_schools WHERE id=?', (repaired[0],)
        ).fetchone()
        self.assertIsNotNone(repaired[0])
        self.assertEqual(('business_school', 'structured_posting'), repaired[1:])
        self.assertEqual('Fisher College of Business', school[0])
        self.assertEqual(1, conn.execute(
            'SELECT COUNT(*) FROM faculty_job_migrations WHERE version=29'
        ).fetchone()[0])
        conn.close()

    def test_ihe_legacy_collaborator_school_link_is_cleared_by_current_rule(self):
        job = SourceJob(
            source='inside_higher_ed', source_job_id='ihe-legacy-collaborator',
            source_url='https://careers.insidehighered.com/job/ihe-legacy-collaborator/example/',
            title_raw='Associate Professor Tenure Track',
            institution_raw='Dartmouth College',
            school_raw='Tuck School of Business',
            location_raw='Hanover, New Hampshire, US',
            description_excerpt=(
                'The Department of Epidemiology at the Geisel School of Medicine invites '
                'applications for a tenure-track faculty position. Faculty collaborate with '
                'colleagues at the Tuck School of Business.'
            ),
            captured_at='2026-08-24T00:00:00Z',
            extra={'school_evidence_context': 'structured_posting'},
        )
        update_faculty_jobs(
            self.db,
            source_names=['inside_higher_ed'],
            adapters=[FakeAdapter([[job]], name='inside_higher_ed')],
        )
        conn = sqlite3.connect(self.db)
        self.assertIsNotNone(conn.execute('SELECT school_id FROM jobs').fetchone()[0])
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=33')
        conn.commit()
        conn.close()

        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        repaired = conn.execute(
            'SELECT school_id,business_scope,school_evidence_context FROM jobs'
        ).fetchone()
        self.assertIsNone(repaired[0])
        self.assertEqual(('non_business', 'unknown'), repaired[1:])
        self.assertEqual(1, conn.execute(
            "SELECT COUNT(*) FROM faculty_job_repair_audit "
            "WHERE action='faculty_market_boundary_repair'"
        ).fetchone()[0])
        conn.close()

    def test_school_entity_chrome_label_merges_into_same_institution_aacsb_school(self):
        update_faculty_jobs(
            self.db,
            source_names=['ais'],
            adapters=[FakeAdapter([[fixture_job(institution='Example State University')]])],
        )
        conn = sqlite3.connect(self.db)
        institution_id = conn.execute('SELECT institution_id FROM jobs').fetchone()[0]
        now = '2026-08-24T00:00:00Z'
        target_id = conn.execute(
            """INSERT INTO business_schools
                 (institution_id,official_name,normalized_name,aacsb,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (institution_id, 'Culverhouse College of Business',
             'culverhouse college of business', 1, now, now),
        ).lastrowid
        conn.execute(
            """INSERT INTO school_evidence
                 (school_id,evidence_type,value,source_name,source_url,verified_at,confidence)
               VALUES (?,?,?,?,?,?,?)""",
            (target_id, 'AACSB', 'Business', 'AACSB',
             'https://www.aacsb.edu/accredited/example', now, 'high'),
        )
        old_id = conn.execute(
            """INSERT INTO business_schools
                 (institution_id,official_name,normalized_name,created_at,updated_at)
               VALUES (?,?,?,?,?)""",
            (institution_id, 'Position Summary The Culverhouse College of Business',
             'position summary the culverhouse college of business', now, now),
        ).lastrowid
        conn.execute('UPDATE jobs SET school_id=?', (old_id,))
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=34')
        conn.commit()
        conn.close()

        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        self.assertEqual(target_id, conn.execute('SELECT school_id FROM jobs').fetchone()[0])
        self.assertEqual(0, conn.execute(
            'SELECT is_current FROM business_schools WHERE id=?', (old_id,),
        ).fetchone()[0])
        self.assertEqual(1, conn.execute(
            "SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='school_entity_label_merge'"
        ).fetchone()[0])
        conn.close()

    def test_current_market_excludes_passed_deadline_and_stale_unverified_posting(self):
        jobs = [
            SourceJob(
                source='ais', source_job_id='past-deadline',
                source_url='https://board.example/job/past-deadline',
                title_raw='Assistant Professor of Management',
                institution_raw='Example University', location_raw='Boston, MA',
                posted_date_raw='2020-01-01', deadline_raw='2020-02-01',
                description_excerpt='Application deadline: February 1, 2020.',
                captured_at='2026-08-24T00:00:00Z',
            ),
            SourceJob(
                source='ais', source_job_id='stale-rolling',
                source_url='https://board.example/job/stale-rolling',
                title_raw='Assistant Professor of Marketing',
                institution_raw='Example University', location_raw='Boston, MA',
                posted_date_raw='2020-01-01', deadline_raw='Open until filled',
                description_excerpt='Applications accepted until the position is filled.',
                captured_at='2026-08-24T00:00:00Z',
            ),
        ]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        self.assertEqual(0, build_faculty_jobs_payload(self.db, {'limit': 10})['pagination']['total'])
        self.assertEqual(2, build_faculty_jobs_payload(
            self.db, {'scope': 'all', 'limit': 10},
        )['pagination']['total'])
        closed = build_faculty_jobs_payload(self.db, {'status': 'closed', 'limit': 10})
        stale = build_faculty_jobs_payload(self.db, {'status': 'unknown', 'limit': 10})
        self.assertEqual(['Assistant Professor of Management'], [job['title_raw'] for job in closed['jobs']])
        self.assertEqual(['Assistant Professor of Marketing'], [job['title_raw'] for job in stale['jobs']])

    def test_location_replay_prefers_named_canadian_province_over_ca_token(self):
        job = fixture_job(
            'canada-alias', 'Assistant Professor of Management',
            institution='McMaster University', location='Hamilton, Ontario, CA',
        )
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        conn.execute(
            """UPDATE jobs SET country='United States',country_code='US',region_group='United States',
               state_province='CA',location_evidence='state_province'"""
        )
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=28')
        conn.commit()
        conn.close()
        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            'SELECT country,country_code,region_group,state_province,city,location_evidence FROM jobs'
        ).fetchone()
        self.assertEqual(
            ('Canada', 'CA', 'Canada', 'ON', 'Hamilton', 'source_location_replay'),
            row,
        )
        self.assertEqual(
            1,
            conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='source_location_country_replay'").fetchone()[0],
        )
        conn.close()

    def test_v38_replays_washington_dc_without_deleting_source_records(self):
        job = fixture_job(
            'washington-dc', 'Professor of Management',
            institution='Example University', location='Washington D.C., US',
        )
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE jobs SET state_province='WA'")
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=38')
        conn.commit()
        conn.close()

        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        self.assertEqual(
            ('Washington D.C.', 'DC', 'US'),
            conn.execute('SELECT city,state_province,country_code FROM jobs').fetchone(),
        )
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM source_job_records').fetchone()[0])
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM job_sources').fetchone()[0])
        self.assertEqual(
            1,
            conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='source_location_country_replay'").fetchone()[0],
        )
        conn.close()

    def test_location_replay_does_not_relabel_an_already_correct_job(self):
        update_faculty_jobs(
            self.db, source_names=['ais'],
            adapters=[FakeAdapter([[fixture_job('location-noop')]])],
        )
        conn = sqlite3.connect(self.db)
        before = conn.execute('SELECT location_evidence FROM jobs').fetchone()[0]
        conn.execute('DELETE FROM faculty_job_migrations WHERE version IN (28,30)')
        conn.commit()
        conn.close()
        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        after = conn.execute('SELECT location_evidence FROM jobs').fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(
            0,
            conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='source_location_country_replay'").fetchone()[0],
        )
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM faculty_job_migrations WHERE version=30').fetchone()[0])
        conn.close()

    def test_v29_restores_an_evidence_only_v28_write_without_deleting_audit(self):
        update_faculty_jobs(
            self.db, source_names=['ais'],
            adapters=[FakeAdapter([[fixture_job('location-v29')]])],
        )
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        job = conn.execute('SELECT * FROM jobs').fetchone()
        link = conn.execute('SELECT * FROM job_sources').fetchone()
        observed = '2026-08-24T02:00:00Z'
        old = {
            'country': job['country'], 'country_code': job['country_code'],
            'region_group': job['region_group'], 'state_province': job['state_province'],
            'city': job['city'], 'location_evidence': job['location_evidence'],
            'institution_id': job['institution_id'],
        }
        new = {**old, 'location_evidence': 'source_location_replay'}
        conn.execute("UPDATE jobs SET location_evidence='source_location_replay' WHERE id=?", (job['id'],))
        conn.execute("UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name='country'", (job['id'],))
        replay_provenance_id = conn.execute("""
            INSERT INTO job_field_provenance
              (job_id,field_name,source_id,source_job_id,source_url,value_text,evidence_text,captured_at,is_current)
            VALUES (?,?,?,?,?,?,?,?,1)
        """, (
            job['id'], 'country', link['source_id'], link['source_job_id'], link['source_url'],
            job['country'], 'Structured source location: New York, NY', observed,
        )).lastrowid
        conn.execute("""
            INSERT INTO faculty_job_repair_audit
              (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            observed, 'source_location_country_replay', job['id'], link['source_id'],
            link['source_job_id'], json.dumps(old), json.dumps(new), 'synthetic v28 no-op',
        ))
        conn.execute("""
            INSERT INTO job_status_history
              (job_id,observed_at,status,deadline,salary_raw,title_raw,source_count,change_reason)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            job['id'], observed, job['status'], job['deadline_date'], job['salary_raw'],
            job['title_raw'], 1, 'source_location_country_replay',
        ))
        conn.execute('DELETE FROM faculty_job_migrations WHERE version=30')
        conn.commit()
        conn.close()

        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        self.assertEqual(old['location_evidence'], conn.execute('SELECT location_evidence FROM jobs').fetchone()[0])
        self.assertEqual(0, conn.execute('SELECT is_current FROM job_field_provenance WHERE id=?', (replay_provenance_id,)).fetchone()[0])
        self.assertEqual(
            'source_location_country_replay_noop_superseded',
            conn.execute('SELECT change_reason FROM job_status_history WHERE observed_at=?', (observed,)).fetchone()[0],
        )
        self.assertEqual(
            1,
            conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='source_location_replay_noop_reversal'").fetchone()[0],
        )
        conn.close()

    def test_quarantined_derived_rows_stay_out_of_default_market_view(self):
        job = fixture_job('quarantined', 'Assistant Professor of Management')
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        job_id = conn.execute('SELECT id FROM jobs WHERE title_raw LIKE ?', ('%Assistant Professor of Management%',)).fetchone()[0]
        conn.execute("UPDATE jobs SET derived_quality='quarantined', status='unknown' WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        business = build_faculty_jobs_payload(self.db, {'limit': 20})
        audit = build_faculty_jobs_payload(self.db, {'scope': 'all', 'limit': 20})
        self.assertEqual(0, business['pagination']['total'])
        self.assertEqual(1, audit['pagination']['total'])

    def test_different_disciplines_at_one_school_are_not_merged_or_flagged(self):
        """Management and Marketing at one school are two jobs, not a duplicate.

        This assertion changed on 2026-08-26. Fuzzy confidence used to be scored
        over a string containing the institution, city and state, which the
        candidate gate had already forced to be equal; the identical prefix
        inflated the ratio so that any two jobs at one school cleared the 0.82
        threshold. Scoring the discriminating fields only puts this pair at
        0.744, and it is no longer raised for review -- correctly, since the two
        postings are different vacancies. The guarantee the original test was
        written for, that borderline records are never silently merged, is
        unchanged and still asserted here.
        """
        jobs = [
            fixture_job('a', 'Assistant Professor of Management', 'Example University'),
            fixture_job('b', 'Assistant Professor of Marketing', 'Example University'),
        ]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        conn = sqlite3.connect(self.db)
        count = conn.execute('SELECT COUNT(*) FROM possible_duplicates').fetchone()[0]
        jobs_count = conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        conn.close()
        self.assertEqual(2, jobs_count, 'the two postings must both survive')
        self.assertEqual(0, count, 'different disciplines are not a duplicate candidate')

    def test_near_identical_titles_are_still_raised_for_review(self):
        """The review path must still fire for pairs that really do look alike."""
        jobs = [
            fixture_job('a', 'Assistant Professor of Marketing', 'Example University'),
            fixture_job('b', 'Assistant Professor of Marketing (2 Positions)', 'Example University'),
        ]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        conn = sqlite3.connect(self.db)
        count = conn.execute('SELECT COUNT(*) FROM possible_duplicates').fetchone()[0]
        jobs_count = conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        basis = conn.execute('SELECT match_basis FROM possible_duplicates').fetchone()
        conn.close()
        self.assertEqual(2, jobs_count, 'a review signal is never an identity decision')
        self.assertGreaterEqual(count, 1)
        self.assertEqual('fuzzy_review_only', basis[0])

    def test_same_official_url_can_merge_but_source_records_remain(self):
        first = fixture_job('url-a', 'Assistant Professor of Finance')
        second = SourceJob(
            source='ais', source_job_id='url-b', source_url='https://board.example/job/url-b',
            official_url='https://example.edu/apply/finance', title_raw='Assistant Professor of Finance',
            institution_raw='Example University', location_raw='New York, NY',
            description_excerpt='Tenure-track appointment. PhD required.', captured_at='2026-08-23T00:00:00Z',
        )
        first = SourceJob(**{**first.__dict__, 'official_url': 'https://example.edu/apply/finance'})
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[first, second]])])
        conn = sqlite3.connect(self.db)
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
        self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM source_job_records').fetchone()[0])
        self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM job_sources').fetchone()[0])
        conn.close()

    def test_same_official_url_across_sources_keeps_both_provenance_records(self):
        first = SourceJob(
            source='ais', source_job_id='cross-ais', source_url='https://ais.example/cross-ais',
            official_url='https://example.edu/jobs/finance', title_raw='Assistant Professor of Finance',
            institution_raw='Example University', location_raw='New York, NY',
            description_excerpt='Tenure-track appointment. PhD required.', captured_at='2026-08-23T00:00:00Z',
        )
        second = SourceJob(
            source='inside_higher_ed', source_job_id='cross-ihe', source_url='https://ihe.example/cross-ihe',
            official_url='https://example.edu/jobs/finance', title_raw='Assistant Professor of Finance',
            institution_raw='Example University', location_raw='New York, NY',
            description_excerpt='Tenure-track appointment. PhD required.', captured_at='2026-08-23T00:00:00Z',
        )
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[first]])])
        update_faculty_jobs(self.db, source_names=['inside_higher_ed'], adapters=[FakeAdapter([[second]], name='inside_higher_ed')])
        conn = sqlite3.connect(self.db)
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0])
        self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM source_job_records').fetchone()[0])
        self.assertEqual(2, conn.execute('SELECT COUNT(*) FROM job_sources').fetchone()[0])
        self.assertEqual({'cross-ais', 'cross-ihe'}, {row[0] for row in conn.execute('SELECT source_job_id FROM job_field_provenance')})
        conn.close()

    def test_country_display_name_and_iso_code_share_filtered_summary(self):
        job = fixture_job('uk-filter', 'Assistant Professor of Finance', location='London, UK')
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        by_name = build_faculty_jobs_payload(self.db, {'country': 'United Kingdom', 'limit': 20})
        by_code = build_faculty_jobs_payload(self.db, {'country': 'GB', 'limit': 20})
        summary = build_faculty_job_summary(self.db, {'country': 'GB'})['summary']
        self.assertEqual(1, by_name['pagination']['total'])
        self.assertEqual(1, by_code['pagination']['total'])
        self.assertEqual(1, summary['active_jobs'])
        self.assertEqual('GB', by_name['jobs'][0]['country_code'])
        self.assertEqual(1, len(summary['by_region']))

    def test_csv_exports_more_than_two_hundred_current_results(self):
        jobs = [fixture_job(f'bulk-{index}', f'Assistant Professor of Management {index}') for index in range(205)]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        csv_text = export_faculty_jobs_csv(self.db, {'scope': 'all'})
        self.assertEqual(206, len(csv_text.splitlines()))

    def test_repeated_table_initialization_is_idempotent(self):
        ensure_faculty_jobs_tables(self.db)
        ensure_faculty_jobs_tables(self.db)
        conn = sqlite3.connect(self.db)
        self.assertEqual('ok', conn.execute('PRAGMA quick_check').fetchone()[0])
        self.assertEqual([], conn.execute('PRAGMA foreign_key_check').fetchall())
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM faculty_job_migrations WHERE version=1').fetchone()[0])
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM faculty_job_migrations WHERE version=12').fetchone()[0])
        self.assertEqual(1, conn.execute('SELECT COUNT(*) FROM faculty_job_migrations WHERE version=13').fetchone()[0])
        conn.close()

    def test_source_health_excludes_disabled_opt_in_sources(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE sources SET last_status='ok' WHERE enabled=1")
        conn.execute("UPDATE sources SET last_status='ok' WHERE name='aacsb_official'")
        conn.commit()
        conn.close()
        coverage = build_faculty_job_summary(self.db, {'scope': 'all'})['summary']['coverage']
        self.assertEqual(coverage['sources_enabled'], coverage['sources_healthy'])

    def test_scope_override_is_auditable_and_does_not_change_raw_scope(self):
        jobs = [
            fixture_job('business-raw', 'Assistant Professor of Management'),
            fixture_job('medicine-raw', 'Assistant Professor of Emergency Medicine'),
        ]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        conn = sqlite3.connect(self.db)
        medicine_id = conn.execute("SELECT id FROM jobs WHERE title_raw LIKE '%Emergency Medicine%'").fetchone()[0]
        business_id = conn.execute("SELECT id FROM jobs WHERE title_raw LIKE '%Management%'").fetchone()[0]
        conn.close()
        save_scope_override(self.db, medicine_id, {'action': 'include', 'reason': 'Manual review found an explicit business faculty context.'})
        save_scope_override(self.db, business_id, {'action': 'exclude', 'reason': 'Manual review excluded this posting from the local market view.'})
        payload = build_faculty_jobs_payload(self.db, {'limit': 20})
        self.assertEqual([medicine_id], [job['id'] for job in payload['jobs']])
        conn = sqlite3.connect(self.db)
        self.assertEqual('non_business', conn.execute('SELECT business_scope FROM jobs WHERE id=?', (medicine_id,)).fetchone()[0])
        self.assertEqual(2, conn.execute("SELECT COUNT(*) FROM faculty_job_repair_audit WHERE action='scope_override'").fetchone()[0])
        conn.close()

    def test_school_directory_excludes_orphaned_school_rows(self):
        conn = sqlite3.connect(self.db)
        now = '2026-08-23T00:00:00Z'
        institution_id = conn.execute(
            """INSERT INTO institutions
               (official_name,normalized_name,country,country_code,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            ('Corrected University', 'corrected university', 'Ireland', 'IE', now, now),
        ).lastrowid
        conn.execute(
            """INSERT INTO business_schools
               (institution_id,official_name,normalized_name,created_at,updated_at)
               VALUES (?,?,?,?,?)""",
            (institution_id, 'School of Business', 'school of business', now, now),
        )
        conn.commit()
        conn.close()
        self.assertEqual([], list_schools(self.db)['schools'])

    def test_school_directory_excludes_quarantined_job_rows(self):
        job = fixture_job('quarantined-school')
        job = SourceJob(**{**job.__dict__, 'school_raw': 'School of Business'})
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        school_id = conn.execute('SELECT school_id FROM jobs WHERE title_raw=?', ('Assistant Professor of Management',)).fetchone()[0]
        conn.execute("UPDATE jobs SET derived_quality='quarantined', status='unknown' WHERE school_id=?", (school_id,))
        conn.commit()
        conn.close()
        self.assertEqual([], list_schools(self.db)['schools'])
        self.assertEqual([], school_detail(self.db, school_id)['school']['jobs'])

    def test_school_evidence_and_manual_override_are_explicit(self):
        job = SourceJob(
            source='ais', source_job_id='school-evidence', source_url='https://board.example/school-evidence',
            title_raw='Assistant Professor of Management', institution_raw='Evidence University',
            school_raw='Evidence School of Business', location_raw='Boston, MA',
            description_excerpt='Tenure-track appointment. PhD required.', captured_at='2026-08-23T00:00:00Z',
        )
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([[job]])])
        conn = sqlite3.connect(self.db)
        try:
            school_id = conn.execute(
                "SELECT school_id FROM jobs WHERE title_raw=?",
                ('Assistant Professor of Management',),
            ).fetchone()[0]
        finally:
            conn.close()
        before = school_detail(self.db, school_id)['school']
        self.assertEqual('linked_school_entity', before['evidence_status'])
        self.assertEqual('Unclassified', before['business_research_tier'])
        add_evidence(self.db, school_id, {
            'evidence_type': 'AACSB', 'value': 'Official accreditation page',
            'source_name': 'Example University', 'source_url': 'https://evidence.example/aacsb',
            'confidence': 'high',
        })
        with_evidence = school_detail(self.db, school_id)['school']
        self.assertEqual('verified_school_evidence', with_evidence['evidence_status'])
        self.assertEqual('T4', with_evidence['business_research_tier'])
        save_override(self.db, school_id, {
            'tier': 'T2', 'reason': 'Local review recorded with official evidence.',
            'source_url': 'https://evidence.example/review',
        })
        overridden = school_detail(self.db, school_id)['school']
        self.assertEqual('manual_school_override', overridden['evidence_status'])
        self.assertEqual('T2', overridden['business_research_tier'])

    def test_explicit_school_employer_is_split_from_university_entity(self):
        jobs = [
            SourceJob(
                source='ais', source_job_id='wpi-school', source_url='https://board.example/wpi-school',
                title_raw='Assistant Professor of Information Systems', institution_raw='The WPI Business School',
                location_raw='Worcester, MA', description_excerpt='The WPI Business School Worcester, Massachusetts, United States',
                captured_at='2026-08-23T00:00:00Z',
            ),
            SourceJob(
                source='ais', source_job_id='kings-school', source_url='https://board.example/kings-school',
                title_raw='Lecturer in Marketing', institution_raw="King's Business School King's College London",
                location_raw='London, UK', description_excerpt="King's Business School King's College London",
                captured_at='2026-08-23T00:00:00Z',
            ),
        ]
        update_faculty_jobs(self.db, source_names=['ais'], adapters=[FakeAdapter([jobs])])
        conn = sqlite3.connect(self.db)
        # The source ID lives on job_sources, so inspect the two canonical rows
        # by their titles instead of relying on a denormalized job column.
        rows = conn.execute('''SELECT j.title_raw, i.official_name, bs.official_name
                               FROM jobs j LEFT JOIN institutions i ON i.id=j.institution_id
                               LEFT JOIN business_schools bs ON bs.id=j.school_id
                               WHERE j.title_raw IN (?,?) ORDER BY j.title_raw''',
                            ('Assistant Professor of Information Systems', 'Lecturer in Marketing')).fetchall()
        conn.close()
        self.assertEqual([
            ('Assistant Professor of Information Systems', 'Worcester Polytechnic Institute', 'WPI Business School'),
            ('Lecturer in Marketing', "King's College London", "King's Business School"),
        ], [tuple(row) for row in rows])

    def test_school_extraction_does_not_prefix_disciplines_or_title_words(self):
        self.assertEqual('HKU Business School', _extract_school_name(None, 'Statistics in HKU Business School and...'))
        self.assertEqual('Sheffield Business School', _extract_school_name(None, 'International Business Sheffield Business School'))
        self.assertEqual('Business School', _extract_school_name(None, 'in Management Accounting Business School'))
        self.assertEqual('Darla Moore School of Business', _extract_school_name(None, 'Darla Moore School of Business'))
        self.assertEqual(
            'Darla Moore School of Business',
            _extract_school_name(None, 'Department: DMSB Marketing', 'University of South Carolina'),
        )
        self.assertIsNone(_extract_school_name(None, 'Department: DMSB Marketing', 'Example University'))


class FacultyJobLifecycleTests(unittest.TestCase):
    def test_three_successful_missing_runs_close_source_job_but_error_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'faculty_jobs.db'
            ensure_faculty_jobs_tables(db)
            job = fixture_job()
            adapter = FakeAdapter([[job], [], [], []])
            update_faculty_jobs(db, source_names=['ais'], adapters=[adapter])
            update_faculty_jobs(db, source_names=['ais'], adapters=[adapter])
            update_faculty_jobs(db, source_names=['ais'], adapters=[adapter])
            conn = sqlite3.connect(db)
            self.assertEqual(1, conn.execute('SELECT active FROM job_sources').fetchone()[0])
            conn.close()
            update_faculty_jobs(db, source_names=['ais'], adapters=[adapter])
            conn = sqlite3.connect(db)
            self.assertEqual(0, conn.execute('SELECT active FROM job_sources').fetchone()[0])
            self.assertEqual('closed', conn.execute('SELECT status FROM jobs').fetchone()[0])
            conn.close()

            db2 = Path(temp) / 'error.db'
            ensure_faculty_jobs_tables(db2)
            update_faculty_jobs(db2, source_names=['ais'], adapters=[FakeAdapter([[job]])])
            update_faculty_jobs(db2, source_names=['ais'], adapters=[FakeAdapter(error=True)])
            conn = sqlite3.connect(db2)
            self.assertEqual(0, conn.execute('SELECT consecutive_missing_runs FROM job_sources').fetchone()[0])
            self.assertEqual('likely_open', conn.execute('SELECT status FROM jobs').fetchone()[0])
            conn.close()


if __name__ == '__main__':
    unittest.main()
