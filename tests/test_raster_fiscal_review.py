import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.review_province_fiscal_sources import verify_reviewed_raster_page


class RasterFiscalReviewTests(unittest.TestCase):
    def sample(self,directory):
        data=b'reviewed-page-bytes'
        (directory/'page.png').write_bytes(data)
        source={'region_name':'广东','statistical_year':'2025','profile':'guangdong_2025_fiscal_raster',
                'render_path':'page.png','render_sha256':hashlib.sha256(data).hexdigest(),
                'pdf_pages':29,'evidence_page':17,'render_scale':1.6}
        pdf=MagicMock();pdf.__len__.return_value=29
        pdf.__getitem__.return_value.get_text.return_value=''
        pdf.__getitem__.return_value.get_pixmap.return_value.tobytes.return_value=data
        context=MagicMock();context.__enter__.return_value=pdf
        return source,context,pdf

    def test_original_page_render_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,context,pdf=self.sample(Path(tmp))
            with patch('scripts.review_province_fiscal_sources.fitz.open',return_value=context):
                verify_reviewed_raster_page(b'%PDF-fixture',source,Path(tmp))
            pdf.__getitem__.assert_called_once_with(16)

    def test_wrong_profile_tampered_or_escaped_render_reject(self):
        for mutation in ('profile','hash','escape','not_pdf'):
            with tempfile.TemporaryDirectory() as tmp:
                source,context,pdf=self.sample(Path(tmp));content=b'%PDF-fixture'
                if mutation=='profile':source['region_name']='安徽'
                elif mutation=='hash':source['render_sha256']='0'*64
                elif mutation=='escape':source['render_path']='../outside.png'
                else:content=b'not a pdf'
                with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                    verify_reviewed_raster_page(content,source,Path(tmp))

    def test_page_count_text_mode_and_different_original_page_reject(self):
        for mutation in ('count','text','reproduction'):
            with tempfile.TemporaryDirectory() as tmp:
                source,context,pdf=self.sample(Path(tmp))
                if mutation=='count':pdf.__len__.return_value=28
                elif mutation=='text':pdf.__getitem__.return_value.get_text.return_value='real text'
                else:pdf.__getitem__.return_value.get_pixmap.return_value.tobytes.return_value=b'other page'
                with self.subTest(mutation=mutation),patch('scripts.review_province_fiscal_sources.fitz.open',return_value=context),self.assertRaises(ValueError):
                    verify_reviewed_raster_page(b'%PDF-fixture',source,Path(tmp))


if __name__=='__main__':
    unittest.main()
