#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create an auditable, resumable OCR text layer for a research source.

The original PDF is never modified.  Each rendered page is OCR'd into its own
UTF-8 text file and a JSON manifest records the input hash, OCR configuration,
page status, and derived text hashes.  The per-page files make interrupted
runs resumable and keep later page-level evidence notes traceable.

This script intentionally does not infer theory claims, constructs, measures,
or methods from OCR output.  It only creates a derived text layer; a human
reading/evidence pass must still code claims and page locators.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit('PyMuPDF is required: python3 -m pip install --user pymupdf') from exc


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'data' / 'research_source_text'

# When this file is executed directly, Python puts ``scripts/`` rather than
# the repository root on sys.path.  The chapter map is intentionally sourced
# from the existing catalog-expansion module, so make that import reproducible
# for both direct execution and test imports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(chunk_size), b''):
            digest.update(block)
    return digest.hexdigest()


def safe_source_id(value: str) -> str:
    value = re.sub(r'[^A-Za-z0-9._-]+', '-', str(value or 'source')).strip('-')
    return value[:120] or 'source'


def tesseract_version(binary: str) -> str:
    result = subprocess.run([binary, '--version'], check=True,
                            capture_output=True, text=True)
    return (result.stdout or result.stderr).splitlines()[0].strip()


def ocr_page(page, binary: str, languages: str, dpi: int, psm: int) -> str:
    scale = dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale),
                             colorspace=fitz.csRGB, alpha=False)
    result = subprocess.run(
        [binary, 'stdin', 'stdout', '--dpi', str(dpi), '-l', languages,
         '--psm', str(psm)],
        input=pixmap.tobytes('png'),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n').strip() + '\n'


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                         encoding='utf-8')
    os.replace(temporary, path)


def _normalized_text(value: str) -> str:
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', str(value or '').lower())


def build_chapter_map(catalog_path: Path, output_path: Path,
                      pages_dir: Path | None = None,
                      printed_page_offset: int | None = None,
                      pdf_page_count: int | None = None) -> None:
    """Materialize the printed-page chapter map beside the OCR manifest.

    ``source_page`` is the printed page recorded from the attached scan.  A
    PDF page offset may be supplied after checking the scan's front matter.
    Even when a deterministic offset is supplied, the output records whether
    the OCR page contains the catalog title; this remains a review candidate,
    not a primary-source claim.
    """
    try:
        from scripts.research_catalog_expansion import BOOK60_SOURCE_PAGES
    except (ImportError, AttributeError):
        BOOK60_SOURCE_PAGES = {}
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    theories = {item.get('id'): item for item in catalog.get('theories', [])}
    ordered = sorted(BOOK60_SOURCE_PAGES.items(), key=lambda item: item[1])
    chapters = []
    for index, (theory_id, printed_start) in enumerate(ordered):
        next_start = ordered[index + 1][1] if index + 1 < len(ordered) else None
        theory = theories.get(theory_id) or {}
        pdf_start = (printed_start + printed_page_offset
                     if printed_page_offset is not None else None)
        pdf_end = (next_start - 1 + printed_page_offset
                   if next_start is not None and printed_page_offset is not None else None)
        start_text = ''
        if pdf_start is not None and pages_dir is not None:
            text_path = pages_dir / ('page-%04d.txt' % pdf_start)
            if text_path.exists():
                start_text = text_path.read_text(encoding='utf-8', errors='replace')
        normalized_start = _normalized_text(start_text)
        en_match = bool(_normalized_text(theory.get('name')) and
                        _normalized_text(theory.get('name')) in normalized_start)
        zh_match = bool(_normalized_text(theory.get('name_zh')) and
                        _normalized_text(theory.get('name_zh')) in normalized_start)
        if pdf_start is None:
            mapping_status = 'printed_chapter_start_only'
        elif en_match or zh_match:
            mapping_status = 'ocr_start_candidate'
        else:
            mapping_status = 'offset_applied_title_not_exact'
        chapters.append({
            'theory_id': theory_id,
            'title': theory.get('name'),
            'title_zh': theory.get('name_zh'),
            'printed_page_start': printed_start,
            'printed_page_end': next_start - 1 if next_start is not None else None,
            'pdf_page_start': pdf_start,
            'pdf_page_end': pdf_end,
            'page_offset': printed_page_offset,
            'ocr_title_match': {'english': en_match, 'chinese': zh_match},
            'status': mapping_status,
            'note': ('Printed chapter starts came from the attached scan. The PDF offset is an '
                     'OCR/title-checked locator candidate; read the chapter and review the '
                     'exact page before citing a claim.'),
        })
    write_json(output_path, {
        'schema_version': 1,
        'source_pack': 'management-organization-60',
        'pdf_page_count': pdf_page_count,
        'printed_to_pdf_offset': printed_page_offset,
        'chapters': chapters,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--source-id', default='management-organization-60-book-scan')
    parser.add_argument('--tesseract-bin', default='tesseract')
    parser.add_argument('--languages', default='eng+chi_sim')
    parser.add_argument('--dpi', type=int, default=180)
    parser.add_argument('--psm', type=int, default=3)
    parser.add_argument('--printed-page-offset', type=int, default=None,
                        help='PDF page minus printed page after front-matter review')
    parser.add_argument('--start-page', type=int, default=1,
                        help='1-based PDF page to start with')
    parser.add_argument('--end-page', type=int, default=0,
                        help='1-based inclusive PDF page; 0 means the final page')
    parser.add_argument('--limit', type=int, default=0,
                        help='maximum pages to process in this invocation; 0 means no limit')
    parser.add_argument('--force', action='store_true',
                        help='re-OCR pages even if a matching derived text file exists')
    args = parser.parse_args()

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit('input PDF not found: %s' % input_path)
    if args.dpi < 120 or args.dpi > 400:
        raise SystemExit('--dpi must be between 120 and 400')
    if args.start_page < 1:
        raise SystemExit('--start-page must be >= 1')

    binary = args.tesseract_bin
    try:
        version = tesseract_version(binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit('cannot execute tesseract %r: %s' % (binary, exc)) from exc

    output_dir = args.output_dir.expanduser().resolve() / safe_source_id(args.source_id)
    pages_dir = output_dir / 'pages'
    pages_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / 'source_text_manifest.json'
    chapter_map_path = output_dir / 'chapter_map.json'

    input_hash = sha256_file(input_path)
    document = fitz.open(str(input_path))
    try:
        page_count = document.page_count
        end_page = args.end_page or page_count
        if end_page > page_count or end_page < args.start_page:
            raise SystemExit('page range is outside the PDF: 1-%d' % page_count)

        manifest = load_manifest(manifest_path)
        if manifest and (manifest.get('input_sha256') != input_hash or
                         manifest.get('ocr', {}).get('dpi') != args.dpi or
                         manifest.get('ocr', {}).get('languages') != args.languages or
                         manifest.get('ocr', {}).get('psm') != args.psm):
            raise SystemExit(
                'existing manifest uses a different input/config; choose a new --output-dir or --force with a clean derived directory')

        manifest.setdefault('schema_version', 1)
        manifest.update({
            'source_id': args.source_id,
            'source_type': 'image_pdf',
            'input_path': str(input_path),
            'input_sha256': input_hash,
            'page_count': page_count,
            'derived_at': time.strftime('%Y-%m-%d'),
            'ocr': {
                'engine': 'tesseract',
                'version': version,
                'languages': args.languages,
                'dpi': args.dpi,
                'psm': args.psm,
                'text_encoding': 'utf-8',
            },
            'text_policy': 'Derived OCR only; original PDF remains authoritative and unchanged.',
        })
        pages = {int(item['pdf_page']): item for item in manifest.get('pages', [])
                 if isinstance(item, dict) and str(item.get('pdf_page', '')).isdigit()}
        processed = 0
        for pdf_page in range(args.start_page, end_page + 1):
            text_path = pages_dir / ('page-%04d.txt' % pdf_page)
            existing = pages.get(pdf_page)
            if (not args.force and existing and existing.get('status') == 'complete' and
                    text_path.exists() and sha256_file(text_path) == existing.get('text_sha256')):
                continue
            if args.limit and processed >= args.limit:
                break
            started = time.time()
            try:
                text = ocr_page(document.load_page(pdf_page - 1), binary,
                                args.languages, args.dpi, args.psm)
                text_bytes = text.encode('utf-8')
                temporary = text_path.with_suffix('.txt.tmp')
                temporary.write_bytes(text_bytes)
                os.replace(temporary, text_path)
                pages[pdf_page] = {
                    'pdf_page': pdf_page,
                    'text_path': str(text_path.relative_to(output_dir)),
                    'text_sha256': sha256_bytes(text_bytes),
                    'char_count': len(text),
                    'status': 'complete',
                    'elapsed_seconds': round(time.time() - started, 2),
                }
                processed += 1
                print('[%d/%d] page %d chars=%d %.1fs' %
                      (pdf_page, end_page, pdf_page, len(text), time.time() - started),
                      flush=True)
            except Exception as exc:  # keep a resumable failure record
                pages[pdf_page] = {
                    'pdf_page': pdf_page,
                    'text_path': str(text_path.relative_to(output_dir)),
                    'status': 'error',
                    'error': str(exc)[:500],
                }
                print('[%d/%d] page %d ERROR %s' %
                      (pdf_page, end_page, pdf_page, str(exc)[:300]), flush=True)
                write_json(manifest_path, dict(manifest, pages=list(pages.values())))
                raise
            manifest['pages'] = [pages[key] for key in sorted(pages)]
            write_json(manifest_path, manifest)
        manifest['pages'] = [pages[key] for key in sorted(pages)]
        manifest['completed_pages'] = sum(item.get('status') == 'complete'
                                          for item in pages.values())
        manifest['failed_pages'] = sum(item.get('status') == 'error'
                                       for item in pages.values())
        write_json(manifest_path, manifest)
    finally:
        document.close()

    build_chapter_map(ROOT / 'data' / 'research_catalog.json', chapter_map_path,
                      pages_dir=pages_dir,
                      printed_page_offset=args.printed_page_offset,
                      pdf_page_count=page_count)
    print('manifest:', manifest_path)
    print('chapter map:', chapter_map_path)
    print('completed pages:', manifest.get('completed_pages', 0), '/', manifest.get('page_count'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
