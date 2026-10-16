#!/usr/bin/env python3
"""Apply reviewed annual province GDP with before/after evidence and protected-row checks."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.province_gdp_bulletin_service import sync_reviewed_province_gdp, validate_reviewed_province_snapshot, verify_snapshot_file_integrity


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def read_rows(conn, where, parameters=()):
    return [dict(row) for row in conn.execute('SELECT * FROM gdp_region_observations WHERE ' + where + ' ORDER BY id', parameters)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--snapshot-dir', type=Path, default=ROOT / 'data/province_gdp_reviewed')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/macro_refresh_20261013')
    args = parser.parse_args()
    if not args.database.is_file():
        raise ValueError('Refuse to create a replacement database at a missing path.')
    candidates = []
    for path in args.snapshot_dir.glob('*.json'):
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        validate_reviewed_province_snapshot(snapshot)
        candidates.append((snapshot['generated_at'], path, snapshot))
    if not candidates or len({s['statistical_year'] for _, _, s in candidates}) != 1:
        raise ValueError('This bounded activation handles exactly one reviewed statistical year.')
    _, snapshot_path, snapshot = max(candidates, key=lambda item: item[0])
    verify_snapshot_file_integrity(snapshot_path)
    year = str(snapshot['statistical_year'])
    output = args.output_dir / ('province-gdp-activation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    audit_path = output / 'audit.json'
    selected = "country_code='CN' AND region_code LIKE '__0000' AND period=? AND indicator_code IN ('nominal_gdp','real_growth')"
    with closing(sqlite3.connect(str(args.database), timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA busy_timeout=30000')
        before = read_rows(conn, selected, (year,))
        protected_before = read_rows(conn, 'NOT (' + selected + ')', (year,))
        result = {'captured_at': datetime.now().astimezone().isoformat(), 'statistical_year': year,
                  'snapshot': str(snapshot_path), 'snapshot_sha256': hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                  'target_rows_before': before, 'protected_row_count': len(protected_before),
                  'protected_rows_sha256_before': hashlib.sha256(encoded(protected_before)).hexdigest(),
                  'phase': 'reviewed_ready_not_applied', 'apply_requested': args.apply}
        audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if args.apply:
            session = requests.Session()
            session.trust_env = False
            response = session.get('http://127.0.0.1:5001/api/jobs', timeout=15)
            response.raise_for_status()
            payload = response.json()
            jobs = payload.get('jobs', []) if isinstance(payload, dict) else payload
            if isinstance(jobs, dict):
                jobs = list(jobs.values())
            if any(job.get('status') in ('running', 'pending', 'queued') for job in jobs if isinstance(job, dict)):
                raise RuntimeError('An existing update job is active; do not interleave this activation.')
            result['import'] = sync_reviewed_province_gdp(conn, args.snapshot_dir)
            if result['import']['errors']:
                conn.rollback()
                raise ValueError('Reviewed import failed; inspect import errors before continuing.')
            conn.commit()
            after = read_rows(conn, selected, (year,))
            protected_after = read_rows(conn, 'NOT (' + selected + ')', (year,))
            result['target_rows_after'] = after
            result['protected_rows_sha256_after'] = hashlib.sha256(encoded(protected_after)).hexdigest()
            result['protected_rows_unchanged'] = result['protected_rows_sha256_before'] == result['protected_rows_sha256_after']
            expected = {(r['region_code'],r['indicator_code'],r['period']):r['value'] for r in snapshot['observations']}
            actual = {(r['region_code'],r['indicator_code'],r['period']):r['value'] for r in after}
            result['exact_value_readback'] = actual == expected
            result['phase'] = 'applied_readback_verified' if result['protected_rows_unchanged'] and result['exact_value_readback'] else 'applied_verification_failed'
            if result['phase'] == 'applied_readback_verified':
                sources = {s['source_id']:s for s in snapshot['sources']}
                public_rows = []
                for row in snapshot['observations']:
                    source = sources[row['source_id']]
                    public_rows.append({**row, 'source_name':source['source_name'],'source_url':source['source_url'],
                                        'access_type':source['access_type'],
                                        'parser_notes':source.get('access_limit','完整官方HTML原文已归档；年度初步统计/核算。')})
                destination = ROOT / 'static/province-gdp-provenance-2025.json'
                if destination.exists():
                    (output / 'public_provenance_before.json').write_bytes(destination.read_bytes())
                destination.write_text(json.dumps({'schema_version':1,'snapshot_sha256':result['snapshot_sha256'],
                                       'rows':public_rows,'caveats':snapshot['caveats']},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                result['public_provenance'] = str(destination)
                result['public_provenance_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
            audit_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            if result['phase'] != 'applied_readback_verified':
                raise ValueError('Readback/protected-row verification failed; do not claim completion.')
    print(json.dumps({'output_dir':str(output),'phase':result['phase'],'import':result.get('import'),
                      'exact_value_readback':result.get('exact_value_readback'),
                      'protected_rows_unchanged':result.get('protected_rows_unchanged')},ensure_ascii=False))


if __name__ == '__main__':
    main()
