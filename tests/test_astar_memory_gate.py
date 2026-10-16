"""Resource-pressure interruption is explicit and leaves checkpoint ownership to caller."""

import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from services.system_memory_gate import require_headroom
from scripts.run_astar_embeddings_with_memory_gate import run


class MemoryGateTests(unittest.TestCase):
    def test_low_commit_headroom_raises_before_a_new_batch(self):
        with patch('services.system_memory_gate.memory_headroom', return_value={'commit_available': 512 * 2**20}):
            with self.assertRaisesRegex(MemoryError, 'checkpoint threshold'):
                require_headroom()

    def test_available_commit_headroom_passes(self):
        status = {'commit_available': 2 * 2**30}
        with patch('services.system_memory_gate.memory_headroom', return_value=status):
            self.assertEqual(status, require_headroom())

    def test_unavailable_non_windows_measurement_does_not_fake_zero(self):
        with patch('services.system_memory_gate.memory_headroom', return_value=None):
            self.assertIsNone(require_headroom())

    def test_wrapper_forwards_and_records_the_verified_cpu_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'new_run'
            status = {'commit_available': 4 * 2**30, 'physical_available': 4 * 2**30}
            with patch('scripts.run_astar_embeddings_with_memory_gate.memory_headroom', return_value=status), \
                    patch('scripts.run_astar_embeddings_with_memory_gate.subprocess.Popen') as popen:
                popen.return_value.pid = 1234
                popen.return_value.wait.return_value = 0
                result = run(root / 'history', root / 'pack', output, encoder_backend='onnx',
                             onnx_model=root / 'model.onnx', tokenizer_dir=root / 'tokenizer',
                             backend_validation=root / 'verified.json', threads=4, batch_size=8)
            self.assertEqual('COMPLETE', result['state'])
            arguments = popen.call_args.args[0]
            self.assertEqual('4', arguments[arguments.index('--threads') + 1])
            self.assertEqual('8', arguments[arguments.index('--batch-size') + 1])
            self.assertEqual(str(root / 'verified.json'), arguments[arguments.index('--backend-validation') + 1])
            self.assertEqual('1', popen.call_args.kwargs['env']['OPENBLAS_NUM_THREADS'])
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual((4, 8), (manifest['threads'], manifest['batch_size']))
