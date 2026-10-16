import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.enrich_abdc_research_scope_openalex import (
    SOURCE_NAME,
    SOURCE_TYPE,
    classify_record,
    load_openalex_api_key,
    reconstruct_abstract,
)


class OpenAlexAbstractStageTests(unittest.TestCase):
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

    def test_reconstruct_abstract_uses_only_indexed_words_in_position_order(self):
        result = reconstruct_abstract({"A": [2], "source": [0], "provided": [1]})
        self.assertEqual("source provided A", result)
        self.assertEqual("", reconstruct_abstract(None))

    def test_doi_and_title_must_match_before_abstract_is_staged(self):
        record = {
            "id": "https://openalex.org/W123",
            "doi": "https://doi.org/10.1234/Example.1",
            "title": self.target["title"],
            "abstract_inverted_index": {"An": [0], "abstract": [1], "from": [2], "OpenAlex.": [3]},
        }
        result = classify_record(self.target, [record])
        self.assertEqual("abstract_candidate", result["status"])
        self.assertEqual("An abstract from OpenAlex.", result["abstract"])
        self.assertEqual(SOURCE_NAME, result["source"])
        self.assertEqual(SOURCE_TYPE, result["source_type"])
        self.assertEqual("W123", result["openalex_id"])
        self.assertEqual(hashlib.sha256(result["abstract"].encode()).hexdigest(),
                         result["abstract_sha256"])
        wrong_title = {**record, "title": "A different paper"}
        self.assertEqual("title_mismatch", classify_record(self.target, [wrong_title])["status"])
        wrong_doi = {**record, "doi": "10.1234/different"}
        self.assertEqual("no_match", classify_record(self.target, [wrong_doi])["status"])

    def test_empty_index_is_not_written_as_an_abstract(self):
        result = classify_record(self.target, [{
            "id": "https://openalex.org/W123",
            "doi": self.target["doi"],
            "title": self.target["title"],
            "abstract_inverted_index": {},
        }])
        self.assertEqual("no_abstract", result["status"])
        self.assertNotIn("abstract", result)

    def test_placeholder_index_text_is_not_staged(self):
        result = classify_record(self.target, [{
            "id": "https://openalex.org/W123",
            "doi": self.target["doi"],
            "title": self.target["title"],
            "abstract_inverted_index": {"No": [0], "description": [1], "provided": [2]},
        }])
        self.assertEqual("placeholder_abstract", result["status"])
        self.assertNotIn("abstract", result)

    def test_api_key_loader_reads_only_the_named_local_key(self):
        key, source = load_openalex_api_key({"OPENALEX_API_KEY": "env-secret"}, Path("missing-secrets"))
        self.assertEqual(("env-secret", "environment:OPENALEX_API_KEY"), (key, source))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".secrets"
            path.write_text("OTHER_PRIVATE_KEY=do-not-read\nOPENALEX_API_KEY=test-key\n", encoding="utf-8")
            self.assertEqual(("test-key", "local_secrets:OPENALEX_API_KEY"),
                             load_openalex_api_key({}, path))
        self.assertEqual((None, "none"), load_openalex_api_key({}, Path("missing-secrets")))


if __name__ == "__main__":
    unittest.main()
