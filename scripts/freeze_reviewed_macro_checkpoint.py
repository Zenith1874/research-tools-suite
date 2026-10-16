#!/usr/bin/env python3
"""Freeze a reviewed China-macro cohort after actual source, DB, test and page acceptance."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import platform
import re
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.activate_bank_history_year import protected_digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-base', type=Path, default=ROOT / 'outputs/macro_refresh_20261015')
    args = parser.parse_args()

    def local(path):
        path = (ROOT / path).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Keep checkpoint sources inside the declared workspace.')
        return path

    def load(path):
        return json.loads(local(path).read_text(encoding='utf-8-sig'))

    spec = load(args.spec)
    if spec.get('schema_version') != 1:
        raise ValueError('Unknown reviewed-cohort checkpoint schema.')
    activation, replay, ui = (load(spec[name]) for name in ('activation_audit', 'replay_audit', 'ui_audit'))
    for record in (activation, replay):
        if record.get('phase') != 'applied_readback_verified' or not record.get('protected_unchanged'):
            raise ValueError('A complete successful production receipt is required.')
    expected_committed = spec.get('expected_committed_rows', spec.get('expected_new_values'))
    if activation['committed_rows'] != expected_committed or replay['committed_rows'] != 0:
        raise ValueError('Actual activation/idempotence differs from this reviewed cohort.')
    checks = {row['name']: row for row in ui['checks']}
    if (ui.get('status') != 'passed' or not all(row['pass'] for row in ui['checks'])
            or not set(spec['required_ui_checks']) <= set(checks)):
        raise ValueError('The actual-page acceptance lacks required cohort checks.')
    tests = []
    for requirement in spec['test_logs']:
        content = local(requirement['path']).read_bytes()
        text = content.decode('utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')
        if any(not re.search(pattern, text, re.M) for pattern in requirement['required_patterns']):
            raise ValueError('A required final test result is missing: ' + requirement['path'])
        tests.append({'kind': requirement['kind'], 'passed': requirement['expected_count'], 'path': requirement['path']})
    if hashlib.sha256(local(spec['parser_source']).read_bytes()).hexdigest() != activation['parser_sha256']:
        raise ValueError('The source parser changed after activation; review before freezing.')

    supporting = []
    for requirement in spec.get('supporting_cohorts', []):
        added, unchanged = load(requirement['activation_audit']), load(requirement['replay_audit'])
        if (added.get('phase') != 'applied_readback_verified' or not added.get('protected_unchanged')
                or unchanged.get('committed_rows') != 0 or not unchanged.get('protected_unchanged')):
            raise ValueError('A supporting activation lacks successful/idempotent receipts.')
        if hashlib.sha256(local(requirement['parser_source']).read_bytes()).hexdigest() != added['parser_sha256']:
            raise ValueError('The original supporting parser identity is not preserved.')
        supporting.append((requirement, added, unchanged))
    expected = activation['expected_rows']
    all_expected = expected + [row for _, added, _ in supporting for row in added['expected_rows']]
    keys = {(row['indicator_code'], row['period']) for row in expected}
    with closing(sqlite3.connect(local(args.database).as_uri() + '?mode=ro', uri=True, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row; conn.execute('BEGIN')
        signature = protected_digest(conn, keys)
        if list(signature) != activation['protected_before']:
            raise ValueError('An old non-target macro record changed since activation.')
        current = []
        for row in all_expected:
            actual = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                       (row['indicator_code'], row['period'])).fetchone())
            if any(actual.get(name) != value for name, value in row.items()):
                raise ValueError('A committed value or provenance field changed.')
            current.append(actual)
    with closing(requests.Session()) as session:
        session.trust_env = False
        response = session.get('http://127.0.0.1:5001/api/china-macro/data', timeout=40, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError('Actual local API is unavailable.')
        payload = response.json()
    for row in all_expected:
        actual = next(item for item in payload['series'][row['indicator_code']] if item['period'] == row['period'])
        if any(actual.get(name) != row.get(name) for name in ('value', 'unit', 'frequency', 'data_status', 'source_url', 'release_date', 'retrieved_at')):
            raise ValueError('The running API does not expose a committed cohort value.')

    csv_check = None
    if spec.get('csv_repair'):
        rule = spec['csv_repair']
        with local(rule['before']).open(encoding='utf-8-sig', newline='') as handle:
            old_csv = list(csv.DictReader(handle))
        with local(rule['after']).open(encoding='utf-8-sig', newline='') as handle:
            new_csv = list(csv.DictReader(handle))
        key = lambda row: (row['indicator_code'], row['period'])
        if [key(row) for row in old_csv] != [key(row) for row in new_csv]:
            raise ValueError('The seed CSV row set/order changed outside the approved correction.')
        differences = [(old, new) for old, new in zip(old_csv, new_csv) if old != new]
        expected_csv = {(item['indicator_code'], item['period']): item for item in rule['repairs']}
        if {key(old) for old, _ in differences} != set(expected_csv):
            raise ValueError('The seed CSV has unapproved or missing row changes.')
        for old, new in differences:
            approved = expected_csv[key(old)]
            if (float(old['value']) != approved['old'] or float(new['value']) != approved['new']
                    or any(old[name] != new[name] for name in old if name not in ('value', 'parser_notes'))):
                raise ValueError('A seed CSV correction changed an unapproved value or column.')
        csv_check = {'status': 'passed', 'rows': len(old_csv), 'approved_changes': len(differences),
                     'non_target_rows_unchanged': True, 'row_order_unchanged': True}

    output = local(args.output_base) / ('macro-cohort-checkpoint-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    references = {}

    def add(path, role, freeze=False):
        path = local(path); data = path.read_bytes(); relative = path.relative_to(ROOT).as_posix()
        record = {'path': relative, 'role': role, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if freeze:
            destination = output / 'frozen' / relative; destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise ValueError('A frozen checkpoint cannot be overwritten.')
            shutil.copy2(path, destination); record['frozen_path'] = destination.relative_to(output).as_posix()
        references[relative] = record

    add(args.spec, 'reviewed_checkpoint_spec', True)
    for path in spec['frozen_files']:
        add(path, 'frozen_code_definition_or_status', True)
    for path in (spec['activation_audit'], spec['replay_audit'], spec['ui_audit']):
        add(path, 'successful_acceptance')
    for requirement, _, _ in supporting:
        for name in ('activation_audit', 'replay_audit', 'parser_source'):
            add(requirement[name], 'supporting_completed_cohort')
    for row in spec['test_logs']:
        add(row['path'], 'final_test_receipt')
    for path in spec.get('additional_references', []):
        add(path, 'retained_prior_attempt')
    for path in ui['screenshots']:
        add(path, 'visually_reviewed_actual_page')
    for path in ui.get('exports', []):
        add(path, 'actual_page_export')
    all_sources = activation['sources'] + [source for _, added, _ in supporting for source in added['sources']]
    for source in all_sources:
        raw = local(source['raw_path'])
        if hashlib.sha256(raw.read_bytes()).hexdigest() != source['raw_sha256']:
            raise ValueError('An original source archive changed.')
        add(raw, 'original_source_bytes')
        governing = None
        for parent in raw.parents:
            if not parent.is_relative_to(ROOT):
                break
            candidate = parent / 'audit.json'
            if not candidate.is_file():
                continue
            for record in load(candidate).get('source_manifest', []):
                if (record.get('source_url') == source['source_url'] and record.get('raw_sha256') == source['raw_sha256']
                        and (parent / record['raw_path']).resolve() == raw):
                    governing = candidate
                    break
            if governing:
                break
        if governing is None:
            raise ValueError('No original source manifest binds this exact URL/file/hash.')
        add(governing, 'original_source_manifest')

    def write(name, data):
        with (output / name).open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2); handle.write('\n')

    write('reading_log.json', {'scope': spec['reading_scope'], 'sources': all_sources,
                              'screenshots_visually_reviewed': ui['screenshots'], 'source_requests_by_freeze': 0})
    write('decision_log.json', spec['decisions'])
    write('records_after.json', current)
    if csv_check:
        write('seed_csv_verification.json', csv_check)
    codes = sorted({row['indicator_code'] for row in all_expected})
    completion = {'status': 'verified_cohort_broad_macro_goal_open', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
                  'cohort': spec['cohort'], 'committed_observations': activation['committed_rows'],
                  'new_effective_values': activation['inserted_keys'] + activation['filled_null_values'],
                  'supporting_new_values': sum(added['inserted_keys'] + added['filled_null_values'] for _, added, _ in supporting),
                  'corrected_existing_rows': activation.get('corrected_existing_rows', 0),
                  'total_verified_observations': len(all_expected),
                  'inserted_keys': activation['inserted_keys'], 'filled_null_values': activation['filled_null_values'],
                  'indicator_count': len(codes), 'final_replay_changes': 0, 'protected_old_rows': list(signature),
                  'current_api_coverage': {code: payload['data_quality']['indicators'][code] for code in codes},
                  'tests': tests, 'live_ui_passed': len(ui['checks']), 'whole_repository_claim': False,
                  'database_opened_read_only': True, 'database_writes_by_freeze': 0, 'source_requests': 0, 'loopback_requests': 1,
                  'new_resident_backend_runtime_verified': False, 'remaining': spec['remaining'],
                  'unrecoverable': spec.get('unrecoverable', []),
                  'versions': {'python': platform.python_version(), 'requests': importlib.metadata.version('requests')},
                  'command': ['python', '-X', 'utf8', 'scripts/freeze_reviewed_macro_checkpoint.py', *sys.argv[1:]],
                  'output_dir': output.relative_to(ROOT).as_posix()}
    write('completion_audit.json', completion)
    write('manifest.json', {'references': list(references.values()), 'generated': [
        {'path': path.name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in output.iterdir() if path.is_file()]})
    for record in references.values():
        if hashlib.sha256(local(record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('An evidence reference changed during freeze.')
        if record.get('frozen_path') and hashlib.sha256((output / record['frozen_path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Frozen evidence readback failed.')
    for record in load(output / 'manifest.json')['generated']:
        if hashlib.sha256((output / record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Generated checkpoint readback failed.')
    write('manifest_verification.json', {'status': 'passed', 'references_checked': len(references),
                                       'frozen_files': sum(bool(row.get('frozen_path')) for row in references.values())})
    print(json.dumps({'output_dir': str(output), 'status': completion['status'], 'references': len(references),
                      'new_values': completion['new_effective_values'] + completion['supporting_new_values'],
                      'corrected_existing_rows': completion['corrected_existing_rows'],
                      'verified_observations': len(all_expected), 'indicators': len(codes)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
