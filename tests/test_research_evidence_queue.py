import json
from pathlib import Path
import tempfile
import unittest

from scripts.build_research_evidence_queue import build_queue


ROOT = Path(__file__).resolve().parents[1]


class ResearchEvidenceQueueTests(unittest.TestCase):
    def test_book_queue_is_blank_but_page_located(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'queue.json'
            payload = build_queue(
                ROOT / 'data' / 'research_catalog.json',
                ROOT / 'data' / 'research_source_text' /
                'management-organization-60-book-scan' / 'chapter_map.json',
                output,
            )
        self.assertEqual(len(payload['chapters']), 60)
        self.assertTrue(all(row['coding']['status'] == 'needs_human_coding'
                            for row in payload['chapters']))
        self.assertTrue(all(row['source']['pdf_page_start'] for row in payload['chapters']))
        self.assertTrue(all('original_scan_required' in row['review_flags']
                            for row in payload['chapters']))
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('"text_path"', serialized)
        self.assertNotIn('input_path', serialized)

    def test_queue_preserves_manual_fields_when_locators_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'queue.json'
            first = build_queue(
                ROOT / 'data' / 'research_catalog.json',
                ROOT / 'data' / 'research_source_text' /
                'management-organization-60-book-scan' / 'chapter_map.json',
                output,
            )
            first['chapters'][0]['coding']['definition'] = 'manual note'
            first['chapters'][0]['evidence'] = [{'kind': 'definition', 'pdf_page': 18}]
            output.write_text(json.dumps(first), encoding='utf-8')
            second = build_queue(
                ROOT / 'data' / 'research_catalog.json',
                ROOT / 'data' / 'research_source_text' /
                'management-organization-60-book-scan' / 'chapter_map.json',
                output,
            )
        self.assertEqual(second['chapters'][0]['coding']['definition'], 'manual note')
        self.assertEqual(second['chapters'][0]['evidence'][0]['pdf_page'], 18)


if __name__ == '__main__':
    unittest.main()
