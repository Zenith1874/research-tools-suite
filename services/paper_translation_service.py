# -*- coding: utf-8 -*-
"""Privacy-preserving academic paper translation.

The original document stays on the research workstation.  Only bounded text
segments are sent to an OpenAI-compatible model endpoint, normally reached via
an SSH tunnel.  DOCX files are edited inside their OOXML text nodes so package
members, styles, tables, media, relationships, fields, and section structure
remain in place.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import requests

from services.pdf_translation_service import (
    PdfFormatError,
    extract_pdf_units,
    write_translated_pdf,
)


DEFAULT_MODEL = os.environ.get('TRANSLATION_MODEL', 'Qwen/Qwen3-14B-AWQ')
DEFAULT_BASE_URL = os.environ.get('TRANSLATION_BASE_URL', 'http://127.0.0.1:18001/v1').rstrip('/')
TRANSLATION_MAX_UPLOAD_BYTES = int(os.environ.get('TRANSLATION_MAX_UPLOAD_BYTES', 50 * 1024 * 1024))
TRANSLATION_BATCH_CHARS = int(os.environ.get('TRANSLATION_BATCH_CHARS', 4200))
TRANSLATION_BATCH_UNITS = int(os.environ.get('TRANSLATION_BATCH_UNITS', 10))
SUPPORTED_EXTENSIONS = {'.docx', '.pdf', '.txt', '.md'}

_XML_PART_RE = re.compile(
    r'^word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$'
)
_PARAGRAPH_RE = re.compile(r'<w:p(?:\s[^>]*)?>.*?</w:p>', re.DOTALL)
_RUN_RE = re.compile(r'<w:r(?:\s[^>]*)?>.*?</w:r>', re.DOTALL)
_TEXT_RE = re.compile(r'(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)', re.DOTALL)
_RPR_RE = re.compile(r'<w:rPr(?:\s[^>]*)?>.*?</w:rPr>', re.DOTALL)
_FIELD_TYPE_RE = re.compile(r'<w:fldChar\b[^>]*w:fldCharType="(begin|separate|end)"[^>]*/?>')
_PSTYLE_RE = re.compile(r'<w:pStyle\b[^>]*w:val="([^"]+)"[^>]*/?>')
_TRANSLATABLE_RE = re.compile(r'[A-Za-z\u3400-\u9fff]')
_JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')

_COVID_RE = re.compile(r'\b(?:post-)?COVID[-\u2010-\u2015]19\b', re.IGNORECASE)
_AUTHOR_YEAR_PATTERNS = [
    re.compile(r"\b[A-Z\u00c0-\u024f][\w\u00c0-\u024f\-'\u2019]+\s+et\s+al\.,?\s*(?:19|20)\d{2}[a-z]?"),
    re.compile(r"\b[A-Z\u00c0-\u024f][\w\u00c0-\u024f\-'\u2019]+\s+(?:&|and)\s+"
               r"[A-Z\u00c0-\u024f][\w\u00c0-\u024f\-'\u2019]+,?\s*(?:19|20)\d{2}[a-z]?"),
    re.compile(r"\b[A-Z\u00c0-\u024f][\w\u00c0-\u024f\-'\u2019]+,\s*(?:19|20)\d{2}[a-z]?"),
]

_PROTECTED_PATTERNS = [
    re.compile(r'`[^`\r\n]+`'),
    re.compile(r'https?://[^\s<>\]\)]+', re.IGNORECASE),
    re.compile(r'\bwww\.[^\s<>\]\)]+', re.IGNORECASE),
    re.compile(r'\b10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.IGNORECASE),
    re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.IGNORECASE),
    _COVID_RE,
    *_AUTHOR_YEAR_PATTERNS,
    re.compile(r'\[(?:\d+[a-z]?\s*[-,;]?\s*)+\]', re.IGNORECASE),
    re.compile(
        r'\((?:[A-Z][\w\-\'’]+(?:\s+(?:&|and)\s+[A-Z][\w\-\'’]+)?'
        r'(?:\s+et\s+al\.)?,?\s*)+(?:19|20)\d{2}[a-z]?(?:\s*;[^)]*)?\)'
    ),
    re.compile(r'(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:\s*[%‰])?(?![\w])'),
]


class TranslationError(RuntimeError):
    """A validation-safe translation error that never includes paper text."""


class ModelStructureError(TranslationError):
    """The model answered, but its JSON/protected-token structure was invalid."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    name = os.path.basename((value or '').replace('\\', '/')).strip()
    name = ''.join(ch for ch in name if ch >= ' ' and ch not in '\x7f')
    if not name or name in {'.', '..'} or len(name) > 180:
        raise TranslationError('文件名无效或过长')
    return name


def decode_options_header(value: str | None) -> dict:
    """Decode the browser's URL-safe base64 JSON options header."""
    if not value:
        return {}
    try:
        padding = '=' * (-len(value) % 4)
        raw = base64.urlsafe_b64decode((value + padding).encode('ascii'))
        parsed = json.loads(raw.decode('utf-8'))
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        raise TranslationError('翻译选项格式无效') from exc


def parse_glossary(value) -> list[dict[str, str]]:
    """Normalize at most 100 non-empty terminology pairs."""
    pairs: list[dict[str, str]] = []
    if isinstance(value, str):
        rows = []
        for line in value.splitlines():
            if '=' in line:
                source, target = line.split('=', 1)
                rows.append({'source': source, 'target': target})
        value = rows
    if not isinstance(value, list):
        return pairs
    seen = set()
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        source = str(item.get('source') or '').strip()
        target = str(item.get('target') or '').strip()
        if not source or not target or len(source) > 160 or len(target) > 160:
            continue
        key = source.casefold()
        if key in seen:
            continue
        seen.add(key)
        pairs.append({'source': source, 'target': target})
    return pairs


SUPPORTED_MODES = {'translate', 'summarize', 'translate_summarize'}


def normalize_options(options: dict | None) -> dict:
    options = options if isinstance(options, dict) else {}
    mode = str(options.get('mode') or 'translate').strip().casefold()
    if mode not in SUPPORTED_MODES:
        raise TranslationError('无效的任务模式')
    source = str(options.get('source_language') or 'English').strip()[:60]
    target = str(options.get('target_language') or 'Simplified Chinese').strip()[:60]
    # 源=目标只在需要翻译时才是矛盾;纯总结允许英文原文→英文摘要。
    if mode in {'translate', 'translate_summarize'} and source.casefold() == target.casefold():
        raise TranslationError('源语言和目标语言不能相同')
    domain = str(options.get('domain') or 'Information Systems, Management, OB/HR, and computational social science').strip()
    return {
        'mode': mode,
        'source_language': source,
        'target_language': target,
        'domain': domain[:300],
        'preserve_references': bool(options.get('preserve_references', True)),
        'pdf_mode': 'layout_overlay',
        'glossary': parse_glossary(options.get('glossary')),
    }


def _split_outer_whitespace(text: str) -> tuple[str, str, str]:
    leading_match = re.match(r'^\s*', text)
    trailing_match = re.search(r'\s*$', text)
    leading = leading_match.group(0) if leading_match else ''
    trailing = trailing_match.group(0) if trailing_match else ''
    end = len(text) - len(trailing) if trailing else len(text)
    return leading, text[len(leading):end], trailing


@dataclass
class TextTarget:
    start: int
    end: int


@dataclass
class Segment:
    segment_id: str
    text: str
    targets: list[TextTarget] = field(default_factory=list)
    locked: bool = False
    leading: str = ''
    trailing: str = ''

    @property
    def core_text(self) -> str:
        return self.text[len(self.leading):len(self.text) - len(self.trailing) if self.trailing else None]


@dataclass
class TranslationUnit:
    unit_id: str
    part_name: str
    paragraph_start: int
    paragraph_end: int
    paragraph_xml: str
    segments: list[Segment]
    translations: dict[str, str] = field(default_factory=dict)

    def public_payload(self) -> dict:
        return {
            'id': self.unit_id,
            'segments': [
                {'id': seg.segment_id, 'text': seg.core_text, 'translate': not seg.locked}
                for seg in self.segments
            ],
        }

    @property
    def translatable_chars(self) -> int:
        return sum(len(seg.core_text) for seg in self.segments if not seg.locked)


def _xml_unescape(value: str) -> str:
    return html.unescape(value)


def _xml_escape(value: str) -> str:
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _ooxml_tag_count(xml: str, tag: str) -> int:
    return len(re.findall(rf'<{re.escape(tag)}(?:\s[^>]*)?>', xml))


def _is_cjk_boundary_char(value: str) -> bool:
    if not value:
        return False
    char = value[0]
    return ('\u3400' <= char <= '\u9fff') or char in '，。；：！？、）》】'


def normalize_cjk_run_boundaries(units: Iterable[TranslationUnit]) -> None:
    """Remove English run-boundary spaces only between two translated CJK spans."""
    for unit in units:
        for left, right in zip(unit.segments, unit.segments[1:]):
            if left.locked or right.locked:
                continue
            left_text = unit.translations.get(left.segment_id, '').rstrip()
            right_text = unit.translations.get(right.segment_id, '').lstrip()
            if left_text and right_text and _is_cjk_boundary_char(left_text[-1]) \
                    and _is_cjk_boundary_char(right_text[0]):
                left.trailing = ''
                right.leading = ''


def _heading_level(paragraph_xml: str) -> int | None:
    match = _PSTYLE_RE.search(paragraph_xml)
    if not match:
        return None
    style = match.group(1).casefold().replace(' ', '')
    level = re.search(r'(?:heading|标题)(\d+)$', style)
    return int(level.group(1)) if level else None


def _paragraph_plain_text(paragraph_xml: str) -> str:
    return ''.join(_xml_unescape(match.group(2)) for match in _TEXT_RE.finditer(paragraph_xml))


def _paragraph_segments(paragraph_xml: str, locked_paragraph: bool = False) -> list[Segment]:
    groups: list[dict] = []
    field_depth = 0
    previous_run_index = -2
    previous_run_end = -1
    for run_index, run_match in enumerate(_RUN_RE.finditer(paragraph_xml)):
        run_xml = run_match.group(0)
        field_events = _FIELD_TYPE_RE.findall(run_xml)
        begins = field_events.count('begin')
        ends = field_events.count('end')
        locked = locked_paragraph or field_depth > 0 or begins > 0 or '<w:instrText' in run_xml
        field_depth += begins

        text_matches = list(_TEXT_RE.finditer(run_xml))
        if text_matches:
            text = ''.join(_xml_unescape(item.group(2)) for item in text_matches)
            rpr = _RPR_RE.search(run_xml)
            style_signature = rpr.group(0) if rpr else ''
            prefix = paragraph_xml[:run_match.start()]
            in_hyperlink = prefix.rfind('<w:hyperlink') > prefix.rfind('</w:hyperlink>')
            targets = [
                TextTarget(run_match.start() + item.start(2), run_match.start() + item.end(2))
                for item in text_matches
            ]
            merge = (
                groups and groups[-1]['style'] == style_signature and
                groups[-1]['locked'] == locked and groups[-1]['hyperlink'] == in_hyperlink and
                previous_run_index == run_index - 1 and previous_run_end >= 0 and
                not paragraph_xml[previous_run_end:run_match.start()].strip()
            )
            if merge:
                groups[-1]['text'] += text
                groups[-1]['targets'].extend(targets)
            else:
                groups.append({
                    'text': text,
                    'targets': targets,
                    'locked': locked,
                    'style': style_signature,
                    'hyperlink': in_hyperlink,
                })
            previous_run_index = run_index
        previous_run_end = run_match.end()
        field_depth = max(0, field_depth - ends)

    segments = []
    for index, group in enumerate(groups):
        leading, core, trailing = _split_outer_whitespace(group['text'])
        locked = bool(group['locked'] or not core or not _TRANSLATABLE_RE.search(core))
        segments.append(Segment(
            segment_id=str(index), text=group['text'], targets=group['targets'],
            locked=locked, leading=leading, trailing=trailing,
        ))
    return segments


def extract_docx_units(input_path: Path, preserve_references: bool = True) -> tuple[dict[str, str], list[TranslationUnit], dict]:
    """Read DOCX XML parts and return translatable units without rewriting the file."""
    parts: dict[str, str] = {}
    units: list[TranslationUnit] = []
    media_hashes: dict[str, str] = {}
    member_names: list[str] = []
    structure: dict[str, dict[str, int]] = {}
    skipped = {'reference_paragraphs': 0, 'formula_paragraphs': 0, 'locked_segments': 0}
    with zipfile.ZipFile(input_path, 'r') as archive:
        bad = archive.testzip()
        if bad:
            raise TranslationError('DOCX 压缩包损坏')
        member_names = archive.namelist()
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename.startswith('word/media/'):
                media_hashes[info.filename] = hashlib.sha256(data).hexdigest()
            if _XML_PART_RE.match(info.filename):
                try:
                    xml = data.decode('utf-8')
                except UnicodeDecodeError as exc:
                    raise TranslationError('DOCX XML 不是有效的 UTF-8') from exc
                parts[info.filename] = xml
                structure[info.filename] = {
                    'paragraphs': len(_PARAGRAPH_RE.findall(xml)),
                    'tables': _ooxml_tag_count(xml, 'w:tbl'),
                    'drawings': _ooxml_tag_count(xml, 'w:drawing'),
                }

    for part_name, xml in parts.items():
        reference_level: int | None = None
        reference_mode = False
        for paragraph_index, paragraph_match in enumerate(_PARAGRAPH_RE.finditer(xml)):
            paragraph_xml = paragraph_match.group(0)
            plain = _paragraph_plain_text(paragraph_xml).strip()
            level = _heading_level(paragraph_xml)
            normalized = re.sub(r'[^a-z\u4e00-\u9fff]', '', plain.casefold())
            is_reference_heading = normalized in {'references', 'bibliography', '参考文献'}
            if preserve_references and reference_mode and level is not None and reference_level is not None \
                    and level <= reference_level and not is_reference_heading:
                reference_mode = False
                reference_level = None
            locked_paragraph = preserve_references and reference_mode
            if preserve_references and is_reference_heading:
                reference_mode = True
                reference_level = level or 1
                locked_paragraph = False  # Translate the heading, preserve the entries below it.
            has_formula = '<m:oMath' in paragraph_xml or '<m:oMathPara' in paragraph_xml
            if locked_paragraph and plain and not has_formula:
                skipped['reference_paragraphs'] += 1
            if has_formula:
                if plain:
                    skipped['formula_paragraphs'] += 1
                locked_paragraph = True
            segments = _paragraph_segments(paragraph_xml, locked_paragraph=locked_paragraph)
            skipped['locked_segments'] += sum(1 for segment in segments if segment.locked)
            if not segments or not any(not segment.locked for segment in segments):
                continue
            units.append(TranslationUnit(
                unit_id=f'{part_name}:{paragraph_index}',
                part_name=part_name,
                paragraph_start=paragraph_match.start(),
                paragraph_end=paragraph_match.end(),
                paragraph_xml=paragraph_xml,
                segments=segments,
            ))
    audit = {
        'member_names': member_names,
        'media_hashes': media_hashes,
        'structure': structure,
        'xml_parts_scanned': sorted(parts),
        'skipped': skipped,
    }
    return parts, units, audit


def _patched_paragraph(unit: TranslationUnit) -> str:
    paragraph = unit.paragraph_xml
    replacements: list[tuple[int, int, str]] = []
    for segment in unit.segments:
        if segment.locked:
            continue
        if segment.segment_id not in unit.translations:
            raise TranslationError('翻译结果缺少段落片段')
        translated = segment.leading + unit.translations[segment.segment_id] + segment.trailing
        for target_index, target in enumerate(segment.targets):
            replacement = _xml_escape(translated) if target_index == 0 else ''
            replacements.append((target.start, target.end, replacement))
    for start, end, replacement in sorted(replacements, reverse=True):
        paragraph = paragraph[:start] + replacement + paragraph[end:]
    return paragraph


def write_translated_docx(
        input_path: Path, output_path: Path, parts: dict[str, str],
        units: list[TranslationUnit], audit: dict) -> dict:
    """Write translated XML parts while copying every ZIP member and metadata."""
    by_part: dict[str, list[TranslationUnit]] = {}
    for unit in units:
        by_part.setdefault(unit.part_name, []).append(unit)
    translated_parts = dict(parts)
    for part_name, part_units in by_part.items():
        xml = translated_parts[part_name]
        for unit in sorted(part_units, key=lambda item: item.paragraph_start, reverse=True):
            xml = xml[:unit.paragraph_start] + _patched_paragraph(unit) + xml[unit.paragraph_end:]
        translated_parts[part_name] = xml

    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
    with zipfile.ZipFile(input_path, 'r') as source, zipfile.ZipFile(temp_path, 'w') as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename in translated_parts:
                data = translated_parts[info.filename].encode('utf-8')
            target.writestr(info, data)
    os.replace(temp_path, output_path)

    with zipfile.ZipFile(output_path, 'r') as result:
        if result.testzip():
            raise TranslationError('输出 DOCX 完整性校验失败')
        result_names = result.namelist()
        if result_names != audit['member_names']:
            raise TranslationError('输出 DOCX 的包成员发生变化')
        for name, expected in audit['media_hashes'].items():
            if hashlib.sha256(result.read(name)).hexdigest() != expected:
                raise TranslationError('输出 DOCX 的图片或媒体发生变化')
        verified_structure = {}
        for name, expected in audit['structure'].items():
            xml = result.read(name).decode('utf-8')
            observed = {
                'paragraphs': len(_PARAGRAPH_RE.findall(xml)),
                'tables': _ooxml_tag_count(xml, 'w:tbl'),
                'drawings': _ooxml_tag_count(xml, 'w:drawing'),
            }
            if observed != expected:
                raise TranslationError('输出 DOCX 的段落、表格或图片结构发生变化')
            verified_structure[name] = observed
    return {
        'package_members_unchanged': True,
        'media_hashes_unchanged': True,
        'ooxml_structure_unchanged': True,
        'structure': verified_structure,
    }


def _mask_segment(text: str, glossary: list[dict[str, str]], serial_start: int = 0) -> tuple[str, dict[str, str]]:
    masked = text
    replacements: dict[str, str] = {}
    serial = serial_start

    def protect_span(start: int, end: int, replacement: str) -> None:
        nonlocal masked, serial
        token = f'[[KEEP_{serial:06d}]]'
        serial += 1
        masked = masked[:start] + token + masked[end:]
        replacements[token] = replacement

    for pair in sorted(glossary, key=lambda item: len(item['source']), reverse=True):
        pattern = re.compile(re.escape(pair['source']), re.IGNORECASE)
        matches = list(pattern.finditer(masked))
        for match in reversed(matches):
            protect_span(match.start(), match.end(), pair['target'])
    for pattern in _PROTECTED_PATTERNS:
        matches = [match for match in pattern.finditer(masked) if '[[KEEP_' not in match.group(0)]
        for match in reversed(matches):
            protect_span(match.start(), match.end(), match.group(0))
    return masked, replacements


def _restore_segment(text: str, replacements: dict[str, str]) -> str:
    restored = text
    for token, replacement in replacements.items():
        if restored.count(token) != 1:
            raise ModelStructureError('模型改变了受保护的术语、引用、链接或数字')
        restored = restored.replace(token, replacement)
    if re.search(r'\[\[KEEP_\d+\]\]', restored):
        raise ModelStructureError('模型返回了未知保护标记')
    return restored


def _validate_translation_content(source: str, translated: str) -> None:
    """Reject visibly empty or cut-off translations before checkpointing."""
    source = source.strip()
    translated = translated.strip()
    if source and not translated:
        raise ModelStructureError('模型返回了空译文')
    if re.search(r'[.!?][\"\'\u2019\u201d)]*$', source) and not re.search(
            r'[。！？.!?》〉】”’\"\')\]）]$', translated):
        raise ModelStructureError('模型译文疑似在句末截断')


class AcademicTranslationClient:
    """Strict JSON client for a local OpenAI-compatible inference server."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 timeout: int = 240, retries: int = 2):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout
        self.retries = retries

    def health(self) -> dict:
        started = time.monotonic()
        try:
            response = requests.get(f'{self.base_url}/models', timeout=4)
            response.raise_for_status()
            models = [item.get('id') for item in response.json().get('data', []) if isinstance(item, dict)]
            return {
                'available': self.model in models or bool(models),
                'configured_model': self.model,
                'served_models': models,
                'latency_ms': round((time.monotonic() - started) * 1000),
            }
        except Exception:
            return {
                'available': False,
                'configured_model': self.model,
                'served_models': [],
                'latency_ms': round((time.monotonic() - started) * 1000),
            }

    def translate_units(self, units: list[TranslationUnit], options: dict,
                        progress: Callable[[int, int], None] | None = None,
                        checkpoint: Callable[[dict], None] | None = None) -> None:
        batches: list[list[TranslationUnit]] = []
        current: list[TranslationUnit] = []
        current_chars = 0
        for unit in units:
            if current and (
                current_chars + unit.translatable_chars > TRANSLATION_BATCH_CHARS
                or len(current) >= TRANSLATION_BATCH_UNITS
            ):
                batches.append(current)
                current, current_chars = [], 0
            current.append(unit)
            current_chars += unit.translatable_chars
        if current:
            batches.append(current)

        completed = 0
        checkpoint_index = 0

        def translate_batch_with_fallback(batch: list[TranslationUnit]) -> None:
            nonlocal completed, checkpoint_index
            try:
                result = self._translate_batch(batch, options)
            except ModelStructureError:
                if len(batch) <= 1:
                    raise
                midpoint = len(batch) // 2
                translate_batch_with_fallback(batch[:midpoint])
                translate_batch_with_fallback(batch[midpoint:])
                return
            for unit in batch:
                unit.translations = result[unit.unit_id]
            completed += len(batch)
            checkpoint_index += 1
            if checkpoint:
                checkpoint({
                    'batch': checkpoint_index,
                    'unit_ids': [unit.unit_id for unit in batch],
                    'translations': result,
                    'completed_at': _utc_now(),
                })
            if progress:
                progress(completed, len(units))

        for batch in batches:
            translate_batch_with_fallback(batch)

    def _translate_batch(self, units: list[TranslationUnit], options: dict) -> dict[str, dict[str, str]]:
        glossary = options.get('glossary') or []
        payload_units = []
        masks: dict[tuple[str, str], dict[str, str]] = {}
        sources: dict[tuple[str, str], str] = {}
        expected: dict[str, set[str]] = {}
        serial = 0
        for unit in units:
            segments = []
            translatable_ids = set()
            for segment in unit.segments:
                item = {'id': segment.segment_id, 'translate': not segment.locked}
                if segment.locked:
                    item['text'] = segment.core_text
                else:
                    masked, replacements = _mask_segment(segment.core_text, glossary, serial)
                    serial += len(replacements) + 1
                    item['text'] = masked
                    masks[(unit.unit_id, segment.segment_id)] = replacements
                    sources[(unit.unit_id, segment.segment_id)] = segment.core_text
                    translatable_ids.add(segment.segment_id)
                segments.append(item)
            expected[unit.unit_id] = translatable_ids
            payload_units.append({'id': unit.unit_id, 'segments': segments})

        system = (
            'You are a meticulous academic paper translator. Translate only segments where translate=true '
            f"from {options['source_language']} to {options['target_language']}. Use publication-quality "
            f"academic language suitable for {options['domain']}. Read every segment in a unit as shared context. "
            'Preserve meaning, hedging, construct distinctions, causal strength, and terminology. '
            'Keep author personal names in their original spelling. '
            'Tokens like [[KEEP_000001]] are immutable and must appear exactly once. '
            'Do not translate segments where translate=false and do not return them. '
            'Return JSON only with this exact shape: '
            '{"units":[{"id":"same unit id","segments":[{"id":"same translatable segment id","text":"translation"}]}]}. '
            'Return every requested unit and every translatable segment exactly once. No notes or markdown. /no_think'
        )
        user = json.dumps({'units': payload_units}, ensure_ascii=False, separators=(',', ':'))
        body = {
            'model': self.model,
            'temperature': 0.1,
            'top_p': 0.8,
            'seed': 20260721,
            # The deployed Qwen endpoint has an 8K context window.  Keep the
            # output reservation comfortably below that ceiling after the
            # system prompt and masked source JSON are counted by vLLM.
            'max_tokens': min(5000, max(1200, int(sum(unit.translatable_chars for unit in units) * 1.35))),
            'response_format': {'type': 'json_object'},
            'chat_template_kwargs': {'enable_thinking': False},
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(
                    f'{self.base_url}/chat/completions', json=body, timeout=self.timeout,
                    headers={'Content-Type': 'application/json'},
                )
                if response.status_code >= 400:
                    raise TranslationError(f'本地模型服务返回 HTTP {response.status_code}')
                content = response.json()['choices'][0]['message']['content']
                try:
                    parsed = json.loads(content)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ModelStructureError('模型未返回有效 JSON') from exc
                return self._validate_response(parsed, expected, masks, sources)
            except ModelStructureError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        if isinstance(last_error, TranslationError):
            raise last_error
        raise TranslationError('本地模型响应无法解析或未满足结构校验') from last_error

    @staticmethod
    def _validate_response(parsed: dict, expected: dict[str, set[str]],
                           masks: dict[tuple[str, str], dict[str, str]],
                           sources: dict[tuple[str, str], str]) -> dict[str, dict[str, str]]:
        rows = parsed.get('units') if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            raise ModelStructureError('模型未返回 units 数组')
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                raise ModelStructureError('模型返回了无效的单元标识')
            unit_id = row['id']
            if unit_id in result or unit_id not in expected:
                raise ModelStructureError('模型返回了重复或未知单元')
            segment_rows = row.get('segments')
            if not isinstance(segment_rows, list):
                raise ModelStructureError('模型未返回 segments 数组')
            translated: dict[str, str] = {}
            for segment in segment_rows:
                if not isinstance(segment, dict):
                    raise ModelStructureError('模型返回了无效片段')
                segment_id = str(segment.get('id'))
                text = segment.get('text')
                if segment_id in translated or segment_id not in expected[unit_id] or not isinstance(text, str):
                    raise ModelStructureError('模型返回了重复、未知或非文本片段')
                restored = _restore_segment(text, masks[(unit_id, segment_id)])
                _validate_translation_content(sources[(unit_id, segment_id)], restored)
                translated[segment_id] = restored
            if set(translated) != expected[unit_id]:
                raise ModelStructureError('模型返回的片段数量与输入不一致')
            result[unit_id] = translated
        if set(result) != set(expected):
            raise ModelStructureError('模型返回的单元数量与输入不一致')
        return result

    # ---- Summarization (map/reduce over the same tunnelled endpoint) ---------

    def summarize_sections(self, units: list[dict], options: dict,
                           on_batch: Callable[[dict[str, str]], None]) -> None:
        """Map step: batch section units, summarize each, report {unit_id: summary}."""
        batches: list[list[dict]] = []
        current: list[dict] = []
        current_chars = 0
        for unit in units:
            if current and (current_chars + len(unit['text']) > TRANSLATION_BATCH_CHARS
                            or len(current) >= TRANSLATION_BATCH_UNITS):
                batches.append(current)
                current, current_chars = [], 0
            current.append(unit)
            current_chars += len(unit['text'])
        if current:
            batches.append(current)

        def run_batch(batch: list[dict]) -> None:
            try:
                mapped = self._summarize_batch(batch, options)
            except ModelStructureError:
                if len(batch) <= 1:
                    raise
                midpoint = len(batch) // 2
                run_batch(batch[:midpoint])
                run_batch(batch[midpoint:])
                return
            on_batch(mapped)

        for batch in batches:
            run_batch(batch)

    def _summarize_batch(self, units: list[dict], options: dict) -> dict[str, str]:
        payload = [{'id': unit['unit_id'], 'title': unit['title'], 'text': unit['text']}
                   for unit in units]
        expected = {unit['unit_id'] for unit in units}
        target = options['target_language']
        system = (
            'You are a meticulous academic reader. For each section object, write a faithful '
            f'summary in {target} of 2-4 sentences covering the section purpose, method or '
            'content, and key finding. Preserve technical terms, hedging, and construct '
            'distinctions. Do not invent facts not present in the section. Keep author names '
            'in original spelling. Return JSON only with this exact shape: '
            '{"summaries":[{"id":"same section id","summary":"..."}]}. '
            'Return every requested section exactly once. No notes or markdown. /no_think'
        )
        user = json.dumps({'sections': payload}, ensure_ascii=False, separators=(',', ':'))
        content = self._chat(system, user,
                             max_tokens=min(4000, max(600, int(sum(len(u['text']) for u in units) * 0.5))))
        try:
            parsed = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ModelStructureError('模型未返回有效 JSON') from exc
        rows = parsed.get('summaries') if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            raise ModelStructureError('模型未返回 summaries 数组')
        result: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ModelStructureError('模型返回了无效的小结项')
            unit_id = str(row.get('id'))
            summary = row.get('summary')
            if unit_id in result or unit_id not in expected or not isinstance(summary, str) or not summary.strip():
                raise ModelStructureError('模型返回了重复、未知或空的小结')
            result[unit_id] = summary.strip()
        if set(result) != expected:
            raise ModelStructureError('模型返回的小结数量与输入不一致')
        return result

    def synthesize_overall(self, section_summaries: list[dict], options: dict) -> str:
        """Reduce step: combine per-section summaries into a structured full summary.

        Hierarchical when the combined section summaries would overflow the window.
        """
        target = options['target_language']
        blocks = [f"[{item['title']}] {item['summary']}" for item in section_summaries]
        joined = '\n'.join(blocks)
        if len(joined) > 5000 and len(blocks) > 4:
            # First fold the section summaries into a few condensed digests.
            digests: list[str] = []
            chunk: list[str] = []
            chunk_chars = 0
            for block in blocks:
                if chunk and chunk_chars + len(block) > 4000:
                    digests.append(self._reduce_call(chunk, target, condensed=True))
                    chunk, chunk_chars = [], 0
                chunk.append(block)
                chunk_chars += len(block)
            if chunk:
                digests.append(self._reduce_call(chunk, target, condensed=True))
            blocks = digests
        return self._reduce_call(blocks, target, condensed=False)

    def _reduce_call(self, blocks: list[str], target: str, condensed: bool) -> str:
        if condensed:
            system = (f'Condense these academic section notes into a single tight paragraph in '
                      f'{target}, preserving key methods and findings. Plain text only. /no_think')
        else:
            system = (
                'You synthesize an academic paper summary from per-section notes. '
                f'Write in {target} using exactly these four markdown headings and nothing else: '
                '「## 研究问题」「## 方法与数据」「## 主要发现」「## 贡献与局限」. '
                'Be concise and faithful; do not invent anything beyond the notes. /no_think'
            )
        user = '\n'.join(blocks)
        return self._chat(system, user, max_tokens=1600, response_json=False).strip()

    def _chat(self, system: str, user: str, max_tokens: int, response_json: bool = True) -> str:
        body = {
            'model': self.model,
            'temperature': 0.2,
            'top_p': 0.8,
            'seed': 20260721,
            'max_tokens': max_tokens,
            'chat_template_kwargs': {'enable_thinking': False},
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
        }
        if response_json:
            body['response_format'] = {'type': 'json_object'}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = requests.post(
                    f'{self.base_url}/chat/completions', json=body, timeout=self.timeout,
                    headers={'Content-Type': 'application/json'})
                if response.status_code >= 400:
                    raise TranslationError(f'本地模型服务返回 HTTP {response.status_code}')
                return response.json()['choices'][0]['message']['content']
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise TranslationError('本地模型响应无法获取') from last_error


def _text_units(text: str) -> tuple[list[TranslationUnit], list[tuple[str, str]]]:
    units: list[TranslationUnit] = []
    line_records: list[tuple[str, str]] = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        ending_match = re.search(r'(\r\n|\n|\r)$', line)
        ending = ending_match.group(1) if ending_match else ''
        content = line[:-len(ending)] if ending else line
        leading, core, trailing = _split_outer_whitespace(content)
        line_records.append((content, ending))
        if core and _TRANSLATABLE_RE.search(core):
            units.append(TranslationUnit(
                unit_id=f'line:{index}', part_name='text', paragraph_start=index,
                paragraph_end=index + 1, paragraph_xml=content,
                segments=[Segment('0', content, locked=False, leading=leading, trailing=trailing)],
            ))
    return units, line_records


def _unit_source_sha256(unit, legacy_publisher_glyphs: bool = False) -> str:
    payload = [
        {
            'id': segment.segment_id,
            'text': segment.core_text.replace('\u2212', '\x01')
            if legacy_publisher_glyphs else segment.core_text,
            'locked': segment.locked,
        }
        for segment in unit.segments
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _cached_translation_compatible(unit, translations: dict) -> dict[str, str] | None:
    expected_ids = {segment.segment_id for segment in unit.segments if not segment.locked}
    if not isinstance(translations, dict) or set(translations) != expected_ids:
        return None
    normalized = {key: str(value).replace('\x01', '\u2212') for key, value in translations.items()}
    for segment in unit.segments:
        if segment.locked:
            continue
        target = normalized[segment.segment_id]
        source = segment.core_text
        try:
            _validate_translation_content(source, target)
        except ModelStructureError:
            return None
        for pattern in [_COVID_RE, *_AUTHOR_YEAR_PATTERNS]:
            literals = [match.group(0) for match in pattern.finditer(source)]
            if any(target.count(literal) < literals.count(literal) for literal in set(literals)):
                return None
    return normalized


def _load_checkpoint_translations(checkpoint_path: Path, unit_hash_path: Path,
                                  units: list) -> int:
    if not checkpoint_path.is_file():
        return 0
    legacy_hashes: dict[str, str] = {}
    if unit_hash_path.is_file():
        try:
            payload = json.loads(unit_hash_path.read_text(encoding='utf-8'))
            legacy_hashes = payload.get('units') if isinstance(payload.get('units'), dict) else {}
        except Exception:
            legacy_hashes = {}
    cached_by_hash: dict[str, list[dict]] = {}
    try:
        records = checkpoint_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return 0
    for raw in records:
        try:
            record = json.loads(raw)
            translations = record.get('translations') or {}
            recorded_hashes = record.get('source_sha256') or {}
            for unit_id, values in translations.items():
                source_hash = recorded_hashes.get(unit_id) or legacy_hashes.get(unit_id)
                if isinstance(source_hash, str) and isinstance(values, dict):
                    cached_by_hash.setdefault(source_hash, []).append(values)
        except Exception:
            continue
    restored = 0
    for unit in units:
        source_hash = _unit_source_sha256(unit)
        candidate_hashes = [source_hash]
        legacy_hash = legacy_hashes.get(unit.unit_id)
        if legacy_hash and legacy_hash == _unit_source_sha256(unit, legacy_publisher_glyphs=True):
            candidate_hashes.append(legacy_hash)
        candidates = [
            candidate for candidate_hash in dict.fromkeys(candidate_hashes)
            for candidate in cached_by_hash.get(candidate_hash, [])
        ]
        for candidate in candidates:
            compatible = _cached_translation_compatible(unit, candidate)
            if compatible is not None:
                unit.translations = compatible
                restored += 1
                break
    return restored


def _write_unit_hash_index(path: Path, units: list) -> None:
    if path.exists():
        return
    payload = {
        'schema_version': 1,
        'units': {unit.unit_id: _unit_source_sha256(unit) for unit in units},
    }
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


class PaperTranslationManager:
    """Persistent, thread-safe job manager with isolated private job folders."""

    def __init__(self, root: str | Path, client_factory: Callable[[], AcademicTranslationClient] | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self._client_factory = client_factory or (lambda: AcademicTranslationClient())
        self._lock = threading.RLock()
        self._active: set[str] = set()

    def config(self) -> dict:
        client = self._client_factory()
        return {
            'privacy_mode': 'local_files_ssh_tunnel',
            'supported_extensions': sorted(SUPPORTED_EXTENSIONS),
            'max_upload_bytes': TRANSLATION_MAX_UPLOAD_BYTES,
            'model': client.model,
            'batch_limits': {
                'characters': TRANSLATION_BATCH_CHARS,
                'units': TRANSLATION_BATCH_UNITS,
            },
            'model_service': client.health(),
            'job_storage': 'data/translation_jobs (gitignored, local only)',
            'pdf_format_preservation_supported': True,
            'pdf_support': {
                'mode': 'high_fidelity_text_layer_overlay',
                'lossless': False,
                'scanned_pdf_ocr_configured': False,
                'tables_preserved_in_original_language': True,
            },
        }

    def create_job(self, filename: str, content: bytes, options: dict | None,
                   start: bool = True) -> dict:
        filename = _safe_filename(filename)
        extension = Path(filename).suffix.casefold()
        if extension not in SUPPORTED_EXTENSIONS:
            raise TranslationError('当前仅支持 PDF、DOCX、TXT 和 Markdown')
        if not content:
            raise TranslationError('上传文件为空')
        if len(content) > TRANSLATION_MAX_UPLOAD_BYTES:
            raise TranslationError('上传文件超过隐私翻译模块的大小限制')
        options = normalize_options(options)
        job_id = uuid.uuid4().hex
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(mode=0o700)
        input_name = 'source' + extension
        input_path = job_dir / input_name
        with input_path.open('xb') as handle:
            handle.write(content)
        mode = options['mode']
        stem = Path(filename).stem
        suffix = self._target_suffix(options['target_language'])
        output_name = (f'{stem}_{suffix}{extension}'
                       if mode in {'translate', 'translate_summarize'} else None)
        summary_name = (f'{stem}_summary_{suffix}.md'
                        if mode in {'summarize', 'translate_summarize'} else None)
        warnings = []
        if extension == '.pdf' and output_name:
            warnings = [
                'PDF 使用高保真文本层回写，不是无损替换；中文长度变化可能触发局部字体缩放。',
                '为保护统计结果与版式，表格内容、页眉页脚、竖排版权文字和参考文献条目默认保留原文。',
                '扫描型 PDF 在本地 OCR/VLM 配置完成前会明确失败，不生成不完整译文。',
            ]
        if summary_name:
            warnings.append('总结为模型概括，可能有遗漏或偏差，重要判断请核对原文；总结与原文仅保存在本机。')
        manifest = {
            'schema_version': 1,
            'job_id': job_id,
            'status': 'queued',
            'mode': mode,
            'created_at': _utc_now(),
            'updated_at': _utc_now(),
            'original_filename': filename,
            'input_filename': input_name,
            'output_filename': output_name,
            'summary_filename': summary_name,
            'input_sha256': hashlib.sha256(content).hexdigest(),
            'input_bytes': len(content),
            'options': options,
            'model': self._client_factory().model,
            'translation_settings': {
                'batch_characters': TRANSLATION_BATCH_CHARS,
                'batch_units': TRANSLATION_BATCH_UNITS,
                'temperature': 0.1,
                'top_p': 0.8,
                'seed': 20260721,
            },
            'progress': {'total_units': 0, 'translated_units': 0, 'percent': 0},
            'warnings': warnings,
            'audit': {},
            'error': None,
        }
        self._write_manifest(job_id, manifest)
        if start:
            self._start(job_id)
        return self._public_manifest(manifest)

    def retry_job(self, job_id: str) -> dict:
        manifest = self._read_manifest(job_id)
        if manifest['status'] not in {'failed', 'interrupted'}:
            raise TranslationError('只有失败或中断的任务可以重试')
        manifest.update(status='queued', updated_at=_utc_now(), error=None)
        self._write_manifest(job_id, manifest)
        self._start(job_id)
        return self._public_manifest(manifest)

    def list_jobs(self) -> list[dict]:
        rows = []
        for manifest_path in self.root.glob('*/manifest.json'):
            try:
                rows.append(self._public_manifest(json.loads(manifest_path.read_text(encoding='utf-8'))))
            except Exception:
                continue
        return sorted(rows, key=lambda row: row.get('created_at', ''), reverse=True)[:30]

    def get_job(self, job_id: str) -> dict:
        return self._public_manifest(self._read_manifest(job_id))

    def output_path(self, job_id: str, kind: str = 'translation') -> tuple[Path, str]:
        manifest = self._read_manifest(job_id)
        if manifest['status'] != 'completed':
            raise TranslationError('任务尚未完成，不能下载')
        name = manifest.get('summary_filename' if kind == 'summary' else 'output_filename')
        if not name:
            raise TranslationError('该任务没有此类型的输出')
        output_path = self._job_dir(job_id) / name
        if not output_path.is_file():
            raise TranslationError('输出文件不存在')
        return output_path, name

    def delete_job(self, job_id: str) -> None:
        job_dir = self._job_dir(job_id)
        with self._lock:
            if job_id in self._active:
                raise TranslationError('运行中的任务不能删除')
        if not job_dir.is_dir():
            raise TranslationError('任务不存在')
        shutil.rmtree(job_dir)

    def run_job_sync(self, job_id: str) -> None:
        """Public synchronous hook used by tests and administrative recovery."""
        self._run(job_id)

    def _start(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._active:
                raise TranslationError('任务已在运行')
            self._active.add(job_id)
        threading.Thread(target=self._run, args=(job_id,), daemon=True,
                         name=f'paper-translation-{job_id[:8]}').start()

    def _run(self, job_id: str) -> None:
        try:
            with self._lock:
                self._active.add(job_id)
            manifest = self._read_manifest(job_id)
            manifest.update(status='running', started_at=_utc_now(), updated_at=_utc_now(), error=None)
            manifest.pop('failed_at', None)
            self._write_manifest(job_id, manifest)
            job_dir = self._job_dir(job_id)
            input_path = job_dir / manifest['input_filename']
            options = manifest['options']
            mode = manifest.get('mode') or options.get('mode') or 'translate'
            do_translate = mode in {'translate', 'translate_summarize'}
            do_summarize = mode in {'summarize', 'translate_summarize'}
            output_path = (job_dir / manifest['output_filename']) if manifest.get('output_filename') else None
            client = self._client_factory()
            checkpoint_path = job_dir / 'translations.jsonl'
            unit_hash_path = job_dir / 'unit_hashes.json'
            unit_by_id: dict[str, object] = {}
            resumed_units = 0
            audit: dict = {}
            units: list = []

            def checkpoint(record: dict) -> None:
                record = dict(record)
                record['source_sha256'] = {
                    unit_id: _unit_source_sha256(unit_by_id[unit_id])
                    for unit_id in record.get('unit_ids') or [] if unit_id in unit_by_id
                }
                with checkpoint_path.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + '\n')

            def progress(done: int, total: int, phase: str = 'translate') -> None:
                current = self._read_manifest(job_id)
                current['progress'] = {
                    'total_units': total,
                    'translated_units': done,
                    'percent': round(done * 100 / total, 1) if total else 100,
                }
                current['phase'] = phase
                current['updated_at'] = _utc_now()
                self._write_manifest(job_id, current)

            def translate_with_resume(extracted_units: list) -> None:
                nonlocal resumed_units
                unit_by_id.clear()
                unit_by_id.update({unit.unit_id: unit for unit in extracted_units})
                _write_unit_hash_index(unit_hash_path, extracted_units)
                resumed_units = _load_checkpoint_translations(
                    checkpoint_path, unit_hash_path, extracted_units)
                pending = [unit for unit in extracted_units if not unit.translations]
                progress(resumed_units, len(extracted_units))
                if pending:
                    client.translate_units(
                        pending, options,
                        progress=lambda done, _total: progress(
                            resumed_units + done, len(extracted_units)),
                        checkpoint=checkpoint,
                    )

            extension = input_path.suffix.casefold()
            if do_translate:
                if extension == '.docx':
                    parts, units, package_audit = extract_docx_units(
                        input_path, preserve_references=options['preserve_references'])
                    translate_with_resume(units)
                    if units:
                        if 'chinese' in options['target_language'].casefold() or '中文' in options['target_language']:
                            normalize_cjk_run_boundaries(units)
                    integrity = write_translated_docx(input_path, output_path, parts, units, package_audit)
                    audit = {
                        'input_type': 'docx',
                        'translated_units': len(units),
                        'resumed_units': resumed_units,
                        'xml_parts_scanned': package_audit['xml_parts_scanned'],
                        'skipped': package_audit['skipped'],
                        **integrity,
                    }
                elif extension == '.pdf':
                    try:
                        units, pdf_bundle = extract_pdf_units(
                            input_path, preserve_references=options['preserve_references'])
                    except PdfFormatError as exc:
                        raise TranslationError(str(exc)) from exc
                    translate_with_resume(units)
                    try:
                        integrity = write_translated_pdf(
                            input_path, output_path, units, pdf_bundle)
                    except PdfFormatError as exc:
                        raise TranslationError(str(exc)) from exc
                    audit = {
                        'input_type': 'pdf',
                        'translated_units': len(units),
                        'resumed_units': resumed_units,
                        'text_chars_by_page': pdf_bundle.text_chars_by_page,
                        'skipped': pdf_bundle.skipped,
                        **integrity,
                    }
                else:
                    raw = input_path.read_bytes()
                    has_bom = raw.startswith(b'\xef\xbb\xbf')
                    try:
                        text = raw.decode('utf-8-sig')
                    except UnicodeDecodeError as exc:
                        raise TranslationError('TXT/Markdown 必须使用 UTF-8 编码') from exc
                    units, records = _text_units(text)
                    translate_with_resume(units)
                    translated_by_line = {
                        unit.paragraph_start: unit.segments[0].leading + unit.translations['0'] + unit.segments[0].trailing
                        for unit in units
                    }
                    output_text = ''.join(translated_by_line.get(index, content) + ending
                                          for index, (content, ending) in enumerate(records))
                    encoded = output_text.encode('utf-8')
                    if has_bom:
                        encoded = b'\xef\xbb\xbf' + encoded
                    temp_path = output_path.with_suffix(output_path.suffix + '.tmp')
                    temp_path.write_bytes(encoded)
                    os.replace(temp_path, output_path)
                    audit = {
                        'input_type': extension.lstrip('.'),
                        'translated_units': len(units),
                        'resumed_units': resumed_units,
                        'line_count_unchanged': len(records) == len(output_text.splitlines(keepends=True)),
                        'bom_preserved': has_bom,
                    }

            summary_result = None
            if do_summarize:
                from services.paper_summary_service import (
                    render_summary_markdown, summarize_document)
                summary_checkpoint_path = job_dir / 'summary.jsonl'
                summary_resume: dict[str, str] = {}
                if summary_checkpoint_path.is_file():
                    for line in summary_checkpoint_path.read_text(encoding='utf-8').splitlines():
                        try:
                            summary_resume.update(json.loads(line).get('unit_summaries') or {})
                        except (json.JSONDecodeError, AttributeError):
                            continue

                def summary_checkpoint(record: dict) -> None:
                    with summary_checkpoint_path.open('a', encoding='utf-8') as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + '\n')

                summary_result = summarize_document(
                    input_path, client, options,
                    progress=lambda done, total: progress(done, total, phase='summarize'),
                    checkpoint=summary_checkpoint, resume=summary_resume)
                summary_meta = {
                    'original_filename': manifest['original_filename'],
                    'target_language': options['target_language'],
                    'model': client.model,
                    'completed_at': _utc_now(),
                }
                markdown = render_summary_markdown(summary_meta, summary_result)
                summary_path = job_dir / manifest['summary_filename']
                summary_temp = summary_path.with_suffix(summary_path.suffix + '.tmp')
                summary_temp.write_text(markdown, encoding='utf-8')
                os.replace(summary_temp, summary_path)
                audit['summary'] = {
                    'section_count': summary_result['section_count'],
                    'unit_count': summary_result['unit_count'],
                    'summary_bytes': summary_path.stat().st_size,
                }

            final = self._read_manifest(job_id)
            update = dict(status='completed', completed_at=_utc_now(),
                          updated_at=_utc_now(), audit=audit, error=None, phase='done')
            if do_translate and output_path is not None:
                update['output_sha256'] = _sha256_file(output_path)
                update['output_bytes'] = output_path.stat().st_size
            if summary_result is not None:
                update['summary_preview'] = (summary_result.get('overall') or '')[:600]
            final.update(update)
            unit_total = len(units) if do_translate else (summary_result or {}).get('unit_count', 0)
            final['progress'] = {
                'total_units': unit_total, 'translated_units': unit_total, 'percent': 100,
            }
            self._write_manifest(job_id, final)
        except Exception as exc:
            try:
                manifest = self._read_manifest(job_id)
                manifest.update(
                    status='failed', updated_at=_utc_now(), failed_at=_utc_now(),
                    error=str(exc) if isinstance(exc, TranslationError) else '翻译任务发生内部错误',
                )
                self._write_manifest(job_id, manifest)
            except Exception:
                pass
        finally:
            with self._lock:
                self._active.discard(job_id)

    def _job_dir(self, job_id: str) -> Path:
        if not _JOB_ID_RE.fullmatch(job_id or ''):
            raise TranslationError('任务编号无效')
        path = (self.root / job_id).resolve()
        if path.parent != self.root:
            raise TranslationError('任务路径无效')
        return path

    def _read_manifest(self, job_id: str) -> dict:
        path = self._job_dir(job_id) / 'manifest.json'
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError as exc:
            raise TranslationError('任务不存在') from exc

    def _write_manifest(self, job_id: str, manifest: dict) -> None:
        path = self._job_dir(job_id) / 'manifest.json'
        temp = path.with_suffix('.json.tmp')
        with self._lock:
            temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, path)

    @staticmethod
    def _target_suffix(language: str) -> str:
        folded = language.casefold()
        if 'chinese' in folded or '中文' in folded:
            return 'zh'
        if 'english' in folded or '英文' in folded:
            return 'en'
        return re.sub(r'[^a-z0-9]+', '-', folded).strip('-')[:12] or 'translated'

    @staticmethod
    def _public_manifest(manifest: dict) -> dict:
        allowed = {
            'schema_version', 'job_id', 'status', 'mode', 'created_at', 'updated_at', 'started_at',
            'completed_at', 'failed_at', 'original_filename', 'output_filename', 'summary_filename',
            'input_sha256', 'output_sha256', 'input_bytes', 'output_bytes', 'options', 'model',
            'progress', 'phase', 'warnings', 'audit', 'error', 'summary_preview',
        }
        return {key: value for key, value in manifest.items() if key in allowed}
