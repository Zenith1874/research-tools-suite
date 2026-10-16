"""Publication links and actual contents boundaries must survive PDF geometry."""

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import fitz

from scripts.prepare_lexis_contents_metadata import parse_document, parse_byline, inline_byline, trailing_byline_title, split_title_block, publication_id


class LexisContentsTests(unittest.TestCase):
    def document(self, path, byline=True, guidelines=False):
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 75), 'Fixture Journal', fontsize=14)
        page.insert_text((72, 95), 'Volume 37 Part 2', fontsize=12)
        page.insert_text((72, 120), 'CONTENTS', fontsize=13)
        page.insert_text((72, 145), 'An Actual Title', fontsize=12)
        if byline:
            page.insert_text((72, 165), byline if isinstance(byline, str) else 'An Author', fontsize=12)
        page.insert_text((510, 165 if byline else 145), '99', fontsize=12)
        page.insert_text((72, 190), 'This is the supplied abstract.', fontsize=10.5)
        page.insert_link({'kind': fitz.LINK_URI, 'from': fitz.Rect(70, 130, 250, 150),
                         'uri': 'https://advance.lexis.com/api/document?idtype=DOC-ID&id=fixture-one'})
        if guidelines:
            page = pdf.new_page()
            page.insert_text((72, 75), 'Style Guidelines', fontsize=14)
            page.insert_text((72, 110), 'Send submissions to the editor.', fontsize=10.5)
        pdf.save(path);pdf.close()
        pages = []
        with fitz.open(path) as pdf:
            for page in pdf:
                lines = [{'text': ''.join(span['text'] for span in line['spans']), 'bbox': line['bbox'],
                    'sizes': [span['size'] for span in line['spans']], 'flags': [span['flags'] for span in line['spans']]}
                    for block in page.get_text('dict')['blocks'] if block.get('type') == 0 for line in block['lines']]
                pages.append({'page': page.number + 1, 'text': page.get_text(), 'lines': lines})
        return {'journal_title': 'Fixture Journal', 'pages': pages, 'pdf_path': str(path),
                'pdf_sha256': 'fixture', 'url': 'https://publisher.example/contents.pdf'}

    def test_guidelines_do_not_become_the_last_abstract(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self.document(Path(temporary) / 'contents.pdf', guidelines=True)
            row = parse_document(doc, {})[0]
            self.assertEqual('This is the supplied abstract.', row['abstract'])
            self.assertIsNone(row['publication_year'])
            self.assertIsNone(row['publication_date'])

    def test_page_number_on_the_title_baseline_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            doc = self.document(Path(temporary) / 'contents.pdf', byline=False)
            row = parse_document(doc, {})[0]
            self.assertEqual(99, row['printed_start_page'])
            self.assertEqual([], row['authors'])

    def test_tracking_parameters_do_not_change_a_content_item_identity(self):
        first = 'https://advance.lexis.com/document/?crid=one&pddocfullpath=%2Fshared%2Furn%3AcontentItem%3A6AAA-BBB1-00000-00'
        second = first.replace('crid=one', 'crid=two')
        self.assertEqual(publication_id(first), publication_id(second))

    def test_large_bold_blank_padding_cannot_truncate_the_abstract(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'contents.pdf'
            document = self.document(path)
            with fitz.open(path) as pdf:
                page = pdf[0]
                page.insert_text((72, 205), 'This last sentence must also remain.', fontsize=10.5)
                page.insert_text((250, 205), ' ', fontsize=16, fontname='hebo')
                data = pdf.tobytes()
            path.write_bytes(data)
            row = parse_document(document, {})[0]
            self.assertEqual('This is the supplied abstract. This last sentence must also remain.', row['abstract'])

    def test_postnominal_is_retained_without_a_fictitious_coauthor(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = self.document(Path(temporary) / 'contents.pdf', byline='Peter R A Gray, AM')
            row = parse_document(document, {})[0]
            self.assertEqual(['Peter R A Gray'], row['authors'])
            self.assertEqual('Peter R A Gray, AM', row['observed_author_text'])
            self.assertEqual({'Peter R A Gray': ['AM']}, row['author_postnominals'])

    def test_and_still_starts_a_person_and_initials_are_not_dropped(self):
        self.assertEqual((['Tess Hardy', 'Richard Johnstone', 'John Howe'], {}),
                         parse_byline('Tess Hardy, Richard Johnstone and John Howe'))
        self.assertEqual((['Another Author', 'AM'], {}), parse_byline('Another Author and AM'))
        self.assertEqual((['C N Jessup'], {}), parse_byline('C N Jessup'))

    def test_inline_italic_byline_is_separated_from_a_linked_title(self):
        spans = [{'text': 'An actual article title — ', 'flags': 0},
                 {'text': 'Elizabeth Handsley and Arlen Duke', 'flags': 2},
                 {'text': ' ', 'flags': 0}]
        self.assertEqual(('An actual article title', 'Elizabeth Handsley and Arlen Duke'), inline_byline(spans))

    def test_normal_subtitle_and_wholly_italic_title_are_not_authors(self):
        self.assertIsNone(inline_byline([{'text': 'An article — a normal subtitle', 'flags': 0}]))
        self.assertIsNone(inline_byline([{'text': 'An italic title — its italic subtitle', 'flags': 2}]))

    def test_an_italic_case_name_before_a_continuing_title_is_retained(self):
        lines = [{'text': 'Vicarious liability — Barclays Bank',
                  'inline_title': 'Vicarious liability', 'inline_author': 'Barclays Bank'},
                 {'text': 'plc v Various Claimants; Wm Morrison Supermarkets'}]
        self.assertEqual(('Vicarious liability — Barclays Bank plc v Various Claimants; Wm Morrison Supermarkets', []),
                         split_title_block(lines))

    def test_compact_dash_still_requires_an_italic_byline(self):
        spans = [{'text': 'present', 'flags': 0}, {'text': '— ', 'flags': 2},
                 {'text': 'Pradeep Krishan Tiwari and Gaurav Shukla', 'flags': 2}]
        self.assertEqual(('present', 'Pradeep Krishan Tiwari and Gaurav Shukla'), inline_byline(spans))
        self.assertIsNone(inline_byline([{'text': 'A title—its ordinary subtitle', 'flags': 0}]))

    def test_italic_byline_marker_is_not_part_of_the_title(self):
        self.assertEqual('Compulsory liability insurance for drones in Australia', trailing_byline_title([
            {'text': 'Compulsory liability insurance for drones in Australia', 'flags': 0},
            {'text': '—', 'flags': 2}, {'text': ' ', 'flags': 0}]))
        self.assertIsNone(trailing_byline_title([{'text': 'A meaningful regular dash —', 'flags': 0}]))
        self.assertIsNone(trailing_byline_title([{'text': 'An entirely italic title', 'flags': 2},
                                              {'text': '—', 'flags': 2}]))

    def test_unlinked_final_title_fragment_is_not_a_fictitious_author(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = self.document(Path(temporary) / 'contents.pdf')
            # Reproduce the actual URL rectangle covering only the first line.
            lines = [
                {'text': 'The evolution of insurance law in Fiji: The past and',
                 'bbox': [72, 132, 230, 145], 'sizes': [12], 'flags': [0], 'source_page': 1},
                {'text': 'present— Pradeep Krishan Tiwari and Gaurav Shukla',
                 'inline_title': 'present', 'inline_author': 'Pradeep Krishan Tiwari and Gaurav Shukla',
                 'bbox': [72, 156, 460, 170], 'sizes': [12], 'flags': [0, 2], 'source_page': 1},
                {'text': '33', 'bbox': [510, 156, 530, 170], 'sizes': [12], 'flags': [0], 'source_page': 1},
                {'text': 'The actual supplied abstract.', 'bbox': [72, 186, 460, 199],
                 'sizes': [10.5], 'flags': [0], 'source_page': 1}]
            with patch('scripts.prepare_lexis_contents_metadata.visible_line_pages',
                       return_value=[{'page': 1, 'lines': lines}]):
                row = parse_document(document, {})[0]
            self.assertEqual('The evolution of insurance law in Fiji: The past and present', row['title'])
            self.assertEqual(['Pradeep Krishan Tiwari', 'Gaurav Shukla'], row['authors'])
            self.assertEqual('The actual supplied abstract.', row['abstract'])
            self.assertEqual(33, row['printed_start_page'])

    def test_distant_unlinked_heading_is_not_added_to_the_title(self):
        with tempfile.TemporaryDirectory() as temporary:
            document = self.document(Path(temporary) / 'contents.pdf')
            lines = [
                {'text': 'Original linked title', 'bbox': [72, 132, 230, 145],
                 'sizes': [12], 'flags': [0], 'source_page': 1},
                {'text': 'A different unlinked title— Another Author', 'inline_title': 'A different unlinked title',
                 'inline_author': 'Another Author', 'bbox': [72, 245, 460, 259],
                 'sizes': [12], 'flags': [0, 2], 'source_page': 1}]
            with patch('scripts.prepare_lexis_contents_metadata.visible_line_pages',
                       return_value=[{'page': 1, 'lines': lines}]):
                row = parse_document(document, {})[0]
            self.assertEqual('Original linked title', row['title'])
