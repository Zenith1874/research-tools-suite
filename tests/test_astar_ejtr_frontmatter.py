"""Front-matter evidence boundaries using small synthetic publisher-like PDFs."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import fitz

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_ejtr_frontmatter.py"
SPEC = importlib.util.spec_from_file_location("ejtr_frontmatter", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FrontMatterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "2026-upload-filename.pdf"

    def tearDown(self):
        self.temp.cleanup()

    def pdf(self, title="Verified research title", abstract=True, covers=0, report_year=True, author_size=12, add_jel=False):
        document = fitz.open()
        for _ in range(covers):
            page = document.new_page()
            page.insert_text((50, 80), "Publisher cover and contents")
        page = document.new_page()
        header = "eJournal of Tax Research " + ("(2025) " if report_year else "") + "vol. 23, no. 2, pp. 191-215"
        page.insert_text((50, 50), header, fontsize=9)
        page.insert_text((50, 120), title, fontsize=18)
        if abstract:
            page.insert_text((50, 160), "A Researcher1, B Author2 and C Author3", fontsize=author_size)
            page.insert_text((50, 210), "Abstract", fontsize=12)
            page.insert_text((50, 245), "A verified publisher abstract with an explicit boundary.", fontsize=10)
            if add_jel:
                page.insert_text((50, 290), "JEL classification: K34 Tax Law", fontsize=10)
            page.insert_text((50, 330), "Keywords: taxation, governance", fontsize=11)
            page.insert_text((50, 720), "Author affiliations must not enter the abstract.", fontsize=8)
        else:
            page.insert_text((50, 170), "Editorial body text is not an author name.", fontsize=11)
        document.save(self.path)
        document.close()

    def test_explicit_issue_year_overrides_upload_filename_year(self):
        self.pdf()
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("VERIFIED_METADATA", result["status"])
        self.assertEqual(2025, result["print_year"])
        self.assertIsNone(result["publication_date"])
        self.assertEqual("year", result["date_precision"])

    def test_authors_have_individual_footnote_markers_removed(self):
        self.pdf()
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual(["A Researcher", "B Author", "C Author"], result["authors"])

    def test_same_font_author_block_is_not_appended_to_title(self):
        self.pdf(author_size=18)
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("Verified research title", result["title"])
        self.assertEqual(["A Researcher", "B Author", "C Author"], result["authors"])

    def test_a_missing_year_is_not_inferred_from_volume_or_filename(self):
        self.pdf(report_year=False)
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("REVIEW_ISSUE_YEAR_NOT_REPORTED", result["status"])
        evidence = {"volume": 23, "issue": 2, "year": 2019, "basis": "publisher_archive_issue_label_year"}
        result = MODULE.extract(self.path, "Verified research title", issue_year_evidence=evidence)
        self.assertEqual("VERIFIED_METADATA", result["status"])
        self.assertEqual(2019, result["archive_year"])
        self.assertIsNone(result["print_year"])
        self.assertEqual("publisher_archive_issue_label_year", result["year_basis"])

    def test_external_year_evidence_for_another_issue_is_rejected(self):
        self.pdf(report_year=False)
        evidence = {"volume": 22, "issue": 1, "year": 2024, "basis": "publisher_issue_cover_year"}
        result = MODULE.extract(self.path, "Verified research title", issue_year_evidence=evidence)
        self.assertEqual("REVIEW_ISSUE_YEAR_NOT_REPORTED", result["status"])

    def test_jel_classification_is_not_part_of_an_abstract(self):
        self.pdf(add_jel=True)
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("A verified publisher abstract with an explicit boundary.", result["abstract"])

    def test_explicit_abstract_boundary_excludes_keywords_and_affiliations(self):
        self.pdf()
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("A verified publisher abstract with an explicit boundary.", result["abstract"])
        self.assertEqual(["taxation", "governance"], result["keywords"])

    def test_missing_author_region_is_left_unsupplied(self):
        self.pdf(title="Editorial Announcements", abstract=False)
        result = MODULE.extract(self.path, "Editorial Announcements")
        self.assertEqual("VERIFIED_METADATA", result["status"])
        self.assertEqual([], result["authors"])
        self.assertIsNone(result["abstract"])

    def test_different_paper_is_reviewed_instead_of_taking_index_title(self):
        self.pdf(title="A different published paper")
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("REVIEW_TITLE_MISMATCH", result["status"])
        self.assertEqual("A different published paper", result["title"])

    def test_selected_page_scope_records_cover_pages_and_stops_at_header(self):
        self.pdf(covers=2)
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual([1, 2, 3], result["pages_text_extracted"])
        self.assertTrue(result["all_pdf_pages_text_extracted"])
        self.assertFalse(result["full_text_reviewed"])

    def test_eight_page_limit_does_not_claim_an_unread_header(self):
        self.pdf(covers=8)
        result = MODULE.extract(self.path, "Verified research title")
        self.assertEqual("REVIEW_BIBLIOGRAPHIC_HEADER_NOT_FOUND", result["status"])
        self.assertEqual(list(range(1, 9)), result["pages_text_extracted"])
        self.assertFalse(result["all_pdf_pages_text_extracted"])


if __name__ == "__main__":
    unittest.main()
