# -*- coding: utf-8 -*-
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import json
import copy

from services.regional_fiscal_service import (
    ensure_regional_fiscal_table, parse_asfin_dat, import_china_official_csv,
    build_regional_fiscal_payload, parse_china_final_account_text,
    parse_mof_regional_debt_html, parse_nbs_regional_fiscal_sheet, CN_PROVINCES,
    parse_nbs_regional_fiscal_image,
    _upsert,
    parse_china_annual_fiscal_bulletin, _derived_rows,
    sync_reviewed_regional_fiscal, validate_reviewed_regional_fiscal_snapshot,
    parse_china_execution_report, parse_china_fiscal_completion_release, parse_china_fiscal_pdf_pages,
)
from services.nbs_yearbook_ocr import parse_ocr_numeric_rows


class RegionalFiscalServiceTests(unittest.TestCase):
    def ningxia_pdf_fixture(self):
        return {
            5:'''2025年全区地方一般公共预算收入执行情况表（财政快报数）表1 单位：万元
            项目 2024年决算数 2025年预算数 2025年完成数 为预算数的% 比上年增减%
            地方一般公共预算收入合计 5,165,863 5,320,000 5,405,747 101.6% 4.6%
            一、税收收入 3,589,402 3,720,000 3,874,029 104.1% 7.9%''',
            6:'''2025年全区一般公共预算支出执行情况表（财政快报数）表2 单位：万元
            预算科目 2024年决算数 2025年变动预算数 2025年完成数
            一般公共预算支出 17,684,951 20,220,887 17,773,512 88% 0.5%''',
            95:'''2025年全区政府性基金预算收支执行情况表（财政快报数）表19 单位：万元
            2024年决算数 2025年预算数 2025年完成数
            一、政府性基金收入 999,237 1,380,459 1,004,892 0.6%
            国有土地使用权出\n让收入 833,781 1,228,071 859,397 3.1%''',
            96:'二、专项债务对应项目专项收入 56,845 49,199 42,080 -26.0%',
            97:'政府性基金表延续，不构造缺失数字。',
            98:'''收入合计 1,056,082 1,429,658 1,046,972 -0.9% 支出合计 1,639,638 2,359,036 4,100,104 150.1%
            收入总计 4,663,604 4,253,607 7,327,056 57.1% 支出总计 4,663,604 4,253,607 7,327,056 57.1%''',
            187:'''2025年全区政府债务基本情况表 表60 单位：亿元
            地区 政府债务限额 政府债务余额 债务到期规模
            全区 3,230.10 1,923.20 1,306.90 2,985.07 1,819.70 1,131.78 33.59 624.55 2,360.52
            自治区本级 1,042.30 590.47 451.84 877.85 566.96 310.22 0.67 167.23 710.62''',
            188:'''2025年全区政府债务还本付息情况表 表61 单位：亿元
            2025年新增政府债务 2025年政府债务偿还本金 2025年余额 2025年付息支出
全区 2,489.47 523.00 523.00 212.82 25.02 185.42 2.38 2,985.07 79.46
自治区本级 746.84 136.03 136.03 40.76 4.99 35.74 0.03 877.85 24.01''',
        }

    def test_pdf_tables_select_completed_column_and_literal_units_not_budget_or_gross_total(self):
        rows=parse_china_fiscal_pdf_pages(self.ningxia_pdf_fixture(),'宁夏','2025','ningxia_2025_execution_tables')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},{
            'general_budget_revenue':540.5747,'tax_revenue':387.4029,'general_budget_expenditure':1777.3512,
            'gov_fund_revenue':104.6972,'gov_fund_expenditure':410.0104,'land_transfer_revenue':85.9397,
            'debt_outstanding':2985.07,'principal_repayment':212.82,'interest_expenditure':79.46})
        self.assertTrue(all(r['data_status']=='official_preliminary' and r['unit']=='亿元' for r in rows))
        self.assertEqual(next(r['raw_unit'] for r in rows if r['indicator_code']=='general_budget_revenue'),'万元')
        self.assertEqual(next(r['raw_unit'] for r in rows if r['indicator_code']=='debt_outstanding'),'亿元')
        self.assertFalse(any(r['indicator_code'] in ('general_debt_outstanding','special_debt_outstanding') for r in rows))

    def test_pdf_tables_require_current_headers_units_and_every_continuation_page(self):
        for mutation in ('missing','wrong_unit','wrong_column','wrong_year'):
            pages=self.ningxia_pdf_fixture()
            if mutation=='missing':del pages[98]
            elif mutation=='wrong_unit':pages[5]=pages[5].replace('单位：万元','单位：亿元')
            elif mutation=='wrong_column':pages[5]=pages[5].replace('2025年预算数 2025年完成数','2025年完成数 2025年预算数')
            else:pages[95]=pages[95].replace('2025年全区','2024年全区')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                parse_china_fiscal_pdf_pages(pages,'宁夏','2025','ningxia_2025_execution_tables')

    def test_pdf_tables_do_not_shift_blank_debt_cells_or_ignore_inconsistent_totals(self):
        for mutation in ('new_foreign_zero','total','tax_parent','debt_components'):
            pages=self.ningxia_pdf_fixture()
            if mutation=='new_foreign_zero':pages[188]=pages[188].replace('523.00 523.00 212.82','523.00 523.00 0 212.82')
            elif mutation=='total':pages[188]=pages[188].replace('2,985.07 79.46','3,000.00 79.46')
            elif mutation=='tax_parent':pages[5]=pages[5].replace('3,874,029','9,874,029')
            else:pages[187]=pages[187].replace('1,819.70','1,500.00')
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                parse_china_fiscal_pdf_pages(pages,'宁夏','2025','ningxia_2025_execution_tables')

    def test_completion_release_uses_textual_amounts_and_not_missing_land_or_debt(self):
        html = '''<h1>2025年全区一般公共预算和政府性基金预算收支完成情况</h1>
        初步统计，全区一般公共预算收入3,005.2亿元，同比下降4.6%。其中，税收2115.6亿元，非税收入889.6亿元。
        全区一般公共预算支出6635.4亿元。全区政府性基金预算收入452.4亿元，主要是土地收入减少；
        全区政府性基金预算支出1212.1亿元。信息来源：内蒙古自治区财政厅'''
        rows = parse_china_fiscal_completion_release(html, '内蒙古', '2025',
                                                     'inner_mongolia_2025_completion')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'general_budget_revenue':3005.2, 'general_budget_expenditure':6635.4,
            'tax_revenue':2115.6, 'gov_fund_revenue':452.4, 'gov_fund_expenditure':1212.1})
        self.assertTrue(all(r['data_status']=='official_preliminary' for r in rows))
        for invalid in (html.replace('2025年全区一般', '2026年全区一般'),
                        html.replace('信息来源：', '其他说明：'),
                        html.replace('税收2115.6亿元', '税收9999亿元'),
                        html.replace('初步统计，', '2026年全区预算安排600亿元。初步统计，')):
            with self.subTest(html=invalid), self.assertRaises(ValueError):
                parse_china_fiscal_completion_release(invalid, '内蒙古', '2025',
                                                       'inner_mongolia_2025_completion')

    def sichuan_execution_fixture(self):
        return '''四川省2025年预算执行情况和2026年预算草案。
        一、2025年预算执行情况。（一）一般公共预算。
        全省地方一般公共预算收入5853.9亿元，增长3.9%。其中：税收收入3732.1亿元。
        省级实现收入1018亿元。全省一般公共预算支出13697.6亿元，省级实现支出2281.6亿元。
        全省筹集收入来源16969.1亿元；安排全省一般公共预算支出13697.6亿元，偿还一般债务1009.8亿元。
        （二）政府性基金预算。全省政府性基金预算收入3789.3亿元（其中：土地出让收入3147亿元）；
        加上中央转移支付、专项债务等来源，实现支出5918.6亿元，其中：土地出让收入安排支出2455.3亿元。
        省级政府性基金预算收入139亿元，支出112.7亿元。
        （三）国有资本经营预算。全省国有资本经营预算收入227亿元。
        （五）地方政府债务。减去偿还到期政府债务1292.3亿元后，全省政府债务余额28015亿元，
        较2024年末余额24028.9亿元增加3986.1亿元，限额29635.7亿元。
        全省一般债务限额8739.4亿元，余额8515.5亿元；专项债务限额20896.3亿元，余额19499.5亿元。
        二、落实省人大预算决议和重点财政工作情况。省级财政政策安排50亿元。
        三、十四五财政工作。五年累计收入8.11万亿元。
        四、2026年预算草案。全省地方一般公共预算收入5971亿元，全省一般公共预算支出14136.9亿元。
        全省政府性基金预算收入3190亿元，全省政府债务余额31000亿元。'''

    def test_sichuan_execution_preserves_full_scope_and_balance_not_limits(self):
        rows = parse_china_execution_report(self.sichuan_execution_fixture(), '四川', '2025',
                                            'sichuan_2025_execution')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'general_budget_revenue':5853.9, 'general_budget_expenditure':13697.6,
            'tax_revenue':3732.1, 'gov_fund_revenue':3789.3, 'gov_fund_expenditure':5918.6,
            'land_transfer_revenue':3147, 'debt_outstanding':28015,
            'general_debt_outstanding':8515.5, 'principal_repayment':1292.3})
        self.assertTrue(all(r['period']=='2025' and r['government_scope']=='province_total'
                            and r['data_status']=='official_preliminary' for r in rows))
        self.assertFalse(any(r['indicator_code']=='special_debt_outstanding' for r in rows))

    def test_sichuan_execution_rejects_ambiguous_or_broken_sections(self):
        fixture = self.sichuan_execution_fixture()
        for invalid in (
            fixture.replace('四、2026年预算草案', '四、其他安排'),
            fixture.replace('（二）政府性基金预算', '（二）其他预算'),
            fixture.replace('其中：税收收入3732.1亿元', '其中：税收收入7000亿元'),
            fixture.replace('土地出让收入3147亿元', '土地出让收入4000亿元'),
            fixture.replace('余额8515.5亿元', '余额30000亿元'),
            fixture.replace('全省筹集收入来源', '全省地方一般公共预算收入9999亿元。全省筹集收入来源'),
        ):
            with self.subTest(text=invalid), self.assertRaises(ValueError):
                parse_china_execution_report(invalid, '四川', '2025', 'sichuan_2025_execution')

    def test_execution_profile_cannot_cross_province_or_year(self):
        for province, period, profile in (
            ('福建', '2025', 'sichuan_2025_execution'),
            ('四川', '2024', 'sichuan_2025_execution'),
            ('四川', '2025', 'generic'),
        ):
            with self.subTest(province=province, period=period), self.assertRaises(ValueError):
                parse_china_execution_report(self.sichuan_execution_fixture(), province, period, profile)

    def test_fujian_execution_does_not_invent_tax_or_replace_final_special_debt(self):
        text = '''福建省2025年预算执行情况与2026年预算草案。一、2025年预算执行情况。
        （一）2025年预算收支情况。1.一般公共预算。全省地方一般公共预算收入3723.35亿元。
        全省一般公共预算支出6148.7亿元。省本级地方一般公共预算收入271.49亿元。
        2.政府性基金预算。全省政府性基金预算收入1680.45亿元，国有土地使用权出让收入减收。
        全省政府性基金预算支出3971.63亿元。省本级政府性基金预算收入38.84亿元，支出79.66亿元。
        3.国有资本经营预算。全省收入201.85亿元。4.社会保险基金预算。
        5.地方政府债务情况。全省共偿还政府债务本金726.3亿元。截至2025年末，
        全省政府债务余额18918.79亿元（其中，一般债务4155.16亿元，占22%；专项债务14763.63亿元，占78%）。
        省本级共偿还政府债务本金13.69亿元，省本级政府债务余额431.05亿元。
        （二）主要财税政策落实和重点财政工作情况。税费减免1000亿元。
        二、2026年预算草案。全省地方一般公共预算收入预计为3816.43亿元，
        全省政府性基金预算收入预计为1814.88亿元。'''
        rows = parse_china_execution_report(text, '福建', '2025', 'fujian_2025_execution')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows}, {
            'general_budget_revenue':3723.35, 'general_budget_expenditure':6148.7,
            'gov_fund_revenue':1680.45, 'gov_fund_expenditure':3971.63,
            'debt_outstanding':18918.79, 'general_debt_outstanding':4155.16, 'principal_repayment':726.3})
        self.assertFalse(any(r['indicator_code'] in ('tax_revenue', 'land_transfer_revenue',
                                                     'special_debt_outstanding') for r in rows))

    def test_execution_report_excludes_next_year_plans_limits_and_province_own_values(self):
        text='''云南省2025年执行情况与2026年草案。一、2025年地方财政预算执行
        （一）一般公共预算。全省地方一般公共预算收入2243.3亿元，全省地方一般公共预算支出7002.2亿元。
        全省税收收入完成1510.1亿元。（二）政府性基金预算。全省政府性基金预算收入893.5亿元，
        全省政府性基金预算支出2286亿元。2025年末全省地方政府债务限额19622.4亿元，
        2025年末全省地方政府债务余额18320.7亿元，其中省级3481亿元。
        二、“十五五”时期和2026年地方财政预算安排。全省地方一般公共预算收入2288亿元，
        全省地方一般公共预算支出7107亿元，全省政府性基金预算收入700亿元。'''
        rows=parse_china_execution_report(text,'云南','2025','yunnan_2025_execution')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},{'general_budget_revenue':2243.3,
            'general_budget_expenditure':7002.2,'tax_revenue':1510.1,'gov_fund_revenue':893.5,
            'gov_fund_expenditure':2286,'debt_outstanding':18320.7})
        self.assertTrue(all(r['data_status']=='official_preliminary' for r in rows))
        with self.assertRaises(ValueError):parse_china_execution_report(text.replace('二、“十五五”时期和2026年地方财政预算安排','二、未来规划'),
            '云南','2025','yunnan_2025_execution')

    def fiscal_snapshot(self):
        row={'country_code':'CN','government_scope':'province_total','region_code':'110000','region_name':'北京',
             'indicator_code':'general_budget_revenue','period':'2025','value':6680.6,'unit':'亿元',
             'frequency':'annual','period_type':'calendar_year','data_status':'official_preliminary',
             'source_name':'北京市统计局','source_url':'https://tjj.beijing.gov.cn/a.html',
             'source_title':'2025年北京市统计公报','parser_notes':'全市地方一般公共预算收入，初步数。'}
        return {'schema_version':1,'review_status':'source_values_reviewed','statistical_year':'2025',
                'generated_at':'2026-10-13T12:00:00+00:00','observations':[row]}

    def test_reviewed_fiscal_is_idempotent_and_keeps_unrelated_rows(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;ensure_regional_fiscal_table(conn)
        with tempfile.TemporaryDirectory() as directory:
            snapshot=self.fiscal_snapshot()
            existing={**snapshot['observations'][0],'region_code':'110100','government_scope':'city_total','value':1}
            _upsert(conn,existing)
            (Path(directory)/'snapshot.json').write_text(json.dumps(snapshot),encoding='utf-8')
            first=sync_reviewed_regional_fiscal(conn,directory);second=sync_reviewed_regional_fiscal(conn,directory)
            self.assertEqual((first['inserted'],second['inserted'],second['updated'],second['unchanged']),(1,0,0,1))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0],2)
            self.assertEqual(conn.execute("SELECT value FROM regional_fiscal_observations WHERE government_scope='city_total'").fetchone()[0],1)
        conn.close()

    def test_reviewed_fiscal_rejects_wrong_grain_scope_source_and_tax_parent(self):
        for mutation in ('month','scope','source','bool','tax'):
            snapshot=self.fiscal_snapshot();row=snapshot['observations'][0]
            if mutation=='month':row['period']='2025-06'
            elif mutation=='scope':row['government_scope']='province_level'
            elif mutation=='source':row['source_url']='https://example.com/data'
            elif mutation=='bool':row['value']=True
            else:snapshot['observations'].append({**copy.deepcopy(row),'indicator_code':'tax_revenue','value':10000})
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_reviewed_regional_fiscal_snapshot(snapshot)

    def test_reviewed_fiscal_revision_preserves_original(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;ensure_regional_fiscal_table(conn)
        with tempfile.TemporaryDirectory() as directory:
            snapshot=self.fiscal_snapshot();path=Path(directory)/'snapshot.json'
            path.write_text(json.dumps(snapshot),encoding='utf-8');sync_reviewed_regional_fiscal(conn,directory)
            snapshot['observations'][0]['value']=6680.7
            path.write_text(json.dumps(snapshot),encoding='utf-8');result=sync_reviewed_regional_fiscal(conn,directory)
            self.assertEqual(result['updated'],1)
            old=json.loads(conn.execute('SELECT original_row_json FROM regional_fiscal_revision_history').fetchone()[0])
            self.assertEqual(old['value'],6680.6);self.assertEqual(old['source_url'],'https://tjj.beijing.gov.cn/a.html')
        conn.close()

    def test_annual_bulletin_reads_local_revenue_tax_and_expenditure(self):
        text='2025年，全年完成一般公共预算收入6680.6亿元。其中，税收收入5775.6亿元。全市一般公共预算支出8401.9亿元。'
        rows=parse_china_annual_fiscal_bulletin(text,'北京','2025','北京市2025年国民经济和社会发展统计公报')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},
                         {'general_budget_revenue':6680.6,'tax_revenue':5775.6,'general_budget_expenditure':8401.9})
        self.assertTrue(all(r['government_scope']=='province_total' and r['period_type']=='calendar_year' for r in rows))

    def test_bulletin_does_not_take_province_own_or_planned_amount(self):
        text='2025年，省本级一般公共预算收入100亿元。全年全省一般公共预算收入900亿元。计划一般公共预算支出1200亿元。'
        rows=parse_china_annual_fiscal_bulletin(text,'福建','2025','2025年福建省统计公报')
        self.assertEqual([(r['indicator_code'],r['value']) for r in rows],[('general_budget_revenue',900)])

    def test_tax_authority_collection_and_total_receipts_are_not_local_budget_tax(self):
        text='2025年，全年全省一般公共预算收入900亿元。全省财政总收入1800亿元，其中税收收入1200亿元。'
        rows=parse_china_annual_fiscal_bulletin(text,'福建','2025','2025年福建省统计公报')
        self.assertEqual([r['indicator_code'] for r in rows],['general_budget_revenue'])

    def test_fullwidth_and_literal_unit_scaling(self):
        text='２０２５年，全年全省一般公共预算收入０．９万亿元，其中税收收入６，０００．５０亿元。一般公共预算支出１．２万亿元。'
        rows=parse_china_annual_fiscal_bulletin(text,'福建','2025','2025年福建省统计公报')
        self.assertEqual({r['indicator_code']:r['value'] for r in rows},
                         {'general_budget_revenue':9000,'tax_revenue':6000.5,'general_budget_expenditure':12000})

    def test_missing_or_subannual_fields_do_not_become_zero(self):
        self.assertEqual(parse_china_annual_fiscal_bulletin('2025年，全省经济增长5%。','福建','2025','2025年福建省统计公报'),[])
        with self.assertRaises(ValueError):
            parse_china_annual_fiscal_bulletin('2025年，上半年收入900亿元。','福建','2025','2025年上半年经济运行情况')

    def test_mof_balance_column_is_selected_by_header_not_last_number(self):
        body='<tr><th>地区</th><th>2025年末专项债务余额</th><th>2025年专项债务限额</th></tr>'
        body+=''.join(f'<tr><td>{name}</td><td>{i+1}</td><td>1000</td></tr>' for i,name in enumerate(CN_PROVINCES))
        rows=parse_mof_regional_debt_html('<table>'+body+'</table>','special_debt_outstanding','2025','https://yss.mof.gov.cn/table',require_balance_header=True)
        self.assertEqual(rows[0]['value'],1);self.assertEqual(len(rows),31)
        with self.assertRaisesRegex(ValueError,'balance column'):
            parse_mof_regional_debt_html('<table>'+body.replace('2025年末专项债务余额','2024年末专项债务余额')+'</table>',
                                       'special_debt_outstanding','2025','https://yss.mof.gov.cn/table',require_balance_header=True)

    def test_zero_denominators_skip_ratios_but_preserve_actual_balance(self):
        base={'country_code':'CN','government_scope':'province_total','region_code':'110000','period':'2025','unit':'亿元'}
        rows=[{**base,'indicator_code':code,'value':value} for code,value in
              [('general_budget_revenue',0),('general_budget_expenditure',20),('tax_revenue',0),('gov_fund_revenue',0),('land_transfer_revenue',1)]]
        derived=_derived_rows(rows)
        self.assertEqual([r['value'] for r in derived if r['indicator_code']=='fiscal_balance'],[-20])
        self.assertFalse(any(r['indicator_code'] in ('tax_share','land_dependency') for r in derived))

    def test_upsert_refreshes_source_lineage_on_canonical_overlap(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        ensure_regional_fiscal_table(conn)
        base = {'country_code': 'CN', 'government_scope': 'province_total',
                'region_code': '110000', 'region_name': '北京',
                'indicator_code': 'general_budget_revenue', 'period': '2023',
                'value': 1, 'unit': '亿元', 'frequency': 'annual',
                'period_type': 'calendar_year', 'source_title': 'old',
                'parser_notes': 'old'}
        _upsert(conn, {**base, 'source_name': '省级财政部门',
                       'source_url': 'https://czj.beijing.gov.cn/old'})
        _upsert(conn, {**base, 'value': 2,
                       'source_name': '国家统计局《中国统计年鉴》',
                       'source_url': 'https://www.stats.gov.cn/new',
                       'source_title': 'new', 'parser_notes': 'new'})
        row = conn.execute('SELECT * FROM regional_fiscal_observations').fetchone()
        self.assertEqual(row['value'], 2)
        self.assertEqual(row['source_name'], '国家统计局《中国统计年鉴》')
        self.assertEqual(row['source_url'], 'https://www.stats.gov.cn/new')

    def test_nbs_ocr_rows_skip_aggregate_and_enforce_confidence(self):
        def box(x, y): return [[x, y], [x + 8, y], [x + 8, y + 4], [x, y + 4]]
        ocr = []
        for row in range(32):
            y = 100 + row * 20
            for column, value in enumerate((1000 + row, 700 + row, 10 + row)):
                ocr.append([box(100 + column * 80, y), str(value), 0.99])
        rows = parse_ocr_numeric_rows(ocr, needed_columns=2)
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[0]['values'], [1001.0, 701.0])
        ocr[-3][2] = 0.5
        with self.assertRaisesRegex(ValueError, 'confidence'):
            parse_ocr_numeric_rows(ocr, needed_columns=2)

    def test_nbs_fiscal_image_maps_revenue_tax_and_rejects_inversion(self):
        extracted = [{'values': [1000 + i, 700 + i], 'confidence': 0.99}
                     for i in range(31)]
        with patch('services.regional_fiscal_service.extract_nbs_yearbook_image_values',
                   return_value=extracted):
            rows = parse_nbs_regional_fiscal_image(
                b'jpeg', '2024', 'revenue', 'https://stats.gov.cn/table.jpg')
        self.assertEqual(len(rows), 62)
        self.assertEqual(rows[0]['region_name'], '北京')
        self.assertEqual(rows[1]['indicator_code'], 'tax_revenue')
        extracted[4]['values'] = [100, 101]
        with patch('services.regional_fiscal_service.extract_nbs_yearbook_image_values',
                   return_value=extracted):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                parse_nbs_regional_fiscal_image(
                    b'jpeg', '2024', 'revenue', 'https://stats.gov.cn/table.jpg')

    def test_nbs_fiscal_sheet_maps_revenue_tax_and_expenditure(self):
        class Sheet:
            ncols = 3
            data = [[name, i + 100, i + 50] for i, name in enumerate(CN_PROVINCES)]
            nrows = len(data)
            def cell_value(self, row, col): return self.data[row][col]
        revenue = parse_nbs_regional_fiscal_sheet(
            Sheet(), '2020', 'revenue', 'https://stats.gov.cn/revenue.xls')
        expenditure = parse_nbs_regional_fiscal_sheet(
            Sheet(), '2020', 'expenditure', 'https://stats.gov.cn/expenditure.xls')
        self.assertEqual(len(revenue), 62)
        self.assertEqual(len(expenditure), 31)
        self.assertEqual({r['indicator_code'] for r in revenue},
                         {'general_budget_revenue', 'tax_revenue'})

    def test_mof_debt_parser_requires_all_provinces_and_skips_subregions(self):
        body = ''.join(f'<tr><td>{name}省</td><td>100</td><td>{i + 1}</td></tr>'
                       for i, name in enumerate(CN_PROVINCES))
        body += '<tr><td>广东省（不含深圳市）</td><td>90</td><td>80</td></tr>'
        rows = parse_mof_regional_debt_html(
            f'<table>{body}</table>', 'general_debt_outstanding', '2024', 'https://mof.gov.cn/x')
        self.assertEqual(len(rows), 31)
        self.assertEqual(len({r['region_code'] for r in rows}), 31)
        self.assertEqual(rows[0]['value'], 1.0)

    def test_mof_debt_parser_rejects_partial_table(self):
        with self.assertRaisesRegex(ValueError, 'expected 31'):
            parse_mof_regional_debt_html(
                '<table><tr><td>北京市</td><td>2</td><td>1</td></tr></table>',
                'general_debt_outstanding', '2024', 'https://mof.gov.cn/x')

    def test_parse_shanghai_final_account_narrative(self):
        text = '''全 市 一般公共预算收入 8312.5 亿元，全市一般公共预算支出9638.5亿元。
        全市政府性基金预算收入3466.7亿元，全市政府性基金预算支出2997.7亿元。
        市级国有土地使用权出让收入774.4亿元。截至2023年底，本市政府债务余额为8832.3亿元。'''
        rows = parse_china_final_account_text(text, 'shanghai_2023')
        values = {(r['government_scope'], r['indicator_code']): r['value'] for r in rows}
        self.assertEqual(values[('province_total', 'general_budget_revenue')], 8312.5)
        self.assertEqual(values[('province_total', 'debt_outstanding')], 8832.3)
        self.assertEqual(values[('province_level', 'land_transfer_revenue')], 774.4)

    def test_parse_guangdong_final_account_table_and_debt(self):
        text = '''全省一般公共预算收入13850.78亿元，全省一般公共预算支出18527.03亿元。
        全省政府性基金预算收入4501.88亿元，全省政府性基金预算支出8244.75亿元。
        全省政府债务余额29879.6亿元，其中一般债务7628.77亿元、专项债务22250.82亿元。
        全省偿还地方政府债券本金2054.53亿元；支付地方政府债券利息899.13亿元。
        国有土地使用权出让收入59,546,504 40,960,318 38,101,623'''
        values = {r['indicator_code']: r['value']
                  for r in parse_china_final_account_text(text, 'guangdong_2023')}
        self.assertEqual(values['land_transfer_revenue'], 3810.1623)
        self.assertEqual(values['special_debt_outstanding'], 22250.82)
        self.assertEqual(values['interest_expenditure'], 899.13)

    def test_beijing_parser_uses_full_city_appendix(self):
        text = '''收入合计 34,316,000 33,916,000 31,508,712 92.9
        收入合计 57,143,583 注：2022年全市一般公共预算收入。
        国有土地使用权出让收入 6,329,500 6,329,500 6,596,581 104.2
        国有土地使用权出让收入 21,007,854'''
        values = {r['indicator_code']: r['value']
                  for r in parse_china_final_account_text(text, 'beijing_2022')}
        self.assertAlmostEqual(values['general_budget_revenue'], 5714.3583)
        self.assertAlmostEqual(values['land_transfer_revenue'], 2100.7854)

    def test_asfin_parser_maps_units_and_skips_us_and_missing(self):
        text = ('#YEAR|GEO_ID|GEO_LABEL|ST|AGG_DESC|AGG_DESC_LABEL|GOVTYPE|AMOUNT\n'
                '2024|x|Alabama|01|SF0001|Revenue - Total Revenue|002|1234000\n'
                '2024|x|Alabama|01|SF0132|Expenditure - Total Expenditure|002|X\n'
                '2024|x|United States|00|SF0001|Revenue - Total Revenue|002|999\n')
        rows = parse_asfin_dat(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['indicator_code'], 'total_revenue')
        self.assertEqual(rows[0]['value'], 1234.0)
        self.assertEqual(rows[0]['period'], '2024')

    def test_china_import_requires_official_url_and_is_idempotent(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        ensure_regional_fiscal_table(conn)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cn.csv'
            path.write_text('region_code,region_name,period,indicator_code,value,unit,source_url\n'
                            '11,北京,2023,general_budget_revenue,6181.1,亿元,https://czj.beijing.gov.cn/a\n', encoding='utf-8')
            self.assertEqual(import_china_official_csv(conn, str(path))['rows'], 1)
            self.assertEqual(import_china_official_csv(conn, str(path))['rows'], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM regional_fiscal_observations').fetchone()[0], 1)

    def test_payload_builds_balance_tax_share_and_interest_burden(self):
        conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
        ensure_regional_fiscal_table(conn)
        base = ('US','state_government','01','Alabama','2023','million current US$','annual','fiscal_year','official','Census','https://census.gov','t','n','now')
        for code,value in [('total_revenue',100),('total_expenditure',110),('tax_revenue',60),('interest_expenditure',5)]:
            conn.execute('''INSERT INTO regional_fiscal_observations(country_code,government_scope,region_code,region_name,
              indicator_code,period,value,unit,frequency,period_type,data_status,source_name,source_url,source_title,parser_notes,updated_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', base[:4]+(code,base[4],value)+base[5:])
        payload = build_regional_fiscal_payload(conn)
        values={r['indicator_code']:r['value'] for r in payload['rows']}
        self.assertEqual(values['fiscal_balance'], -10)
        self.assertEqual(values['tax_share'], 60)
        self.assertEqual(values['interest_burden'], 5)

    def test_page_has_real_regional_fiscal_controls(self):
        page=(Path(__file__).resolve().parents[1]/'static'/'gdp.html').read_text(encoding='utf-8')
        for token in ('data-tab="fiscal"','id="fiscalCountry"','id="fiscalMetric"',
                      'id="fiscalStart"','id="fiscalEnd"','id="fiscalRanking"'):
            self.assertIn(token,page)


if __name__ == '__main__': unittest.main()
