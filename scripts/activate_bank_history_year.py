#!/usr/bin/env python3
"""Activate one source-reconciled bank year, preserving every non-target macro row."""
import argparse
import csv
import hashlib
import json
import math
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_bank_workbook import reviewed_workbook_cells, ROW_LABELS
from services.bank_supervision_snapshot_service import (
    HISTORY_PATH, SNAPSHOT_PATH, SOURCE_IMAGE, SOURCE_NOTE, reviewed_history_rows,
    sync_bank_supervision_snapshot,
)


def validated_year_targets(table, cells):
    """Require the same 13 indicators and all four independently read quarters."""
    year = int(table['year'])
    expected = {(code, f'{year}-{quarter * 3:02d}'): table['values'][code][quarter - 1]
                for code in ROW_LABELS for quarter in range(1, 5)}
    if len(cells) != 52 or len({(c['indicator_code'], c['period']) for c in cells}) != 52:
        raise ValueError('All 52 distinct source cells are required, not a partial year.')
    actual = {(c['indicator_code'], c['period']): c['reported_value'] for c in cells}
    if set(actual) != set(expected):
        raise ValueError('Source cells and reviewed indicator/quarter identities differ.')
    for key, value in expected.items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('An observed finite reviewed value is required; blanks are not zero.')
        if not math.isclose(value, actual[key], abs_tol=1e-9, rel_tol=0):
            raise ValueError('Reviewed value differs from the independently read workbook cell.')
    if any(v is not None for v in table['values'].get('CN_BANK_NSFR', [None] * 4)):
        raise ValueError('This historical contract must not manufacture undisclosed NSFR.')
    return expected


def protected_digest(conn, keys):
    digest, count = hashlib.sha256(), 0
    for row in conn.execute('SELECT * FROM china_macro_observations ORDER BY id'):
        if (row['indicator_code'], row['period']) in keys:
            continue
        digest.update((json.dumps(dict(row), ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':')) + '\n').encode('utf-8'))
        count += 1
    return count, digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--history-path', type=Path, default=HISTORY_PATH)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs/macro_refresh_20261013')
    args = parser.parse_args()
    if not args.db.is_file():
        raise ValueError('Refuse to create a replacement database.')
    archive = json.loads((args.source_dir / 'audit.json').read_text(encoding='utf-8'))
    for source in archive['source_manifest']:
        path = (args.source_dir / source['raw_path']).resolve()
        if not path.is_relative_to(args.source_dir.resolve()):
            raise ValueError('Source path escaped its acquisition run.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['raw_sha256']:
            raise ValueError('Original source bytes no longer match the archive.')
    history_bytes = args.history_path.read_bytes()
    history = json.loads(history_bytes.decode('utf-8'))
    tables = [t for t in history['tables'] if t['year'] == args.year]
    if len(tables) != 1:
        raise ValueError('One independently reviewed source table is required for the year.')
    table = tables[0]
    source = next(s for s in archive['source_manifest'] if s['source_url'] == table['workbook_source_url'])
    image = next(s for s in archive['source_manifest'] if s['source_url'] == table['source_url'])
    if source['raw_sha256'] != table['workbook_sha256'] or image['raw_sha256'] != table['source_raw_sha256']:
        raise ValueError('Reviewed source vintage does not match the archived image/workbook.')
    cells = reviewed_workbook_cells(args.source_dir / source['raw_path'], args.year)
    expected = validated_year_targets(table, cells)
    out = args.output_dir / ('bank-history-activation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    frozen_history, frozen_csv = out / 'reviewed-history-input.json', out / 'reviewed-current-input.csv'
    frozen_history.write_bytes(history_bytes)
    frozen_csv.write_bytes(SNAPSHOT_PATH.read_bytes())
    rows = list(csv.DictReader(frozen_csv.read_text(encoding='utf-8-sig').splitlines()))
    rows.extend(reviewed_history_rows(frozen_history))
    with closing(sqlite3.connect(f'file:{args.db.resolve().as_posix()}?mode=rw', uri=True, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        # The existing writer skips an exact value/source/note match. Verify all
        # non-target snapshot rows match before allowing it to run against production.
        for row in rows:
            key = (row['indicator_code'], row['period'])
            if key in expected:
                continue
            prior = conn.execute('SELECT value,source_url,parser_notes FROM china_macro_observations '
                                 'WHERE indicator_code=? AND period=?', key).fetchone()
            target = (float(row['value']), row.get('source_url') or SOURCE_IMAGE,
                      row.get('parser_notes') or SOURCE_NOTE)
            if prior is None or tuple(prior) != target:
                raise ValueError('A non-target bank row would change; review that expansion separately.')
        count, before = protected_digest(conn, set(expected))
        previous = [dict(row) for row in conn.execute('SELECT * FROM china_macro_observations')
                    if (row['indicator_code'], row['period']) in expected]
        audit = {'phase':'source_reviewed_not_applied', 'year':args.year, 'source_dir':str(args.source_dir),
                 'history_sha256':hashlib.sha256(history_bytes).hexdigest(), 'cells':cells,
                 'target_rows_before':previous, 'protected_rows':count, 'protected_sha256_before':before,
                 'apply_requested':args.apply}
        audit_path = out / 'audit.json'
        audit_path.write_bytes((json.dumps(audit, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        if args.apply:
            session = requests.Session(); session.trust_env = False
            response = session.get('http://127.0.0.1:5001/api/jobs', timeout=15)
            response.raise_for_status(); payload = response.json()
            jobs = payload.get('jobs', []) if isinstance(payload, dict) else payload
            if isinstance(jobs, dict): jobs = list(jobs.values())
            if any(j.get('status') in ('running','queued','pending') for j in jobs if isinstance(j,dict)):
                raise RuntimeError('An update job is active; keep this bounded activation separate.')
            result = sync_bank_supervision_snapshot(conn, frozen_csv, frozen_history)
            after_rows = [dict(row) for row in conn.execute('SELECT * FROM china_macro_observations')
                          if (row['indicator_code'], row['period']) in expected]
            values = {(r['indicator_code'],r['period']):r['value'] for r in after_rows}
            after_count, after_hash = protected_digest(conn, set(expected))
            audit.update(import_result=result, target_rows_after=after_rows,
                         exact_readback=values==expected,
                         protected_sha256_after=after_hash,
                         protected_rows_unchanged=(count==after_count and before==after_hash))
            audit['phase'] = ('applied_verified' if audit['exact_readback'] and audit['protected_rows_unchanged']
                              else 'applied_verification_failed')
            audit_path.write_bytes((json.dumps(audit, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
            if audit['phase'] != 'applied_verified':
                raise ValueError('Readback/preservation check failed.')
    print(json.dumps({'output_dir':str(out), 'phase':audit['phase'], 'year':args.year,
                      'records_changed':audit.get('import_result',{}).get('records_changed'),
                      'protected_rows_unchanged':audit.get('protected_rows_unchanged')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
