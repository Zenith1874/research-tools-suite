"""Exact visual-transcript profiles for the five inspected official issuer files."""
import math
import re
import unicodedata


FIVE_VISUAL_PROFILES = {
    'beijing_2026_fiscal_visual': {
        'province':'北京','region_code':'110000','pages':{1,2},'fiscal_pages':(2,),
        'years':('2024','2025','2026'),'actual_years':('2024','2025'),
        'header':'市本级全市市本级全市市本级全市','fund_page':2,
        'title':'北京市经济、财政和债务有关数据','issuer':'北京市财政局',
        'fiscal_status':{'2024':'official_final','2025':'official_final'},
    },
    'hebei_2026_fiscal_visual': {
        'province':'河北','region_code':'130000','pages':{1,2,3},'fiscal_pages':(2,3),
        'years':('2023','2024','2025'),'actual_years':('2023','2024','2025'),
        'header':'省本级全省省本级全省省本级全省','fund_page':3,
        'title':'河北省经济、财政和债务有关数据','issuer':'河北省财政厅',
        'allow_text_layer_pages':{1},
        'fiscal_status':dict.fromkeys(('2023','2024','2025'),'official'),
    },
    'shanxi_2026_fiscal_visual': {
        'province':'山西','region_code':'140000','pages':{1,8,11,12,13},'fiscal_pages':(12,13),
        'years':('2024','2025','2026'),'actual_years':('2024','2025'),
        'header':'省本级全省省本级全省省本级全省','fund_page':13,
        'title':'2026年山西省政府专项债券(四十四至四十九期)信息披露文件',
        'issuer':'山西省财政厅','signature_page':11,'signature_date':'2026年9月22日',
        'fiscal_status':{'2024':'official_final','2025':'official_final'},
    },
    'liaoning_2026_fiscal_visual': {
        'province':'辽宁','region_code':'210000','pages':{1,4,5,8},'fiscal_pages':(4,5),
        'years':('2022','2023','2024'),'actual_years':('2022','2023','2024'),
        'header':'省本级全省省本级全省省本级全省','fund_page':5,
        'title':'2026年辽宁省地方政府再融资专项债券(十一期)信息披露文件',
        'issuer':'辽宁省财政厅','signature_page':8,'signature_date':'2026年8月7日',
        'fiscal_status':dict.fromkeys(('2022','2023','2024'),'official_final'),
    },
    'tianjin_2026_debt_visual': {
        'province':'天津','region_code':'120000','pages':{1,5,6,8},'fiscal_pages':(),
        'actual_years':('2025',),'title':'2026年第六批天津市政府债券信息披露文件',
        'issuer':'天津市财政局','signature_page':8,'signature_date':'2026年7月27日',
        'fiscal_status':{'2025':'official'},
    },
}

FIVE_APPROVED_VISUAL_FILINGS = {
 'https://www.governbond.org.cn/uploadFiles/11/attachFiles/202609/80c19e2b-b334-46c8-b715-97168a6aa0b8.pdf':{
  'region_code':'110000','region_name':'北京','source_name':'北京市财政局（财政部地方债平台原始附件）',
  'source_title':'北京市经济、财政和债务有关数据','source_class':'official_platform_document',
  'raw_sha256':'b8c1108bb12b4fae9c2b61c029f602ff021c7a36fc208bb80d03119bdd895682',
  'transcript_sha256':'28b0404180d305b43eec2a55cc1d5993dbc1a60fb57d4642059f850595ec6ab2',
  'page_by_code':{'gov_fund_revenue':2,'gov_fund_expenditure':2,'debt_outstanding':{'2025':2}},
  'fiscal_status':{'2024':'official_final','2025':'official_final'},'debt_status':{'2025':'official_final'}},
 'https://www.governbond.org.cn/uploadFiles/13/attachFiles/202609/ae060c7a-1b61-4dca-801e-1ddfd4a1c570.pdf':{
  'region_code':'130000','region_name':'河北','source_name':'河北省财政厅（财政部地方债平台原始附件）',
  'source_title':'河北省经济、财政和债务有关数据','source_class':'official_platform_document',
  'raw_sha256':'08f245f509bbdd9006ea2ee857d6b02ae70b9b0e187c77e260d718ef8fad6fb2',
  'transcript_sha256':'43dc5700485f30a5dc4154b4fc453bf4e9bd4a308d50cc4c6bf1ec68d8ad9bd8',
  'page_by_code':{'gov_fund_revenue':3,'gov_fund_expenditure':3,'debt_outstanding':{'2025':3}},
  'fiscal_status':{'2023':'official','2024':'official','2025':'official'}},
 'https://www.governbond.org.cn/uploadFiles/14/attachFiles/202609/47050154-cd87-4b88-babf-ed9d11707969.pdf':{
  'region_code':'140000','region_name':'山西','source_name':'山西省财政厅（财政部地方债平台原始披露）',
  'source_title':'2026年山西省政府专项债券（四十四至四十九期）信息披露文件','source_class':'official_platform_document',
  'raw_sha256':'a889f3433cb0d1f9e0a65f051280283922385af03f0585b52deb487d3fcf7110',
  'transcript_sha256':'74edda2b4421d9a6c4ec9064562a29b91ee8cfd234a12291fbc43b7d45829cd1',
  'page_by_code':{'gov_fund_revenue':13,'gov_fund_expenditure':13,'debt_outstanding':{'2025':8},
                  'general_debt_outstanding':{'2025':8},'special_debt_outstanding':{'2025':8}},
  'fiscal_status':{'2024':'official_final','2025':'official_final'},'debt_status':{'2025':'official_final'}},
 'https://www.governbond.org.cn/uploadFiles/21/attachFiles/202608/d75e0dad-64c3-440c-a088-393b969b7e8e.pdf':{
  'region_code':'210000','region_name':'辽宁','source_name':'辽宁省财政厅（财政部地方债平台原始披露）',
  'source_title':'2026年辽宁省地方政府再融资专项债券（十一期）信息披露文件','source_class':'official_platform_document',
  'raw_sha256':'03d3adccdc025083d3869978a552ad3e88d8594bea87ad172bb690b311a5849b',
  'transcript_sha256':'d12dd185ac07faf9abeb8e410e55c89ca27f18fb96775a6565448272a280961a',
  'page_by_code':{'gov_fund_revenue':5,'gov_fund_expenditure':5},
  'fiscal_status':{'2022':'official_final','2023':'official_final','2024':'official_final'}},
 'https://www.governbond.org.cn/uploadFiles/12/attachFiles/202607/9244984c-8679-4aab-81c6-92df0eb4d705.pdf':{
  'region_code':'120000','region_name':'天津','source_name':'天津市财政局（财政部地方债平台原始披露）',
  'source_title':'2026年第六批天津市政府债券信息披露文件','source_class':'official_platform_document',
  'raw_sha256':'ecb03874cc2e093711a6371dd39301a12b03857ec17cb3e347a1f30fbdcb84ee',
  'transcript_sha256':'fea26f526653f2ad2474ea1c9ee476a265c98893f3dae88ab2dd961b80d1eb3e',
  'page_by_code':{'debt_outstanding':6},'fiscal_status':{'2025':'official'}},
}


def _compact(value):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',value or ''))


def parse_five_province_visual_pages(page_texts, province, period, profile):
    """Interpret labelled excerpts only after the caller verifies PDF/render hashes."""
    config=FIVE_VISUAL_PROFILES.get(profile);period=str(period)
    if (not config or province!=config['province'] or period not in config['actual_years']
            or set(page_texts)!=config['pages']):
        raise ValueError('Use the exact reviewed province, actual year and physical-page set.')
    text={n:unicodedata.normalize('NFKC',t or '') for n,t in page_texts.items()}
    short={n:_compact(t) for n,t in text.items()}
    if config['title'] not in short[1] or '信用评级报告' in short[1]:
        raise ValueError('Primary issuer/annex identity changed.')
    signature=config.get('signature_page',1)
    if config['issuer']+config.get('signature_date','') not in short[signature]:
        raise ValueError('The inspected issuer seal/signature identity changed.')
    rows=[]

    def record(code,value,evidence,page,status=None):
        if not math.isfinite(value) or value<0:
            raise ValueError('Only nonnegative disclosed full-province amounts are observations.')
        rows.append({'country_code':'CN','government_scope':'province_total','region_code':config['region_code'],
                     'region_name':province,'indicator_code':code,'period':period,'value':value,'unit':'亿元',
                     'frequency':'annual','period_type':'calendar_year','data_status':status or config['fiscal_status'][period],
                     'evidence':evidence,'evidence_page':page,'raw_unit':'亿元',
                     'unit_source':'explicit_source_heading','parse_mode':'reviewed_visual_transcript'})

    def amount(code,page,pattern,status=None,cell=False):
        body=text[page] if cell else short[page]
        matches=list(re.finditer(pattern,body,re.MULTILINE))
        if len(matches)!=1:raise ValueError('One exact whole-province amount is required: '+code)
        record(code,float(matches[0][1].replace(',','')),matches[0][0],page,status)

    number=r'(-?[\d,]+(?:\.\d+)?)'
    if profile=='tianjin_2026_debt_visual':
        if '全市政府性基金总收入' not in short[6] or '市本级债务' not in short[6] or '区级债务' not in short[6]:
            raise ValueError('Keep fund totals and government-level debt components explicitly distinguished.')
        # Neither total fund receipts nor city-own debt is an own-revenue/general-debt observation.
        amount('debt_outstanding',6,r'截至2025年末,天津市政府债务余额'+number+'亿元')
        return rows
    combined=''.join(short[n] for n in config['fiscal_pages'])
    if ('财政收支状况(亿元)' not in combined
            or ''.join(y+'年' for y in config['years']) not in combined
            or config['header'] not in combined):
        raise ValueError('The actual fiscal years, printed currency unit and full-province columns must match.')
    if profile in ('beijing_2026_fiscal_visual','shanxi_2026_fiscal_visual'):
        if not re.search(r'2024(?:年)?、2025年(?:数据)?按决算口径公布',combined) or '2026年数据按' not in combined:
            raise ValueError('Actual final-account and future-budget vintages must be explicit.')
    if profile=='liaoning_2026_fiscal_visual':
        if ('2022-2024年数据按决算口径公布' not in combined
                or '辽宁省非债务类数据包含大连市,债务类数据不包含大连市' not in combined):
            raise ValueError('Liaoning fiscal/debt Dalian coverage and final vintages must remain explicit.')
    index=2*config['years'].index(period)+2;page=config['fund_page']
    for code,label in [('gov_fund_revenue','政府性基金收入'),('gov_fund_expenditure','政府性基金支出')]:
        matches=list(re.finditer(r'^[ \t]*'+label+r'\s+'+r'\s+'.join([number]*6)+r'[ \t]*$',text[page],re.MULTILINE))
        if len(matches)!=1:raise ValueError('One complete six-cell fiscal row is required: '+code)
        match=matches[0];record(code,float(match[index].replace(',','')),match[0],page)
    if period=='2025':
        if profile=='beijing_2026_fiscal_visual':
            amount('debt_outstanding',2,r'^截至2025年底地方政府债务余额[ \t]+'+number+r'[ \t]*$',cell=True)
        elif profile=='hebei_2026_fiscal_visual':
            amount('debt_outstanding',3,r'^截至2025年底地方政府债务余额[ \t]+'+number+r'[ \t]*$',cell=True)
        elif profile=='shanxi_2026_fiscal_visual':
            for code,pattern in [('debt_outstanding',r'2025年底山西省政府债务余额'),
                                 ('general_debt_outstanding',r'其中,一般债务'),
                                 ('special_debt_outstanding',r'专项债务')]:
                amount(code,8,pattern+number+'亿元')
            values={r['indicator_code']:r['value'] for r in rows}
            if not math.isclose(values['general_debt_outstanding']+values['special_debt_outstanding'],
                                values['debt_outstanding'],abs_tol=.011,rel_tol=0):
                raise ValueError('Same-source general and special debt do not reconcile.')
    return rows
