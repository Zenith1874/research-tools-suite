#!/usr/bin/env python3
"""Prepare linked contents items; issue dates require explicit source evidence."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import fitz


def publication_id(uri):
    parsed = urlparse(uri)
    if parsed.hostname != 'advance.lexis.com':
        return None
    decoded = unquote(uri)
    urn = re.search(r'urn:contentItem:([A-Za-z0-9-]+)', decoded, re.I)
    if urn:
        return 'urn:' + urn[1].upper()
    query = parse_qs(parsed.query)
    if query.get('idtype', [''])[0].upper() == 'DOC-ID' and query.get('id'):
        return 'docid:' + query['id'][0]
    permalink = re.search(r'/api/permalink/([0-9a-f-]{36})', parsed.path, re.I)
    return 'permalink:' + permalink[1].lower() if permalink else None


def clean(text):
    return ' '.join(text.split())


def parse_byline(text):
    """Separate people; comma-delimited postnominals are not extra authors."""
    pieces = re.split(r'(\s*,\s*|\s+and\s+)', text or '')
    authors, suffixes = [], {}
    postnominals = {'AM', 'AO', 'AC', 'SC', 'KC', 'QC'}
    for position in range(0, len(pieces), 2):
        name = clean(pieces[position])
        if not name:
            continue
        separator = pieces[position - 1].strip() if position else None
        if (separator == ',' and name in postnominals and authors
                and len(authors[-1].split()) >= 2):
            suffixes.setdefault(authors[-1], []).append(name)
        else:
            authors.append(name)
    return authors, suffixes


def inline_byline(spans):
    """Recognize an italic byline after a dash in a regular linked title line."""
    text = ''.join(span['text'] for span in spans)
    delimiter = list(re.finditer(r'[—–]', text))
    if not delimiter:
        return None
    last = delimiter[-1]
    suffix = clean(text[last.end():])
    if len(suffix.split()) < 2:
        return None
    cursor, prefix_regular, suffix_style = 0, False, []
    for span in spans:
        end = cursor + len(span['text'])
        if clean(text[cursor:min(end, last.start())]) and not span['flags'] & 2:
            prefix_regular = True
        if end > last.end() and clean(text[max(cursor, last.end()):end]):
            suffix_style.append(bool(span['flags'] & 2))
        cursor = end
    if prefix_regular and suffix_style and all(suffix_style):
        return clean(text[:last.start()]), suffix
    return None


def trailing_byline_title(spans):
    """A final italic dash can introduce a byline on the following line."""
    visible = [span for span in spans if clean(span['text'])]
    if not visible or clean(visible[-1]['text']) not in ('—', '–'):
        return None
    if not visible[-1]['flags'] & 2:
        return None
    prefix = visible[:-1]
    if not prefix or not any(not span['flags'] & 2 for span in prefix):
        return None
    return clean(''.join(span['text'] for span in spans).rstrip().rstrip('—–'))


def split_title_block(lines):
    """Only the final linked line can end in a byline; case titles may continue."""
    title = clean(' '.join(line.get('inline_title', line['text']) if index == len(lines) - 1
                          else line['text'] for index, line in enumerate(lines)))
    authors = [lines[-1]['inline_author']] if lines and lines[-1].get('inline_author') else []
    return title, authors


def visible_line_pages(document, pdf):
    """Blank spans can have large/bold fonts; classify only visible text ink."""
    pages = []
    for source in document['pages']:
        page = pdf[source['page'] - 1]
        lines = []
        for block in page.get_text('dict')['blocks']:
            if block.get('type') != 0:
                continue
            for line in block['lines']:
                spans = [span for span in line['spans'] if clean(span['text'])]
                if not spans:
                    continue
                bbox = [min(span['bbox'][0] for span in spans), min(span['bbox'][1] for span in spans),
                        max(span['bbox'][2] for span in spans), max(span['bbox'][3] for span in spans)]
                item = {'text': ''.join(span['text'] for span in line['spans']), 'bbox': bbox,
                    'source_page': source['page'],
                    'sizes': [span['size'] for span in spans], 'flags': [span['flags'] for span in spans]}
                byline = inline_byline(line['spans'])
                if byline:
                    item['inline_title'], item['inline_author'] = byline
                else:
                    continued_byline = trailing_byline_title(line['spans'])
                    if continued_byline:
                        item['inline_title'] = continued_byline
                lines.append(item)
        pages.append(dict(source, lines=lines))
    return pages


def parse_document(document, year_map):
    header = re.search(r'Volume\s+(\d+)\s+Parts?\s+(\d+(?:\s*(?:&|and)\s*\d+)?)',
                       document['pages'][0]['text'], re.I)
    if header is None:
        raise ValueError('An explicit volume/part header is missing')
    volume = int(header[1]);issue = re.sub(r'\s*(?:&|and)\s*', '&', header[2], flags=re.I)
    period = year_map.get((document['journal_title'], volume, issue))
    blocks = []
    with fitz.open(document['pdf_path']) as pdf:
        visible_pages = visible_line_pages(document, pdf)
        for page in visible_pages:
            groups = {}
            for link in pdf[page['page'] - 1].get_links():
                identifier = publication_id(link.get('uri', ''))
                if not identifier:
                    continue
                rectangle = link['from']
                selected = [line for line in page['lines'] if clean(line['text']) and not clean(line['text']).isdecimal()
                    and not clean(line['text']).startswith(('—', '–'))
                    and max(line['sizes']) >= 11.5
                    and rectangle.contains(fitz.Point((line['bbox'][0] + line['bbox'][2]) / 2,
                                                       (line['bbox'][1] + line['bbox'][3]) / 2))]
                if not selected:
                    continue
                group = groups.setdefault(identifier, {'lines': [], 'uri': link['uri']})
                for line in selected:
                    if line not in group['lines']:
                        group['lines'].append(line)
            for identifier, group in groups.items():
                lines = sorted(group['lines'], key=lambda line: (line['bbox'][1], line['bbox'][0]))
                blocks.append({'identifier': identifier, 'title_lines': lines, 'linked_url': group['uri'],
                               'page': page['page'], 'top': min(line['bbox'][1] for line in lines),
                               'bottom': max(line['bbox'][3] for line in lines)})
    blocks.sort(key=lambda block: (block['page'], block['top']))
    records = []
    for index, block in enumerate(blocks):
        title, inline_authors = split_title_block(block['title_lines'])
        next_block = blocks[index + 1] if index + 1 < len(blocks) else None
        content = [line for page in visible_pages for line in page['lines']
            if (page['page'], line['bbox'][1]) > (block['page'], max(line['bbox'][1] for line in block['title_lines']) + 1)
            and (next_block is None or (page['page'], line['bbox'][1]) < (next_block['page'], next_block['top'] - 1))]
        page_anchor_lines = [line for page in visible_pages for line in page['lines']
            if clean(line['text']).isdecimal() and max(line['sizes']) >= 11.5 and line['bbox'][0] > 350
            and (page['page'], line['bbox'][1]) >= (block['page'], block['top'] - 1)
            and (next_block is None or (page['page'], line['bbox'][1]) < (next_block['page'], next_block['top'] - 1))]
        authors = inline_authors
        body = []
        start_page = int(clean(page_anchor_lines[0]['text'])) if page_anchor_lines else None
        for line in content:
            text = clean(line['text']);size = max(line['sizes'])
            if text.casefold().startswith(('style guidelines', 'submission guidelines', 'in this issue')):
                break
            if not text or text == 'CONTENTS' or re.search(r'Volume\s+\d+\s+Part', text, re.I):
                continue
            if text.isdecimal():
                if start_page is None and size >= 11.5:
                    start_page = int(text)
                continue
            if any(flag & 16 for flag in line['flags']) and size >= 12.3:
                continue
            if size >= 11.5:
                if not body:
                    if (not authors and line.get('inline_author')
                            and line['source_page'] == block['page']
                            and line['bbox'][1] <= block['bottom'] + 2 * size):
                        # A short final title fragment may sit outside the URL
                        # rectangle, followed by a differently styled byline.
                        title = clean(title + ' ' + line['inline_title'])
                        authors.append(line['inline_author'])
                    else:
                        authors.append(text.lstrip('—–- ').strip())
                # Later unlinked item headings/bylines must not become abstract.
                else:
                    break
            else:
                body.append(text)
        author_text = clean(' '.join(authors)) or None
        parsed_authors, author_postnominals = parse_byline(author_text)
        records.append({'journal_title': document['journal_title'], 'volume': volume, 'issue': issue,
            'publication_year': period['publication_year'] if period else None, 'publication_month': None,
            'publication_date': None, 'date_precision': 'year' if period else 'unknown',
            'issue_year_evidence': period, 'title': title, 'observed_author_text': author_text,
            'authors': parsed_authors,
            'abstract': clean(' '.join(body)) or None, 'printed_start_page': start_page,
            'source_raw_id': 'lexis_publication:' + block['identifier'], 'publisher_article_url': block['linked_url'],
            'source_url': document['url'], 'pdf_path': document['pdf_path'], 'pdf_sha256': document['pdf_sha256'],
            'source_title_page': block['page'], 'source_title_top': block['top'],
            'status': 'REVIEW_LINKED_METADATA_WITH_EXPLICIT_YEAR' if period else 'REVIEW_PUBLICATION_YEAR_UNCONFIRMED',
            'reading_scope': 'public_contents_and_abstract_document_only', 'full_text_reviewed': False})
        if author_postnominals:
            records[-1]['author_postnominals'] = author_postnominals
    return records


def prepare(document_dir, evidence_file, output):
    evidence = json.loads(evidence_file.read_text(encoding='utf-8'))
    years = {(evidence['journal_title'], row['volume'], row['issue']): dict(row,
             source_url=evidence['source_url'], year_basis=evidence['year_basis']) for row in evidence['rows']}
    records, documents = [], []
    for path in sorted(document_dir.glob('*.contents_document.json')):
        document = json.loads(path.read_text(encoding='utf-8'))
        if document['status'] != 'SAVED_CONTENTS_DOCUMENT':
            continue
        if hashlib.sha256(Path(document['pdf_path']).read_bytes()).hexdigest() != document['pdf_sha256']:
            raise ValueError('An original public contents PDF changed')
        extracted = parse_document(document, years)
        records.extend(extracted)
        documents.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'linked_items': len(extracted)})
    output.mkdir(parents=True, exist_ok=False)
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'documents': documents,
        'explicit_year_evidence': str(evidence_file), 'year_evidence_sha256': hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'linked_items': len(records),
        'statuses': dict(Counter(row['status'] for row in records)),
        'per_journal': dict(Counter(row['journal_title'] for row in records)),
        'unlinked_contents_items_review_required': True, 'article_database_writes': 0, 'full_text_reviewed': False}
    for name, data in [('records.json', records), ('report.json', result)]:
        with (output / name).open('x', encoding='utf-8') as stream:json.dump(data, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document-dir', type=Path, required=True)
    parser.add_argument('--year-evidence', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.document_dir.resolve(), args.year_evidence.resolve(), args.output_dir.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != 'documents'}, indent=2))
