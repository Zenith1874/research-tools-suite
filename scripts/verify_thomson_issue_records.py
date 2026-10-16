#!/usr/bin/env python3
"""Corroborate public issue items and retain observed abstract-version differences."""

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz


SPELLING_VARIANTS = {
    'westlaw_publication:ia6954016f1c211ea99dafba9e329f6c2': 'conceptualizing/conceptualising',
    'westlaw_publication:if34c4254a8bc11e98d34858489f4be61': 'simplicity/simpilicity',
    'westlaw_publication:ie92906e068dd11e6881a84759648e093': 'arrangements/arrangments',
}
MISSING_SENTENCE = 'westlaw_publication:if2009bf4cf7c11e79c6392f7a6424d52'
HEADINGS = {'AUSTRALIAN TAX REVIEW', 'INSOLVENCY LAW JOURNAL', 'JOURNAL OF BANKING AND',
    'FINANCE LAW AND PRACTICE', 'JOURNAL OF BANKING AND FINANCE LAW AND PRACTICE', 'TORT LAW REVIEW'}


def compact(text):
    return ''.join(character for character in unicodedata.normalize('NFKD', text).casefold() if character.isalnum())


def verify(source, output):
    records = json.loads(source.read_text(encoding='utf-8'))
    if len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Resolve repeated publisher identities first')
    source_texts, failures, changes = {}, [], []
    for row in records:
        if row['pdf_path'] not in source_texts:
            if hashlib.sha256(Path(row['pdf_path']).read_bytes()).hexdigest() != row['pdf_sha256']:
                raise ValueError('A corroborating PDF changed')
            with fitz.open(row['pdf_path']) as pdf:
                lines = [re.sub(r'\s*\.{5,}\s*\d+\s*$', '', re.sub(r'[\x00-\x1f]', '', line)).strip()
                         for page in pdf for line in page.get_text().splitlines()]
            kept = [line for line in lines if line.upper() not in HEADINGS
                and not re.match(r'^(?:Volume\s+\d+|\(\d{4}\)\s+\d+\s+)', line, re.I)
                and not re.fullmatch(r'(?:[A-Za-z]+\s+)?\d{1,4}', line)]
            source_texts[row['pdf_path']] = ' '.join(kept)
        text = source_texts[row['pdf_path']];normalized = compact(text)
        for field in ('title', 'observed_author_text'):
            if row.get(field) and compact(row[field]) not in normalized:
                failures.append({'id': row['source_raw_id'], 'reason': field + '_not_in_printed_contents'})
        period = row['issue_year_evidence']
        if hashlib.sha256(Path(period['header_record_path']).read_bytes()).hexdigest() != period['header_record_sha256']:
            raise ValueError('A checked printed period record changed')
        if row['publication_year'] != period['header_evidence']['header_year'] or row['publication_date'] is not None:
            failures.append({'id': row['source_raw_id'], 'reason': 'period_or_precision_mismatch'})
        row['abstract_source'] = 'public_publisher_issue_post'
        if row.get('abstract') and compact(row['abstract']) not in normalized:
            if row['source_raw_id'] in SPELLING_VARIANTS:
                row['abstract_version_difference'] = SPELLING_VARIANTS[row['source_raw_id']]
                row['abstract_version_difference_verified_scope'] = 'public publisher abstract versions, not article full text'
            elif row['source_raw_id'] == MISSING_SENTENCE:
                prefix = row['abstract'][:45]
                suffix = row['abstract'][-75:]
                start = text.find(prefix);end = text.find(suffix, start)
                if start < 0 or end < start:
                    failures.append({'id': row['source_raw_id'], 'reason': 'reviewed_printed_abstract_boundary_missing'})
                    continue
                printed = text[start:end + len(suffix)]
                row['web_abstract_original'] = row['abstract']
                row['abstract'] = printed
                row['abstract_source'] = 'printed_public_publisher_contents_pdf'
                row['abstract_version_difference'] = 'web abstract omits a sentence across the printed page boundary'
                changes.append({'id': row['source_raw_id'], 'change': 'use complete printed abstract; web version retained'})
            else:
                failures.append({'id': row['source_raw_id'], 'reason': 'unresolved_abstract_version_difference'})
    output.mkdir(parents=True, exist_ok=False)
    result = {'verified_at': datetime.now(timezone.utc).isoformat(), 'source': str(source),
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'record_count': len(records),
        'abstracts': sum(bool(row['abstract']) for row in records), 'failures': failures,
        'reviewed_changes': changes, 'raw_files_overwritten': False, 'article_database_writes': 0,
        'full_text_reviewed': False, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (output / 'report.json').open('x', encoding='utf-8') as stream:json.dump(result, stream, indent=2)
    if not failures:
        for row in records:
            row['status'] = 'VERIFIED_PUBLIC_CONTENTS_ITEM'
            row['verification'] = 'public publisher identifier; title/byline corroborated in printed contents; checked printed issue period; bounded publisher abstract'
        with (output / 'verified_records.json').open('x', encoding='utf-8') as stream:json.dump(records, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.records.resolve(), args.output_dir.resolve()), indent=2))
