"""Local original-response evidence and explicit date roles do not require a live site."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from services.nbs_release_evidence import (
    archive_nbs_release,nbs_release_dates,nbs_https_url,nbs_reported_month,MAX_BYTES,
)


class NbsEvidenceTests(unittest.TestCase):
    def capture(self,root,content=None,url='https://www.stats.gov.cn/source.html'):
        return archive_nbs_release(content or b'<meta name="PubDate" content="2026/10/14 09:30">',url,
                                   original_url=url,kind='ppi',period_hint='2026-09',title='fixture',
                                   parser_version='fixture',parser_sha256='a'*64,root=root)

    def test_each_capture_keeps_exact_bytes_and_an_immutable_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw='<meta name="PubDate" content="2026/10/14 09:30"><p>原文</p>'.encode('utf-8')
            first=self.capture(tmp,raw);second=self.capture(tmp,raw)
            self.assertNotEqual(first['_archive_dir'],second['_archive_dir'])
            for evidence in (first,second):
                directory=Path(evidence['_archive_dir']);receipt=json.loads((directory/'receipt.json').read_text(encoding='utf-8'))
                self.assertEqual((directory/receipt['raw_path']).read_bytes(),raw)
                self.assertEqual(receipt['raw_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(receipt['period_hint'],'2026-09')
                self.assertEqual(receipt['parser_code_sha256'],'a'*64)
                self.assertEqual(evidence['release_date'],'2026-10-14')

    def test_publication_creation_unknown_and_conflict_are_not_interchangeable(self):
        creation=nbs_release_dates(BeautifulSoup('成文日期2021年4月9日','html.parser'))
        self.assertIsNone(creation['release_date'])
        self.assertEqual(creation['source_page_created_date'],'2021-04-09')
        self.assertEqual(creation['release_date_not_provided'],1)
        unknown=nbs_release_dates(BeautifulSoup('2023年迁移的页面，没有解析到日期字段','html.parser'))
        self.assertIsNone(unknown['release_date']);self.assertEqual(unknown['release_date_not_provided'],0)
        self.assertIn('未解析',unknown['release_date_reason'])
        html='<meta name="PubDate" content="2026/10/14"><div class="detail-title-des">2026/10/15 09:30</div>'
        conflict=nbs_release_dates(BeautifulSoup(html,'html.parser'))
        self.assertIsNone(conflict['release_date']);self.assertIn('冲突',conflict['release_date_reason'])
        with self.assertRaises(ValueError):nbs_release_dates(BeautifulSoup(html,'html.parser'),True)

    def test_original_dated_nbs_heading_is_not_the_migrated_url_year(self):
        timing=nbs_release_dates(BeautifulSoup('（2012年4月13日）中华人民共和国国家统计局','html.parser'))
        self.assertEqual(timing['release_date'],'2012-04-13')

    def test_only_exact_public_nbs_paths_can_be_upgraded(self):
        self.assertEqual(nbs_https_url('http://www.stats.gov.cn/source.html'),'https://www.stats.gov.cn/source.html')
        for url in ('https://example.org/a.html','https://www.stats.gov.cn.evil/a',
                    'https://user:pass@www.stats.gov.cn/a','https://www.stats.gov.cn/a?token=x',
                    'https://www.stats.gov.cn:1234/a','file:///tmp/source'):
            with self.subTest(url=url),self.assertRaises(ValueError):nbs_https_url(url)
        with self.assertRaises(ValueError):nbs_https_url('https://www.stats.gov.cn/')

    def test_reported_table_month_is_explicit_and_not_the_url_or_annual_average(self):
        self.assertEqual(nbs_reported_month(BeautifulSoup('2016年12月工业生产者价格主要数据 2016年全年平均','html.parser'),'ppi'),'2016-12')
        self.assertIsNone(nbs_reported_month(BeautifulSoup('2023年页面迁移记录','html.parser'),'ppi'))
        with self.assertRaises(ValueError):
            nbs_reported_month(BeautifulSoup('2016年11月工业生产者价格主要数据 2016年12月工业生产者价格主要数据','html.parser'),'ppi')

    def test_downgrade_empty_or_oversized_response_does_not_publish_a_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):self.capture(tmp,b'x',url='http://www.stats.gov.cn/a.html')
            with patch('services.nbs_release_evidence.MAX_BYTES',1),self.assertRaises(ValueError):self.capture(tmp,b'xx')
            self.assertEqual(list(Path(tmp).glob('*/receipt.json')),[])

    def test_replay_is_labelled_and_retains_original_acquisition_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence=archive_nbs_release(b'<p>fixture</p>','https://www.stats.gov.cn/a.html',
                original_url='https://www.stats.gov.cn/a.html',kind='ppi',period_hint='2026-09',title='fixture',
                parser_version='fixture',parser_sha256='a'*64,root=tmp,access_mode='archived_response_replay',
                source_retrieved_at='2026-10-14T01:30:00+00:00',replay_parent_ref='original/receipt.json')
            record=json.loads((Path(evidence['_archive_dir'])/'receipt.json').read_text(encoding='utf-8'))
            self.assertEqual(record['access_mode'],'archived_response_replay')
            self.assertEqual(record['retrieved_at'],'2026-10-14T01:30:00+00:00')
            self.assertNotEqual(record['captured_at'],record['retrieved_at'])


if __name__=='__main__':
    unittest.main()
