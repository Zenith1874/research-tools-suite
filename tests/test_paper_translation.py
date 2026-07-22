# -*- coding: utf-8 -*-
"""Privacy, structure, and checkpoint guards for paper translation."""
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

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
            def _translate_batch(self, units, options):
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


if __name__ == '__main__':
    unittest.main()
