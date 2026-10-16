#!/usr/bin/env python3
"""Archive one public MOFCOM statistical bulletin and its observed PDF attachment."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
MAX_PDF_BYTES = 30 * 1024 * 1024


def official_mofcom_url(url):
    parts = urlsplit(url)
    return parts.scheme == 'https' and not parts.username and not parts.password and (
        parts.hostname == 'mofcom.gov.cn' or (parts.hostname or '').endswith('.mofcom.gov.cn'))


def bulletin_pdf_links(html, source_url):
    links = set()
    for anchor in BeautifulSoup(html, 'html.parser').find_all('a', href=True):
        label = anchor.get_text('', strip=True)
        url = urljoin(source_url, anchor['href'])
        parts = urlsplit(url)
        filename = parse_qs(parts.query).get('fileName', [''])[0]
        if ('外资统计公报' in label and official_mofcom_url(url)
                and (parts.path.lower().endswith('.pdf') or filename.lower().endswith('.pdf'))):
            links.add(url)
    if len(links) != 1:
        raise ValueError('Exactly one observed official bulletin PDF attachment is required.')
    return next(iter(links))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--observed-pdf-url', help='Exact attachment URL already observed on an official source; no guessing.')
    parser.add_argument('--attachment-source-url', help='Official page where the supplied PDF link was observed.')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261012')
    args = parser.parse_args()
    if not official_mofcom_url(args.source_url):
        parser.error('A verified public MOFCOM source-page URL is required.')
    if args.observed_pdf_url and (not official_mofcom_url(args.observed_pdf_url)
                                 or not official_mofcom_url(args.attachment_source_url or '')):
        parser.error('An observed PDF override requires its verified MOFCOM discovery page.')
    out = args.output_dir / ('mofcom-bulletin-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    manifest, errors = [], []

    def archive(url, name, limit):
        response = session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, stream=True)
        response.raise_for_status()
        if not official_mofcom_url(response.url):
            response.close()
            raise ValueError('Source redirected outside the verified MOFCOM hosts.')
        content = bytearray()
        try:
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > limit:
                    raise ValueError('The source exceeds the proposed bounded download size.')
        finally:
            response.close()
        if name.endswith('.pdf') and not bytes(content).startswith(b'%PDF-'):
            raise ValueError('The observed PDF link returned a non-PDF response.')
        (out / name).write_bytes(content)
        item = {'source_url': url, 'resolved_url': response.url,
                'retrieved_at': datetime.now().astimezone().isoformat(), 'raw_path': name,
                'raw_sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
        manifest.append(item)
        with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        return bytes(content)

    try:
        if args.observed_pdf_url:
            # Do not repeat a failed primary-page fetch just to download an already
            # observed attachment on another official MOFCOM host.
            link = args.observed_pdf_url
        else:
            page = archive(args.source_url, 'source-page.html', 4 * 1024 * 1024)
            link = bulletin_pdf_links(page.decode('utf-8'), args.source_url)
        archive(link, 'bulletin.pdf', MAX_PDF_BYTES)
    except Exception as exc:
        errors.append(str(exc))
    audit = {'captured_at': datetime.now().astimezone().isoformat(), 'source_manifest': manifest,
             'primary_source_page': args.source_url, 'attachment_discovery_page': args.attachment_source_url,
             'primary_page_archived': any(item['raw_path'] == 'source-page.html' for item in manifest),
             'errors': errors, 'status': 'raw_archived_not_yet_reviewed' if not errors else 'incomplete'}
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), 'files': len(manifest),
                      'bytes': sum(item['bytes'] for item in manifest), 'errors': errors}, ensure_ascii=False))
    raise SystemExit(0 if not errors else 1)


if __name__ == '__main__':
    main()
