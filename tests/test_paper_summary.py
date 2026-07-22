# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from services.paper_summary_service import (
    Section, extract_document_blocks, group_sections, render_summary_markdown,
    summarize_document,
)
from services.paper_translation_service import PaperTranslationManager, normalize_options


class FakeSummaryClient:
    model = 'test/private-model'

    def health(self):
        return {'available': True, 'configured_model': self.model, 'served_models': [self.model]}

    def summarize_sections(self, units, options, on_batch):
        for unit in units:
            on_batch({unit['unit_id']: '小结:' + unit['title']})

    def synthesize_overall(self, section_summaries, options):
        return f'## 研究问题\nq\n## 方法与数据\nm\n## 主要发现\n{len(section_summaries)}节\n## 贡献与局限\nl'


class OutlineTests(unittest.TestCase):
    def _md(self, tmp: Path, text: str) -> Path:
        path = tmp / 'paper.md'
        path.write_text(text, encoding='utf-8')
        return path

    def test_markdown_headings_split_into_sections(self):
        with TemporaryDirectory() as tmp:
            path = self._md(Path(tmp), '# 引言\n\n开头一段。\n\n## 方法\n\n方法一段。\n\n## 结果\n\n结果一段。')
            blocks = extract_document_blocks(path)
            sections = group_sections(blocks)
        titles = [s.title for s in sections]
        self.assertEqual(titles, ['引言', '方法', '结果'])
        self.assertIn('方法一段', sections[1].body)

    def test_markdown_heading_glued_to_body_still_splits(self):
        # 标题紧跟正文、无空行分隔:仍应逐行断成独立章节(真实 E2E 抓到的场景)
        with TemporaryDirectory() as tmp:
            path = self._md(Path(tmp), '# 标题\n## 方法\n方法正文。\n## 结果\n结果正文。')
            sections = group_sections(extract_document_blocks(path))
        self.assertEqual([s.title for s in sections], ['标题', '方法', '结果'])
        self.assertIn('方法正文', sections[1].body)

    def test_body_before_first_heading_becomes_opening_section(self):
        with TemporaryDirectory() as tmp:
            path = self._md(Path(tmp), '一段没有标题的开头。\n\n# 正文\n\n正文段落。')
            sections = group_sections(extract_document_blocks(path))
        self.assertEqual(sections[0].title, '')
        self.assertIn('开头', sections[0].body)
        self.assertEqual(sections[1].title, '正文')

    def test_oversized_section_splits_but_merges_back(self):
        long_paragraphs = '\n\n'.join(f'段落{i} ' + '内容' * 400 for i in range(6))
        with TemporaryDirectory() as tmp:
            path = self._md(Path(tmp), '# 大节\n\n' + long_paragraphs)
            result = summarize_document(path, FakeSummaryClient(), normalize_options({'mode': 'summarize'}))
        # 一个超长 section 拆成多个 unit 翻译,但仍合并为一条 section 小结
        self.assertEqual(result['section_count'], 1)
        self.assertGreater(result['unit_count'], 1)
        self.assertTrue(result['overall'].startswith('## 研究问题'))


class SummaryJobTests(unittest.TestCase):
    def _md_job(self, manager, text, options):
        return manager.create_job('paper.md', text.encode('utf-8'), options, start=False)

    def test_summarize_only_job_produces_markdown_and_records_time(self):
        with TemporaryDirectory() as tmp:
            manager = PaperTranslationManager(tmp, client_factory=FakeSummaryClient)
            job = self._md_job(manager, '# A\n\n甲段。\n\n# B\n\n乙段。', {'mode': 'summarize'})
            manager.run_job_sync(job['job_id'])
            final = manager.get_job(job['job_id'])
            self.assertEqual(final['status'], 'completed')
            self.assertTrue(final.get('completed_at'))            # 记录完成时间
            self.assertIsNone(final.get('output_filename'))       # 纯总结无翻译件
            self.assertTrue(final['summary_filename'].endswith('.md'))
            self.assertEqual(final['progress']['percent'], 100)
            path, name = manager.output_path(job['job_id'], 'summary')
            body = path.read_text(encoding='utf-8')
        self.assertIn('全文摘要', body)
        self.assertIn('逐节小结', body)
        self.assertIn('### A', body)

    def test_summarize_only_rejects_translation_download(self):
        with TemporaryDirectory() as tmp:
            manager = PaperTranslationManager(tmp, client_factory=FakeSummaryClient)
            job = self._md_job(manager, '# A\n\n甲。', {'mode': 'summarize'})
            manager.run_job_sync(job['job_id'])
            with self.assertRaises(Exception):
                manager.output_path(job['job_id'], 'translation')

    def test_translate_summarize_produces_both_outputs(self):
        with TemporaryDirectory() as tmp:
            manager = PaperTranslationManager(tmp, client_factory=_TranslateAndSummarizeClient)
            job = self._md_job(manager, '# A\n\nhello world.', {'mode': 'translate_summarize'})
            manager.run_job_sync(job['job_id'])
            final = manager.get_job(job['job_id'])
            self.assertEqual(final['status'], 'completed')
            self.assertTrue(final['output_filename'])
            self.assertTrue(final['summary_filename'])
            manager.output_path(job['job_id'], 'translation')   # 两个输出都在
            manager.output_path(job['job_id'], 'summary')

    def test_summarize_resumes_from_checkpoint(self):
        with TemporaryDirectory() as tmp:
            manager = PaperTranslationManager(tmp, client_factory=_CountingClient)
            _CountingClient.calls = 0
            job = self._md_job(manager, '# A\n\n甲。\n\n# B\n\n乙。', {'mode': 'summarize'})
            job_dir = Path(tmp) / job['job_id']
            # 预写一条检查点,模拟已完成的 section 0
            (job_dir / 'summary.jsonl').write_text(
                json.dumps({'unit_summaries': {'0:0': '已缓存'}}, ensure_ascii=False) + '\n',
                encoding='utf-8')
            manager.run_job_sync(job['job_id'])
        # 只有 section 1 需要新算(section 0 从检查点恢复)
        self.assertEqual(_CountingClient.summarized, ['1:0'])


class _TranslateAndSummarizeClient(FakeSummaryClient):
    def translate_units(self, units, options, progress=None, checkpoint=None):
        for i, unit in enumerate(units, 1):
            unit.translations = {seg.segment_id: '译' + seg.core_text
                                 for seg in unit.segments if not seg.locked}
            if checkpoint:
                checkpoint({'unit_ids': [unit.unit_id], 'translations': {unit.unit_id: unit.translations}})
            if progress:
                progress(i, len(units))


class _CountingClient(FakeSummaryClient):
    calls = 0
    summarized: list = []

    def summarize_sections(self, units, options, on_batch):
        type(self).summarized = [u['unit_id'] for u in units]
        for unit in units:
            on_batch({unit['unit_id']: '新小结'})


if __name__ == '__main__':
    unittest.main()
