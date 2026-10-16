"""BGE uses its actual CLS token rather than mean or pooler embeddings."""

import unittest
import numpy as np

from services.astar_onnx_encoder import normalized_cls


class OnnxEncoderTests(unittest.TestCase):
    def test_only_cls_contributes_and_output_is_float32_unit_length(self):
        values = np.zeros((2, 3, 384), dtype=np.float32)
        values[0, 0, :2] = [3, 4]
        values[1, 0, 2] = 7
        values[:, 1:, :] = 100
        encoded = normalized_cls(values)
        np.testing.assert_allclose(encoded[0, :2], [0.6, 0.8])
        np.testing.assert_allclose(np.linalg.norm(encoded, axis=1), [1, 1])
        self.assertEqual(np.float32, encoded.dtype)
        self.assertEqual(1, encoded[1, 2])

    def test_wrong_dimensions_zero_and_nonfinite_vectors_are_rejected(self):
        for values in [np.zeros((1, 384)), np.zeros((1, 2, 384)), np.zeros((1, 2, 768)),
                       np.full((1, 2, 384), np.nan)]:
            with self.assertRaises(ValueError):
                normalized_cls(values)
