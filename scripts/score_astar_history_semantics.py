#!/usr/bin/env python3
"""Score the newly imported history using the platform's existing semantic profile.

The original baseline classifications are protected. Scores, prior values,
profile identity, pack identity, and application receipts remain in the private
run directory. Only the semantic_relevance column on new eligible records changes.
"""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('USE_TF', '0')
os.environ.setdefault('TRANSFORMERS_NO_TF', '1')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
for thread_variable in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[thread_variable] = '1'

from services.astar_history_service import connect, digest, utc_now, write_new_json
from services.astar_semantic_service import MODEL_NAME, PROFILE_ASPECTS
from scripts.stage_astar_history_embeddings import verify


def apply_scores(db_path, baseline_max_id, pairs):
    """Apply one validated derived generation atomically, excluding all baseline IDs."""
    db = connect(db_path)
    changed = 0
    seen = set()
    try:
        db.execute('BEGIN IMMEDIATE')
        for score, identifier in pairs:
            if identifier <= baseline_max_id or identifier in seen or not math.isfinite(score) or not 0 <= score <= 100:
                raise ValueError('score application contains a protected, duplicate, or invalid row')
            seen.add(identifier)
            result = db.execute('''UPDATE astar_article_classifications SET semantic_relevance=?
                WHERE article_id=? AND article_id>? AND EXISTS (
                    SELECT 1 FROM astar_articles a WHERE a.id=astar_article_classifications.article_id
                    AND a.is_duplicate=0 AND a.title IS NOT NULL)''', (score, identifier, baseline_max_id))
            if result.rowcount != 1:
                raise ValueError(f'new eligible classification {identifier} is unavailable; generation was not applied')
            changed += result.rowcount
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    return changed


def score_pack(run_dir, pack_dir, apply=False):
    import numpy as np
    run_manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    checked = verify(pack_dir)
    if (checked['completed_rows'] != checked['frozen_target_count'] or checked['duplicate_ids'] or
        checked['invalid_or_unnormalized_rows'] or checked['live_ids_not_yet_in_pack'] or
        checked['frozen_ids_missing_from_live_database'] or checked.get('title_only_vectors_with_new_abstract', 0) or
        checked.get('input_fingerprints_missing_or_unknown', checked['frozen_target_count']) or
        checked.get('input_fingerprints_changed', checked['frozen_target_count'])):
        raise ValueError('semantic scoring requires a complete verified pack for the current corpus')
    # Do not allocate the model until document inputs have passed freshness checks.
    import torch
    from sentence_transformers import SentenceTransformer
    meta = json.loads((pack_dir / 'astar_emb_meta.json').read_text(encoding='utf-8'))
    if meta.get('model') != MODEL_NAME or meta.get('dim') != 384:
        raise ValueError('the staged semantic model differs from the platform model')
    baseline = connect(run_manifest['snapshot_path'], readonly=True)
    try:
        baseline_max_id = baseline.execute('SELECT COALESCE(MAX(id),0) FROM astar_articles').fetchone()[0]
    finally:
        baseline.close()
    db_path = Path(run_manifest['db_path'])
    db = connect(db_path, readonly=True)
    try:
        prior = {row['article_id']: row['semantic_relevance'] for row in db.execute('''
            SELECT c.article_id,c.semantic_relevance FROM astar_article_classifications c
            JOIN astar_articles a ON a.id=c.article_id WHERE a.id>? AND a.is_duplicate=0 AND a.title IS NOT NULL
        ''', (baseline_max_id,))}
    finally:
        db.close()
    ids = np.load(pack_dir / 'astar_emb_ids.npy', mmap_mode='r')
    matrix = np.load(pack_dir / 'astar_emb.npy', mmap_mode='r')
    positions = np.flatnonzero(ids > baseline_max_id)
    if {int(ids[p]) for p in positions} != set(prior):
        raise ValueError('new eligible IDs and classification rows do not reconcile')
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.backends.mkldnn.enabled = False
    model = SentenceTransformer(MODEL_NAME, device='cpu', local_files_only=True,
                                model_kwargs={'attn_implementation': 'eager'})
    model_revision = getattr(model[0].auto_model.config, '_commit_hash', None)
    aspects = model.encode(PROFILE_ASPECTS, batch_size=1, normalize_embeddings=True,
                           show_progress_bar=False).astype('float32')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = run_dir / 'semantic_score_runs' / stamp
    folder.mkdir(parents=True)
    csv_path = folder / 'new_record_scores.csv'
    with csv_path.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['article_id', 'semantic_relevance_before', 'semantic_relevance'])
        writer.writeheader()
        for first in range(0, len(positions), 4096):
            chunk_positions = positions[first:first + 4096]
            best = (np.asarray(matrix[chunk_positions]) @ aspects.T).max(axis=1)
            scores = np.round(np.clip(best, 0, 1) * 100, 1)
            for position, score in zip(chunk_positions, scores):
                identifier = int(ids[position])
                writer.writerow({'article_id': identifier, 'semantic_relevance_before': prior[identifier],
                                 'semantic_relevance': float(score)})
    del model
    method = {'created_at': utc_now(), 'pack_dir': str(pack_dir), 'model': MODEL_NAME,
              'model_revision': model_revision,
              'packages': {name: importlib.metadata.version(name) for name in ('torch', 'sentence-transformers', 'transformers', 'numpy')},
              'profile_aspects': PROFILE_ASPECTS, 'score_formula': 'round(clip(max(document cosine profile aspect),0,1)*100,1)',
              'baseline_max_id': baseline_max_id, 'target_records': len(positions),
              'protected_baseline_updated': False, 'script_sha256': digest(__file__),
              'pack_metadata_sha256': digest(pack_dir / 'astar_emb_meta.json'),
              'pack_vectors_sha256': digest(pack_dir / 'astar_emb.npy'),
              'pack_ids_sha256': digest(pack_dir / 'astar_emb_ids.npy'),
              'profile_vectors_sha256': hashlib.sha256(aspects.tobytes()).hexdigest(),
              'score_file_sha256': digest(csv_path), 'applied': False,
              'interpretation': 'existing profile similarity; not construct or human validation'}
    write_new_json(folder / 'method.json', method)
    if apply:
        with csv_path.open(encoding='utf-8', newline='') as stream:
            pairs = ((float(row['semantic_relevance']), int(row['article_id'])) for row in csv.DictReader(stream))
            changed = apply_scores(db_path, baseline_max_id, pairs)
        method.update({'applied': True, 'applied_records': changed, 'applied_at': utc_now()})
        write_new_json(folder / 'application.json', method)
    return {'folder': str(folder), **method}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--pack-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(score_pack(args.run_dir.resolve(), args.pack_dir.resolve(), args.apply), indent=2))


if __name__ == '__main__':
    main()
