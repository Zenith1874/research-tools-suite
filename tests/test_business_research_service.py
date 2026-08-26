import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.business_research_service import (
    build_construct_detail,
    build_methods_payload,
    build_landscape_payload,
    build_library_payload,
    build_method_detail,
    build_paper_workspace,
    build_theory_detail,
    build_theories_payload,
    ensure_business_research_tables,
    delete_research_note,
    rebuild_link_index,
    save_research_note,
    _source_text_metadata,
    update_library_state,
)


class BusinessResearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.article_db = self.root / 'articles.db'
        self.state_db = self.root / 'state.db'
        conn = sqlite3.connect(self.article_db)
        conn.executescript('''
            CREATE TABLE astar_articles (
                id INTEGER PRIMARY KEY,
                doi TEXT, openalex_id TEXT, semantic_scholar_id TEXT,
                title TEXT, abstract TEXT, abstract_status TEXT,
                publication_date TEXT, publication_year INTEGER, publication_month TEXT,
                journal_title TEXT, journal_issn TEXT, journal_abdc_rating TEXT,
                journal_abdc_version TEXT, publisher TEXT, authors_json TEXT,
                author_count INTEGER, concepts_json TEXT, keywords_json TEXT,
                url TEXT, landing_page_url TEXT, open_access_status TEXT,
                cited_by_count INTEGER, source_name TEXT, source_type TEXT,
                source_url TEXT, data_status TEXT, is_duplicate INTEGER DEFAULT 0
            );
            CREATE TABLE astar_article_classifications (
                article_id INTEGER PRIMARY KEY, broad_area TEXT, research_topic TEXT,
                theory_tags_json TEXT, method_tags_json TEXT, data_type_tags_json TEXT,
                context_tags_json TEXT, sample_context TEXT, relevance_score REAL,
                is_related_to_my_research INTEGER, classification_method TEXT,
                classification_status TEXT, classification_notes TEXT
            );
            CREATE TABLE astar_article_sources (
                id INTEGER PRIMARY KEY, article_id INTEGER, source_name TEXT,
                source_type TEXT, source_url TEXT, raw_id TEXT, fetched_at TEXT,
                parser_notes TEXT
            );
        ''')
        rows = [
            (1, '10.1/example.1', 'W1', 'A study of autonomy and employee voice',
             'This study examines job demands, autonomy, engagement, and employee voice.',
             '2026-01-02', 2026, 'Journal of Management', 'A*',
             '[{"name":"Jane Smith"}]', 88, '["AI_in_organizations"]',
             '["jd_r"]', '["survey experiment"]', 72.0),
            (2, '10.1/example.2', 'W2', 'Algorithmic management and burnout',
             'Algorithmic monitoring is associated with workload and burnout in a panel sample.',
             '2025-06-02', 2025, 'Information Systems Journal', 'A',
             '[{"name":"John Doe"}]', 44, '["algorithmic_management","burnout"]',
             '["job_design","conservation_of_resources"]', '["panel_data"]', 64.0),
            (3, '10.1/example.3', 'W3', 'A methods paper on fixed effects',
             'We estimate a policy effect using panel data and fixed effects.',
             '2024-03-02', 2024, 'Management Science', 'A*',
             '[{"name":"Alex Lee"}]', 61, '["strategy_innovation"]',
             '[]', '["fixed-effects","causal_inference"]', 30.0),
        ]
        for row in rows:
            (article_id, doi, openalex, title, abstract, pub_date, year, journal, rank,
             authors, citations, topics, theories, methods, relevance) = row
            conn.execute('''INSERT INTO astar_articles
                (id, doi, openalex_id, title, abstract, abstract_status,
                 publication_date, publication_year, journal_title, journal_abdc_rating,
                 authors_json, cited_by_count, source_name, source_type, data_status,
                 is_duplicate)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)''',
                (article_id, doi, openalex, title, abstract, 'available', pub_date, year,
                 journal, rank, authors, citations, 'OpenAlex', 'api_metadata', 'cache'))
            conn.execute('''INSERT INTO astar_article_classifications
                (article_id, broad_area, research_topic, theory_tags_json,
                 method_tags_json, data_type_tags_json, context_tags_json,
                 relevance_score, is_related_to_my_research, classification_method,
                 classification_status, classification_notes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (article_id, 'OB / HR', topics, theories, methods, '[]', '[]',
                 relevance, int(relevance >= 60), 'rules', 'confident', 'test fixture'))
        conn.execute('''INSERT INTO astar_article_sources
            (article_id, source_name, source_type, source_url, raw_id, fetched_at, parser_notes)
            VALUES (?,?,?,?,?,?,?)''', (1, 'OpenAlex', 'api_metadata', 'https://openalex.org/W1', 'W1', '2026-01-03', 'test'))
        conn.commit()
        conn.close()
        ensure_business_research_tables(state_db_path=self.state_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_theory_and_method_catalogs_link_to_real_fixture_papers(self):
        theories = build_theories_payload({'q': 'Job Demands'}, self.article_db, self.state_db)
        self.assertTrue(theories['success'])
        self.assertEqual(len(theories['entities']), 1)
        self.assertGreaterEqual(theories['entities'][0]['paper_count'], 1)

        detail = build_theory_detail('job-demands-resources', self.article_db, self.state_db)
        self.assertEqual(detail['success'], True)
        self.assertTrue(any(p['id'] == '1' for p in detail['recent_applications']))

        method = build_method_detail('fixed-effects', self.article_db, self.state_db)
        self.assertEqual(method['success'], True)
        self.assertTrue(any(p['id'] == '3' for p in method['example_papers']))

    def test_a_broad_umbrella_tag_is_never_counted_as_the_entity(self):
        """`job_design` covers JD-R and the Job Characteristics Model alike.

        Counting it as either theory's own evidence made two distinct theories
        report identical paper sets, so umbrella hits are reported separately.
        """
        payload = build_theories_payload({}, self.article_db, self.state_db)
        entities = {item['id']: item for item in payload['entities']}

        jdr = entities['job-demands-resources']
        jcm = entities['job-characteristics-model']
        # Paper 1 carries `jd_r`; paper 2 carries the umbrella `job_design`.
        self.assertEqual(jdr['paper_count'], 1)
        self.assertEqual(jdr['broad_paper_count'], 1)
        self.assertEqual(jcm['paper_count'], 0)
        self.assertEqual(jcm['broad_paper_count'], 1)
        self.assertEqual(jcm['mapping_status'], 'broad_tag_only')
        self.assertNotEqual(jdr['paper_count'], jcm['paper_count'])

        detail = build_theory_detail('job-demands-resources', self.article_db, self.state_db)
        precise = {p['id'] for p in detail['recent_applications']}
        broad = {p['id'] for p in detail['broad_tag_applications']['papers']}
        self.assertEqual(precise, {'1'})
        self.assertEqual(broad, {'2'})

    def test_entity_without_any_classifier_tag_says_so(self):
        """TAM has no tag anywhere in the cache vocabulary; 0 needs an explanation."""
        payload = build_theories_payload({}, self.article_db, self.state_db)
        tam = {item['id']: item for item in payload['entities']}['technology-acceptance-model']
        self.assertEqual(tam['paper_count'], 0)
        self.assertEqual(tam['mapping_status'], 'no_classifier_tag_in_cache')
        self.assertIn('coverage limit of the classifier', tam['mapping_note'])

    def test_theory_conceptual_model_comes_from_the_theory(self):
        jdr = build_theory_detail('job-demands-resources', self.article_db, self.state_db)
        model = jdr['conceptual_model']
        self.assertEqual(model['kind'], 'pathways')
        labels = [step['name'] for pathway in model['pathways'] for step in pathway['steps']]
        self.assertIn('Burnout', labels)
        # Slugs must never reach the page as labels.
        self.assertNotIn('employee-engagement', labels)

        other = build_theory_detail('resource-based-view', self.article_db, self.state_db)
        self.assertNotEqual(other['conceptual_model'], model)

    def test_signaling_detail_exposes_recorded_antecedent_and_source_authors(self):
        detail = build_theory_detail('signaling-theory', self.article_db, self.state_db)
        self.assertEqual([item['id'] for item in detail['antecedents']],
                         ['information-asymmetry'])
        self.assertEqual(detail['key_scholars'], [])
        self.assertEqual(len(detail['source_authors']), 2)
        self.assertIn('canonical', detail['key_scholars_note'])
        self.assertTrue(any(row['verified'] for row in detail['source_authors']))
        self.assertTrue(any(not row['verified'] for row in detail['source_authors']))

    def test_catalog_references_are_resolved_to_names(self):
        detail = build_theory_detail('social-exchange-theory', self.article_db, self.state_db)
        for field in ('antecedents', 'outcomes', 'moderators'):
            for ref in detail[field]:
                self.assertTrue(ref['resolved'], '%s left %r unresolved' % (field, ref))
                self.assertNotIn('-', ref['name'].replace('Return-to', ''))

    def test_book_source_text_metadata_keeps_ocr_boundary_explicit(self):
        entity = {
            'id': 'demo-theory',
            'source_pack': 'management-organization-60',
            'source_page': 1,
        }
        metadata = _source_text_metadata(entity, {
            'demo-theory': {
                'status': 'ocr_start_candidate',
                'ocr_title_match': {'english': True, 'chinese': False},
                'printed_page_start': 1,
                'printed_page_end': 10,
                'pdf_page_start': 18,
                'pdf_page_end': 27,
                'page_offset': 17,
            }
        })
        self.assertEqual(metadata['status'], 'ocr_derived_available')
        self.assertEqual(metadata['pdf_page_start'], 18)
        self.assertTrue(metadata['human_review_required'])
        self.assertIn('evidence_queue', metadata)
        self.assertTrue(metadata['evidence_queue']['human_coding_required'])
        self.assertIn('derived local reading layer', metadata['note'])

    def test_construct_detail_marks_keyword_inference_and_measurement_boundary(self):
        detail = build_construct_detail('autonomy', {'sort': 'recent'}, self.article_db, self.state_db)
        self.assertEqual(detail['success'], True)
        self.assertTrue(detail['construct']['measurement_scales'])
        self.assertTrue(detail['construct']['source_works'])
        self.assertEqual(detail['construct']['source_works'][0]['source_role'],
                         'construct_definition_measurement')
        self.assertIn('access_status', detail['construct']['source_works'][0])
        self.assertTrue(any(p['id'] == '1' for p in detail['papers']))
        self.assertEqual(detail['data_boundary']['inference']['constructs'],
                         'title_abstract_keyword_inference')

    def test_method_detail_exposes_foundational_sources(self):
        detail = build_method_detail('difference-in-differences', self.article_db, self.state_db)
        self.assertTrue(detail['method']['source_works'])
        self.assertEqual(detail['method']['source_works'][0]['source_role'], 'method_origin')
        self.assertEqual(detail['method']['source_works'][0]['access_status'], 'open_full_text')
        self.assertTrue(detail['method']['source_works'][0]['source_url'])

    def test_construct_network_is_data_driven(self):
        detail = build_construct_detail('autonomy', {}, self.article_db, self.state_db)
        network = detail['network']
        self.assertTrue(network['antecedents'])
        self.assertTrue(network['outcomes'])
        for ref in network['antecedents'] + network['outcomes']:
            self.assertTrue(ref['resolved'])
            self.assertTrue(ref['name'][0].isupper())

    def test_paper_workspace_state_and_notes_are_separate_from_article_db(self):
        state = update_library_state(1, {'reading_status': 'reading', 'favorite': True}, self.state_db)
        self.assertEqual(state['state']['reading_status'], 'reading')
        note = save_research_note(
            1, {'note_text': 'Check the autonomy mechanism in the full paper.',
                'tags': ['Theory', 'Idea']}, self.state_db)
        self.assertEqual(note['note']['tags'], ['Theory', 'Idea'])
        workspace = build_paper_workspace(1, self.article_db, self.state_db)
        self.assertEqual(workspace['paper']['status'], 'reading')
        self.assertTrue(workspace['paper']['favorite'])
        self.assertEqual(len(workspace['notes']), 1)
        library = build_library_payload(self.article_db, self.state_db)
        self.assertEqual([p['id'] for p in library['papers']], ['1'])

    def test_partial_state_update_keeps_the_other_field(self):
        """Toggling favorite must not silently reset a paper to unread."""
        update_library_state(2, {'reading_status': 'read'}, self.state_db)
        result = update_library_state(2, {'favorite': True}, self.state_db)
        self.assertEqual(result['state']['reading_status'], 'read')
        self.assertEqual(result['state']['favorite'], 1)
        result = update_library_state(2, {'reading_status': 'reading'}, self.state_db)
        self.assertEqual(result['state']['favorite'], 1)

    def test_notes_can_be_edited_and_deleted(self):
        note = save_research_note(1, {'note_text': 'first pass'}, self.state_db)
        note_id = note['note']['id']
        updated = save_research_note(
            1, {'note_id': note_id, 'note_text': 'second pass', 'tags': ['Method']}, self.state_db)
        self.assertEqual(updated['note']['note_text'], 'second pass')
        self.assertEqual(updated['note']['tags'], ['Method'])
        self.assertEqual(len(build_paper_workspace(1, self.article_db, self.state_db)['notes']), 1)
        self.assertTrue(delete_research_note(1, note_id, self.state_db)['deleted'])
        self.assertEqual(build_paper_workspace(1, self.article_db, self.state_db)['notes'], [])
        self.assertFalse(delete_research_note(1, note_id, self.state_db)['deleted'])

    def test_library_reports_recently_opened_papers(self):
        update_library_state(3, {'reading_status': 'unread'}, self.state_db)
        library = build_library_payload(self.article_db, self.state_db, recent_ids=['1'])
        self.assertIn('1', [p['id'] for p in library['recent_papers']])
        self.assertIn('3', [p['id'] for p in library['recent_papers']])

    def test_landscape_is_descriptive_and_does_not_claim_gap(self):
        landscape = build_landscape_payload({
            'topic': 'autonomy employee voice', 'from_year': '2020', 'to_year': '2026', 'rank': 'A*,A'
        }, self.article_db, self.state_db)
        self.assertEqual(landscape['success'], True)
        self.assertIn('do not by themselves establish', landscape['underexplored_disclaimer'])
        self.assertGreaterEqual(landscape['overview']['analyzed_papers'], 1)
        self.assertIn('matrix', landscape)

    def test_landscape_withholds_underexplored_claims_on_a_tiny_corpus(self):
        """Three fixture papers cannot support a statement about what is under-studied."""
        landscape = build_landscape_payload({
            'topic': 'autonomy', 'from_year': '2020', 'to_year': '2026', 'rank': 'A*,A'
        }, self.article_db, self.state_db)
        self.assertLess(landscape['overview']['analyzed_papers'], 40)
        self.assertEqual(landscape['underexplored_combinations'], [])
        self.assertIn('withheld', landscape['underexplored_suppressed'])

    def test_landscape_widens_a_phrase_that_matches_nothing(self):
        landscape = build_landscape_payload({
            'topic': 'return-to-office employee autonomy', 'rank': 'A*,A'
        }, self.article_db, self.state_db)
        self.assertTrue(landscape['relaxed_to_any_term'])
        self.assertGreaterEqual(landscape['overview']['analyzed_papers'], 1)

    def test_landscape_distributions_carry_a_share(self):
        landscape = build_landscape_payload({
            'topic': 'autonomy burnout', 'rank': 'A*,A', 'match': 'any'
        }, self.article_db, self.state_db)
        for row in landscape['themes'] + landscape['constructs']:
            self.assertIn('share', row)
            self.assertGreaterEqual(row['share'], 0)

    def test_link_index_is_incremental_after_the_first_build(self):
        first = rebuild_link_index(self.article_db, self.state_db, force=True)
        self.assertTrue(first['rebuilt'])
        self.assertEqual(first['papers_indexed'], 3)
        second = rebuild_link_index(self.article_db, self.state_db)
        self.assertFalse(second['rebuilt'])

    def test_method_catalog_covers_every_category(self):
        payload = build_methods_payload({}, self.article_db, self.state_db)
        categories = {item['category'] for item in payload['entities']}
        self.assertEqual(categories,
                         {'quantitative', 'experimental', 'computational', 'qualitative'})
        for category in sorted(categories):
            filtered = build_methods_payload({'category': category}, self.article_db, self.state_db)
            self.assertGreaterEqual(len(filtered['entities']), 4)

    def test_theory_search_matches_its_constructs(self):
        """A search for a construct should surface the theories built on it."""
        payload = build_theories_payload({'q': 'autonomy'}, self.article_db, self.state_db)
        ids = {item['id'] for item in payload['entities']}
        self.assertIn('job-demands-resources', ids)
        self.assertIn('self-determination-theory', ids)


if __name__ == '__main__':
    unittest.main()
