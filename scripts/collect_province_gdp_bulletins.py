#!/usr/bin/env python3
"""Archive and parse a bounded list of already discovered official provincial releases."""
import argparse
import hashlib
import json
import sys
import ssl
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.province_gdp_bulletin_service import parse_province_gdp_release


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--replay-only', action='store_true', help='Reuse hash-verified archived HTML without any HTTP requests.')
    parser.add_argument('--http-client', choices=('requests', 'urllib'), default='requests',
                        help='urllib uses the platform default validated TLS trust store; neither client disables verification.')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261013')
    args = parser.parse_args()
    if args.replay_only and not args.replay_dir:
        parser.error('--replay-only requires --replay-dir')
    sources = json.loads(args.sources.read_text(encoding='utf-8'))
    if sources.get('schema_version') != 1 or len(sources['releases']) > 31:
        raise ValueError('Use a reviewed list of at most 31 provincial source links.')
    out = args.output_dir / ('province-gdp-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    manifest, parsed, errors = [], [], []
    network_requests = 0
    cached = {}
    if args.replay_dir:
        prior = json.loads((args.replay_dir / 'audit.json').read_text(encoding='utf-8'))
        cached = {row['source_url']: row for row in prior['source_manifest']}
    session = requests.Session()
    for release in sources['releases']:
        url = release['source_url']
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not (parts.hostname or '').endswith('.gov.cn'):
            raise ValueError('Only already discovered official government source links are allowed.')
        try:
            name = release['region_code'] + '.html'
            if url in cached:
                record = cached[url]
                source = (args.replay_dir / record['raw_path']).resolve()
                if not source.is_relative_to(args.replay_dir.resolve()):
                    raise ValueError('Cached source path escaped its run directory.')
                content = source.read_bytes()
                if hashlib.sha256(content).hexdigest() != record['raw_sha256']:
                    raise ValueError('Cached source hash does not match.')
                record = {**record, 'raw_path': name, 'replayed_at': datetime.now().astimezone().isoformat()}
            else:
                if args.replay_only:
                    raise ValueError('No archived source is available; replay-only makes no network request.')
                network_requests += 1
                if args.http_client == 'urllib':
                    context = ssl.create_default_context()
                    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
                        raise ValueError('TLS verification and hostname checks must remain enabled.')
                    with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}),
                                 timeout=15, context=context) as response:
                        content = response.read(5 * 1024 * 1024 + 1)
                        resolved_url = response.url
                else:
                    response = session.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
                    response.raise_for_status()
                    content, resolved_url = response.content, response.url
                if not (urlsplit(resolved_url).hostname or '').endswith('.gov.cn'):
                    raise ValueError('Government source redirected outside its allowed source family.')
                if len(content) > 5 * 1024 * 1024 or content.startswith(b'%PDF'):
                    raise ValueError('This bounded collector requires a public HTML release, not an unchecked PDF.')
                record = {'source_url': url, 'resolved_url': resolved_url, 'raw_path': name,
                          'http_client': args.http_client, 'tls_verified': parts.scheme == 'https',
                          'retrieved_at': datetime.now().astimezone().isoformat(),
                          'raw_sha256': hashlib.sha256(content).hexdigest()}
            (out / name).write_bytes(content)
            manifest.append(record)
            with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            rows = parse_province_gdp_release(content.decode('utf-8'), release['region_name'],
                                              sources['statistical_year'], release['source_title'])
            parsed.append({'release': release, 'source_record': record, 'observations': rows})
            print(f"{release['region_name']}: {len(rows)} directly reported GDP fields", flush=True)
        except Exception as exc:
            errors.append({'source_url': url, 'region_name': release['region_name'], 'error': str(exc)})
            print(f"{release['region_name']}: source/parse incomplete", flush=True)
        time.sleep(0.2)
    audit = {'captured_at': datetime.now().astimezone().isoformat(), 'statistical_year': sources['statistical_year'],
             'source_manifest': manifest, 'parsed': parsed, 'errors': errors,
             'expected_provinces': 31, 'parsed_provinces': len(parsed),
             'network_requests': network_requests,
             'status': 'parsed_pending_independent_review'}
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), 'parsed_provinces': len(parsed), 'errors': len(errors)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
