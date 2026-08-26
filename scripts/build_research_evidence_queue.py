#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a blank, auditable T-C-M coding queue for the supplied book scan.

This creates workflow metadata, not scholarly findings.  It deliberately does
not copy OCR text, scale items, or infer a Theory-Construct-Method relationship
from the catalog.  If an existing queue is present, user-entered coding fields
are preserved while source locators are refreshed from the current catalog and
chapter map.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import os


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'data' / 'research_catalog.json'
CHAPTER_MAP_PATH = (
    ROOT / 'data' / 'research_source_text' /
    'management-organization-60-book-scan' / 'chapter_map.json'
)
DEFAULT_OUTPUT = (
    ROOT / 'data' / 'research_evidence' /
    'management-organization-60_evidence_queue.json'
)

CODING_TEMPLATE = {
    'status': 'needs_human_coding',
    'definition': None,
    'constructs': [],
    'mechanisms': [],
    'boundary_conditions': [],
    'criticisms': [],
    'measurement_scales': [],
    'methods': [],
    'cited_works': [],
}


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback
    return value


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    os.replace(temporary, path)


def _source_locator(theory, chapter_map, map_meta):
    row = chapter_map.get(theory.get('id')) or {}
    source = theory.get('source_text') or {}
    return {
        'source_pack': map_meta.get('source_pack') or theory.get('source_pack'),
        'printed_page_start': row.get('printed_page_start', theory.get('source_page')),
        'printed_page_end': row.get('printed_page_end'),
        'pdf_page_start': row.get('pdf_page_start', source.get('pdf_page_start')),
        'pdf_page_end': row.get('pdf_page_end', source.get('pdf_page_end')),
        'pdf_page_count': map_meta.get('pdf_page_count', source.get('pdf_page_count')),
        'page_offset': row.get('page_offset', map_meta.get('printed_to_pdf_offset')),
        'locator_status': row.get('status', source.get('chapter_locator_status', 'not_ingested')),
        'ocr_title_match': row.get('ocr_title_match', source.get('ocr_title_match', {})),
    }


def build_queue(catalog_path=CATALOG_PATH, chapter_map_path=CHAPTER_MAP_PATH,
                output_path=DEFAULT_OUTPUT):
    catalog = _read_json(Path(catalog_path), {})
    chapter_payload = _read_json(Path(chapter_map_path), {})
    if not isinstance(catalog, dict):
        raise ValueError('catalog must be a JSON object')
    if not isinstance(chapter_payload, dict):
        chapter_payload = {}
    chapter_map = {
        row.get('theory_id'): row
        for row in chapter_payload.get('chapters', [])
        if isinstance(row, dict) and row.get('theory_id')
    }
    map_meta = {
        'source_pack': chapter_payload.get('source_pack'),
        'pdf_page_count': chapter_payload.get('pdf_page_count'),
        'printed_to_pdf_offset': chapter_payload.get('printed_to_pdf_offset'),
    }

    previous_payload = _read_json(Path(output_path), {})
    previous_rows = {
        row.get('theory_id'): row
        for row in previous_payload.get('chapters', [])
        if isinstance(row, dict) and row.get('theory_id')
    } if isinstance(previous_payload, dict) else {}

    chapters = []
    for theory in catalog.get('theories', []):
        if theory.get('source_pack') != 'management-organization-60':
            continue
        theory_id = theory.get('id')
        previous = previous_rows.get(theory_id, {})
        coding = dict(CODING_TEMPLATE)
        coding.update(previous.get('coding') or {})
        row = {
            'evidence_id': 'book60:%s' % theory_id,
            'theory_id': theory_id,
            'theory_name': theory.get('name'),
            'theory_name_zh': theory.get('name_zh'),
            'source': _source_locator(theory, chapter_map, map_meta),
            'coding': coding,
            'evidence': list(previous.get('evidence') or []),
            'review_flags': sorted(set((previous.get('review_flags') or []) + [
                'ocr_derived_locator',
                'original_scan_required',
                'no_tcm_claim_until_human_coding',
            ])),
        }
        chapters.append(row)

    payload = {
        'schema_version': 1,
        'generated_at': date.today().isoformat(),
        'source_policy': (
            'Workflow metadata only. OCR text is not copied here; every evidence '
            'entry must be checked against the original scan or a legally accessible '
            'primary source before it is used in a manuscript.'
        ),
        'coding_fields': list(CODING_TEMPLATE),
        'evidence_entry_fields': [
            'printed_page', 'pdf_page', 'kind', 'quote_or_note', 'source_check',
        ],
        'chapters': chapters,
    }
    _write_json(Path(output_path), payload)
    return payload


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', type=Path, default=CATALOG_PATH)
    parser.add_argument('--chapter-map', type=Path, default=CHAPTER_MAP_PATH)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = build_queue(args.catalog, args.chapter_map, args.output)
    print('wrote', args.output)
    print('chapters:', len(payload['chapters']))
    print('status:', 'needs_human_coding')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
