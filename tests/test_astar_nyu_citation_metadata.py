"""NYU citation extraction keeps titles/abstracts/authors and scope distinct."""

import unittest

from scripts.collect_nyu_publication_metadata import parse_citations, public_pdf_url
from scripts.prepare_nyu_verified_metadata import issue_items


SOURCE = {'source_url': 'https://its.law.nyu.edu/facultyprofiles/index.cfm?personid=1',
          'raw_path': 'source.html.gz', 'sha256': 'fixture'}


class NyuCitationMetadataTests(unittest.TestCase):
    def test_anchor_title_has_no_wrapper_comma_or_affiliation_text(self):
        html = '''<h1>Owner Name</h1><ul><li>"<a href="https://go.openathens.net/login">A title</a>,"
            72 <em>Tax Law Review</em> 197 (2019) (with First Author and Second Author)
            <a class="toggle-description">Abstract</a><div class="description"><p>Supplied abstract.</p></div>
            </li></ul>'''
        rows, excluded = parse_citations(html, SOURCE)
        self.assertEqual([], excluded)
        self.assertEqual('A title', rows[0]['title'])
        self.assertEqual(['Owner Name', 'First Author', 'Second Author'], rows[0]['authors_in_faculty_citation'])
        self.assertEqual('Supplied abstract.', rows[0]['faculty_abstract'])
        self.assertNotIn('Supplied abstract.', rows[0]['citation_text'])
        self.assertFalse(public_pdf_url(rows[0]['observed_article_url']))

    def test_nested_foreword_anchor_and_roman_page(self):
        html = '''<h1>Owner Name</h1><li><a href="https://its.law.nyu.edu/faculty/profiles/representiveFiles/a.pdf">
            <a href="https://its.law.nyu.edu/faculty/profiles/representiveFiles/a.pdf">"Foreword,"</a>
            72 <i>Tax Law Review</i>, at vii (2018)</li>'''
        rows, _ = parse_citations(html, SOURCE)
        self.assertEqual('Foreword', rows[0]['title'])
        self.assertEqual('vii', rows[0]['printed_start_page'])

    def test_old_years_and_non_target_journals_are_not_admitted(self):
        html = '''<h1>Owner Name</h1><li><a href="old.pdf">Old</a> 26 Virginia Tax Review 53 (2006)</li>
            <li><a href="other.pdf">Other</a> 69 Virginia Law Review 1 (2016)</li>'''
        rows, excluded = parse_citations(html, SOURCE)
        self.assertEqual([], rows)
        self.assertEqual([2006], [row['year'] for row in excluded])

    def test_redirect_targets_cannot_enter_authentication_or_other_hosts(self):
        self.assertTrue(public_pdf_url('https://its.law.nyu.edu/faculty/profiles/representiveFiles/file.pdf'))
        for url in ['http://its.law.nyu.edu/faculty/profiles/representiveFiles/file.pdf',
                    'https://heinonline.org/file.pdf', 'https://its.law.nyu.edu/login/file.pdf']:
            self.assertFalse(public_pdf_url(url))

    def test_current_and_upcoming_sections_are_read_from_publisher_headings(self):
        html = '''<h2>Current Issue</h2><h3>Volume 72, Issue 1</h3><dl>
            <dt>"Published title"</dt><dd><p>by Author, University</p><p>Abstract:</p>
            <p>First paragraph.</p><p>Second paragraph.</p></dd></dl>
            <h2>Upcoming Issues</h2><h3>Volume 73, Issue 1</h3><dl>
            <dt>"Upcoming title"</dt><dd><p>by Other Author, University</p></dd></dl>'''
        rows = issue_items(html)
        self.assertEqual(['current_issue', 'upcoming_issue'], [row['publisher_page_section'] for row in rows])
        self.assertEqual('First paragraph. Second paragraph.', rows[0]['abstract'])
        self.assertIsNone(rows[1]['abstract'])

    def test_unknown_section_is_not_assumed_published(self):
        rows = issue_items('<h3>Volume 72, Issue 1</h3><dl><dt>Title</dt>'
                           '<dd><p>by Author, University</p></dd></dl>')
        self.assertEqual('unknown_section', rows[0]['publisher_page_section'])
