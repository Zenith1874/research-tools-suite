#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract embedded text from locally downloaded, legally open research PDFs.

This is deliberately separate from OCR.  A PDF with no usable text layer is
reported as ``text_layer_missing`` and is not silently treated as readable.
Original PDFs remain untouched; per-page derived text and SHA-256 manifests are
written under the gitignored research source-text directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import os
import re
import time

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit('PyMuPDF is required: python3 -m pip install --user pymupdf') from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'data' / 'research_sources'
DEFAULT_OUTPUT = ROOT / 'data' / 'research_source_text' / 'open-access'


def sha256_file(path: Path, chunk_size=1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(chunk_size), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_id(path: Path) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '-', path.stem).strip('-') or 'source'


def _read_manifest(path: Path):
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    os.replace(temporary, path)


def extract_pdf(pdf_path: Path, output_root: Path, force=False) -> dict:
    source_id = safe_id(pdf_path)
    output_dir = output_root / source_id
    pages_dir = output_dir / 'pages'
    manifest_path = output_dir / 'source_text_manifest.json'
    input_sha256 = sha256_file(pdf_path)
    previous = _read_manifest(manifest_path)
    if (not force and previous.get('input_sha256') == input_sha256 and
            previous.get('status') in {'complete', 'text_layer_missing'}):
        return previous

    document = fitz.open(str(pdf_path))
    pages = []
    try:
        pages_dir.mkdir(parents=True, exist_ok=True)
        for number in range(1, document.page_count + 1):
            page = document.load_page(number - 1)
            text = page.get_text('text') or ''
            text = text.replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'
            text_path = pages_dir / ('page-%04d.txt' % number)
            text_bytes = text.encode('utf-8')
            temporary = text_path.with_suffix('.txt.tmp')
            temporary.write_bytes(text_bytes)
            os.replace(temporary, text_path)
            pages.append({
                'pdf_page': number,
                'text_path': str(text_path.relative_to(output_dir)),
                'text_sha256': hashlib.sha256(text_bytes).hexdigest(),
                'char_count': len(text),
                'status': 'complete' if text.strip() else 'empty',
            })
    finally:
        page_count = document.page_count
        document.close()

    total_chars = sum(row['char_count'] for row in pages)
    nonempty_pages = sum(row['char_count'] > 1 for row in pages)
    status = 'complete' if total_chars >= 500 and nonempty_pages else 'text_layer_missing'
    manifest = {
        'schema_version': 1,
        'source_id': source_id,
        'source_type': 'open_access_pdf_embedded_text',
        'input_filename': pdf_path.name,
        'input_sha256': input_sha256,
        'page_count': page_count,
        'derived_at': time.strftime('%Y-%m-%d'),
        'extraction': {'engine': 'PyMuPDF', 'mode': 'embedded_text', 'text_encoding': 'utf-8'},
        'status': status,
        'total_chars': total_chars,
        'nonempty_pages': nonempty_pages,
        'text_policy': 'Derived local text only; the original OA PDF remains authoritative.',
        'pages': pages,
    }
    _write_json(manifest_path, manifest)
    return manifest


def build_index(input_dir=DEFAULT_INPUT, output_dir=DEFAULT_OUTPUT, force=False):
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    manifests = []
    for pdf_path in sorted(input_dir.glob('*.pdf')):
        manifests.append(extract_pdf(pdf_path, output_dir, force=force))
    index = {
        'schema_version': 1,
        'source_policy': (
            'Only locally downloaded open-access PDFs are included. This index '
            'records extraction status and page locators, not verified scholarly claims.'
        ),
        'sources': [{
            'source_id': item.get('source_id'),
            'input_filename': item.get('input_filename'),
            'input_sha256': item.get('input_sha256'),
            'page_count': item.get('page_count'),
            'status': item.get('status'),
            'total_chars': item.get('total_chars'),
            'nonempty_pages': item.get('nonempty_pages'),
        } for item in manifests],
    }
    _write_json(output_dir / 'source_text_index.json', index)
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    index = build_index(args.input_dir, args.output_dir, force=args.force)
    print('wrote', args.output_dir / 'source_text_index.json')
    for row in index['sources']:
        print('%-34s %-19s pages=%s chars=%s' % (
            row['input_filename'], row['status'], row['page_count'], row['total_chars']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
