import json
import sqlite3
import unittest

from services.abdc_astar_research_service import (
    _article_row_to_dict,
    _upsert_article,
    apply_verified_publisher_abstract,
    ensure_astar_tables,
)


DOI = '10.1016/j.dss.2026.114683'
TITLE = ('From compliance to commitment: A deep learning decision-support artifact '
         'linking corporate social performance to multidimensional employee perceptions')
ABSTRACT = (
    'This study uses thirteen years of employee reviews from Glassdoor and deep learning '
    'to measure pride and credibility, then links corporate social responsibility to '
    'employee satisfaction across industries and organizational stigma.')
SOURCE_URL = ('https://www.sciencedirect.com/science/article/abs/pii/'
              'S0167923626000722')


class VerifiedAbstractOverrideTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        ensure_astar_tables(self.conn)
        self.conn.execute("""INSERT INTO abdc_astar_journals
            (journal_title,issn_print,abdc_rating,abdc_version,discipline,
             field_of_research,is_active,source_table)
            VALUES ('Decision Support Systems','0167-9236','A*','2025',
                    'Information Systems','4609',1,'abdc_data.json')""")
        self.journal = {
            'journal_title': 'Decision Support Systems',
            'abdc_rating': 'A*',
            'abdc_version': '2025',
            '_area': 'Information Systems',
        }
        self.missing_article = {
            'doi': DOI,
            'openalex_id': 'W7160170324',
            'title': TITLE,
            'abstract': None,
            'abstract_status': 'missing',
            'publication_date': '2026-08-01',
            'publication_year': 2026,
            'journal_title': 'Decision Support Systems',
            'journal_issn': '0167-9236',
            'publisher': 'Elsevier BV',
            'authors': [],
            'concepts': [],
            'keywords': [],
            'url': f'https://doi.org/{DOI}',
            'landing_page_url': f'https://doi.org/{DOI}',
            'open_access_status': 'closed',
            'cited_by_count': 1,
            'source_name': 'OpenAlex',
            'source_type': 'openalex',
            'source_url': 'https://openalex.org/W7160170324',
            'data_status': 'title_only',
        }
        status, self.article_id = _upsert_article(
            self.conn, dict(self.missing_article), self.journal)
        self.assertEqual(status, 'inserted')
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def apply_override(self):
        return apply_verified_publisher_abstract(
            doi=DOI,
            abstract=ABSTRACT,
            source_url=SOURCE_URL,
            source_name='ScienceDirect',
            source_id='S0167923626000722',
            expected_title=TITLE,
            verified_at='2026-08-03T18:18:15-06:00',
            verification_notes='Public abstract verified; no full text fetched.',
            conn=self.conn,
        )

    def test_override_adds_abstract_provenance_and_reclassification(self):
        result = self.apply_override()
        self.assertTrue(result['changed'])
        row = self.conn.execute(
            'SELECT abstract,abstract_status,data_status FROM astar_articles WHERE id=?',
            (self.article_id,)).fetchone()
        self.assertEqual(row['abstract'], ABSTRACT)
        self.assertEqual(row['abstract_status'], 'available')
        self.assertEqual(row['data_status'], 'publisher_metadata')

        source = self.conn.execute("""SELECT * FROM astar_article_sources
            WHERE article_id=? AND source_type='publisher_page'""",
            (self.article_id,)).fetchone()
        self.assertEqual(source['source_name'], 'ScienceDirect')
        self.assertEqual(json.loads(source['raw_json'])['abstract'], ABSTRACT)
        self.assertIn('full_text_fetched=false', source['parser_notes'])

        classification = self.conn.execute("""SELECT classification_notes
            FROM astar_article_classifications WHERE article_id=?""",
            (self.article_id,)).fetchone()
        self.assertNotIn('no_abstract:cap55', classification['classification_notes'])

    def test_later_missing_metadata_does_not_downgrade_verified_abstract(self):
        self.apply_override()
        status, _ = _upsert_article(
            self.conn, dict(self.missing_article), self.journal)
        self.assertEqual(status, 'updated')
        row = self.conn.execute(
            'SELECT abstract,abstract_status,data_status FROM astar_articles WHERE id=?',
            (self.article_id,)).fetchone()
        self.assertEqual(row['abstract'], ABSTRACT)
        self.assertEqual(row['abstract_status'], 'available')
        self.assertEqual(row['data_status'], 'publisher_metadata')
        classification = self.conn.execute("""SELECT classification_notes
            FROM astar_article_classifications WHERE article_id=?""",
            (self.article_id,)).fetchone()
        self.assertNotIn('no_abstract:cap55', classification['classification_notes'])

    def test_override_normalizes_publisher_metadata_html_to_plain_text(self):
        apply_verified_publisher_abstract(
            doi=DOI,
            abstract=f'<h3>Abstract</h3><p>{ABSTRACT}</p>',
            source_url=SOURCE_URL,
            source_name='ScienceDirect',
            source_id='S0167923626000722',
            expected_title=TITLE,
            conn=self.conn,
        )
        row = self.conn.execute(
            'SELECT abstract FROM astar_articles WHERE id=?',
            (self.article_id,)).fetchone()
        self.assertEqual(row['abstract'], ABSTRACT)

    def test_authorized_api_provenance_is_stored_separately(self):
        result = apply_verified_publisher_abstract(
            doi=DOI,
            abstract=ABSTRACT,
            source_url=('https://api.elsevier.com/content/article/doi/'
                        '10.1016%2Fj.dss.2026.114683?view=META'),
            source_name='Elsevier Article Retrieval API',
            source_type='publisher_api',
            source_id='S0167923626000722',
            expected_title=TITLE,
            conn=self.conn,
        )
        self.assertEqual(result['source_type'], 'publisher_api')
        source = self.conn.execute("""SELECT * FROM astar_article_sources
            WHERE article_id=? AND source_type='publisher_api'""",
            (self.article_id,)).fetchone()
        self.assertEqual(source['source_name'],
                         'Elsevier Article Retrieval API')
        self.assertIn('verified_publisher_api_metadata',
                      source['parser_notes'])

    def test_missing_elsevier_record_is_labeled_review_pending(self):
        record = _article_row_to_dict({
            'id': 1,
            'doi': DOI,
            'publisher': 'Elsevier BV',
            'abstract_status': 'missing',
            'authors_json': '[]',
            'concepts_json': '[]',
            'keywords_json': '[]',
        })
        self.assertEqual(record['abstract_review_status'],
                         'publisher_page_review_pending')

        ais_record = _article_row_to_dict({
            'id': 2,
            'doi': '10.17705/1jais.00977',
            'publisher': 'Association for Information Systems',
            'abstract_status': 'missing',
            'authors_json': '[]',
            'concepts_json': '[]',
            'keywords_json': '[]',
        })
        self.assertEqual(ais_record['abstract_review_status'],
                         'metadata_recheck_pending')


if __name__ == '__main__':
    unittest.main()
