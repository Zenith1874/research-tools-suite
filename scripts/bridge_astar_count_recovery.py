#!/usr/bin/env python3
"""Link a complete rescan's immutable evidence to its failed parent source unit."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_history_service import digest, utc_now, write_new_json


def bridge(parent, recovery, output):
    if not recovery.is_relative_to(parent):
        raise ValueError('Recovery evidence must remain within its parent private run')
    prepared = json.loads((recovery / 'recovery.json').read_text(encoding='utf-8'))
    original_manifest = json.loads((parent / 'manifest.json').read_text(encoding='utf-8'))
    manifest = json.loads((recovery / 'manifest.json').read_text(encoding='utf-8'))
    if prepared['parent_run_dir'] != str(parent) or prepared['parent_manifest_sha256'] != digest(parent / 'manifest.json'):
        raise ValueError('Parent provenance or frozen manifest changed')
    if any(original_manifest[key] != manifest[key] for key in ('from_date', 'to_date', 'snapshot_path', 'snapshot_sha256')):
        raise ValueError('Recovery changes the authorized window or original baseline')
    source = sqlite3.connect((recovery / 'checkpoint.sqlite3').as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    conn = sqlite3.connect(parent / 'checkpoint.sqlite3', timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        units = [dict(row) for row in source.execute('SELECT * FROM units')]
        if len(units) != 1:
            raise ValueError('An independent source recovery must contain one exact journal query')
        unit = units[0]
        records = [dict(row) for row in source.execute('SELECT * FROM records ORDER BY source_id')]
        pages = [dict(row) for row in source.execute('SELECT * FROM pages ORDER BY page')]
        if unit['status'] != 'COMPLETE' or unit['expected_count'] != len(records) or unit['observed_count'] != len(records):
            raise ValueError('The recovered query is not completely and uniquely count-reconciled')
        if not pages or sum(page['row_count'] for page in pages) != len(records):
            raise ValueError('Recovery pagination does not reconcile its complete record census')
        for page in pages:
            path = (recovery / page['path']).resolve()
            if not path.is_relative_to(recovery) or not path.is_file() or digest(path) != page['sha256']:
                raise ValueError('An immutable recovered source page changed')
            if page['expected_count'] != unit['expected_count']:
                raise ValueError('Recovery pages disagree on the advertised source count')
        conn.execute('BEGIN IMMEDIATE')
        before = dict(conn.execute('SELECT * FROM units WHERE unit_key=?', (unit['unit_key'],)).fetchone())
        if before != prepared['parent_unit']:
            raise ValueError('The failed parent unit changed during its independent rescan')
        old = [dict(row) for row in conn.execute('SELECT * FROM records WHERE unit_key=?', (unit['unit_key'],))]
        lookup = {row['source_id']: row for row in records}
        if any(row['source_id'] not in lookup or lookup[row['source_id']]['article_id'] != row['article_id'] for row in old):
            raise ValueError('Recovered census does not preserve all original source-to-article mappings')
        output.mkdir(parents=True, exist_ok=False)
        write_new_json(output / 'parent_unit_before.json', before)
        write_new_json(output / 'parent_records_before.json', old)
        offset = conn.execute('SELECT COALESCE(MAX(page),0) FROM pages WHERE unit_key=?', (unit['unit_key'],)).fetchone()[0]
        fields = ('unit_key', 'source_id', 'article_id', 'disposition', 'publication_year', 'record_type', 'date_precision')
        conn.executemany('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?)',
                         [tuple(row[key] for key in fields) for row in records])
        for page in pages:
            relative = str((recovery / page['path']).resolve().relative_to(parent))
            conn.execute('INSERT INTO pages VALUES(?,?,?,?,?,?,?,?)',
                (unit['unit_key'], offset + page['page'], relative, page['sha256'], page['row_count'],
                 page['expected_count'], page['next_cursor'], page['committed_at']))
        merged_count = conn.execute('SELECT COUNT(*) FROM records WHERE unit_key=?', (unit['unit_key'],)).fetchone()[0]
        if merged_count != unit['expected_count']:
            raise ValueError('The preserved union differs from the verified latest census')
        conn.execute('''UPDATE units SET status='COMPLETE',cursor=?,next_page=?,expected_count=?,
            observed_count=?,not_before=0,error=NULL,updated_at=? WHERE unit_key=?''',
            (unit['cursor'], offset + unit['next_page'], unit['expected_count'],
             before['observed_count'] + unit['observed_count'], utc_now(), unit['unit_key']))
        event = {'recovery_dir': str(recovery), 'parent_previous_expected_count': before['expected_count'],
            'latest_verified_expected_count': unit['expected_count'], 'latest_pass_unique_records': len(records),
            'recovered_pages': len(pages), 'old_source_records_retained': len(old),
            'original_raw_pages_not_overwritten': True, 'fresh_full_rescan_not_a_relaxed_count_guard': True}
        conn.execute('INSERT INTO events(created_at,event,details) VALUES(?,?,?)',
                     (utc_now(), 'verified_source_count_drift_reconciliation', json.dumps(event)))
        conn.commit()
        result = {'finished_at': utc_now(), 'unit_key': unit['unit_key'], 'status': 'COMPLETE',
            'source_census_reconciled': True, 'unique_source_records': merged_count, **event,
            'script_sha256': digest(__file__), 'production_article_database_modified_by_bridge': False}
        write_new_json(output / 'verification.json', result)
        return result
    except BaseException:
        conn.rollback()
        raise
    finally:
        source.close()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-run', type=Path, required=True)
    parser.add_argument('--recovery-run', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        parser.error('Parent checkpoint reconciliation requires explicit --apply')
    print(json.dumps(bridge(args.parent_run.resolve(), args.recovery_run.resolve(), args.output_dir.resolve()), indent=2))
