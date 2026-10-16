"""Activation preserves old assets and rejects incomplete source coverage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import activate_astar_semantic_pack as activation


class SemanticPackActivationTests(unittest.TestCase):
    def test_complete_ids_with_late_abstracts_cannot_replace_live_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(activation, 'verify', return_value={
                'completed_rows': 2, 'frozen_target_count': 2,
                'duplicate_ids': 0, 'invalid_or_unnormalized_rows': 0,
                'frozen_ids_missing_from_live_database': 0, 'live_ids_not_yet_in_pack': 0,
                'title_only_vectors_with_new_abstract': 1,
            }):
                with self.assertRaisesRegex(ValueError, 'complete'):
                    activation.activate(root / 'run', root / 'pack')
            self.assertFalse((root / 'run').exists())

    def test_incomplete_corpus_coverage_never_replaces_live_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(activation, 'verify', return_value={
                'completed_rows': 1, 'frozen_target_count': 2,
                'duplicate_ids': 0, 'invalid_or_unnormalized_rows': 0,
                'frozen_ids_missing_from_live_database': 0, 'live_ids_not_yet_in_pack': 1,
            }):
                with self.assertRaisesRegex(ValueError, 'complete'):
                    activation.activate(root / 'run', root / 'pack')
            self.assertFalse((root / 'run').exists())

    def test_validated_pack_keeps_exact_original_assets_in_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'data').mkdir()
            pack = root / 'pack'
            pack.mkdir()
            names = ('astar_emb.npy', 'astar_emb_ids.npy', 'astar_emb_titleonly_ids.npy', 'astar_emb_input_hashes.npy')
            for name in names:
                (root / 'data' / name).write_bytes(b'original-' + name.encode())
                (pack / name).write_bytes(b'new-' + name.encode())
            (root / 'data/astar_emb_meta.json').write_text(json.dumps({'count': 1}), encoding='utf-8')
            (pack / 'astar_emb_meta.json').write_text(json.dumps({'count': 2, 'dim': 384, 'model': 'BAAI/bge-small-en-v1.5'}), encoding='utf-8')
            receipt = {'completed_rows': 2, 'frozen_target_count': 2, 'duplicate_ids': 0,
                       'invalid_or_unnormalized_rows': 0, 'frozen_ids_missing_from_live_database': 0,
                       'live_ids_not_yet_in_pack': 0, 'input_fingerprints_missing_or_unknown': 0,
                       'input_fingerprints_changed': 0}
            with patch.object(activation, 'ROOT', root), patch.object(activation, 'verify', return_value=receipt):
                result = activation.activate(root / 'run', pack)
            backup = Path(result['backup_dir'])
            for name in names:
                self.assertEqual(b'original-' + name.encode(), (backup / name).read_bytes())
                self.assertEqual(b'new-' + name.encode(), (root / 'data' / name).read_bytes())
            self.assertEqual(2, json.loads((root / 'data/astar_emb_meta.json').read_text())['count'])

    def test_unknown_or_changed_inputs_cannot_be_activated_even_with_complete_id_coverage(self):
        for unknown, changed in [(1, 0), (0, 1)]:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt = {'completed_rows': 2, 'frozen_target_count': 2, 'duplicate_ids': 0,
                    'invalid_or_unnormalized_rows': 0, 'frozen_ids_missing_from_live_database': 0,
                    'live_ids_not_yet_in_pack': 0, 'input_fingerprints_missing_or_unknown': unknown,
                    'input_fingerprints_changed': changed}
                with patch.object(activation, 'verify', return_value=receipt):
                    with self.assertRaisesRegex(ValueError, 'complete'):
                        activation.activate(root / 'run', root / 'pack')
                self.assertFalse((root / 'run').exists())


if __name__ == '__main__':
    unittest.main()
