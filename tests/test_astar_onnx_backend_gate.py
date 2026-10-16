"""A PASS label cannot replace immutable artifacts and numerical verification."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from services import astar_onnx_validation as validation


class OnnxBackendGateTests(unittest.TestCase):
    def fixture(self, root, candidate=None):
        reference = np.zeros((128, 384), dtype=np.float32)
        reference[:, 0] = 1
        candidate = reference.copy() if candidate is None else candidate
        np.save(root / 'reference.npy', reference)
        np.save(root / 'onnx_vectors.npy', candidate)
        (root / 'fixed_samples.json').write_text('[]', encoding='utf-8')
        (root / 'tokenizer.json').write_text('{}', encoding='utf-8')
        (root / 'model.onnx').write_bytes(b'fixture artifact')
        report = {'state': 'PASS', 'sample_count': 128, 'model': 'BAAI/bge-small-en-v1.5',
            'revision': '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a', 'dimension': 384, 'dtype': 'float32',
            'onnx_sha256': '828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35',
            'tokenizer_sha256': validation.digest(root / 'tokenizer.json'),
            'encoder_sha256': validation.digest(Path(validation.__file__).with_name('astar_onnx_encoder.py')),
            'packages': {'numpy': np.__version__}}
        for file, field in [('fixed_samples.json', 'fixed_samples_sha256'), ('reference.npy', 'reference_sha256'),
                            ('onnx_vectors.npy', 'onnx_vectors_sha256')]:
            report[field] = validation.digest(root / file)
        path = root / 'verification.json'
        path.write_text(json.dumps(report), encoding='utf-8')
        original_digest = validation.digest
        def fixture_digest(path):
            return report['onnx_sha256'] if Path(path) == root / 'model.onnx' else original_digest(path)
        return path, fixture_digest

    def test_equivalent_saved_fp32_samples_are_accepted_and_changed_artifacts_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, hashed = self.fixture(root)
            with patch.object(validation, 'digest', side_effect=hashed):
                self.assertEqual(128, validation.validate_receipt(receipt, root / 'model.onnx', root)['sample_count'])
                (root / 'fixed_samples.json').write_text('["changed"]', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'artifact'):
                    validation.validate_receipt(receipt, root / 'model.onnx', root)

    def test_numerically_wrong_saved_vectors_fail_despite_a_pass_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong = np.zeros((128, 384), dtype=np.float32)
            wrong[:, 1] = 1
            receipt, hashed = self.fixture(root, wrong)
            with patch.object(validation, 'digest', side_effect=hashed):
                with self.assertRaisesRegex(ValueError, 'equivalence'):
                    validation.validate_receipt(receipt, root / 'model.onnx', root)

    def test_zero_vectors_cannot_pass_by_nan_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, hashed = self.fixture(root, np.zeros((128, 384), dtype=np.float32))
            with patch.object(validation, 'digest', side_effect=hashed):
                with self.assertRaisesRegex(ValueError, 'normalized'):
                    validation.validate_receipt(receipt, root / 'model.onnx', root)
