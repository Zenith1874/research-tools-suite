#!/usr/bin/env python3
"""Collect public issue contents PDFs from hash-checked publisher navigation."""

import argparse
import hashlib
import json
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import fitz
import requests


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', value.lower().replace('&', 'and'))


def collect(candidate_file, output):
    all_candidates = json.loads(candidate_file.read_text(encoding='utf-8'))
    candidates = [row for row in all_candidates if 'volume' in row['link_text'].lower()
                  or row.get('metadata_format') == 'public_journal_issue_contents']
    checked = set()
    for row in candidates:
        if urlparse(row['url']).hostname not in ('www.lexisnexis.com', 'www.lexisnexis.com.au',
                                               'sites.thomsonreuters.com.au', 'livepages.thomsonreuters.com.au'):
            raise ValueError('Supply observed public publisher contents links')
        if row['source_html_path'] not in checked:
            path = Path(row['source_html_path'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['source_html_sha256']:
                raise ValueError('An original publisher navigation page changed')
            checked.add(row['source_html_path'])
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'manifest.json', {
        'created_at': datetime.now(timezone.utc).isoformat(), 'candidate_file': str(candidate_file),
        'candidate_sha256': hashlib.sha256(candidate_file.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'public_volume_pdf_count': len(candidates), 'excluded_policy_or_guideline_links': len(all_candidates) - len(candidates),
        'per_journal': dict(Counter(row['journal_title'] for row in candidates)),
        'workers': 1, 'request_delay_seconds': 1, 'maximum_pdf_bytes': 16 * 1024 ** 2,
        'maximum_pages_text_extracted': 20, 'article_database_writes': 0, 'full_text_reviewed': False})
    state = sqlite3.connect(output / 'checkpoint.sqlite3')
    state.execute('CREATE TABLE records(url TEXT PRIMARY KEY,journal_title TEXT,status TEXT,details_json TEXT)')
    state.executemany("INSERT INTO records(url,journal_title,status) VALUES(?,?,'PENDING')",
                      [(row['url'], row['journal_title']) for row in candidates])
    state.commit()
    unavailable_hosts = set()
    try:
        for candidate in candidates:
            url = candidate['url'];host = urlparse(url).hostname
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            details = dict(candidate, requested_at=datetime.now(timezone.utc).isoformat())
            if host in unavailable_hosts:
                details['status'] = 'UNCHECKED_AFTER_ACCESS_OR_RATE_LIMIT'
            else:
                try:
                    with requests.get(url, headers={'User-Agent': 'ResearchTools-PublicBibliographyAudit/1.0'},
                                      timeout=(15, 45), stream=True) as response:
                        details.update(http_status=response.status_code, final_url=response.url,
                                       content_type=response.headers.get('Content-Type'))
                        if response.status_code != 200:
                            details['status'] = 'ACCESS_UNAVAILABLE'
                            if response.status_code in (401, 403, 429):
                                unavailable_hosts.add(host)
                        else:
                            chunks, size = [], 0
                            for chunk in response.iter_content(65536):
                                size += len(chunk)
                                if size > 16 * 1024 ** 2:
                                    raise ValueError('The contents document exceeds the bounded file size')
                                chunks.append(chunk)
                            raw = b''.join(chunks)
                            if not raw.startswith(b'%PDF-'):
                                details['status'] = 'REVIEW_NON_PDF_RESPONSE'
                            else:
                                path = output / (key + '.pdf')
                                with path.open('xb') as stream:stream.write(raw)
                                with fitz.open(path) as document:
                                    text = document[0].get_text()
                                    header_title = candidate.get('publisher_journal_header_title') or candidate['journal_title']
                                    contents_marker = ('CONTENTS' in text.upper() or
                                        (candidate.get('metadata_format') == 'public_journal_issue_contents'
                                         and re.search(r'\b(?:ARTICLES|EDITORIAL|BOOK REVIEWS)\b', text)))
                                    eligible = (normalize(header_title) in normalize(text[:1500])
                                        and contents_marker and re.search(r'Volume\s+\d+', text, re.I))
                                    pages = []
                                    if eligible:
                                        for number in range(min(20, len(document))):
                                            page = document[number]
                                            lines = [{'text': ''.join(span['text'] for span in line['spans']),
                                                'bbox': line['bbox'], 'sizes': sorted({span['size'] for span in line['spans']}),
                                                'flags': sorted({span['flags'] for span in line['spans']})}
                                                for block in page.get_text('dict')['blocks'] if block.get('type') == 0
                                                for line in block['lines']]
                                            pages.append({'page': number + 1, 'text': page.get_text(), 'lines': lines})
                                    metadata = dict(details, pdf_path=str(path), pdf_sha256=hashlib.sha256(raw).hexdigest(),
                                        total_pages=len(document), pages=pages, full_text_reviewed=False,
                                        reading_scope='publisher_public_contents_and_abstract_document_only',
                                        status='SAVED_CONTENTS_DOCUMENT' if eligible else 'REVIEW_DOCUMENT_HEADER_MISMATCH')
                                    metadata_path = output / (key + '.contents_document.json')
                                    write_json(metadata_path, metadata)
                                details.update(status=metadata['status'], pdf_path=str(path), pdf_sha256=metadata['pdf_sha256'],
                                    metadata_path=str(metadata_path), metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                                    total_pages=metadata['total_pages'], bytes=len(raw))
                except Exception as error:
                    details.update(status='REVIEW_ACCESS_OR_PARSE', error_type=type(error).__name__)
            state.execute('UPDATE records SET status=?,details_json=? WHERE url=?',
                          (details['status'], json.dumps(details, ensure_ascii=False), url))
            state.commit()
            print(json.dumps({'key': key, 'journal': candidate['journal_title'], 'status': details['status']}), flush=True)
            time.sleep(1)
        report = {'finished_at': datetime.now(timezone.utc).isoformat(),
            'states': list(state.execute('SELECT status,COUNT(*) FROM records GROUP BY status')),
            'per_journal_states': list(state.execute('SELECT journal_title,status,COUNT(*) FROM records GROUP BY journal_title,status')),
            'article_database_writes': 0, 'full_text_reviewed': False}
        write_json(output / 'report.json', report)
        return report
    finally:
        state.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.candidates.resolve(), args.output_dir.resolve()), indent=2))
