#!/usr/bin/env python3
"""Verify and activate a complete semantic pack, preserving every live asset.

The metadata file is installed last as the reader's generation marker. Existing
files are copied to an immutable backup before replacing generated vector assets.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.stage_astar_history_embeddings import verify
from services.astar_history_service import digest, utc_now, write_new_json


def copy_new(source, target):
    with source.open('rb') as inp, target.open('xb') as out:
        for block in iter(lambda: inp.read(1024 * 1024), b''):
            out.write(block)


def activate(run_dir, pack_dir):
    receipt = verify(pack_dir)
    if (receipt['completed_rows'] != receipt['frozen_target_count'] or
        receipt['duplicate_ids'] or receipt['invalid_or_unnormalized_rows'] or
        receipt['frozen_ids_missing_from_live_database'] or receipt['live_ids_not_yet_in_pack'] or
        receipt.get('title_only_vectors_with_new_abstract', 0) or
        receipt.get('input_fingerprints_missing_or_unknown', receipt['frozen_target_count']) or
        receipt.get('input_fingerprints_changed', 0)):
        raise ValueError('the pack does not cover the complete currently eligible corpus')
    metadata = json.loads((pack_dir / 'astar_emb_meta.json').read_text(encoding='utf-8'))
    if metadata.get('model') != 'BAAI/bge-small-en-v1.5' or metadata.get('dim') != 384:
        raise ValueError('the staged model identity differs from the live semantic service')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = run_dir / 'semantic_activations' / stamp
    (folder / 'before').mkdir(parents=True)
    names = ('astar_emb.npy', 'astar_emb_ids.npy', 'astar_emb_titleonly_ids.npy', 'astar_emb_input_hashes.npy', 'astar_emb_meta.json')
    hashes_before, hashes_after = {}, {}
    prepared = []
    for name in names:
        live = ROOT / 'data' / name
        if live.exists():
            backup = folder / 'before' / name
            copy_new(live, backup)
            hashes_before[name] = digest(backup)
        staged = pack_dir / name
        temporary = ROOT / 'data' / (name + '.history_' + stamp + '.tmp')
        copy_new(staged, temporary)
        prepared.append((temporary, live))
        hashes_after[name] = digest(staged)
    # Generated files are complete before the generation marker changes.
    for temporary, live in prepared:
        os.replace(temporary, live)
    result = {'activated_at': utc_now(), 'pack_dir': str(pack_dir), 'backup_dir': str(folder / 'before'),
              'eligible_count': metadata['count'], 'before_hashes': hashes_before,
              'after_hashes': hashes_after, 'verification': receipt}
    write_new_json(folder / 'activation.json', result)
    return result


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--pack-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(activate(args.run_dir.resolve(), args.pack_dir.resolve()), indent=2))


if __name__ == '__main__':
    main()
