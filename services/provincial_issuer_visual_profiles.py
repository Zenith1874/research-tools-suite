"""Parse labelled visual transcripts bound separately to inspected official PDF pages.

These are review transcripts, not OCR or a text layer recovered from the PDF.
The review runner verifies the original and reproduced page-render hashes first.
"""
import math
import re
import unicodedata
from services.provincial_fiscal_visual_expansion import FIVE_VISUAL_PROFILES, parse_five_province_visual_pages
from services.provincial_fiscal_six_profiles import SIX_VISUAL_PROFILES, parse_six_province_visual_pages


VISUAL_PROFILES = {
    'guangxi_2026_reviewed_visual': {
        'province':'广西','region_code':'450000','pages':{1,6,7,9},
        'fiscal_pages':(6,), 'table_header':'自治区本级全区自治区本级全区自治区本级全区',
        'issuer':'广西壮族自治区财政厅','signature_page':9,'signature_date':'2026年4月14日',
        'fiscal_status':{'2023':'official','2024':'official','2025':'official'},
        'specs':[('general_budget_revenue','一般公共预算收入',6),
                 ('general_budget_expenditure','一般公共预算支出',6),
                 ('gov_fund_revenue','政府性基金预算收入',6),
                 ('gov_fund_expenditure','政府性基金预算支出',6)],
    },
    'anhui_2026_reviewed_visual': {
        'province':'安徽','region_code':'340000','pages':{1,5,6,9,10},
        'fiscal_pages':(5,6),'table_header':'省本级全省省本级全省省本级全省',
        'issuer':'安徽省财政厅','signature_page':9,'signature_date':'2026年9月7日',
        'fiscal_status':dict.fromkeys(('2023','2024','2025'),'official_final'),
        'specs':[('general_budget_revenue','一般公共预算收入',5),
                 ('general_budget_expenditure','一般公共预算支出',5),
                 ('gov_fund_revenue','政府性基金收入',5),
                 ('gov_fund_expenditure','政府性基金支出',6),
                 ('land_transfer_revenue','国有土地使用权出让收入',6)],
    },
    'chongqing_2026_reviewed_visual': {
        'province':'重庆','region_code':'500000','pages':{1,7,8,9,11},
        'fiscal_pages':(7,8),'table_header':'市本全市市本级全市市本级全市',
        'issuer':'重庆市财政局','signature_page':11,'signature_date':'2026年9月11日',
        'fiscal_status':dict.fromkeys(('2023','2024','2025'),'official_final'),
        'specs':[('general_budget_revenue','一般公共预算收入',7),
                 ('general_budget_expenditure','一般公共预算支出',7),
                 ('gov_fund_revenue','政府性基金收入',8),
                 ('gov_fund_expenditure','政府性基金支出',8),
                 ('land_transfer_revenue','国有土地使用权出让收入',8)],
    },
    'guizhou_2026_reviewed_visual': {
        'province':'贵州','region_code':'520000','pages':{1,4,5,6,7,8,10,12},
        'fiscal_pages':(12,),'table_header':'省本级全省省本级全省省本级全省',
        'issuer':'贵州省财政厅','signature_page':10,'signature_date':'2026年9月11日',
        'fiscal_status':{'2023':'official_final','2024':'official_final','2025':'official_preliminary'},
        'specs':[('general_budget_revenue','一般公共预算收入',12),
                 ('general_budget_expenditure','一般公共预算支出',12),
                 ('gov_fund_revenue','政府性基金收入',12),
                 ('gov_fund_expenditure','政府性基金支出',12)],
    },
}
VISUAL_PROFILES.update(FIVE_VISUAL_PROFILES)
VISUAL_PROFILES.update(SIX_VISUAL_PROFILES)


def compact(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text or ''))


def parse_provincial_issuer_visual_pages(page_texts, province, period, profile):
    """Read only an inspected whole-province/year column and explicit source unit."""
    if profile in SIX_VISUAL_PROFILES:
        return parse_six_province_visual_pages(page_texts, province, period, profile)
    if profile in FIVE_VISUAL_PROFILES:
        return parse_five_province_visual_pages(page_texts,province,period,profile)
    config=VISUAL_PROFILES.get(profile);period=str(period)
    if not config or province!=config['province'] or period not in ('2023','2024','2025') or set(page_texts)!=config['pages']:
        raise ValueError('Use an exact reviewed visual profile, page set and stated fiscal year.')
    text={n:unicodedata.normalize('NFKC',t or '') for n,t in page_texts.items()}
    short={n:compact(t) for n,t in text.items()}
    if ('2026年' not in short[1] or '信息披露文件' not in short[1]
            or '信用评级报告' in short[1]
            or config['issuer']+config['signature_date'] not in short[config['signature_page']]):
        raise ValueError('The primary issuer identity, document type or signature date changed.')
    first=config['fiscal_pages'][0]
    if ('财政收支状况(亿元)' not in short[first]
            or '2023年2024年2025年' not in short[first]
            or config['table_header'] not in short[first]):
        raise ValueError('The explicit亿元 unit, years or local/whole-province column groups changed.')
    combined=''.join(short[n] for n in config['fiscal_pages'])
    if profile in ('anhui_2026_reviewed_visual','chongqing_2026_reviewed_visual') and '数据均为决算数' not in combined and '数据为决算数' not in combined:
        raise ValueError('The source must explicitly identify the fiscal amounts as final accounts.')
    if profile=='guizhou_2026_reviewed_visual' and ('2023-2024年贵州省财政决算报告' not in combined or '2025年预算执行情况' not in combined):
        raise ValueError('Keep the Guizhou final/execution source-vintage distinction explicit.')
    number=r'([\d,]+(?:\.\d+)?)';index=2*(int(period)-2023)+2;rows=[]

    def record(code,value,evidence,page,status=None):
        if not math.isfinite(value) or value<0:raise ValueError('Missing or invalid amounts are not observations.')
        rows.append({'country_code':'CN','government_scope':'province_total',
                     'region_code':config['region_code'],'region_name':province,
                     'indicator_code':code,'period':period,'value':value,'unit':'亿元',
                     'frequency':'annual','period_type':'calendar_year',
                     'data_status':status or config['fiscal_status'][period],
                     'evidence':evidence,'evidence_page':page,'raw_unit':'亿元',
                     'unit_source':'explicit_source_heading','parse_mode':'reviewed_visual_transcript'})

    for code,label,page in config['specs']:
        pattern=r'^[ \t]*'+re.escape(label)+r'\s+'+r'\s+'.join([number]*6)+r'[ \t]*$'
        matches=list(re.finditer(pattern,text[page],re.MULTILINE))
        if len(matches)!=1:raise ValueError('One complete six-cell reviewed fiscal row is required: '+code)
        match=matches[0];record(code,float(match[index].replace(',','')),match[0],page)

    def debt(code,page,pattern,section=None):
        matches=list(re.finditer(pattern,short[page] if section is None else section))
        if len(matches)!=1:raise ValueError('One exact year-end whole-region debt statement is required: '+code)
        match=matches[0];record(code,float(match[1].replace(',','')),match[0],page,'official')

    if profile=='guangxi_2026_reviewed_visual' and period=='2024':
        matches=list(re.finditer(r'^截至2024年底地方政府债务余额[ \t]+'+number+r'[ \t]*$',text[6],re.MULTILINE))
        if len(matches)!=1:raise ValueError('Preserve the year-end debt table cell boundary before the next year row.')
        match=matches[0];record('debt_outstanding',float(match[1].replace(',','')),match[0],6,'official')
    if period=='2025':
        if profile=='guangxi_2026_reviewed_visual':
            start=short[7].find('2025年全区政府债务余额为')
            end=short[7].find('2025年自治区本级政府债务余额',start)
            if not 0<=start<end:raise ValueError('Keep full-region and region-own debt paragraphs separate.')
            section=short[7][start:end]
            debt('debt_outstanding',7,r'2025年全区政府债务余额为'+number+'亿元',section)
            debt('general_debt_outstanding',7,r'一般债务余额'+number+'亿元',section)
            debt('special_debt_outstanding',7,r'专项债务余额'+number+'亿元',section)
        elif profile=='anhui_2026_reviewed_visual':
            debt('debt_outstanding',6,r'截至2025年末,安徽省政府债务余额'+number+'亿元')
            debt('general_debt_outstanding',6,r'一般债务余额'+number+'亿元')
            debt('special_debt_outstanding',6,r'专项债务余额'+number+'亿元')
        elif profile=='chongqing_2026_reviewed_visual':
            debt('debt_outstanding',9,r'2025年底,全市政府债务余额为'+number+'亿元')
        else:
            debt('debt_outstanding',8,r'截至2025年底,全省政府债务余额'+number+'亿元')
            debt('general_debt_outstanding',8,r'一般债务余额'+number+'亿元')
            debt('special_debt_outstanding',8,r'专项债务余额'+number+'亿元')
    values={r['indicator_code']:r['value'] for r in rows}
    if values.get('land_transfer_revenue',0)>values['gov_fund_revenue']:
        raise ValueError('Land revenue exceeds its same-source government-fund parent.')
    if 'special_debt_outstanding' in values and not math.isclose(values['debt_outstanding'],values['general_debt_outstanding']+values['special_debt_outstanding'],abs_tol=.021,rel_tol=0):
        raise ValueError('Same-source debt components do not reconcile within printed rounding.')
    return rows
