from pathlib import Path
import tempfile
import unittest

import fitz

from scripts.extract_research_source_text import extract_pdf


class ResearchSourceTextTests(unittest.TestCase):
    def test_embedded_text_extraction_is_page_addressable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / 'demo.pdf'
            document = fitz.open()
            page = document.new_page()
            page.insert_textbox(
                (72, 72, 500, 800),
                ('Theory definition and construct note\n' * 30),
            )
            document.save(pdf_path)
            document.close()

            manifest = extract_pdf(pdf_path, root / 'out')
            text_path = root / 'out' / 'demo' / 'pages' / 'page-0001.txt'
            self.assertEqual(manifest['status'], 'complete')
            self.assertEqual(manifest['page_count'], 1)
            self.assertTrue(text_path.exists())
            self.assertIn('Theory definition', text_path.read_text(encoding='utf-8'))

    def test_empty_text_layer_is_not_called_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / 'empty.pdf'
            document = fitz.open()
            document.new_page()
            document.save(pdf_path)
            document.close()

            manifest = extract_pdf(pdf_path, root / 'out')

        self.assertEqual(manifest['status'], 'text_layer_missing')
        self.assertEqual(manifest['nonempty_pages'], 0)


if __name__ == '__main__':
    unittest.main()
