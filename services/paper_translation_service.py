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
from concurrent.futures import ThreadPoolExecutor
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


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _process_is_alive(pid) -> bool:
    """Cross-platform liveness check used to avoid cross-process false recovery."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.OpenProcess.argtypes = (
                wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = (
                wintypes.HANDLE, wintypes.DWORD)
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == 0x00000102
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# One worker is deliberately conservative: PDF extraction is CPU/memory heavy and
# Iverson serves a single shared Qwen instance.  Administrators may raise this to
# at most four after measuring the host, but queued jobs never create one thread
# per uploaded file.
TRANSLATION_MAX_CONCURRENT_JOBS = _bounded_int_env(
    'TRANSLATION_MAX_CONCURRENT_JOBS', 1, 1, 4)
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
    # A trailing period is not always a sentence boundary. PDF tables often
    # expose labels such as ``Std. Err.`` as standalone text units; requiring a
    # Chinese full stop there turns a correct table-header translation into a
    # deterministic false "truncation" failure. Keep the hard check for real
    # sentences, questions, and exclamations while exempting an explicit,
    # bounded set of common academic/table abbreviations.
    period_is_abbreviation = bool(re.search(
        r'(?i)(?:\b(?:std|err|coef|coeff|fig|eq|eqs|no|nos|vol|pp|vs|etc|'
        r'dr|prof|mr|mrs|ms)|\b(?:e\.g|i\.e|s\.e|et\s+al))\.'
        r'[\"\'\u2019\u201d)\]]*$', source))
    # Signature blocks commonly end with a degree rather than a sentence,
    # for example ``Zixing Shen, Ph.D.``. Limit this exemption to a short,
    # comma-delimited name/credential line so prose such as ``She earned a
    # Ph.D.`` still has to end with translated terminal punctuation.
    credential_metadata = len(source) <= 120 and bool(re.fullmatch(
        r"[\w\s.'\-\u00c0-\u024f]+,\s*(?:Ph\.?D|M\.?D|D\.?B\.?A|"
        r"J\.?D|M\.?B\.?A|M\.?S|M\.?A|B\.?S|B\.?A)\."
        r'[\"\'\u2019\u201d)\]]*', source, re.I))
    source_has_terminal = bool(re.search(r'[.!?][\"\'\u2019\u201d)]*$', source))
    if source_has_terminal and not period_is_abbreviation \
            and not credential_metadata and not re.search(
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
        self.validation_retries_used = 0
        self.protected_anchor_fallbacks_used = 0

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
            except ModelStructureError as initial_error:
                if len(batch) > 1:
                    midpoint = len(batch) // 2
                    translate_batch_with_fallback(batch[:midpoint])
                    translate_batch_with_fallback(batch[midpoint:])
                    return
                # A singleton cannot be split by unit any further.  Re-request
                # it with a different seed and an explicit validation-repair
                # instruction.  Previously the first malformed KEEP token or
                # missing terminal punctuation permanently failed the paper,
                # and a manual retry reproduced the same deterministic answer.
                last_error = initial_error
                for validation_attempt in range(1, self.retries + 1):
                    self.validation_retries_used += 1
                    try:
                        result = self._translate_batch(
                            batch, options, validation_attempt=validation_attempt)
                        break
                    except ModelStructureError as exc:
                        last_error = exc
                else:
                    # Some models consistently omit the first placeholder even
                    # after repair prompting.  In that case translate only the
                    # prose between immutable anchors, then reinsert protected
                    # values locally in exact source order.  The protected
                    # values themselves are still never entrusted to model
                    # output and all translated fragments retain hard checks.
                    repaired = None
                    for validation_attempt in range(
                            self.retries + 1, self.retries + 3):
                        self.validation_retries_used += 1
                        try:
                            repaired = self._translate_with_protected_anchors(
                                batch[0], options, validation_attempt)
                            break
                        except ModelStructureError as exc:
                            last_error = exc
                    if repaired is None:
                        raise last_error
                    self.protected_anchor_fallbacks_used += 1
                    result = repaired
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

    def _translate_with_protected_anchors(
            self, unit: TranslationUnit, options: dict,
            validation_attempt: int) -> dict[str, dict[str, str]] | None:
        """Translate prose fragments while reinserting immutable spans locally.

        Returns ``None`` when the unit contains no protected anchors, allowing
        the caller to preserve the original hard failure.
        """
        glossary = options.get('glossary') or []
        recipes: dict[str, list[tuple]] = {}
        fragment_texts: dict[str, str] = {}
        original_segments: dict[str, Segment] = {}
        serial = 0
        has_anchors = False

        for original in unit.segments:
            if original.locked:
                continue
            masked, replacements = _mask_segment(original.core_text, glossary, serial)
            serial += len(replacements) + 1
            original_segments[original.segment_id] = original
            if replacements:
                has_anchors = True
                token_pattern = re.compile(
                    '(' + '|'.join(re.escape(token) for token in replacements) + ')')
                pieces = token_pattern.split(masked)
            else:
                pieces = [masked]

            recipe: list[tuple] = []
            for part_index, piece in enumerate(pieces):
                if not piece:
                    continue
                if piece in replacements:
                    recipe.append(('anchor', replacements[piece]))
                    continue
                leading, core, trailing = _split_outer_whitespace(piece)
                if not core or not _TRANSLATABLE_RE.search(core):
                    recipe.append(('literal', piece))
                    continue
                segment_id = f'{original.segment_id}:text:{part_index}'
                fragment_texts[segment_id] = core
                recipe.append(('translation', segment_id, leading, trailing))
            recipes[original.segment_id] = recipe

        if not has_anchors:
            return None
        translated_fragments: dict[str, str] = {}
        # Request each prose fragment independently.  Asking one response to
        # echo many tiny fragments proved vulnerable to another omission mode;
        # singleton requests make the expected cardinality unambiguous.
        for fragment_index, (fragment_id, source_text) in enumerate(
                fragment_texts.items()):
            synthetic_id = (
                f'{unit.unit_id}:protected-anchor-fallback:{fragment_index}')
            synthetic = TranslationUnit(
                unit_id=synthetic_id,
                part_name='protected-anchor-fallback',
                paragraph_start=getattr(unit, 'paragraph_start', 0),
                paragraph_end=getattr(unit, 'paragraph_end', 0),
                paragraph_xml='',
                segments=[Segment('0', source_text)],
            )
            translated = self._translate_batch(
                [synthetic], options, validation_attempt=validation_attempt,
                fragment_mode=True)
            translated_fragments[fragment_id] = translated[synthetic_id]['0']
        restored: dict[str, str] = {}
        for segment_id, recipe in recipes.items():
            output: list[str] = []
            for item in recipe:
                if item[0] in {'anchor', 'literal'}:
                    output.append(item[1])
                else:
                    _kind, synthetic_id, leading, trailing = item
                    output.append(
                        leading + translated_fragments[synthetic_id] + trailing)
            value = ''.join(output)
            _validate_translation_content(
                original_segments[segment_id].core_text, value)
            restored[segment_id] = value
        return {unit.unit_id: restored}

    def _translate_batch(self, units: list[TranslationUnit], options: dict,
                         validation_attempt: int = 0,
                         fragment_mode: bool = False) -> dict[str, dict[str, str]]:
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

        placeholder_instruction = (
            'This request contains only prose fragments and no placeholder tokens. '
            'Never emit text matching [[KEEP_ followed by digits. '
            if fragment_mode else
            'Tokens like [[KEEP_000001]] are immutable and must appear exactly once. '
        )
        system = (
            'You are a meticulous academic paper translator. Translate only segments where translate=true '
            f"from {options['source_language']} to {options['target_language']}. Use publication-quality "
            f"academic language suitable for {options['domain']}. Read every segment in a unit as shared context. "
            'Preserve meaning, hedging, construct distinctions, causal strength, and terminology. '
            'Keep author personal names in their original spelling. '
            + placeholder_instruction +
            'Do not translate segments where translate=false and do not return them. '
            'Return JSON only with this exact shape: '
            '{"units":[{"id":"same unit id","segments":[{"id":"same translatable segment id","text":"translation"}]}]}. '
            'Return every requested unit and every translatable segment exactly once. No notes or markdown. /no_think'
        )
        if validation_attempt and not fragment_mode:
            system += (
                ' This is a validation-repair retry. Copy every [[KEEP_000000]] token '
                'byte-for-byte exactly once before translating the surrounding prose. '
                'Return a complete translation for every segment; when the source ends '
                'as a sentence, the translation must also end with appropriate terminal punctuation.'
            )
        elif validation_attempt:
            system += (
                ' This is a plain-prose validation repair. Return the complete translation '
                'without placeholders, commentary, prefixes, or suffixes. When the source '
                'ends as a sentence, use appropriate terminal punctuation.'
            )
        user = json.dumps({'units': payload_units}, ensure_ascii=False, separators=(',', ':'))
        body = {
            'model': self.model,
            'temperature': min(0.25, 0.1 + validation_attempt * 0.05),
            'top_p': 0.8,
            'seed': 20260721 + validation_attempt * 104729,
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

    @staticmethod
    def _summary_guidance(options: dict, source_text: str = '') -> str:
        """Bound domain/terminology guidance so summary controls are not cosmetic."""
        rows = options.get('glossary') or []
        folded_source = source_text.casefold()
        selected = []
        for pair in rows:
            source = str(pair.get('source') or '').strip()
            target = str(pair.get('target') or '').strip()
            if not source or not target:
                continue
            if source_text and source.casefold() not in folded_source:
                continue
            selected.append(f'{source} = {target}')
            if len(selected) >= 40 or sum(len(item) for item in selected) > 1400:
                break
        guidance = f"Research domain: {options.get('domain') or 'academic research'}."
        if selected:
            guidance += (' Use these terms consistently when the corresponding concept appears: '
                         + '; '.join(selected) + '.')
        return guidance

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
        guidance = self._summary_guidance(
            options, '\n'.join(unit['text'] for unit in units))
        system = (
            'You are a meticulous academic reader. For each section object, write a faithful '
            f'summary in {target} of 2-4 sentences covering the section purpose, method or '
            'content, and key finding. Preserve technical terms, hedging, and construct '
            'distinctions. Do not invent facts not present in the section. Keep author names '
            f'in original spelling. {guidance} Return JSON only with this exact shape: '
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
        blocks = [f"[{item['title']}] {item['summary']}" for item in section_summaries]
        if not blocks:
            raise ModelStructureError('没有可用于全文摘要的逐节小结')
        # Repeatedly fold bounded chunks until the final synthesis fits.  This is
        # intentionally recursive rather than a one-level reduction that can
        # overflow again for documents with hundreds of detected sections.
        for _level in range(6):
            if len('\n'.join(blocks)) <= 5000:
                break
            chunks: list[list[str]] = []
            chunk: list[str] = []
            chunk_chars = 0
            for block in blocks:
                if chunk and chunk_chars + 1 + len(block) > 4000:
                    chunks.append(chunk)
                    chunk, chunk_chars = [], 0
                chunk.append(block)
                chunk_chars += (1 if chunk_chars else 0) + len(block)
            if chunk:
                chunks.append(chunk)
            previous_chars = len('\n'.join(blocks))
            blocks = [self._reduce_call(items, options, condensed=True) for items in chunks]
            if len('\n'.join(blocks)) >= previous_chars:
                raise ModelStructureError('模型未能将逐节小结压缩到安全上下文范围')
        if len('\n'.join(blocks)) > 5000:
            raise ModelStructureError('全文摘要输入超过安全上下文范围')
        return self._reduce_call(blocks, options, condensed=False)

    def answer_question(self, evidence: list[dict], question: str,
                        history: list[dict], options: dict) -> dict:
        """Answer one paper question from bounded original-language evidence."""
        target = options.get('target_language') or 'Simplified Chinese / 简体中文'
        system = (
            'You are an evidence-bound academic reading assistant. Answer the user question '
            f'in {target} using only the supplied original-paper evidence. Prior conversation '
            'is conversational context, never evidence. Do not rely on a generated translation '
            'or summary. Preserve hedging, correlation-versus-causation distinctions, construct '
            'definitions, sample limits, and statistical uncertainty. If the evidence is '
            'insufficient, say what cannot be established and set not_found=true. Distinguish '
            'the authors\' claims from your interpretation. Answer the current question directly; '
            'do not repeat a previous answer merely because it appears in conversation context. '
            'When the user asks you to re-check or read more carefully, re-evaluate the supplied '
            'evidence and explain any corrected or newly supported conclusion. Cite supporting '
            'evidence IDs such '
            'as [E0001] in the answer. Return JSON only with exactly these keys: '
            '{"answer":"...", "evidence_ids":["E0001"], '
            '"confidence":"high|medium|low", "not_found":false}. /no_think'
        )
        safe_history = []
        for turn in history[-4:]:
            safe_history.append({
                'question': str(turn.get('question') or '')[:1000],
                'answer': str(turn.get('answer') or '')[:1600],
            })
        payload = {
            'question': question,
            'conversation_context': safe_history,
            'evidence': [{
                'id': row['evidence_id'],
                'location': row.get('locator') or row.get('title') or '正文',
                'title': row.get('title') or '正文',
                'text': row.get('text') or '',
            } for row in evidence],
        }
        expected_ids = {row['evidence_id'] for row in evidence}
        last_error: Exception | None = None
        for _attempt in range(self.retries + 1):
            try:
                content = self._chat(
                    system, json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                    max_tokens=1800, response_json=True)
                parsed = json.loads(content)
                if not isinstance(parsed, dict) or set(parsed) != {
                        'answer', 'evidence_ids', 'confidence', 'not_found'}:
                    raise ModelStructureError('模型未返回有效的文章问答 JSON')
                answer = parsed.get('answer')
                evidence_ids = parsed.get('evidence_ids')
                confidence = parsed.get('confidence')
                not_found = parsed.get('not_found')
                if not isinstance(answer, str) or not answer.strip():
                    raise ModelStructureError('模型返回了空回答')
                if (not isinstance(evidence_ids, list)
                        or any(not isinstance(item, str) for item in evidence_ids)):
                    raise ModelStructureError('模型返回了无效的证据编号')
                if len(evidence_ids) != len(set(evidence_ids)) \
                        or any(item not in expected_ids for item in evidence_ids):
                    raise ModelStructureError('模型引用了重复或未知的原文证据')
                if confidence not in {'high', 'medium', 'low'} or not isinstance(not_found, bool):
                    raise ModelStructureError('模型返回了无效的置信度或证据状态')
                if not not_found and not evidence_ids:
                    raise ModelStructureError('有结论的回答必须引用至少一条原文证据')
                inline_ids = set(re.findall(r'\[(E\d{4})\]', answer))
                if inline_ids - set(evidence_ids):
                    raise ModelStructureError('回答正文引用了未声明的原文证据')
                if not not_found and not inline_ids:
                    raise ModelStructureError('有结论的回答正文必须标注原文证据编号')
                return {
                    'answer': answer.strip(),
                    'evidence_ids': evidence_ids,
                    'confidence': confidence,
                    'not_found': not_found,
                }
            except (json.JSONDecodeError, ModelStructureError) as exc:
                last_error = exc
        if isinstance(last_error, ModelStructureError):
            raise last_error
        raise ModelStructureError('模型未返回有效的文章问答结果') from last_error

    def _reduce_call(self, blocks: list[str], options: dict, condensed: bool) -> str:
        target = options['target_language']
        guidance = self._summary_guidance(options)
        if condensed:
            system = (f'Condense these academic section notes into a single tight paragraph in '
                      f'{target}, preserving key methods and findings. {guidance} '
                      'Return JSON only as {"digest":"..."}. /no_think')
        else:
            system = (
                'You synthesize an academic paper summary from per-section notes. '
                f'Write concise, faithful content in {target}; do not invent anything beyond the notes. '
                f'{guidance} Return JSON only with exactly these four non-empty string keys: '
                '"research_question", "methods_and_data", "key_findings", '
                '"contributions_and_limitations". /no_think'
            )
        user = '\n'.join(blocks)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                content = self._chat(system, user, max_tokens=1600, response_json=True)
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ModelStructureError('模型未返回总结 JSON 对象')
                if condensed:
                    digest = parsed.get('digest')
                    if set(parsed) != {'digest'} or not isinstance(digest, str) or not digest.strip():
                        raise ModelStructureError('模型未返回有效的压缩小结')
                    return digest.strip()
                keys = (
                    'research_question', 'methods_and_data', 'key_findings',
                    'contributions_and_limitations',
                )
                if set(parsed) != set(keys) or any(
                        not isinstance(parsed.get(key), str) or not parsed[key].strip()
                        for key in keys):
                    raise ModelStructureError('模型返回的全文摘要字段不完整')
                from services.paper_summary_service import summary_heading_set
                headings = summary_heading_set(target)
                return '\n\n'.join(
                    f'## {heading}\n{parsed[key].strip()}'
                    for heading, key in zip(headings, keys)
                )
            except (json.JSONDecodeError, ModelStructureError) as exc:
                last_error = exc
                if attempt < self.retries:
                    continue
        if isinstance(last_error, ModelStructureError):
            raise last_error
        raise ModelStructureError('模型未返回有效的全文摘要 JSON') from last_error

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

    def __init__(self, root: str | Path,
                 client_factory: Callable[[], AcademicTranslationClient] | None = None,
                 max_concurrent_jobs: int | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        self._client_factory = client_factory or (lambda: AcademicTranslationClient())
        self._lock = threading.RLock()
        self._active: set[str] = set()
        self._question_locks: dict[str, threading.Lock] = {}
        configured_workers = (TRANSLATION_MAX_CONCURRENT_JOBS
                              if max_concurrent_jobs is None else max_concurrent_jobs)
        self.max_concurrent_jobs = max(1, min(4, int(configured_workers)))
        self._executor: ThreadPoolExecutor | None = None
        self._recover_stale_jobs()

    def _recover_stale_jobs(self) -> None:
        """Make crash/restart leftovers explicitly retryable without auto-using a GPU."""
        for manifest_path in self.root.glob('*/manifest.json'):
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception:
                continue
            if manifest.get('status') not in {'queued', 'running'}:
                continue
            # Another process may legitimately own this manager root (for
            # example a test importing server.py while the real server is
            # translating).  Never rewrite a live owner's manifest.
            if _process_is_alive(manifest.get('worker_pid')):
                continue
            job_id = manifest.get('job_id')
            if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
                continue
            manifest.update(
                status='interrupted',
                interrupted_at=_utc_now(),
                updated_at=_utc_now(),
                error='服务重启前任务未完成；本机检查点已保留，可重试续跑。',
            )
            manifest.pop('worker_pid', None)
            manifest.pop('worker_started_at', None)
            self._write_manifest(job_id, manifest)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.max_concurrent_jobs,
                    thread_name_prefix='paper-job',
                )
            return self._executor

    def shutdown(self, wait: bool = True) -> None:
        """Release queue workers; primarily used by tests and controlled shutdowns."""
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=not wait)

    def _finish_cancelled_submission(self, job_id: str, future) -> None:
        """Keep a cancelled queued job retryable instead of leaving it active forever."""
        if not future.cancelled():
            return
        with self._lock:
            self._active.discard(job_id)
        try:
            manifest = self._read_manifest(job_id)
            if manifest.get('status') == 'queued':
                now = _utc_now()
                manifest.update(
                    status='interrupted', interrupted_at=now, updated_at=now,
                    error='任务队列已关闭；本机原件与检查点已保留，可重试续跑。',
                )
                manifest.pop('worker_pid', None)
                manifest.pop('worker_started_at', None)
                self._write_manifest(job_id, manifest)
        except Exception:
            pass

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
            'max_concurrent_jobs': self.max_concurrent_jobs,
            'model_service': client.health(),
            'job_storage': 'data/translation_jobs (gitignored, local only)',
            'paper_questions': {
                'supported': True,
                'grounding': 'original_document_only',
                'history_storage': 'per-job JSONL (local only)',
                'citations': 'PDF page or source section/paragraph',
            },
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
        summary_settings = None
        if summary_name:
            from services.paper_summary_service import (
                SUMMARY_CHECKPOINT_SCHEMA_VERSION, SUMMARY_MAX_SECTIONS,
                SUMMARY_PROMPT_VERSION, SUMMARY_SECTION_CHAR_BUDGET,
            )
            summary_settings = {
                'prompt_version': SUMMARY_PROMPT_VERSION,
                'checkpoint_schema_version': SUMMARY_CHECKPOINT_SCHEMA_VERSION,
                'section_character_budget': SUMMARY_SECTION_CHAR_BUDGET,
                'maximum_sections': SUMMARY_MAX_SECTIONS,
                'temperature': 0.2,
                'top_p': 0.8,
                'seed': 20260721,
                'map_output': 'validated JSON',
                'reduce_output': 'validated four-field JSON rendered with localized headings',
            }
        manifest = {
            'schema_version': 2,
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
            'summary_settings': summary_settings,
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
        manifest.pop('failed_at', None)
        manifest.pop('interrupted_at', None)
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

    def question_history(self, job_id: str) -> dict:
        """Return validated local turns without exposing cached full-paper chunks."""
        manifest = self._read_manifest(job_id)
        if manifest.get('status') != 'completed':
            raise TranslationError('文章处理完成后才能开始问答')
        turns = self._load_question_turns(job_id, manifest.get('input_sha256'))
        return {
            'job_id': job_id,
            'original_filename': manifest.get('original_filename'),
            'model': manifest.get('model'),
            'turns': turns,
            'grounding': 'original_document_only',
        }

    def ask_question(self, job_id: str, question: str) -> dict:
        """Run a source-grounded question and append one auditable local turn."""
        question = re.sub(r'\s+', ' ', str(question or '')).strip()
        if len(question) < 2:
            raise TranslationError('请输入至少两个字符的问题')
        if len(question) > 2000:
            raise TranslationError('问题过长，请控制在 2000 个字符以内')
        manifest = self._read_manifest(job_id)
        if manifest.get('status') != 'completed':
            raise TranslationError('文章处理完成后才能开始问答')
        job_dir = self._job_dir(job_id)
        input_path = job_dir / manifest['input_filename']
        input_sha256 = manifest.get('input_sha256')
        if _sha256_file(input_path) != input_sha256:
            raise TranslationError('原文件校验失败，已停止文章问答')

        with self._lock:
            question_lock = self._question_locks.setdefault(job_id, threading.Lock())
        if not question_lock.acquire(blocking=False):
            raise TranslationError('这篇文章正在回答另一个问题，请稍后再问')
        try:
            from services.paper_summary_service import (
                QUESTION_PROMPT_VERSION,
                extract_question_evidence,
                rank_question_evidence,
            )
            evidence_cache_path = job_dir / 'question_evidence.json'
            evidence = self._load_question_evidence_cache(
                evidence_cache_path, input_sha256, QUESTION_PROMPT_VERSION)
            if evidence is None:
                evidence = extract_question_evidence(input_path)
                self._write_question_evidence_cache(
                    evidence_cache_path, input_sha256, QUESTION_PROMPT_VERSION, evidence)

            history = self._load_question_turns(job_id, input_sha256)
            retrieval_context = '\n'.join(
                turn.get('question', '') for turn in history[-2:])
            selected = rank_question_evidence(
                evidence, question, context=retrieval_context)
            if not selected:
                raise TranslationError('没有找到可供模型核对的原文证据')
            client = self._client_factory()
            result = client.answer_question(
                selected, question, history, manifest.get('options') or {})
            selected_by_id = {row['evidence_id']: row for row in selected}
            citations = []
            for evidence_id in result['evidence_ids']:
                row = selected_by_id[evidence_id]
                excerpt = re.sub(r'\s+', ' ', row.get('text') or '').strip()
                citations.append({
                    'evidence_id': evidence_id,
                    'title': row.get('title') or '正文',
                    'locator': row.get('locator') or row.get('title') or '正文',
                    'page_number': row.get('page_number'),
                    'excerpt': excerpt[:1200],
                    'source_sha256': row.get('source_sha256'),
                })
            turn = {
                'schema_version': 1,
                'turn_id': uuid.uuid4().hex,
                'created_at': _utc_now(),
                'question': question,
                'answer': result['answer'],
                'citations': citations,
                'confidence': result['confidence'],
                'not_found': result['not_found'],
                'model': client.model,
                'input_sha256': input_sha256,
                'prompt_version': QUESTION_PROMPT_VERSION,
                'retrieved_evidence_ids': [
                    row['evidence_id'] for row in selected],
            }
            with (job_dir / 'questions.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(turn, ensure_ascii=False) + '\n')
                handle.flush()
            return turn
        finally:
            question_lock.release()

    def _load_question_turns(self, job_id: str, input_sha256: str | None) -> list[dict]:
        path = self._job_dir(job_id) / 'questions.jsonl'
        if not path.is_file():
            return []
        turns = []
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if (not isinstance(row, dict) or row.get('schema_version') != 1
                    or row.get('input_sha256') != input_sha256
                    or not isinstance(row.get('question'), str)
                    or not isinstance(row.get('answer'), str)
                    or not isinstance(row.get('citations'), list)):
                continue
            turns.append({
                key: row.get(key) for key in (
                    'turn_id', 'created_at', 'question', 'answer', 'citations',
                    'confidence', 'not_found', 'model', 'prompt_version')
            })
        return turns[-50:]

    @staticmethod
    def _load_question_evidence_cache(path: Path, input_sha256: str,
                                      prompt_version: str) -> list[dict] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        evidence = payload.get('evidence') if isinstance(payload, dict) else None
        if (payload.get('input_sha256') != input_sha256
                or payload.get('prompt_version') != prompt_version
                or not isinstance(evidence, list) or not evidence):
            return None
        required = {'evidence_id', 'title', 'locator', 'text', 'source_sha256'}
        if any(not isinstance(row, dict) or not required.issubset(row)
               for row in evidence):
            return None
        return evidence

    @staticmethod
    def _write_question_evidence_cache(path: Path, input_sha256: str,
                                       prompt_version: str,
                                       evidence: list[dict]) -> None:
        payload = {
            'schema_version': 1,
            'input_sha256': input_sha256,
            'prompt_version': prompt_version,
            'created_at': _utc_now(),
            'evidence': evidence,
        }
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temp, path)

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

    def read_text_output(self, job_id: str, kind: str = 'summary') -> tuple[str, str]:
        """Return the text content of a viewable output (summary .md, or .txt/.md
        translation) for in-page preview without downloading. Binary outputs
        (PDF/DOCX) raise so the caller falls back to inline-open or download."""
        path, name = self.output_path(job_id, kind)
        if path.suffix.casefold() not in {'.md', '.txt'}:
            raise TranslationError('该文件为 PDF/DOCX，无法在页面内以文本预览')
        if path.stat().st_size > 4 * 1024 * 1024:
            raise TranslationError('文件过大，请下载后查看')
        return path.read_text(encoding='utf-8'), name

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
        try:
            manifest = self._read_manifest(job_id)
            manifest.update(
                worker_pid=os.getpid(), worker_started_at=_utc_now(),
                updated_at=_utc_now())
            self._write_manifest(job_id, manifest)
            future = self._ensure_executor().submit(self._run, job_id)
            future.add_done_callback(
                lambda completed, queued_job_id=job_id:
                self._finish_cancelled_submission(queued_job_id, completed))
        except Exception:
            with self._lock:
                self._active.discard(job_id)
            # Submission can fail after the manifest has been marked as owned
            # by this process (for example if the executor is shutting down).
            # Clear that ownership and leave the job explicitly retryable
            # instead of creating a permanent queued/live-owner contradiction.
            try:
                manifest = self._read_manifest(job_id)
                if manifest.get('status') == 'queued':
                    now = _utc_now()
                    manifest.update(
                        status='interrupted', interrupted_at=now,
                        updated_at=now,
                        error='任务未能提交到并发队列；本机原件与检查点已保留，可重试续跑。',
                    )
                    manifest.pop('worker_pid', None)
                    manifest.pop('worker_started_at', None)
                    self._write_manifest(job_id, manifest)
            except Exception:
                pass
            raise

    def _run(self, job_id: str) -> None:
        try:
            with self._lock:
                self._active.add(job_id)
            manifest = self._read_manifest(job_id)
            manifest.update(
                status='running', started_at=_utc_now(), updated_at=_utc_now(),
                worker_pid=os.getpid(), worker_started_at=_utc_now(), error=None)
            manifest.pop('failed_at', None)
            manifest.pop('interrupted_at', None)
            self._write_manifest(job_id, manifest)
            job_dir = self._job_dir(job_id)
            input_path = job_dir / manifest['input_filename']
            if _sha256_file(input_path) != manifest.get('input_sha256'):
                raise TranslationError('任务原文件校验失败；为避免复用错误检查点，已停止处理。')
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
                        'document_body_font_size': pdf_bundle.document_body_font_size,
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
                audit['validation_retries_used'] = getattr(
                    client, 'validation_retries_used', 0)
                audit['protected_anchor_fallbacks_used'] = getattr(
                    client, 'protected_anchor_fallbacks_used', 0)

            summary_result = None
            if do_summarize:
                from services.paper_summary_service import (
                    load_summary_checkpoint, render_summary_markdown,
                    summarize_document)
                summary_checkpoint_path = job_dir / 'summary.jsonl'
                summary_resume = load_summary_checkpoint(summary_checkpoint_path)

                def summary_checkpoint(record: dict) -> None:
                    record = dict(record)
                    record['completed_at'] = _utc_now()
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
                    **(summary_result.get('audit') or {}),
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
                summary_path = job_dir / manifest['summary_filename']
                update['summary_sha256'] = _sha256_file(summary_path)
                update['summary_bytes'] = summary_path.stat().st_size
            final.update(update)
            final.pop('worker_pid', None)
            final.pop('worker_started_at', None)
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
                    error=str(exc) if isinstance(exc, TranslationError) else '文档任务发生内部错误',
                )
                manifest.pop('worker_pid', None)
                manifest.pop('worker_started_at', None)
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
            'interrupted_at', 'input_sha256', 'output_sha256', 'summary_sha256',
            'input_bytes', 'output_bytes', 'summary_bytes', 'options', 'model',
            'summary_settings',
            'progress', 'phase', 'warnings', 'audit', 'error', 'summary_preview',
        }
        return {key: value for key, value in manifest.items() if key in allowed}
