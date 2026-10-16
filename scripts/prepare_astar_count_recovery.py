#!/usr/bin/env python3
"""Create an independent count-drift rescan without altering the parent run."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_history_service import digest, utc_now, write_new_json


def prepare(parent, unit_key, output):
    source = sqlite3.connect((parent / 'checkpoint.sqlite3').as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    try:
        unit = source.execute('SELECT * FROM units WHERE unit_key=?', (unit_key,)).fetchone()
        if unit is None or unit['status'] != 'ERROR' or unit['attempts'] < 3 or 'source count changed during pagination:' not in (unit['error'] or ''):
            raise ValueError('Only a terminally failed source-count-drift unit can be rescanned')
        journal = next(row for row in json.loads((parent / 'journals.json').read_text(encoding='utf-8'))
                       if row['history_key'] == unit['journal_key'])
        manifest = json.loads((parent / 'manifest.json').read_text(encoding='utf-8'))
        schemas = [row['sql'] for row in source.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND type IN ('table','index') ORDER BY type DESC")]
        output.mkdir(parents=True, exist_ok=False)
        metadata = {'created_at': utc_now(), 'parent_run_dir': str(parent), 'parent_unit': dict(unit),
            'parent_manifest_sha256': digest(parent / 'manifest.json'), 'script_sha256': digest(__file__),
            'parent_checkpoint_rows_changed': False, 'source_contract_and_date_range_unchanged': True,
            'fresh_source_cursor': '*', 'immutable_baseline_reused': manifest['snapshot_path'],
            'bridge_to_parent_requires_complete_reconciled_rescan': True}
        failed_page = parent / 'raw' / unit_key / f"page_{unit['next_page']:06d}.json.gz"
        if failed_page.exists():
            metadata.update(retained_failed_raw_page=str(failed_page), failed_page_sha256=digest(failed_page))
        write_new_json(output / 'recovery.json', metadata)
        manifest.update(run_dir=str(output), journal_count=1,
            journal_scope='exact original journal selected for independent source-count-drift reconciliation',
            recovery_parent=str(parent), recovery_parent_unit=unit_key)
        write_new_json(output / 'manifest.json', manifest)
        write_new_json(output / 'journals.json', [journal])
        state = sqlite3.connect(output / 'checkpoint.sqlite3')
        try:
            state.execute('PRAGMA journal_mode=WAL')
            for sql in schemas:
                state.execute(sql)
            state.execute('INSERT INTO units(unit_key,journal_key,provider,status,cursor,next_page,observed_count,not_before,attempts) VALUES(?,?,?,?,?,?,?,?,?)',
                          (unit_key, unit['journal_key'], unit['provider'], 'PENDING', '*', 1, 0, 0, 0))
            state.commit()
        finally:
            state.close()
        return {'recovery_dir': str(output), 'journal_title': journal['journal_title'],
            'original_expected_count': unit['expected_count'], 'original_cursor_preserved': unit['cursor'],
            'parent_modified': False, 'source_api_requests': 0}
    finally:
        source.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-run', type=Path, required=True)
    parser.add_argument('--unit-key', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.parent_run.resolve(), args.unit_key, args.output_dir.resolve()), indent=2))
