#!/usr/bin/env python3
"""Preserve public faculty citations and observed PDF metadata, without login."""

import argparse
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import fitz
import requests
from bs4 import BeautifulSoup

TARGETS = ('Tax Law Review', 'Virginia Tax Review')
CITATION = re.compile(r'(\d+)\s+(' + '|'.join(TARGETS) +
                      r')\s*(?:,\s*at\s*)?([ivxlcdm]+|\d+)\s+\((\d{4})\)', re.I)


def clean(value):
    return ' '.join(value.split())


def public_pdf_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'its.law.nyu.edu'
            and parsed.path.startswith('/faculty/profiles/representiveFiles/')
            and parsed.path.casefold().endswith('.pdf'))


def parse_citations(html, source):
    soup = BeautifulSoup(html, 'html.parser')
    owner = clean(soup.find('h1').get_text(' ', strip=True))
    records, excluded = [], []
    for li in soup.find_all('li'):
        clone = BeautifulSoup(str(li), 'html.parser')
        for description in clone.select('.description,.toggle-description'):
            description.decompose()
        supplied = clean(clone.get_text(' ', strip=True))
        citation = CITATION.search(supplied)
        if citation is None:
            continue
        links = [a for a in li.find_all('a', href=True)
                 if not a.find('a') and 'toggle-description' not in a.get('class', [])]
        if not links:
            raise ValueError('A target citation lacks its observed title link')
        title = clean(links[0].get_text(' ', strip=True)).strip('"“” ').rstrip(',')
        if not title:
            raise ValueError('An observed citation title is empty')
        year = int(citation[4])
        if not 2010 <= year <= 2026:
            excluded.append({'title': title, 'year': year, 'reason': 'outside_2010_onward_scope'})
            continue
        description = li.select_one('.description')
        collaborators = re.search(r'\(with\s+([^)]*)\)', supplied[citation.end():], re.I)
        additional = [clean(name) for name in re.split(r',\s*(?:and\s+)?|\s+(?:and|&)\s+',
                      collaborators[1] if collaborators else '') if clean(name)]
        records.append({'title': title, 'faculty_author': owner, 'authors_in_faculty_citation': [owner] + additional,
            'journal_title': citation[2], 'volume': int(citation[1]), 'printed_start_page': citation[3],
            'institution_reported_year': year, 'citation_text': supplied,
            'faculty_abstract': clean(description.get_text(' ', strip=True)) if description else None,
            'observed_article_url': links[0]['href'], 'source_url': source['source_url'],
            'source_html_path': source['raw_path'], 'source_html_sha256': source['sha256'],
            'status': 'REVIEW_FACULTY_CITATION_PUBLISHED_METADATA_PENDING', 'full_text_reviewed': False})
    return records, excluded


def download_pdf(session, url, maximum_bytes):
    """Redirects must stay within the same explicitly public NYU file surface."""
    current = url
    for _ in range(4):
        if not public_pdf_url(current):
            return None, {'status': 'UNAPPROVED_PUBLIC_METADATA_REDIRECT', 'url': current}
        with session.get(current, timeout=(12, 30), allow_redirects=False, stream=True) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                current = urljoin(current, response.headers.get('Location', ''))
                continue
            receipt = {'url': current, 'http_status': response.status_code,
                       'content_type': response.headers.get('Content-Type')}
            if response.status_code != 200:
                return None, dict(receipt, status='PUBLIC_FILE_UNAVAILABLE')
            content = bytearray()
            for chunk in response.iter_content(64 * 1024):
                content.extend(chunk)
                if len(content) > maximum_bytes:
                    return None, dict(receipt, status='PUBLIC_FILE_SIZE_LIMIT', maximum_bytes=maximum_bytes)
            if not content.startswith(b'%PDF-'):
                return None, dict(receipt, status='PUBLIC_RESPONSE_NOT_PDF', bytes=len(content))
            return bytes(content), dict(receipt, status='SAVED_PUBLIC_PDF', bytes=len(content))
    return None, {'status': 'PUBLIC_REDIRECT_LIMIT', 'url': current}


def collect(source_dir, output, maximum_mb=16, metadata_pages=2):
    manifest = json.loads((source_dir / 'manifest.json').read_text(encoding='utf-8'))
    records, excluded = [], []
    for source in manifest['requests']:
        if source['http'] != 200:
            continue
        path = Path(source['raw_path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('An original faculty bibliography changed')
        rows, older = parse_citations(gzip.decompress(path.read_bytes()), source)
        records.extend(rows)
        excluded.extend(older)
    output.mkdir(parents=True, exist_ok=False)
    protected = saved = total_bytes = 0
    source_access_stopped = False
    with requests.Session() as session:
        for row in records:
            url = row['observed_article_url']
            if not public_pdf_url(url):
                row['pdf_receipt'] = {'status': 'PROTECTED_OR_UNSUPPORTED_LINK_NOT_REQUESTED'}
                protected += 1
                continue
            if source_access_stopped:
                row['pdf_receipt'] = {'status': 'ORIGIN_REQUESTS_STOPPED_AFTER_ACCESS_LIMIT'}
                continue
            try:
                data, receipt = download_pdf(session, url, maximum_mb * 1024 * 1024)
            except requests.RequestException as error:
                row['pdf_receipt'] = {'status': 'PUBLIC_REQUEST_FAILED', 'error_type': type(error).__name__}
                continue
            row['pdf_receipt'] = receipt
            if receipt.get('http_status') in (401, 403, 429):
                source_access_stopped = True
            if data is None:
                continue
            key = hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]
            path = output / (key + '.pdf')
            with path.open('xb') as stream:
                stream.write(data)
            row.update(pdf_path=str(path), pdf_sha256=hashlib.sha256(data).hexdigest())
            saved += 1
            total_bytes += len(data)
            with fitz.open(path) as pdf:
                row['pdf_total_pages'] = len(pdf)
                row['metadata_pages'] = [{'physical_page': index + 1,
                                         'text': pdf[index].get_text()}
                                        for index in range(min(metadata_pages, len(pdf)))]
                for index in range(min(metadata_pages, len(pdf))):
                    page = pdf[index]
                    page.get_pixmap(matrix=fitz.Matrix(1.25, 1.25),
                                    clip=fitz.Rect(0, 0, page.rect.width, min(320, page.rect.height))).save(
                                        output / (key + f'.page_{index+1}_header.png'))
            row['reading_scope'] = 'public citation and first two PDF metadata pages; article body not reviewed'
    report = {'finished_at': datetime.now(timezone.utc).isoformat(), 'source_dir': str(source_dir),
        'source_manifest_sha256': hashlib.sha256((source_dir / 'manifest.json').read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'citations': len(records), 'saved_public_pdfs': saved, 'protected_links_not_requested': protected,
        'saved_bytes': total_bytes, 'maximum_mb_per_pdf': maximum_mb, 'metadata_page_limit': metadata_pages,
        'excluded_older_citations': excluded, 'article_database_writes': 0, 'full_text_reviewed': False}
    for name, value in [('records.json', records), ('report.json', report)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--maximum-mb', type=int, default=16)
    parser.add_argument('--metadata-pages', type=int, choices=[1, 2], default=2)
    args = parser.parse_args()
    print(json.dumps(collect(args.source_dir.resolve(), args.output_dir.resolve(),
                             args.maximum_mb, args.metadata_pages), indent=2))
