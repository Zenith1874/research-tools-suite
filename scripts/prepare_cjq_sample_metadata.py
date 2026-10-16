#!/usr/bin/env python3
"""Read a public sample's contents and bounded, explicitly labelled abstracts."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import fitz


def clean(value):
    return ' '.join(value.split())


def abstract_region(page):
    lines = [line for block in page.get_text('dict')['blocks'] if block.get('type') == 0 for line in block['lines']]
    marker = next((number for number, line in enumerate(lines)
                   if clean(''.join(span['text'] for span in line['spans'])) == 'Abstract'), None)
    if marker is None:
        raise ValueError('An explicit abstract heading is missing')
    selected, previous_bottom = [], None
    for line in lines[marker + 1:]:
        spans = [span for span in line['spans'] if span['size'] >= 8]
        text = clean(' '.join(span['text'] for span in spans))
        if not text:
            continue
        top, bottom = line['bbox'][1], line['bbox'][3]
        if previous_bottom is not None and top - previous_bottom >= 9:
            break
        if max(span['size'] for span in spans) >= 11:
            break
        selected.append((text, line['bbox']))
        previous_bottom = max(previous_bottom or 0, bottom)
    if not selected:
        raise ValueError('The abstract block is empty')
    return clean(' '.join(text for text, _ in selected)), selected[0][1][1], selected[-1][1][3]


def prepare(pdf_path, source_url, output):
    output.mkdir(parents=True, exist_ok=False)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    records = []
    with fitz.open(pdf_path) as pdf:
        cover = pdf[0].get_text();citation = pdf[3].get_text()
        match = re.search(r'Vol\.\s*(\d+)\s+Issue\s*(\d+)\s+(\d{4})', cover)
        if not match or f'({match[3]}) {match[1]} C.J.Q.' not in citation:
            raise ValueError('The cover and explicit citation period do not agree')
        volume, issue, year = int(match[1]), match[2], int(match[3])
        toc = [clean(line) for line in pdf[2].get_text().splitlines() if clean(line)]
        pending, section = [], None
        for line in toc:
            if line in ('Editors Note', 'Notes', 'Articles'):
                section = line;pending = [];continue
            if section is None:continue
            if not line.isdecimal():
                pending.append(line);continue
            if len(pending) < 2:
                raise ValueError('A contents item lacks a title or supplied byline')
            start = int(line);title = clean(' '.join(pending[:-1]));byline = pending[-1]
            physical = start + 3
            page = pdf[physical]
            if not re.search(rf'(?m)^{start}$', page.get_text()):
                raise ValueError('The printed start page is not corroborated')
            abstract, top, bottom = abstract_region(page)
            crop = output / f'abstract_page_{start:03d}.png'
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), clip=fitz.Rect(0, top - 20, page.rect.width, bottom + 8)).save(crop)
            identity = ['0261-9261', volume, issue, year, start, title, byline]
            records.append({'journal_title': 'Civil Justice Quarterly', 'title': title,
                'authors': [clean(name) for name in re.split(r'\s+and\s+', byline) if clean(name)],
                'observed_author_text': byline, 'volume': volume, 'issue': issue,
                'publication_year': year, 'publication_month': None, 'publication_date': None, 'date_precision': 'year',
                'source_raw_id': 'publisher_printed_item:' + hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                'source_url': source_url, 'pdf_path': str(pdf_path), 'pdf_sha256': digest,
                'printed_start_page': start, 'source_title_page': 3, 'abstract_physical_page': physical + 1,
                'abstract': abstract, 'abstract_crop': str(crop), 'abstract_crop_sha256': hashlib.sha256(crop.read_bytes()).hexdigest(),
                'issue_year_evidence': {'year_basis': 'publisher_cover_and_explicit_citation_year', 'source_url': source_url,
                    'publication_year': year, 'copyright_year_separately_reported': 2023},
                'record_type': 'editorial' if section == 'Editors Note' else 'case-note' if section == 'Notes' else 'journal-article',
                'status': 'REVIEW_PUBLIC_SAMPLE_METADATA_AND_LABELLED_ABSTRACT',
                'reading_scope': 'contents and six selected title/abstract regions; article bodies not reviewed',
                'full_text_reviewed': False})
            pending = []
    result = {'prepared_at': datetime.now(timezone.utc).isoformat(), 'records': len(records),
        'source_pdf_sha256': digest, 'sample_issue_only': True, 'full_text_reviewed': False,
        'article_database_writes': 0, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name, value in [('records.json', records), ('report.json', result)]:
        with (output / name).open('x', encoding='utf-8') as stream:json.dump(value, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.pdf.resolve(), args.source_url, args.output_dir.resolve()), indent=2))
