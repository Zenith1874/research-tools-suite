"""Publisher verification must not turn index hits into unverified paper dates."""

import unittest

from scripts.supplement_tax_forum_history import parse_public_metadata


TARGET = {"title": "A tax research article", "path": "/resources/journals/australian-tax-forum/2010/a-tax-research-article", "contentAuthors": ["A Researcher"]}


class PublisherMetadataTests(unittest.TestCase):
    def test_matching_public_title_and_date_are_verified(self):
        html = '<div><h1>A tax research article</h1><p>Published Date: 19 Mar 2010</p></div>'
        result = parse_public_metadata(html, TARGET)
        self.assertEqual("2010-03-19", result["publication_date"])
        self.assertEqual(["A Researcher"], result["authors"])
        self.assertEqual(TARGET["path"], result["source_raw_id"])
        self.assertIsNone(result["doi"])

    def test_archive_year_is_not_used_to_overrule_a_conflicting_page_date(self):
        html = '<div><h1>A tax research article</h1><p>Published Date: 19 Mar 2024</p></div>'
        with self.assertRaisesRegex(ValueError, "differs"):
            parse_public_metadata(html, TARGET)

    def test_heading_mismatch_is_not_imported(self):
        html = '<div><h1>A different journal article</h1><p>Published Date: 19 Mar 2010</p></div>'
        with self.assertRaisesRegex(ValueError, "heading"):
            parse_public_metadata(html, TARGET)

    def test_missing_publication_date_does_not_invent_january_first(self):
        html = '<div><h1>A tax research article</h1><p>Subscriber only</p></div>'
        with self.assertRaisesRegex(ValueError, "unavailable"):
            parse_public_metadata(html, TARGET)


if __name__ == "__main__":
    unittest.main()
