"""Public issue metadata must preserve roles and actual publisher identifiers."""

import unittest

from scripts.prepare_thomson_issue_metadata import parse_post


class ThomsonIssueMetadataTests(unittest.TestCase):
    def parse(self, body):
        return parse_post({'id': 1, 'date': '2026-01-01', 'link': 'https://publisher.example/post',
            'content': {'rendered': body}}, {'journal_title': 'Australian Tax Review', 'volume': 54,
            'issue': '4', 'year': 2025, 'pdf_path': 'fixture.pdf', 'pdf_sha256': 'fixture'})

    def test_anchor_title_keeps_an_internal_dash_and_byline_is_separate(self):
        rows = self.parse('<h3>Articles</h3><p><a href="https://www.westlaw.com.au/doc?docguid=Iabc">Title – A Question?</a> – An Author</p><p>The public abstract.</p>')
        self.assertEqual('Title – A Question?', rows[0]['title'])
        self.assertEqual(['An Author'], rows[0]['authors'])
        self.assertEqual(2025, rows[0]['publication_year'])

    def test_general_editor_is_not_assigned_as_editorial_author(self):
        rows = self.parse('<p><a href="https://www.westlaw.com.au/doc?docguid=Ieditorial">EDITORIAL</a> – General Editors: Two Names</p><ul><li><strong>A Real Editorial Title</strong></li></ul>')
        self.assertEqual('A Real Editorial Title', rows[0]['title'])
        self.assertEqual([], rows[0]['authors'])

    def test_download_and_contact_footer_is_not_an_abstract(self):
        rows = self.parse('<p><a href="https://www.westlaw.com.au/doc?docguid=Iarticle">An Article</a> – An Author</p><p>An abstract.</p><p>For the PDF version, click here.</p><p>For general queries, contact the publisher.</p>')
        self.assertEqual('An abstract.', rows[0]['abstract'])

    def test_repeated_frontmatter_link_keeps_one_item_and_editor_roles_separate(self):
        rows = self.parse('<p><a href="https://www.westlaw.com.au/doc?docguid=Ifront">JOURNAL AND SPONSOR</a></p>'
            '<p><a href="https://www.westlaw.com.au/doc?docguid=Ifront">Special Issue Title</a></p>'
            '<p>Guest Editors: First Editor, Second Editor</p>')
        self.assertEqual(1, len(rows))
        self.assertEqual('Special Issue Title', rows[0]['title'])
        self.assertIsNone(rows[0]['abstract'])
        self.assertEqual([], rows[0]['authors'])

    def test_new_publisher_domain_retains_recent_issue_items(self):
        rows = self.parse('<p><a href="https://anzlaw.thomsonreuters.com/Document/I1234567890abcdef1234567890abcdef/View/FullText.html">A Recent Article</a> – An Author</p><p>An abstract.</p>')
        self.assertEqual('A Recent Article', rows[0]['title'])
        self.assertEqual('westlaw_publication:i1234567890abcdef1234567890abcdef', rows[0]['source_raw_id'])
