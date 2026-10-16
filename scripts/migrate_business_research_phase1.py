#!/usr/bin/env python3
"""Apply the additive Business Research Milestone 1 migration safely.

The script never rewrites or deletes the source article cache.  It can make a
file-family backup, rerun the local rules classifier, and rebuild the separate
research-state link/assertion index.  Network retrieval and LLM classification
are intentionally outside this migration.

Example::

    python scripts/migrate_business_research_phase1.py --reclassify --index
    python scripts/migrate_business_research_phase1.py --dry-run
"""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTICLE_DB = ROOT / 'pboc_data.db'
STATE_DB = ROOT / 'data' / 'business_research_state.db'


def _hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _integrity(path):
    conn = sqlite3.connect('file:%s?mode=ro' % path.resolve(), uri=True,
                           timeout=30)
    try:
        quick = conn.execute('PRAGMA quick_check').fetchone()[0]
        foreign = [row[0] for row in conn.execute('PRAGMA foreign_key_check')]
        return {'quick_check': quick, 'foreign_key_errors': len(foreign)}
    finally:
        conn.close()


def _backup_family(path, destination):
    records = []
    for suffix in ('', '-wal', '-shm'):
        source = Path(str(path) + suffix)
        if not source.exists():
            continue
        target = destination / source.name
        shutil.copy2(source, target)
        records.append({
            'source': str(source.resolve()),
            'backup': str(target.resolve()),
            'size': target.stat().st_size,
            'sha256': _hash(target),
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reclassify', action='store_true',
                        help='rerun the deterministic rules classifier in pboc_data.db')
    parser.add_argument('--index', action='store_true',
                        help='create/rebuild the state-db links and assertions')
    parser.add_argument('--dry-run', action='store_true',
                        help='run read-only integrity and row-count checks')
    parser.add_argument('--backup-root', type=Path,
                        default=ROOT / 'backups')
    args = parser.parse_args()
    if not args.dry_run and not (args.reclassify or args.index):
        parser.error('choose --reclassify and/or --index, or use --dry-run')

    before = {
        'article_db': _integrity(ARTICLE_DB),
        'state_db': _integrity(STATE_DB) if STATE_DB.exists() else None,
    }
    result = {
        'started_at': datetime.now().isoformat(timespec='seconds'),
        'article_db': str(ARTICLE_DB.resolve()),
        'state_db': str(STATE_DB.resolve()),
        'before_integrity': before,
        'actions': [],
    }
    if args.dry_run:
        conn = sqlite3.connect(ARTICLE_DB)
        try:
            result['article_rows'] = conn.execute(
                'SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0').fetchone()[0]
        finally:
            conn.close()
        result['dry_run'] = True
        print(json.dumps(result, indent=2))
        return 0

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_dir = args.backup_root / ('business-research-phase1-' + stamp)
    backup_dir.mkdir(parents=True, exist_ok=False)
    result['backup_dir'] = str(backup_dir.resolve())
    result['backup_files'] = (_backup_family(ARTICLE_DB, backup_dir) +
                              _backup_family(STATE_DB, backup_dir))

    if args.reclassify:
        from services.abdc_astar_research_service import reclassify_all
        result['actions'].append({'name': 'reclassify_all',
                                  'result': reclassify_all(str(ARTICLE_DB))})
    if args.index:
        from services.business_research_service import rebuild_link_index
        result['actions'].append({'name': 'rebuild_link_index',
                                  'result': rebuild_link_index(
                                      str(ARTICLE_DB), str(STATE_DB), force=False)})

    result['after_integrity'] = {
        'article_db': _integrity(ARTICLE_DB),
        'state_db': _integrity(STATE_DB),
    }
    result['finished_at'] = datetime.now().isoformat(timespec='seconds')
    manifest = backup_dir / 'manifest.json'
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                        encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('manifest:', manifest)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
