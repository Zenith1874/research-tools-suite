# -*- coding: utf-8 -*-
"""Resolve legal original-source landing pages and open-access locations.

This is intentionally separate from bibliographic verification.  A Crossref
or OpenAlex match proves that a citation record exists; it does not prove that
the full text is freely accessible.  Unpaywall supplies an OA location when
one is registered.  By default this script writes URLs and rights metadata
only.  ``--download`` is opt-in and downloads only an OA PDF URL into the
private derived ``data/research_sources`` directory; it never attempts to
bypass a publisher login or a paywall.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'data' / 'research_catalog.json'
OA_API = 'https://api.unpaywall.org/v2/'
MAILTO = 'zither1874@gmail.com'
ENTITY_KINDS = ('theories', 'constructs', 'methods')
POLITE_DELAY = 1.2


def _safe_name(value):
    value = re.sub(r'[^a-zA-Z0-9._-]+', '-', str(value or 'source')).strip('-')
    return value[:120] or 'source'


def _resolve(session, record):
    doi = str(record.get('doi') or '').strip()
    if not doi:
        if record.get('verification') in {'verified_openalex', 'verified_crossref'}:
            record['access_status'] = 'metadata_only'
            record['retrieval_note'] = 'No DOI was available for an OA locator lookup.'
        return 'metadata_only'

    url = OA_API + requests.utils.quote(doi, safe='')
    try:
        response = session.get(url, params={'email': MAILTO}, timeout=30)
    except requests.RequestException as error:
        record['access_status'] = 'access_lookup_failed'
        record['retrieval_note'] = str(error)[:300]
        return record['access_status']

    if response.status_code != 200:
        record['access_status'] = 'access_lookup_failed'
        record['retrieval_note'] = 'Unpaywall HTTP %s' % response.status_code
        return record['access_status']

    payload = response.json()
    record['unpaywall_is_oa'] = bool(payload.get('is_oa'))
    record['unpaywall_oa_status'] = payload.get('oa_status')
    record['unpaywall_updated'] = payload.get('oa_locations_updated')
    best = payload.get('best_oa_location') or {}
    locations = payload.get('oa_locations') or []
    pdf_url = best.get('url_for_pdf')
    page_url = best.get('url') or best.get('url_for_landing_page')
    if not pdf_url:
        for location in locations:
            if location.get('url_for_pdf'):
                pdf_url = location['url_for_pdf']
                best = location
                break
    if not page_url:
        page_url = best.get('url_for_landing_page')

    if payload.get('is_oa') and (pdf_url or page_url):
        record['access_status'] = 'open_full_text' if pdf_url else 'open_landing_page'
        record['full_text_url'] = pdf_url or record.get('full_text_url')
        record['landing_url'] = page_url or record.get('landing_url')
        record['full_text_version'] = best.get('version')
        record['license'] = best.get('license')
        record['oa_host_type'] = best.get('host_type')
        record['oa_repository'] = best.get('repository_institution')
        record['retrieval_note'] = 'OA location resolved from Unpaywall; inspect version and license before citation.'
    else:
        record['access_status'] = 'publisher_page'
        record['landing_url'] = record.get('landing_url') or payload.get('doi_url')
        record['retrieval_note'] = 'No registered open-access location; publisher/institutional access may be required.'
    return record['access_status']


def _download(session, record, destination):
    if record.get('access_status') != 'open_full_text' or not record.get('full_text_url'):
        return False
    doi = record.get('doi') or record.get('title')
    path = destination / (_safe_name(doi) + '.pdf')
    if path.exists():
        record['local_path'] = str(path.relative_to(ROOT))
        record['local_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        record['retrieval_note'] = 'Existing private OA copy retained; no overwrite performed.'
        return False
    try:
        response = session.get(record['full_text_url'], timeout=60, allow_redirects=True,
                               headers={'Accept': 'application/pdf'})
        response.raise_for_status()
    except requests.RequestException as error:
        record['retrieval_note'] = 'OA URL resolved but download failed: %s' % str(error)[:220]
        return False
    content_type = (response.headers.get('content-type') or '').lower()
    if 'pdf' not in content_type and not response.content.startswith(b'%PDF'):
        record['retrieval_note'] = 'OA URL did not return a PDF; URL retained without local copy.'
        return False
    path.write_bytes(response.content)
    record['local_path'] = str(path.relative_to(ROOT))
    record['local_sha256'] = hashlib.sha256(response.content).hexdigest()
    record['retrieved_at'] = time.strftime('%Y-%m-%d')
    record['retrieval_note'] = 'Private derived OA copy downloaded from the recorded locator; original publisher source remains authoritative.'
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=ENTITY_KINDS, default='all')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--download', action='store_true',
                        help='download OA PDFs only; never bypasses access controls')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    catalog = json.loads(CATALOG.read_text(encoding='utf-8'))
    kinds = ENTITY_KINDS if args.kind == 'all' else (args.kind,)
    rows = []
    for kind in kinds:
        for entity in catalog.get(kind, []):
            for record in entity.get('seminal_works', []):
                if record.get('verification') in {'verified_openalex', 'verified_crossref', 'verified_pubmed'}:
                    rows.append((kind, entity['id'], record))
    if args.limit:
        rows = rows[:args.limit]
    print('%d verified source records to inspect for legal access locations' % len(rows))

    session = requests.Session()
    session.headers.update({'User-Agent': 'research-tools source locator (mailto:%s)' % MAILTO})
    destination = ROOT / 'data' / 'research_sources'
    if args.download:
        destination.mkdir(parents=True, exist_ok=True)

    counts = {}
    downloaded = 0
    for index, (kind, entity_id, record) in enumerate(rows, 1):
        status = _resolve(session, record)
        if args.download:
            downloaded += int(_download(session, record, destination))
        counts[status] = counts.get(status, 0) + 1
        print('[%3d/%d] %-10s %-32s %-20s %s' %
              (index, len(rows), kind[:-1], entity_id, status,
               record.get('full_text_url') or record.get('landing_url') or ''))
        time.sleep(POLITE_DELAY)

    print('access statuses', counts, 'downloaded', downloaded)
    if args.dry_run:
        print('dry run: catalog not written')
        return 0
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8')
    print('wrote', CATALOG)
    return 0


if __name__ == '__main__':
    sys.exit(main())
