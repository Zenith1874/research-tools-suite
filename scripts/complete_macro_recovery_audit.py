#!/usr/bin/env python3
"""Close recovery acceptance using existing receipts; never repeat ingestion."""
import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MACRO_FILES = (
    'README.md', 'server.py', 'services/china_macro_service.py',
    'services/china_macro_dashboard_service.py', 'services/china_macro_extended_service.py',
    'services/bank_supervision_snapshot_service.py', 'services/macro_data_quality_service.py',
    'services/us_macro_service.py', 'services/pboc_balance_sheet_service.py',
    'services/macro_analytics_service.py', 'services/macro_scenario_service.py',
    'static/china_macro.html', 'static/us_macro.html',
    'tests/test_macro_completeness.py', 'tests/test_china_macro_service.py',
    'tests/test_rates_macro_parsers.py', 'tests/macro_chart_precision.test.cjs',
    'scripts/backfill_macro_completeness.py', 'scripts/audit_macro_completeness.py',
    'scripts/recover_macro_checkpoint.py', 'scripts/verify_macro_ui.js',
)


def read_log(path):
    data = path.read_bytes()
    return data.decode('utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig')


def browser_receipt(path):
    text = read_log(path)
    match = re.search(r'### Result\s*\n(\{[^\n]+\})', text)
    if not match:
        raise ValueError(f'No saved browser result: {path.name}')
    result = json.loads(match[1])
    if result.get('status') != 'passed' or not all(item['pass'] for item in result['checks'].values()):
        raise ValueError(f'Browser acceptance did not pass: {path.name}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    out = args.run_dir.resolve()
    if not out.is_relative_to(ROOT / 'outputs' / 'macro_completeness'):
        parser.error('The run directory must be inside the macro recovery output directory.')
    final_path = out / 'final_completion_audit.json'
    if final_path.exists():
        parser.error('A final audit already exists; preserve it and inspect that checkpoint.')

    integrity = json.loads((out / 'checkpoint_integrity.json').read_text(encoding='utf-8'))
    initial = json.loads((out / 'completion_audit.json').read_text(encoding='utf-8'))
    api = json.loads((out / 'api_acceptance.json').read_text(encoding='utf-8'))
    tests = read_log(out / 'targeted_tests.log')
    node_tests = read_log(out / 'chart_precision_tests.log')
    assert integrity['all_recorded_raw_hashes_match']
    assert re.search(r'Ran 182 tests', tests) and tests.rstrip().endswith('OK')
    assert re.search(r'pass 3\b', node_tests) and re.search(r'fail 0\b', node_tests)
    assert all(api[name].get('http_status') == 200 and 'error' not in api[name]
               for name in ('health', 'china', 'us', 'quality'))
    browsers = {
        'china': browser_receipt(out / 'china_browser_acceptance.log'),
        'us': browser_receipt(out / 'us_browser_acceptance_v3.log'),
    }
    status_doc = ROOT / 'docs' / 'macro_completeness_STATUS_2026-10-02.md'
    assert status_doc.is_file()
    diff_command = ['git', 'diff', '--check', '--', *MACRO_FILES]
    diff = subprocess.run(diff_command, cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    (out / 'git_diff_check.log').write_text(diff.stdout or 'No diff whitespace errors.\n', encoding='utf-8')
    assert diff.returncode == 0, 'Inspect the saved diff check; do not repair unrelated changes.'

    artifacts = [status_doc, ROOT / 'README.md',
        ROOT / 'outputs/macro_completeness/acceptance-20261002-224828-192248/indicator_coverage.csv',
        *[out / name for name in ('checkpoint_integrity.json', 'raw_manifest_check.json',
          'completion_audit.json', 'api_acceptance.json', 'targeted_tests.log',
          'chart_precision_tests.log', 'china_browser_acceptance.log',
          'us_browser_acceptance.log', 'us_browser_acceptance_v2.log',
          'us_browser_acceptance_v3.log', 'git_diff_check.log', 'reading_log.md', 'decision_log.md')]]
    for receipt in browsers.values():
        artifacts.extend(ROOT / 'output' / 'playwright' / name for name in receipt['screenshots'])
    artifacts.append(ROOT / 'output/playwright/macro-recovery-prices.csv')
    artifacts.extend(ROOT / name for name in MACRO_FILES if name != 'README.md')
    manifest = []
    for path in dict.fromkeys(artifacts):
        data = path.read_bytes()
        manifest.append({'path': path.relative_to(ROOT).as_posix(), 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest()})
    (out / 'final_artifact_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    result = {
        'status': 'completed_with_disclosed_data_gaps',
        'completed_at': datetime.now().astimezone().isoformat(),
        'checkpoint_integrity': {'raw_records_checked': integrity['raw_records_checked'],
                                 'all_recorded_raw_hashes_match': True},
        'before_crash': {'completed_data_runs': [item['run'] for item in integrity['runs']],
                         'saved_implementation': list(MACRO_FILES[:13]),
                         'preserved_original_values': 29},
        'after_recovery': {'ingestion_repeated': False, 'server_restarted_by_recovery': False,
            'backend_tests_passed': 182, 'chart_tests_passed': 3,
            'live_api_acceptance': api, 'browser_acceptance': browsers,
            'documentation': status_doc.relative_to(ROOT).as_posix(),
            'git_diff_check_exit_code': diff.returncode},
        'unrecoverable_data_or_code': [],
        'unrecoverable_transient_evidence': [
            'Pre-crash terminal-only test and progress state had no durable receipt.',
            'No pre-crash reading, decision or completion logs were present; recovery logs start after restart.'
        ],
        'remaining_data_gaps': [
            'Two registered official monthly online-goods fields remain absent.',
            'Chinese unemployment and some annual livelihood histories have internal gaps.',
            'Bank supervisory snapshot covers only reviewed 2026Q1/Q2, not a complete historical panel.',
            'MOFCOM USD FDI latest remains 2023-07; no FX-converted surrogate was inserted.',
            'Trade detail, BOP/IIP detail and harmonized GDP vintages remain follow-up work.'
        ],
        'not_claimed': ['Full-repository test completion', 'Complete macro-domain/history coverage',
                        'Semantic full-text reading of every archived source'],
        'initial_recovery_checkpoint': initial,
        'artifact_manifest': 'final_artifact_manifest.json',
        'git_actions': 'No staging, commit, push or PR performed; unrelated changes preserved.',
    }
    final_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'final_audit': str(final_path),
                      'manifest_artifacts': len(manifest),
                      'browser_checks': {name: len(value['checks']) for name, value in browsers.items()}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
