#!/usr/bin/env python3
"""Verify YueDu FM local files against the auditable library manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHUNK_BYTES = 4 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description='核对悦读FM目录、大小和 SHA-256')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data' / 'yuedu_fm')
    parser.add_argument('--quick', action='store_true', help='只核对目录和大小，不重新计算 SHA-256')
    args = parser.parse_args()
    library_path = args.data_dir / 'library.json'
    try:
        library = json.loads(library_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False, indent=2))
        return 1

    episodes = library.get('episodes') or []
    failures = []
    seen = set()
    counts = {'episodes': len(episodes), 'audio': 0, 'images': 0, 'metadata': 0,
              'signature_valid': 0, 'signature_invalid': 0,
              'declared_size_mismatch': 0, 'hashes_checked': 0}
    sizes = {'audio': 0, 'images': 0}
    for episode in episodes:
        episode_id = episode.get('episode_id', '')
        if episode_id in seen:
            failures.append({'episode_id': episode_id, 'kind': 'metadata', 'error': 'duplicate id'})
        seen.add(episode_id)
        metadata = args.data_dir / 'metadata' / f'{episode_id}.json'
        counts['metadata'] += int(metadata.is_file())
        if not metadata.is_file():
            failures.append({'episode_id': episode_id, 'kind': 'metadata', 'error': 'missing'})
        for kind, count_key, size_key in (('audio', 'audio', 'audio'), ('image', 'images', 'images')):
            asset = episode.get(kind) or {}
            path = args.data_dir / str(asset.get('relative_path') or '')
            if not path.is_file():
                failures.append({'episode_id': episode_id, 'kind': kind, 'error': 'missing'})
                continue
            counts[count_key] += 1
            actual_size = path.stat().st_size
            sizes[size_key] += actual_size
            expected_size = int(asset.get('actual_bytes') or 0)
            if expected_size != actual_size:
                failures.append({'episode_id': episode_id, 'kind': kind,
                                 'error': f'size {actual_size} != {expected_size}'})
            expected_hash = str(asset.get('sha256') or '')
            if not args.quick and expected_hash:
                counts['hashes_checked'] += 1
                if sha256_file(path) != expected_hash:
                    failures.append({'episode_id': episode_id, 'kind': kind, 'error': 'sha256 mismatch'})
        if episode.get('audio', {}).get('signature_valid') is True:
            counts['signature_valid'] += 1
        elif episode.get('audio', {}).get('signature_valid') is False:
            counts['signature_invalid'] += 1
        if episode.get('audio', {}).get('declared_size_matches') is False:
            counts['declared_size_mismatch'] += 1

    part_files = sorted(str(path.relative_to(args.data_dir))
                        for path in args.data_dir.rglob('*.part'))
    if part_files:
        failures.append({'kind': 'partial_files', 'error': part_files[:20]})
    result = {
        'ok': not failures,
        'mode': 'quick' if args.quick else 'full_sha256',
        'counts': counts,
        'sizes': {'audio_bytes': sizes['audio'], 'image_bytes': sizes['images'],
                  'total_media_bytes': sizes['audio'] + sizes['images']},
        'failures': failures[:100],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
