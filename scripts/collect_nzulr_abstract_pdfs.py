#!/usr/bin/env python3
"""Preserve only public abstract PDFs explicitly linked by verified NZULR issues."""

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import fitz
import requests


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def collect(issue_file, output):
    issues = json.loads(issue_file.read_text(encoding='utf-8'))
    urls = sorted({url for issue in issues if issue.get('status') == 'PARSED'
                   for url in issue.get('public_abstract_pdf_urls', [])})
    if not urls or any(urlparse(url).hostname != 'nzulr.com' or
                       'abstract' not in urlparse(url).path.lower() or
                       not urlparse(url).path.lower().endswith('.pdf') for url in urls):
        raise ValueError('Supply explicitly observed publisher abstract PDF links')
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'manifest.json', {
        'created_at': datetime.now(timezone.utc).isoformat(), 'issue_file': str(issue_file),
        'issue_file_sha256': hashlib.sha256(issue_file.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'urls': urls, 'url_count': len(urls), 'workers': 1,
        'request_delay_seconds': 1, 'maximum_bytes_per_pdf': 16 * 1024 ** 2,
        'maximum_pages_text_extracted': 20, 'article_database_writes': 0,
        'reading_scope': 'publisher_abstract_documents_only', 'full_text_reviewed': False})
    state = sqlite3.connect(output / 'checkpoint.sqlite3')
    state.execute('CREATE TABLE records(url TEXT PRIMARY KEY,status TEXT,details_json TEXT)')
    state.executemany("INSERT INTO records(url,status) VALUES(?,'PENDING')", [(url,) for url in urls])
    state.commit()
    try:
        for url in urls:
            key = hashlib.sha256(url.encode()).hexdigest()[:20]
            details = {'url': url, 'requested_at': datetime.now(timezone.utc).isoformat()}
            try:
                with requests.get(url, headers={'User-Agent': 'ResearchTools-PublicBibliographyAudit/1.0'},
                                  timeout=(15, 45), stream=True) as response:
                    details.update(http_status=response.status_code, final_url=response.url,
                                   content_type=response.headers.get('Content-Type'))
                    if response.status_code != 200:
                        details['status'] = 'ACCESS_UNAVAILABLE'
                    else:
                        chunks, size = [], 0
                        for chunk in response.iter_content(65536):
                            size += len(chunk)
                            if size > 16 * 1024 ** 2:
                                raise ValueError('Document exceeds the bounded abstract PDF size')
                            chunks.append(chunk)
                        raw = b''.join(chunks)
                        if not raw.startswith(b'%PDF-'):
                            details['status'] = 'REVIEW_NON_PDF_RESPONSE'
                        else:
                            path = output / (key + '.pdf')
                            with path.open('xb') as stream:
                                stream.write(raw)
                            with fitz.open(path) as document:
                                pages = []
                                for page in list(document)[:20]:
                                    lines = [{'text': ''.join(span['text'] for span in line['spans']),
                                              'bbox': line['bbox'],
                                              'sizes': sorted({span['size'] for span in line['spans']}),
                                              'flags': sorted({span['flags'] for span in line['spans']})}
                                             for block in page.get_text('dict')['blocks'] if block.get('type') == 0
                                             for line in block['lines']]
                                    pages.append({'page': page.number + 1, 'text': page.get_text(), 'lines': lines})
                                metadata = dict(details, pdf_path=str(path),
                                    pdf_sha256=hashlib.sha256(raw).hexdigest(), total_pages=len(document),
                                    pages=pages, full_text_reviewed=False,
                                    reading_scope='publisher_abstract_documents_only')
                                metadata_path = output / (key + '.abstract_document.json')
                                write_json(metadata_path, metadata)
                            details.update(status='SAVED_ABSTRACT_DOCUMENT', pdf_path=str(path),
                                           pdf_sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                                           metadata_path=str(metadata_path),
                                           metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest())
            except Exception as error:
                details.update(status='REVIEW_ACCESS_OR_PARSE', error_type=type(error).__name__)
            state.execute('UPDATE records SET status=?,details_json=? WHERE url=?',
                          (details['status'], json.dumps(details, ensure_ascii=False), url))
            state.commit()
            print(json.dumps({'key': key, 'status': details['status']}), flush=True)
            time.sleep(1)
        result = {'finished_at': datetime.now(timezone.utc).isoformat(), 'url_count': len(urls),
                  'states': list(state.execute('SELECT status,COUNT(*) FROM records GROUP BY status')),
                  'article_database_writes': 0, 'full_text_reviewed': False}
        write_json(output / 'report.json', result)
        return result
    finally:
        state.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issues', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(collect(arguments.issues.resolve(), arguments.output_dir.resolve()), indent=2))
