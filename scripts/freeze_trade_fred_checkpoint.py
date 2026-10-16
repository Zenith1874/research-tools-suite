#!/usr/bin/env python3
"""Freeze a verified trade/FRED checkpoint without re-fetching sources or writing the DB."""
import argparse
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
from scripts.review_apply_fred_native import protected_us_digest
from services.fred_native_review import load_fred_native_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fred-review-dir', type=Path, required=True)
    parser.add_argument('--gacc-activation-dir', type=Path, required=True)
    parser.add_argument('--gacc-replay-dir', type=Path, required=True)
    parser.add_argument('--ui-audit', type=Path, required=True)
    parser.add_argument('--python-log', type=Path, required=True)
    parser.add_argument('--node-log', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-base', type=Path, default=ROOT / 'outputs/macro_refresh_20261015')
    args = parser.parse_args()

    def local(path):
        result = (ROOT / path).resolve()
        if not result.is_relative_to(ROOT):
            raise ValueError('This checkpoint may reference only this workspace.')
        return result

    def read_json(path):
        return json.loads(local(path).read_text(encoding='utf-8-sig'))

    def log_text(path):
        data = local(path).read_bytes()
        return data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')

    fred = read_json(args.fred_review_dir / 'audit.json')
    activation = read_json(args.gacc_activation_dir / 'audit.json')
    replay = read_json(args.gacc_replay_dir / 'audit.json')
    ui = read_json(args.ui_audit)
    if (fred['phase'] != 'verified_current_no_changes'
            or fred['planned_totals'] != {'inserted': 0, 'updated': 0, 'unchanged': 294235}
            or fred.get('production_writes') != 0):
        raise ValueError('The reviewed U.S. checkpoint does not establish a no-change result.')
    if (activation.get('committed_rows') != 12 or not activation.get('protected_unchanged')
            or replay.get('committed_rows') != 0 or not replay.get('protected_unchanged')):
        raise ValueError('Successful and idempotent production trade receipts are required.')
    if ui.get('status') != 'passed' or len(ui['checks']) != 34 or not all(row['pass'] for row in ui['checks']):
        raise ValueError('The complete actual-page acceptance must have passed.')
    python_text, node_text = log_text(args.python_log), log_text(args.node_log)
    if not re.search(r'Ran 170 tests\b', python_text) or not re.search(r'^OK\s*$', python_text, re.M):
        raise ValueError('The current 170-test Python result is missing.')
    if not re.search(r'pass 14\b', node_text) or not re.search(r'fail 0\b', node_text):
        raise ValueError('The current 14-test chart result is missing.')

    source_root = local(Path(fred['source_dir']))
    sources = load_fred_native_archive(source_root)
    source_rows = sum(len(source['rows']) for source in sources.values())
    source_bytes = sum(source['csv_path'].stat().st_size for source in sources.values())
    if source_rows != 294235 or source_bytes != 4991761:
        raise ValueError('The source archive no longer matches the documented completed capture.')

    # A read-only WAL snapshot protects the comparison from unrelated ongoing work.
    with closing(sqlite3.connect(local(args.database).as_uri() + '?mode=ro', uri=True, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('BEGIN')
        us_digest = protected_us_digest(conn, set())
        if list(us_digest) != fred['protected_before']:
            raise ValueError('U.S. records changed after source review; do not reuse a stale conclusion.')
        expected = activation['expected_rows']
        target_keys = {(row['indicator_code'], row['period']) for row in expected}
        china_digest = protected_digest(conn, target_keys)
        if list(china_digest) != activation['protected_before']:
            raise ValueError('An unrelated China macro record changed after trade activation.')
        current = []
        for row in expected:
            actual = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                       (row['indicator_code'], row['period'])).fetchone())
            if any(actual.get(key) != value for key, value in row.items()):
                raise ValueError('A committed trade value or provenance field no longer matches.')
            current.append(actual)

    with closing(requests.Session()) as session:
        session.trust_env = False
        live = {}
        for country in ('china', 'us'):
            response = session.get(f'http://127.0.0.1:5001/api/{country}-macro/data', timeout=45, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError('Actual loopback API is unavailable: ' + country)
            live[country] = response.json()
    api_checks = []
    for row in expected:
        actual = live['china']['series'][row['indicator_code']][-1]
        fields = ('period', 'value', 'unit', 'frequency', 'data_status', 'source_url', 'release_date')
        if any(actual.get(field) != row.get(field) for field in fields):
            raise ValueError('The running China API does not expose a committed trade record.')
        api_checks.append({'code': row['indicator_code'], **{field: actual.get(field) for field in fields}})
    us_quality = live['us']['data_quality']
    for plan in fred['plan']:
        actual = us_quality['indicators'][plan['code']]
        if (actual['n_obs'] != plan['source_observations']
                or actual['start_period'] != plan['source_start'] or actual['end_period'] != plan['source_end']):
            raise ValueError('The running U.S. API coverage differs from the reviewed native source: ' + plan['code'])
        api_checks.append({'code': plan['code'], 'n_obs': actual['n_obs'], 'start_period': actual['start_period'],
                           'end_period': actual['end_period'], 'internal_gap_count': actual.get('internal_gap_count')})

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output = local(args.output_base) / ('trade-fred-checkpoint-' + stamp)
    output.mkdir(parents=True, exist_ok=False)

    def write_json(name, data):
        with (output / name).open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')

    references = {}

    def add_reference(path, role, freeze=False):
        path = local(path)
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            raise ValueError('Missing checkpoint evidence: ' + relative)
        record = {'path': relative, 'role': role, 'bytes': path.stat().st_size,
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if freeze:
            destination = output / 'frozen' / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise ValueError('Never overwrite a frozen checkpoint file.')
            shutil.copy2(path, destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('Frozen copy hash mismatch.')
            record['frozen_path'] = destination.relative_to(output).as_posix()
        references[relative] = record

    code_files = [
        'README.md', 'docs/macro_trade_fred_STATUS_2026-10-15.md',
        'services/china_external_service.py', 'services/us_macro_service.py', 'services/fred_native_review.py',
        'scripts/activate_gacc_government_relay.py', 'scripts/review_apply_fred_native.py',
        'scripts/verify_trade_fred_refresh_live.js', 'scripts/freeze_trade_fred_checkpoint.py',
        'tests/test_fred_native_review.py', 'tests/test_fred_refresh_preservation.py', 'tests/test_gacc_government_relay.py',
        'tests/test_china_macro_service.py', 'tests/test_china_external_service.py', 'tests/test_rates_macro_parsers.py',
        'tests/test_macro_analytics.py', 'tests/test_macro_completeness.py', 'tests/test_price_source_metadata.py',
        'tests/macro_chart_precision.test.cjs', 'static/china_macro.html', 'static/us_macro.html',
        'data/macro_trade_latest_discovery_20261015.json', 'data/macro_trade_official_relays_20261015.json'
    ]
    for path in code_files:
        add_reference(path, 'frozen_code_or_definition', freeze=True)
    for path in source_root.rglob('*'):
        if path.is_file():
            add_reference(path, 'fred_native_archive_including_retained_attempts')
    source_receipt = local(Path(activation['source_receipt']))
    for path in source_receipt.parent.iterdir():
        if path.is_file():
            add_reference(path, 'gacc_native_source')
    for directory in (args.fred_review_dir, args.gacc_activation_dir, args.gacc_replay_dir):
        for path in local(directory).iterdir():
            if path.is_file():
                add_reference(path, 'review_or_activation_receipt')
    for path in (args.python_log, args.node_log, args.ui_audit):
        add_reference(path, 'current_verification')
    for path in ui['screenshots']:
        add_reference(path, 'visually_reviewed_actual_page')
    add_reference(str(args.ui_audit).replace('-audit.json', '-cny.csv'), 'bounded_actual_ui_csv')

    reading_log = {
        'scope': 'The Hunan government relay body/date metadata and all 68 public FRED source CSVs/metadata receipts.',
        'gacc': {'raw_html_bytes': 33684, 'reviewed_values': 12, 'primary_detailed_gacc_table_obtained': False,
                 'raw_receipt': source_receipt.relative_to(ROOT).as_posix()},
        'fred': {'csv_sources': len(sources), 'finite_observations': source_rows, 'original_csv_bytes': source_bytes,
                 'source_archive': source_root.relative_to(ROOT).as_posix(), 'full_provider_documents_read': False},
        'screenshots_visually_reviewed': ui['screenshots'],
        'previous_fiscal_checkpoint_reused_not_recollected': 'docs/macro_fiscal_four_provinces_STATUS_2026-10-15.md'
    }
    decisions = [
        'Fill only missing CNY trade records; keep official_relayed and news-source precision.',
        'Keep the September USD and published balance observations missing; no currency conversion or fake official subtraction.',
        'Use exact public native CSV downloads after normal Python TLS failures; no certificate/proxy/auth bypass.',
        'All 294235 U.S. observations match. Perform zero production writes and preserve original row provenance/timestamps.',
        'Keep provider missing dates and native frequency/index bases; no forward fill, rebase, or quarterly date relabeling.',
        'Preserve all previous successful and failed attempts; freeze this checkpoint only, do not rerun acquisitions.',
        'Do not restart the service through an alternative process-kill mechanism; runtime loading remains a separate verification.'
    ]
    audit = {
        'status': 'verified_checkpoint_broad_macro_task_incomplete', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'database_opened_read_only': True, 'production_writes_by_this_freeze': 0, 'source_network_requests': 0,
        'loopback_api_requests': 2, 'gacc_new_rows_prior_activation': 12, 'gacc_idempotent_new_rows': 0,
        'china_protected_rows': list(china_digest), 'us_rows_unchanged': list(us_digest),
        'us_source_series': len(sources), 'us_source_observations': source_rows, 'us_inserted': 0, 'us_updated': 0,
        'tests': {'python_related': 170, 'node_chart': 14, 'live_ui': len(ui['checks']), 'whole_repository_claim': False},
        'all_68_live_us_coverage_matches_source': True, 'all_12_live_trade_values_and_provenance_match': True,
        'new_python_code_runtime_reload_verified': False, 'source_acquisitions_repeated': False,
        'unrecoverable_this_checkpoint': [],
        'historical_unrecoverable_detail': 'An earlier fiscal failure did not retain the underlying SQL error; no invented root cause.',
        'remaining': ['September USD trade original detail and officially published balances',
                      'Earlier China employment/price histories', 'Unfilled provincial fiscal/fund/land coverage and Xinjiang scope',
                      'NBS update runtime acceptance after an authorized normal service reload'],
        'versions': {'python': platform.python_version(), 'requests': importlib.metadata.version('requests')},
        'command': ['python', '-X', 'utf8', 'scripts/freeze_trade_fred_checkpoint.py', *sys.argv[1:]],
        'output_dir': output.relative_to(ROOT).as_posix()
    }
    write_json('reading_log.json', reading_log)
    write_json('decision_log.json', decisions)
    write_json('api_readback.json', api_checks)
    write_json('committed_trade_readback.json', current)
    write_json('completion_audit.json', audit)
    write_json('manifest.json', {'references': list(references.values()), 'generated': [
        {'path': path.name, 'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in output.iterdir() if path.is_file()]})
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    for record in manifest['references']:
        if hashlib.sha256(local(record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Evidence changed while freezing: ' + record['path'])
        if record.get('frozen_path') and hashlib.sha256((output / record['frozen_path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Frozen evidence readback failed.')
    for record in manifest['generated']:
        if hashlib.sha256((output / record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Generated checkpoint readback failed.')
    write_json('manifest_verification.json', {'status': 'passed', 'references_checked': len(references),
                                              'frozen_files': sum(bool(row.get('frozen_path')) for row in references.values()),
                                              'generated_checked': len(manifest['generated'])})
    print(json.dumps({'output_dir': str(output), 'status': audit['status'], 'references': len(references),
                      'gacc_new_rows': 12, 'us_observations_checked': source_rows, 'us_changed': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
