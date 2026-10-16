#!/usr/bin/env python3
"""Reconcile inspected published metadata with preserved faculty/issue sources."""

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


def clean(value):
    return ' '.join(value.split())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compact(value):
    return ''.join(character for character in unicodedata.normalize('NFKC', value).casefold()
                   if character.isalnum())


def issue_items(html):
    soup = BeautifulSoup(html, 'html.parser')
    records = []
    for heading in soup.find_all('h3'):
        period = re.fullmatch(r'Volume (\d+), Issue (\d+)', clean(heading.get_text()))
        if not period:
            continue
        contents = heading.find_next_sibling('dl')
        if contents is None:
            continue
        for title in contents.find_all('dt', recursive=False):
            description = title.find_next_sibling('dd')
            paragraphs = description.find_all('p', recursive=False)
            byline = clean(paragraphs[0].get_text(' ', strip=True))
            abstract_start = next((index for index, p in enumerate(paragraphs)
                                   if re.fullmatch(r'Abstract\s*:', clean(p.get_text()), re.I)), None)
            abstract = clean(' '.join(p.get_text(' ', strip=True) for p in paragraphs[abstract_start + 1:])) if abstract_start is not None else None
            section = heading.find_previous('h2')
            section_text = clean(section.get_text()) if section is not None else ''
            records.append({'title': clean(title.get_text(' ', strip=True)).strip('"“”'),
                'volume': int(period[1]), 'issue': period[2], 'observed_author_text': byline,
                'abstract': abstract or None, 'source_issue_heading': clean(heading.get_text()),
                'publisher_page_section': 'current_issue' if section_text == 'Current Issue' else
                                          'upcoming_issue' if section_text == 'Upcoming Issues' else 'unknown_section'})
    return records


def prepare(collected_path, plan_path, issue_html_path, output):
    collected = json.loads(collected_path.read_text(encoding='utf-8'))
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan['status'] != 'VISUALLY_CHECKED_PUBLISHED_METADATA_PLAN':
        raise ValueError('The published metadata plan has not been inspected')
    source_items = issue_items(gzip.decompress(issue_html_path.read_bytes()))
    indexed = {Path(row['pdf_path']).stem: row for row in collected if row.get('pdf_path')}
    rows, pending = [], []
    if set(indexed) != set(plan['items']):
        raise ValueError('Every downloaded PDF needs explicit metadata reconciliation')
    for key, correction in plan['items'].items():
        original = indexed[key]
        pdf = Path(original['pdf_path'])
        if digest(pdf) != original['pdf_sha256']:
            raise ValueError('A published PDF changed')
        image = pdf.parent / (key + correction['year_image_suffix'])
        title_image = pdf.parent / (key + '.page_2_header.png')
        if digest(image) != correction['year_image_sha256'] or digest(title_image) != correction['title_image_sha256']:
            raise ValueError('An inspected source image changed')
        if digest(original['source_html_path']) != original['source_html_sha256']:
            raise ValueError('An original faculty bibliography changed')
        authors = correction['authors']
        year = correction['publication_year']
        if not 2010 <= year <= 2026 or not authors or not correction['title']:
            raise ValueError('Invalid publication metadata plan')
        key_fields = ['0040-0041', original['volume'], original['printed_start_page'], correction['title'], authors]
        evidence = {'year_basis': correction['year_basis'], 'source_url': original['observed_article_url'],
            'publication_year': year, 'printed_year_document': str(pdf), 'printed_year_sha256': original['pdf_sha256'],
            'year_image_path': str(image), 'year_image_sha256': correction['year_image_sha256'],
            'year_physical_page': correction['year_physical_page'],
            'institutional_citation_year_preserved': original['institution_reported_year']}
        row = {'journal_title': original['journal_title'], 'title': correction['title'], 'authors': authors,
            'source_title_original': original['title'], 'authors_in_faculty_citation': original['authors_in_faculty_citation'],
            'volume': original['volume'], 'issue': correction.get('issue'), 'printed_start_page': original['printed_start_page'],
            'publication_year': year, 'publication_month': None, 'publication_date': None, 'date_precision': 'year',
            'source_raw_id': 'nyu_published_item:' + hashlib.sha256(json.dumps(key_fields, ensure_ascii=False).encode()).hexdigest(),
            'abstract': original.get('faculty_abstract'), 'source_url': original['observed_article_url'],
            'source_name': original['journal_title'] + ': public published-version metadata',
            'pdf_path': str(pdf), 'pdf_sha256': original['pdf_sha256'], 'issue_year_evidence': evidence,
            'archive_year_priority': correction['archive_year_priority'], 'record_type': correction.get('record_type', 'journal-article'),
            'metadata_format': 'publisher_pdf_metadata', 'status': 'VERIFIED_PUBLIC_CONTENTS_ITEM',
            'faculty_citation_evidence': {key: original[key] for key in ['source_url', 'source_html_path', 'source_html_sha256', 'citation_text']},
            'abstract_source': {'kind': 'institutional_faculty_supplied_abstract', 'source_url': original['source_url'],
                               'path': original['source_html_path'], 'sha256': original['source_html_sha256']} if original.get('faculty_abstract') else None,
            'verification': 'title and supplied bylines visually reconciled to published page; publication year image and citation evidence retained',
            'reading_scope': 'faculty citation/supplied abstract, published title/byline page and selected year header; article body not reviewed',
            'title_or_year_conflict_preserved': correction['title'] != original['title'] or year != original['institution_reported_year'],
            'full_text_reviewed': False}
        if original['printed_start_page'] == '197':
            issue = next(item for item in source_items if item['volume'] == 72 and item['issue'] == '2' and compact(item['title']) == compact(row['title']))
            row['abstract'] = issue['abstract']
            row['abstract_source'] = {'kind': 'publisher_public_issue_abstract', 'source_url': plan['issue_source_url'],
                                     'path': str(issue_html_path), 'sha256': digest(issue_html_path)}
        rows.append(row)
    foreword = next(row for row in rows if row['record_type'] == 'editorial' and row['issue'] == '1')
    for item in source_items:
        if item['publisher_page_section'] != 'current_issue':
            if not any(compact(row['title']) == compact(item['title']) for row in rows):
                pending.append(dict(item, status='REVIEW_UPCOMING_CONTENTS_NEEDS_PUBLISHED_ITEM_CORROBORATION'))
            continue
        if (item['volume'], item['issue']) != (foreword['volume'], foreword['issue']):
            raise ValueError('The current issue and inspected year anchor are different issues')
        byline = re.fullmatch(r'by\s+([^,;]+),[^;]*', item['observed_author_text'])
        if byline is None or ' and ' in byline[1]:
            raise ValueError('A current-issue byline needs explicit multi-author reconciliation')
        supplied_names = byline[1]
        authors = [clean(supplied_names)]
        identity = ['0040-0041', item['volume'], item['issue'], item['title'], authors]
        rows.append(dict(item, journal_title='Tax Law Review', authors=authors,
            publication_year=foreword['publication_year'], publication_month=None, publication_date=None,
            date_precision='year', printed_start_page=None, source_raw_id='nyu_issue_item:' + hashlib.sha256(
                json.dumps(identity, ensure_ascii=False).encode()).hexdigest(),
            source_url=plan['issue_source_url'], source_name='Tax Law Review: public current-issue contents',
            source_html_path=str(issue_html_path), source_html_sha256=digest(issue_html_path),
            metadata_format='publisher_issue_html', archive_year_priority=20,
            issue_year_evidence=dict(foreword['issue_year_evidence'],
                year_basis='explicit_same_issue_citation_in_published_foreword_and_current_issue_contents'),
            record_type='journal-article', status='VERIFIED_PUBLIC_CONTENTS_ITEM',
            verification='current-issue title/byline/labelled abstract checked; year anchored to the exact published foreword issue citation',
            reading_scope='public current-issue contents and supplied abstracts only', full_text_reviewed=False))
    output.mkdir(parents=True, exist_ok=False)
    result = {'prepared_at': datetime.now(timezone.utc).isoformat(), 'records': len(rows),
        'supplied_abstracts': sum(bool(row.get('abstract')) for row in rows), 'published_pdfs': len(indexed),
        'current_issue_html_items': sum(row.get('metadata_format') == 'publisher_issue_html' for row in rows),
        'unconfirmed_upcoming_items': len(pending),
        'metadata_plan_path': str(plan_path), 'metadata_plan_sha256': digest(plan_path),
        'collector_output_path': str(collected_path), 'collector_output_sha256': digest(collected_path),
        'script_sha256': digest(__file__), 'article_database_writes': 0, 'publisher_article_census_proven': False,
        'full_text_reviewed': False}
    for name, value in [('verified_records.json', rows), ('pending_upcoming_items.json', pending), ('report.json', result)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collected-records', type=Path, required=True)
    parser.add_argument('--metadata-plan', type=Path, required=True)
    parser.add_argument('--issue-html', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.collected_records.resolve(), args.metadata_plan.resolve(),
                             args.issue_html.resolve(), args.output_dir.resolve()), indent=2))
