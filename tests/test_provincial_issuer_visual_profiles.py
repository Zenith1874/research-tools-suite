"""Guard reviewed image-only fiscal originals, scopes, units and source vintages."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import fitz
from pypdf import PdfReader

from services.provincial_issuer_visual_profiles import parse_provincial_issuer_visual_pages
from services.fiscal_source_authority import reviewed_issuer_fiscal_source, official_fiscal_download_url
from scripts.review_province_fiscal_supplement import verified_visual_pages, visual_transcript_digest


ROOT=Path(__file__).resolve().parents[1]
REVIEW=json.loads((ROOT/'data/province_fiscal_visual_review_20261015.json').read_text(encoding='utf-8'))


class ProvincialIssuerVisualTests(unittest.TestCase):
    def source(self,province):
        return copy.deepcopy(next(d for d in REVIEW['documents'] if d['region_name']==province))

    def parse(self,source,period='2025'):
        pages={int(n):p['text'] for n,p in source['visual_transcript_pages'].items()}
        return parse_provincial_issuer_visual_pages(pages,source['region_name'],period,source['profile'])

    def test_latest_whole_region_values_not_own_budget_limits_or_old_vintages(self):
        expected={
            '广西':{'general_budget_revenue':1922.05,'general_budget_expenditure':6742.18,'gov_fund_revenue':597.25,'gov_fund_expenditure':1779.58,'debt_outstanding':14752.58,'general_debt_outstanding':5841.35,'special_debt_outstanding':8911.24},
            '安徽':{'general_budget_revenue':4157.37,'general_budget_expenditure':9117.04,'gov_fund_revenue':1629.14,'gov_fund_expenditure':3999.34,'land_transfer_revenue':1306.13,'debt_outstanding':21400.4,'general_debt_outstanding':4953.63,'special_debt_outstanding':16446.77},
            '重庆':{'general_budget_revenue':2736,'general_budget_expenditure':5691,'gov_fund_revenue':1593,'gov_fund_expenditure':3032,'land_transfer_revenue':1369,'debt_outstanding':16782},
            '贵州':{'general_budget_revenue':2223.3,'general_budget_expenditure':6555.97,'gov_fund_revenue':2575.69,'gov_fund_expenditure':3253.43,'debt_outstanding':19368.66,'general_debt_outstanding':8827.22,'special_debt_outstanding':10541.44}}
        for name,values in expected.items():
            rows=self.parse(self.source(name))
            self.assertEqual({r['indicator_code']:r['value'] for r in rows},values)
            self.assertTrue(all(r['unit']=='亿元' and r['parse_mode']=='reviewed_visual_transcript' and r['government_scope']=='province_total' for r in rows))
            self.assertNotIn('tax_revenue',values)
            self.assertNotIn('principal_repayment',values)

    def test_historical_and_current_status_follows_explicit_source_note(self):
        for name,status in [('广西','official'),('安徽','official_final'),('重庆','official_final'),('贵州','official_preliminary')]:
            rows=self.parse(self.source(name));fiscal=[r for r in rows if 'debt_outstanding' not in r['indicator_code']]
            self.assertTrue(all(r['data_status']==status for r in fiscal))
            self.assertTrue(all(r['data_status']=='official' for r in rows if 'debt_outstanding' in r['indicator_code']))
        self.assertEqual({r['data_status'] for r in self.parse(self.source('贵州'),'2023')},{'official_final'})
        self.assertEqual(next(r['value'] for r in self.parse(self.source('广西'),'2024') if r['indicator_code']=='debt_outstanding'),13150.39)

    def test_missing_fields_are_not_synthesized(self):
        for name in ('广西','贵州'):
            codes={r['indicator_code'] for r in self.parse(self.source(name))}
            self.assertNotIn('land_transfer_revenue',codes);self.assertNotIn('interest_expenditure',codes)
        self.assertNotIn('general_debt_outstanding',{r['indicator_code'] for r in self.parse(self.source('重庆'))})

    def test_unit_scope_vintage_signature_and_component_mutations_fail_closed(self):
        cases=[('广西',6,'财政收支状况（亿元）','财政收支状况（万元）'),
               ('广西',6,'自治区本级 全区','全区 自治区本级'),
               ('安徽',6,'数据均为决算数','数据均为预算数'),
               ('重庆',8,'数据为决算数','数据为执行数'),
               ('贵州',12,'2025年预算执行情况','2025年预算计划'),
               ('广西',7,'全区政府债务余额为14752.58','全区政府债务余额为24752.58'),
               ('安徽',9,'2026年9月7日','2025年9月7日'),
               ('安徽',6,'1306.13','2306.13')]
        for name,n,old,new in cases:
            source=self.source(name);source['visual_transcript_pages'][str(n)]['text']=source['visual_transcript_pages'][str(n)]['text'].replace(old,new)
            with self.subTest(name=name,new=new),self.assertRaises(ValueError):self.parse(source)

    def test_page_and_year_identity_are_not_inferred(self):
        source=self.source('安徽');pages={int(n):p['text'] for n,p in source['visual_transcript_pages'].items()}
        for province,period,p in [('安徽','2022',pages),('福建','2025',pages),('安徽','2025',{**pages,2:'extra'}),('安徽','2025',{n:t for n,t in pages.items() if n!=1})]:
            with self.assertRaises(ValueError):parse_provincial_issuer_visual_pages(p,province,period,source['profile'])

    def test_approved_source_binds_publisher_bytes_transcript_page_and_status(self):
        for source in REVIEW['documents']:
            for row in self.parse(source):
                if row['indicator_code']=='special_debt_outstanding':continue
                row.update(source_name=source['source_name'],source_title=source['source_title'],
                           source_url=source['source_url']+'#page='+str(row['evidence_page']),
                           parser_notes='access_type='+source['source_class']+'; raw_sha256='+source['raw_sha256']+'; visual_transcript_sha256='+source['transcript_sha256']+'; parse_mode=reviewed_visual_transcript; unit_evidence=explicit_source_heading')
                self.assertTrue(reviewed_issuer_fiscal_source(row))
                for field,value in [('parser_notes','not-reviewed'),('source_name','评级机构'),('source_url',source['source_url']+'#page=2')]:
                    self.assertFalse(reviewed_issuer_fiscal_source({**row,field:value}))
        self.assertFalse(official_fiscal_download_url('https://example.org/unreviewed.pdf',None))
        self.assertFalse(official_fiscal_download_url('https://static.sse.com.cn/unreviewed.pdf',None))

    def test_raster_binding_reproduces_each_page_and_rejects_transcript_or_render_changes(self):
        source=self.source('广西')
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            with fitz.open() as document:
                for i in range(9):
                    page=document.new_page(width=120,height=160)
                    page.draw_rect(fitz.Rect(5+i,5,80,130),fill=(i/10,.3,.7))
                content=document.tobytes()
                for n in source['reviewed_pages']:
                    proof=source['visual_transcript_pages'][str(n)]
                    data=document[n-1].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes('png')
                    (directory/proof['render_path']).write_bytes(data)
                    proof['render_sha256']=hashlib.sha256(data).hexdigest()
            reader=PdfReader(io.BytesIO(content))
            pages=verified_visual_pages(content,source,directory,reader)
            self.assertEqual(set(pages),{1,6,7,9})
            changed=copy.deepcopy(source);changed['visual_transcript_pages']['6']['text']+=' changed'
            with self.assertRaises(ValueError):verified_visual_pages(content,changed,directory,reader)
            changed=copy.deepcopy(source);changed['visual_transcript_pages']['6']['render_path']='../escape.png'
            with self.assertRaises(ValueError):verified_visual_pages(content,changed,directory,reader)
            proof=source['visual_transcript_pages']['6'];(directory/proof['render_path']).write_bytes(b'corrupt')
            with self.assertRaises(ValueError):verified_visual_pages(content,source,directory,reader)


if __name__=='__main__':unittest.main()
