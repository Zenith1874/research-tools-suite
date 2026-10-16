#!/usr/bin/env python3
"""Inspect the other provider for completed Crossref-zero journal units.

No article or main checkpoint values are written. Immutable one-record probes
support source-gap triage; they are not a publisher-issue census or a substitute
for the uncapped primary collector. Successful saved probes are reused.
"""

import argparse
import gzip
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import connect, request_spec, utc_now, write_new_json
from services.openalex_budget import openalex_headers


def probe(run_dir, reserve):
    manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    journals = {row['history_key']: row for row in
                json.loads((run_dir / 'journals.json').read_text(encoding='utf-8'))}
    conn = connect(run_dir / 'checkpoint.sqlite3', readonly=True)
    try:
        targets = [dict(row) for row in conn.execute('''
            SELECT c.journal_key,o.status AS openalex_status,o.expected_count AS openalex_count
            FROM units c JOIN units o ON c.journal_key=o.journal_key
            WHERE c.provider='crossref' AND o.provider='openalex'
              AND c.status='COMPLETE' AND c.expected_count=0 ORDER BY c.journal_key''')]
    finally:
        conn.close()
    folder = run_dir / 'source_gap_probes'
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    with requests.Session() as session:
        for target in targets:
            key = target['journal_key']
            journal = journals[key]
            path = folder / ('openalex_' + key + '.json.gz')
            if target['openalex_status'] == 'COMPLETE':
                results.append({'title': journal['journal_title'], 'journal_key': key,
                                'basis': 'completed uncapped primary unit',
                                'source_count': target['openalex_count'], 'http_status': 200})
                continue
            if path.exists():
                with gzip.open(path, 'rt', encoding='utf-8') as stream:
                    envelope = json.load(stream)
            else:
                url, params = request_spec('openalex', journal, manifest, '*', 1)
                try:
                    response = session.get(url, params=params, headers=openalex_headers(url), timeout=25)
                    headers = {name: value for name, value in response.headers.items()
                               if name.lower().startswith('x-ratelimit') or name.lower() == 'retry-after'}
                    if response.status_code == 429:
                        results.append({'title': journal['journal_title'], 'journal_key': key,
                                        'http_status': 429, 'rate_headers': headers})
                        break
                    response.raise_for_status()
                    envelope = {'requested_at': utc_now(), 'url': url, 'params': params,
                                'http_status': response.status_code, 'rate_headers': headers,
                                'data': response.json(), 'credential_values_saved': False}
                    with path.open('xb') as file:
                        with gzip.GzipFile(fileobj=file, mode='wb') as stream:
                            stream.write(json.dumps(envelope, ensure_ascii=False).encode('utf-8'))
                except (requests.RequestException, ValueError) as exc:
                    logging.warning('%s probe failed: %s', journal['journal_title'], type(exc).__name__)
                    results.append({'title': journal['journal_title'], 'journal_key': key,
                                    'error_type': type(exc).__name__})
                    continue
                time.sleep(0.5)
            count = envelope['data']['meta']['count']
            results.append({'title': journal['journal_title'], 'journal_key': key,
                            'basis': 'one-record count probe', 'http_status': envelope['http_status'],
                            'source_count': count, 'raw_probe': str(path),
                            'first_work_id': next(iter(envelope['data'].get('results', [])), {}).get('id')})
            logging.info('%s | OpenAlex advertised count=%s', journal['journal_title'], count)
            remaining = envelope.get('rate_headers', {}).get('X-RateLimit-Remaining')
            if remaining is not None and float(remaining) <= reserve:
                break
    report = {'created_at': utc_now(), 'target_count': len(targets), 'observed_count': len(results),
              'crossref_zero_openalex_positive': [row for row in results if (row.get('source_count') or 0) > 0],
              'zero_in_both_probed_sources': [row for row in results if row.get('source_count') == 0],
              'results': results, 'main_article_and_checkpoint_writes': False,
              'source_absence_is_not_no_publications': True,
              'full_primary_pagination_replaced': False}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    report_path = folder / ('review_' + stamp + '.json')
    write_new_json(report_path, report)
    return {'report': str(report_path), 'target_count': len(targets), 'observed_count': len(results),
            'OpenAlex_positive': len(report['crossref_zero_openalex_positive']),
            'both_zero': len(report['zero_in_both_probed_sources'])}


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--reserve', type=int, default=1500)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    print(json.dumps(probe(args.run_dir.resolve(), args.reserve), ensure_ascii=False))
