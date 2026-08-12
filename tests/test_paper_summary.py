# -*- coding: utf-8 -*-
import json
import os
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from services.paper_summary_service import (
    SUMMARY_CHECKPOINT_SCHEMA_VERSION, SUMMARY_MAX_SECTIONS,
    SUMMARY_SECTION_CHAR_BUDGET, Section, _section_units, extract_document_blocks,
    extract_question_evidence, group_sections, load_summary_checkpoint,
    rank_question_evidence, render_summary_markdown, summary_heading_set,
    summary_unit_sha256, summarize_document,
)
from services.paper_translation_service import (
    AcademicTranslationClient, ModelStructureError, PaperTranslationManager,
    TranslationError, normalize_options,
)


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

    def test_single_oversized_paragraph_is_also_bounded(self):
        sections = [Section('Results', 1, ['x' * (SUMMARY_SECTION_CHAR_BUDGET + 1500)])]
        units = _section_units(sections)
        self.assertGreater(len(units), 1)
        self.assertTrue(all(len(unit['text']) <= SUMMARY_SECTION_CHAR_BUDGET for unit in units))

    def test_title_only_section_is_not_sent_to_model(self):
        with TemporaryDirectory() as tmp:
            path = self._md(Path(tmp), '# Paper title\n## Abstract\nEvidence.\n')
            result = summarize_document(
                path, FakeSummaryClient(), normalize_options({'mode': 'summarize'}))
        self.assertEqual(result['section_count'], 1)
        self.assertEqual(result['section_summaries'][0]['title'], 'Abstract')
        self.assertEqual(result['audit']['title_only_sections_excluded'], 1)

    def test_section_limit_fails_instead_of_silent_truncation(self):
        blocks = []
        for index in range(SUMMARY_MAX_SECTIONS + 1):
            blocks.extend([(1, f'H{index}'), (0, 'body')])
        with self.assertRaisesRegex(TranslationError, '避免静默截断'):
            group_sections(blocks)

    def test_docx_summary_excludes_header_footer_and_comments(self):
        main = ('<w:document xmlns:w="x"><w:body>'
                '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Main</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Main evidence</w:t></w:r></w:p>'
                '</w:body></w:document>')
        extras = {
            'word/header1.xml': '<w:hdr xmlns:w="x"><w:p><w:r><w:t>Running header</w:t></w:r></w:p></w:hdr>',
            'word/footer1.xml': '<w:ftr xmlns:w="x"><w:p><w:r><w:t>Page footer</w:t></w:r></w:p></w:ftr>',
            'word/comments.xml': '<w:comments xmlns:w="x"><w:p><w:r><w:t>Private reviewer comment</w:t></w:r></w:p></w:comments>',
        }
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'paper.docx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('word/document.xml', main)
                for name, body in extras.items():
                    archive.writestr(name, body)
            audit = {}
            blocks = extract_document_blocks(path, audit=audit)
        joined = ' '.join(text for _level, text in blocks)
        self.assertIn('Main evidence', joined)
        self.assertNotIn('Running header', joined)
        self.assertNotIn('Page footer', joined)
        self.assertNotIn('Private reviewer comment', joined)
        self.assertEqual(audit['docx_non_body_units_excluded'], 3)

    def test_markdown_question_evidence_keeps_section_and_excludes_references(self):
        with TemporaryDirectory() as tmp:
            path = self._md(
                Path(tmp),
                '# Introduction\n\nThe paper studies digital work.\n\n'
                '# Methods\n\nThe sample contains 84 interviews.\n\n'
                '# References\n\nSmith, A. (2024). Reference only.',
            )
            evidence = extract_question_evidence(path)
            ranked = rank_question_evidence(evidence, 'How many interviews are in the sample?')
        self.assertTrue(evidence)
        self.assertTrue(all('Reference only' not in row['text'] for row in evidence))
        self.assertEqual(ranked[0]['title'], 'Methods')
        self.assertIn('84 interviews', ranked[0]['text'])
        self.assertRegex(ranked[0]['source_sha256'], r'^[0-9a-f]{64}$')

    def test_numbered_reference_heading_is_excluded_from_question_evidence(self):
        with TemporaryDirectory() as tmp:
            path = self._md(
                Path(tmp),
                '# 3. How AI reshapes collaboration\n\n'
                'Employees choose between coworkers and an AI system.\n\n'
                '# 7. References\n\n'
                'Bonabeau, E. (2002). Agent-based modeling: Methods.\n',
            )
            evidence = extract_question_evidence(path)
        joined = ' '.join(row['text'] for row in evidence)
        self.assertIn('Employees choose', joined)
        self.assertNotIn('Bonabeau', joined)

    def test_chinese_method_question_finds_model_description_without_methods_heading(self):
        with TemporaryDirectory() as tmp:
            path = self._md(
                Path(tmp),
                '# Introduction\n\nThe paper offers a methodological contribution.\n\n'
                '# 3. How AI reshapes collaboration\n\n'
                'We develop an agent-based model in which employees choose whether to '
                'collaborate, work independently, or delegate tasks to AI. Feedback updates '
                'future choices through reinforcement learning and repeated simulations.\n',
            )
            evidence = extract_question_evidence(path)
            ranked = rank_question_evidence(evidence, '他这个方法都写了什么？')
        self.assertEqual(ranked[0]['title'], '3. How AI reshapes collaboration')
        self.assertIn('reinforcement learning', ranked[0]['text'])

    def test_pdf_question_evidence_retains_page_number(self):
        import pymupdf
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'paper.pdf'
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((50, 70), 'METHODS', fontsize=14)
            page.insert_textbox(
                pymupdf.Rect(50, 100, 520, 180),
                'The sample includes eighty-four longitudinal interviews.',
                fontsize=10,
            )
            document.save(path)
            document.close()
            evidence = extract_question_evidence(path)
        self.assertTrue(evidence)
        self.assertEqual(evidence[0]['page_number'], 1)
        self.assertIn('第 1 页', evidence[0]['locator'])


class SummaryLanguageTests(unittest.TestCase):
    def test_english_heading_schema_and_wrapper_are_localized(self):
        self.assertEqual(summary_heading_set('English')[0], 'Research Question')
        rendered = render_summary_markdown(
            {'original_filename': 'paper.md', 'target_language': 'English',
             'model': 'local/model', 'completed_at': '2026-07-22T00:00:00Z'},
            {'section_count': 1, 'overall': '## Research Question\nQuestion',
             'section_summaries': [{'title': 'Methods', 'summary': 'Method.'}],
             'audit': {'block_count': 2, 'unit_count': 1}},
        )
        self.assertIn('# Paper Summary', rendered)
        self.assertIn('## Overall Summary', rendered)
        self.assertIn('Coverage audit', rendered)
        self.assertIn('- Summary language: English', rendered)
        self.assertIn('local/model (campus GPU; stored locally)', rendered)
        self.assertNotIn('论文总结', rendered)

    def test_language_and_completeness_audits_are_recorded(self):
        class EnglishSummaryClient:
            def summarize_sections(self, units, options, on_batch):
                on_batch({
                    unit['unit_id']: (
                        'The section explains the research design, evidence, and findings '
                        'without adding claims beyond the supplied source material.')
                    for unit in units
                })

            def synthesize_overall(self, section_summaries, options):
                return (
                    '## Research Question\nThe study asks how digital work changes collaboration.\n\n'
                    '## Methods and Data\nThe authors analyze longitudinal interview evidence.\n\n'
                    '## Key Findings\nThe evidence identifies a consistent coordination mechanism.\n\n'
                    '## Contributions and Limitations\nThe study clarifies the mechanism and its boundary conditions.')

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'paper.md'
            path.write_text('# Findings\n\nEvidence from the longitudinal study.', encoding='utf-8')
            result = summarize_document(
                path, EnglishSummaryClient(),
                normalize_options({'mode': 'summarize', 'target_language': 'English'}))
        self.assertEqual(result['audit']['completeness_audit']['status'], 'pass')
        self.assertEqual(result['audit']['language_audit']['status'], 'pass')
        self.assertGreater(result['audit']['language_audit']['target_script_ratio'], .9)

    def test_missing_map_unit_is_a_hard_completeness_failure(self):
        class IncompleteClient:
            def summarize_sections(self, units, options, on_batch):
                on_batch({units[0]['unit_id']: 'only one summary'})

            def synthesize_overall(self, section_summaries, options):
                return 'not reached'

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'paper.md'
            path.write_text('# A\n\nBody A.\n\n# B\n\nBody B.', encoding='utf-8')
            with self.assertRaisesRegex(TranslationError, '逐节小结不完整'):
                summarize_document(
                    path, IncompleteClient(),
                    normalize_options({'mode': 'summarize'}))

    def test_reduce_requires_four_fields_and_renders_localized_headings(self):
        class ScriptedClient(AcademicTranslationClient):
            def __init__(self):
                super().__init__(retries=0)
                self.system = ''

            def _chat(self, system, user, max_tokens, response_json=True):
                self.system = system
                return json.dumps({
                    'research_question': 'RQ', 'methods_and_data': 'Methods',
                    'key_findings': 'Findings',
                    'contributions_and_limitations': 'Contribution',
                })

        client = ScriptedClient()
        options = normalize_options({
            'mode': 'summarize', 'target_language': 'English',
            'domain': 'Information Systems',
            'glossary': [{'source': 'sensemaking', 'target': 'sensemaking'}],
        })
        output = client._reduce_call(['notes'], options, condensed=False)
        self.assertIn('## Research Question', output)
        self.assertIn('Research domain: Information Systems', client.system)
        self.assertIn('sensemaking = sensemaking', client.system)

    def test_reduce_rejects_incomplete_schema(self):
        class InvalidClient(AcademicTranslationClient):
            def __init__(self):
                super().__init__(retries=0)

            def _chat(self, system, user, max_tokens, response_json=True):
                return json.dumps({'research_question': 'RQ'})

        with self.assertRaises(ModelStructureError):
            InvalidClient()._reduce_call(
                ['notes'], normalize_options({'mode': 'summarize'}), condensed=False)


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
            self.assertRegex(final['summary_sha256'], r'^[0-9a-f]{64}$')
            self.assertEqual(final['summary_settings']['checkpoint_schema_version'],
                             SUMMARY_CHECKPOINT_SCHEMA_VERSION)
            self.assertEqual(final['progress']['percent'], 100)
            path, name = manager.output_path(job['job_id'], 'summary')
            self.assertEqual(final['summary_bytes'], path.stat().st_size)
            body = path.read_text(encoding='utf-8')
            records = [json.loads(line) for line in
                       (path.parent / 'summary.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(records)
            self.assertTrue(all(record['schema_version'] == SUMMARY_CHECKPOINT_SCHEMA_VERSION
                                for record in records))
            self.assertTrue(all(record.get('source_sha256') for record in records))
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
            options = normalize_options({'mode': 'summarize'})
            job = self._md_job(manager, '# A\n\n甲。\n\n# B\n\n乙。', options)
            job_dir = Path(tmp) / job['job_id']
            unit = {'unit_id': '0:0', 'section_index': 0, 'part': 0, 'parts': 1,
                    'title': 'A', 'text': '甲。'}
            (job_dir / 'summary.jsonl').write_text(
                json.dumps({
                    'schema_version': SUMMARY_CHECKPOINT_SCHEMA_VERSION,
                    'unit_summaries': {'0:0': '已缓存'},
                    'source_sha256': {'0:0': summary_unit_sha256(unit, options)},
                }, ensure_ascii=False) + '\n',
                encoding='utf-8')
            manager.run_job_sync(job['job_id'])
        # 只有 section 1 需要新算(section 0 从检查点恢复)
        self.assertEqual(_CountingClient.summarized, ['1:0'])

    def test_legacy_or_wrong_hash_checkpoint_is_not_reused(self):
        with TemporaryDirectory() as tmp:
            manager = PaperTranslationManager(tmp, client_factory=_CountingClient)
            job = self._md_job(manager, '# A\n\nnew evidence', {'mode': 'summarize'})
            job_dir = Path(tmp) / job['job_id']
            (job_dir / 'summary.jsonl').write_text(
                json.dumps({'unit_summaries': {'0:0': 'stale'}}), encoding='utf-8')
            self.assertEqual(load_summary_checkpoint(job_dir / 'summary.jsonl'), {})
            manager.run_job_sync(job['job_id'])
        self.assertEqual(_CountingClient.summarized, ['0:0'])

    def test_changed_source_file_fails_input_hash_guard(self):
        with TemporaryDirectory() as tmp:
            manager = PaperTranslationManager(tmp, client_factory=FakeSummaryClient)
            job = self._md_job(manager, '# A\n\noriginal', {'mode': 'summarize'})
            job_dir = Path(tmp) / job['job_id']
            (job_dir / 'source.md').write_text('# A\n\nchanged', encoding='utf-8')
            manager.run_job_sync(job['job_id'])
            final = manager.get_job(job['job_id'])
        self.assertEqual(final['status'], 'failed')
        self.assertIn('原文件校验失败', final['error'])


class ManagerRecoveryTests(unittest.TestCase):
    def test_restart_marks_queued_and_running_jobs_interrupted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, status in enumerate(('queued', 'running')):
                job_id = f'{index + 1:032x}'
                job_dir = root / job_id
                job_dir.mkdir()
                (job_dir / 'manifest.json').write_text(json.dumps({
                    'schema_version': 1, 'job_id': job_id, 'status': status,
                    'created_at': '2026-07-22T00:00:00Z',
                    'updated_at': '2026-07-22T00:00:00Z',
                    'original_filename': 'paper.md', 'input_filename': 'source.md',
                    'options': {}, 'model': 'test', 'progress': {},
                }), encoding='utf-8')
            manager = PaperTranslationManager(root, client_factory=FakeSummaryClient)
            recovered = [manager.get_job(f'{index + 1:032x}') for index in range(2)]
        self.assertTrue(all(row['status'] == 'interrupted' for row in recovered))
        self.assertTrue(all(row.get('interrupted_at') for row in recovered))

    def test_live_worker_owner_is_not_reclassified_as_interrupted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            job_id = 'f' * 32
            job_dir = root / job_id
            job_dir.mkdir()
            (job_dir / 'manifest.json').write_text(json.dumps({
                'schema_version': 2, 'job_id': job_id, 'status': 'running',
                'worker_pid': os.getpid(),
                'created_at': '2026-07-22T00:00:00Z',
                'updated_at': '2026-07-22T00:00:00Z',
                'original_filename': 'paper.md', 'input_filename': 'source.md',
                'options': {}, 'model': 'test', 'progress': {},
            }), encoding='utf-8')
            manager = PaperTranslationManager(root, client_factory=FakeSummaryClient)
            row = manager.get_job(job_id)
        self.assertEqual(row['status'], 'running')
        self.assertIsNone(row.get('interrupted_at'))


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
