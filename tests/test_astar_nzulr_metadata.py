"""Legacy issue-page boundaries, character decoding and missing-author checks."""

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_nzulr_metadata.py"
SPEC = importlib.util.spec_from_file_location("nzulr_metadata", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NZULRMetadataTests(unittest.TestCase):
    def parse(self, html):
        return MODULE.parse_issue(html, "https://nzulr.com/archives/example.htm", "saved.html.gz", "fixture")

    def test_malformed_nested_paragraphs_do_not_hide_articles(self):
        rows, issues = self.parse('<td><h3>Vol 27, No 4B December 2017</h3><h4>ARTICLES</h4><p>First title<br><em>A Author</em><p>Second title<br><em>B Author</em></p></td>')
        self.assertEqual(["First title", "Second title"], [row["title"] for row in rows])
        self.assertEqual(2, issues[0]["record_count"])

    def test_both_lettered_issues_have_separate_identities(self):
        rows, issues = self.parse('<td><h3>Vol 27, No 4B December 2017</h3><h4>ARTICLES</h4><p>Editorial<br><em>Editor Name</em></p><h3>Vol 27, No 4A December 2017</h3><h4>ARTICLES</h4><p>Editorial<br><em>Editor Name</em></p></td>')
        self.assertEqual(["4B", "4A"], [row["issue"] for row in rows])
        self.assertNotEqual(rows[0]["source_raw_id"], rows[1]["source_raw_id"])
        self.assertEqual(2, len(issues))

    def test_legacy_smart_quotes_are_decoded_without_replacement(self):
        rows, _ = self.parse(b'<td><h3>Vol 24, No 2 December 2010</h3><h4>ARTICLES</h4><p>You Don\x92t Always Get What You Pay For<br><em>A Author</em></p></td>')
        self.assertEqual("You Don’t Always Get What You Pay For", rows[0]["title"])
        self.assertNotIn("\ufffd", rows[0]["title"])

    def test_italic_title_and_blank_emphasis_do_not_replace_author(self):
        rows, _ = self.parse('<td><h3>Vol 24, No 1 June 2010</h3><h4>ARTICLES</h4><p>NOTE<br><em>Bain</em>, Bayes and Basics<br><em>Bernard Robertson</em><em> </em></p></td>')
        self.assertEqual("Bain , Bayes and Basics", rows[0]["title"])
        self.assertEqual(["Bernard Robertson"], rows[0]["authors"])

    def test_book_review_title_is_not_an_invented_author(self):
        rows, _ = self.parse('<td><h3>Vol 24, No 2 December 2010</h3><h4>BOOK REVIEWS</h4><p><em>A reviewed book title</em></p></td>')
        self.assertEqual("A reviewed book title", rows[0]["title"])
        self.assertEqual([], rows[0]["authors"])
        self.assertEqual("book-review", rows[0]["record_type"])
        self.assertIsNone(rows[0]["publication_date"])
        self.assertEqual("2010-12", rows[0]["publication_month"])

    def test_multiple_articles_in_one_paragraph_have_distinct_authors(self):
        rows, _ = self.parse('<td><h3>Vol 26, No 2 December 2014</h3><h4>ARTICLES</h4>'
            '<p>First title<br><em>First Author</em><br><br>'
            'Second title with <em>Italic Case</em><br><em>Second Author<br> </em><br>'
            'Third title<br><em>Third Author</em></p></td>')
        self.assertEqual(['First title', 'Second title with Italic Case', 'Third title'], [row['title'] for row in rows])
        self.assertEqual([['First Author'], ['Second Author'], ['Third Author']], [row['authors'] for row in rows])

    def test_inline_book_review_section_splits_separate_italic_titles(self):
        rows, _ = self.parse('<td><h3>Vol 25, No 5 December 2013</h3><h4>ARTICLES</h4>'
            '<p>Article title<br><em>An Author</em><br><br>BOOK REVIEWS<br>'
            '<em>First reviewed book</em><br><br><em>Second reviewed book</em></p></td>')
        self.assertEqual(['Article title', 'First reviewed book', 'Second reviewed book'], [row['title'] for row in rows])
        self.assertEqual(['journal-metadata-item', 'book-review', 'book-review'], [row['record_type'] for row in rows])

    def test_book_review_and_explicit_reviewer_are_one_item(self):
        rows, _ = self.parse('<td><h3>Vol 29, No 1 June 2020</h3><h4>BOOK REVIEWS</h4>'
                            '<p><em>A Book Title</em><br><em>Jayden Houghton</em></p></td>')
        self.assertEqual(1, len(rows))
        self.assertEqual('A Book Title', rows[0]['title'])
        self.assertEqual(['Jayden Houghton'], rows[0]['authors'])

    def test_wrapped_author_continuation_retains_every_supplied_author(self):
        rows, _ = self.parse('<td><h3>Vol 28, No 3 June 2019</h3><h4>ARTICLES</h4>'
            '<p>An Article Title<br><em>Kelly Howard, Clare McCann, Andrea Ewing, Margaret Dudley</em>'
            '<br><em>and Warren Brookbanks</em></p></td>')
        self.assertEqual(1, len(rows))
        self.assertEqual(['Kelly Howard', 'Clare McCann', 'Andrea Ewing', 'Margaret Dudley', 'Warren Brookbanks'], rows[0]['authors'])


if __name__ == "__main__":
    unittest.main()
