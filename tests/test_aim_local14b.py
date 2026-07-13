import unittest

from scripts.aim_calibrate_local14b import clean_text, validate_result


class Local14BValidationTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [{'profile_id': 'p1'}]

    def test_clean_text_normalizes_model_lists(self):
        self.assertEqual(clean_text(['United States', 'Canada']), 'United States; Canada')
        self.assertIsNone(clean_text([]))

    def test_validation_drops_nonverbatim_evidence_and_normalizes_scalars(self):
        result = {
            'labels': {
                'research_topics': 'remote work',
                'country': ['United States', 'Canada'],
                'time_range': ['2020', '2021'],
                'evidence_spans': ['exact excerpt', 'paraphrased excerpt'],
                'uncertainty': False,
            },
            'profiles': {
                'p1': {
                    'topic': 110, 'theory': -5, 'method': 50, 'data': 40,
                    'setting': 30, 'opportunity': 20, 'rationale': 'test',
                }
            },
        }
        article = {'abstract': 'This abstract contains an exact excerpt only.'}
        labels, profiles, notes = validate_result(result, article, self.profiles)
        self.assertEqual(labels['research_topics'], ['remote work'])
        self.assertEqual(labels['country'], 'United States; Canada')
        self.assertEqual(labels['time_range'], '2020; 2021')
        self.assertEqual(labels['evidence_spans'], ['exact excerpt'])
        self.assertTrue(labels['uncertainty'])
        self.assertEqual(profiles['p1']['topic'], 100.0)
        self.assertEqual(profiles['p1']['theory'], 0.0)
        self.assertEqual(notes, 'dropped_nonverbatim_evidence=1')


if __name__ == '__main__':
    unittest.main()
