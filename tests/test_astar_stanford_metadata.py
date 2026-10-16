"""Publisher citation years outrank website timestamps and trailing repository notes."""

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts" / "verify_stanford_archive_metadata.py"
SPEC = importlib.util.spec_from_file_location("stanford_metadata", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StanfordCitationTests(unittest.TestCase):
    def parse(self, citation):
        candidate = {"title": "Published paper title", "publisher_article_url": "https://law.stanford.edu/publications/paper/"}
        html = '<main><h1>Published paper title</h1><dd class="publication-citation">' + citation + '</dd></main>'
        return MODULE.parse_detail(html, candidate)

    def test_abbreviated_citation(self):
        row = self.parse('A Author, Published paper title, 29 Stan. J.L. Bus. &amp; Fin. 265 (2024).')
        self.assertEqual(2024, row['archive_year'])
        self.assertIsNone(row['publication_date'])

    def test_full_journal_name_and_repository_note(self):
        row = self.parse('A Author, Published paper title, 21 Stanford Journal of Law, Business &amp; Finance 192 (2016) (available as Working Paper 223 in 2017).')
        self.assertEqual(2016, row['archive_year'])

    def test_citation_without_page_number_still_establishes_year(self):
        row = self.parse('A Author, Published paper title, 28 Stan. J.L. Bus. &amp; Fin. (2023).')
        self.assertEqual(2023, row['archive_year'])

    def test_unrelated_year_does_not_establish_journal_year(self):
        with self.assertRaises(ValueError):
            self.parse('A Author, Published paper title, uploaded to a repository (2024).')
