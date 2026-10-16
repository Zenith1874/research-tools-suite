#!/usr/bin/env python3
"""Match public NZULR abstract blocks to verified issue items before any DB write."""

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ISSUE = re.compile(r'Vol\.?\s*(\d+)\s*,?\s*No\.?\s*(\d+[A-Za-z]?)\s+(\w+)\s+(\d{4})', re.I)


def normalize_title(text):
    normalized = unicodedata.normalize('NFKD', html.unescape(text)).casefold()
    return ''.join(character for character in normalized if character.isalnum())


def clean(text):
    return ' '.join(text.split())


def title_line(line):
    text = clean(line['text'])
    letters = [character for character in text if character.isalpha()]
    uppercase_fraction = sum(character.isupper() for character in letters) / len(letters) if letters else 0
    return (bool(text) and uppercase_fraction >= 0.75 and max(line.get('sizes') or [0]) >= 9.5
            and any(flag & 16 for flag in line.get('flags', [])))


def parse_document(document):
    header = ISSUE.search(document['pages'][0]['text'])
    if header is None:
        raise ValueError('No explicit volume, issue and year in the abstract document')
    volume, issue, month, year = int(header[1]), header[2].upper(), header[3].title(), int(header[4])
    records, current = [], None
    for page in document['pages']:
        for line in page['lines']:
            text = clean(line['text'])
            if not text or text == 'NZULR ABSTRACTS' or ISSUE.search(text) or text.isdecimal():
                continue
            title_date_continuation = (current is not None and not current['authors'] and not current['body']
                and re.fullmatch(r'c\.\s*\d{4}\s*[\u2013-]\s*\d{4}', text)
                and any(flag & 16 for flag in line.get('flags', [])))
            if title_line(line) or title_date_continuation:
                # Adjacent heading lines belong to one title until an author/body
                # line occurs. A title with no following abstract remains empty.
                if current is None or current['authors'] or current['body']:
                    current = {'title_lines': [], 'authors': [], 'body': [], 'pages': [], 'content_lines': []}
                    records.append(current)
                current['title_lines'].append(text)
            elif current is not None:
                current['content_lines'].append(text)
                size = max(line.get('sizes') or [0])
                italic = any(flag & 2 for flag in line.get('flags', []))
                if not current['body'] and size >= 9.5 and not italic:
                    current['authors'].append(text)
                else:
                    current['body'].append(text)
            if current is not None and page['page'] not in current['pages']:
                current['pages'].append(page['page'])
    return [{'observed_pdf_title': clean(' '.join(record['title_lines'])),
             'observed_pdf_author': clean(' '.join(record['authors'])) or None,
             'abstract': clean(' '.join(record['body'])) or None,
             '_content_lines': record['content_lines'],
             'volume': volume, 'issue': issue, 'month_label': month, 'archive_year': year,
             'source_url': document['url'], 'pdf_path': document['pdf_path'],
             'pdf_sha256': document['pdf_sha256'], 'source_pages': record['pages'],
             'reading_scope': 'publisher_abstract_document_only', 'full_text_reviewed': False}
            for record in records]


def match_records(candidates, issue_records):
    def normalized_authors(text):
        without_connectors = re.sub(r'\b(?:and|dr|professor|prof)\b\.?', '', text, flags=re.I)
        return normalize_title(without_connectors)

    expected = defaultdict(list)
    for record in issue_records:
        key = (record['volume'], record['issue'], record['archive_year'], normalize_title(record['title']))
        expected[key].append(record)
    for candidate in candidates:
        key = (candidate['volume'], candidate['issue'], candidate['archive_year'],
               normalize_title(candidate['observed_pdf_title']))
        matches = expected[key]
        candidate['status'] = 'REVIEW_TITLE_OR_ISSUE_MISMATCH'
        if len(matches) == 1:
            candidate['source_raw_id'] = matches[0]['source_raw_id']
            candidate['issue_title'] = matches[0]['title']
            candidate['issue_source_url'] = matches[0]['source_url']
            candidate['status'] = 'MATCHED_EMPTY_ABSTRACT' if not candidate['abstract'] else 'MATCHED_ABSTRACT_CANDIDATE'
            if '_content_lines' in candidate:
                # Font size alone cannot distinguish plain-text abstracts from
                # author names. Match the supplied issue author block first.
                expected_authors = matches[0].get('observed_author_text') or ', '.join(matches[0].get('authors') or [])
                content = candidate['_content_lines']
                author_end = next((number for number in range(1, min(5, len(content)) + 1)
                    if expected_authors and normalized_authors(' '.join(content[:number])) == normalized_authors(expected_authors)), None)
                if author_end is None:
                    candidate['status'] = 'REVIEW_AUTHOR_BOUNDARY'
                else:
                    candidate['observed_pdf_author'] = clean(' '.join(content[:author_end]))
                    candidate['abstract'] = clean(' '.join(content[author_end:])) or None
                    candidate['author_prefix_verified_against_issue'] = True
                    candidate['status'] = 'MATCHED_EMPTY_ABSTRACT' if not candidate['abstract'] else 'MATCHED_ABSTRACT_CANDIDATE'
        elif len(matches) > 1:
            candidate['status'] = 'REVIEW_AMBIGUOUS_ISSUE_TITLE'
    return candidates


def prepare(document_dir, issue_file, output):
    issues = json.loads(issue_file.read_text(encoding='utf-8'))
    candidates, documents = [], []
    for path in sorted(document_dir.glob('*.abstract_document.json')):
        document = json.loads(path.read_text(encoding='utf-8'))
        if hashlib.sha256(Path(document['pdf_path']).read_bytes()).hexdigest() != document['pdf_sha256']:
            raise ValueError('An original abstract PDF changed')
        documents.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        candidates.extend(parse_document(document))
    candidates = match_records(candidates, issues)
    output.mkdir(parents=True, exist_ok=False)
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'documents': documents,
              'issue_records_file': str(issue_file), 'issue_records_sha256': hashlib.sha256(issue_file.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'candidate_count': len(candidates), 'statuses': dict(Counter(row['status'] for row in candidates)),
              'article_database_writes': 0, 'full_text_reviewed': False,
              'next_step': 'verify block boundaries and title variants before abstract enrichment'}
    for name, data in [('records.json', candidates), ('report.json', result)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document-dir', type=Path, required=True)
    parser.add_argument('--issue-records', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    arguments = parser.parse_args()
    result = prepare(arguments.document_dir.resolve(), arguments.issue_records.resolve(),
                     arguments.output_dir.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != 'documents'}, indent=2))
