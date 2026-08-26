# -*- coding: utf-8 -*-
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from services.faculty_jobs_sources.ais import AISAdapter
from services.faculty_jobs_sources.euraxess import EuraxessAdapter
from services.faculty_jobs_sources.insidehighered import InsideHigherEdAdapter
from services.faculty_jobs_sources.jobs_ac_uk import JobsAcUkAdapter
from services.faculty_jobs_sources.university_affairs import UniversityAffairsAdapter
from services.faculty_jobs_sources import SourceJob


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'faculty_jobs'


class FacultyJobSourceFixtureTests(unittest.TestCase):
    def _read(self, name):
        return (FIXTURES / name).read_text(encoding='utf-8')

    def test_ais_fixture(self):
        jobs = AISAdapter.parse_fixture(self._read('ais.html')) if hasattr(AISAdapter, 'parse_fixture') else []
        # The production helper is module-level on the adapter module; use the
        # live class path as a smoke contract when the convenience method is absent.
        if not jobs:
            from services.faculty_jobs_sources.ais import parse_fixture
            jobs = parse_fixture(self._read('ais.html'))
        self.assertEqual('12345', jobs[0].source_job_id)
        self.assertEqual('Assistant Professor of Management', jobs[0].title_raw)
        self.assertEqual('Example State University', jobs[0].institution_raw)
        self.assertEqual('Las Cruces, NM', jobs[0].location_raw)
        self.assertEqual('Posted today', jobs[0].posted_date_raw)
        self.assertTrue(jobs[0].source_url.endswith('/12345'))

    def test_other_source_fixtures(self):
        from services.faculty_jobs_sources.euraxess import parse_fixture as euraxess
        from services.faculty_jobs_sources.insidehighered import parse_fixture as ihe
        from services.faculty_jobs_sources.jobs_ac_uk import parse_fixture as jobsuk
        from services.faculty_jobs_sources.university_affairs import parse_fixture as ua
        cases = [
            (ua, 'university_affairs.html', '54321'),
            (jobsuk, 'jobs_ac_uk.html', 'uk-1001'),
            (euraxess, 'euraxess.html', '777001'),
            (ihe, 'inside_higher_ed.html', '90001'),
        ]
        for parser, filename, source_id in cases:
            with self.subTest(filename=filename):
                jobs = parser(self._read(filename))
                self.assertEqual(source_id, jobs[0].source_job_id)
                self.assertTrue(jobs[0].title_raw)

    def test_production_adapter_fixture_fields_are_not_only_ids(self):
        from services.faculty_jobs_sources.euraxess import parse_fixture as euraxess
        from services.faculty_jobs_sources.insidehighered import parse_fixture as ihe
        from services.faculty_jobs_sources.jobs_ac_uk import parse_fixture as jobsuk
        from services.faculty_jobs_sources.university_affairs import parse_fixture as ua
        eu = euraxess(self._read('euraxess.html'))[0]
        self.assertIn('Digital Work', eu.title_raw)
        self.assertEqual('Example European Institute', eu.institution_raw)
        self.assertEqual('Amsterdam, Netherlands', eu.location_raw)
        self.assertEqual('15 October 2026', eu.deadline_raw)
        ihe_job = ihe(self._read('inside_higher_ed.html'))[0]
        self.assertEqual('Example University', ihe_job.institution_raw)
        self.assertEqual('Boston, MA', ihe_job.location_raw)
        uk = jobsuk(self._read('jobs_ac_uk.html'))[0]
        self.assertEqual('Example London University', uk.institution_raw)
        self.assertEqual('London, UK', uk.location_raw)
        self.assertIn('Closing 30 September 2026', uk.deadline_raw)
        self.assertIn('£55,000', uk.salary_raw)
        canada = ua(self._read('university_affairs.html'))[0]
        self.assertEqual('Example University', canada.institution_raw)
        self.assertEqual('Toronto, Ontario', canada.location_raw)
        self.assertEqual('Closing September 30, 2026', canada.deadline_raw)

    def test_jobs_ac_uk_preserves_explicit_ucd_business_label(self):
        from services.faculty_jobs_sources.jobs_ac_uk import parse_fixture
        jobs = parse_fixture("""
          <div class="j-search-result__result" data-advert-id="ucd-1">
            <a href="/job/ucd-1">Lecturer/Assistant Prof in Marketing, UCD Business</a>
            <div class="j-search-result__employer">University College Dublin</div>
            <div class="j-search-result__location">Dublin</div>
          </div>
        """)
        self.assertEqual("UCD Business", jobs[0].school_raw)

    def test_euraxess_drops_street_address_from_city(self):
        from services.faculty_jobs_sources.euraxess import EuraxessAdapter
        location, host = EuraxessAdapter._work_location('Mekelweg 5, Netherlands')
        self.assertEqual('Netherlands', location)
        self.assertIsNone(host)

    def test_inside_higher_ed_uses_structured_organization_and_location(self):
        from services.faculty_jobs_sources.insidehighered import parse_fixture
        html = '''
        <script type="application/ld+json">
        {"@type":"JobPosting","hiringOrganization":{"name":"University of South Carolina"},
         "jobLocation":{"address":{"addressLocality":"Columbia","addressRegion":"SC","addressCountry":"US"}},
         "datePosted":"2026-08-20","validThrough":"2026-09-30"}
        </script>
        <li class="lister__item">
          <a href="/job/90002/assistant-professor-management">Assistant Professor of Management</a>
          <div class="lister__meta-item--location">Columbia, SC</div>
        </li>
        '''
        jobs = parse_fixture(html)
        self.assertEqual(1, len(jobs))
        self.assertEqual('University of South Carolina', jobs[0].institution_raw)
        self.assertEqual('Columbia, SC, US', jobs[0].location_raw)
        self.assertEqual('2026-08-20', jobs[0].posted_date_raw)
        # Listing-level validThrough is a board expiry, not application
        # deadline evidence; detail text must provide the closing date.
        self.assertIsNone(jobs[0].deadline_raw)

    def test_inside_higher_ed_rejects_business_department_as_location(self):
        from services.faculty_jobs_sources.insidehighered import parse_fixture
        html = '''
        <li class="lister__item">
          <a href="/job/90003/assistant-professor-practice">Assistant Professor of Practice in Management</a>
          <div class="lister__meta-item--company">Sam Houston State University</div>
          <div class="lister__meta-item--location">College of Business Administration</div>
        </li>
        '''
        jobs = parse_fixture(html)
        self.assertEqual('Sam Houston State University', jobs[0].institution_raw)
        self.assertIsNone(jobs[0].location_raw)

    def test_inside_higher_ed_listing_excerpt_recovers_employer_after_location(self):
        self.assertEqual(
            'The Ohio State University',
            InsideHigherEdAdapter._institution_from_text(
                'Assistant Professor of Organizational Behavior Columbus Campus '
                'The Ohio State University Screen reader users',
                'Assistant Professor of Organizational Behavior',
            ),
        )
        self.assertEqual(
            'Lebanese American University',
            InsideHigherEdAdapter._institution_from_text(
                'Tenure track Assistant Professor position in Management Lebanon (LB) '
                'Lebanese American University Disciplines: Management',
                'Tenure track Assistant Professor position in Management',
            ),
        )
        self.assertEqual(
            'University of Tennessee',
            InsideHigherEdAdapter._institution_from_text(
                'Assistant Professor of Operations Management, Fall 2027 '
                'The University of Tennessee, Knoxville, Haslam College of Business '
                'Location: The University of Tennessee, Knoxville, Haslam College of Business',
                'Assistant Professor of Operations Management, Fall 2027',
            ),
        )
        self.assertEqual(
            'The Ohio State University',
            InsideHigherEdAdapter._clean_institution_value(
                'Ambulatory The Ohio State University', 'Outpatient Care/Ambulatory',
            ),
        )
        self.assertEqual(
            'Atlanta Metropolitan State College',
            InsideHigherEdAdapter._clean_institution_value(
                'Atl Metropolitan State College Atlanta Metropolitan State College',
                'Atl Metropolitan State College',
            ),
        )

    def test_inside_higher_ed_detail_jsonld_extracts_employer_and_fields(self):
        detail = '''
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"Assistant Professor of Organizational Behavior",
         "hiringOrganization":{"name":"The Ohio State University"},
         "jobLocation":{"address":{"addressLocality":"Columbus","addressRegion":"Ohio","addressCountry":"US"}},
         "datePosted":"2026-07-30T04:00:00.000Z","validThrough":"2026-09-28T04:00:00.000Z",
         "description":"Job Title:Assistant Professor of Organizational Behavior Department:Fisher College | Management and Human Resources-Interim Application deadline: September 28, 2026. The Department of Management and Human Resources at The Ohio State University’s Fisher College of Business invites applications. The position requires a Ph.D. and has a base salary between $185,000 - $200,000."}
        </script>
        '''
        adapter = InsideHigherEdAdapter(max_pages=1)
        adapter.detail_delay = 0
        job = SourceJob(
            source='inside_higher_ed', source_job_id='3534806',
            source_url='https://careers.insidehighered.com/job/3534806/example/',
            title_raw='Assistant Professor of Organizational Behavior',
            institution_raw='Unknown institution', location_raw='Columbus Campus',
            description_excerpt='Assistant Professor of Organizational Behavior Columbus Campus',
        )
        with patch.object(adapter, 'request', return_value=SimpleNamespace(text=detail)):
            enriched = adapter._enrich_detail(job)
        self.assertEqual('The Ohio State University', enriched.institution_raw)
        self.assertEqual('Columbus, Ohio, US', enriched.location_raw)
        self.assertEqual('2026-07-30T04:00:00.000Z', enriched.posted_date_raw)
        self.assertIn('September 28, 2026', enriched.deadline_raw)
        self.assertEqual('Fisher College | Management and Human Resources-Interim', enriched.department_raw)
        self.assertEqual('Fisher College of Business', enriched.school_raw)
        self.assertIn('$185,000', enriched.salary_raw)
        self.assertIn('Ph.D.', enriched.description_excerpt)

    def test_inside_higher_ed_lau_detail_preserves_employer_school_and_rolling_deadline(self):
        detail = '''
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"Tenure track Assistant Professor position in Management",
         "hiringOrganization":{"name":"Lebanese American University"},
         "jobLocation":{"address":{"addressLocality":"Beirut and Byblos","addressCountry":"LB"}},
         "datePosted":"2024-09-19",
         "description":"School of Business. Applications will be accepted until the position is filled. The Lebanese American University operates in Lebanon."}
        </script>
        '''
        adapter = InsideHigherEdAdapter(max_pages=1)
        adapter.detail_delay = 0
        job = SourceJob(
            source='inside_higher_ed', source_job_id='3226393',
            source_url='https://careers.insidehighered.com/job/3226393/example/',
            title_raw='Tenure track Assistant Professor position in Management',
            institution_raw='Unknown institution', location_raw='Lebanon (LB)',
            description_excerpt='Tenure track Assistant Professor position in Management',
        )
        with patch.object(adapter, 'request', return_value=SimpleNamespace(text=detail)):
            enriched = adapter._enrich_detail(job)
        self.assertEqual('Lebanese American University', enriched.institution_raw)
        self.assertEqual('Beirut and Byblos, LB', enriched.location_raw)
        self.assertEqual('School of Business', enriched.school_raw)
        self.assertIn('position is filled', enriched.deadline_raw)

    def test_inside_higher_ed_valid_through_is_not_application_deadline(self):
        detail = '''
        <script type="application/ld+json">
        {"@type":"JobPosting","title":"Assistant Professor of Biology",
         "hiringOrganization":{"name":"Example University"},
         "jobLocation":{"address":{"addressLocality":"Augusta","addressRegion":"GA","addressCountry":"US"}},
         "datePosted":"2026-08-17T04:00:00.000Z","validThrough":"2038-08-18T03:59:59.000Z",
         "description":"Job ID: 278518 Location: Augusta University Full Time. Applications are encouraged."}
        </script>
        '''
        adapter = InsideHigherEdAdapter(max_pages=1)
        adapter.detail_delay = 0
        job = SourceJob(
            source='inside_higher_ed', source_job_id='valid-through',
            source_url='https://careers.insidehighered.com/job/valid-through/example/',
            title_raw='Assistant Professor of Biology', institution_raw='Example University',
            location_raw='Augusta, GA', description_excerpt='Assistant Professor of Biology',
        )
        with patch.object(adapter, 'request', return_value=SimpleNamespace(text=detail)):
            enriched = adapter._enrich_detail(job)
        self.assertIsNone(enriched.deadline_raw)

    def test_inside_higher_ed_detail_prefers_faculty_division_over_cross_appointment(self):
        description = (
            'Assistant Professor - Accounting Faculty/Division: University of Toronto Scarborough (UTSC) '
            'Department: UTSC:Dept-Management Campus: University of Toronto Scarborough (UTSC) '
            'The successful candidate will be cross-appointed to the Rotman School of Management.'
        )
        self.assertIsNone(InsideHigherEdAdapter._detail_school(description))
        self.assertEqual(
            'Darden School of Business',
            InsideHigherEdAdapter._detail_school(
                'Description The Darden School of Business at the University of Virginia invites applications.'
            ),
        )

    def test_inside_higher_ed_does_not_promote_later_business_collaborator(self):
        description = (
            'Canada Impact+ Emerging Leader in Radiopharmaceutical Sciences & Development. '
            'The appointment is housed in the Department of Chemistry and Chemical Biology. '
            'The successful candidate may collaborate across the university on commercialization, '
            'including with colleagues at the DeGroote School of Business.'
        )
        self.assertIsNone(InsideHigherEdAdapter._detail_school(description))

    def test_inside_higher_ed_does_not_promote_medical_or_engineering_collaborator(self):
        for description in (
            'The Department of Epidemiology at the Geisel School of Medicine invites applications. '
            'Faculty collaborate with colleagues at the Tuck School of Business.',
            'The Thayer School of Engineering invites applications for chairs in Materials Science. '
            'The university also includes the Tuck School of Business.',
        ):
            self.assertIsNone(InsideHigherEdAdapter._detail_school(description))

    def test_inside_higher_ed_fetches_numbered_pages_and_dedupes_ids(self):
        def card(job_id, title, institution, location):
            return f'''<li class="lister__item">
              <a href="/job/{job_id}/posting">{title}</a>
              <div class="lister__meta-item--company">{institution}</div>
              <div class="lister__meta-item--location">{location}</div>
              <div class="lister__meta-item--salary">Salary not specified</div>
            </li>'''

        pages = {
            1: card("91001", "Assistant Professor of Finance", "Example University", "Austin, TX"),
            2: card("91002", "Assistant Professor of Marketing", "Example College", "Dublin, Ireland")
               + card("91003", "Assistant Professor of Management", "Example Institute", "Auckland, New Zealand"),
            3: card("91002", "Assistant Professor of Marketing", "Example College", "Dublin, Ireland")
               + card("91004", "Assistant Professor of Accounting", "Example State University", "Dhaka, Bangladesh")
               + card("91005", "Business Program Director", "Example Business College", "Singapore"),
        }
        adapter = InsideHigherEdAdapter(max_pages=3, max_items=10)
        adapter.page_delay = 0
        requested = []

        def fake_request(url):
            requested.append(url)
            page = int(re.search(r"/jobs/(\d+)/", url).group(1)) if "/jobs/" in url and "/jobs/?" not in url else 1
            return SimpleNamespace(text=pages[page], url=url, status_code=200, headers={})

        with patch.object(adapter, "request", side_effect=fake_request):
            response = adapter.fetch()
        self.assertEqual(3, response.pages_fetched)
        self.assertEqual(["91001", "91002", "91003", "91004", "91005"], [job.source_job_id for job in response.jobs])
        self.assertEqual(5, len(response.jobs))
        self.assertTrue(requested[0].endswith("/jobs/?keywords=assistant+professor+business"))
        self.assertTrue(requested[1].endswith("/jobs/2/?keywords=assistant+professor+business"))
        self.assertTrue(requested[2].endswith("/jobs/3/?keywords=assistant+professor+business"))
        self.assertEqual("Example College", response.jobs[1].institution_raw)
        self.assertEqual("Dublin, Ireland", response.jobs[1].location_raw)
        self.assertEqual("assistant professor business", response.jobs[-1].extra["search_query"])


if __name__ == '__main__':
    unittest.main()
