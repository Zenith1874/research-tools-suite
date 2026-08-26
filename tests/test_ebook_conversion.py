# -*- coding: utf-8 -*-
"""Layout, fidelity, privacy, and delivery guards for PDF reading copies."""
import json
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from services.ebook_conversion_service import (
    DEVICE_PROFILES,
    EbookConversionError,
    EbookConversionManager,
    convert_pdf,
    email_configuration,
    normalize_options,
    scan_folder,
)
from services.pdf_translation_service import extract_reading_layout


BODY = (
    'Algorithmic management reshapes how frontline workers experience autonomy '
    'and accountability at work. Prior studies emphasise surveillance, yet the '
    'mechanism through which platform ratings translate into felt control '
    'remains underspecified. We draw on job demands-resources theory to argue '
    'that rating opacity, rather than rating frequency, drives strain. Using a '
    'two-wave panel of couriers, we test a moderated mediation model. Results '
    'indicate a positive indirect effect of opacity on turnover intention. '
)


def make_two_column_pdf(path: Path, pages: int = 3):
    """A journal-shaped PDF: running head, wide masthead, two columns, a table."""
    import pymupdf
    document = pymupdf.open()
    for index in range(pages):
        page = document.new_page(width=595, height=792)
        page.insert_text((50, 34), 'Journal of Synthetic Organisation Studies', fontsize=7.5)
        page.insert_text((50, 770), 'Received 3 Jan 2026', fontsize=7)
        top = 92
        if index == 0:
            page.insert_textbox(
                pymupdf.Rect(50, 60, 545, 110),
                'Rating Opacity and the Felt Control of Algorithmic Management',
                fontsize=17)
            page.insert_textbox(pymupdf.Rect(50, 115, 545, 135),
                                'Wei Cui   Zixing Shen', fontsize=10)
            page.insert_text((50, 158), 'ABSTRACT', fontsize=9.5)
            page.insert_textbox(pymupdf.Rect(50, 165, 545, 245), BODY, fontsize=8.5)
            top = 265
        page.insert_text((50, top), f'{index + 1} | THEORY AND HYPOTHESES', fontsize=11)
        page.insert_text((307, top), 'Measurement', fontsize=10)
        for left in (50, 307):
            box = pymupdf.Rect(left, top + 18, left + 238, 700)
            repeats = 3
            while repeats and page.insert_textbox(box, BODY * repeats, fontsize=9) < 0:
                repeats -= 1
            assert repeats, 'fixture column text must fit'
        if index == 1:
            page.draw_rect(pymupdf.Rect(307, 300, 545, 400), width=.8)
            page.draw_line((307, 330), (545, 330), width=.8)
            page.insert_text((315, 320), 'Table 1. Descriptives', fontsize=8)
            page.insert_text((440, 320), 'Mean', fontsize=8)
    document.save(path)
    document.close()


def make_scanned_pdf(path: Path, pages: int = 2):
    import pymupdf
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page(width=595, height=792)
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 600, 800), False)
        pixmap.clear_with(240)
        page.insert_image(page.rect, pixmap=pixmap)
    document.save(path)
    document.close()


class ReadingLayoutTests(unittest.TestCase):
    """The reading layout must keep what translation deliberately drops."""

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp())
        cls.pdf = cls.directory / 'paper.pdf'
        make_two_column_pdf(cls.pdf, pages=3)
        cls.layout = extract_reading_layout(cls.pdf)

    def test_title_comes_from_the_masthead_not_a_later_heading(self):
        self.assertEqual(
            self.layout.title,
            'Rating Opacity and the Felt Control of Algorithmic Management')

    def test_running_head_and_footer_are_cropped_out(self):
        text = ' '.join(block.text for block in self.layout.blocks)
        self.assertNotIn('Journal of Synthetic Organisation Studies', text)
        self.assertNotIn('Received 3 Jan 2026', text)

    def test_reading_order_follows_wide_then_left_then_right(self):
        first_page = [block for block in self.layout.blocks if block.page_index == 0]
        columns = [block.column for block in first_page]
        self.assertEqual(columns, sorted(columns, key=['wide', 'left', 'right'].index))

    def test_tables_become_artwork_instead_of_scrambled_text(self):
        figures = [block for block in self.layout.blocks if block.kind == 'figure']
        self.assertTrue(figures, 'the ruled table must be detected as artwork')
        text = ' '.join(block.text for block in self.layout.blocks)
        self.assertNotIn('Table 1. Descriptives', text)

    def test_headings_are_detected_for_navigation(self):
        headings = [block.text for block in self.layout.blocks if block.kind == 'heading']
        self.assertIn('ABSTRACT', headings)
        self.assertTrue(any('THEORY AND HYPOTHESES' in text for text in headings))

    def test_mixed_first_page_columns_never_overlap_the_wide_band(self):
        geometry = self.layout.pages[0]
        self.assertTrue(geometry.two_column)
        self.assertGreaterEqual(len(geometry.column_rects), 3)
        wide, left, right = geometry.column_rects[:3]
        # A left crop that reached up into the abstract would show the same
        # prose twice: once in the wide panel and again in the column panel.
        self.assertGreaterEqual(left[1], wide[3] - 1)
        self.assertGreaterEqual(right[1], wide[3] - 1)

    def test_body_columns_are_split_on_ordinary_pages(self):
        geometry = self.layout.pages[1]
        self.assertTrue(geometry.two_column)
        self.assertEqual(len(geometry.column_rects), 2)
        left, right = geometry.column_rects
        self.assertLess(left[2], right[0], 'column crops must not overlap')

    def test_scanned_pdf_is_rejected_for_reflow_but_kept_for_geometry(self):
        scanned = self.directory / 'scanned.pdf'
        make_scanned_pdf(scanned)
        with self.assertRaises(Exception) as caught:
            extract_reading_layout(scanned)
        self.assertIn('扫描', str(caught.exception))
        layout = extract_reading_layout(scanned, allow_scanned=True)
        self.assertEqual(len(layout.pages), 2)


class ConversionOutputTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp())
        cls.pdf = cls.directory / 'paper.pdf'
        make_two_column_pdf(cls.pdf, pages=3)
        cls.output = cls.directory / 'out'
        cls.output.mkdir()
        cls.result = convert_pdf(cls.pdf, cls.output,
                                 {'formats': ['epub', 'device_pdf']})

    def _epub(self):
        return zipfile.ZipFile(self.output / 'paper.epub')

    def test_both_formats_are_produced(self):
        statuses = {entry['format']: entry['status'] for entry in self.result['outputs']}
        self.assertEqual(statuses, {'epub': 'completed', 'device_pdf': 'completed'})

    def test_epub_container_is_structurally_valid(self):
        archive = self._epub()
        names = archive.namelist()
        self.assertEqual(names[0], 'mimetype')
        self.assertEqual(archive.getinfo('mimetype').compress_type, zipfile.ZIP_STORED)
        self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
        self.assertIn('META-INF/container.xml', names)
        for name in names:
            if name.endswith(('.xhtml', '.opf', '.xml')):
                ET.fromstring(archive.read(name))

    def test_every_manifest_entry_exists_and_every_file_is_declared(self):
        archive = self._epub()
        names = set(archive.namelist())
        namespace = {'o': 'http://www.idpf.org/2007/opf'}
        package = ET.fromstring(archive.read('OEBPS/content.opf'))
        declared = {item.get('href') for item in package.findall('.//o:item', namespace)}
        self.assertTrue(all('OEBPS/' + href in names for href in declared))
        present = {name[len('OEBPS/'):] for name in names if name.startswith('OEBPS/')}
        self.assertEqual(present - declared, {'content.opf'})
        identifiers = {item.get('id') for item in package.findall('.//o:item', namespace)}
        spine = [ref.get('idref') for ref in package.findall('.//o:itemref', namespace)]
        self.assertTrue(spine)
        self.assertTrue(set(spine) <= identifiers)

    def test_epub_keeps_source_page_numbers_for_citation(self):
        archive = self._epub()
        chapters = ''.join(
            archive.read(name).decode('utf-8')
            for name in archive.namelist() if name.startswith('OEBPS/text/'))
        self.assertIn('epub:type="pagebreak"', chapters)
        self.assertIn('id="pg1"', chapters)

    def test_epub_output_is_byte_reproducible(self):
        again = Path(tempfile.mkdtemp())
        repeat = convert_pdf(self.pdf, again, {'formats': ['epub']})
        first = next(entry for entry in self.result['outputs']
                     if entry['format'] == 'epub')
        self.assertEqual(repeat['outputs'][0]['sha256'], first['sha256'])

    def test_device_pdf_emits_more_screens_than_source_pages(self):
        entry = next(item for item in self.result['outputs']
                     if item['format'] == 'device_pdf')
        audit = entry['audit']
        self.assertGreater(audit['output_pages'], audit['source_pages'])
        self.assertGreater(audit['pages_with_columns_split'], 0)

    def test_device_pdf_pages_match_the_chosen_screen_aspect(self):
        import pymupdf
        for device in ('kindle_paperwhite', 'phone'):
            with tempfile.TemporaryDirectory() as directory:
                convert_pdf(self.pdf, Path(directory),
                            {'formats': ['device_pdf'], 'device': device})
                path = Path(directory) / f'paper.{device}.pdf'
                with pymupdf.open(path) as book:
                    width, height = DEVICE_PROFILES[device]['screen']
                    page = book[0]
                    self.assertAlmostEqual(page.rect.height / page.rect.width,
                                           height / width, places=2)

    def test_scanned_pdf_skips_epub_but_still_ships_a_device_pdf(self):
        scanned = self.directory / 'scanned.pdf'
        make_scanned_pdf(scanned)
        with tempfile.TemporaryDirectory() as directory:
            result = convert_pdf(scanned, Path(directory),
                                 {'formats': ['epub', 'device_pdf']})
            statuses = {entry['format']: entry['status'] for entry in result['outputs']}
            self.assertEqual(statuses['epub'], 'skipped')
            self.assertEqual(statuses['device_pdf'], 'completed')

    def test_scanned_pdf_with_only_epub_requested_fails_loudly(self):
        scanned = self.directory / 'scanned.pdf'
        make_scanned_pdf(scanned)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(EbookConversionError):
                convert_pdf(scanned, Path(directory), {'formats': ['epub']})


class OptionAndScanTests(unittest.TestCase):

    def test_unknown_options_fall_back_to_safe_defaults(self):
        options = normalize_options({'formats': ['docx'], 'device': 'nokia',
                                     'figure_dpi': 9000})
        self.assertEqual(options['formats'], ['epub', 'device_pdf'])
        self.assertEqual(options['device'], 'kindle_paperwhite')
        self.assertEqual(options['figure_dpi'], 300)

    def test_folder_scan_walks_subfolders_and_ignores_non_pdf(self):
        root = Path(tempfile.mkdtemp())
        (root / 'sub').mkdir()
        make_two_column_pdf(root / 'a.pdf', pages=1)
        make_two_column_pdf(root / 'sub' / 'b.pdf', pages=1)
        (root / 'notes.txt').write_text('not a pdf', encoding='utf-8')
        (root / '.hidden.pdf').write_text('skip me', encoding='utf-8')
        result = scan_folder(root)
        self.assertEqual(result['count'], 2)
        self.assertEqual(sorted(item['name'] for item in result['files']),
                         ['a.pdf', 'b.pdf'])

    def test_folder_scan_can_stay_shallow(self):
        root = Path(tempfile.mkdtemp())
        (root / 'sub').mkdir()
        make_two_column_pdf(root / 'a.pdf', pages=1)
        make_two_column_pdf(root / 'sub' / 'b.pdf', pages=1)
        self.assertEqual(scan_folder(root, recursive=False)['count'], 1)

    def test_missing_folder_is_reported_not_crashed(self):
        with self.assertRaises(EbookConversionError):
            scan_folder(str(Path(tempfile.mkdtemp()) / 'nope'))

    def test_email_configuration_never_returns_the_password(self):
        config = email_configuration({
            'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'me@example.com',
            'SMTP_PASS': 'super-secret', 'KINDLE_EMAIL': 'weicui@kindle.com'})
        self.assertTrue(config['configured'])
        self.assertNotIn('secret', json.dumps(
            {k: v for k, v in config.items() if k != 'password'}))
        self.assertEqual(config['default_recipient_masked'], 'we***@kindle.com')
        # A very short local part gives away almost the whole address, so it
        # is masked harder rather than consistently.
        short = email_configuration({'KINDLE_EMAIL': 'me@kindle.com'})
        self.assertEqual(short['default_recipient_masked'], 'm***@kindle.com')


class ManagerTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.sources = Path(tempfile.mkdtemp())
        self.pdf = self.sources / 'paper.pdf'
        make_two_column_pdf(self.pdf, pages=2)
        self.manager = EbookConversionManager(self.root / 'jobs',
                                              max_concurrent_jobs=1)

    def tearDown(self):
        self.manager.shutdown(wait=True)

    def _finish(self, job):
        self.manager.shutdown(wait=True)
        return self.manager.get_job(job['job_id'])

    def test_config_hides_credentials_from_the_page_payload(self):
        payload = json.dumps(self.manager.config(), ensure_ascii=False)
        self.assertNotIn('password', payload)
        self.assertIn('kindle_paperwhite', payload)

    def test_local_source_is_read_in_place_and_survives_job_deletion(self):
        job = self.manager.create_job(local_path=str(self.pdf))
        finished = self._finish(job)
        self.assertEqual(finished['status'], 'completed')
        self.assertEqual(finished['source_mode'], 'local_path')
        self.manager.delete_job(job['job_id'])
        self.assertTrue(self.pdf.is_file(), '本机原件绝不能被任务删除影响')

    def test_upload_source_is_stored_inside_the_private_job_folder(self):
        job = self.manager.create_job(
            filename='paper.pdf', content=self.pdf.read_bytes())
        finished = self._finish(job)
        self.assertEqual(finished['status'], 'completed')
        self.assertTrue((self.manager.root / job['job_id'] / 'input.pdf').is_file())

    def test_non_pdf_and_empty_uploads_are_refused(self):
        with self.assertRaises(EbookConversionError):
            self.manager.create_job(filename='notes.docx', content=b'x')
        with self.assertRaises(EbookConversionError):
            self.manager.create_job(filename='paper.pdf', content=b'')

    def test_missing_local_path_is_refused_before_a_job_folder_survives(self):
        with self.assertRaises(EbookConversionError):
            self.manager.create_job(local_path=str(self.sources / 'ghost.pdf'))
        self.assertEqual(list(self.manager.root.glob('*/manifest.json')), [])

    def test_batch_shares_one_identifier_for_delivery(self):
        second = self.sources / 'other.pdf'
        make_two_column_pdf(second, pages=1)
        batch = self.manager.create_batch(
            [{'path': str(self.pdf)}, {'path': str(second)}])
        self.manager.shutdown(wait=True)
        self.assertEqual(batch['created'], 2)
        jobs = [self.manager.get_job(job['job_id']) for job in batch['jobs']]
        self.assertEqual({job['batch_id'] for job in jobs}, {batch['batch_id']})

    def test_bundle_packs_every_completed_output(self):
        job = self.manager.create_job(local_path=str(self.pdf))
        finished = self._finish(job)
        bundle_path, download_name = self.manager.build_bundle(
            job_ids=[job['job_id']])
        self.assertTrue(download_name.endswith('.zip'))
        with zipfile.ZipFile(bundle_path) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                sorted(entry['filename'] for entry in finished['outputs']
                       if entry['status'] == 'completed'))

    def test_folder_delivery_never_overwrites_silently(self):
        job = self.manager.create_job(local_path=str(self.pdf))
        self._finish(job)
        target = Path(tempfile.mkdtemp())
        first = self.manager.deliver_to_folder(str(target), job_ids=[job['job_id']])
        self.assertGreater(first['written_count'], 0)
        self.assertEqual(first['skipped_count'], 0)
        second = self.manager.deliver_to_folder(str(target), job_ids=[job['job_id']])
        self.assertEqual(second['written_count'], 0)
        self.assertEqual(second['skipped_count'], first['written_count'])
        third = self.manager.deliver_to_folder(
            str(target), job_ids=[job['job_id']], overwrite=True)
        self.assertEqual(third['written_count'], first['written_count'])

    def test_folder_delivery_refuses_a_missing_target(self):
        job = self.manager.create_job(local_path=str(self.pdf))
        self._finish(job)
        with self.assertRaises(EbookConversionError):
            self.manager.deliver_to_folder(
                str(Path(tempfile.mkdtemp()) / 'nope'), job_ids=[job['job_id']])

    def test_kindle_send_validates_address_and_attaches_one_file_per_message(self):
        sent = []
        manager = EbookConversionManager(
            self.root / 'mail-jobs', max_concurrent_jobs=1,
            email_sender=lambda config, message: sent.append(message),
            env={'SMTP_HOST': 'smtp.example.com', 'SMTP_USER': 'me@example.com',
                 'SMTP_PASS': 'secret'})
        job = manager.create_job(local_path=str(self.pdf))
        manager.shutdown(wait=True)
        with self.assertRaises(EbookConversionError):
            manager.send_to_kindle('not-an-address', job_ids=[job['job_id']])
        result = manager.send_to_kindle('reader@kindle.com', job_ids=[job['job_id']])
        self.assertEqual(result['sent_count'], len(sent))
        self.assertEqual(result['recipient_masked'], 're***@kindle.com')
        for message in sent:
            attachments = list(message.iter_attachments())
            self.assertEqual(len(attachments), 1)

    def test_kindle_send_without_smtp_is_refused_before_reading_files(self):
        manager = EbookConversionManager(
            self.root / 'nomail-jobs', max_concurrent_jobs=1, env={})
        job = manager.create_job(local_path=str(self.pdf))
        manager.shutdown(wait=True)
        with self.assertRaises(EbookConversionError) as caught:
            manager.send_to_kindle('reader@kindle.com', job_ids=[job['job_id']])
        self.assertIn('SMTP', str(caught.exception))

    def test_job_identifiers_are_validated_before_touching_disk(self):
        for bad in ('../../etc', 'zz', '../' * 6):
            with self.assertRaises(EbookConversionError):
                self.manager.get_job(bad)
            with self.assertRaises(EbookConversionError):
                self.manager.delete_job(bad)


if __name__ == '__main__':
    unittest.main()
