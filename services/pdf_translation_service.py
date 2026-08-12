# -*- coding: utf-8 -*-
"""High-fidelity, local-only PDF translation helpers.

Text-layer PDFs are parsed at line level, regrouped into paragraph-like
regions, translated by the existing text model, and written back into the
same page rectangles. Page geometry, images, vector graphics, tables, and
metadata stay in the original PDF. This is intentionally a reading-copy
workflow, not a claim of byte-identical or lossless PDF editing.
"""
from __future__ import annotations

import contextlib
import html
import io
import os
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


_TRANSLATABLE_RE = re.compile(r'[A-Za-z\u3400-\u9fff]')
_REFERENCE_HEADING_RE = re.compile(r'^\s*(?:references|bibliography|参考文献)\s*$', re.I)
_REFERENCE_END_RE = re.compile(r'^\s*(?:appendix|附录)(?:\s+[A-Z0-9]+)?\s*$', re.I)
_NUMBERED_HEADING_RE = re.compile(r'^\s*\d{1,2}(?:\.\d+)*\s*(?:\|\s*|\s+)[A-Z]')
_UNMAPPED_PUBLISHER_GLYPHS = {'\x01': '\u2212', '\u0273': '\u03b7'}
_SUPERSCRIPT_DIGITS = str.maketrans('0123456789', '\u2070\xb9\xb2\xb3\u2074\u2075\u2076\u2077\u2078\u2079')
_SUPERSCRIPT_TO_ASCII = str.maketrans('\u2070\xb9\xb2\xb3\u2074\u2075\u2076\u2077\u2078\u2079', '0123456789')
_SUPERSCRIPT_RUN_RE = re.compile(r'[\u2070\xb9\xb2\xb3\u2074-\u2079]+')


class PdfFormatError(RuntimeError):
    """A PDF validation or rendering error that never includes paper text."""


def _pymupdf():
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - depends on deployment environment
        raise PdfFormatError('PDF 支持需要安装 PyMuPDF>=1.26') from exc
    return pymupdf


@dataclass
class PdfSegment:
    segment_id: str
    text: str
    locked: bool = False
    leading: str = ''
    trailing: str = ''

    @property
    def core_text(self) -> str:
        return self.text[len(self.leading):len(self.text) - len(self.trailing)
                         if self.trailing else None]


@dataclass
class PdfUnit:
    unit_id: str
    page_index: int
    segments: list[PdfSegment]
    translations: dict[str, str] = field(default_factory=dict)

    @property
    def translatable_chars(self) -> int:
        return sum(len(segment.core_text) for segment in self.segments if not segment.locked)


@dataclass
class PdfLine:
    text: str
    rect: tuple[float, float, float, float]
    font_size: float
    bold: bool
    italic: bool
    color: int
    horizontal: bool
    column: str = ''
    locked_reason: str | None = None
    heading: bool = False


@dataclass
class PdfRegion:
    unit_id: str
    page_index: int
    rect: tuple[float, float, float, float]
    line_rects: list[tuple[float, float, float, float]]
    font_size: float
    bold: bool
    italic: bool
    heading: bool


@dataclass
class PdfLayoutBundle:
    regions: dict[str, PdfRegion]
    page_sizes: list[tuple[float, float]]
    image_counts: list[int]
    image_signatures: list[tuple]
    link_counts: list[int]
    table_counts: list[int]
    text_chars_by_page: list[int]
    scanned_pages: list[int]
    skipped: dict[str, int]
    document_body_font_size: float | None = None


def _rect_intersects(left: tuple[float, float, float, float], right) -> bool:
    x0, y0, x1, y1 = left
    rx0, ry0, rx1, ry1 = tuple(right)
    return max(x0, rx0) < min(x1, rx1) and max(y0, ry0) < min(y1, ry1)


def _page_image_signature(page) -> tuple:
    """Describe rendered images, ignoring internal soft-mask object bookkeeping."""
    rows = []
    for image in page.get_image_info(hashes=True):
        digest = image.get('digest')
        rows.append((
            int(image.get('width') or 0), int(image.get('height') or 0),
            digest.hex() if isinstance(digest, bytes) else str(digest or ''),
            tuple(round(float(value), 2) for value in image.get('bbox') or ()),
        ))
    return tuple(rows)


def _union_rect(lines: Iterable[PdfLine]) -> tuple[float, float, float, float]:
    rows = list(lines)
    return (
        min(line.rect[0] for line in rows), min(line.rect[1] for line in rows),
        max(line.rect[2] for line in rows), max(line.rect[3] for line in rows),
    )


def _join_pdf_lines(lines: list[PdfLine]) -> str:
    """Join visual lines while undoing publisher line-break hyphenation."""
    result = ''
    for line in lines:
        text = re.sub(r'\s+', ' ', line.text).strip()
        if not text:
            continue
        if result and re.search(r'COVID-$', result, re.IGNORECASE) and re.match(r'^19\b', text):
            result += text
        elif result and result.endswith('\xad'):
            result = result[:-1] + text
        elif result and re.search(r'[A-Za-z]-$', result) and re.match(r'^[a-z]', text):
            result = result[:-1] + text
        elif result:
            result += ' ' + text
        else:
            result = text
    return result


def _is_heading(text: str, font_size: float, body_size: float,
                bold: bool = False) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 180:
        return False
    letters = [char for char in stripped if char.isalpha()]
    uppercase_ratio = (sum(char.isupper() for char in letters) / len(letters)) if letters else 0
    structural_heading = bool(
        _REFERENCE_HEADING_RE.match(stripped)
        or _REFERENCE_END_RE.match(stripped)
        or re.fullmatch(r'(?:acknowledg(?:e)?ments?|endnotes?|notes?)', stripped, re.I)
    )
    bold_short_heading = (
        bold and font_size >= body_size - .5 and len(stripped.split()) <= 16
        and not re.search(r'[.;,!?]\s*$', stripped)
    )
    numbered_heading = (
        font_size >= body_size - .5
        and bool(_NUMBERED_HEADING_RE.match(stripped))
    )
    return (
        structural_heading or bold_short_heading or
        font_size >= body_size + 1.25 or
        numbered_heading or
        (len(letters) >= 4 and uppercase_ratio >= 0.85 and not stripped.endswith('.'))
    )


def _layout_label_y(page, rect: tuple[float, float, float, float]) -> float | None:
    """Locate a Table/Figure label belonging to a text-detected layout object."""
    candidates = []
    try:
        payload = page.get_text('dict', sort=True)
        for block in payload.get('blocks') or []:
            if block.get('type') != 0:
                continue
            for raw_line in block.get('lines') or []:
                text = ''.join(
                    str(span.get('text') or '') for span in raw_line.get('spans') or [])
                if not re.match(r'^\s*(?:Table|Figure)\s+\d+[A-Za-z]?[.:\s]', text, re.I):
                    continue
                bbox = tuple(float(value) for value in raw_line.get('bbox'))
                if bbox[3] < rect[1] - 30 or bbox[1] > rect[3]:
                    continue
                if max(bbox[0], rect[0]) >= min(bbox[2], rect[2]):
                    continue
                candidates.append(bbox[1])
    except Exception:
        return None
    return min(candidates) if candidates else None


def _page_table_rects(page) -> list[tuple[float, float, float, float]]:
    try:
        # PyMuPDF prints an optional-layout-package suggestion; it is not an error
        # and must not pollute the research server log.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            detected = [tuple(table.bbox) for table in page.find_tables().tables]
    except Exception:
        detected = []

    # Many journal tables and figures have no vector grid, so the default line
    # strategy finds nothing. A mixed text/line strategy detects their aligned
    # cells and labels, but can also mistake a two-column abstract for a table.
    # Accept only candidates with an explicit label, and crop the top to that
    # label so preceding body paragraphs are never locked with the object.
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            mixed = page.find_tables(
                vertical_strategy='text', horizontal_strategy='lines').tables
        for table in mixed:
            rect = tuple(float(value) for value in table.bbox)
            label_y = _layout_label_y(page, rect)
            if label_y is None:
                continue
            candidate = (rect[0], max(rect[1], label_y - 2.0), rect[2], rect[3])
            if not any(
                    abs(candidate[0] - prior[0]) < 2
                    and abs(candidate[1] - prior[1]) < 2
                    and abs(candidate[2] - prior[2]) < 2
                    and abs(candidate[3] - prior[3]) < 2
                    for prior in detected):
                detected.append(candidate)
    except Exception:
        pass
    if not detected:
        return []

    # Publisher tables often encode only the shaded header / alternating rows
    # as separate table objects.  Merge nearby neutral-gray bands so all table
    # cells are locked consistently instead of translating only half a table.
    fills = []
    try:
        for drawing in page.get_drawings():
            fill = drawing.get('fill')
            rect = tuple(drawing['rect'])
            if not fill or len(fill) < 3 or rect[2] - rect[0] < page.rect.width * .16:
                continue
            if max(fill[:3]) - min(fill[:3]) <= .035 and .72 <= sum(fill[:3]) / 3 <= .98:
                fills.append(rect)
    except Exception:
        fills = []
    if not fills:
        return detected

    fills.sort(key=lambda rect: (rect[1], rect[0]))
    groups: list[list[tuple[float, float, float, float]]] = []
    for rect in fills:
        if groups and rect[1] - max(item[3] for item in groups[-1]) <= 125:
            groups[-1].append(rect)
        else:
            groups.append([rect])
    expanded = []
    for group in groups:
        union = (
            min(rect[0] for rect in group), min(rect[1] for rect in group),
            max(rect[2] for rect in group), max(rect[3] for rect in group),
        )
        vertical_gap = min(max(0.0, union[1] - rect[3], rect[1] - union[3]) for rect in detected)
        if vertical_gap > 25:
            continue
        expanded.append((
            max(0.0, union[0] - 1.5), max(0.0, union[1] - 12.0),
            min(page.rect.width, union[2] + 1.5), min(page.rect.height, union[3] + 12.0),
        ))
    return expanded or detected


def _extract_page_lines(page, table_rects) -> tuple[list[PdfLine], float, int, int]:
    pymupdf = _pymupdf()
    payload = page.get_text('dict', sort=True)
    lines: list[PdfLine] = []
    text_chars = 0
    for block in payload.get('blocks') or []:
        if block.get('type') != 0:
            continue
        for raw_line in block.get('lines') or []:
            spans = [span for span in raw_line.get('spans') or [] if span.get('text')]
            if not spans:
                continue
            largest_span = max(float(span.get('size') or 0) for span in spans)
            span_text = []
            for span in spans:
                value = str(span.get('text') or '')
                if value.isdigit() and largest_span and float(span.get('size') or 0) <= largest_span * .8:
                    value = value.translate(_SUPERSCRIPT_DIGITS)
                span_text.append(value)
            text = ''.join(span_text).strip()
            if not text:
                continue
            rect = tuple(float(value) for value in raw_line.get('bbox'))
            sizes = [float(span.get('size') or 0) for span in spans]
            flags = 0
            for span in spans:
                flags |= int(span.get('flags') or 0)
            direction = raw_line.get('dir') or (1, 0)
            horizontal = abs(float(direction[0])) >= 0.7
            line = PdfLine(
                text=text, rect=rect, font_size=max(sizes or [8.0]),
                bold=bool(flags & pymupdf.TEXT_FONT_BOLD),
                italic=bool(flags & pymupdf.TEXT_FONT_ITALIC),
                color=int(spans[0].get('color') or 0), horizontal=horizontal,
            )
            text_chars += len(text)
            if not horizontal or (rect[2] - rect[0] < 14 and rect[3] - rect[1] > page.rect.height * 0.35):
                line.locked_reason = 'vertical_or_rotated'
            # Journal running heads and first-page imprint lines commonly
            # extend to y=60--68pt. Keep that furniture untouched rather than
            # translating it as article text.
            elif rect[3] <= 70:
                line.locked_reason = 'header'
            elif rect[1] >= page.rect.height - 45:
                line.locked_reason = 'footer'
            elif any(_rect_intersects(rect, table_rect) for table_rect in table_rects):
                line.locked_reason = 'table'
            lines.append(line)

    lines = _merge_visual_line_fragments(lines, page.rect.width)
    body_candidates = [
        line.font_size for line in lines
        if line.locked_reason is None and 5.5 <= line.font_size <= 13
    ]
    body_size = statistics.median(body_candidates) if body_candidates else 9.0
    image_area = sum(float(image.get('width', 0)) * float(image.get('height', 0))
                     for image in payload.get('blocks') or [] if image.get('type') == 1)
    return lines, body_size, text_chars, int(image_area)


def _merge_visual_line_fragments(lines: list[PdfLine], page_width: float) -> list[PdfLine]:
    """Rejoin justified words/spans that a publisher encoded as separate lines."""
    midpoint = page_width / 2

    def visual_column(line: PdfLine) -> str:
        x0, _, x1, _ = line.rect
        if x1 <= midpoint + 4:
            return 'left'
        if x0 >= midpoint - 4:
            return 'right'
        return 'wide'

    merged: list[PdfLine] = []
    for column in ('wide', 'left', 'right'):
        candidates = sorted(
            (line for line in lines if visual_column(line) == column),
            key=lambda item: (item.rect[1], item.rect[0]),
        )
        rows: list[list[PdfLine]] = []
        for line in candidates:
            if rows and abs(line.rect[1] - rows[-1][0].rect[1]) <= 1.5 \
                    and abs(line.rect[3] - rows[-1][0].rect[3]) <= 2.5 \
                    and line.locked_reason == rows[-1][0].locked_reason:
                rows[-1].append(line)
            else:
                rows.append([line])
        for fragments in rows:
            fragments.sort(key=lambda item: item.rect[0])
            largest_font = max(fragment.font_size for fragment in fragments)

            def fragment_text(fragment: PdfLine) -> str:
                value = fragment.text
                if value.isdigit() and largest_font and fragment.font_size <= largest_font * .8:
                    return value.translate(_SUPERSCRIPT_DIGITS)
                return value

            text = fragment_text(fragments[0])
            previous = fragments[0]
            for fragment in fragments[1:]:
                gap = fragment.rect[0] - previous.rect[2]
                text += ('' if gap <= 1.2 else ' ') + fragment_text(fragment)
                previous = fragment
            merged.append(PdfLine(
                text=text,
                rect=_union_rect(fragments),
                font_size=max(fragment.font_size for fragment in fragments),
                bold=any(fragment.bold for fragment in fragments),
                italic=all(fragment.italic for fragment in fragments),
                color=fragments[0].color,
                horizontal=all(fragment.horizontal for fragment in fragments),
                column=column,
                locked_reason=fragments[0].locked_reason,
            ))
    return merged


def _assign_columns(lines: list[PdfLine], page_width: float) -> None:
    midpoint = page_width / 2
    has_right_column_evidence = any(
        line.rect[0] >= midpoint - 4 for line in lines)
    for line in lines:
        x0, _, x1, _ = line.rect
        if x1 <= midpoint + 4:
            line.column = 'left'
        elif x0 >= midpoint - 4:
            line.column = 'right'
        else:
            line.column = 'wide'
    # A short final line in a wide abstract can end before the page midpoint
    # and otherwise look like a left-column line.  Inherit the preceding wide
    # block when the left edge and baseline continuation make that unambiguous.
    previous_wide: PdfLine | None = None
    for line in sorted(lines, key=lambda item: (item.rect[1], item.rect[0])):
        inherited_wide = False
        if line.column == 'left' and previous_wide:
            gap = line.rect[1] - previous_wide.rect[3]
            # A hanging continuation may be indented by roughly one small-font
            # character.  The former 8pt cutoff split first-page metadata such
            # as ``University of / Pennsylvania.`` into different columns,
            # which later made their translated regions overlap.
            continuation_indent = max(10.0, line.font_size * 1.25)
            hanging_metadata = (
                line.rect[0] >= page_width * .30
                and abs(line.rect[0] - previous_wide.rect[0]) <= continuation_indent)
            # On a genuinely single-column page, a paragraph's short final
            # line often ends before the midpoint and otherwise looks like a
            # left-column fragment.  Only inherit it when no right column is
            # present and its left edge continues the preceding wide line.
            single_column_continuation = (
                not has_right_column_evidence
                and abs(line.rect[0] - previous_wide.rect[0]) <= continuation_indent)
            if -1.5 <= gap <= 22 and (
                    hanging_metadata or single_column_continuation):
                line.column = 'wide'
                inherited_wide = True
        if line.column == 'wide':
            previous_wide = line
        elif not inherited_wide:
            # Do not let a later left-column line jump over an intervening
            # noncontinuation line and attach to an older wide block.
            previous_wide = None


def _normalize_pdf_text(text: str) -> str:
    for source, replacement in _UNMAPPED_PUBLISHER_GLYPHS.items():
        text = text.replace(source, replacement)
    return text.replace('\xad', '')


def _infer_document_body_size(page_lines: list[list[PdfLine]]) -> float | None:
    """Infer article body size from opening-page prose, not table density."""
    weights: dict[float, int] = {}
    observed: dict[float, list[float]] = {}
    for lines in page_lines[:8]:
        for line in lines:
            if line.locked_reason is not None or not (5.5 <= line.font_size <= 13):
                continue
            if not any(char.isalpha() for char in line.text):
                continue
            bucket = round(line.font_size * 2) / 2
            weights[bucket] = weights.get(bucket, 0) + max(1, len(line.text.strip()))
            observed.setdefault(bucket, []).append(line.font_size)
    if not weights:
        return None
    winner = max(weights, key=weights.get)
    return statistics.median(observed[winner])


def _effective_page_body_size(lines: list[PdfLine], local_body_size: float,
                              document_body_size: float | None) -> float:
    """Use the document body size when that face has real prose on this page."""
    if document_body_size is None:
        return local_body_size
    if abs(local_body_size - document_body_size) <= .75:
        return document_body_size
    bucket = round(document_body_size * 2) / 2
    matching = [
        line for line in lines
        if line.locked_reason is None
        and round(line.font_size * 2) / 2 == bucket
        and any(char.isalpha() for char in line.text)
    ]
    if len(matching) >= 3 and sum(len(line.text.strip()) for line in matching) >= 120:
        return statistics.median(line.font_size for line in matching)
    return local_body_size


def _new_region(previous: PdfLine, current: PdfLine, column_right: float,
                body_size: float) -> bool:
    if previous.heading or current.heading:
        return True
    if abs(previous.font_size - current.font_size) > 0.85:
        return True
    vertical_gap = current.rect[1] - previous.rect[3]
    if vertical_gap > max(8.0, body_size * 1.35):
        return True
    # Academic PDFs typically mark a new paragraph with a first-line indent.
    if current.rect[0] >= previous.rect[0] + max(8.0, body_size) \
            and not re.search(r'[A-Za-z](?:-|\xad)$', previous.text.strip()):
        return True
    # A short terminal line followed by a new full-width line is another strong
    # paragraph boundary when the publisher does not insert vertical spacing.
    if previous.rect[2] <= column_right - 35 and re.search(r'[.!?\u3002！？)]$', previous.text.strip()):
        return True
    return False


def _group_page_lines(lines: list[PdfLine], page_width: float, body_size: float) -> list[list[PdfLine]]:
    _assign_columns(lines, page_width)
    for line in lines:
        line.heading = _is_heading(line.text, line.font_size, body_size, line.bold)
    groups: list[list[PdfLine]] = []
    for column in ('wide', 'left', 'right'):
        column_lines = sorted((line for line in lines if line.column == column), key=lambda item: (item.rect[1], item.rect[0]))
        current: list[PdfLine] = []
        column_right = max((line.rect[2] for line in column_lines), default=page_width)
        for line in column_lines:
            if line.locked_reason:
                if current:
                    groups.append(current)
                    current = []
                continue
            if current and _new_region(current[-1], line, column_right, body_size):
                groups.append(current)
                current = []
            current.append(line)
            if line.heading:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
    return groups


def extract_pdf_units(input_path: Path, preserve_references: bool = True,
                      max_pages: int = 250) -> tuple[list[PdfUnit], PdfLayoutBundle]:
    """Extract paragraph-like regions from a text-layer PDF."""
    pymupdf = _pymupdf()
    try:
        document = pymupdf.open(input_path)
    except Exception as exc:
        raise PdfFormatError('PDF 文件损坏或无法读取') from exc
    with document:
        if document.needs_pass:
            raise PdfFormatError('PDF 已加密；请先在本机解除密码保护')
        if document.page_count < 1:
            raise PdfFormatError('PDF 没有可处理页面')
        if document.page_count > max_pages:
            raise PdfFormatError(f'PDF 超过 {max_pages} 页安全上限')

        units: list[PdfUnit] = []
        regions: dict[str, PdfRegion] = {}
        page_sizes: list[tuple[float, float]] = []
        image_counts: list[int] = []
        image_signatures: list[tuple] = []
        link_counts: list[int] = []
        table_counts: list[int] = []
        text_chars_by_page: list[int] = []
        scanned_pages: list[int] = []
        skipped = {
            'header_lines': 0, 'footer_lines': 0, 'vertical_or_rotated_lines': 0,
            'table_lines': 0, 'reference_regions': 0, 'nontranslatable_regions': 0,
        }
        page_records: list[dict] = []
        for page_index, page in enumerate(document):
            page_sizes.append((round(page.rect.width, 3), round(page.rect.height, 3)))
            image_signature = _page_image_signature(page)
            image_signatures.append(image_signature)
            image_counts.append(len(image_signature))
            link_counts.append(len(page.get_links()))
            table_rects = _page_table_rects(page)
            table_counts.append(len(table_rects))
            lines, body_size, text_chars, image_area = _extract_page_lines(page, table_rects)
            text_chars_by_page.append(text_chars)
            for line in lines:
                if line.locked_reason:
                    skipped[f'{line.locked_reason}_lines'] += 1
            if text_chars < 40 and (page.get_images(full=True) or image_area > page.rect.width * page.rect.height * .2):
                scanned_pages.append(page_index + 1)

            page_records.append({
                'page_index': page_index,
                'lines': lines,
                'local_body_size': body_size,
            })

        document_body_size = _infer_document_body_size(
            [record['lines'] for record in page_records])
        reference_mode = False
        for record in page_records:
            page_index = record['page_index']
            page = document[page_index]
            lines = record['lines']
            body_size = _effective_page_body_size(
                lines, record['local_body_size'], document_body_size)

            groups = _group_page_lines(lines, page.rect.width, body_size)
            groups.sort(key=lambda group: (
                0 if group[0].column == 'wide' else 1 if group[0].column == 'left' else 2,
                group[0].rect[1], group[0].rect[0],
            ))
            wide_group_rects = [
                _union_rect(group) for group in groups if group[0].column == 'wide'
            ]
            for group_index, group in enumerate(groups):
                source_text = _normalize_pdf_text(_join_pdf_lines(group)).strip()
                normalized = re.sub(r'\s+', ' ', source_text)
                if _REFERENCE_END_RE.match(normalized):
                    reference_mode = False
                is_reference_heading = bool(_REFERENCE_HEADING_RE.match(normalized))
                locked_reference = preserve_references and reference_mode and not is_reference_heading
                if preserve_references and is_reference_heading:
                    reference_mode = True
                if locked_reference:
                    skipped['reference_regions'] += 1
                    continue
                if not source_text or not _TRANSLATABLE_RE.search(source_text):
                    skipped['nontranslatable_regions'] += 1
                    continue

                rect = list(_union_rect(group))
                if group[0].column == 'left':
                    desired_right = page.rect.width / 2 - 8
                    # Front pages often place a narrow metadata column beside
                    # a wide abstract that begins left of the normal midpoint.
                    # Never expand a short left-column line underneath that
                    # neighbouring region; retain a small visual gutter.
                    for wide_rect in wide_group_rects:
                        vertically_overlaps = (
                            max(rect[1], wide_rect[1]) < min(rect[3], wide_rect[3]))
                        if vertically_overlaps and wide_rect[0] > rect[0]:
                            desired_right = min(desired_right, wide_rect[0] - 4)
                    rect[2] = max(rect[2], desired_right)
                elif group[0].column == 'right':
                    rect[2] = max(rect[2], page.rect.width - 45)
                rect[0] = max(0, rect[0] - .8)
                rect[1] = max(0, rect[1] - .8)
                rect[2] = min(page.rect.width, rect[2] + .8)
                rect[3] = min(page.rect.height, rect[3] + 1.8)
                unit_id = f'pdf:{page_index + 1}:{group_index}'
                unit = PdfUnit(unit_id=unit_id, page_index=page_index,
                               segments=[PdfSegment('0', source_text)])
                region = PdfRegion(
                    unit_id=unit_id, page_index=page_index, rect=tuple(rect),
                    line_rects=[line.rect for line in group],
                    font_size=max(6.0, statistics.median(line.font_size for line in group)),
                    bold=all(line.bold for line in group), italic=all(line.italic for line in group),
                    heading=any(line.heading for line in group),
                )
                units.append(unit)
                regions[unit_id] = region

        if scanned_pages and len(scanned_pages) >= max(1, (document.page_count + 3) // 4):
            preview = ', '.join(str(page) for page in scanned_pages[:8])
            raise PdfFormatError(
                f'检测到扫描型 PDF（页 {preview}）；当前未配置本地 OCR/VLM，未生成不完整译文'
            )
        if not units:
            raise PdfFormatError('PDF 没有检测到可翻译的文本层')

        return units, PdfLayoutBundle(
            regions=regions, page_sizes=page_sizes, image_counts=image_counts,
            image_signatures=image_signatures,
            link_counts=link_counts, table_counts=table_counts,
            text_chars_by_page=text_chars_by_page, scanned_pages=scanned_pages,
            skipped=skipped, document_body_font_size=document_body_size,
        )


def _link_key(link: dict) -> tuple:
    rect = link.get('from')
    rect_key = tuple(round(float(value), 1) for value in rect) if rect else ()
    return (
        int(link.get('kind') or 0), rect_key, link.get('uri'), link.get('page'),
        link.get('nameddest') or link.get('name'), link.get('file'),
    )


def _restore_missing_links(page, original_links: list[dict]) -> int:
    pymupdf = _pymupdf()
    existing = {_link_key(link) for link in page.get_links()}
    restored = 0
    for link in original_links:
        if _link_key(link) in existing:
            continue
        kind = int(link.get('kind') or 0)
        payload = {'kind': kind, 'from': link['from']}
        if kind == pymupdf.LINK_URI and link.get('uri'):
            payload['uri'] = link['uri']
        elif kind == pymupdf.LINK_GOTO and link.get('page') is not None:
            payload['page'] = link['page']
            if link.get('to') is not None:
                payload['to'] = link['to']
            payload['zoom'] = link.get('zoom', 0)
        elif kind == pymupdf.LINK_NAMED and (link.get('nameddest') or link.get('name')):
            payload['name'] = link.get('nameddest') or link.get('name')
        elif kind in {pymupdf.LINK_GOTOR, pymupdf.LINK_LAUNCH} and link.get('file'):
            payload['file'] = link['file']
            if link.get('page') is not None:
                payload['page'] = link['page']
        else:
            continue
        try:
            page.insert_link(payload)
            restored += 1
            existing.add(_link_key(link))
        except Exception:
            continue
    return restored


def _region_html(text: str, region: PdfRegion) -> tuple[str, str]:
    text = _normalize_pdf_text(text)
    safe_parts = []
    cursor = 0
    for match in _SUPERSCRIPT_RUN_RE.finditer(text):
        safe_parts.append(html.escape(text[cursor:match.start()], quote=False))
        safe_parts.append(
            '<sup>' + match.group(0).translate(_SUPERSCRIPT_TO_ASCII) + '</sup>')
        cursor = match.end()
    safe_parts.append(html.escape(text[cursor:], quote=False))
    safe = ''.join(safe_parts).replace('\n', '<br>')
    tag = 'div'
    weight = '700' if region.bold or region.heading else '400'
    style = 'italic' if region.italic else 'normal'
    align = 'left' if region.heading else 'justify'
    css = (
        f'*{{font-family:sans-serif;color:#111;}} '
        f'{tag}{{margin:0;padding:0;font-size:{region.font_size:.2f}pt;'
        f'font-weight:{weight};font-style:{style};line-height:1.28;text-align:{align};}}'
        'sup{font-size:.72em;vertical-align:super;line-height:0;}'
    )
    return f'<{tag}>{safe}</{tag}>', css


def write_translated_pdf(input_path: Path, output_path: Path, units: list[PdfUnit],
                         bundle: PdfLayoutBundle) -> dict:
    """Replace translated text regions while preserving original PDF geometry."""
    pymupdf = _pymupdf()
    translated = {unit.unit_id: unit for unit in units}
    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
    min_scale = 1.0
    restored_links = 0
    low_scale_regions = 0
    try:
        document = pymupdf.open(input_path)
        with document:
            original_links = [page.get_links() for page in document]
            original_replacement_chars = sum(page.get_text().count('\ufffd') for page in document)
            original_control_chars = sum(
                1 for page in document for char in page.get_text()
                if ord(char) < 32 and char not in '\n\r\t'
            )
            by_page: dict[int, list[PdfRegion]] = {}
            for region in bundle.regions.values():
                by_page.setdefault(region.page_index, []).append(region)

            for page_index, regions in by_page.items():
                page = document[page_index]
                for region in regions:
                    unit = translated[region.unit_id]
                    if '0' not in unit.translations:
                        raise PdfFormatError('PDF 翻译结果缺少版面片段')
                    for line_rect in region.line_rects:
                        page.add_redact_annot(line_rect, fill=None, cross_out=False)
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_NONE,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                    text=pymupdf.PDF_REDACT_TEXT_REMOVE,
                )
                restored_links += _restore_missing_links(page, original_links[page_index])
                for region in sorted(regions, key=lambda item: (item.rect[1], item.rect[0])):
                    unit = translated[region.unit_id]
                    markup, css = _region_html(unit.translations['0'], region)
                    spare_height, scale = page.insert_htmlbox(
                        region.rect, markup, css=css, scale_low=.58, overlay=True,
                    )
                    if spare_height < 0:
                        raise PdfFormatError('PDF 某个翻译段落无法放回原版面；任务已停止，未输出截断文件')
                    min_scale = min(min_scale, float(scale))
                    if scale < .72:
                        low_scale_regions += 1

            document.save(temp_path, garbage=4, deflate=True, clean=True)
        os.replace(temp_path, output_path)
    except PdfFormatError:
        raise
    except Exception as exc:
        raise PdfFormatError('PDF 版面回写或完整性验证失败') from exc
    finally:
        if temp_path.exists():
            temp_path.unlink()

    with pymupdf.open(output_path) as result:
        page_sizes = [(round(page.rect.width, 3), round(page.rect.height, 3)) for page in result]
        image_signatures = [_page_image_signature(page) for page in result]
        image_counts = [len(signature) for signature in image_signatures]
        output_link_counts = [len(page.get_links()) for page in result]
        if page_sizes != bundle.page_sizes:
            raise PdfFormatError('输出 PDF 的页数或页面尺寸发生变化')
        if image_counts != bundle.image_counts:
            raise PdfFormatError('输出 PDF 的图片对象数量发生变化')
        if image_signatures != bundle.image_signatures:
            raise PdfFormatError('输出 PDF 的图片内容或位置发生变化')
        output_replacement_chars = sum(page.get_text().count('\ufffd') for page in result)
        output_control_chars = sum(
            1 for page in result for char in page.get_text()
            if ord(char) < 32 and char not in '\n\r\t'
        )
        if output_replacement_chars > original_replacement_chars:
            raise PdfFormatError('输出 PDF 新增了无效替换字符')
        if output_control_chars > original_control_chars:
            raise PdfFormatError('输出 PDF 新增了未映射的出版商字形')

    return {
        'pdf_layout_mode': 'text-layer overlay; high fidelity, not lossless',
        'page_count': len(bundle.page_sizes),
        'page_sizes_unchanged': True,
        'image_counts_unchanged': True,
        'image_content_and_positions_unchanged': True,
        'tables_preserved_original': sum(bundle.table_counts),
        'original_link_count': sum(bundle.link_counts),
        'output_link_count': sum(output_link_counts),
        'links_restored_after_redaction': restored_links,
        'original_replacement_chars': original_replacement_chars,
        'output_replacement_chars': output_replacement_chars,
        'original_unmapped_control_chars': original_control_chars,
        'output_unmapped_control_chars': output_control_chars,
        'minimum_text_scale': round(min_scale, 3),
        'low_scale_regions': low_scale_regions,
        'scanned_pages_left_original': bundle.scanned_pages,
    }
