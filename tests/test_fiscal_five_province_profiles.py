"""Protect scope/years and exact official-source identity of the five-province cohort."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

from services.provincial_issuer_visual_profiles import parse_provincial_issuer_visual_pages
from services.provincial_fiscal_visual_expansion import FIVE_VISUAL_PROFILES
from services.fiscal_source_authority import APPROVED_VISUAL_FILINGS,reviewed_issuer_fiscal_source
from services.provincial_fiscal_report_profiles import parse_provincial_fiscal_annex_pages
from scripts.review_province_fiscal_supplement import verified_visual_pages,visual_transcript_digest

ROOT=Path(__file__).resolve().parents[1]


class FiveProvinceFiscalProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=json.loads((ROOT/'data/province_fiscal_five_visual_declarations_20261015.json').read_text(encoding='utf8'))['documents']

    def parse(self,source,year,text=None):
        return parse_provincial_issuer_visual_pages(
            text or {int(n):t for n,t in source['transcript_texts'].items()},source['region_name'],year,source['profile'])

    def test_all_inspected_values_vintages_and25_selected_visual_fields(self):
        self.assertEqual(sum(len(p['import_codes']) for s in self.sources for p in s['periods'].values()),25)
        for source in self.sources:
            for year,definition in source['periods'].items():
                with self.subTest(source=source['id'],year=year):
                    rows=self.parse(source,year)
                    self.assertEqual({r['indicator_code']:r['value'] for r in rows},definition['expected_values'])
                    self.assertTrue(all(r['government_scope']=='province_total' and r['data_status']==
                                        FIVE_VISUAL_PROFILES[source['profile']]['fiscal_status'][year] for r in rows))

    def test_future_years_wrong_province_and_missing_or_extra_pages_fail_closed(self):
        for s in self.sources:
            text={int(n):t for n,t in s['transcript_texts'].items()};year=next(iter(s['periods']))
            for bad in ({**text,99:'not reviewed'},{n:t for n,t in text.items() if n!=1}):
                with self.assertRaises(ValueError):self.parse(s,year,bad)
            with self.assertRaises(ValueError):self.parse(s,'2026')
            with self.assertRaises(ValueError):parse_provincial_issuer_visual_pages(text,'福建',year,s['profile'])

    def test_actual_fiscal_headers_scope_units_and_signatures_are_required(self):
        for s in self.sources:
            if s['region_name']=='天津':continue
            text={int(n):t for n,t in s['transcript_texts'].items()};year=next(iter(s['periods']))
            for old,new in [('全省','全县') if s['region_name']!='北京' else ('全市','市本级'),('财政收支状况（亿元）','财政收支状况（万元）')]:
                bad={n:t.replace(old,new) for n,t in text.items()}
                with self.subTest(region=s['region_name'],old=old),self.assertRaises(ValueError):self.parse(s,year,bad)
            bad={n:t.replace(FIVE_VISUAL_PROFILES[s['profile']]['issuer'],'评级公司') for n,t in text.items()}
            with self.assertRaises(ValueError):self.parse(s,year,bad)

    def test_tianjin_fund_totals_and_government_level_split_never_become_other_fields(self):
        s=next(s for s in self.sources if s['region_name']=='天津');rows=self.parse(s,'2025')
        self.assertEqual({r['indicator_code'] for r in rows},{'debt_outstanding'})
        self.assertEqual(rows[0]['value'],15099.4)
        for old,new in [('市本级债务','一般债务'),('区级债务','专项债务'),('全市政府性基金总收入','全市政府性基金收入')]:
            text={int(n):t.replace(old,new) for n,t in s['transcript_texts'].items()}
            with self.assertRaises(ValueError):self.parse(s,'2025',text)

    def test_liaoning_negative_own_spending_is_not_zero_or_whole_province(self):
        s=next(s for s in self.sources if s['region_name']=='辽宁')
        rows=self.parse(s,'2023');values={r['indicator_code']:r['value'] for r in rows}
        self.assertEqual(values['gov_fund_expenditure'],1166.3);self.assertNotIn('debt_outstanding',values)
        for old,new in [('-72.6','-'),('1166.3','-1166.3'),('债务类数据不包含大连市','债务类数据包含大连市')]:
            text={int(n):t.replace(old,new) for n,t in s['transcript_texts'].items()}
            with self.assertRaises(ValueError):self.parse(s,'2023',text)

    def test_each_source_exception_is_bound_to_exact_sha_transcript_page_and_status(self):
        for s in self.sources:
            policy=APPROVED_VISUAL_FILINGS[s['source_url']]
            for year in s['periods']:
                for row in self.parse(s,year):
                    row.update(source_name=s['source_name'],source_title=s['source_title'],
                               source_url=s['source_url']+'#page='+str(row['evidence_page']),
                               parser_notes='access_type=official_platform_document; raw_sha256='+s['raw_sha256']+
                               '; visual_transcript_sha256='+policy['transcript_sha256']+
                               '; parse_mode=reviewed_visual_transcript; unit_evidence=explicit_source_heading')
                    self.assertTrue(reviewed_issuer_fiscal_source(row))
                    for field,value in [('source_url',s['source_url']+'#page=99'),('parser_notes','wrong hash'),
                                        ('source_title','Credit rating report'),('period','2026')]:
                        self.assertFalse(reviewed_issuer_fiscal_source({**row,field:value}))

    def test_only_reviewed_hebei_identity_page_can_have_a_partial_text_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);s=copy.deepcopy(next(s for s in self.sources if s['region_name']=='河北'))
            s['visual_transcript_pages']={}
            for n in s['reviewed_pages']:
                body=('pixels'+str(n)).encode();(directory/(str(n)+'.png')).write_bytes(body)
                s['visual_transcript_pages'][str(n)]={'text':s['transcript_texts'][str(n)],'render_path':str(n)+'.png',
                    'render_scale':1.6,'render_sha256':hashlib.sha256(body).hexdigest()}
            s['transcript_sha256']=visual_transcript_digest(s)
            reader=MagicMock();reader.pages=[MagicMock() for _ in range(3)]
            for i,p in enumerate(reader.pages):p.extract_text.return_value='identity text' if i==0 else ''
            document=MagicMock()
            document.__getitem__.side_effect=lambda index:MagicMock(get_pixmap=lambda **kwargs:MagicMock(tobytes=lambda fmt:('pixels'+str(index+1)).encode()))
            context=MagicMock();context.__enter__.return_value=document
            with patch('scripts.review_province_fiscal_supplement.fitz.open',return_value=context):
                self.assertEqual(set(verified_visual_pages(b'%PDF-fixture',s,directory,reader)),{1,2,3})
                reader.pages[1].extract_text.return_value='unexpected numeric text'
                with self.assertRaises(ValueError):verified_visual_pages(b'%PDF-fixture',s,directory,reader)

    def test_liaoning2025_final_pdf_stops_before_excluding_dalian_and_limits(self):
        pages={1:'关于辽宁省2025年财政决算的报告 省财政厅厅长 一、2025年财政决算情况（一）全省财政决算情况 全省一般公共预算收入2918.6亿元。其中：税收收入1828.2亿元。',
               2:'全省一般公共预算支出6615.9亿元。全省政府性基金预算收入439亿元。全省政府性基金预算支出1436.9亿元。收入总量3118.3亿元。',
               7:'2025年地方政府债务限额16901.5亿元；全省政府债务余额15690.3亿元，其中：一般债务7964.1亿元，专项债务7726.2亿元。全省（不含大连）政府债务余额12129.1亿元，其中一般债务6283.3亿元。'}
        rows=parse_provincial_fiscal_annex_pages(pages,'辽宁','2025','liaoning_2025_final_report_pdf')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}['general_debt_outstanding'],7964.1)
        for page,old,new in [(1,'税收收入1828.2','税收收入3828.2'),(2,'全省政府性基金预算收入','省级政府性基金预算收入'),
                             (7,'7964.1','8964.1'),(7,'全省（不含大连）','下一个段落')]:
            bad=copy.deepcopy(pages);bad[page]=bad[page].replace(old,new)
            with self.assertRaises(ValueError):parse_provincial_fiscal_annex_pages(bad,'辽宁','2025','liaoning_2025_final_report_pdf')


if __name__=='__main__':unittest.main()
