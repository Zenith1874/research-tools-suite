import hashlib
import unittest

from scripts.enrich_abdc_research_scope_openalex_no_doi import (
    NO_DOI_TARGET_QUERY,
    classify_record,
    normalize_openalex_id,
)


class OpenAlexNoDoiAbstractStageTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            "article_id": 456,
            "doi": None,
            "openalex_id": "W1234567890",
            "title": "An Organizational Research Title",
            "publisher": "Example Press",
            "journal_title": "Example Journal",
            "broad_area": "Management / Strategy",
            "scope_tags": ["field:Management / Strategy"],
        }

    def test_no_doi_query_uses_existing_openalex_ids_and_keeps_scope(self):
        self.assertIn("a.openalex_id IS NOT NULL", NO_DOI_TARGET_QUERY)
        self.assertIn("a.doi IS NULL", NO_DOI_TARGET_QUERY)
        self.assertIn("Management / Strategy", NO_DOI_TARGET_QUERY)
        self.assertIn("ai_related_score", NO_DOI_TARGET_QUERY)

    def test_openalex_id_url_is_normalized(self):
        self.assertEqual("W1234567890", normalize_openalex_id("https://openalex.org/W1234567890"))

    def test_openalex_id_and_title_match_can_stage_abstract_without_doi(self):
        record = {
            "id": "https://openalex.org/W1234567890",
            "doi": "https://doi.org/10.1234/publisher-record",
            "title": self.target["title"],
            "abstract_inverted_index": {"A": [0], "source": [1], "abstract.": [2]},
        }
        result = classify_record(self.target, [record])
        self.assertEqual("abstract_candidate", result["status"])
        self.assertIsNone(result["doi"])
        self.assertEqual("W1234567890", result["openalex_id"])
        self.assertEqual("W1234567890", result["returned_openalex_id"])
        self.assertEqual("A source abstract.", result["abstract"])
        self.assertEqual(hashlib.sha256(result["abstract"].encode()).hexdigest(),
                         result["abstract_sha256"])
        self.assertEqual("10.1234/publisher-record", result["returned_doi"].removeprefix("https://doi.org/"))

    def test_wrong_work_id_or_title_never_supplies_abstract(self):
        record = {
            "id": "https://openalex.org/W9876543210",
            "title": self.target["title"],
            "abstract_inverted_index": {"Wrong": [0]},
        }
        self.assertEqual("no_match", classify_record(self.target, [record])["status"])
        record["id"] = "https://openalex.org/W1234567890"
        record["title"] = "A different work"
        self.assertEqual("title_mismatch", classify_record(self.target, [record])["status"])

    def test_empty_abstract_index_stays_no_abstract(self):
        result = classify_record(self.target, [{
            "id": "https://openalex.org/W1234567890",
            "title": self.target["title"],
            "abstract_inverted_index": None,
        }])
        self.assertEqual("no_abstract", result["status"])
        self.assertNotIn("abstract", result)

    def test_openalex_placeholder_is_not_staged(self):
        result = classify_record(self.target, [{
            "id": "https://openalex.org/W1234567890",
            "title": self.target["title"],
            "abstract_inverted_index": {"No": [0], "description": [1], "provided": [2]},
        }])
        self.assertEqual("placeholder_abstract", result["status"])
        self.assertNotIn("abstract", result)


if __name__ == "__main__":
    unittest.main()
