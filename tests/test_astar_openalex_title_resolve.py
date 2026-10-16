import hashlib
import unittest

from scripts.enrich_abdc_research_scope_openalex_title_resolve import (
    TITLE_TARGET_QUERY,
    classify_search_results,
)


class OpenAlexTitleResolutionTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            "article_id": 99,
            "doi": None,
            "openalex_id": None,
            "title": "A Study of Work and Wages",
            "journal_title": "Journal of Australian Taxation",
            "publication_year": 2019,
            "broad_area": "Law",
            "scope_tags": ["interest:work"],
        }
        self.record = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1234/work.1",
            "title": "A Study of Work and Wages",
            "publication_year": 2019,
            "primary_location": {"source": {"display_name": "Journal of Australian Taxation"}},
            "abstract_inverted_index": {"A": [0], "source": [1], "abstract.": [2]},
        }

    def test_no_doi_candidate_requires_exact_title_journal_year_and_id(self):
        result = classify_search_results(self.target, [self.record])
        self.assertEqual("abstract_candidate", result["status"])
        self.assertIsNone(result["doi"])
        self.assertEqual("W123", result["openalex_id"])
        self.assertEqual("title_journal_year", result["identity_method"])
        self.assertEqual("A source abstract.", result["abstract"])
        self.assertEqual(hashlib.sha256(result["abstract"].encode()).hexdigest(),
                         result["abstract_sha256"])

    def test_wrong_journal_or_year_is_held(self):
        wrong_journal = {**self.record, "primary_location": {"source": {"display_name": "Other Journal"}}}
        self.assertEqual("venue_year_mismatch", classify_search_results(
            self.target, [wrong_journal])["status"])
        wrong_year = {**self.record, "publication_year": 2018}
        self.assertEqual("venue_year_mismatch", classify_search_results(
            self.target, [wrong_year])["status"])

    def test_placeholder_description_is_not_a_candidate(self):
        placeholder = {**self.record, "abstract_inverted_index": {
            "No": [0], "description": [1], "provided": [2],
        }}
        result = classify_search_results(self.target, [placeholder])
        self.assertEqual("placeholder_abstract", result["status"])
        self.assertNotIn("abstract", result)

    def test_query_preserves_missing_doi_and_no_source_id_scope(self):
        self.assertIn("a.openalex_id IS NULL", TITLE_TARGET_QUERY)
        self.assertIn("a.doi IS NULL", TITLE_TARGET_QUERY)
        self.assertIn("Management / Strategy", TITLE_TARGET_QUERY)


if __name__ == "__main__":
    unittest.main()
