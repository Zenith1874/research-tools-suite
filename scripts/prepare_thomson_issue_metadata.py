#!/usr/bin/env python3
"""Prepare public issue-post items using independently checked printed periods."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


def clean(text):
    replacements = {'Â\u00a0': ' ', 'â€™': '’', 'â€˜': '‘', 'â€œ': '“', 'â€\u009d': '”',
                    'â€“': '–', 'â€”': '—', 'â€¦': '…'}
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r'Â(?=\s|$)', '', text)
    # Repair only observed UTF-8/Latin-1 accent byte sequences, preserving raw HTML.
    text = re.sub(r'Ã[\x80-\xbf]', lambda match: match[0].encode('latin-1').decode('utf-8'), text)
    return ' '.join(text.split())


def publication_id(uri):
    parsed = urlparse(uri)
    if not parsed.hostname or ('westlaw' not in parsed.hostname and parsed.hostname != 'anzlaw.thomsonreuters.com'):
        return None
    query = {key.casefold(): value for key, value in parse_qs(parsed.query).items()}
    if query.get('docguid'):
        return query['docguid'][0].lower()
    match = re.search(r'/Document/(I[a-f0-9]{32})', parsed.path, re.I)
    return match[1].lower() if match else None


def parse_post(post, period):
    soup = BeautifulSoup(post['content']['rendered'], 'html.parser')
    records, current, section = [], None, 'unspecified'
    for node in soup.find_all(['p', 'li', 'h2', 'h3', 'h4']):
        if node.name == 'p' and node.find_parent('li'):
            continue
        text = clean(node.get_text(' ', strip=True))
        if text.casefold().startswith(('for the pdf version', 'click here to access', 'for general queries')):
            current = None
            continue
        if node.name in ('h2', 'h3', 'h4'):
            section = text;current = None
            continue
        anchors = [(anchor, publication_id(anchor.get('href', ''))) for anchor in node.select('a[href]')]
        anchors = [(anchor, identifier) for anchor, identifier in anchors if identifier]
        if anchors:
            if len(anchors) != 1:
                continue
            anchor, identifier = anchors[0]
            title = clean(anchor.get_text(' ', strip=True))
            tail = BeautifulSoup(str(node), 'html.parser')
            tail_anchor = next((a for a in tail.select('a[href]') if publication_id(a['href']) == identifier), None)
            tail_anchor.decompose()
            author_text = clean(tail.get_text(' ', strip=True)).lstrip('–—- ').strip() or None
            if current is not None and current['source_raw_id'] == 'westlaw_publication:' + identifier:
                current.setdefault('source_link_title_aliases', []).append(current['title'])
                current['title'] = title
                continue
            role_only = bool(author_text and re.match(r'(?:General|Guest|Section)?\s*Editors?\s*:', author_text, re.I))
            current = {'title': title, 'authors': [] if role_only else [clean(name) for name in re.split(r'\s*,\s*|\s+and\s+', author_text or '') if clean(name)],
                'observed_author_text': None if role_only else author_text, 'observed_editor_role': author_text if role_only else None,
                'section_label': section, 'body': [], 'source_raw_id': 'westlaw_publication:' + identifier,
                'publisher_article_url': anchor['href'], 'generic_heading_requires_title': title.upper() in ('EDITORIAL', 'FOREWORD')}
            records.append(current)
        elif current is not None:
            if current['generic_heading_requires_title'] and node.name == 'li' and node.find('strong'):
                current['title'] = text;current['generic_heading_requires_title'] = False
            elif re.match(r'(?:General|Guest|Section)?\s*Editors?\s*:', text, re.I):
                current['observed_editor_role'] = text
            elif node.name == 'p' and text and not node.find('a'):
                current['body'].append(text)
    result = []
    for record in records:
        record.pop('generic_heading_requires_title')
        record.update(journal_title=period['journal_title'], volume=period['volume'], issue=period['issue'],
            publication_year=period['year'], publication_date=None, publication_month=period.get('publication_month'),
            date_precision='month' if period.get('publication_month') else 'year',
            issue_year_evidence=period, source_url=post['link'], source_post_id=post['id'],
            blog_timestamp=post['date'], blog_timestamp_used_as_issue_year=False,
            pdf_path=period['pdf_path'], pdf_sha256=period['pdf_sha256'],
            abstract=clean(' '.join(record.pop('body'))) or None, record_type='journal-metadata-item',
            status='REVIEW_PUBLIC_POST_ITEM_WITH_PRINTED_PERIOD',
            reading_scope='public_issue_post_metadata_and_abstract_only', full_text_reviewed=False)
        result.append(record)
    return result


def prepare(post_dir, header_dir, output):
    posts_file = post_dir / 'posts.json'
    posts = json.loads(posts_file.read_text(encoding='utf-8'))
    periods = defaultdict(list)
    for path in header_dir.glob('*.contents_document.json'):
        metadata = json.loads(path.read_text(encoding='utf-8'))
        if metadata['status'] != 'HEADER_AND_CITATION_RECONCILED':
            continue
        if hashlib.sha256(Path(metadata['pdf_path']).read_bytes()).hexdigest() != metadata['pdf_sha256']:
            raise ValueError('An original contents PDF changed')
        header = metadata['header_evidence']
        months = {name.lower(): number for number, name in enumerate(
            ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'), 1)}
        month_match = re.fullmatch(r'([A-Za-z]+)\s+(\d{4})', header['header_period_label'])
        known_month = months.get(month_match[1].lower()) if month_match else None
        periods[metadata['post_id']].append({'journal_title': metadata['journal_title'], 'volume': header['header_volume'],
            'issue': header['header_issue'], 'year': header['header_year'], 'source_url': metadata['url'],
            'publication_month': f"{header['header_year']:04d}-{known_month:02d}" if known_month else None,
            'year_basis': 'publisher_printed_header_and_citation_year', 'pdf_path': metadata['pdf_path'],
            'pdf_sha256': metadata['pdf_sha256'], 'header_evidence': header, 'header_record_path': str(path),
            'header_record_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    records, skipped = [], []
    for post in posts:
        candidates = periods.get(post['id'], [])
        identities = {(row['journal_title'], row['volume'], row['issue'], row['year']) for row in candidates}
        if len(identities) != 1:
            skipped.append({'post_id': post['id'], 'reason': 'no_unique_checked_printed_issue_period'})
            continue
        records += parse_post(post, candidates[0])
    output.mkdir(parents=True, exist_ok=False)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'source_posts': str(posts_file),
        'source_posts_sha256': hashlib.sha256(posts_file.read_bytes()).hexdigest(),
        'header_dir': str(header_dir), 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'candidate_items': len(records), 'unique_publisher_ids': len({row['source_raw_id'] for row in records}),
        'per_journal': dict(Counter(row['journal_title'] for row in records)), 'skipped_posts': skipped,
        'article_database_writes': 0, 'full_text_reviewed': False}
    for name, data in [('records.json', records), ('report.json', report)]:
        with (output / name).open('x', encoding='utf-8') as stream:json.dump(data, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--post-dir', type=Path, required=True)
    parser.add_argument('--header-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.post_dir.resolve(), args.header_dir.resolve(), args.output_dir.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != 'skipped_posts'}, indent=2))
