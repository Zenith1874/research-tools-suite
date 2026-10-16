# -*- coding: utf-8 -*-
import unittest

from services.faculty_jobs_normalizer import (
    classify_business_scope,
    canonical_key,
    classify_disciplines,
    normalize_source_job,
    normalize_url,
    parse_deadline,
    parse_location,
    parse_salary,
    classify_faculty_market_role,
    hiring_cycle,
    hiring_cycle_reason,
    country_code_for,
    is_mergeable_official_url,
    parse_date,
)
from services.faculty_jobs_rank_mapper import EARLY, MID, SENIOR, map_rank
from services.faculty_jobs_sources.base import SourceJob


class FacultyJobNormalizerTests(unittest.TestCase):
    def test_url_tracking_parameters_are_removed(self):
        self.assertEqual(
            'https://example.edu/jobs/1?x=2',
            normalize_url('HTTPS://EXAMPLE.EDU/jobs/1/?utm_source=board&x=2'),
        )

    def test_location_uses_explicit_country_fallback_without_inventing_city(self):
        location = parse_location('Remote', 'GB')
        self.assertEqual('GB', location['country_code'])
        self.assertEqual('United Kingdom', location['country'])
        self.assertEqual('Europe', location['region_group'])

    def test_board_default_is_not_posting_country_or_region_evidence(self):
        source_job = SourceJob(
            source='ais', source_job_id='85721994',
            source_url='https://academiccareers.aisnet.org/job/85721994',
            title_raw='Management of Information Systems Professor (open rank) at NovaSBE',
            institution_raw='Unknown institution',
        )
        location = normalize_source_job(source_job, 'United States')
        self.assertIsNone(location['country_code'])
        self.assertIsNone(location['country'])
        self.assertEqual('Other', location['region_group'])
        self.assertEqual('source_region_only_unknown_country', location['location_evidence'])

    def test_unambiguous_city_hint_overrides_broad_source_fallback(self):
        location = parse_location('Dublin', 'GB')
        self.assertEqual('IE', location['country_code'])
        self.assertEqual('Ireland', location['country'])
        self.assertEqual('Europe', location['region_group'])

    def test_salary_deadline_and_track_preserve_unknowns(self):
        salary = parse_salary('USD 85k–95k per year')
        self.assertEqual('USD', salary['currency'])
        self.assertEqual(85000.0, salary['min'])
        self.assertEqual(95000.0, salary['max'])
        self.assertEqual('annual', salary['period'])
        self.assertEqual({'date': None, 'mode': 'rolling'}, parse_deadline('', 'reviewed on a rolling basis'))

    def test_posting_and_date_placed_are_not_deadlines(self):
        self.assertEqual({'date': None, 'mode': 'unknown'}, parse_deadline('', 'Posting date 2026-08-21'))
        self.assertEqual({'date': None, 'mode': 'unknown'}, parse_deadline('Date Placed: 18 Aug', ''))

    def test_closing_keyword_and_yearless_reference_date(self):
        self.assertEqual('2026-09-14', parse_deadline('Closes 14 Sep', reference_date='2026-08-23')['date'])
        self.assertEqual('2026-09-30', parse_deadline('', 'Application deadline: 30 September 2026')['date'])
        self.assertEqual(
            '2026-09-15',
            parse_deadline('', 'Application Deadline: 09/15/2026 Open Until Filled: No')['date'],
        )

    def test_relative_posted_date_is_parsed_without_recursive_fallback(self):
        self.assertEqual('2026-08-17', parse_date('6 days ago', reference_date='2026-08-23'))
        self.assertEqual('2026-08-09', parse_date('2 weeks ago', reference_date='2026-08-23'))
        self.assertEqual('2026-07-30', parse_date('2026-07-30T04:00:00.000Z'))

    def test_open_until_filled_and_rolling_remain_modes(self):
        self.assertEqual('open_until_filled', parse_deadline('', 'Open until filled')['mode'])
        self.assertEqual('unknown', parse_deadline('', 'Open Until Filled: No')['mode'])
        self.assertEqual('open_until_filled', parse_deadline('2036-09-20T03:59:00.000Z', 'Applications accepted until the position is filled')['mode'])
        self.assertEqual('rolling', parse_deadline('', 'Applications reviewed on a rolling basis')['mode'])

    def test_mode_evidence_is_keyword_bounded(self):
        result = parse_deadline(
            '',
            'Long description before. Applications reviewed on a rolling basis. ' + ('More text. ' * 100),
            return_details=True,
        )
        self.assertEqual('rolling', result['mode'])
        self.assertLessEqual(len(result['evidence']), 300)
        self.assertIn('rolling', result['evidence'].casefold())

    def test_country_aliases_and_labels_are_centralized(self):
        for value, expected in [('Auckland, New Zealand', 'NZ'), ('Dhaka, Bangladesh', 'BD'),
                                ('Dublin, Ireland', 'IE'), ('KAUST, Saudi Arabia', 'SA'),
                                ('Stanford, CA, US', 'US'), ('Ontario, Canada', 'CA'),
                                ('Ankara, Türkiye', 'TR'), ('Taipei City, Taiwan', 'TW'),
                                ('New Delhi, India', 'IN')]:
            self.assertEqual(expected, parse_location(value, 'Europe', institution_text=value)['country_code'])
        self.assertEqual('GB', country_code_for('United Kingdom'))
        self.assertIsNone(country_code_for('Outside North America'))

    def test_canadian_province_beats_ambiguous_california_code(self):
        location = parse_location(
            'Toronto, Ontario, CA', 'Global', institution_text='University of Toronto',
        )
        self.assertEqual('CA', location['country_code'])
        self.assertEqual('Canada', location['country'])
        self.assertEqual('ON', location['state_province'])
        self.assertEqual('Toronto', location['city'])

    def test_washington_dc_is_not_normalized_as_washington_state(self):
        location = parse_location('Washington D.C., US', 'Global')
        self.assertEqual('US', location['country_code'])
        self.assertEqual('DC', location['state_province'])
        self.assertEqual('Washington D.C.', location['city'])

    def test_iso_only_location_is_country_evidence_not_a_city(self):
        china = parse_location('CN')
        self.assertEqual('CN', china['country_code'])
        self.assertEqual('China', china['country'])
        self.assertIsNone(china['city'])
        uae = parse_location('AE')
        self.assertEqual('AE', uae['country_code'])
        self.assertEqual('United Arab Emirates', uae['country'])
        self.assertIsNone(uae['city'])

    def test_french_institution_text_does_not_become_germany_and_kaust_hint_is_saudi(self):
        quebec = parse_location('Location Quebec', 'Canada', institution_text='Université de Montréal')
        self.assertEqual('CA', quebec['country_code'])
        self.assertEqual('QC', quebec['state_province'])
        kaust = parse_location('Outside North America', 'Canada', institution_text='King Abdullah University of Science and Technology (KAUST)')
        self.assertEqual('SA', kaust['country_code'])
        self.assertIsNone(kaust['city'])
        self.assertIsNone(parse_location(
            'Augusta', 'Global', institution_text='Augusta University Job ID 278518',
        )['country_code'])

    def test_euraxess_work_location_labels_are_cleaned(self):
        location = parse_location(
            'Work Locations: Number of offers: 1, France, UNIVERSITE DE PAU, PAU CEDEX',
            'Europe', institution_text='UNIVERSITE DE PAU',
        )
        self.assertEqual('FR', location['country_code'])
        self.assertEqual('PAU CEDEX', location['city'])
        self.assertNotIn('Work Locations', location['location_raw'])

    def test_location_parenthetical_work_mode_is_not_city_text(self):
        location = parse_location('Hong Kong (on-site)', 'United States')
        self.assertEqual('HK', location['country_code'])
        self.assertEqual('Hong Kong', location['city'])

    def test_city_state_prefix_beats_broader_country_suffix(self):
        location = parse_location('Macau, China', 'Global')
        self.assertEqual('MO', location['country_code'])
        self.assertEqual('Macau SAR', location['country'])
        self.assertEqual('Macau', location['city'])

    def test_country_work_mode_suffix_is_not_a_city(self):
        california = parse_location('California, United States (remote)')
        self.assertEqual('US', california['country_code'])
        self.assertEqual('CA', california['state_province'])
        self.assertIsNone(california['city'])

        washington = parse_location('Washington, Dist. Columbia, United States (on-site)')
        self.assertEqual('US', washington['country_code'])
        self.assertEqual('DC', washington['state_province'])
        self.assertEqual('Washington', washington['city'])

    def test_city_and_state_may_share_the_same_name(self):
        location = parse_location('New York, New York, United States (on-site)')
        self.assertEqual('US', location['country_code'])
        self.assertEqual('NY', location['state_province'])
        self.assertEqual('New York', location['city'])

    def test_flattened_multiple_locations_do_not_choose_one_state(self):
        location = parse_location(
            'Multiple Locations New York, New York, United States '
            'Washington, Dist. Columbia, United States (hybrid)'
        )
        self.assertEqual('US', location['country_code'])
        self.assertIsNone(location['state_province'])
        self.assertEqual('Multiple Locations', location['city'])
        self.assertEqual('location_raw_multiple', location['location_evidence'])

    def test_multiple_locations_retain_one_shared_state(self):
        california = parse_location(
            'Multiple Locations Alameda County, California, United States '
            'Sacramento, California, United States (hybrid)'
        )
        self.assertEqual('CA', california['state_province'])
        self.assertEqual('Multiple Locations', california['city'])

        missouri = parse_location('Multiple Locations, MO')
        self.assertEqual('MO', missouri['state_province'])
        self.assertEqual('Multiple Locations', missouri['city'])

    def test_country_slash_city_is_structured_without_losing_raw_evidence(self):
        paris = parse_location('France / Paris', 'Global')
        self.assertEqual('FR', paris['country_code'])
        self.assertEqual('Paris', paris['city'])
        self.assertEqual('France / Paris', paris['location_raw'])
        self.assertEqual('location_raw_country_slash', paris['location_evidence'])

        hanoi = parse_location('Viet Nam / Hanoi', 'Global')
        self.assertEqual('VN', hanoi['country_code'])
        self.assertEqual('Vietnam', hanoi['country'])
        self.assertEqual('Hanoi', hanoi['city'])

        multi = parse_location('France / Lyon / Paris', 'Global')
        self.assertEqual('Lyon', multi['city'])
        self.assertEqual('France / Lyon / Paris', multi['location_raw'])

    def test_non_country_slashes_are_not_rewritten_as_country_city(self):
        location = parse_location('College of Medicine/Office of Health Sciences', 'US')
        self.assertEqual('College of Medicine/Office of Health Sciences', location['city'])

    def test_organizational_and_campus_prefixes_do_not_become_the_city(self):
        location = parse_location(
            'College of Business, Main Campus, Portales, NM', 'United States',
        )
        self.assertEqual('US', location['country_code'])
        self.assertEqual('NM', location['state_province'])
        self.assertEqual('Portales', location['city'])

        campus = parse_location('Gresham Campus, OR', 'United States')
        self.assertEqual('OR', campus['state_province'])
        self.assertEqual('Gresham', campus['city'])

        prefixed = parse_location('Main Campus - Portales, NM', 'United States')
        self.assertEqual('Portales', prefixed['city'])

    def test_rank_cycle_and_generic_portal_contracts(self):
        normalized = normalize_source_job(SourceJob(
            source='test', source_job_id='rank', source_url='https://board.example/rank',
            title_raw='Lecturer / Senior Lecturer in Business', institution_raw='Example University',
            location_raw='Oxford', description_excerpt='Date Placed: 18 Aug Closes 14 Sep',
            posted_date_raw='Date Placed: 18 Aug', deadline_raw='Closes 14 Sep',
            captured_at='2026-08-23T00:00:00Z',
        ), 'Europe')
        self.assertEqual('GB', normalized['country_code'])
        self.assertEqual('2026-09-14', normalized['deadline_date'])
        self.assertEqual('2026-08-18', normalized['posted_date'])
        self.assertEqual('2026-27', hiring_cycle('2026-08-23T00:00:00Z', 2027))
        self.assertIn('explicit start year', hiring_cycle_reason('2026-08-23T00:00:00Z', 2027))
        self.assertFalse(is_mergeable_official_url('https://www.galaxie.enseignementsup-recherche.gouv.fr/ensup/candidats.html'))

    def test_generic_portal_is_not_exposed_as_official_application_url(self):
        normalized = normalize_source_job(SourceJob(
            source='euraxess', source_job_id='portal', source_url='https://euraxess.example/jobs/portal',
            official_url='https://www.galaxie.enseignementsup-recherche.gouv.fr/ensup/candidats.html',
            title_raw='ATER-Informatique', institution_raw='Example University', location_raw='Pau, France',
            description_excerpt='Application deadline: 30 September 2026', captured_at='2026-08-23T00:00:00Z',
        ), 'Europe')
        self.assertIsNone(normalized['official_url'])

    def test_local_rank_mapping_keeps_uk_irish_and_german_terms(self):
        uk = map_rank('GB', 'Lecturer in Finance')
        ireland = map_rank('IE', 'Lecturer in Management')
        self.assertEqual('Lecturer', uk.rank_normalized)
        self.assertEqual('Lecturer', ireland.rank_normalized)
        self.assertEqual(EARLY, uk.career_stage)
        self.assertEqual(EARLY, ireland.career_stage)

        w1 = map_rank('DE', 'W1 Juniorprofessor of Accounting')
        w2 = map_rank('DE', 'W2 Professor of Finance')
        w3 = map_rank('DE', 'W3 Professor of Management')
        self.assertEqual('W1 / Juniorprofessor', w1.rank_normalized)
        self.assertEqual('W2', w2.rank_normalized)
        self.assertEqual('W3', w3.rank_normalized)
        self.assertEqual(EARLY, w1.career_stage)
        self.assertEqual(MID, w2.career_stage)
        self.assertEqual(SENIOR, w3.career_stage)

    def test_multi_rank_precedence_is_independent_of_title_word_order(self):
        for title in (
            'Assistant / Associate Professor in Finance',
            'Associate or Full Professor of Management',
            'Assistant, Associate or Full Professor of Accounting',
            'Assistant Professor / Associate Professor / Professor',
        ):
            self.assertEqual('Open Rank', map_rank('US', title).rank_normalized, title)

    def test_lecturer_is_not_rewritten_as_assistant_professor_outside_uk(self):
        self.assertEqual('Lecturer', map_rank('US', 'Lecturer in Marketing').rank_normalized)
        self.assertEqual('Lecturer / Senior Lecturer', map_rank(
            'AU', 'Lecturer / Senior Lecturer in Information Systems').rank_normalized)

    def test_discipline_between_assistant_and_professor_keeps_assistant_rank(self):
        self.assertEqual('Assistant Professor', map_rank(
            'US', 'Assistant Accounting Professor').rank_normalized)

    def test_department_evidence_outranks_description_evidence(self):
        classification = classify_disciplines('Information Systems', 'Assistant Professor', 'Marketing and strategy')
        self.assertEqual('Information Systems / MIS', classification['primary'])
        self.assertIn('Marketing', classification['secondary'])

    def test_business_scope_separates_school_discipline_nonbusiness_and_nonacademic(self):
        self.assertEqual(
            'business_school',
            classify_business_scope(title='Assistant Professor of Management', school='School of Business')['scope'],
        )
        self.assertEqual(
            'business_discipline',
            classify_business_scope(title='Assistant Professor of Management')['scope'],
        )
        self.assertEqual(
            'business_discipline',
            classify_business_scope(
                title='Assistant Professor',
                department='Department of Management',
            )['scope'],
        )
        self.assertEqual(
            'non_business',
            classify_business_scope(title='Assistant Professor of Emergency Medicine')['scope'],
        )
        self.assertEqual(
            'non_academic',
            classify_business_scope(title='Product Manager, Money')['scope'],
        )
        self.assertEqual(
            'non_academic',
            classify_business_scope(title='Administrative Vice President (Legal & Finance)')['scope'],
        )
        self.assertEqual(
            'non_academic',
            classify_business_scope(title='Sr. Financial Analyst, Wharton Finance & Administration')['scope'],
        )

    def test_faculty_market_gate_excludes_student_staff_and_collection_pages(self):
        for title, role in (
            ('Graduate Assistant, Master of Accountancy- Mike Cottrell College of Business', 'student_role'),
            ('Federal Work Study - Behavioral Laboratory', 'student_role'),
            ('Executive Assistant - Faculty of SABEL', 'staff_role'),
            ('Postmaster Research Associate - Transportation', 'staff_role'),
            ('Faculty Job Openings', 'listing_page'),
            ('Faculty (Full-Time)', 'listing_page'),
            ('Faculty Positions in Various Departments', 'listing_page'),
            ("Dean's Message", 'listing_page'),
        ):
            result = classify_faculty_market_role(title)
            self.assertEqual(0, result['eligible'], title)
            self.assertEqual(role, result['role'], title)

        # A named field makes it one advertisement rather than a directory of
        # them, so the role gate accepts it. Whether it belongs in *this*
        # market is a separate question with a separate gate: engineering and
        # nursing are kept out by business scope, which is where that judgement
        # belongs. Deciding it in the role gate also discarded
        # "Faculty Positions in Finance", which is a real posting.
        for title, scope in (
            ('Faculty Positions in Biological and Chemical Engineering', 'non_business'),
            ('Faculty Positions in Nursing', 'non_business'),
            ('Faculty Positions in Finance', 'business_discipline'),
        ):
            result = classify_faculty_market_role(title)
            self.assertEqual('faculty', result['role'], title)
            self.assertEqual(1, result['eligible'], title)
            self.assertEqual(
                scope,
                classify_business_scope(title=title, department=None, description=None)['scope'],
                title)

        professor = classify_faculty_market_role('Research Assistant Professor of Finance')
        self.assertEqual(1, professor['eligible'])
        self.assertEqual('faculty', professor['role'])
        postdoc = classify_faculty_market_role('Post-Doc Research Associate in Management')
        self.assertEqual(1, postdoc['eligible'])
        self.assertEqual('postdoc', postdoc['role'])

        collection = classify_faculty_market_role(
            "Tenure-track and visiting faculty positions in Bucknell's three colleges: "
            "Arts & Sciences, Engineering and the Freeman College of Management FACULTY OPPORTUNITIES",
            official_url='https://bucknell.wd1.myworkdayjobs.com/External?jobFamilyGroup=faculty',
        )
        self.assertEqual(0, collection['eligible'])
        self.assertEqual('listing_page', collection['role'])

    def test_nonbusiness_field_outranks_business_school_association(self):
        for title in (
            'Cosmetology: Contract Instructor-College Credit',
            'Chairperson, School of Computer Science',
            'Canada Impact+ Emerging Leader in Radiopharmaceutical Sciences & Development',
            'Clinical Instructor of Dental Hygiene',
        ):
            result = classify_business_scope(
                title=title,
                school='School of Business',
                description='Position is associated with the School of Business.',
            )
            # The radiopharmaceutical title has no conventional faculty-role
            # signal and is therefore conservatively unknown; every other
            # explicit academic non-business title is non_business.
            self.assertNotIn(result['scope'], {'business_school', 'business_discipline'}, title)

        self.assertEqual(
            'non_business',
            classify_business_scope(
                title='Adjunct Faculty - School of Social and Behavioral Sciences, Economics',
                institution='Example University',
            )['scope'],
        )
        for title, department in (
            ('Adjunct Faculty, Geographic Information Systems (GIS)', None),
            ('Assistant Professor in Manufacturing Engineering Technology', None),
            ('Post-Doctoral Associate in the Division of Social Science', None),
            ('Assistant Professor', 'AG-FOOD - RESOURCES ECONOMICS'),
            ('Professor of Sport Management', 'Dept of Health & Human'),
            ('Pain Management Specialist - Assistant Professor', None),
            ('Assistant Professor Culinary, Bakery & Pastry, Tenure Track', 'Secchia Institute of Culinary'),
            ('Associate or Full Professor - Literature and Languages', None),
            ('Distinguished Chair in Materials Science', None),
            ('Assistant/Associate Contracts & Business Law Professor, School of Law', None),
            ('Property and Real Estate Law Professor, Winston College of Law', None),
        ):
            self.assertEqual(
                'non_business',
                classify_business_scope(title=title, department=department)['scope'],
                title,
            )

        self.assertEqual(
            'non_business',
            classify_business_scope(title='Assistant Professor Construction Management')['scope'],
        )
        self.assertEqual(
            'business_school',
            classify_business_scope(
                title='Assistant Professor Construction Management',
                school='College of Business',
            )['scope'],
        )
        self.assertEqual(
            'unknown',
            classify_business_scope(title='Assistant Professor of Economics')['scope'],
        )
        self.assertEqual(
            'non_business',
            classify_business_scope(
                title='Associate Professor Tenure Track',
                description='Department of Epidemiology at the Geisel School of Medicine invites applications.',
            )['scope'],
        )
        self.assertEqual(
            'business_discipline',
            classify_business_scope(title='Assistant Professor of Legal Studies')['scope'],
        )
        self.assertEqual(
            'business_discipline',
            classify_business_scope(title='Assistant Professor of Real Estate and Risk Management')['scope'],
        )
        self.assertEqual(
            'non_business',
            classify_business_scope(
                title='Tenure Track Assistant Professor of Aviation Science Management',
            )['scope'],
        )

    def test_aacsb_roster_school_is_not_posting_level_scope_evidence(self):
        normalized = normalize_source_job(SourceJob(
            source='aacsb_official', source_job_id='roster-only',
            source_url='https://university.example/jobs/1',
            title_raw='Assistant Professor', institution_raw='Example University',
            school_raw='Example School of Business',
            description_excerpt='Tenure-track faculty appointment.',
            captured_at='2026-08-24T00:00:00Z',
            extra={'school_evidence_context': 'aacsb_roster_target'},
        ), 'Global')
        self.assertEqual(1, normalized['faculty_market_eligible'])
        self.assertEqual('unknown', normalized['business_scope'])
        self.assertEqual('aacsb_roster_target', normalized['school_evidence_context'])

    def test_normalized_record_retains_mapping_and_evidence_fields(self):
        job = SourceJob(
            source='test', source_job_id='1', source_url='https://board.example/job/1',
            title_raw='Lecturer in Business Analytics', institution_raw='Example University',
            location_raw='London, UK', description_excerpt='Fixed-term appointment. PhD preferred. £55,000 per annum.',
            deadline_raw='30 September 2026', official_url='https://example.edu/apply/1',
            extra={'country_code': 'GB'}, captured_at='2026-08-23T00:00:00Z',
        )
        normalized = normalize_source_job(job, 'Europe')
        self.assertEqual('GB', normalized['country_code'])
        self.assertEqual('Business Analytics / AI', normalized['discipline_primary'])
        self.assertEqual('fixed_term', normalized['track_type'])
        self.assertEqual('unknown', normalized['visa_status'])
        self.assertEqual('https://example.edu/apply/1', normalized['official_url'])
        self.assertTrue(normalized['canonical_key'].startswith('url:'))
        self.assertEqual(normalized['canonical_key'], canonical_key(normalized['official_url'], normalized['fingerprint']))


if __name__ == '__main__':
    unittest.main()
