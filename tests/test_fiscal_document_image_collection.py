"""Archive public official raster originals, never accept HTML as a chart image."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

from scripts.collect_official_fiscal_documents import main


class FiscalDocumentImageCollectionTests(unittest.TestCase):
    def run_collection(self,body):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'sources.json'
            url='https://fixture.gov.cn/figure.png'
            config.write_text(json.dumps({'schema_version':1,'documents':[{
                'id':'official-image','format':'png','source_url':url,'source_title':'Public official chart'}]}),encoding='utf8')
            response=MagicMock();response.url=url;response.iter_content.return_value=[body]
            session=MagicMock();session.get.return_value=response
            with patch('scripts.collect_official_fiscal_documents.requests.Session',return_value=session), \
                    patch('sys.argv',['collector','--sources',str(config),'--output-dir',str(root/'runs')]), \
                    contextlib.redirect_stdout(io.StringIO()):
                main()
            output=next((root/'runs').iterdir());audit=json.loads((output/'audit.json').read_text(encoding='utf8'))
            raw=output/'official-image.png'
            self.assertNotIn('verify',session.get.call_args.kwargs)
            response.close.assert_called_once()
            return audit,raw.read_bytes() if raw.is_file() else None

    def test_png_original_is_archived_with_hash_and_normal_tls(self):
        body=b'\x89PNG\r\n\x1a\nraw-public-image-fixture'
        audit,raw=self.run_collection(body)
        self.assertEqual(raw,body);self.assertFalse(audit['errors'])
        self.assertTrue(audit['source_manifest'][0]['tls_verified'])
        self.assertEqual(audit['source_manifest'][0]['format'],'png')

    def test_verification_html_is_not_written_as_a_png_original(self):
        audit,raw=self.run_collection(b'<html>Access denied</html>')
        self.assertIsNone(raw);self.assertFalse(audit['source_manifest']);self.assertTrue(audit['errors'])


if __name__=='__main__':unittest.main()
