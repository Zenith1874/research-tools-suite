"""Require a reproducible numerical equivalence proof before pack encoding."""

import hashlib
import importlib.metadata
import json
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def validate_receipt(receipt_path, onnx_model, tokenizer_dir):
    import numpy as np
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if (receipt.get('state') != 'PASS' or receipt.get('sample_count', 0) < 128
            or receipt.get('model') != 'BAAI/bge-small-en-v1.5'
            or receipt.get('revision') != '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'
            or receipt.get('dimension') != 384 or receipt.get('dtype') != 'float32'):
        raise ValueError('Missing or incompatible ONNX numerical equivalence proof')
    if (digest(onnx_model) != receipt.get('onnx_sha256')
            or receipt.get('onnx_sha256') != '828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35'
            or digest(Path(tokenizer_dir) / 'tokenizer.json') != receipt.get('tokenizer_sha256')
            or digest(Path(__file__).with_name('astar_onnx_encoder.py')) != receipt.get('encoder_sha256')):
        raise ValueError('ONNX model/tokenizer/encoder differs from the verified artifacts')
    for package, version in receipt['packages'].items():
        if importlib.metadata.version(package) != version:
            raise ValueError('A verified runtime package changed')
    for name, field in [('fixed_samples.json', 'fixed_samples_sha256'), ('reference.npy', 'reference_sha256'),
                        ('onnx_vectors.npy', 'onnx_vectors_sha256')]:
        if digest(receipt_path.parent / name) != receipt.get(field):
            raise ValueError('A numerical validation artifact changed')
    reference = np.load(receipt_path.parent / 'reference.npy', allow_pickle=False)
    candidate = np.load(receipt_path.parent / 'onnx_vectors.npy', allow_pickle=False)
    if reference.shape != (receipt['sample_count'], 384) or reference.shape != candidate.shape:
        raise ValueError('Numerical validation sample shapes differ')
    if reference.dtype != np.float32 or candidate.dtype != np.float32:
        raise ValueError('Numerical validation must use the verified FP32 representation')
    if not np.isfinite(reference).all() or not np.isfinite(candidate).all():
        raise ValueError('Numerical validation vectors are nonfinite')
    reference_norms = np.linalg.norm(reference, axis=1)
    candidate_norms = np.linalg.norm(candidate, axis=1)
    if (np.abs(reference_norms - 1) > 1e-3).any() or (np.abs(candidate_norms - 1) > 1e-3).any():
        raise ValueError('Numerical validation vectors are not normalized')
    cosine = np.sum(reference * candidate, axis=1) / (reference_norms * candidate_norms)
    if float(cosine.min()) < 0.99999 or float(np.max(np.abs(reference - candidate))) > 0.0001:
        raise ValueError('ONNX numerical equivalence gate failed on the saved vectors')
    return {'receipt_path': str(receipt_path), 'receipt_sha256': digest(receipt_path),
            'minimum_cosine': float(cosine.min()), 'sample_count': receipt['sample_count'],
            'onnx_sha256': receipt['onnx_sha256'], 'tokenizer_sha256': receipt['tokenizer_sha256'],
            'encoder_sha256': receipt['encoder_sha256']}
