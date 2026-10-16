"""Abstract matching requires an explicit issue and preserves title-only blocks."""

import unittest

from scripts.prepare_nzulr_abstracts import match_records, parse_document


def line(text, size=9, flags=6):
    return {'text': text, 'sizes': [size], 'flags': [flags]}


class NzulrAbstractTests(unittest.TestCase):
    def test_title_only_item_does_not_borrow_the_next_abstract(self):
        document = {'url': 'fixture.pdf', 'pdf_path': 'fixture.pdf', 'pdf_sha256': 'fixture', 'pages': [
            {'page': 1, 'text': 'Vol 29, No 1 June 2020', 'lines': [
                line('NZULR ABSTRACTS', 12, 20), line('Vol 29, No 1 June 2020', 12, 20),
                line('FIRST TITLE', 10, 20), line('First Author', 10, 4),
                line('SECOND TITLE', 10, 20), line('Second Author', 10, 4),
                line('This is the second abstract.')]}]}
        rows = parse_document(document)
        self.assertEqual(2, len(rows))
        self.assertIsNone(rows[0]['abstract'])
        self.assertEqual('This is the second abstract.', rows[1]['abstract'])

    def test_continuation_across_pages_keeps_one_abstract(self):
        document = {'url': 'fixture.pdf', 'pdf_path': 'fixture.pdf', 'pdf_sha256': 'fixture', 'pages': [
            {'page': 1, 'text': 'Vol 27, No 4A December 2017', 'lines': [
                line('WRAPPED TITLE', 10, 20), line('SECOND TITLE LINE', 10, 20),
                line('An Author', 10, 4), line('The abstract starts')]},
            {'page': 2, 'text': 'and continues.', 'lines': [line('and continues.')]}]}
        rows = parse_document(document)
        self.assertEqual('WRAPPED TITLE SECOND TITLE LINE', rows[0]['observed_pdf_title'])
        self.assertEqual('The abstract starts and continues.', rows[0]['abstract'])
        self.assertEqual([1, 2], rows[0]['source_pages'])

    def test_same_title_in_the_wrong_issue_is_not_matched(self):
        candidate = {'volume': 27, 'issue': '4B', 'archive_year': 2017,
                     'observed_pdf_title': 'Same title', 'abstract': 'An abstract'}
        issue = {'volume': 27, 'issue': '4A', 'archive_year': 2017, 'title': 'Same title',
                 'source_raw_id': 'first-item', 'source_url': 'fixture.htm'}
        self.assertEqual('REVIEW_TITLE_OR_ISSUE_MISMATCH', match_records([candidate], [issue])[0]['status'])

    def test_plain_ten_point_abstract_is_not_discarded_as_author_text(self):
        document = {'url': 'fixture.pdf', 'pdf_path': 'fixture.pdf', 'pdf_sha256': 'fixture', 'pages': [
            {'page': 1, 'text': 'Vol 26, No 2 December 2014', 'lines': [
                line('AN ARTICLE', 10, 20), line('An Author', 10, 4),
                line('This plain text is the abstract.', 10, 4)]}]}
        issue = {'volume': 26, 'issue': '2', 'archive_year': 2014, 'title': 'An Article',
                 'source_raw_id': 'one', 'source_url': 'fixture.htm', 'authors': ['An Author']}
        row = match_records(parse_document(document), [issue])[0]
        self.assertEqual('This plain text is the abstract.', row['abstract'])
        self.assertTrue(row['author_prefix_verified_against_issue'])

    def test_lowercase_statutory_abbreviation_still_marks_a_new_title(self):
        document = {'url': 'fixture.pdf', 'pdf_path': 'fixture.pdf', 'pdf_sha256': 'fixture', 'pages': [
            {'page': 1, 'text': 'Vol 26, No 2 December 2014', 'lines': [
                line('FIRST ARTICLE', 10, 20), line('An Author', 10, 4), line('First abstract.'),
                line('DO ADJUDICATORS MAKE ss 19-24', 10, 20), line('DETERMINATIONS?', 10, 20),
                line('Second Author', 10, 4), line('Second abstract.')]}]}
        rows = parse_document(document)
        self.assertEqual(2, len(rows))
        self.assertEqual('First abstract.', rows[0]['abstract'])
        self.assertEqual('DO ADJUDICATORS MAKE ss 19-24 DETERMINATIONS?', rows[1]['observed_pdf_title'])

    def test_italic_subtitle_and_title_date_range_are_not_author_names(self):
        document = {'url': 'fixture.pdf', 'pdf_path': 'fixture.pdf', 'pdf_sha256': 'fixture', 'pages': [
            {'page': 1, 'text': 'Vol 26, No 3 June 2015', 'lines': [
                line('BANKRUPTCY LAW', 10, 20), line('AN ITALIC SUBTITLE', 10, 22),
                line('c. 1860–1867', 10, 20), line('Stuart Anderson', 10, 4), line('An abstract.')]}]}
        row = parse_document(document)[0]
        self.assertEqual('BANKRUPTCY LAW AN ITALIC SUBTITLE c. 1860–1867', row['observed_pdf_title'])
        self.assertEqual('Stuart Anderson', row['observed_pdf_author'])
