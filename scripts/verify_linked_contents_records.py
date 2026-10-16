#!/usr/bin/env python3
"""Check dated linked contents metadata against preserved source text and links."""

import argparse
import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz


def compact(text):
    return ''.join(character for character in unicodedata.normalize('NFKD', text).casefold() if character.isalnum())


def verify(source, output):
    records = [row for row in json.loads(source.read_text(encoding='utf-8')) if row['publication_year'] is not None]
    sources, failures = {}, []
    if len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Resolve repeated publisher identities before verification')
    for row in records:
        if row['pdf_path'] not in sources:
            path = Path(row['pdf_path'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['pdf_sha256']:
                raise ValueError('A source PDF changed')
            with fitz.open(path) as pdf:
                sources[row['pdf_path']] = {'text': compact(' '.join(page.get_text() for page in pdf)),
                    'links': [link.get('uri') for page in pdf for link in page.get_links()]}
        data = sources[row['pdf_path']]
        if compact(row['title']) not in data['text']:
            failures.append({'id': row['source_raw_id'], 'reason': 'title_not_in_source'})
        if row['publisher_article_url'] not in data['links']:
            failures.append({'id': row['source_raw_id'], 'reason': 'identifier_not_in_annotation'})
        for field in ('abstract', 'observed_author_text'):
            if row.get(field) and compact(row[field]) not in data['text']:
                failures.append({'id': row['source_raw_id'], 'reason': field + '_not_contiguous_in_source'})
        if row['printed_start_page'] is None:
            failures.append({'id': row['source_raw_id'], 'reason': 'printed_page_missing'})
        if row['publication_date'] is not None or row['publication_month'] is not None:
            failures.append({'id': row['source_raw_id'], 'reason': 'unsupported_date_precision'})
    output.mkdir(parents=True, exist_ok=False)
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'input': str(source),
        'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'records_checked': len(records),
        'source_documents': len(sources), 'failures': failures, 'article_database_writes': 0,
        'reading_scope': 'public_contents_metadata_and_abstract_text_only', 'full_text_reviewed': False,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (output / 'audit.json').open('x', encoding='utf-8') as stream:json.dump(result, stream, indent=2)
    if not failures:
        for row in records:
            row['status'] = 'VERIFIED_PUBLIC_CONTENTS_ITEM'
            row['verification'] = 'source_title_byline_abstract_annotation_identifier_and_printed_page_checked; explicit_editorial_issue_year'
        with (output / 'verified_records.json').open('x', encoding='utf-8') as stream:json.dump(records, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.records.resolve(), args.output_dir.resolve()), indent=2))
