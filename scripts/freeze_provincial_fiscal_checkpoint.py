#!/usr/bin/env python3
"""Freeze a verified fiscal cohort without rewriting data or re-fetching originals."""
import argparse
import hashlib
import json
import platform
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.activate_regional_fiscal_snapshot import protected_digest
from scripts.review_province_fiscal_supplement import review_documents


def verify_receipts(applied, replay):
    """Accept a fill-only commit and its exact zero-change replay."""
    for receipt in (applied, replay):
        if (receipt.get('phase') != 'applied_readback_verified'
                or receipt.get('exact_value_readback') is not True
                or receipt.get('protected_rows_unchanged') is not True
                or receipt['import']['updated'] != 0 or receipt['import']['errors']):
            raise ValueError('Verified fill-only activation and replay receipts are required.')
    inserted = applied['import']['inserted']
    if (inserted <= 0 or applied['committed_rows'] != inserted
            or replay['committed_rows'] != 0 or replay['import']['inserted'] != 0
            or applied['target_keys'] != replay['target_keys']):
        raise ValueError('The first commit must add rows and its replay must change nothing.')
    before = {row['id']: row for row in applied['target_rows_before']}
    after = {row['id']: row for row in applied['target_rows_after']}
    if not all(after.get(key) == row for key, row in before.items()):
        raise ValueError('An original target record changed, including metadata or timestamps.')
    return inserted, len(before)


def parse_test_summary(content, kind):
    """Extract a terminal success summary, not a count from an unfinished log."""
    if kind == 'python':
        match = re.search(r'Ran (\d+) tests?\b', content)
        success = re.search(r'^OK\s*$', content, re.MULTILINE) is not None
    elif kind == 'node':
        match = re.search(r'\btests\s+(\d+)', content)
        success = re.search(r'\bfail\s+0\b', content) is not None
    else:
        raise ValueError('Declare Python or Node terminal test output.')
    if not match or not success or re.search(r'FAILED|not ok', content):
        raise ValueError('The declared test log does not establish successful completion.')
    return int(match[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT/'pboc_data.db')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'outputs/macro_refresh_20261015')
    args = parser.parse_args()
    references = {}

    def read(path):
        path = (ROOT/path).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('A checkpoint reference is absent or outside this workspace.')
        content = path.read_bytes()
        references[path.relative_to(ROOT).as_posix()] = {
            'path': path.relative_to(ROOT).as_posix(), 'bytes': len(content),
            'sha256': hashlib.sha256(content).hexdigest()}
        return content

    def load(path):
        return json.loads(read(path).decode('utf-8-sig'))

    spec = load(args.spec)
    cohort_slug=spec.get('cohort_slug','hunan-jiangsu')
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,79}',cohort_slug):
        raise ValueError('Use a short plain cohort name for the new checkpoint directory.')
    review = load(spec['review'])
    applied, replay = load(spec['activation']), load(spec['replay'])
    inserted, preserved_targets = verify_receipts(applied, replay)
    reviewed = load(spec['review_audit'])
    if reviewed['added_observations'] != inserted or reviewed['database_written']:
        raise ValueError('Review and fill-only activation disagree.')
    archives = {}
    for directory in spec['documents_dirs']:
        directory = (ROOT/directory).resolve()
        for record in load(directory/'audit.json')['source_manifest']:
            content = read(directory/record['raw_path'])
            if (hashlib.sha256(content).hexdigest() != record['raw_sha256']
                    or record.get('tls_verified') is not True
                    or record.get('certificate_or_proxy_override', False)):
                raise ValueError('An original source hash or normal verified-HTTPS receipt changed.')
            archives[record['id']] = (directory, record)
    if not args.database.is_file():
        raise ValueError('Never create a substitute production database.')
    with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows_by_year, provenance, _ = review_documents(review, archives, conn)
        new_rows = [row for rows in rows_by_year.values() for row in rows]
        if len(new_rows) != inserted:
            raise ValueError('The original-source reparse no longer produces the committed cohort.')
        table = {row['id']: dict(row) for row in conn.execute('SELECT * FROM regional_fiscal_observations')}
        if any(table.get(row['id']) != row for row in applied['target_rows_after']):
            raise ValueError('A committed target row changed since verified activation.')
        keys = {(row['country_code'], row['government_scope'], row['region_code'], row['indicator_code'], row['period'])
                for row in applied['target_rows_after']}
        protected_count, protected_hash = protected_digest(conn, keys)
        if (protected_count != applied['protected_rows']
                or protected_hash != applied['protected_sha256_before']):
            raise ValueError('Protected non-target rows changed since this cohort was committed.')
        coverage = {row['indicator_code']: row['n'] for row in conn.execute('''
            SELECT indicator_code,COUNT(*) AS n FROM regional_fiscal_observations
            WHERE country_code='CN' AND government_scope='province_total' AND period='2025'
            GROUP BY indicator_code''')}
    for snapshot in reviewed['snapshots']:
        original = read(snapshot['path'])
        if hashlib.sha256(original).hexdigest() != snapshot['sha256']:
            raise ValueError('A reviewed immutable candidate changed.')
        active = read(Path('data/regional_fiscal_reviewed')/Path(snapshot['path']).name)
        if active != original:
            raise ValueError('The active immutable snapshot is not the verified candidate.')
        if snapshot.get('prior_snapshot'):
            read(snapshot['prior_snapshot'])
    ui = load(spec['ui_audit'])
    if (not ui['passed'] or ui['errors'] or not ui['production_ui'] or ui['preview_only']
            or ui['verified_new_observations'] != inserted or not all(c['passed'] for c in ui['checks'])):
        raise ValueError('Successful actual-production UI evidence is required.')
    for path in ui['screenshots'] + spec['source_renders']:
        read(path)
    for path in spec.get('extra_evidence',[]):
        read(path)
    tests = {}
    for item in spec['test_logs']:
        content = read(item['path'])
        text = content.decode('utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        tests[item['kind']] = tests.get(item['kind'], 0) + parse_test_summary(text, item['kind'])
    session = requests.Session()
    session.trust_env = False
    try:
        with session.get('http://127.0.0.1:5001/api/gdp/data', timeout=20) as response:
            response.raise_for_status()
            payload = response.json()
        live = {(r['region_code'], r['indicator_code'], r['period']): r
                for r in payload['regional_fiscal']['rows']
                if r['country_code']=='CN' and r['government_scope']=='province_total'}
        for row in new_rows:
            actual = live.get((row['region_code'], row['indicator_code'], row['period']))
            if not actual or any(actual.get(field) != row[field] for field in
                                 ('value', 'unit', 'data_status', 'source_url', 'parser_notes')):
                raise ValueError('The live API does not match a verified new observation.')
    finally:
        session.close()
    output = args.output_dir/('fiscal-'+cohort_slug+'-checkpoint-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    for path in spec['frozen_files']:
        content = read(path)
        relative = (ROOT/path).resolve().relative_to(ROOT)
        frozen = output/'frozen'/relative
        frozen.parent.mkdir(parents=True, exist_ok=True)
        frozen.write_bytes(content)
        if frozen.read_bytes()!=content:
            raise ValueError('Frozen evidence copy differs from the inspected bytes.')
    audit = {'checked_at': datetime.now(timezone.utc).isoformat(), 'overall_goal_complete': False,
             'status': 'cohort_complete_overall_macro_gaps_remain', 'database_written': False,
             'new_raw_observations': inserted, 'existing_observations_updated': 0,
             'old_target_records_unchanged': preserved_targets, 'regional_fiscal_rows': len(table),
             'protected_rows': protected_count, 'protected_full_field_sha256': protected_hash,
             'coverage_2025_raw': coverage, 'api_new_rows_verified': len(new_rows),
             'ui_checks': len(ui['checks']), 'tests': tests,
             'source_documents': len(review['documents']), 'full_document_reading_claim': False,
             'commercial_or_lgfv_data': False, 'python_version': platform.python_version(),
             'sqlite_version': sqlite3.sqlite_version, 'command': sys.argv,
             'activation': spec['activation'], 'replay': spec['replay'], 'ui_audit': spec['ui_audit'],
             'remaining': spec['remaining']}
    for name, value in [('reading_log.json', provenance), ('decision_log.json', spec['decisions'])]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output/'manifest.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n'
                                             for _, row in sorted(references.items())), encoding='utf-8')
    # Completion is the final marker; an interrupted partial folder is not a checkpoint.
    (output/'completion_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output_dir': str(output), 'references': len(references),
                      'frozen_files': len(spec['frozen_files']), **audit}, ensure_ascii=False))


if __name__ == '__main__':
    main()
