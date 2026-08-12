import os
import tempfile
import unittest
from unittest.mock import patch

from scripts.probe_astar_publisher_abstracts import (
    _elsevier_api_abstract,
    _elsevier_api_url,
    _generic_strong_abstract,
    _MetaParser,
    _publisher_family,
    load_local_secret,
    probe_elsevier_api_row,
    count_excluded_nonempty,
    select_rows,
    _springer_abstract,
)


class PublisherProbeTests(unittest.TestCase):
    def test_local_secret_loader_reads_only_requested_value(self):
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
            handle.write('OTHER_SECRET=do-not-load\n')
            handle.write('ELSEVIER_API_KEY=local-test-value\n')
            path = handle.name
        try:
            with patch.dict(os.environ, {}, clear=True):
                source = load_local_secret('ELSEVIER_API_KEY', path=path)
                self.assertEqual(source, 'local_secrets')
                self.assertEqual(os.environ['ELSEVIER_API_KEY'],
                                 'local-test-value')
                self.assertNotIn('OTHER_SECRET', os.environ)
        finally:
            os.unlink(path)

    def test_local_secret_loader_preserves_environment_precedence(self):
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as handle:
            handle.write('ELSEVIER_API_KEY=file-test-value\n')
            path = handle.name
        try:
            with patch.dict(os.environ,
                            {'ELSEVIER_API_KEY': 'environment-test-value'},
                            clear=True):
                source = load_local_secret('ELSEVIER_API_KEY', path=path)
                self.assertEqual(source, 'environment')
                self.assertEqual(os.environ['ELSEVIER_API_KEY'],
                                 'environment-test-value')
        finally:
            os.unlink(path)

    def test_springer_dc_description_is_a_candidate_after_identity_checks(self):
        parser = _MetaParser()
        parser.feed('''
            <meta name="citation_doi" content="10.1007/abc-123" />
            <meta name="citation_title" content="A useful article" />
            <meta name="dc.description" content="This is a sufficiently long public abstract field that should be accepted as the article abstract for the probe." />
        ''')
        meta = {m.get('name'): m.get('content') for m in parser.meta}
        abstract, parser_name, reason = _springer_abstract(meta, {
            'doi': '10.1007/abc-123',
            'title': 'A useful article',
        })
        self.assertTrue(abstract)
        self.assertEqual(parser_name, 'springer_dc_description')
        self.assertEqual(reason, 'verified_doi_title_and_public_metadata')

    def test_springer_title_mismatch_is_not_accepted(self):
        abstract, parser_name, reason = _springer_abstract({
            'citation_doi': '10.1007/abc-123',
            'citation_title': 'Another article',
            'dc.description': 'This is a sufficiently long public abstract field that must not be accepted when the title does not match.',
        }, {'doi': '10.1007/abc-123', 'title': 'A useful article'})
        self.assertIsNone(abstract)
        self.assertEqual(parser_name, 'springer_metadata')
        self.assertEqual(reason, 'title_mismatch')

    def test_generic_citation_abstract_requires_matching_doi_and_title(self):
        abstract, parser_name, reason = _generic_strong_abstract({
            'citation_doi': 'https://doi.org/10.1234/example',
            'citation_title': 'A useful article',
            'citation_abstract': (
                '<h3>Abstract</h3><p>This article provides a sufficiently detailed '
                'abstract for a generic publisher metadata test and contains more '
                'than twelve words.</p>'
            ),
        }, {'doi': '10.1234/example', 'title': 'A useful article'})
        self.assertTrue(abstract)
        self.assertNotIn('<', abstract)
        self.assertTrue(abstract.startswith('This article'))
        self.assertEqual(parser_name, 'generic_citation_abstract')
        self.assertEqual(reason, 'verified_doi_title_and_public_metadata')

    def test_generic_description_rejects_identity_mismatch(self):
        abstract, parser_name, reason = _generic_strong_abstract({
            'citation_doi': '10.1234/other',
            'citation_title': 'A useful article',
            'dc.description': (
                'This article provides a sufficiently detailed abstract for a '
                'generic publisher metadata test and contains more than twelve words.'
            ),
        }, {'doi': '10.1234/example', 'title': 'A useful article'})
        self.assertIsNone(abstract)
        self.assertEqual(parser_name, 'generic_scholarly_metadata')
        self.assertEqual(reason, 'doi_mismatch')

    def test_elsevier_meta_view_requires_matching_doi_title_and_abstract(self):
        row = {
            'doi': '10.1016/j.dss.2026.114688',
            'title': ('Unraveling anthropomorphism in IT/IS research: A literature '
                      'review, conceptual framework, and research directions'),
        }
        payload = {'full-text-retrieval-response': {'coredata': {
            'prism:doi': row['doi'],
            'dc:title': row['title'],
            'pii': 'S0167923626000771',
            'dc:description': (
                '<p>This sufficiently detailed abstract contains more than twelve '
                'words and is returned only from the authorized metadata view.</p>'
            ),
        }}}
        abstract, pii, reason = _elsevier_api_abstract(payload, row)
        self.assertTrue(abstract.startswith('This sufficiently detailed'))
        self.assertEqual(pii, 'S0167923626000771')
        self.assertEqual(reason, 'verified_elsevier_meta_doi_title_abstract')
        self.assertNotIn('<', abstract)
        self.assertIn('view=META', _elsevier_api_url(row['doi']))

    def test_elsevier_meta_view_rejects_title_mismatch(self):
        payload = {'full-text-retrieval-response': {'coredata': {
            'prism:doi': '10.1016/j.dss.2026.114688',
            'dc:title': 'A different article',
            'dc:description': 'A long abstract that must never be accepted for a different article title even when the DOI field is present.',
        }}}
        abstract, pii, reason = _elsevier_api_abstract(payload, {
            'doi': '10.1016/j.dss.2026.114688',
            'title': 'Expected title',
        })
        self.assertIsNone(abstract)
        self.assertIsNone(pii)
        self.assertEqual(reason, 'title_mismatch')

    def test_elsevier_probe_without_key_is_pending_and_does_not_request(self):
        class NoNetworkSession:
            def get(self, *args, **kwargs):
                raise AssertionError('network must not be used without a key')

        result = probe_elsevier_api_row(NoNetworkSession(), {
            'id': 616,
            'doi': '10.1016/j.dss.2026.114688',
            'title': 'Expected title',
            'publisher': 'Elsevier BV',
            'journal_title': 'Decision Support Systems',
        }, api_key='', delay=0)
        self.assertEqual(result['status'], 'authorization_required')
        self.assertEqual(result['reason'], 'elsevier_api_key_missing')

    def test_publisher_family_is_explicit(self):
        self.assertEqual(_publisher_family('Springer Science+Business Media'), 'springer')
        self.assertEqual(_publisher_family('Palgrave Macmillan'), 'springer')
        self.assertEqual(_publisher_family('Elsevier BV'), 'elsevier')
        self.assertEqual(_publisher_family('A publisher not yet supported'), 'other')

    def test_nonempty_abstract_marked_missing_is_excluded_from_queue(self):
        import sqlite3

        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute('''CREATE TABLE astar_articles (
            id INTEGER, doi TEXT, title TEXT, publisher TEXT, journal_title TEXT,
            abstract_status TEXT, is_duplicate INTEGER, abstract TEXT,
            publication_date TEXT
        )''')
        conn.execute("""INSERT INTO astar_articles VALUES
            (1,'10.1/blank','Blank','Springer','J','missing',0,'','2026-01-02')""")
        conn.execute("""INSERT INTO astar_articles VALUES
            (2,'10.1/nonempty','Already text','Springer','J','missing',0,
             'Existing abstract text','2026-01-01')""")
        rows = select_rows(conn, publisher='Springer')
        self.assertEqual([row['id'] for row in rows], [1])
        self.assertEqual(count_excluded_nonempty(conn, publisher='Springer'), 1)
        conn.close()


if __name__ == '__main__':
    unittest.main()
