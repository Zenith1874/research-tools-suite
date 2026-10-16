#!/usr/bin/env python3
"""Cross-check rendered header OCR against actual publisher citation footers."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import fitz


CODES = {'Australian Tax Review': r'AT\s*Rev', 'Insolvency Law Journal': r'Insolv\s*LJ',
         'Journal of Banking and Finance - Law and Practice': r'JBFLP', 'Tort Law Review': r'Tort\s*L\s*Rev'}


def assess_header(ocr_lines, citation_text, journal, expected_volume, expected_issue):
    header = ' '.join(ocr_lines)
    match = re.search(r'Volume\s+(\d+)\s*,?\s*(?:Number|No\.?)\s*(\d+)', header, re.I)
    year_lines = [line for line in ocr_lines if re.fullmatch(r'(?:[A-Za-z]+\s+)?(?:19|20)\d{2}', line.strip())]
    citation = re.findall(r'\((\d{4})\)\s+(\d+)\s+' + CODES[journal] + r'\s+\d+', citation_text, re.I)
    evidence = {'observed_ocr_header': header, 'observed_citation_year_volumes': sorted(set(citation)),
                'expected_post_volume': expected_volume, 'expected_post_issue': expected_issue}
    if not match or len(year_lines) != 1 or len(set(citation)) != 1:
        return 'REVIEW_HEADER_OR_CITATION_UNCONFIRMED', evidence
    year = int(re.search(r'\d{4}', year_lines[0])[0]);volume = int(match[1]);issue = match[2]
    evidence.update(header_year=year, header_volume=volume, header_issue=issue, header_period_label=year_lines[0])
    if citation[0] != (str(year), str(volume)):
        return 'REVIEW_HEADER_CITATION_CONFLICT', evidence
    if expected_volume != volume or str(expected_issue) != issue:
        return 'REVIEW_POST_PDF_ISSUE_CONFLICT', evidence
    return 'HEADER_AND_CITATION_RECONCILED', evidence


def prepare(image_dir, ocr_dir, output, footer_review_dir=None, footer_ocr_dir=None):
    inputs = json.loads((image_dir / 'input_records.json').read_text(encoding='utf-8'))
    footers = {}
    if footer_review_dir is not None:
        for footer in json.loads((footer_review_dir / 'records.json').read_text(encoding='utf-8')):
            footer_file = footer_ocr_dir / (Path(footer['png']).stem + '.json')
            recognized = json.loads(footer_file.read_text(encoding='utf-8-sig'))
            if hashlib.sha256(Path(footer['png']).read_bytes()).hexdigest() != recognized['image_sha256']:
                raise ValueError('A recognized citation footer changed')
            footers[Path(footer['metadata']).name] = {'text': recognized['text'], 'ocr_file': str(footer_file),
                'ocr_sha256': hashlib.sha256(footer_file.read_bytes()).hexdigest()}
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for row in inputs:
        metadata_file = Path(row['original_metadata'])
        original = json.loads(metadata_file.read_text(encoding='utf-8'))
        if hashlib.sha256(Path(row['pdf_path']).read_bytes()).hexdigest() != row['pdf_sha256']:
            raise ValueError('An original PDF changed')
        image = Path(row['image']);ocr_file = ocr_dir / (image.stem + '.json')
        ocr = json.loads(ocr_file.read_text(encoding='utf-8-sig'))
        if hashlib.sha256(image.read_bytes()).hexdigest() != ocr['image_sha256']:
            raise ValueError('A recognized header image changed')
        with fitz.open(row['pdf_path']) as document:
            # Body references to earlier volumes are not this issue's citation.
            citation_lines = []
            for page in document:
                for line in page.get_text().splitlines():
                    if re.match(r'^\(\d{4}\)\s+\d+\s+', line.strip()):
                        citation_lines.append(line.strip())
            text = '\n'.join(citation_lines)
            footer = footers.get(metadata_file.name)
            if footer:
                text += '\n' + footer['text']
            status, evidence = assess_header(ocr['lines'], text, row['journal_title'],
                                            row['expected_post_volume'], row['expected_post_issue'])
            pages = []
            for number in range(min(20, len(document))):
                page = document[number]
                lines = [{'text': ''.join(span['text'] for span in line['spans']), 'bbox': line['bbox'],
                          'sizes': sorted({span['size'] for span in line['spans']}),
                          'flags': sorted({span['flags'] for span in line['spans']})}
                         for block in page.get_text('dict')['blocks'] if block.get('type') == 0
                         for line in block['lines']]
                pages.append({'page': number + 1, 'text': page.get_text(), 'lines': lines})
        corrected = dict(original, status=status, header_evidence=evidence, pages=pages,
            original_metadata_path=str(metadata_file), original_metadata_sha256=hashlib.sha256(metadata_file.read_bytes()).hexdigest(),
            ocr_file=str(ocr_file), ocr_sha256=hashlib.sha256(ocr_file.read_bytes()).hexdigest(),
            reading_scope='public_contents_header_and_abstract_document_only', full_text_reviewed=False)
        if footer:
            corrected['additional_footer_ocr_evidence'] = footer
        path = output / metadata_file.name
        with path.open('x', encoding='utf-8') as stream:json.dump(corrected, stream, ensure_ascii=False, indent=2)
        records.append({'path': str(path), 'status': status, 'journal_title': row['journal_title'],
                        'header_evidence': evidence})
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'documents': len(records),
        'statuses': dict(Counter(row['status'] for row in records)), 'records': records,
        'article_database_writes': 0, 'raw_originals_overwritten': False, 'full_text_reviewed': False,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (output / 'report.json').open('x', encoding='utf-8') as stream:json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-dir', type=Path, required=True)
    parser.add_argument('--ocr-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--footer-review-dir', type=Path)
    parser.add_argument('--footer-ocr-dir', type=Path)
    args = parser.parse_args()
    if bool(args.footer_review_dir) != bool(args.footer_ocr_dir):
        parser.error('Supply both footer evidence directories')
    result = prepare(args.image_dir.resolve(), args.ocr_dir.resolve(), args.output_dir.resolve(),
        args.footer_review_dir.resolve() if args.footer_review_dir else None,
        args.footer_ocr_dir.resolve() if args.footer_ocr_dir else None)
    print(json.dumps({key: value for key, value in result.items() if key != 'records'}, indent=2))
