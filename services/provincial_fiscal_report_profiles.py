"""Fail-closed profiles for inspected full-province fiscal report sections."""
import math
import re

from bs4 import BeautifulSoup

from services.regional_fiscal_service import CN_PROVINCES, _normalise_pdf_text
from services.provincial_fiscal_six_profiles import SIX_TEXT_PROFILES, parse_six_province_text_pages


def _amount(section, pattern, code):
    matches = list(re.finditer(pattern + r'(?P<value>[\d,]+(?:\.\d+)?)亿元', section))
    if len(matches) != 1:
        raise ValueError(f'One directly disclosed full-province amount is required: {code}.')
    match = matches[0]
    return float(match['value'].replace(',', '')), match[0]


def _row(province, year, code, value, evidence, status, page=None):
    row = {'country_code': 'CN', 'government_scope': 'province_total',
           'region_code': CN_PROVINCES[province], 'region_name': province,
           'indicator_code': code, 'period': str(year), 'value': value,
           'unit': '亿元', 'frequency': 'annual', 'period_type': 'calendar_year',
           'data_status': status, 'evidence': evidence}
    if page is not None:
        row['evidence_page'] = page
    return row


def parse_hunan_final_report(html, province, period, profile):
    """Read only the annual final-accounts chapter, not next-year H1 execution."""
    year = str(period)
    if province != '湖南' or year not in ('2023', '2024', '2025') or profile != 'hunan_annual_final_report':
        raise ValueError('Use a reviewed Hunan final-report province/year identity.')
    soup = BeautifulSoup(html, 'html.parser')
    title = _normalise_pdf_text(soup.title.get_text() if soup.title else '')
    if f'湖南省{year}年省级决算草案和{int(year)+1}年上半年预算执行情况的报告' not in title:
        raise ValueError('The final-report title and both reporting years must match.')
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = _normalise_pdf_text(soup.get_text(' ', strip=True))
    start = text.find(f'一、{year}年全省及省级财政决算情况')
    end = text.find(f'二、{year}年预算执行效果', start + 1)
    if start < 0 or end <= start:
        raise ValueError('Annual final-accounts chapter boundaries are required.')
    actual = text[start:end]
    fund_heading = '2.政府性基金预算' if year == '2025' else '(二)政府性基金预算收支决算情况'
    capital_heading = '3.国有资本经营预算' if year == '2025' else '(三)国有资本经营预算收支决算情况'
    fund_start, fund_end = actual.find(fund_heading), actual.find(capital_heading)
    if not 0 <= fund_start < fund_end:
        raise ValueError('Government-fund and state-capital subsection boundaries are required.')
    fund = actual[fund_start:fund_end]
    own_start = fund.find('省级收入')
    if own_start < 0:
        raise ValueError('The province-own boundary must be explicit.')
    full_province = fund[:own_start]
    # Own-source revenue and budget expenditure exclude debt, transfers and carryovers.
    specs = [('gov_fund_revenue', full_province, r'全省收入'),
             ('gov_fund_expenditure', full_province, r'[;。]支出')]
    debt_heading = '9.地方政府债务情况' if year == '2025' else '(五)地方政府债务情况'
    debt_start = actual.find(debt_heading)
    if debt_start < fund_end:
        raise ValueError('The annual government-debt subsection is required.')
    debt = actual[debt_start:]
    if year == '2023':
        if '2023年,全省发行新增债券' not in debt:
            raise ValueError('The 2023 debt paragraph must explicitly describe the full province.')
        debt_pattern = r'年底政府债务余额'
    elif year == '2024':
        debt_pattern = r'截至2024年底,全省政府债务余额'
    else:
        debt_pattern = r'截至2025年底,全省法定债务余额'
    specs.append(('debt_outstanding', debt, debt_pattern))
    return [_row(province, year, code, *_amount(section, pattern, code), 'official_final')
            for code, section, pattern in specs]


JIANGSU_GAZETTE_PROFILES = {
    'jiangsu_2026_gazette_execution': {123, 124},
    'jiangsu_2026_gazette_final_debt': {712, 713},
}


def parse_jiangsu_gazette_pages(page_texts, province, period, profile):
    """Read the inspected physical pages, keeping execution and final vintages separate."""
    if (province != '江苏' or str(period) != '2025' or profile not in JIANGSU_GAZETTE_PROFILES
            or set(page_texts) != JIANGSU_GAZETTE_PROFILES[profile]):
        raise ValueError('Exact reviewed Jiangsu province, year, profile and physical pages are required.')
    pages = {n: _normalise_pdf_text(t) for n, t in page_texts.items()}
    header = '江苏省人民代表大会常务委员会公报2026·'
    if not all(header in t for t in pages.values()):
        raise ValueError('Each page must belong to the official Jiangsu gazette.')
    rows = []
    if profile == 'jiangsu_2026_gazette_execution':
        if ('关于江苏省2025年预算执行情况与2026年预算草案的报告' not in pages[123]
                or '2026年2月3日' not in pages[123]
                or '一、2025年预算执行顶压前行、稳中有进' not in pages[123]):
            raise ValueError('The execution report identity, date and actual-year chapter must match.')
        fund = pages[124]
        start = fund.find('(二)政府性基金预算执行情况。')
        end = fund.find('省级政府性基金预算收入', start + 1)
        if not 0 <= start < end:
            raise ValueError('The full-province fund paragraph must precede province-own amounts.')
        fund = fund[start:end]
        specs = [('gov_fund_revenue', r'全省政府性基金预算收入'),
                 ('land_transfer_revenue', r'其中国有土地使用权出让收入'),
                 ('gov_fund_expenditure', r'政府性基金预算支出')]
        for code, pattern in specs:
            rows.append(_row(province, period, code, *_amount(fund, pattern, code),
                             'official_preliminary', 124))
        values = {r['indicator_code']: r['value'] for r in rows}
        if values['land_transfer_revenue'] > values['gov_fund_revenue']:
            raise ValueError('Land-transfer revenue cannot exceed same-report fund revenue.')
    else:
        if ('关于江苏省2025年省级财政决算草案及2026年上半年预算执行情况的报告' not in pages[712]
                or '2026年7月30日' not in pages[712]
                or '一、2025年省级财政决算情况' not in pages[712]):
            raise ValueError('The final-report identity, date and annual chapter must match.')
        text = pages[713]
        start, end = text.find('(五)经批准举借政府债务情况'), text.find('(六)部门决算')
        if not 0 <= start < end:
            raise ValueError('The inspected final government-debt section is required.')
        debt = text[start:end].split('省本级政府债务余额')[0]
        specs = [('debt_outstanding', r'2025年末,全省政府债务余额'),
                 ('general_debt_outstanding', r'其中,一般债务'),
                 ('special_debt_outstanding', r'、专项债务')]
        for code, pattern in specs:
            rows.append(_row(province, period, code, *_amount(debt, pattern, code),
                             'official_final', 713))
        values = {r['indicator_code']: r['value'] for r in rows}
        if not math.isclose(values['general_debt_outstanding'] + values['special_debt_outstanding'],
                            values['debt_outstanding'], rel_tol=0, abs_tol=0.011):
            raise ValueError('Disclosed final general and special debt must reconcile with total debt.')
    return rows


PROVINCIAL_ANNEX_PROFILES = {'hubei_2026_fiscal_annex', 'zhejiang_2024_execution_pdf',
                           'liaoning_2025_final_report_pdf'}
PROVINCIAL_ANNEX_PROFILES.update(SIX_TEXT_PROFILES)


def _table_values(text, label, next_label, count=6):
    """Keep distinct cells; removing whitespace would concatenate amounts."""
    spaced = lambda value: r'\s*'.join(re.escape(char) for char in value)
    matches = list(re.finditer(spaced(label)+r'\s+(.*?)\s+'+spaced(next_label), text, re.S))
    if len(matches) != 1:
        raise ValueError('One fiscal table row is required: '+label)
    cells = matches[0][1].split()
    if len(cells) != count or not all(re.fullmatch(r'\d[\d,]*(?:\.\d+)?', cell) for cell in cells):
        raise ValueError(f'{count} explicit fiscal table cells are required: '+label)
    return [float(cell.replace(',', '')) for cell in cells], label+' '+matches[0][1]


def parse_provincial_fiscal_annex_pages(page_texts, province, period, profile):
    """Read inspected fiscal tables/sections without importing budget columns."""
    if profile in SIX_TEXT_PROFILES:
        return parse_six_province_text_pages(page_texts, province, period, profile)
    year = str(period)
    if profile=='liaoning_2025_final_report_pdf':
        if province!='辽宁' or year!='2025' or set(page_texts)!={1,2,7}:
            raise ValueError('Exact Liaoning final-report identity and pages are required.')
        pages={n:_normalise_pdf_text(t) for n,t in page_texts.items()}
        if ('关于辽宁省2025年财政决算的报告' not in pages[1]
                or '一、2025年财政决算情况(一)全省财政决算情况' not in pages[1]
                or '省财政厅厅长' not in pages[1]):
            raise ValueError('The annual full-province final-account chapter must match.')
        text=pages[7];start=text.find('全省政府债务余额');end=text.find('全省(不含大连)',start+1)
        if ('2025年地方政府债务限额' not in text or not 0<=start<end):
            raise ValueError('Keep province-total and excluding-Dalian debt paragraphs separate.')
        debt=text[start:end]
        specs=[('general_budget_revenue',pages[1],r'全省一般公共预算收入',1),
               ('tax_revenue',pages[1],r'其中:税收收入',1),
               ('general_budget_expenditure',pages[2],r'全省一般公共预算支出',2),
               ('gov_fund_revenue',pages[2],r'全省政府性基金预算收入',2),
               ('gov_fund_expenditure',pages[2],r'全省政府性基金预算支出',2),
               ('debt_outstanding',debt,r'全省政府债务余额',7),
               ('general_debt_outstanding',debt,r'其中:一般债务',7),
               ('special_debt_outstanding',debt,r'专项债务',7)]
        rows=[_row(province,year,code,*_amount(section,pattern,code),'official_final',page)
              for code,section,pattern,page in specs]
        values={r['indicator_code']:r['value'] for r in rows}
        if (values['tax_revenue']>values['general_budget_revenue'] or
                not math.isclose(values['general_debt_outstanding']+values['special_debt_outstanding'],
                                 values['debt_outstanding'],rel_tol=0,abs_tol=.11)):
            raise ValueError('Same-report tax/debt components do not reconcile.')
        return rows
    if profile == 'hubei_2026_fiscal_annex':
        if province != '湖北' or year not in ('2024', '2025') or set(page_texts) != {1, 2}:
            raise ValueError('Only inspected Hubei2024 final/2025 execution columns are supported.')
        identity, text = (_normalise_pdf_text(page_texts[n]) for n in (1, 2))
        required = ['二、财政收支状况(亿元)',
                    '2024年2025年2026年省本级全省省本级全省省本级全省',
                    '2024年数据为决算数',
                    '2025年和2026年数据来源于《湖北省2025年预算执行情况和2026年预算(草案)》',
                    '六项数据不包含债券收支数和转移性收支数']
        if ('湖北省(区、市)经济、财政和债务有关数据' not in identity
                or any(part not in text for part in required)):
            raise ValueError('Hubei identity, currency unit, scope columns and actual/budget footnotes must match.')
        column = {'2024': 1, '2025': 3}[year]
        status = 'official_final' if year == '2024' else 'official_preliminary'
        specs = [('general_budget_revenue', '一般公共预算收入', '一般公共预算支出'),
                 ('general_budget_expenditure', '一般公共预算支出', '地方政府一般债券收入'),
                 ('gov_fund_revenue', '政府性基金收入', '政府性基金支出'),
                 ('gov_fund_expenditure', '政府性基金支出', '地方政府专项债券收入')]
        rows = []
        for code, label, next_label in specs:
            values, evidence = _table_values(page_texts[2], label, next_label)
            rows.append(_row(province, year, code, values[column], evidence, status, 2))
        if year == '2025':
            amounts, evidence = _table_values(page_texts[2], '截至2025年底地方政府债务余额',
                                              '2024年地方政府债务限额', count=1)
            rows.append(_row(province, year, 'debt_outstanding', amounts[0], evidence, status, 2))
        return rows
    if profile != 'zhejiang_2024_execution_pdf' or province != '浙江' or year != '2024' or set(page_texts) != {1, 2, 3}:
        raise ValueError('Use the exact inspected Zhejiang execution-report identity and pages.')
    pages = {n: _normalise_pdf_text(t) for n, t in page_texts.items()}
    if ('关于2024年全省和省级预算执行情况及2025年全省和省级预算草案的报告' not in pages[1]
            or '2025年1月14日' not in pages[1] or '浙江省财政厅' not in pages[1]
            or '一、2024年预算执行情况' not in pages[1]):
        raise ValueError('The official reporting title/date and actual-year chapter must match.')
    general = pages[2].split('(2)省级')[0]
    fund = pages[3]
    start, end = fund.find('2.政府性基金预算执行情况(1)全省'), fund.find('(2)省级')
    if '(一)2024年预算收支执行情况1.一般公共预算执行情况(1)全省' not in general or not 0 <= start < end:
        raise ValueError('Full-province general and fund boundaries must be explicit.')
    specs = [('general_budget_revenue', general, r'2024年全省一般公共预算收入', 2),
             ('tax_revenue', general, r'其中,税收收入', 2),
             ('general_budget_expenditure', general, r'全省一般公共预算支出', 2),
             ('gov_fund_revenue', fund[start:end], r'2024年全省政府性基金预算收入', 3),
             ('gov_fund_expenditure', fund[start:end], r'全省政府性基金预算支出', 3)]
    rows = [_row(province, year, code, *_amount(section, pattern, code), 'official_preliminary', page)
            for code, section, pattern, page in specs]
    values = {r['indicator_code']:r['value'] for r in rows}
    if values['tax_revenue'] > values['general_budget_revenue']:
        raise ValueError('Local-budget tax cannot exceed its same-report parent.')
    return rows
