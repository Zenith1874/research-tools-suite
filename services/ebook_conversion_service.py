# -*- coding: utf-8 -*-
"""Local-only PDF to e-reader conversion.

Two reading copies are produced from the same parse of a source PDF:

``epub``
    A reflowable EPUB 3 book.  Prose is re-typeset so the reader controls font
    size, and tables and figures are rendered as pictures rather than being
    re-typeset into HTML that would misalign.  This is the phone format.

``device_pdf``
    The source pages with margins cropped, multi-column pages split into
    single-column panels, and every panel refitted to one screen of a chosen
    device.  Formulas, tables and figures stay pixel-exact, so this is the
    e-ink format for papers.  It also works on scanned PDFs, which cannot be
    reflowed at all.

Files never leave the machine.  Uploaded originals and every output live in a
gitignored private job folder; locally selected originals are read in place and
are never modified, moved, or deleted.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import smtplib
import ssl
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Iterable

from services.pdf_translation_service import (
    PdfFormatError,
    ReadingBlock,
    ReadingLayout,
    extract_reading_layout,
)


EBOOK_MAX_UPLOAD_BYTES = int(os.environ.get('EBOOK_MAX_UPLOAD_BYTES', 120 * 1024 * 1024))
EBOOK_MAX_FOLDER_FILES = int(os.environ.get('EBOOK_MAX_FOLDER_FILES', 800))
EBOOK_MAX_SCAN_DEPTH = int(os.environ.get('EBOOK_MAX_SCAN_DEPTH', 6))
EBOOK_MAX_OUTPUT_PAGES = int(os.environ.get('EBOOK_MAX_OUTPUT_PAGES', 4000))
EBOOK_EMAIL_MAX_BYTES = int(os.environ.get('EBOOK_EMAIL_MAX_BYTES', 24 * 1024 * 1024))

_JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')
_EMAIL_RE = re.compile(r'^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$')
# EPUB entries use a fixed timestamp so the same PDF and options always produce
# a byte-identical book, which keeps the recorded output SHA-256 meaningful.
_EPUB_TIMESTAMP = (2000, 1, 1, 0, 0, 0)
_FORMATS = ('epub', 'device_pdf')


DEVICE_PROFILES: dict[str, dict] = {
    'kindle_paperwhite': {
        'label': 'Kindle Paperwhite / Signature（6.8″）',
        'screen': (1236, 1648), 'family': 'kindle',
    },
    'kindle_basic': {
        'label': 'Kindle 入门款 / Kobo Clara（6″）',
        'screen': (1072, 1448), 'family': 'kindle',
    },
    'kindle_oasis': {
        'label': 'Kindle Oasis（7″）',
        'screen': (1264, 1680), 'family': 'kindle',
    },
    'kindle_scribe': {
        'label': 'Kindle Scribe（10.2″）',
        'screen': (1860, 2480), 'family': 'kindle',
    },
    'phone': {
        'label': '手机竖屏（约 19.5:9）',
        'screen': (1080, 2160), 'family': 'phone',
    },
    'tablet': {
        'label': '平板 / iPad（约 4:3）',
        'screen': (1640, 2160), 'family': 'tablet',
    },
}
DEFAULT_DEVICE = 'kindle_paperwhite'


class EbookConversionError(RuntimeError):
    """A conversion or request error that never contains document text."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    name = Path(str(value or '').replace('\\', '/')).name.strip()
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', name)
    name = name.strip(' .') or 'document.pdf'
    return name[:150]


def _output_stem(value: str) -> str:
    stem = Path(_safe_filename(value)).stem
    return stem[:120] or 'document'


def normalize_options(options: dict | None) -> dict:
    raw = options if isinstance(options, dict) else {}
    formats = [item for item in (raw.get('formats') or []) if item in _FORMATS]
    if not formats:
        formats = ['epub', 'device_pdf']
    device = raw.get('device')
    if device not in DEVICE_PROFILES:
        device = DEFAULT_DEVICE
    return {
        'formats': sorted(set(formats), key=_FORMATS.index),
        'device': device,
        'include_figures': raw.get('include_figures', True) is not False,
        'split_columns': raw.get('split_columns', True) is not False,
        'trim_margins': raw.get('trim_margins', True) is not False,
        'figure_dpi': max(96, min(300, int(raw.get('figure_dpi') or 190))),
    }


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------

_EPUB_CSS = """@charset "utf-8";
html, body { margin: 0; padding: 0; }
body { font-family: serif; line-height: 1.55; margin: 0 5%; text-align: justify; }
h1, h2, h3 { line-height: 1.3; text-align: left; page-break-after: avoid;
             margin: 1.1em 0 .5em; font-family: sans-serif; }
h1 { font-size: 1.45em; } h2 { font-size: 1.2em; } h3 { font-size: 1.05em; }
p { margin: 0 0 .6em; text-indent: 0; widows: 2; orphans: 2; }
figure { margin: 1.1em 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; height: auto; }
figcaption { font-size: .82em; color: #555; margin-top: .3em; text-align: center; }
.source-note { font-size: .8em; color: #666; text-align: left; }
"""


def _xhtml_document(title: str, body: str, language: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{language}" lang="{language}">\n'
        f'<head><meta charset="utf-8"/><title>{html.escape(title)}</title>'
        '<link rel="stylesheet" type="text/css" href="../style.css"/></head>\n'
        f'<body>\n{body}\n</body>\n</html>\n'
    )


def _detect_language(blocks: Iterable[ReadingBlock]) -> str:
    sample = []
    total = 0
    for block in blocks:
        if block.kind == 'figure' or not block.text:
            continue
        sample.append(block.text)
        total += len(block.text)
        if total > 4000:
            break
    text = ''.join(sample)
    if not text:
        return 'en'
    cjk = sum(1 for char in text if '㐀' <= char <= '鿿')
    return 'zh' if cjk >= len(text) * .2 else 'en'


def _heading_level(font_size: float, body_size: float) -> int:
    if body_size <= 0:
        return 2
    if font_size >= body_size * 1.42:
        return 1
    if font_size >= body_size * 1.16:
        return 2
    return 3


@dataclass
class _Chapter:
    index: int
    title: str
    parts: list[str]
    headings: list[tuple[str, str, int]]  # (anchor, text, level)
    pages: list[tuple[str, int]]          # (anchor, source page number)

    @property
    def href(self) -> str:
        return f'text/ch{self.index:03d}.xhtml'


def _chapter_plan(layout: ReadingLayout, body_size: float) -> list[list[ReadingBlock]]:
    """Group reading blocks into chapters, splitting at substantial headings."""
    chapters: list[list[ReadingBlock]] = []
    current: list[ReadingBlock] = []
    for block in layout.blocks:
        starts_chapter = (
            block.kind == 'heading'
            and _heading_level(block.font_size, body_size) <= 2
            and len(current) >= 4
        )
        if starts_chapter or len(current) >= 140:
            chapters.append(current)
            current = []
        current.append(block)
    if current:
        chapters.append(current)
    return chapters or [[]]


def _render_figure(document, block: ReadingBlock, dpi: int) -> bytes | None:
    import pymupdf
    page = document[block.page_index]
    rect = pymupdf.Rect(*block.rect) & page.rect
    if rect.is_empty or rect.width < 8 or rect.height < 8:
        return None
    # Cap the long edge so a full-page figure cannot inflate the book.
    effective = min(dpi, max(96, int(1600 / max(rect.width, rect.height) * 72)))
    try:
        pixmap = page.get_pixmap(clip=rect, dpi=effective, alpha=False)
        return pixmap.tobytes('png')
    except Exception:
        return None


def build_epub(layout: ReadingLayout, source_path: Path, output_path: Path,
               options: dict, title: str | None = None) -> dict:
    """Write a reflowable EPUB 3 book from an extracted reading layout."""
    import pymupdf

    prose_blocks = [block for block in layout.blocks if block.kind != 'figure']
    if not prose_blocks:
        raise EbookConversionError('这份 PDF 没有文本层，无法重排为 EPUB；请改用裁边分栏 PDF')

    body_size = layout.body_font_size or 9.0
    language = _detect_language(layout.blocks)
    book_title = (title or layout.title or _output_stem(source_path.name)).strip()
    author = layout.author or '未标注作者'
    book_id = 'urn:uuid:' + str(uuid.UUID(
        hashlib.sha256(
            f'{book_title}|{layout.page_count}|{len(layout.blocks)}'.encode('utf-8')
        ).hexdigest()[:32]))

    chapters: list[_Chapter] = []
    images: dict[str, bytes] = {}
    figures_rendered = 0
    figures_failed = 0
    seen_pages: set[int] = set()
    heading_serial = 0

    with pymupdf.open(source_path) as document:
        for chapter_index, blocks in enumerate(_chapter_plan(layout, body_size), start=1):
            chapter = _Chapter(index=chapter_index, title='', parts=[],
                               headings=[], pages=[])
            for block in blocks:
                page_number = block.page_index + 1
                if page_number not in seen_pages:
                    seen_pages.add(page_number)
                    anchor = f'pg{page_number}'
                    chapter.pages.append((anchor, page_number))
                    chapter.parts.append(
                        f'<span epub:type="pagebreak" role="doc-pagebreak" '
                        f'id="{anchor}" aria-label="{page_number}"></span>')
                if block.kind == 'figure':
                    if not options['include_figures']:
                        continue
                    payload = _render_figure(document, block, options['figure_dpi'])
                    if payload is None:
                        figures_failed += 1
                        continue
                    name = f'p{page_number:04d}_{len(images):03d}.png'
                    images[name] = payload
                    figures_rendered += 1
                    chapter.parts.append(
                        f'<figure><img src="../images/{name}" '
                        f'alt="第 {page_number} 页的图或表"/>'
                        f'<figcaption>原文第 {page_number} 页</figcaption></figure>')
                    continue
                text = html.escape(block.text)
                if block.kind == 'heading':
                    heading_serial += 1
                    level = _heading_level(block.font_size, body_size)
                    anchor = f'h{heading_serial}'
                    chapter.headings.append((anchor, block.text, level))
                    if not chapter.title:
                        chapter.title = block.text[:120]
                    chapter.parts.append(
                        f'<h{level} id="{anchor}">{text}</h{level}>')
                else:
                    chapter.parts.append(f'<p>{text}</p>')
            if not chapter.title:
                chapter.title = f'第 {chapter_index} 部分'
            chapters.append(chapter)

    chapters = [chapter for chapter in chapters if chapter.parts]
    if not chapters:
        raise EbookConversionError('这份 PDF 没有可写入 EPUB 的内容')
    for position, chapter in enumerate(chapters, start=1):
        chapter.index = position

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        def store(name: str, payload: bytes | str, compress=zipfile.ZIP_DEFLATED):
            info = zipfile.ZipInfo(name, date_time=_EPUB_TIMESTAMP)
            info.compress_type = compress
            info.external_attr = 0o644 << 16
            archive.writestr(
                info, payload.encode('utf-8') if isinstance(payload, str) else payload)

        store('mimetype', 'application/epub+zip', zipfile.ZIP_STORED)
        store('META-INF/container.xml',
              '<?xml version="1.0" encoding="utf-8"?>\n'
              '<container version="1.0" '
              'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
              '<rootfiles><rootfile full-path="OEBPS/content.opf" '
              'media-type="application/oebps-package+xml"/></rootfiles></container>')
        store('OEBPS/style.css', _EPUB_CSS)
        for chapter in chapters:
            store('OEBPS/' + chapter.href,
                  _xhtml_document(chapter.title, '\n'.join(chapter.parts), language))
        for name, payload in images.items():
            store(f'OEBPS/images/{name}', payload)

        nav_items = '\n'.join(
            f'<li><a href="{chapter.href}">{html.escape(chapter.title)}</a></li>'
            for chapter in chapters)
        page_items = '\n'.join(
            f'<li><a href="{chapter.href}#{anchor}">{number}</a></li>'
            for chapter in chapters for anchor, number in chapter.pages)
        nav_body = (
            f'<nav epub:type="toc" id="toc"><h1>目录</h1><ol>\n{nav_items}\n</ol></nav>\n'
            f'<nav epub:type="page-list" id="page-list" hidden="hidden">'
            f'<h1>原文页码</h1><ol>\n{page_items}\n</ol></nav>')
        nav_document = _xhtml_document('目录', nav_body, language).replace(
            'href="../style.css"', 'href="style.css"')
        store('OEBPS/nav.xhtml', nav_document)

        manifest = [
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
            'properties="nav"/>',
            '<item id="css" href="style.css" media-type="text/css"/>',
        ]
        spine = []
        for chapter in chapters:
            item_id = f'ch{chapter.index:03d}'
            manifest.append(
                f'<item id="{item_id}" href="{chapter.href}" '
                'media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="{item_id}"/>')
        for position, name in enumerate(images, start=1):
            manifest.append(
                f'<item id="img{position:03d}" href="images/{name}" media-type="image/png"/>')
        store('OEBPS/content.opf',
              '<?xml version="1.0" encoding="utf-8"?>\n'
              '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
              'unique-identifier="book-id" xml:lang="' + language + '">\n'
              '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
              f'<dc:identifier id="book-id">{html.escape(book_id)}</dc:identifier>\n'
              f'<dc:title>{html.escape(book_title)}</dc:title>\n'
              f'<dc:creator>{html.escape(author)}</dc:creator>\n'
              f'<dc:language>{language}</dc:language>\n'
              f'<dc:source>{html.escape(source_path.name)}</dc:source>\n'
              '<meta property="dcterms:modified">2000-01-01T00:00:00Z</meta>\n'
              '</metadata>\n'
              '<manifest>\n' + '\n'.join(manifest) + '\n</manifest>\n'
              '<spine>\n' + '\n'.join(spine) + '\n</spine>\n'
              '</package>\n')

    return {
        'format': 'epub',
        'title': book_title,
        'language': language,
        'chapters': len(chapters),
        'headings': heading_serial,
        'paragraphs': sum(1 for block in layout.blocks if block.kind == 'paragraph'),
        'figures_rendered': figures_rendered,
        'figures_failed': figures_failed,
        'source_pages': layout.page_count,
        'reflowable': True,
    }


# ---------------------------------------------------------------------------
# Device-fitted PDF
# ---------------------------------------------------------------------------

def _split_positions(segment: tuple[float, float, float, float],
                     line_rects: list[tuple[float, float, float, float]],
                     slices: int) -> list[float]:
    """Choose horizontal cut lines, preferring real gaps between text lines."""
    x0, y0, x1, y1 = segment
    height = y1 - y0
    inside = sorted(
        (rect for rect in line_rects
         if rect[1] >= y0 - 1 and rect[3] <= y1 + 1
         and max(rect[0], x0) < min(rect[2], x1)),
        key=lambda rect: rect[1])
    gaps: list[tuple[float, float]] = []
    for previous, current in zip(inside, inside[1:]):
        gap = current[1] - previous[3]
        if gap > 1.0:
            gaps.append(((previous[3] + current[1]) / 2, gap))

    cuts: list[float] = []
    for index in range(1, slices):
        ideal = y0 + height * index / slices
        tolerance = height / slices * .38
        best = None
        for position, size in gaps:
            if abs(position - ideal) > tolerance:
                continue
            # Prefer a wide gap, then one close to the ideal cut.
            score = size - abs(position - ideal) * .12
            if best is None or score > best[1]:
                best = (position, score)
        candidate = best[0] if best else ideal
        if cuts and candidate <= cuts[-1] + 4:
            candidate = ideal
        cuts.append(candidate)
    return cuts


def build_device_pdf(layout: ReadingLayout, source_path: Path, output_path: Path,
                     options: dict) -> dict:
    """Crop margins, split columns, and refit every panel to one device screen."""
    import pymupdf

    profile = DEVICE_PROFILES[options['device']]
    screen_width, screen_height = profile['screen']
    target_width = 480.0
    target_height = round(target_width * screen_height / screen_width, 2)
    margin = 4.0
    usable_width = target_width - margin * 2
    usable_height = target_height - margin * 2

    panels_emitted = 0
    blank_pages_skipped = 0
    columns_split = 0
    pages_split_vertically = 0

    with pymupdf.open(source_path) as document, pymupdf.open() as book:
        for geometry in layout.pages:
            source_page = document[geometry.page_index]
            if not options['trim_margins']:
                base_rects = [(0.0, 0.0, geometry.width, geometry.height)]
            elif options['split_columns']:
                base_rects = list(geometry.column_rects)
                if geometry.two_column and len(base_rects) > 1:
                    columns_split += 1
            else:
                base_rects = [geometry.content_rect]

            for segment in base_rects:
                width = segment[2] - segment[0]
                height = segment[3] - segment[1]
                if width < 12 or height < 12:
                    blank_pages_skipped += 1
                    continue
                # Filling the screen width is the magnification we want.  But
                # if the whole panel also fits at nearly that scale, showing it
                # on one screen beats two half-empty ones.
                width_scale = usable_width / width
                whole_scale = min(width_scale, usable_height / height)
                if whole_scale >= width_scale * .82:
                    slices = 1
                else:
                    slices = max(2, min(6, int(-(-height * width_scale // usable_height))))
                    pages_split_vertically += 1
                cuts = _split_positions(segment, geometry.line_rects, slices)
                bounds = [segment[1]] + cuts + [segment[3]]
                for top, bottom in zip(bounds, bounds[1:]):
                    if bottom - top < 8:
                        continue
                    if panels_emitted >= EBOOK_MAX_OUTPUT_PAGES:
                        raise EbookConversionError(
                            f'输出超过 {EBOOK_MAX_OUTPUT_PAGES} 页安全上限')
                    clip = pymupdf.Rect(segment[0], top, segment[2], bottom)
                    scale = min(usable_width / clip.width, usable_height / clip.height)
                    drawn_width = clip.width * scale
                    drawn_height = clip.height * scale
                    left = margin + (usable_width - drawn_width) / 2
                    page = book.new_page(width=target_width, height=target_height)
                    page.show_pdf_page(
                        pymupdf.Rect(left, margin, left + drawn_width, margin + drawn_height),
                        document, geometry.page_index, clip=clip)
                    panels_emitted += 1

        if not panels_emitted:
            raise EbookConversionError('这份 PDF 没有可裁切的内容')
        book.set_metadata({
            'title': (layout.title or _output_stem(source_path.name))[:200],
            'author': layout.author or '',
            'producer': 'research-tools-suite ebook conversion',
        })
        output_path.parent.mkdir(parents=True, exist_ok=True)
        book.save(output_path, garbage=3, deflate=True)

    return {
        'format': 'device_pdf',
        'device': options['device'],
        'device_label': profile['label'],
        'screen': list(profile['screen']),
        'page_size_pt': [target_width, target_height],
        'source_pages': layout.page_count,
        'output_pages': panels_emitted,
        'pages_with_columns_split': columns_split,
        'panels_split_vertically': pages_split_vertically,
        'empty_segments_skipped': blank_pages_skipped,
        'margins_trimmed': options['trim_margins'],
        'vector_content_preserved': True,
    }


def convert_pdf(source_path: Path, output_dir: Path, options: dict | None = None,
                stem: str | None = None) -> dict:
    """Convert one PDF into every requested reading format.

    Each format reports its own outcome, so a scanned PDF still yields a device
    PDF while explicitly recording why EPUB was not possible.
    """
    options = normalize_options(options)
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    if not source_path.is_file():
        raise EbookConversionError('找不到源 PDF 文件')
    stem = _output_stem(stem or source_path.name)

    try:
        layout = extract_reading_layout(source_path, allow_scanned=True)
    except PdfFormatError as exc:
        raise EbookConversionError(str(exc)) from exc

    scanned = bool(layout.scanned_pages) and (
        len(layout.scanned_pages) >= max(1, (layout.page_count + 3) // 4))
    outputs: list[dict] = []
    for output_format in options['formats']:
        entry: dict = {'format': output_format}
        try:
            if output_format == 'epub':
                if scanned:
                    raise EbookConversionError(
                        f'扫描型 PDF（{len(layout.scanned_pages)} / {layout.page_count} 页无文本层）'
                        '无法重排为 EPUB；裁边分栏 PDF 仍然可用')
                filename = f'{stem}.epub'
                audit = build_epub(layout, source_path, output_dir / filename, options)
            else:
                filename = f'{stem}.{options["device"]}.pdf'
                audit = build_device_pdf(layout, source_path, output_dir / filename, options)
            path = output_dir / filename
            entry.update(status='completed', filename=filename,
                         bytes=path.stat().st_size, sha256=_sha256_file(path),
                         audit=audit)
        except EbookConversionError as exc:
            entry.update(status='skipped', reason=str(exc))
        except Exception as exc:  # pragma: no cover - defensive, never leaks text
            entry.update(status='failed', reason=f'{output_format} 生成失败：{type(exc).__name__}')
        outputs.append(entry)

    if not any(entry['status'] == 'completed' for entry in outputs):
        reasons = '；'.join(
            entry.get('reason', '') for entry in outputs if entry.get('reason'))
        raise EbookConversionError(reasons or '没有生成任何输出')

    return {
        'outputs': outputs,
        'source': {
            'pages': layout.page_count,
            'title': layout.title,
            'author': layout.author,
            'figures_detected': layout.figure_count,
            'headings_detected': layout.heading_count,
            'scanned_pages': layout.scanned_pages,
            'two_column_pages': sum(1 for page in layout.pages if page.two_column),
        },
    }


# ---------------------------------------------------------------------------
# Local folder selection
# ---------------------------------------------------------------------------

def scan_folder(root: str | Path, recursive: bool = True,
                limit: int = EBOOK_MAX_FOLDER_FILES) -> dict:
    """List PDFs under a local folder without reading or modifying any of them."""
    raw = str(root or '').strip().strip('"')
    if not raw:
        raise EbookConversionError('请填写本机文件夹路径')
    try:
        base = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    except (OSError, ValueError) as exc:
        raise EbookConversionError('文件夹路径无法解析') from exc
    if not base.exists():
        raise EbookConversionError('文件夹不存在')
    if not base.is_dir():
        raise EbookConversionError('这不是一个文件夹')

    files: list[dict] = []
    truncated = False
    base_depth = len(base.parts)
    stack = [base]
    while stack:
        directory = stack.pop(0)
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.name.startswith('.') or entry.name.startswith('~$'):
                continue
            try:
                if entry.is_dir():
                    if (recursive
                            and len(entry.parts) - base_depth < EBOOK_MAX_SCAN_DEPTH):
                        stack.append(entry)
                    continue
                if entry.suffix.casefold() != '.pdf':
                    continue
                info = entry.stat()
            except (OSError, PermissionError):
                continue
            if len(files) >= limit:
                truncated = True
                stack.clear()
                break
            files.append({
                'path': str(entry),
                'name': entry.name,
                'relative': str(entry.relative_to(base)),
                'bytes': info.st_size,
                'modified': datetime.fromtimestamp(
                    info.st_mtime, timezone.utc).isoformat(timespec='seconds'),
            })

    files.sort(key=lambda item: item['relative'].casefold())
    return {
        'root': str(base),
        'recursive': bool(recursive),
        'files': files,
        'count': len(files),
        'truncated': truncated,
        'limit': limit,
    }


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _mask_email(value: str) -> str:
    value = str(value or '').strip()
    if '@' not in value:
        return ''
    name, _, domain = value.partition('@')
    keep = name[:2] if len(name) > 3 else name[:1]
    return f'{keep}***@{domain}'


def email_configuration(env=None) -> dict:
    """Report SMTP readiness without ever exposing the password."""
    source = env if env is not None else os.environ
    prefixed = ('EBOOK_SMTP_HOST', 'EBOOK_SMTP_PORT', 'EBOOK_SMTP_USER',
                'EBOOK_SMTP_PASS', 'EBOOK_SMTP_FROM', 'EBOOK_SMTP_USE_SSL',
                'EBOOK_SMTP_STARTTLS')
    use_prefixed = any(str(source.get(name) or '').strip() for name in prefixed)

    def setting(prefixed_name, generic_name, default=''):
        return source.get(prefixed_name if use_prefixed else generic_name, default)

    host = str(setting('EBOOK_SMTP_HOST', 'SMTP_HOST') or '').strip()
    user = str(setting('EBOOK_SMTP_USER', 'SMTP_USER') or '').strip()
    password = str(setting('EBOOK_SMTP_PASS', 'SMTP_PASS') or '')
    sender = str(setting('EBOOK_SMTP_FROM', 'SMTP_FROM', user) or user).strip()
    default_to = str(source.get('KINDLE_EMAIL') or '').strip()
    try:
        port = int(setting('EBOOK_SMTP_PORT', 'SMTP_PORT', 587) or 587)
    except (TypeError, ValueError):
        port = 587
    missing = [name for name, value in (
        ('SMTP_HOST', host), ('SMTP_USER', user), ('SMTP_PASS', password)) if not value]
    use_ssl = str(setting('EBOOK_SMTP_USE_SSL', 'SMTP_USE_SSL') or '').strip().casefold() in {
        '1', 'true', 'yes', 'on'} or port == 465
    starttls = str(setting('EBOOK_SMTP_STARTTLS', 'SMTP_STARTTLS', '1') or '1'
                   ).strip().casefold() not in {'0', 'false', 'no', 'off'}
    return {
        'configured': not missing, 'host': host, 'port': port, 'user': user,
        'password': password, 'sender': sender, 'use_ssl': use_ssl,
        'starttls': starttls, 'missing': sorted(set(missing)),
        'sender_masked': _mask_email(sender),
        'default_recipient': default_to,
        'default_recipient_masked': _mask_email(default_to),
        'max_attachment_bytes': EBOOK_EMAIL_MAX_BYTES,
    }


def _send_smtp_message(config: dict, message: EmailMessage) -> None:
    context = ssl.create_default_context()
    if config.get('use_ssl'):
        with smtplib.SMTP_SSL(config['host'], config['port'],
                              timeout=60, context=context) as smtp:
            smtp.login(config['user'], config['password'])
            smtp.send_message(message)
        return
    with smtplib.SMTP(config['host'], config['port'], timeout=60) as smtp:
        smtp.ehlo()
        if config.get('starttls'):
            smtp.starttls(context=context)
            smtp.ehlo()
        smtp.login(config['user'], config['password'])
        smtp.send_message(message)


# ---------------------------------------------------------------------------
# Job manager
# ---------------------------------------------------------------------------

class EbookConversionManager:
    """Persistent, thread-safe conversion queue with private per-job folders."""

    def __init__(self, root: str | Path, max_concurrent_jobs: int | None = None,
                 email_sender: Callable[[dict, EmailMessage], None] | None = None,
                 env=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self.bundle_dir = self.root / '_bundles'
        self.bundle_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._executor: ThreadPoolExecutor | None = None
        self._email_sender = email_sender or _send_smtp_message
        self._env = env if env is not None else os.environ
        try:
            configured = int(os.environ.get('EBOOK_MAX_CONCURRENT_JOBS', 2)
                             if max_concurrent_jobs is None else max_concurrent_jobs)
        except (TypeError, ValueError):
            configured = 2
        self.max_concurrent_jobs = max(1, min(4, configured))
        self._recover_stale_jobs()

    # -- storage ---------------------------------------------------------

    def _job_dir(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
            raise EbookConversionError('任务编号无效')
        return self.root / job_id

    def _read_manifest(self, job_id: str) -> dict:
        path = self._job_dir(job_id) / 'manifest.json'
        if not path.is_file():
            raise EbookConversionError('任务不存在')
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise EbookConversionError('任务记录损坏') from exc

    def _write_manifest(self, job_id: str, manifest: dict) -> None:
        directory = self._job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / 'manifest.json.tmp'
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(directory / 'manifest.json')

    def _recover_stale_jobs(self) -> None:
        for manifest_path in self.root.glob('*/manifest.json'):
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception:
                continue
            if manifest.get('status') not in {'queued', 'running'}:
                continue
            job_id = manifest.get('job_id')
            if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
                continue
            manifest.update(
                status='interrupted', updated_at=_utc_now(),
                error='服务重启前转换未完成；源文件未改动，可直接重试。')
            self._write_manifest(job_id, manifest)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.max_concurrent_jobs,
                    thread_name_prefix='ebook-job')
            return self._executor

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=not wait)

    # -- public API ------------------------------------------------------

    def config(self) -> dict:
        return {
            'privacy_mode': 'local_files_only',
            'formats': list(_FORMATS),
            'devices': [
                {'value': key, 'label': profile['label'], 'screen': list(profile['screen'])}
                for key, profile in DEVICE_PROFILES.items()
            ],
            'default_device': DEFAULT_DEVICE,
            'max_upload_bytes': EBOOK_MAX_UPLOAD_BYTES,
            'max_folder_files': EBOOK_MAX_FOLDER_FILES,
            'max_concurrent_jobs': self.max_concurrent_jobs,
            'job_storage': 'data/ebook_jobs (gitignored, local only)',
            'local_sources_read_in_place': True,
            'email': {
                key: value for key, value in email_configuration(self._env).items()
                if key not in {'password', 'user', 'sender', 'default_recipient'}
            },
        }

    def create_job(self, *, filename: str = '', content: bytes | None = None,
                   local_path: str | None = None, options: dict | None = None,
                   batch_id: str | None = None, start: bool = True) -> dict:
        options = normalize_options(options)
        if batch_id is not None and not _JOB_ID_RE.fullmatch(str(batch_id)):
            batch_id = None
        job_id = uuid.uuid4().hex
        directory = self._job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=True)

        if local_path:
            source = Path(str(local_path).strip().strip('"'))
            try:
                source = source.resolve(strict=True)
            except (OSError, ValueError) as exc:
                shutil.rmtree(directory, ignore_errors=True)
                raise EbookConversionError('本机文件不存在') from exc
            if not source.is_file() or source.suffix.casefold() != '.pdf':
                shutil.rmtree(directory, ignore_errors=True)
                raise EbookConversionError('本机路径不是 PDF 文件')
            size = source.stat().st_size
            display_name = source.name
            source_record = {'mode': 'local_path', 'local_path': str(source),
                             'original_filename': display_name, 'bytes': size}
        else:
            display_name = _safe_filename(filename)
            if Path(display_name).suffix.casefold() != '.pdf':
                shutil.rmtree(directory, ignore_errors=True)
                raise EbookConversionError('当前仅支持 PDF 源文件')
            if not content:
                shutil.rmtree(directory, ignore_errors=True)
                raise EbookConversionError('上传文件为空')
            if len(content) > EBOOK_MAX_UPLOAD_BYTES:
                shutil.rmtree(directory, ignore_errors=True)
                raise EbookConversionError(
                    f'文件超过 {EBOOK_MAX_UPLOAD_BYTES // (1024 * 1024)} MB 上限')
            stored = directory / 'input.pdf'
            stored.write_bytes(content)
            source_record = {'mode': 'upload', 'stored_filename': 'input.pdf',
                             'original_filename': display_name, 'bytes': len(content)}

        now = _utc_now()
        manifest = {
            'job_id': job_id,
            'batch_id': batch_id or job_id,
            'status': 'queued',
            'created_at': now,
            'updated_at': now,
            'options': options,
            'source': source_record,
            'outputs': [],
            'delivery': {},
            'progress': {'percent': 0, 'phase': 'queued'},
        }
        self._write_manifest(job_id, manifest)
        if start:
            self._ensure_executor().submit(self._run_job, job_id)
        return self._public_job(manifest)

    def create_batch(self, items: list[dict], options: dict | None = None) -> dict:
        """Queue several sources under one batch id so they can ship together."""
        if not isinstance(items, list) or not items:
            raise EbookConversionError('没有选择任何文件')
        if len(items) > EBOOK_MAX_FOLDER_FILES:
            raise EbookConversionError(f'一次最多 {EBOOK_MAX_FOLDER_FILES} 个文件')
        batch_id = uuid.uuid4().hex
        created, failed = [], []
        for item in items:
            path = (item or {}).get('path') if isinstance(item, dict) else item
            try:
                created.append(self.create_job(
                    local_path=str(path), options=options, batch_id=batch_id))
            except EbookConversionError as exc:
                failed.append({'path': str(path), 'error': str(exc)})
        if not created:
            raise EbookConversionError(
                failed[0]['error'] if failed else '没有可转换的文件')
        return {'batch_id': batch_id, 'created': len(created),
                'jobs': created, 'failed': failed}

    def retry_job(self, job_id: str) -> dict:
        manifest = self._read_manifest(job_id)
        if manifest.get('status') in {'queued', 'running'}:
            raise EbookConversionError('任务正在队列中')
        manifest.update(status='queued', error=None, updated_at=_utc_now(),
                        outputs=[], progress={'percent': 0, 'phase': 'queued'})
        self._write_manifest(job_id, manifest)
        self._ensure_executor().submit(self._run_job, job_id)
        return self._public_job(manifest)

    def list_jobs(self, limit: int = 60) -> list[dict]:
        jobs = []
        for manifest_path in self.root.glob('*/manifest.json'):
            try:
                jobs.append(self._public_job(
                    json.loads(manifest_path.read_text(encoding='utf-8'))))
            except Exception:
                continue
        jobs.sort(key=lambda job: job.get('created_at') or '', reverse=True)
        return jobs[:limit]

    def get_job(self, job_id: str) -> dict:
        return self._public_job(self._read_manifest(job_id))

    def delete_job(self, job_id: str) -> None:
        directory = self._job_dir(job_id)
        if not directory.is_dir():
            raise EbookConversionError('任务不存在')
        # Only the private job folder is removed.  A locally selected source
        # PDF lives outside this tree and is never touched.
        shutil.rmtree(directory, ignore_errors=True)

    def output_path(self, job_id: str, output_format: str) -> tuple[Path, str]:
        manifest = self._read_manifest(job_id)
        for entry in manifest.get('outputs') or []:
            if entry.get('format') == output_format and entry.get('status') == 'completed':
                path = self._job_dir(job_id) / entry['filename']
                if not path.is_file():
                    raise EbookConversionError('输出文件已被删除')
                return path, entry['filename']
        raise EbookConversionError('该任务没有这种格式的输出')

    # -- worker ----------------------------------------------------------

    def _source_path(self, manifest: dict) -> Path:
        source = manifest.get('source') or {}
        if source.get('mode') == 'local_path':
            path = Path(source.get('local_path') or '')
            if not path.is_file():
                raise EbookConversionError('本机源文件已被移动或删除')
            return path
        return self._job_dir(manifest['job_id']) / (source.get('stored_filename') or 'input.pdf')

    def _run_job(self, job_id: str) -> None:
        try:
            manifest = self._read_manifest(job_id)
        except EbookConversionError:
            return
        manifest.update(status='running', started_at=_utc_now(), updated_at=_utc_now(),
                        worker_pid=os.getpid(),
                        progress={'percent': 5, 'phase': 'parsing'})
        self._write_manifest(job_id, manifest)
        try:
            source = self._source_path(manifest)
            result = convert_pdf(
                source, self._job_dir(job_id), manifest['options'],
                stem=(manifest.get('source') or {}).get('original_filename'))
            manifest.update(
                status='completed', completed_at=_utc_now(), updated_at=_utc_now(),
                outputs=result['outputs'], audit=result['source'], error=None,
                progress={'percent': 100, 'phase': 'done'})
        except EbookConversionError as exc:
            manifest.update(status='failed', updated_at=_utc_now(), error=str(exc),
                            progress={'percent': 100, 'phase': 'failed'})
        except Exception as exc:  # pragma: no cover - defensive
            manifest.update(status='failed', updated_at=_utc_now(),
                            error=f'转换失败：{type(exc).__name__}',
                            progress={'percent': 100, 'phase': 'failed'})
        manifest.pop('worker_pid', None)
        self._write_manifest(job_id, manifest)

    # -- delivery --------------------------------------------------------

    def _completed_outputs(self, job_ids: list[str],
                           output_format: str | None = None) -> list[tuple[dict, dict, Path]]:
        collected: list[tuple[dict, dict, Path]] = []
        for job_id in job_ids:
            manifest = self._read_manifest(job_id)
            for entry in manifest.get('outputs') or []:
                if entry.get('status') != 'completed':
                    continue
                if output_format and entry.get('format') != output_format:
                    continue
                path = self._job_dir(job_id) / entry['filename']
                if path.is_file():
                    collected.append((manifest, entry, path))
        if not collected:
            raise EbookConversionError('没有可用的转换结果')
        return collected

    def _batch_job_ids(self, batch_id: str) -> list[str]:
        if not _JOB_ID_RE.fullmatch(str(batch_id or '')):
            raise EbookConversionError('批次编号无效')
        job_ids = []
        for manifest_path in sorted(self.root.glob('*/manifest.json')):
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception:
                continue
            if manifest.get('batch_id') == batch_id:
                job_ids.append(manifest['job_id'])
        if not job_ids:
            raise EbookConversionError('批次不存在')
        return job_ids

    def build_bundle(self, job_ids: list[str] | None = None,
                     batch_id: str | None = None,
                     output_format: str | None = None) -> tuple[Path, str]:
        """Pack every completed output into one ZIP for a single download."""
        if batch_id:
            job_ids = self._batch_job_ids(batch_id)
        collected = self._completed_outputs(list(job_ids or []), output_format)
        self._prune_bundles()
        label = (batch_id or 'selection')[:12]
        bundle_path = self.bundle_dir / f'ebook-{label}-{uuid.uuid4().hex[:8]}.zip'
        used: set[str] = set()
        with zipfile.ZipFile(bundle_path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for _, entry, path in collected:
                original = Path(entry['filename'])
                name = original.name
                serial = 1
                # Two folders can hold papers with the same file name; keep both.
                while name in used:
                    name = f'{original.stem}-{serial}{original.suffix}'
                    serial += 1
                used.add(name)
                archive.write(path, name)
        return bundle_path, f'ebook-{datetime.now().strftime("%Y%m%d-%H%M")}.zip'

    def _prune_bundles(self, max_age_seconds: int = 24 * 3600) -> None:
        """Download bundles are throwaway copies; do not let them pile up."""
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
        for path in self.bundle_dir.glob('ebook-*.zip'):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                continue

    def deliver_to_folder(self, target: str, job_ids: list[str] | None = None,
                          batch_id: str | None = None,
                          output_format: str | None = None,
                          overwrite: bool = False) -> dict:
        """Copy finished books into a local folder, never overwriting silently."""
        raw = str(target or '').strip().strip('"')
        if not raw:
            raise EbookConversionError('请填写目标文件夹路径')
        try:
            destination = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
        except (OSError, ValueError) as exc:
            raise EbookConversionError('目标文件夹路径无法解析') from exc
        if not destination.is_dir():
            raise EbookConversionError('目标文件夹不存在；请先在本机创建')
        if self.root == destination or self.root in destination.parents:
            raise EbookConversionError('目标文件夹不能位于任务目录内')
        if batch_id:
            job_ids = self._batch_job_ids(batch_id)
        collected = self._completed_outputs(list(job_ids or []), output_format)

        written, skipped = [], []
        for _, entry, path in collected:
            target_path = destination / entry['filename']
            if target_path.exists() and not overwrite:
                skipped.append({'filename': entry['filename'], 'reason': '目标已存在'})
                continue
            try:
                shutil.copy2(path, target_path)
                written.append({'filename': entry['filename'],
                                'bytes': target_path.stat().st_size})
            except OSError as exc:
                skipped.append({'filename': entry['filename'],
                                'reason': f'写入失败：{exc.strerror or "未知错误"}'})
        return {'target': str(destination), 'written': written, 'skipped': skipped,
                'written_count': len(written), 'skipped_count': len(skipped),
                'overwrite': bool(overwrite)}

    def send_to_kindle(self, recipient: str, job_ids: list[str] | None = None,
                       batch_id: str | None = None,
                       output_format: str | None = None) -> dict:
        """Email finished books to a Send-to-Kindle address, one file per message."""
        address = str(recipient or '').strip()
        config = email_configuration(self._env)
        if not address:
            address = config.get('default_recipient') or ''
        if not _EMAIL_RE.fullmatch(address):
            raise EbookConversionError('收件地址格式无效')
        if not config['configured']:
            raise EbookConversionError(
                '本机 SMTP 未配置：请在 .secrets 中设置 ' + '、'.join(config['missing']))
        if batch_id:
            job_ids = self._batch_job_ids(batch_id)
        collected = self._completed_outputs(list(job_ids or []), output_format)

        sent, skipped = [], []
        for _, entry, path in collected:
            size = path.stat().st_size
            if size > EBOOK_EMAIL_MAX_BYTES:
                skipped.append({
                    'filename': entry['filename'],
                    'reason': f'超过单封 {EBOOK_EMAIL_MAX_BYTES // (1024 * 1024)} MB 附件上限'})
                continue
            message = EmailMessage()
            message['Subject'] = Path(entry['filename']).stem[:120]
            message['From'] = config['sender']
            message['To'] = address
            message.set_content(
                '这是本机研究工具转换的阅读副本。\n'
                f'文件：{entry["filename"]}\n'
                f'格式：{"EPUB 重排" if entry["format"] == "epub" else "裁边分栏 PDF"}\n'
            )
            subtype = 'epub+zip' if entry['format'] == 'epub' else 'pdf'
            message.add_attachment(path.read_bytes(), maintype='application',
                                   subtype=subtype, filename=entry['filename'])
            try:
                self._email_sender(config, message)
                sent.append({'filename': entry['filename'], 'bytes': size})
            except Exception as exc:
                skipped.append({'filename': entry['filename'],
                                'reason': f'发送失败：{type(exc).__name__}'})
        if not sent and skipped:
            raise EbookConversionError(skipped[0]['reason'])
        return {'recipient_masked': _mask_email(address), 'sent': sent,
                'skipped': skipped, 'sent_count': len(sent),
                'skipped_count': len(skipped)}

    # -- payload ---------------------------------------------------------

    @staticmethod
    def _public_job(manifest: dict) -> dict:
        source = manifest.get('source') or {}
        return {
            'job_id': manifest.get('job_id'),
            'batch_id': manifest.get('batch_id'),
            'status': manifest.get('status'),
            'created_at': manifest.get('created_at'),
            'completed_at': manifest.get('completed_at'),
            'options': manifest.get('options') or {},
            'original_filename': source.get('original_filename'),
            'source_mode': source.get('mode'),
            'source_bytes': source.get('bytes'),
            'local_path': source.get('local_path'),
            'outputs': manifest.get('outputs') or [],
            'audit': manifest.get('audit') or {},
            'progress': manifest.get('progress') or {},
            'error': manifest.get('error'),
        }
