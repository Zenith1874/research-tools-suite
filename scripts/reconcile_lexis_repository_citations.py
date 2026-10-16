#!/usr/bin/env python3
"""Match specific publisher items to explicit institutional publication years."""

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compact(value):
    return ''.join(character for character in unicodedata.normalize('NFKD', value).casefold()
                   if character.isalnum())


def extract_repository_citation(html):
    soup = BeautifulSoup(html, 'html.parser')
    metadata = {}
    for tag in soup.find_all('meta', attrs={'name': True, 'content': True}):
        metadata.setdefault(tag['name'], []).append(tag['content'])
    one = lambda name: metadata.get(name, [None])[0]
    if one('eprints.ispublished') != 'pub' or one('eprints.date_type') != 'published':
        raise ValueError('The repository does not explicitly identify a published item')
    date = one('citation_publication_date')
    if not date or not re.fullmatch(r'20\d\d', date) or date != one('eprints.date'):
        raise ValueError('A consistent explicit publication year is required')
    return {'journal_title': one('citation_journal_title'), 'title': one('citation_title'),
        'authors': [' '.join(reversed(author.split(', ', 1))) for author in metadata.get('citation_author', [])],
        'volume': int(one('citation_volume')), 'issue': one('citation_issue'),
        'printed_start_page': int(one('citation_firstpage')), 'publication_year': int(date),
        'institution_citation': one('eprints.citation'), 'pdf_restricted': one('eprints.full_text_status') == 'restricted'}


def exact_publisher_match(rows, citation):
    matches = [row for row in rows if row['journal_title'] == citation['journal_title']
        and row['volume'] == citation['volume'] and row['issue'] == citation['issue']
        and row['printed_start_page'] == citation['printed_start_page']
        and compact(row['title']) == compact(citation['title'])
        and [compact(value) for value in row['authors']] == [compact(value) for value in citation['authors']]]
    if not matches or len({row['source_raw_id'] for row in matches}) != 1:
        raise ValueError('The institutional citation does not resolve to one publisher item')
    return reconcile_aliases(matches)


def reconcile_aliases(matches):
    row = dict(matches[0])
    for alias in matches[1:]:
        if any(alias.get(key) != row.get(key) for key in
               ('title', 'authors', 'abstract', 'volume', 'issue', 'printed_start_page', 'source_raw_id')):
            raise ValueError('Publisher aliases have conflicting metadata')
    row['publisher_source_aliases'] = [{key: alias[key] for key in ('source_url', 'pdf_path', 'pdf_sha256')}
                                       for alias in matches]
    return row


def reconcile(records_path, repository_receipt, university_html, university_url, output):
    rows = json.loads(records_path.read_text(encoding='utf-8'))
    receipt = json.loads(repository_receipt.read_text(encoding='utf-8'))
    raw = Path(receipt['source_html_path'])
    if digest(raw) != receipt['source_html_sha256']:
        raise ValueError('The original repository metadata changed')
    citation = extract_repository_citation(gzip.decompress(raw.read_bytes()))
    torts = exact_publisher_match(rows, citation)
    torts.update(publication_year=citation['publication_year'], publication_month=None,
        publication_date=None, date_precision='year', record_type='journal-article')
    torts['issue_year_evidence'] = {'year_basis': 'reported_institutional_publication_citation_year',
        'source_url': receipt['source_url'], 'repository_metadata_path': str(raw),
        'repository_metadata_sha256': receipt['source_html_sha256'], 'citation': citation,
        'publisher_print_period_verified': False, 'other_issue_items_year_not_inferred': True}
    text = ' '.join(BeautifulSoup(gzip.decompress(university_html.read_bytes()), 'html.parser').get_text(' ', strip=True).split())
    pattern = (r'Jedlickova, Barbora \((20\d\d)\)\. Review of Current Issues in Competition Law, '
               r'Michael Gvozdenovic and Stephen Puttick \(eds\), Federation Press, 2021, volume I and volume II\. '
               r'Competition and Consumer Law Journal, (\d+), (\d+)-(\d+)\.')
    found = re.search(pattern, text)
    if found is None:
        raise ValueError('The university does not supply the explicit review publication citation')
    candidates = [row for row in rows if row['journal_title'] == 'Competition and Consumer Law Journal'
        and row['volume'] == int(found[2]) and row['printed_start_page'] == int(found[3])
        and row['authors'] == ['Barbora Jedlickova'] and compact(row['title']) in compact(found[0])]
    if len({row['source_raw_id'] for row in candidates}) != 1:
        raise ValueError('The review citation must resolve to exactly one publisher item')
    review = reconcile_aliases(candidates)
    review.update(publication_year=int(found[1]), publication_month=None, publication_date=None,
                  date_precision='year', record_type='book-review')
    review['issue_year_evidence'] = {'year_basis': 'reported_institutional_publication_citation_year',
        'source_url': university_url, 'repository_metadata_path': str(university_html),
        'repository_metadata_sha256': digest(university_html), 'citation': found[0],
        'review_publication_year': int(found[1]), 'reviewed_book_year_separately_preserved': 2021,
        'publisher_print_period_verified': False, 'other_issue_items_year_not_inferred': True}
    verified = [torts, review]
    for row in verified:
        for alias in row['publisher_source_aliases']:
            if digest(alias['pdf_path']) != alias['pdf_sha256']:
                raise ValueError('An original publisher alias PDF changed')
        row.update(status='VERIFIED_PUBLIC_CONTENTS_ITEM', archive_year_priority=15,
            verification='publisher title/byline/identifier/page matched to explicit institutional publication citation; year remains source-reported fallback',
            reading_scope='public publisher contents/supplied abstract and specific institutional publication citation only',
            publisher_print_period_verified=False, full_text_reviewed=False)
    output.mkdir(parents=True, exist_ok=False)
    report = {'verified_at': datetime.now(timezone.utc).isoformat(), 'records': len(verified),
        'source_records_path': str(records_path), 'source_records_sha256': digest(records_path),
        'repository_receipt_path': str(repository_receipt), 'repository_receipt_sha256': digest(repository_receipt),
        'script_sha256': digest(__file__), 'publication_years': [row['publication_year'] for row in verified],
        'record_types': [row['record_type'] for row in verified], 'supplied_abstracts': sum(bool(row['abstract']) for row in verified),
        'year_inferred_for_other_issue_items': False, 'protected_pdfs_requested': 0,
        'article_database_writes': 0, 'publisher_print_period_verified': False, 'full_text_reviewed': False}
    for name, value in [('verified_records.json', verified), ('report.json', report)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--repository-receipt', type=Path, required=True)
    parser.add_argument('--university-html', type=Path, required=True)
    parser.add_argument('--university-url', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reconcile(args.records.resolve(), args.repository_receipt.resolve(),
                             args.university_html.resolve(), args.university_url, args.output_dir.resolve()), indent=2))
