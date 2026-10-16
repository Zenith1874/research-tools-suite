#!/usr/bin/env python3
"""Freeze the completed city employment supplement using read-only DB/API checks."""
import argparse
import hashlib
import json
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
    parser.add_argument('--activation', type=Path, required=True)
    parser.add_argument('--flag-repair', type=Path, required=True)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--ui-audit', type=Path, required=True)
    parser.add_argument('--python-log', type=Path, required=True)
    parser.add_argument('--node-log', type=Path, required=True)
    parser.add_argument('--review', type=Path, default=ROOT / 'data/nbs_31city_history_review_20261015.json')
    parser.add_argument('--database', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-base', type=Path, default=ROOT / 'outputs/macro_refresh_20261015')
    args = parser.parse_args()

    def local(path):
        path = (ROOT / path).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Checkpoint inputs must stay in this workspace.')
        return path

    def load(path):
        return json.loads(local(path).read_text(encoding='utf-8-sig'))

    def text_log(path):
        content = local(path).read_bytes()
        return content.decode('utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')

    activation, flag, replay, ui = map(load, (args.activation, args.flag_repair, args.replay, args.ui_audit))
    if (activation['committed_rows'] != 11 or len(activation['old_missing']) != 1
            or flag['metadata_flags_cleared'] != 1 or replay['committed_rows'] != 0
            or replay['metadata_flags_cleared'] != 0 or not all(row['protected_unchanged'] for row in (activation, flag, replay))):
        raise ValueError('Successful value, own-flag repair and final no-op receipts are required.')
    if ui['status'] != 'passed' or len(ui['checks']) != 23 or not all(row['pass'] for row in ui['checks']):
        raise ValueError('Actual-page acceptance is incomplete.')
    if not re.search(r'Ran 216 tests\b', text_log(args.python_log)) or not re.search(r'^OK\s*$', text_log(args.python_log), re.M):
        raise ValueError('The current 216-test related Python result is missing.')
    if not re.search(r'pass 14\b', text_log(args.node_log)) or not re.search(r'fail 0\b', text_log(args.node_log)):
        raise ValueError('The current 14-test Node chart result is missing.')
    expected = activation['expected_rows']; code = 'CN_UNEMP_31_CITIES'
    keys = {(code, row['period']) for row in expected}
    with closing(sqlite3.connect(local(args.database).as_uri() + '?mode=ro', uri=True, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row; conn.execute('BEGIN')
        protected = protected_digest(conn, keys)
        if list(protected) != activation['protected_before']:
            raise ValueError('A previously protected macro record changed after activation.')
        actual = []
        for row in expected:
            current = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?', (code, row['period'])).fetchone())
            if (any(current.get(field) != row.get(field) for field in row)
                    or current['missing_reason'] is not None or current['data_status'] != 'official'):
                raise ValueError('A committed value, source date, hash or current missing flag differs.')
            actual.append(current)
        placeholder = next(row for row in actual if row['period'] == '2022-04')
        if placeholder['original_value'] != 5.8 or placeholder['value'] != 6.7:
            raise ValueError('The original wrong-period value was not preserved separately.')
    with closing(requests.Session()) as session:
        session.trust_env = False
        response = session.get('http://127.0.0.1:5001/api/china-macro/data', timeout=40, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError('Actual local China API is unavailable.')
        payload = response.json()
    quality = payload['data_quality']['indicators'][code]
    if (quality['n_obs'] != 96 or quality['start_period'] != '2018-01' or quality['end_period'] != '2026-08'
            or quality['missing_periods'] != [str(year) + '-01' for year in range(2019, 2027)]):
        raise ValueError('Current actual API coverage differs from the verified employment history.')
    for row in expected:
        exposed = next(value for value in payload['series'][code] if value['period'] == row['period'])
        if any(exposed[field] != row[field] for field in ('value', 'source_url', 'release_date', 'retrieved_at')):
            raise ValueError('The running API differs from a committed value or provenance field.')

    output = local(args.output_base) / ('city-survey-checkpoint-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    references = {}

    def add(path, role, freeze=False):
        path = local(path); relative = path.relative_to(ROOT).as_posix()
        data = path.read_bytes()
        record = {'path': relative, 'role': role, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if freeze:
            target = output / 'frozen' / relative; target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError('Never overwrite a checkpoint copy.')
            shutil.copy2(path, target); record['frozen_path'] = target.relative_to(output).as_posix()
        references[relative] = record

    for path in ('README.md', 'docs/macro_city_employment_STATUS_2026-10-15.md',
                 'services/china_macro_service.py', 'services/china_macro_extended_service.py',
                 'services/nbs_release_evidence.py', 'scripts/activate_city_survey_history.py',
                 'scripts/freeze_city_survey_checkpoint.py', 'scripts/verify_city_survey_history_live.js',
                 'tests/test_macro_completeness.py', 'tests/test_city_survey_history.py', 'tests/test_city_survey_activation.py',
                 'data/nbs_31city_history_sources_a_20261015.json', 'data/nbs_31city_history_sources_b_20261015.json',
                 'data/nbs_31city_history_review_20261015.json'):
        add(path, 'frozen_code_definition_or_status', True)
    config = load(args.review)
    for reviewed in config['sources']:
        parent = local(Path(reviewed['archive']) / 'audit.json'); source_manifest = load(parent)['source_manifest']
        source = next(row for row in source_manifest if row['source_url'] == reviewed['source_url'])
        raw = local(Path(reviewed['archive']) / source['raw_path'])
        if hashlib.sha256(raw.read_bytes()).hexdigest() != source['raw_sha256']:
            raise ValueError('Original source changed while freezing.')
        add(parent, 'original_source_manifest'); add(raw, 'original_source_bytes')
    for path in (args.activation, args.flag_repair, args.replay, args.ui_audit, args.python_log, args.node_log):
        add(path, 'completed_current_verification')
    for path in ui['screenshots']:
        add(path, 'visually_reviewed_actual_chart')
    add(str(args.ui_audit).replace('-audit.json', '-april2022.csv'), 'actual_page_csv')
    add('outputs/macro_refresh_20261015/gacc-detail-native-20261015-120400/receipt-attempt2.json', 'retained_customs_certificate_failure')
    add('output/playwright/capture-gacc-current-catalog-20261015-120400.js', 'initial_recorder_failure_code', True)
    add('output/playwright/capture-gacc-current-catalog-20261015-120700.js', 'successful_failure_recorder_code', True)

    def write(name, data):
        with (output / name).open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2); handle.write('\n')

    write('reading_log.json', {'reading_scope': 'Employment paragraphs, titles, reporting-period captions and original date metadata only; not all economic tables or charts.',
          'sources_reviewed': activation['sources'], 'new_source_files': 8, 'new_source_bytes': 8297472,
          'existing_first_quarter_source_reused': True, 'source_reacquisitions_for_checkpoint': 0,
          'screenshots_visually_reviewed': ui['screenshots']})
    write('decision_log.json', ['Keep national and 31-city series separate.',
          'Read the three explicitly listed January-March rates; never split a quarterly average.',
          'Ignore previous-month comparison anchors and migrated URL dates.',
          'Fill only missing values, freeze the invalidated NULL row and retain original_value=5.8 separately.',
          'Clear one own stale missing flag only under identical code-version/source/hash/value guards; preserve every other field.',
          'Do not bypass the Customs certificate error or import commercial search-result numbers.',
          'Keep the eight unobtained January values missing; no forward fill or average allocation.',
          'Do not restart the policy-blocked resident service using a different process mechanism.'])
    write('records_after.json', actual)
    completion = {'status': 'verified_checkpoint_broad_macro_task_incomplete', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
                  'database_read_only': True, 'database_writes_by_freeze': 0, 'source_network_requests': 0, 'loopback_requests': 1,
                  'effective_values_added': 11, 'inserted_keys': 10, 'invalidated_null_filled': 1, 'own_stale_flags_cleared': 1,
                  'final_replay_changes': 0, 'protected_unchanged': list(protected), 'current_city_coverage': quality,
                  'python_related_passed': 216, 'node_chart_passed': 14, 'actual_page_checks': 23, 'whole_repository_claim': False,
                  'new_resident_parser_runtime_verified': False,
                  'unrecoverable_intermediate_detail': ['The first Customs recorder navigation race lost its original source exception; second independent capture records ERR_CERT_AUTHORITY_INVALID. No acquired source data was lost.'],
                  'remaining': ['2019-2026 January 31-city observations', 'September USD trade and original published balances',
                                'Provincial fiscal/fund/land and annual livelihood history gaps', 'Normal runtime reload acceptance'],
                  'command': ['python', '-X', 'utf8', 'scripts/freeze_city_survey_checkpoint.py', *sys.argv[1:]],
                  'output_dir': output.relative_to(ROOT).as_posix()}
    write('completion_audit.json', completion)
    write('manifest.json', {'references': list(references.values()), 'generated': [
        {'path': path.name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in output.iterdir() if path.is_file()]})
    for record in references.values():
        if hashlib.sha256(local(record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('A referenced file changed during checkpoint creation.')
        if record.get('frozen_path') and hashlib.sha256((output / record['frozen_path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('A frozen file failed exact readback.')
    for record in load(output / 'manifest.json')['generated']:
        if hashlib.sha256((output / record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Generated checkpoint readback failed.')
    write('manifest_verification.json', {'status': 'passed', 'references_checked': len(references),
                                       'frozen_files': sum(bool(row.get('frozen_path')) for row in references.values())})
    print(json.dumps({'output_dir': str(output), 'status': completion['status'], 'references': len(references), 'city_effective_values': 96}, ensure_ascii=False))


if __name__ == '__main__':
    main()
