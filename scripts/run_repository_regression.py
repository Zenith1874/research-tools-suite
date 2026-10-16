#!/usr/bin/env python3
"""Run unittest modules in isolated children with durable per-module receipts."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def now():
    return datetime.now().astimezone().isoformat()


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_result(log_text, returncode, timed_out=False):
    counts = re.findall(r'^Ran (\d+) tests? in ', log_text, re.MULTILINE)
    count = int(counts[-1]) if counts else None
    successful = bool(re.search(r'^OK(?:\s*\([^\n]*\))?\s*$', log_text, re.MULTILINE))
    status = 'timed_out' if timed_out else 'passed' if returncode == 0 and count is not None and successful else 'failed'
    return {'status': status, 'tests_run': count, 'returncode': returncode}


def source_fingerprints():
    return {path.relative_to(ROOT).as_posix(): fingerprint(path)
            for directory in ('services', 'tests')
            for path in sorted((ROOT / directory).rglob('*.py'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261012')
    parser.add_argument('--resume-dir', type=Path)
    parser.add_argument('--timeout-seconds', type=int, default=300)
    args = parser.parse_args()
    if not 10 <= args.timeout_seconds <= 900:
        parser.error('Use a per-module timeout between 10 and 900 seconds.')
    directory = args.resume_dir or args.output_root / ('repository-tests-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    directory.mkdir(parents=True, exist_ok=bool(args.resume_dir))
    journal = directory / 'events.jsonl'
    sources = source_fingerprints()
    modules = sorted((ROOT / 'tests').glob('test_*.py'))
    prior = {}
    if args.resume_dir and journal.exists():
        for line in journal.read_text(encoding='utf-8').splitlines():
            record = json.loads(line)
            if record.get('event') == 'result':
                prior[record['module']] = record
    results = []

    def record(data):
        with journal.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + '\n')

    record({'event': 'run_started', 'at': now(), 'python': sys.version,
            'python_executable': sys.executable, 'n_modules': len(modules),
            'timeout_seconds': args.timeout_seconds, 'source_fingerprints': sources})
    print(json.dumps({'output_dir': str(directory), 'n_modules': len(modules)}, ensure_ascii=False), flush=True)
    for index, path in enumerate(modules, 1):
        module = 'tests.' + path.stem
        digest = fingerprint(path)
        previous = prior.get(module)
        # A passed receipt is reused only for the same source snapshot.
        if previous and previous['status'] == 'passed' and previous['test_sha256'] == digest and previous.get('source_fingerprints') == sources:
            results.append(previous)
            continue
        command = [sys.executable, '-X', 'utf8', '-m', 'unittest', module, '-q']
        log_path = directory / (path.stem + '-' + datetime.now().strftime('%H%M%S-%f') + '.log')
        started = time.monotonic()
        timed_out = False
        with log_path.open('xb') as handle:
            child = subprocess.Popen(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
            record({'event': 'module_started', 'at': now(), 'module': module,
                    'child_pid': child.pid, 'command': command, 'log_path': log_path.name})
            try:
                code = child.wait(timeout=args.timeout_seconds)
            except subprocess.TimeoutExpired:
                # Only this runner's own test child is terminated; never the website.
                child.kill()
                code = child.wait()
                timed_out = True
        result = {'event': 'result', 'at': now(), 'module': module, 'test_sha256': digest,
                  'log_path': log_path.name, 'seconds': round(time.monotonic() - started, 3),
                  'source_fingerprints': sources,
                  **test_result(log_path.read_text(encoding='utf-8', errors='replace'), code, timed_out)}
        record(result)
        results.append(result)
        print(f'{index}/{len(modules)} {module}: {result["status"]} ({result["tests_run"]})', flush=True)
    current_sources = source_fingerprints()
    changed = sorted(key for key in sources.keys() | current_sources.keys() if sources.get(key) != current_sources.get(key))
    failures = [{key: value for key, value in result.items() if key != 'source_fingerprints'}
                for result in results if result['status'] != 'passed']
    summary = {'finished_at': now(), 'python': sys.version, 'n_modules': len(modules),
               'n_passed_modules': len(results) - len(failures),
               'tests_run': sum(result['tests_run'] or 0 for result in results),
               'failures': failures, 'changed_sources_during_run': changed,
               'status': 'completed_passed' if not failures and not changed else 'completed_not_all_verified',
               'scope': 'Each current test_*.py module in tests; Node and browser checks are separate.'}
    target = directory / ('summary-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'summary_path': str(target), **summary}, ensure_ascii=False), flush=True)
    return 0 if summary['status'] == 'completed_passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
