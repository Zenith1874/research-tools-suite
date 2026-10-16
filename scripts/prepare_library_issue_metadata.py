#!/usr/bin/env python3
"""Extract explicitly dated issue bibliographies from preserved library posts."""

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString

JOURNAL = 'Canadian Business Law Journal'
MONTHS = {name: number for number, name in enumerate(
    ('January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'), 1)}
PERIOD = re.compile(r'^Volume\s+(\d+),\s+(?:Number|Issue)\s+(\d+)\s*'
                    r'\((' + '|'.join(MONTHS) + r')\s+(\d{4})\)$')


def clean(value):
    return ' '.join(value.split())


def identity_text(value):
    return ''.join(character for character in unicodedata.normalize('NFKC', value).casefold()
                   if character.isalnum())


def block_lines(block):
    """BR ends a line; inline emphasis and span boundaries do not add spaces."""
    parts = []
    for node in block.descendants:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif node.name == 'br':
            parts.append('\n')
    return [clean(line) for line in ''.join(parts).splitlines() if clean(line)]


def issue_lines(post):
    soup = BeautifulSoup(post['content']['rendered'], 'html.parser')
    start = next((block for block in soup.find_all('p')
                  if JOURNAL in block.get_text(' ', strip=True)), None)
    if start is None:
        return None
    lines, block = [], start
    while block is not None:
        if block.name in ('ul', 'ol'):
            lines.extend(clean(item.get_text()) for item in block.find_all('li', recursive=False))
        elif block.name == 'p':
            supplied = block_lines(block)
            if block is not start and supplied:
                # A wholly emphasized non-period heading starts the next journal.
                if (block.find(['strong', 'b']) and '/' not in supplied[0]
                        and not PERIOD.fullmatch(supplied[0])
                        and 'Conference Papers' not in supplied[0]):
                    break
            lines.extend(supplied)
        elif block.name in ('h1', 'h2', 'h3', 'hr'):
            break
        block = block.find_next_sibling()
    return lines


def extract_post(post, source_path, source_sha256):
    lines = issue_lines(post)
    if lines is None:
        return [], None
    periods = [(number, PERIOD.fullmatch(line)) for number, line in enumerate(lines)
               if PERIOD.fullmatch(line)]
    if len(periods) != 1:
        raise ValueError('A library section needs one explicit issue period: ' + str(post['id']))
    position, period = periods[0]
    volume, issue, month, year = int(period[1]), period[2], MONTHS[period[3]], int(period[4])
    if not 2010 <= year <= 2026:
        raise ValueError('Out-of-scope library issue year')
    records, excluded = [], []
    for number, line in enumerate(lines[position + 1:], position + 1):
        if 'Conference Papers' in line and '/' not in line:
            excluded.append({'line': number, 'text': line, 'reason': 'issue_topic_heading'})
            continue
        if '/' in line:
            title, byline = map(clean, line.rsplit('/', 1))
            authors = [clean(author) for author in re.split(r',\s*(?:and\s+)?|\s+(?:and|&)\s+', byline)
                       if clean(author)]
            if not title or not authors:
                raise ValueError('Incomplete library bibliography line')
        elif line == 'Tributes to Bradley Crawford':
            title, byline, authors = line, None, []
        else:
            raise ValueError('Unclassified section line: ' + line)
        kind = ('book-review' if '[Book Review]' in title or title.startswith('Review Essay:')
                else 'editorial' if title == 'Introduction' else 'journal-metadata-item')
        key = [JOURNAL, volume, issue, year, month, title, byline]
        records.append({'journal_title': JOURNAL, 'title': title, 'authors': authors,
            'observed_author_text': byline, 'volume': volume, 'issue': issue,
            'publication_year': year, 'publication_month': f'{year:04d}-{month:02d}',
            'publication_date': None, 'date_precision': 'month', 'abstract': None,
            'source_raw_id': 'institutional_library_item:' + hashlib.sha256(
                json.dumps(key, ensure_ascii=False).encode('utf-8')).hexdigest(),
            'source_url': post['link'], 'source_json_path': str(source_path),
            'source_json_sha256': source_sha256, 'post_id': post['id'],
            'blog_post_date_not_used_as_publication_date': post['date'],
            'source_issue_heading': lines[position], 'source_item_line': line,
            'source_line_number': number, 'record_type': kind,
            'status': 'REVIEW_PUBLIC_LIBRARY_CONTENTS_ITEM',
            'year_basis': 'institutional_library_explicit_issue_period',
            'reading_scope': 'public issue bibliography only',
            'source_transcription_not_publisher_census': True, 'full_text_reviewed': False})
    return records, {'post_id': post['id'], 'source_url': post['link'],
        'issue_heading': lines[position], 'record_count': len(records), 'excluded_headings': excluded}


def reconcile_publisher(records, publisher_records):
    matched = set()
    for row in records:
        candidates = [prior for prior in publisher_records
            if (row['volume'], row['issue'], row['publication_year'], row['publication_month']) ==
               (prior['volume'], prior['issue'], prior['publication_year'], prior['publication_month'])
            and identity_text(row['title']) == identity_text(prior['title'])
            and [identity_text(value) for value in row['authors']] ==
                [identity_text(value) for value in prior['authors']]]
        if len(candidates) > 1:
            raise ValueError('Ambiguous publisher citation corroboration')
        if candidates:
            row['corroborated_publisher_source_raw_id'] = candidates[0]['source_raw_id']
            matched.add(candidates[0]['source_raw_id'])
    if matched != {row['source_raw_id'] for row in publisher_records}:
        raise ValueError('Not every supplied publisher citation was reconciled')


def prepare(posts_path, publisher_path, output):
    posts = json.loads(posts_path.read_text(encoding='utf-8'))
    if len({post['id'] for post in posts}) != len(posts):
        raise ValueError('Repeated library post IDs')
    sha256 = hashlib.sha256(posts_path.read_bytes()).hexdigest()
    records, issues = [], []
    for post in posts:
        items, issue = extract_post(post, posts_path, sha256)
        records.extend(items)
        if issue is not None:
            issues.append(issue)
    prior = json.loads(publisher_path.read_text(encoding='utf-8'))
    reconcile_publisher(records, prior)
    if len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Repeated library item identities need source-alias reconciliation')
    output.mkdir(parents=True, exist_ok=False)
    report = {'prepared_at': datetime.now(timezone.utc).isoformat(), 'source_posts': len(posts),
        'issues': len(issues), 'records': len(records),
        'corroborated_publisher_items': sum(bool(row.get('corroborated_publisher_source_raw_id')) for row in records),
        'source_path': str(posts_path), 'source_sha256': sha256,
        'publisher_records_path': str(publisher_path),
        'publisher_records_sha256': hashlib.sha256(publisher_path.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'article_database_writes': 0, 'publisher_article_census_proven': False}
    for name, value in [('records.json', records), ('issues.json', issues), ('report.json', report)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--posts', type=Path, required=True)
    parser.add_argument('--publisher-records', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.posts.resolve(), args.publisher_records.resolve(), args.output_dir.resolve()), indent=2))
