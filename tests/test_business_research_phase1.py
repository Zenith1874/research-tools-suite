import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.abdc_astar_research_service import classify_article
from services.business_research_service import (
    ASSERTION_CANDIDATE,
    ASSERTION_STATUS_CANDIDATE,
    ensure_business_research_tables,
    rebuild_link_index,
)


class Phase1ClassifierTests(unittest.TestCase):
    def test_signal_processing_and_other_signal_homonyms_are_not_theory_use(self):
        for title in (
                'Signal processing for organizational data',
                'Traffic signal timing and congestion',
                'Weak Signal Asymptotics for Experiments',
                'SIGNAL programming language benchmarks',
                'Sampling signal recovery'):
            result = classify_article({'title': title, 'abstract': '', 'concepts': []})
            self.assertNotIn('signaling', result['theory_tags'], title)

    def test_named_signaling_theory_is_still_a_candidate(self):
        result = classify_article({
            'title': 'Digital supply chain announcements',
            'abstract': 'We develop the hypotheses from signaling theory.',
            'concepts': [],
        })
        self.assertIn('signaling', result['theory_tags'])

    def test_institutional_logics_does_not_promote_institutional_theory(self):
        result = classify_article({
            'title': 'Institutional logics and entrepreneurship',
            'abstract': 'The institutional logics perspective explains competing orders.',
            'concepts': [],
        })
        self.assertIn('institutional_logics', result['theory_tags'])
        self.assertNotIn('institutional_theory', result['theory_tags'])

    def test_intrinsic_motivation_alone_does_not_promote_sdt(self):
        result = classify_article({
            'title': 'Intrinsic motivation in a protection motivation model',
            'abstract': 'The paper studies intrinsic motivation as a construct.',
            'concepts': [],
        })
        self.assertNotIn('self_determination', result['theory_tags'])

    def test_interview_survey_and_qualitative_non_interview_are_not_interviews(self):
        cases = (
            'National Health Interview Survey',
            'Press interview coverage of a policy announcement',
            'A qualitative ethnography of workplace routines',
        )
        for title in cases:
            result = classify_article({'title': title, 'abstract': '', 'concepts': []})
            self.assertNotIn('qualitative_interviews', result['method_tags'], title)

    def test_interview_data_is_a_candidate(self):
        result = classify_article({
            'title': 'Employee experiences of algorithmic management',
            'abstract': 'We conducted semi-structured interviews with  thirty workers.',
            'concepts': [],
        })
        self.assertIn('qualitative_interviews', result['method_tags'])

    def test_continuous_time_embedding_is_not_nlp_embeddings(self):
        result = classify_article({
            'title': 'Continuous-time embedding of a stochastic sales process',
            'abstract': 'We derive a mathematical embedding for a stochastic process.',
            'concepts': [],
        })
        self.assertNotIn('NLP', result['method_tags'])


class Phase1AssertionIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.article_db = root / 'articles.db'
        self.state_db = root / 'state.db'
        conn = sqlite3.connect(self.article_db)
        conn.executescript('''
            CREATE TABLE astar_articles (
                id INTEGER PRIMARY KEY, title TEXT, abstract TEXT,
                is_duplicate INTEGER DEFAULT 0, updated_at TEXT,
                created_at TEXT
            );
            CREATE TABLE astar_article_classifications (
                article_id INTEGER PRIMARY KEY, theory_tags_json TEXT,
                method_tags_json TEXT, classified_at TEXT,
                classification_method TEXT
            );
            INSERT INTO astar_articles VALUES
                (1, 'Signaling theory and announcements',
                 'The paper explicitly uses signaling theory.', 0,
                 '2026-09-02T10:00:00', '2026-09-02T09:00:00');
            INSERT INTO astar_article_classifications VALUES
                (1, '["signaling"]', '[]', '2026-09-02T10:01:00', 'rules');
        ''')
        conn.commit()
        conn.close()
        ensure_business_research_tables(state_db_path=self.state_db)
        self.catalog = {
            'theories': [{
                'id': 'signaling-theory', 'name': 'Signaling Theory',
                'tags': ['signaling'], 'broad_tags': [],
            }],
            'constructs': [], 'methods': [],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_writes_candidate_assertion_with_evidence_boundary(self):
        result = rebuild_link_index(self.article_db, self.state_db,
                                    self.catalog, force=True)
        self.assertTrue(result['rebuilt'])
        conn = sqlite3.connect(self.state_db)
        row = conn.execute('SELECT * FROM research_entity_assertions').fetchone()
        columns = [item[1] for item in conn.execute(
            'PRAGMA table_info(research_entity_assertions)')]
        assertion = dict(zip(columns, row))
        conn.close()
        self.assertEqual(assertion['assertion_type'], ASSERTION_CANDIDATE)
        self.assertEqual(assertion['verification_status'], ASSERTION_STATUS_CANDIDATE)
        self.assertEqual(assertion['evidence_level'], 'E2_TITLE_ABSTRACT')
        self.assertEqual(assertion['matched_field'], 'title_abstract')
        self.assertEqual(assertion['classifier_version'],
                         'business-research-m1-2026-09-02')

    def test_existing_row_revision_forces_rebuild_and_can_remove_link(self):
        rebuild_link_index(self.article_db, self.state_db, self.catalog, force=True)
        conn = sqlite3.connect(self.article_db)
        conn.execute('UPDATE astar_article_classifications SET theory_tags_json=?, classified_at=?',
                     ('[]', '2026-09-02T10:05:00'))
        conn.commit()
        conn.close()
        result = rebuild_link_index(self.article_db, self.state_db, self.catalog)
        self.assertTrue(result['rebuilt'])
        self.assertTrue(result['full'])
        conn = sqlite3.connect(self.state_db)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM research_paper_links').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM research_entity_assertions').fetchone()[0], 0)
        self.assertIsNotNone(conn.execute(
            "SELECT value FROM research_index_meta WHERE key='classification_revision_watermark'"
        ).fetchone())
        conn.close()


if __name__ == '__main__':
    unittest.main()
