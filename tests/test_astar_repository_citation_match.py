"""Published repository dates and full citation identity are mandatory."""

import unittest

from scripts.reconcile_lexis_repository_citations import exact_publisher_match, extract_repository_citation


class RepositoryCitationTests(unittest.TestCase):
    def html(self, date_type='published'):
        fields = {'eprints.ispublished': 'pub', 'eprints.date_type': date_type, 'eprints.date': '2020',
            'citation_publication_date': '2020', 'citation_online_date': '2021/08/27',
            'citation_journal_title': 'Torts Law Journal', 'citation_title': 'A title',
            'citation_author': 'Swannie, Bill', 'citation_volume': '26', 'citation_issue': '1',
            'citation_firstpage': '34', 'eprints.full_text_status': 'restricted'}
        return ''.join('<meta name="' + key + '" content="' + value + '">' for key, value in fields.items())

    def test_publication_date_is_not_accession_date_and_restricted_body_not_needed(self):
        row = extract_repository_citation(self.html())
        self.assertEqual(2020, row['publication_year'])
        self.assertEqual(['Bill Swannie'], row['authors'])
        self.assertTrue(row['pdf_restricted'])
        with self.assertRaises(ValueError):
            extract_repository_citation(self.html('accepted'))

    def test_same_title_without_issue_page_and_author_corroboration_does_not_match(self):
        citation = extract_repository_citation(self.html())
        row = dict(citation, source_raw_id='publisher:item', issue='2')
        with self.assertRaises(ValueError):
            exact_publisher_match([row], citation)

    def test_duplicate_source_aliases_keep_one_item_but_conflicting_abstracts_fail(self):
        citation = extract_repository_citation(self.html())
        row = dict(citation, source_raw_id='publisher:item', abstract='Supplied abstract.',
                   source_url='https://publisher.example/a.pdf', pdf_path='a.pdf', pdf_sha256='one')
        alias = dict(row, source_url='https://publisher.example/b.pdf', pdf_path='b.pdf', pdf_sha256='two')
        result = exact_publisher_match([row, alias], citation)
        self.assertEqual(2, len(result['publisher_source_aliases']))
        with self.assertRaises(ValueError):
            exact_publisher_match([row, dict(alias, abstract='Different text.')], citation)
