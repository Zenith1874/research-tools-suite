"""Copied running headers, title geometry and body-text rejection checks."""

import importlib.util
import unittest
from pathlib import Path

import fitz

PATH = Path(__file__).resolve().parents[1] / "scripts" / "prepare_austax_firstpage_metadata.py"
SPEC = importlib.util.spec_from_file_location("austax_headers", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AustaxHeaderTests(unittest.TestCase):
    def test_actual_cover_label_overrides_stale_running_header(self):
        document = fitz.open()
        page = document.new_page()
        page.insert_text((50, 40), 'JOURNAL OF AUSTRALIAN TAXATION (2021) VOL 23(1)', fontsize=9)
        page.insert_text((50, 200), '(2023) Volume 25(1)', fontsize=18)
        year, volume, issue, basis, _ = MODULE.issue_from_front(document)
        self.assertEqual((year, volume, issue), (2023, 25, '1'))
        self.assertEqual(basis, 'cover_body_issue_label')
        document.close()

    def test_title_above_110_points_is_retained(self):
        document = fitz.open();page = document.new_page()
        page.insert_text((50, 40), 'JOURNAL OF AUSTRALIAN TAXATION 2025 VOL 27(3)', fontsize=9)
        page.insert_text((50, 95), 'Complete published title', fontsize=18)
        page.insert_text((50, 160), 'A Author* AND B Author#', fontsize=12)
        page.insert_text((50, 215), 'ABSTRACT', fontsize=12)
        result = MODULE.first_page_fields(page)
        self.assertEqual('Complete published title', result['title'])
        self.assertEqual(['A Author', 'B Author'], result['authors'])
        document.close()

    def test_body_section_is_not_accepted_as_a_paper_title(self):
        document = fitz.open();page = document.new_page()
        page.insert_text((50, 90), 'D. Case studies', fontsize=12)
        page.insert_text((50, 118), 'Body paragraph discusses an existing study.', fontsize=12)
        with self.assertRaises(ValueError):
            MODULE.first_page_fields(page)
        document.close()


if __name__ == '__main__':
    unittest.main()
