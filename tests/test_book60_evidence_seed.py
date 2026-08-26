import copy
import unittest
from pathlib import Path
import tempfile

from scripts.build_research_evidence_queue import build_queue
from scripts.seed_book60_evidence import EVIDENCE_UPDATES, apply_updates


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data' / 'research_catalog.json'
CHAPTER_MAP = ROOT / 'data' / 'research_source_text' / 'management-organization-60-book-scan' / 'chapter_map.json'
FIRST_FIVE = {
    theory_id: EVIDENCE_UPDATES[theory_id]
    for theory_id in (
        'affective-events-theory',
        'broaden-and-build-theory',
        'co-evolution-theory',
        'cognitive-appraisal-theory',
        'cognitive-dissonance-theory',
    )
}


class Book60EvidenceSeedTests(unittest.TestCase):
    def _queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            return build_queue(CATALOG, CHAPTER_MAP, Path(tmp) / 'queue.json')

    def test_first_five_updates_are_page_located_and_not_verified(self):
        payload = self._queue()
        changed = apply_updates(payload, FIRST_FIVE)

        self.assertEqual(len(changed), 5)
        self.assertEqual(sum(item['evidence_added'] for item in changed), 38)
        coded = [row for row in payload['chapters']
                 if row['coding']['status'] == 'partially_human_coded']
        self.assertEqual(len(coded), 5)
        self.assertTrue(all(
            entry['source_check'] == 'checked_against_original'
            for row in coded for entry in row['evidence']))
        self.assertTrue(all(
            'primary_source_crosscheck_required' in row['review_flags']
            and 'partial_human_coding' in row['review_flags']
            for row in coded))
        self.assertTrue(all(
            row['coding']['status'] != 'verified' for row in coded))

    def test_all_seed_updates_target_distinct_book_chapters(self):
        payload = self._queue()
        changed = apply_updates(payload, EVIDENCE_UPDATES)

        self.assertEqual(len(changed), 35)
        self.assertEqual(sum(item['evidence_added'] for item in changed), 330)
        self.assertEqual(
            {row['theory_id'] for row in payload['chapters']
             if row['coding']['status'] == 'partially_human_coded'},
            set(EVIDENCE_UPDATES),
        )

    def test_seed_is_idempotent_and_preserves_existing_coding(self):
        payload = self._queue()
        row = next(item for item in payload['chapters']
                   if item['theory_id'] == 'affective-events-theory')
        row['coding']['definition'] = 'user-entered definition'
        first = apply_updates(payload, FIRST_FIVE)
        snapshot = copy.deepcopy(payload)
        second = apply_updates(payload, FIRST_FIVE)

        self.assertEqual(first, [
            {'theory_id': theory_id, 'evidence_added': len(update['evidence'])}
            for theory_id, update in FIRST_FIVE.items()
        ])
        self.assertEqual(sum(item['evidence_added'] for item in second), 0)
        self.assertEqual(row['coding']['definition'], 'user-entered definition')
        self.assertEqual(payload, snapshot)


if __name__ == '__main__':
    unittest.main()
