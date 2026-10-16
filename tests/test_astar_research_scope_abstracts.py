import tempfile
import unittest
from pathlib import Path

from scripts.enrich_abdc_research_scope_abstracts import (
    classify_response,
    is_placeholder_abstract,
    load_semantic_scholar_api_key,
    normalize_doi,
    titles_match,
)


class ResearchScopeAbstractStageTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            "article_id": 123,
            "doi": "10.1234/example.1",
            "title": "AI in Organizations: Management and Work Design",
            "publisher": "Example Press",
            "journal_title": "Example Journal",
            "broad_area": "Management / Strategy",
            "scope_tags": ["field:Management / Strategy", "interest:ai"],
        }

    def test_doi_normalization_accepts_doi_url(self):
        self.assertEqual(
            normalize_doi("https://doi.org/10.1234/Example.1"),
            "10.1234/example.1",
        )

    def test_exact_doi_and_title_are_required_for_abstract_candidate(self):
        record = {
            "title": "AI in Organizations: Management and Work Design",
            "abstract": "A source-provided abstract.",
            "externalIds": {"DOI": "10.1234/example.1"},
            "paperId": "s2-paper-id",
        }
        result = classify_response(self.target, record)
        self.assertEqual(result["status"], "abstract_candidate")
        self.assertEqual(result["abstract"], "A source-provided abstract.")
        self.assertEqual(result["source"], "Semantic Scholar")

    def test_doi_mismatch_cannot_supply_abstract(self):
        record = {
            "title": self.target["title"],
            "abstract": "Wrong paper abstract.",
            "externalIds": {"DOI": "10.1234/different"},
        }
        result = classify_response(self.target, record)
        self.assertEqual(result["status"], "doi_mismatch")
        self.assertNotIn("abstract", result)

    def test_title_mismatch_cannot_supply_abstract(self):
        record = {
            "title": "A different paper about an unrelated subject",
            "abstract": "Wrong paper abstract.",
            "externalIds": {"DOI": self.target["doi"]},
        }
        result = classify_response(self.target, record)
        self.assertEqual(result["status"], "title_mismatch")
        self.assertNotIn("abstract", result)

    def test_empty_or_missing_api_abstract_is_not_created(self):
        record = {
            "title": self.target["title"],
            "abstract": "  ",
            "externalIds": {"DOI": self.target["doi"]},
        }
        result = classify_response(self.target, record)
        self.assertEqual(result["status"], "no_abstract")
        self.assertNotIn("abstract", result)
        self.assertEqual(classify_response(self.target, None)["status"], "no_match")

    def test_source_placeholder_is_never_staged_as_an_abstract(self):
        self.assertTrue(is_placeholder_abstract("No description provided."))
        self.assertTrue(is_placeholder_abstract("NO ABSTRACT AVAILABLE"))
        self.assertFalse(is_placeholder_abstract("This article reports no abstract result."))
        record = {
            "title": self.target["title"],
            "abstract": "No description provided",
            "externalIds": {"DOI": self.target["doi"]},
        }
        result = classify_response(self.target, record)
        self.assertEqual("placeholder_abstract", result["status"])
        self.assertNotIn("abstract", result)

    def test_title_match_accepts_normalized_punctuation_only(self):
        self.assertTrue(titles_match(
            "A Study: Title!", "a study title"
        ))
        self.assertFalse(titles_match(
            "A Study: Title!", "A completely different paper"
        ))

    def test_api_key_loader_reads_only_the_named_local_key_and_returns_no_value_to_logs(self):
        key, source = load_semantic_scholar_api_key(
            {"SEMANTIC_SCHOLAR_API_KEY": "test-environment-key"}, Path("missing-secrets")
        )
        self.assertEqual(("test-environment-key", "environment:SEMANTIC_SCHOLAR_API_KEY"),
                         (key, source))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".secrets"
            path.write_text("OTHER_PRIVATE_KEY=do-not-read\nS2_API_KEY=test-local-key\n", encoding="utf-8")
            key, source = load_semantic_scholar_api_key({}, path)
            self.assertEqual(("test-local-key", "local_secrets:S2_API_KEY"), (key, source))
        self.assertEqual((None, "none"), load_semantic_scholar_api_key({}, Path("missing-secrets")))


if __name__ == "__main__":
    unittest.main()
