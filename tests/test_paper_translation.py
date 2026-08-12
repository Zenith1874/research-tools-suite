# -*- coding: utf-8 -*-
"""Privacy, structure, and checkpoint guards for paper translation."""
import json
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from services.pdf_translation_service import (
    PdfLine,
    PdfRegion,
    PdfSegment,
    PdfUnit,
    _assign_columns,
    _effective_page_body_size,
    _infer_document_body_size,
    _is_heading,
    _join_pdf_lines,
    _region_html,
)
from services.paper_translation_service import (
    AcademicTranslationClient,
    ModelStructureError,
    PaperTranslationManager,
    Segment,
    TranslationError,
    TranslationUnit,
    _mask_segment,
    _load_checkpoint_translations,
    _restore_segment,
    _unit_source_sha256,
    _validate_translation_content,
    extract_docx_units,
    normalize_cjk_run_boundaries,
    write_translated_docx,
)
from scripts.check_translation_hosts import DEFAULT_HOSTS, choose_recommendation, probe
from scripts.manage_translation_vllm import DEFAULT_TRANSLATION_HOST
from scripts.watchdog import acquire_single_instance_lock, fresh_running_translation_job


CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''

DOCUMENT_XML = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
<w:body>
<w:p><w:r><w:t>Effects of </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>AI</w:t></w:r><w:r><w:t> on work (Smith, 2024).</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table evidence</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>References</w:t></w:r></w:p>
<w:p><w:r><w:t>Smith, A. (2024). An article title.</w:t></w:r></w:p>
<w:p><m:oMath><m:r><m:t>x=1</m:t></m:r></m:oMath><w:r><w:t>Formula explanation</w:t></w:r></w:p>
</w:body></w:document>'''


def make_docx(path: Path):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('[Content_Types].xml', CONTENT_TYPES)
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        archive.writestr('word/document.xml', DOCUMENT_XML)
        archive.writestr('word/media/image1.png', b'not-a-real-image-but-byte-stable')


def make_pdf(path: Path, scanned: bool = False):
    import pymupdf
    document = pymupdf.open()
    page = document.new_page(width=595, height=782)
    if scanned:
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pixmap.clear_with(245)
        page.insert_image(page.rect, pixmap=pixmap)
    else:
        page.insert_text((45, 28), 'SYNTHETIC JOURNAL HEADER', fontsize=7)
        page.insert_textbox(
            pymupdf.Rect(45, 65, 285, 145),
            'Algorithmic management affects employee autonomy. '
            'The relationship remains uncertain (Smith, 2024).',
            fontsize=9,
        )
        page.insert_text((45, 175), '1 | RESULTS', fontsize=12)
        page.insert_textbox(
            pymupdf.Rect(45, 195, 285, 260),
            'We find a cautious association rather than a causal effect.',
            fontsize=9,
        )
        # A simple ruled table must remain in its original language and geometry.
        page.draw_rect(pymupdf.Rect(310, 65, 550, 125), width=.8)
        page.draw_line((310, 95), (550, 95), width=.8)
        page.draw_line((430, 65), (430, 125), width=.8)
        page.insert_text((320, 85), 'Measure', fontsize=8)
        page.insert_text((440, 85), 'Mean', fontsize=8)
        page.insert_text((320, 115), 'Autonomy', fontsize=8)
        page.insert_text((440, 115), '3.20', fontsize=8)
        page.insert_text((310, 175), 'REFERENCES', fontsize=9)
        page.insert_textbox(
            pymupdf.Rect(310, 195, 550, 260),
            'Smith, A. (2024). A reference that must remain unchanged.',
            fontsize=8,
        )
        page.insert_text((45, 755), 'Synthetic Journal 1 (1): 1-2', fontsize=7)
    document.save(path)
    document.close()


class FakeClient:
    model = 'test/private-model'

    def health(self):
        return {'available': True, 'configured_model': self.model, 'served_models': [self.model]}

    def translate_units(self, units, options, progress=None, checkpoint=None):
        completed = 0
        for unit in units:
            unit.translations = {
                segment.segment_id: '译文-' + segment.core_text
                for segment in unit.segments if not segment.locked
            }
            completed += 1
            if checkpoint:
                checkpoint({'unit_ids': [unit.unit_id], 'translations': {unit.unit_id: unit.translations}})
            if progress:
                progress(completed, len(units))

    def summarize_sections(self, units, options, on_batch):
        for unit in units:
            on_batch({unit['unit_id']: '小结:' + unit['text'][:24]})

    def synthesize_overall(self, section_summaries, options):
        return ('## 研究问题\n占位\n## 方法与数据\n占位\n## 主要发现\n共 '
                f'{len(section_summaries)} 节\n## 贡献与局限\n占位')

    def answer_question(self, evidence, question, history, options):
        return {
            'answer': f'根据原文，问题“{question}”可由 [{evidence[0]["evidence_id"]}] 回答。',
            'evidence_ids': [evidence[0]['evidence_id']],
            'confidence': 'high',
            'not_found': False,
        }


class TranslationHostTests(unittest.TestCase):
    def test_default_allowed_hosts_exclude_simurgh_and_kaiju(self):
        self.assertEqual(DEFAULT_HOSTS, (
            'iverson.cs.nmsu.edu',
            'keller.cs.nmsu.edu',
            'lovelace.cs.nmsu.edu',
            'newton.cs.nmsu.edu',
            'riemann.cs.nmsu.edu',
        ))
        self.assertNotIn('simurgh.cs.nmsu.edu', DEFAULT_HOSTS)
        self.assertNotIn('kaiju.cs.nmsu.edu', DEFAULT_HOSTS)

    def test_iverson_is_the_default_translation_host(self):
        self.assertEqual(DEFAULT_TRANSLATION_HOST, 'iverson.cs.nmsu.edu')

    def test_recommendation_uses_least_loaded_idle_gpu(self):
        rows = [
            {'host': 'busy', 'gpus': [
                {'index': 0, 'memory_used_mib': 9000, 'utilization_percent': 99},
            ]},
            {'host': 'idle-b', 'gpus': [
                {'index': 0, 'memory_used_mib': 20, 'utilization_percent': 1},
            ]},
            {'host': 'idle-a', 'gpus': [
                {'index': 1, 'memory_used_mib': 10, 'utilization_percent': 2},
            ]},
        ]
        self.assertEqual(
            choose_recommendation(rows, max_used_mib=1024, max_utilization=10),
            {'host': 'idle-a', 'gpu_index': 1},
        )
        self.assertFalse(rows[0]['gpus'][0]['idle'])
        self.assertTrue(rows[2]['gpus'][0]['idle'])

    @mock.patch('scripts.check_translation_hosts.subprocess.run')
    def test_timed_out_host_does_not_abort_other_probes(self, run):
        run.side_effect = subprocess.TimeoutExpired(['ssh'], 25)
        self.assertEqual(
            probe('slow.example.edu', ['ssh']),
            {'host': 'slow.example.edu', 'reachable': False, 'error': ['SSH probe timed out']},
        )


class JobQueueTests(unittest.TestCase):
    def test_failed_executor_submission_clears_worker_ownership(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(
                temp_dir, client_factory=FakeClient, max_concurrent_jobs=1)
            job = manager.create_job(
                'paper.md', b'# A\n\nbody', {'mode': 'summarize'}, start=False)
            with mock.patch.object(
                    manager, '_ensure_executor', side_effect=RuntimeError('closed')):
                with self.assertRaises(RuntimeError):
                    manager._start(job['job_id'])
            manifest = json.loads(
                (Path(temp_dir) / job['job_id'] / 'manifest.json').read_text(
                    encoding='utf-8'))
            self.assertEqual(manifest['status'], 'interrupted')
            self.assertNotIn('worker_pid', manifest)
            self.assertNotIn('worker_started_at', manifest)

    def test_batch_jobs_respect_global_worker_limit(self):
        class BlockingClient(FakeClient):
            lock = threading.Lock()
            release = threading.Event()
            started = threading.Event()
            active = 0
            maximum_active = 0

            def summarize_sections(self, units, options, on_batch):
                with type(self).lock:
                    type(self).active += 1
                    type(self).maximum_active = max(
                        type(self).maximum_active, type(self).active)
                    type(self).started.set()
                try:
                    if not type(self).release.wait(3):
                        raise RuntimeError('test queue release timed out')
                    on_batch({unit['unit_id']: 'summary' for unit in units})
                finally:
                    with type(self).lock:
                        type(self).active -= 1

            def synthesize_overall(self, section_summaries, options):
                return ('## 研究问题\nq\n## 方法与数据\nm\n'
                        '## 主要发现\nf\n## 贡献与局限\nl')

        BlockingClient.release.clear()
        BlockingClient.started.clear()
        BlockingClient.active = 0
        BlockingClient.maximum_active = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(
                temp_dir, client_factory=BlockingClient, max_concurrent_jobs=1)
            first = manager.create_job(
                'one.md', b'# A\n\nbody', {'mode': 'summarize'})
            self.assertTrue(BlockingClient.started.wait(2))
            second = manager.create_job(
                'two.md', b'# B\n\nbody', {'mode': 'summarize'})
            time.sleep(.1)
            self.assertEqual(manager.get_job(second['job_id'])['status'], 'queued')
            self.assertEqual(BlockingClient.maximum_active, 1)
            BlockingClient.release.set()
            manager.shutdown(wait=True)
            self.assertEqual(manager.get_job(first['job_id'])['status'], 'completed')
            self.assertEqual(manager.get_job(second['job_id'])['status'], 'completed')
            self.assertEqual(BlockingClient.maximum_active, 1)


class WatchdogTranslationGuardTests(unittest.TestCase):
    def test_fresh_running_job_defers_restart_but_stale_job_does_not(self):
        now = datetime(2026, 7, 22, 21, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            job_dir = Path(temp_dir) / ('a' * 32)
            job_dir.mkdir()
            manifest_path = job_dir / 'manifest.json'
            manifest = {
                'job_id': 'a' * 32,
                'status': 'running',
                'updated_at': (now - timedelta(minutes=2)).isoformat(),
                'progress': {'translated_units': 19, 'total_units': 297},
            }
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            active = fresh_running_translation_job(temp_dir, now=now)
            self.assertEqual(active['job_id'], 'a' * 32)
            manifest['updated_at'] = (now - timedelta(minutes=11)).isoformat()
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            self.assertIsNone(fresh_running_translation_job(temp_dir, now=now))

    def test_only_one_watchdog_can_hold_the_instance_lock(self):
        first = acquire_single_instance_lock(5001, lock_port=0)
        self.assertIsNotNone(first)
        lock_port = first.getsockname()[1]
        try:
            second = acquire_single_instance_lock(5001, lock_port=lock_port)
            self.assertIsNone(second)
        finally:
            first.close()
        replacement = acquire_single_instance_lock(5001, lock_port=lock_port)
        self.assertIsNotNone(replacement)
        replacement.close()


class ProtectedTextTests(unittest.TestCase):
    def test_glossary_citation_doi_url_and_numbers_are_restored_exactly(self):
        source = ('Algorithmic management increased by 12.5% (Smith, 2024); '
                  'doi 10.1234/ABC.9 at https://example.org/a.')
        masked, replacements = _mask_segment(
            source, [{'source': 'Algorithmic management', 'target': '算法管理'}])
        self.assertNotIn('Algorithmic management', masked)
        self.assertNotIn('12.5%', masked)
        self.assertNotIn('10.1234/ABC.9', masked)
        restored = _restore_segment(masked, replacements)
        self.assertIn('算法管理', restored)
        self.assertIn('12.5%', restored)
        self.assertIn('(Smith, 2024)', restored)
        self.assertIn('10.1234/ABC.9', restored)
        self.assertIn('https://example.org/a', restored)

    def test_accented_author_year_and_covid_token_are_exact(self):
        source = 'Prior work (Vänni et al., 2017) changed during COVID-19.'
        masked, replacements = _mask_segment(source, [])
        self.assertNotIn('Vänni et al., 2017', masked)
        self.assertNotIn('COVID-19', masked)
        self.assertEqual(_restore_segment(masked, replacements), source)

    def test_missing_protected_token_is_a_hard_failure(self):
        with self.assertRaises(TranslationError):
            _restore_segment('译文', {'[[KEEP_000001]]': '2024'})

    def test_cut_off_sentence_is_a_hard_failure(self):
        with self.assertRaises(ModelStructureError):
            _validate_translation_content('A complete sentence.', '译文并')

    def test_pdf_table_abbreviation_is_not_misclassified_as_cut_off_sentence(self):
        _validate_translation_content(
            '2021–2022 Std. Err. Coef Std. Err.',
            '2021–2022 标准误 系数 标准误',
        )

    def test_signature_degree_is_not_misclassified_as_cut_off_sentence(self):
        _validate_translation_content('Zixing Shen, Ph.D.', 'Zixing Shen 博士')

    def test_sentence_ending_in_degree_still_requires_terminal_punctuation(self):
        with self.assertRaises(ModelStructureError):
            _validate_translation_content('She earned a Ph.D.', '她获得了博士学位')

    def test_checkpoint_resume_requires_source_hash_match(self):
        unit = TranslationUnit('u1', 'text', 0, 1, 'source', [Segment('0', 'Source sentence.')])
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint = Path(temp_dir) / 'translations.jsonl'
            checkpoint.write_text(json.dumps({
                'unit_ids': ['u1'],
                'source_sha256': {'u1': _unit_source_sha256(unit)},
                'translations': {'u1': {'0': '译文。'}},
            }) + '\n', encoding='utf-8')
            self.assertEqual(
                _load_checkpoint_translations(checkpoint, Path(temp_dir) / 'missing.json', [unit]), 1)
            changed = TranslationUnit('u1', 'text', 0, 1, 'changed', [Segment('0', 'Changed source.')])
            self.assertEqual(
                _load_checkpoint_translations(checkpoint, Path(temp_dir) / 'missing.json', [changed]), 0)

    def test_invalid_multi_unit_response_is_retried_as_smaller_batches(self):
        class SplitClient(AcademicTranslationClient):
            def _translate_batch(self, units, options, validation_attempt=0):
                if len(units) > 1:
                    raise ModelStructureError('synthetic structure mismatch')
                return {units[0].unit_id: {'0': '译文'}}

        units = [
            TranslationUnit(
                f'u{index}', 'text', index, index + 1, 'source',
                [Segment('0', 'source')],
            )
            for index in range(3)
        ]
        checkpoints = []
        SplitClient().translate_units(
            units, {}, checkpoint=checkpoints.append,
        )
        self.assertEqual([unit.translations['0'] for unit in units], ['译文'] * 3)
        self.assertEqual(len(checkpoints), 3)

    def test_invalid_singleton_is_re_requested_with_validation_repair(self):
        class RepairClient(AcademicTranslationClient):
            attempts = []

            def _translate_batch(self, units, options, validation_attempt=0):
                type(self).attempts.append(validation_attempt)
                if validation_attempt < 2:
                    raise ModelStructureError('synthetic protected-token mismatch')
                return {units[0].unit_id: {'0': '完整译文。'}}

        RepairClient.attempts = []
        client = RepairClient(retries=2)
        unit = TranslationUnit(
            'u1', 'text', 0, 1, 'source', [Segment('0', 'Complete source.')])
        client.translate_units([unit], {})
        self.assertEqual(RepairClient.attempts, [0, 1, 2])
        self.assertEqual(client.validation_retries_used, 2)
        self.assertEqual(unit.translations['0'], '完整译文。')

    def test_persistent_placeholder_loss_uses_local_anchor_reinsertion(self):
        class AnchorClient(AcademicTranslationClient):
            fallback_kept_protected_value_local = False

            def _translate_batch(self, units, options, validation_attempt=0,
                                 fragment_mode=False):
                unit = units[0]
                if getattr(unit, 'part_name', '') != 'protected-anchor-fallback':
                    raise ModelStructureError('synthetic first-placeholder loss')
                if not fragment_mode:
                    raise AssertionError('protected prose fallback must hide KEEP protocol')
                visible = ''.join(segment.core_text for segment in unit.segments)
                self.assertNotIn('12.5%', visible)
                self.assertNotIn('[[KEEP_', visible)
                type(self).fallback_kept_protected_value_local = True
                return {unit.unit_id: {
                    segment.segment_id: '译' + segment.core_text
                    for segment in unit.segments if not segment.locked
                }}

            @staticmethod
            def assertNotIn(member, container):
                if member in container:
                    raise AssertionError(f'{member!r} unexpectedly exposed')

            @staticmethod
            def assertIn(member, container):
                if member not in container:
                    raise AssertionError(f'{member!r} missing')

        AnchorClient.fallback_kept_protected_value_local = False
        client = AnchorClient(retries=2)
        unit = PdfUnit(
            'u1', 0, [PdfSegment('0', 'The estimate was 12.5%.')])
        client.translate_units([unit], {})
        self.assertTrue(AnchorClient.fallback_kept_protected_value_local)
        self.assertEqual(unit.translations['0'].count('12.5%'), 1)
        self.assertTrue(unit.translations['0'].endswith('.'))
        self.assertEqual(client.protected_anchor_fallbacks_used, 1)


class PdfExtractionBoundaryTests(unittest.TestCase):
    @staticmethod
    def _line(text, size, *, locked=None, bold=False):
        return PdfLine(
            text=text, rect=(45.0, 60.0, 285.0, 72.0), font_size=size,
            bold=bold, italic=False, color=0, horizontal=True,
            locked_reason=locked,
        )

    def test_soft_hyphenated_visual_lines_are_rejoined_before_translation(self):
        joined = _join_pdf_lines([
            self._line('workplace char\xad', 10),
            self._line('acteristics remain robust.', 10),
        ])
        self.assertEqual(joined, 'workplace characteristics remain robust.')

    def test_document_body_font_overrides_table_dominated_page_median(self):
        opening_pages = [[
            self._line('Main article prose ' * 4, 10) for _ in range(8)
        ]]
        document_size = _infer_document_body_size(opening_pages)
        table_heavy_page = (
            [self._line('coefficient value', 8) for _ in range(30)]
            + [self._line('Continuing main article prose across the page.', 10)
               for _ in range(4)]
        )
        self.assertAlmostEqual(document_size, 10)
        self.assertAlmostEqual(
            _effective_page_body_size(table_heavy_page, 8, document_size), 10)

    def test_indented_short_line_continues_preceding_wide_metadata(self):
        lines = [
            PdfLine(
                text='Funding at the University of',
                rect=(190.4, 443.9, 541.0, 452.0), font_size=7.97,
                bold=False, italic=False, color=0, horizontal=True,
            ),
            PdfLine(
                text='Pennsylvania.',
                rect=(198.9, 454.0, 248.8, 462.0), font_size=7.97,
                bold=False, italic=False, color=0, horizontal=True,
            ),
        ]
        _assign_columns(lines, 612.0)
        self.assertEqual([line.column for line in lines], ['wide', 'wide'])

    def test_single_column_short_final_line_inherits_wide_body(self):
        lines = [
            self._line('Full-width single-column body continues here', 10),
            self._line('short final line.', 10),
        ]
        lines[0].rect = (90.0, 100.0, 525.0, 112.0)
        lines[1].rect = (90.0, 112.5, 250.0, 124.5)
        _assign_columns(lines, 612.0)
        self.assertEqual([line.column for line in lines], ['wide', 'wide'])

    def test_noncontinuation_resets_wide_inheritance(self):
        lines = [
            self._line('Wide title first line', 10),
            self._line('indented title continuation', 10),
            self._line('Applicant: A Person', 10),
        ]
        lines[0].rect = (90.0, 80.0, 525.0, 92.0)
        lines[1].rect = (160.0, 93.0, 290.0, 105.0)
        lines[2].rect = (90.0, 107.0, 250.0, 119.0)
        _assign_columns(lines, 612.0)
        self.assertEqual(
            [line.column for line in lines], ['wide', 'left', 'left'])

    def test_explicit_reference_and_bold_short_headings_do_not_merge_with_body(self):
        self.assertTrue(_is_heading('References', 10, 10))
        self.assertTrue(_is_heading('Acknowledgments', 10, 10, bold=True))
        self.assertFalse(_is_heading(
            '¹ For example, a footnote continues', 8, 10, bold=True))
        self.assertFalse(_is_heading(
            '19 We thank a colleague for this suggestion.', 8, 10))
        self.assertFalse(_is_heading('A complete body sentence.', 10, 10))

    def test_superscript_footnote_digits_use_searchable_html_text(self):
        region = PdfRegion(
            unit_id='u', page_index=0, rect=(0, 0, 100, 20),
            line_rects=[(0, 0, 100, 20)], font_size=10,
            bold=False, italic=False, heading=False,
        )
        markup, css = _region_html('证据¹⁰', region)
        self.assertIn('<sup>10</sup>', markup)
        self.assertNotIn('⁰', markup)
        self.assertIn('vertical-align:super', css)


class DocxStructureTests(unittest.TestCase):
    def test_chinese_run_boundaries_drop_only_cjk_to_cjk_spaces(self):
        from services.paper_translation_service import Segment, TranslationUnit
        unit = TranslationUnit(
            'u', 'word/document.xml', 0, 1, '',
            [Segment('0', 'A ', trailing=' '), Segment('1', ' B', leading=' '),
             Segment('2', ' (Smith, 2024)', leading=' ')],
            translations={'0': '算法管理', '1': '提升协调', '2': '(Smith, 2024)'},
        )
        normalize_cjk_run_boundaries([unit])
        self.assertEqual(unit.segments[0].trailing, '')
        self.assertEqual(unit.segments[1].leading, '')
        self.assertEqual(unit.segments[2].leading, ' ')

    def test_docx_members_media_styles_tables_and_references_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / 'paper.docx'
            output = Path(temp_dir) / 'paper_zh.docx'
            make_docx(source)
            parts, units, audit = extract_docx_units(source, preserve_references=True)
            self.assertEqual(audit['skipped']['reference_paragraphs'], 1)
            self.assertEqual(audit['skipped']['formula_paragraphs'], 1)
            unit_text = [''.join(segment.text for segment in unit.segments) for unit in units]
            self.assertFalse(any('Smith, A. (2024)' in text for text in unit_text))
            self.assertFalse(any('Formula explanation' in text for text in unit_text))
            FakeClient().translate_units(units, {})
            integrity = write_translated_docx(source, output, parts, units, audit)

            self.assertTrue(integrity['package_members_unchanged'])
            self.assertTrue(integrity['media_hashes_unchanged'])
            self.assertTrue(integrity['ooxml_structure_unchanged'])
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(output) as translated:
                self.assertEqual(original.namelist(), translated.namelist())
                self.assertEqual(original.read('word/media/image1.png'), translated.read('word/media/image1.png'))
                xml = translated.read('word/document.xml').decode('utf-8')
            self.assertIn('<w:b/>', xml)
            self.assertEqual(xml.count('<w:tbl'), DOCUMENT_XML.count('<w:tbl'))
            self.assertIn('译文-', xml)
            self.assertIn('Smith, A. (2024). An article title.', xml)
            self.assertIn('Formula explanation', xml)


class PaperQuestionClientTests(unittest.TestCase):
    def test_answer_requires_known_original_evidence_id(self):
        class ScriptedClient(AcademicTranslationClient):
            def __init__(self):
                super().__init__(retries=0)

            def _chat(self, system, user, max_tokens, response_json=True):
                return json.dumps({
                    'answer': 'The paper reports an association [E9999].',
                    'evidence_ids': ['E9999'],
                    'confidence': 'high',
                    'not_found': False,
                })

        with self.assertRaisesRegex(ModelStructureError, '未知的原文证据'):
            ScriptedClient().answer_question(
                [{'evidence_id': 'E0001', 'locator': '第 1 页',
                  'title': 'Results', 'text': 'Association only.'}],
                'Is the effect causal?', [], {'target_language': 'English'})

    def test_not_found_answer_may_return_no_citations(self):
        class ScriptedClient(AcademicTranslationClient):
            def __init__(self):
                super().__init__(retries=0)

            def _chat(self, system, user, max_tokens, response_json=True):
                return json.dumps({
                    'answer': 'The supplied evidence does not report researcher ages.',
                    'evidence_ids': [],
                    'confidence': 'low',
                    'not_found': True,
                })

        result = ScriptedClient().answer_question(
            [{'evidence_id': 'E0001', 'locator': 'Methods',
              'title': 'Methods', 'text': 'The sample includes interviews.'}],
            'How old were the researchers?', [], {'target_language': 'English'})
        self.assertTrue(result['not_found'])
        self.assertEqual(result['evidence_ids'], [])


class TranslationJobTests(unittest.TestCase):
    def test_text_job_is_isolated_audited_and_preserves_line_endings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(temp_dir, client_factory=FakeClient)
            source = b'First line\r\n\r\nSecond line\n'
            job = manager.create_job('notes.txt', source, {
                'source_language': 'English', 'target_language': 'Simplified Chinese',
            }, start=False)
            manager.run_job_sync(job['job_id'])
            result = manager.get_job(job['job_id'])
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['input_sha256'], job['input_sha256'])
            self.assertEqual(result['audit']['translated_units'], 2)
            output_path, output_name = manager.output_path(job['job_id'])
            self.assertEqual(output_name, 'notes_zh.txt')
            translated = output_path.read_bytes()
            self.assertEqual(translated.count(b'\r\n'), 2)
            self.assertEqual(translated.count(b'\n'), 3)
            manifest = json.loads((Path(temp_dir) / job['job_id'] / 'manifest.json').read_text(encoding='utf-8'))
            self.assertNotIn('input_path', manifest)
            self.assertTrue((Path(temp_dir) / job['job_id'] / 'translations.jsonl').exists())

    def test_text_layer_pdf_is_translated_with_page_geometry_and_images_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(temp_dir, client_factory=FakeClient)
            source = Path(temp_dir) / 'source-fixture.pdf'
            make_pdf(source)
            job = manager.create_job('paper.pdf', source.read_bytes(), {
                'source_language': 'English', 'target_language': 'Simplified Chinese',
            }, start=False)
            manager.run_job_sync(job['job_id'])
            result = manager.get_job(job['job_id'])
            self.assertEqual(result['status'], 'completed', result.get('error'))
            self.assertEqual(result['audit']['input_type'], 'pdf')
            self.assertTrue(result['audit']['page_sizes_unchanged'])
            self.assertTrue(result['audit']['image_counts_unchanged'])
            self.assertGreaterEqual(result['audit']['tables_preserved_original'], 1)
            self.assertTrue(result['warnings'])
            output_path, output_name = manager.output_path(job['job_id'])
            self.assertEqual(output_name, 'paper_zh.pdf')
            import pymupdf
            with pymupdf.open(output_path) as translated:
                self.assertEqual(translated.page_count, 1)
                text = translated[0].get_text()
            self.assertIn('译文', text)
            self.assertIn('SYNTHETIC JOURNAL HEADER', text)
            self.assertNotIn('译文-SYNTHETIC JOURNAL HEADER', text)
            self.assertIn('Smith, A. (2024). A reference that must remain unchanged.', text)

    def test_scanned_pdf_fails_explicitly_without_local_ocr_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(temp_dir, client_factory=FakeClient)
            source = Path(temp_dir) / 'scan.pdf'
            make_pdf(source, scanned=True)
            job = manager.create_job('scan.pdf', source.read_bytes(), {}, start=False)
            manager.run_job_sync(job['job_id'])
            result = manager.get_job(job['job_id'])
            self.assertEqual(result['status'], 'failed')
            self.assertIn('扫描型 PDF', result['error'])

    def test_completed_job_supports_grounded_multi_turn_questions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(temp_dir, client_factory=FakeClient)
            source = (
                '# Introduction\n\nThe study examines digital coordination.\n\n'
                '# Methods\n\nThe sample contains 84 longitudinal interviews.\n\n'
                '# Results\n\nThe evidence supports an association, not a causal effect.\n'
            ).encode('utf-8')
            job = manager.create_job(
                'paper.md', source, {'mode': 'translate'}, start=False)
            manager.run_job_sync(job['job_id'])

            first = manager.ask_question(job['job_id'], '样本有多少访谈？')
            second = manager.ask_question(job['job_id'], '这个结果能说明因果关系吗？')
            history = manager.question_history(job['job_id'])
            job_dir = Path(temp_dir) / job['job_id']

            self.assertEqual(len(history['turns']), 2)
            self.assertEqual(first['input_sha256'], job['input_sha256'])
            self.assertTrue(first['citations'])
            self.assertIn('Methods', first['citations'][0]['locator'])
            self.assertTrue(second['citations'])
            self.assertIn('Results', second['citations'][0]['locator'])
            self.assertTrue((job_dir / 'question_evidence.json').is_file())
            self.assertEqual(
                len((job_dir / 'questions.jsonl').read_text(
                    encoding='utf-8').splitlines()), 2)
            self.assertEqual(history['grounding'], 'original_document_only')

    def test_question_refuses_changed_source_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = PaperTranslationManager(temp_dir, client_factory=FakeClient)
            job = manager.create_job(
                'paper.md', b'# Results\n\nOriginal evidence.', {},
                start=False)
            manager.run_job_sync(job['job_id'])
            source_path = Path(temp_dir) / job['job_id'] / 'source.md'
            source_path.write_text('# Results\n\nChanged evidence.', encoding='utf-8')
            with self.assertRaisesRegex(TranslationError, '原文件校验失败'):
                manager.ask_question(job['job_id'], '结果是什么？')


if __name__ == '__main__':
    unittest.main()
