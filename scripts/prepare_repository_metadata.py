#!/usr/bin/env python3
"""Prepare public repository bibliographies with exact access/reading provenance."""

import argparse
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

IPJ = 'Intellectual Property Journal'
NZJTLP = 'New Zealand Journal of Taxation Law and Policy'


def clean(value):
    return ' '.join(value.split())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def supplied_name(value):
    parts = [clean(part) for part in value.split(',', 1)]
    return ' '.join(reversed(parts)) if len(parts) == 2 else clean(value)


def record_identity(url):
    return 'institutional_repository_item:' + url.rstrip('/')


def osgoode_record(html, source):
    soup = BeautifulSoup(html, 'html.parser')
    metadata, fields = {}, {}
    for meta in soup.find_all('meta', attrs={'name': True, 'content': True}):
        metadata.setdefault(meta['name'], []).append(meta['content'])
    for heading in soup.find_all(['h2', 'h3', 'h4']):
        following = heading.find_next_sibling()
        if following is not None:
            fields[clean(heading.get_text())] = clean(following.get_text(' ', strip=True))
    citation = fields.get('Source Publication', '')
    if re.search(r'\b(submitted|forthcoming|preview|working paper)\b', citation, re.I):
        return None, 'UNCONFIRMED_JOURNAL_PUBLICATION'
    if fields.get('Document Type') not in ('Article', 'Commentary', 'Editorial') or IPJ not in citation:
        return None, 'NOT_SUPPORTED_JOURNAL_ITEM'
    published = fields.get('Publication Date', '')
    date = re.fullmatch(r'(?:(\d{1,2})-)?(20\d\d)', published)
    if not date:
        return None, 'UNCONFIRMED_PUBLICATION_DATE'
    year = int(date[2])
    if not 2010 <= year <= 2026:
        return None, 'OUTSIDE_FROZEN_HISTORY_PERIOD'
    month = int(date[1]) if date[1] else None
    if month is not None and not 1 <= month <= 12:
        raise ValueError('Invalid explicit repository publication month')
    patterns = [
        r'^(\d+)\((\d+)\) Intellectual Property Journal (\d+)(?:-\d+)?(?: \((\d{4})\))?\.?$',
        r'^Intellectual Property Journal, (\d+)\((\d+)\), (\d+)(?:-\d+)?\.?$',
        r'^Intellectual Property Journal\. Volume (\d+) \((\d{4})\), p\. (\d+)(?:-\d+)?\.?$',
        r'^Intellectual Property Journal, vol\. (\d+), no\. (\d+), (\d{4}), pp\. (\d+)(?:-\d+)?\.?$']
    match = next(((number, re.fullmatch(pattern, citation)) for number, pattern in enumerate(patterns)
                  if re.fullmatch(pattern, citation)), None)
    if match is None:
        return None, 'UNCONFIRMED_COMPLETE_JOURNAL_CITATION'
    kind, values = match
    volume = int(values[1])
    if kind == 2:
        issue, first_page, cited_year = None, int(values[3]), int(values[2])
    elif kind == 3:
        issue, first_page, cited_year = values[2], int(values[4]), int(values[3])
    else:
        issue, first_page = values[2], int(values[3])
        cited_year = int(values[4]) if kind == 0 and values[4] else year
    if cited_year != year:
        return None, 'REPORTED_YEAR_CONFLICT_NEEDS_RECONCILIATION'
    title = clean(metadata.get('bepress_citation_title', [''])[0])
    authors = [supplied_name(value) for value in metadata.get('bepress_citation_author', [])]
    if not title or not authors:
        raise ValueError('A repository item needs its supplied title and authors')
    return {'journal_title': IPJ, 'title': title, 'authors': authors, 'volume': volume, 'issue': issue,
        'printed_start_page': first_page, 'publication_year': year,
        'publication_month': f'{year:04d}-{month:02d}' if month else None, 'publication_date': None,
        'date_precision': 'month' if month else 'year', 'abstract': fields.get('Abstract') or None,
        'abstract_kind': 'repository_supplied_description', 'source_url': source['source_url'],
        'source_raw_id': record_identity(source['source_url']), 'source_artifact_path': source['raw_path'],
        'source_artifact_sha256': source['sha256'], 'source_format': 'osgoode_public_html_metadata',
        'source_citation': citation, 'source_repository_citation': fields.get('Repository Citation'),
        'source_date_raw': published, 'source_metadata_values': metadata,
        'source_name': 'Osgoode Digital Commons: public journal bibliography',
        'archive_year_priority': 15, 'year_basis': 'reported_institutional_journal_citation_year',
        'record_type': 'commentary' if fields['Document Type'] == 'Commentary' else 'journal-article',
        'status': 'VERIFIED_PUBLIC_REPOSITORY_METADATA', 'publisher_print_period_verified': False,
        'reading_scope': 'direct HTTP 200 public repository metadata and supplied description only',
        'full_text_reviewed': False}, None


def transcribed_record(source, artifact_path):
    if source.get('reading_scope') != 'primary_page_rendered_metadata_only' or source.get('source_kind') != 'WEB_PRIMARY_METADATA_TRANSCRIPTION':
        raise ValueError('A transcription must retain its actual primary-page reading scope')
    if source.get('full_text_reviewed') is not False or source['journal_title'] != NZJTLP:
        raise ValueError('Unsupported transcript or falsely claimed reading scope')
    citation = source['citation']
    match = re.search(r'\((20\d\d)\)\. Editorial\. New Zealand Journal of Taxation Law and Policy\. '
                      r'(\d+)\((\d+)\)\. (\d+)-(\d+)\.', citation)
    if not match or int(match[1]) != source['reported_year'] or not 2010 <= int(match[1]) <= 2026:
        raise ValueError('Transcript lacks its explicit complete publication citation')
    year, volume, issue = int(match[1]), int(match[2]), match[3]
    month, basis, priority = None, 'reported_institutional_journal_citation_year', 15
    notice = source.get('publisher_issue_notice_excerpt')
    if notice:
        period = re.fullmatch(r'Volume (\d+):(\d+) June (20\d\d)', notice)
        if not period or (int(period[1]), period[2], int(period[3])) != (volume, issue, year):
            raise ValueError('The exact publisher issue notice differs from the citation')
        month, basis, priority = f'{year}-06', 'explicit_publisher_issue_notice_in_repository', 30
    return {'journal_title': NZJTLP, 'title': source['title'], 'authors': source['canonical_authors'],
        'source_authors_as_supplied': source['authors_as_supplied'], 'volume': volume, 'issue': issue,
        'printed_start_page': int(match[4]), 'publication_year': year, 'publication_month': month,
        'publication_date': None, 'date_precision': 'month' if month else 'year',
        'abstract': source.get('supplied_abstract'), 'abstract_kind': 'repository_supplied_description',
        'source_url': source['source_url'], 'source_raw_id': record_identity(source['source_url']),
        'source_artifact_path': str(artifact_path), 'source_artifact_sha256': digest(artifact_path),
        'source_format': 'primary_web_metadata_transcription', 'source_citation': citation,
        'source_name': 'University of Canterbury: public repository metadata',
        'source_access_scope': source['access_scope'], 'repository_handle': source.get('handle'),
        'archive_year_priority': priority, 'year_basis': basis, 'record_type': 'editorial',
        'status': 'VERIFIED_PUBLIC_REPOSITORY_METADATA', 'publisher_print_period_verified': False,
        'reading_scope': 'primary repository rendered metadata/citation only; direct HTML unavailable; article body not read',
        'full_text_reviewed': False}


def prepare(receipts_path, transcriptions_path, output):
    records, excluded = [], []
    for source in json.loads(receipts_path.read_text(encoding='utf-8')):
        if source['http'] != 200:
            excluded.append(dict(source, reason='PUBLIC_HTML_UNAVAILABLE'))
            continue
        if digest(source['raw_path']) != source['sha256']:
            raise ValueError('Original public repository HTML changed')
        row, reason = osgoode_record(gzip.decompress(Path(source['raw_path']).read_bytes()), source)
        if row:
            records.append(row)
        else:
            excluded.append({'source_url': source['source_url'], 'reason': reason})
    for source in json.loads(transcriptions_path.read_text(encoding='utf-8')):
        records.append(transcribed_record(source, transcriptions_path))
    if len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Repeated persistent repository identities')
    output.mkdir(parents=True, exist_ok=False)
    report = {'prepared_at': datetime.now(timezone.utc).isoformat(), 'records': len(records),
        'per_journal': {journal: sum(row['journal_title'] == journal for row in records) for journal in [IPJ, NZJTLP]},
        'supplied_descriptions': sum(bool(row.get('abstract')) for row in records), 'excluded': excluded,
        'receipts_path': str(receipts_path), 'receipts_sha256': digest(receipts_path),
        'transcriptions_path': str(transcriptions_path), 'transcriptions_sha256': digest(transcriptions_path),
        'script_sha256': digest(__file__), 'article_database_writes': 0, 'full_text_reviewed': False,
        'publisher_census_proven': False}
    for name, value in [('verified_records.json', records), ('report.json', report)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html-receipts', type=Path, required=True)
    parser.add_argument('--web-transcriptions', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.html_receipts.resolve(), args.web_transcriptions.resolve(), args.output_dir.resolve()), indent=2))
