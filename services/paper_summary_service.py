# -*- coding: utf-8 -*-
"""Privacy-preserving academic paper summarization (逐节小结 + 全文摘要).

Reuses the same local file handling and SSH-tunnelled model endpoint as the
translation module.  Only bounded section text is sent to the model; the source
document, section summaries, and the rendered Markdown all stay on the local
workstation under the job folder.

Two layers:
  * per-section summaries (map)   —— one concise summary per document section
  * full-text structured summary (reduce) —— synthesized from the section
    summaries into 研究问题 / 方法与数据 / 主要发现 / 贡献与局限.

The extractors are shared with the translation path so a single upload can be
both translated and summarized without parsing the file twice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Heading detection re-uses the same low-level helpers as translation so the two
# features never disagree about document structure.
from services.paper_translation_service import (
    TranslationError,
    _heading_level,
    _paragraph_plain_text,
    extract_docx_units,
)
from services.pdf_translation_service import PdfFormatError, extract_pdf_units

# A section carrying more than this many characters is split into sub-batches so
# a single map call stays comfortably inside the deployed 8K context window.
SUMMARY_SECTION_CHAR_BUDGET = 3200
SUMMARY_MAX_SECTIONS = 400

_MD_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*\S)\s*$')


@dataclass
class Section:
    """One document section: a heading (optional) plus its body paragraphs."""
    title: str
    level: int
    paragraphs: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return '\n'.join(p for p in self.paragraphs if p.strip())

    @property
    def chars(self) -> int:
        return len(self.title) + len(self.body)

    @property
    def is_empty(self) -> bool:
        return not self.title.strip() and not self.body.strip()


def _pdf_unit_text(unit) -> str:
    return ' '.join(seg.core_text.strip() for seg in unit.segments if seg.core_text.strip())


def extract_document_blocks(input_path: Path) -> list[tuple[int, str]]:
    """Return ordered (heading_level, text) blocks; level 0 = body paragraph.

    Shares the translation extractors so structure detection is identical.
    """
    extension = input_path.suffix.casefold()
    blocks: list[tuple[int, str]] = []
    if extension == '.docx':
        _parts, units, _audit = extract_docx_units(input_path, preserve_references=True)
        for unit in units:
            text = _paragraph_plain_text(unit.paragraph_xml).strip()
            if not text:
                continue
            level = _heading_level(unit.paragraph_xml)
            blocks.append((level if level and 1 <= level <= 6 else 0, text))
    elif extension == '.pdf':
        try:
            units, bundle = extract_pdf_units(input_path, preserve_references=True)
        except PdfFormatError as exc:
            raise TranslationError(str(exc)) from exc
        for unit in units:
            text = _pdf_unit_text(unit)
            if not text:
                continue
            region = bundle.regions.get(unit.unit_id)
            blocks.append((1 if (region and region.heading) else 0, text))
    elif extension in {'.txt', '.md'}:
        raw = input_path.read_bytes()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise TranslationError('TXT/Markdown 必须使用 UTF-8 编码') from exc
        # 逐行识别:markdown 标题即便紧跟正文(无空行)也要断成独立标题块。
        paragraph: list[str] = []

        def flush() -> None:
            joined = '\n'.join(paragraph).strip()
            if joined:
                blocks.append((0, joined))
            paragraph.clear()

        for line in text.splitlines():
            heading = _MD_HEADING_RE.match(line.strip())
            if heading:
                flush()
                blocks.append((len(heading.group(1)), heading.group(2)))
            elif not line.strip():
                flush()
            else:
                paragraph.append(line)
        flush()
    else:
        raise TranslationError('总结当前仅支持 PDF、DOCX、TXT 和 Markdown')
    return blocks


def group_sections(blocks: list[tuple[int, str]]) -> list[Section]:
    """Split ordered blocks into sections at each heading.

    Body content appearing before the first heading becomes an opening section.
    """
    sections: list[Section] = []
    current = Section(title='', level=0)
    for level, text in blocks:
        if level >= 1:
            if not current.is_empty:
                sections.append(current)
            current = Section(title=text, level=level)
        else:
            current.paragraphs.append(text)
    if not current.is_empty:
        sections.append(current)
    if not sections:
        raise TranslationError('未从文档中提取到可总结的正文')
    return sections[:SUMMARY_MAX_SECTIONS]


def _section_units(sections: list[Section]) -> list[dict]:
    """Flatten sections into model units, splitting oversized sections by paragraph."""
    units: list[dict] = []
    for index, section in enumerate(sections):
        label = section.title.strip() or '(开头)'
        if section.chars <= SUMMARY_SECTION_CHAR_BUDGET or not section.paragraphs:
            units.append({'section_index': index, 'part': 0, 'parts': 1,
                          'title': label, 'text': section.body or section.title})
            continue
        chunk: list[str] = []
        chunk_chars = 0
        chunks: list[str] = []
        for paragraph in section.paragraphs:
            if chunk and chunk_chars + len(paragraph) > SUMMARY_SECTION_CHAR_BUDGET:
                chunks.append('\n'.join(chunk))
                chunk, chunk_chars = [], 0
            chunk.append(paragraph)
            chunk_chars += len(paragraph)
        if chunk:
            chunks.append('\n'.join(chunk))
        for part, text in enumerate(chunks):
            units.append({'section_index': index, 'part': part, 'parts': len(chunks),
                          'title': label, 'text': text})
    return units


def summarize_document(input_path: Path, client, options: dict,
                       progress=None, checkpoint=None,
                       resume: dict[str, str] | None = None) -> dict:
    """Run the two-layer summary. Returns section summaries + overall structured text.

    progress(done, total) is reported over section units so a per-file progress
    bar matches the translation flow.  checkpoint(record) persists each finished
    map batch so an interrupted job can resume without re-billing the GPU.
    """
    blocks = extract_document_blocks(input_path)
    sections = group_sections(blocks)
    units = _section_units(sections)
    total = len(units)
    resume = resume or {}

    unit_summaries: dict[str, str] = {}
    pending = []
    for unit in units:
        key = f"{unit['section_index']}:{unit['part']}"
        unit['unit_id'] = key
        if key in resume:
            unit_summaries[key] = resume[key]
        else:
            pending.append(unit)
    if progress:
        progress(len(unit_summaries), total)

    def on_batch(mapped: dict[str, str]) -> None:
        unit_summaries.update(mapped)
        if checkpoint:
            checkpoint({'unit_summaries': mapped})
        if progress:
            progress(len(unit_summaries), total)

    if pending:
        client.summarize_sections(pending, options, on_batch)

    # Merge multi-part section summaries back in document order.
    section_summaries: list[dict] = []
    for index, section in enumerate(sections):
        parts = [unit_summaries.get(f'{index}:{p}', '')
                 for p in range(max(1, sum(1 for u in units if u['section_index'] == index)))]
        combined = ' '.join(part.strip() for part in parts if part.strip())
        if combined:
            section_summaries.append({
                'title': section.title.strip() or '(开头)',
                'level': section.level or 1,
                'summary': combined,
            })

    overall = client.synthesize_overall(section_summaries, options) if section_summaries else ''
    return {'section_summaries': section_summaries, 'overall': overall,
            'section_count': len(section_summaries), 'unit_count': total}


def render_summary_markdown(meta: dict, result: dict) -> str:
    """Render the two-layer summary as a self-contained Markdown document."""
    lines = [f"# 论文总结 · {meta.get('original_filename', '')}", '']
    lines.append(f"- 总结语言：{meta.get('target_language', '')}")
    lines.append(f"- 模型：{meta.get('model', '')}（校内 GPU，本机保存）")
    if meta.get('completed_at'):
        lines.append(f"- 完成时间：{meta['completed_at']}")
    lines.append(f"- 章节数：{result.get('section_count', 0)}")
    lines.append('')
    lines.append('## 全文摘要')
    lines.append('')
    lines.append(result.get('overall', '').strip() or '（未生成全文摘要）')
    lines.append('')
    lines.append('## 逐节小结')
    lines.append('')
    for item in result.get('section_summaries', []):
        lines.append(f"### {item['title']}")
        lines.append('')
        lines.append(item['summary'].strip())
        lines.append('')
    lines.append('---')
    lines.append('本总结由校内 GPU 上的开源模型生成，原文与总结仅保存在本机；'
                 '总结为模型概括，可能有遗漏或偏差，重要判断请核对原文。')
    return '\n'.join(lines).rstrip() + '\n'
