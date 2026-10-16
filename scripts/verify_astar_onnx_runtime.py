#!/usr/bin/env python3
"""Compare an offline ONNX encoder with fixed committed BGE vector samples."""

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import sys
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_semantic_service import _doc_text
from services.system_memory_gate import memory_headroom


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def own_memory():
    if os.name != 'nt':
        return None
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in
            ['peak_working', 'working', 'quota_peak_paged', 'quota_paged', 'quota_peak_nonpaged',
             'quota_nonpaged', 'pagefile', 'peak_pagefile', 'private']]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetCurrentProcess.argtypes = []
    api = ctypes.WinDLL('psapi', use_last_error=True)
    api.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    api.GetProcessMemoryInfo.restype = wintypes.BOOL
    counter = Counters()
    counter.cb = ctypes.sizeof(counter)
    if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'private_bytes': counter.private, 'peak_commit_bytes': counter.peak_pagefile,
            'working_bytes': counter.working, 'peak_working_bytes': counter.peak_working}


def verify(pack, onnx_path, tokenizer_dir, output, sample_count=128, threads=1, batch_size=4):
    import numpy as np
    output.mkdir(parents=True, exist_ok=False)
    official_sha256 = '828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35'
    if digest(onnx_path) != official_sha256:
        raise ValueError('ONNX artifact differs from the pinned official LFS digest')
    manifest = json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))
    ids = np.load(pack / 'astar_emb_ids.npy', mmap_mode='r')
    done = np.load(pack / 'completed.npy', mmap_mode='r')
    quality = np.load(pack / 'title_only_mask.npy', mmap_mode='r')
    matrix = np.load(pack / 'astar_emb.npy', mmap_mode='r')
    eligible = np.flatnonzero((np.asarray(done) == 1) & (np.asarray(ids) > 350117))
    if len(eligible) < sample_count:
        raise ValueError('Not enough committed newly encoded rows for an independent sample')
    chosen = np.sort(np.random.default_rng(20261007).choice(eligible, sample_count, replace=False))
    conn = sqlite3.connect(Path(manifest['db_path']).as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    texts, source_items = [], []
    for position in chosen:
        identifier = int(ids[position])
        row = conn.execute('SELECT title,abstract,is_duplicate FROM astar_articles WHERE id=?', (identifier,)).fetchone()
        if row is None or row['is_duplicate']:
            raise ValueError('A selected sample is no longer an eligible article')
        text = _doc_text(row['title'], None if quality[position] else row['abstract'])
        texts.append(text)
        source_items.append({'article_id': identifier, 'position': int(position),
                             'was_encoded_title_only': bool(quality[position]), 'encoded_text': text})
    conn.close()
    reference = np.asarray(matrix[chosen], dtype=np.float32)
    np.save(output / 'reference.npy', reference)
    with (output / 'fixed_samples.json').open('x', encoding='utf-8') as stream:
        json.dump(source_items, stream, ensure_ascii=False, indent=2)
    while True:
        status = memory_headroom()
        if status is None or (status['commit_available'] >= 1.75 * 2**30 and status['physical_available'] >= 2 * 2**30):
            break
        print(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'state': 'WAITING_MEMORY',
                          'required_commit_gib': 1.75, 'headroom': status}), flush=True)
        time.sleep(30)
    from services.astar_onnx_encoder import OnnxBgeEncoder
    memory_before = own_memory()
    start = time.perf_counter()
    encoder = OnnxBgeEncoder(onnx_path, tokenizer_dir, threads=threads)
    loaded = time.perf_counter()
    vectors = encoder.encode(texts, batch_size=batch_size)
    elapsed = time.perf_counter() - loaded
    np.save(output / 'onnx_vectors.npy', vectors)
    dot = np.sum(reference * vectors, axis=1)
    cosine = dot / (np.linalg.norm(reference, axis=1) * np.linalg.norm(vectors, axis=1))
    difference = np.max(np.abs(reference - vectors), axis=1)
    passed = bool(np.isfinite(vectors).all() and float(cosine.min()) >= 0.99999 and float(difference.max()) <= 0.0001)
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'state': 'PASS' if passed else 'REVIEW_REQUIRED',
        'sample_count': sample_count, 'selection_seed': 20261007, 'model': 'BAAI/bge-small-en-v1.5',
        'revision': '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a', 'onnx_sha256': official_sha256,
        'tokenizer_sha256': digest(tokenizer_dir / 'tokenizer.json'), 'dimension': 384, 'dtype': 'float32',
        'pooling': 'CLS; L2 normalized', 'model_load_seconds': loaded - start,
        'threads': threads, 'batch_size': batch_size,
        'inference_seconds': elapsed, 'docs_per_second': sample_count / elapsed,
        'minimum_cosine': float(cosine.min()), 'maximum_absolute_difference': float(difference.max()),
        'memory_before': memory_before, 'memory_after': own_memory(),
        'packages': {name: importlib.metadata.version(name) for name in ['onnxruntime', 'tokenizers', 'numpy']},
        'script_sha256': digest(__file__), 'fixed_samples_sha256': digest(output / 'fixed_samples.json'),
        'reference_sha256': digest(output / 'reference.npy'), 'onnx_vectors_sha256': digest(output / 'onnx_vectors.npy'),
        'encoder_sha256': digest(ROOT / 'services/astar_onnx_encoder.py'),
        'live_assets_replaced': False, 'production_database_writes': 0, 'pack_checkpoint_writes': 0}
    with (output / 'verification.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    if not passed:
        raise ValueError('The ONNX output does not meet the committed-vector equivalence gate')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pack-dir', type=Path, required=True)
    parser.add_argument('--onnx-model', type=Path, required=True)
    parser.add_argument('--tokenizer-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=128)
    parser.add_argument('--threads', type=int, choices=range(1, 5), default=1)
    parser.add_argument('--batch-size', type=int, choices=[1, 2, 4, 8], default=4)
    args = parser.parse_args()
    print(json.dumps(verify(args.pack_dir.resolve(), args.onnx_model.resolve(), args.tokenizer_dir.resolve(),
                            args.output_dir.resolve(), args.samples, args.threads, args.batch_size), indent=2))
