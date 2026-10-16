"""Fail-closed parsers for the selected 2026-10-15 provincial source cohort.

Visual excerpts are not OCR. Their original PDF, selected render and transcript
hashes are verified by the existing review runner before these functions run.
"""
import math
import re
import unicodedata


SIX_VISUAL_PROFILES = {
    'jilin_2026_fiscal_visual': {
        'province': '吉林', 'region_code': '220000', 'pages': {1, 8, 10, 13},
        'fiscal_page': 13, 'years': ('2024', '2025', '2026'),
        'actual_years': ('2024', '2025'),
        'title': '2026年第七批吉林省政府债券信息披露文件',
        'issuer': '吉林省财政厅', 'signature_page': 10, 'signature_date': '2026年9月1日',
        'fiscal_status': {'2024': 'official_final', '2025': 'official_final'},
    },
    'heilongjiang_2026_fiscal_visual': {
        'province': '黑龙江', 'region_code': '230000', 'pages': {1, 8, 9, 11},
        'fiscal_page': 8, 'years': ('2023', '2024', '2025'),
        'actual_years': ('2023', '2024'),
        'title': '2026年黑龙江省政府再融资专项债券(五期至六期)信息披露文件',
        'issuer': '黑龙江省财政厅', 'signature_page': 11, 'signature_date': '2026年10月15日',
        'fiscal_status': {'2023': 'official_final', '2024': 'official_final'},
    },
    'henan_2026_fiscal_visual': {
        'province': '河南', 'region_code': '410000', 'pages': {1, 6, 7, 9, 11},
        'fiscal_page': 11, 'years': ('2023', '2024', '2025'),
        'actual_years': ('2023', '2024', '2025'),
        'title': '2026年河南省政府一般债券(十二期)、专项债券(六十四至七十四期)信息披露文件',
        'issuer': '河南省财政厅', 'signature_page': 9, 'signature_date': '2026年9月16日',
        'fiscal_status': {'2023': 'official_final', '2024': 'official_final', '2025': 'official_preliminary'},
    },
    'guangdong_2026_fiscal_visual': {
        'province': '广东', 'region_code': '440000', 'pages': {1, 5, 9},
        'fiscal_page': 5, 'years': ('2024', '2025', '2026'),
        'actual_years': ('2024', '2025'),
        'title': '2026年广东省政府一般债券(八期)和专项债券(四十期)信息披露文件',
        'issuer': '广东省财政厅', 'signature_page': 9, 'signature_date': '2026年9月16日',
        # The original table's text layer splits digits into individual glyphs.
        # Explicitly reviewed visual excerpts remain bound to the real page pixels.
        'allow_text_layer_pages': {1, 5, 9},
        'fiscal_status': {'2024': 'official_preliminary', '2025': 'official_preliminary'},
    },
}

SIX_TEXT_PROFILES = {'shandong_2026_issuer_text', 'heilongjiang_2025_final_book'}

SIX_APPROVED_VISUAL_FILINGS = {
    'https://www.governbond.org.cn/uploadFiles/22/attachFiles/202609/f552e29c-165f-41ce-896b-172fca6d834e.pdf': {
        'region_code': '220000', 'region_name': '吉林',
        'source_name': '吉林省财政厅（财政部地方债平台原始披露）',
        'source_title': '2026年第七批吉林省政府债券信息披露文件',
        'source_class': 'official_platform_document',
        'raw_sha256': 'c03026df957a6036936f16bbd5b5ae39e330415760758aee059bcbf578e63dce',
        'transcript_sha256': '5a3de01212a44f03b10f9ec00c6b00cb7b31c4426e22ce52eec0b7af5544ace7',
        'page_by_code': {'gov_fund_revenue': 13, 'gov_fund_expenditure': 13,
                         'debt_outstanding': {'2025': 8}, 'general_debt_outstanding': {'2025': 8},
                         'special_debt_outstanding': {'2025': 8}},
        'fiscal_status': {'2024': 'official_final', '2025': 'official_final'},
        'debt_status': {'2025': 'official_final'},
    },
    'https://www.governbond.org.cn/uploadFiles/23/attachFiles/202610/c1e4f5df-60e0-498c-a6e4-2f5024fc613a.pdf': {
        'region_code': '230000', 'region_name': '黑龙江',
        'source_name': '黑龙江省财政厅（财政部地方债平台原始披露）',
        'source_title': '2026年黑龙江省政府再融资专项债券（五期至六期）信息披露文件',
        'source_class': 'official_platform_document',
        'raw_sha256': '78f0889c4ad607667bc730fbe5301168e2df5c57abf9f55140399c0ba920a9da',
        'transcript_sha256': '0248e90b2f7d315c60689c2e37962f5305987740a960d2bbd46b8c9dfea921c1',
        'page_by_code': {'gov_fund_revenue': 8, 'gov_fund_expenditure': 8, 'land_transfer_revenue': 8},
        'fiscal_status': {'2023': 'official_final', '2024': 'official_final'},
    },
    'https://www.governbond.org.cn/uploadFiles/41/attachFiles/202609/d2a0bb1b-d903-444e-80a7-0c1c727fbdfe.pdf': {
        'region_code': '410000', 'region_name': '河南',
        'source_name': '河南省财政厅（财政部地方债平台原始披露）',
        'source_title': '2026年河南省政府一般债券（十二期）、专项债券（六十四至七十四期）信息披露文件',
        'source_class': 'official_platform_document',
        'raw_sha256': 'd9d330af20737cc39cbdc63bcc3b556834cd79d1d78ac3c81187bbd0e449c53a',
        'transcript_sha256': '47ca7d6417df98e5bbccc5b6c158bb5d46423d846296f5745c661511e499b79f',
        'page_by_code': {'gov_fund_revenue': 11, 'gov_fund_expenditure': 11, 'land_transfer_revenue': 6,
                         'debt_outstanding': {'2025': 7}, 'general_debt_outstanding': {'2025': 7},
                         'special_debt_outstanding': {'2025': 7}},
        'fiscal_status': {'2023': 'official_final', '2024': 'official_final', '2025': 'official_preliminary'},
        'debt_status': {'2025': 'official'},
    },
    'https://www.governbond.org.cn/uploadFiles/44/attachFiles/202609/7ebf04ba-2f44-441f-9dd0-bed3053f8eb8.pdf': {
        'region_code': '440000', 'region_name': '广东',
        'source_name': '广东省财政厅（财政部地方债平台原始披露）',
        'source_title': '2026年广东省政府一般债券（八期）和专项债券（四十期）信息披露文件',
        'source_class': 'official_platform_document',
        'raw_sha256': 'bb1bd32626f87c155e613a70e092b088925580d2161f81a16157c9abaafa98a2',
        'transcript_sha256': '15ed1f26d64dd72e6fc705aa9170a83d49e88c0b5a9467a90f8f4cb1c8dfe259',
        'page_by_code': {'gov_fund_revenue': 5, 'gov_fund_expenditure': 5,
                         'land_transfer_revenue': 5, 'debt_outstanding': 5},
        'fiscal_status': {'2024': 'official_preliminary', '2025': 'official_preliminary'},
        'debt_status': {'2024': 'official_final', '2025': 'official_final'},
    },
}

SIX_APPROVED_TEXT_FILINGS = {
    'https://www.governbond.org.cn/uploadFiles/37/attachFiles/202609/3a8e04f3-5529-4b5a-8e42-75cb166122c3.pdf': {
        'region_code': '370000', 'region_name': '山东',
        'source_name': '山东省财政厅（财政部地方债平台原始披露）',
        'source_title': '2026年山东省地方政府再融资专项债券（四十期）信息披露文件',
        'source_class': 'official_platform_document',
        'raw_sha256': 'f1b47c715c060ed65fb564f0616105b41b5eca6ca662a6fe09cea3a60c0fe8fd',
        'page_by_code': {'gov_fund_revenue': 4, 'gov_fund_expenditure': 4,
                         'land_transfer_revenue': 5, 'debt_outstanding': {'2025': 5}},
        'fiscal_status': dict.fromkeys(('2023', '2024', '2025'), 'official_final'),
    },
}


def _compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text or ''))


def _record(province, region_code, year, code, value, evidence, page, status, raw_unit='亿元', visual=False):
    if not math.isfinite(value) or value < 0:
        raise ValueError('Only nonnegative directly disclosed province-total amounts are eligible.')
    row = {'country_code': 'CN', 'government_scope': 'province_total',
           'region_name': province, 'region_code': region_code, 'period': year,
           'indicator_code': code, 'value': value, 'unit': '亿元', 'frequency': 'annual',
           'period_type': 'calendar_year', 'data_status': status,
           'evidence': evidence, 'evidence_page': page, 'raw_unit': raw_unit,
           'unit_source': 'explicit_source_heading'}
    if visual:
        row['parse_mode'] = 'reviewed_visual_transcript'
    return row


def _cells(text, label, count):
    """Match a labelled row without collapsing whitespace between distinct cells."""
    number = r'(-?\d[\d,]*(?:\.\d+)?)'
    pattern = r'^[ \t]*' + re.escape(label) + r'[ \t]+' + r'[ \t]+'.join([number] * count) + r'[ \t]*$'
    matches = list(re.finditer(pattern, unicodedata.normalize('NFKC', text), re.M))
    if len(matches) != 1:
        raise ValueError('One complete row of explicit numeric cells is required: ' + label)
    return [float(v.replace(',', '')) for v in matches[0].groups()], matches[0][0]


def _amount(text, pattern):
    matches = list(re.finditer(pattern + r'([\d,]+(?:\.\d+)?)亿元', _compact(text)))
    if len(matches) != 1:
        raise ValueError('One directly disclosed amount with its printed unit is required.')
    return float(matches[0][1].replace(',', '')), matches[0][0]


def parse_six_province_visual_pages(page_texts, province, period, profile):
    config = SIX_VISUAL_PROFILES.get(profile)
    year = str(period)
    if (not config or province != config['province'] or year not in config['actual_years']
            or set(page_texts) != config['pages']):
        raise ValueError('Use the exact selected province, actual year and physical-page set.')
    pages = {n: unicodedata.normalize('NFKC', t or '') for n, t in page_texts.items()}
    short = {n: _compact(t) for n, t in pages.items()}
    if config['title'] not in short[1] or '信用评级报告' in short[1]:
        raise ValueError('The primary issuer-document identity changed.')
    if config['issuer'] + config['signature_date'] not in short[config['signature_page']]:
        raise ValueError('The reviewed fiscal-department signature and date must match.')
    fiscal_page = config['fiscal_page']
    fiscal = short[fiscal_page]
    if (not re.search(r'财政收支(?:状况|情况)\(亿元\)', fiscal)
            or ''.join(y + '年' for y in config['years']) not in fiscal
            or '省本级全省省本级全省省本级全省' not in fiscal
            or '不含宁波' in fiscal or '不含深圳' in fiscal):
        raise ValueError('Keep literal units, actual fiscal years and full-province columns explicit.')
    if profile == 'jilin_2026_fiscal_visual':
        if ('2024年和2025年数据来源于吉林省财政总决算' not in fiscal
                or '2026年数据来源于' not in fiscal):
            raise ValueError('Jilin final accounts and the future budget must remain distinct.')
    elif profile == 'heilongjiang_2026_fiscal_visual':
        if '2023、2024、2025年财政收支状况数据均为决算数' not in fiscal:
            raise ValueError('The reviewed historical final-account note is required.')
    elif profile == 'henan_2026_fiscal_visual':
        if ('2023年、2024年按决算口径公布,2025年按预算执行口径公布' not in fiscal
                or '一般公共预算收入、政府性基金收入两项数据不包含债券数' not in fiscal):
            raise ValueError('Keep Henan actual/execution vintages and own revenue explicit.')
    else:
        if ('2024、2025年数据为执行数,2026年数据为预算数' not in fiscal
                or '以上数据均包含深圳' not in fiscal):
            raise ValueError('Guangdong execution/budget vintages and Shenzhen coverage must match.')
    index = 2 * config['years'].index(year) + 1
    rows = []

    def record(code, value, evidence, page=fiscal_page, status=None):
        rows.append(_record(province, config['region_code'], year, code, value, evidence, page,
                            status or config['fiscal_status'][year], visual=True))

    for code, label in [('gov_fund_revenue', '政府性基金收入'), ('gov_fund_expenditure', '政府性基金支出')]:
        values, evidence = _cells(pages[fiscal_page], label, 6)
        record(code, values[index], evidence)
    if profile == 'heilongjiang_2026_fiscal_visual':
        values, evidence = _cells(pages[fiscal_page], '国有土地使用权出让收入', 6)
        record('land_transfer_revenue', values[index], evidence)
    elif profile == 'henan_2026_fiscal_visual':
        value, evidence = _amount(pages[6], year + r'年,全省国有土地使用权出让收入')
        record('land_transfer_revenue', value, evidence, 6)
    elif profile == 'guangdong_2026_fiscal_visual':
        # Own-level cells are blank in the original. The labelled transcript keeps
        # each blank explicit; three unpositioned values are not accepted.
        matches = list(re.finditer(r'^国有土地使用权出让收入[ \t]+—[ \t]+([\d.]+)[ \t]+—[ \t]+([\d.]+)[ \t]+—[ \t]+([\d.]+)[ \t]*$', pages[5], re.M))
        if len(matches) != 1:
            raise ValueError('The three blank own-level land cells must remain explicitly positioned.')
        record('land_transfer_revenue', float(matches[0][config['years'].index(year) + 1]), matches[0][0])
        values, evidence = _cells(pages[5], year + '年底地方政府债务余额(决算数)', 1)
        record('debt_outstanding', values[0], evidence, status='official_final')
    if year == '2025' and profile in ('jilin_2026_fiscal_visual', 'henan_2026_fiscal_visual'):
        page = 8 if profile == 'jilin_2026_fiscal_visual' else 7
        if profile == 'jilin_2026_fiscal_visual':
            patterns = [('debt_outstanding', r'截至2025年底,吉林省政府债务余额'),
                        ('general_debt_outstanding', r'其中:一般债务余额'),
                        ('special_debt_outstanding', r'专项债务余额')]
            status = 'official_final'
        else:
            patterns = [('debt_outstanding', r'全省政府债务余额合计'),
                        ('general_debt_outstanding', r'\(一般债务'),
                        ('special_debt_outstanding', r'、专项债务')]
            # Stop before province-own / city-county amounts to avoid duplicate matches.
            pages[page] = pages[page].split('其中,省本级')[0]
            status = 'official'
        for code, pattern in patterns:
            value, evidence = _amount(pages[page], pattern)
            record(code, value, evidence, page, status)
        debt = {r['indicator_code']: r['value'] for r in rows}
        if not math.isclose(debt['general_debt_outstanding'] + debt['special_debt_outstanding'],
                            debt['debt_outstanding'], rel_tol=0, abs_tol=.11):
            raise ValueError('Same-source debt components must reconcile within printed precision.')
    values = {r['indicator_code']: r['value'] for r in rows}
    if values.get('land_transfer_revenue', 0) > values['gov_fund_revenue']:
        raise ValueError('Land revenue cannot exceed the same-source fund own revenue.')
    return rows


def parse_six_province_text_pages(page_texts, province, period, profile):
    """Parse actual text layers from only the separately inspected physical pages."""
    year = str(period)
    short = {n: _compact(t) for n, t in page_texts.items()}
    if profile == 'shandong_2026_issuer_text':
        if province != '山东' or year not in ('2023', '2024', '2025') or set(short) != {1, 4, 5, 8}:
            raise ValueError('Use the inspected Shandong actual-year pages only.')
        if ('2026年山东省地方政府再融资专项债券(四十期)信息披露文件' not in short[1]
                or '山东省财政厅2026年9月29日' not in short[8]
                or '2023—2025年山东省(含青岛市)财政收支情况(亿元)' not in short[4]
                or '全省省本级全省省本级全省省本级' not in short[4]
                or '2023年、2024年、2025年数据均为决算数' not in short[5]):
            raise ValueError('Shandong identity, full-first columns, Qingdao and final-account note must match.')
        rows = []
        for code, label, page in [('gov_fund_revenue', '政府性基金收入', 4),
                                  ('gov_fund_expenditure', '政府性基金支出', 4),
                                  ('land_transfer_revenue', '国有土地使用权出让收入', 5)]:
            cells, evidence = _cells(page_texts[page], label, 6)
            rows.append(_record(province, '370000', year, code, cells[2 * (int(year) - 2023)],
                                evidence, page, 'official_final'))
        if year == '2025':
            cells, evidence = _cells(page_texts[5], '2025年底地方政府债务余额', 1)
            rows.append(_record(province, '370000', year, 'debt_outstanding', cells[0], evidence, 5, 'official_final'))
        return rows
    if (profile != 'heilongjiang_2025_final_book' or province != '黑龙江'
            or year not in ('2024', '2025') or set(short) != {1, 10, 23, 27, 79, 80, 99}):
        raise ValueError('Use only the exact selected Heilongjiang final-book pages and years.')
    headings = {1: '2025年黑龙江省和省本级财政决算',
                23: '2.12025年黑龙江省财政收支决算总表',
                27: '2.32025年黑龙江省一般公共预算收入决算表',
                79: '2.102025年黑龙江省政府性基金预算收支总表',
                80: '2.112025年黑龙江省政府性基金预算收入决算表',
                99: '2.212025年黑龙江省地方政府债务限额和余额情况表(分地区)'}
    if any(heading not in short[n] for n, heading in headings.items()) or '2026年10月' not in short[1]:
        raise ValueError('The final-book title, annual table identities and date must match.')
    if any('单位:万元' not in short[n] for n in (23, 27, 79, 80, 99)):
        raise ValueError('Each monetary table must explicitly print its original 万元 unit.')
    if ('2024年决算数2025年决算数' not in short[23]
            or '预算数调整预算数决算数' not in short[27]
            or '预算数决算数' not in short[80]
            or '一般债务专项债务2024年末余额2025年限额2025年末余额2024年末余额2025年限额2025年末余额' not in short[99]):
        raise ValueError('Actual years, final-vs-budget columns and grouped debt headers are required.')
    rows = []

    def record(code, raw_value, evidence, page):
        rows.append(_record(province, '230000', year, code, raw_value / 10000., evidence, page,
                            'official_final', raw_unit='万元'))

    for code, label in [('gov_fund_revenue', '政府性基金预算收入'),
                        ('gov_fund_expenditure', '政府性基金预算支出')]:
        cells, evidence = _cells(page_texts[23], label, 3)
        record(code, cells[int(year) - 2024], evidence + '; 万元 ÷ 10000 = 亿元', 23)
    if year == '2024':
        return rows
    direct = re.findall(r'政府性基金收入(\d+)政府性基金支出(\d+)', _compact(page_texts[79]))
    summary = {r['indicator_code']: r['value'] for r in rows}
    if (len(direct) != 1 or not all(math.isclose(float(raw) / 10000., summary[code], rel_tol=0, abs_tol=1e-8)
                                 for raw, code in zip(direct[0], ('gov_fund_revenue', 'gov_fund_expenditure')))):
        raise ValueError('The directly labelled fund amounts must corroborate the summary, not total resources.')
    tax, evidence = _cells(page_texts[27], '一、税收收入', 5)
    record('tax_revenue', tax[2], evidence + '; 决算列，万元 ÷ 10000 = 亿元', 27)
    land, evidence = _cells(page_texts[80], '三、国有土地使用权出让收入', 4)
    record('land_transfer_revenue', land[1], evidence + '; 决算列，万元 ÷ 10000 = 亿元', 80)
    debt, evidence = _cells(page_texts[99], '全省', 6)
    record('general_debt_outstanding', debt[2], evidence + '; 一般债务2025年末余额，万元 ÷ 10000 = 亿元', 99)
    record('special_debt_outstanding', debt[5], evidence + '; 专项债务2025年末余额，万元 ÷ 10000 = 亿元', 99)
    # A directly printed total in the narrative is an observation; the component
    # sum is only a precision consistency check, never a fabricated raw total.
    start = short[10].find('截至2025年底,全省政府债务限额')
    end = short[10].find('省本级政府债务限额', start + 1)
    if not 0 <= start < end:
        raise ValueError('The full-province debt paragraph must stop before province-own values.')
    total, evidence = _amount(short[10][start:end], r'全省政府债务余额')
    rows.append(_record(province, '230000', year, 'debt_outstanding', total, evidence, 10, 'official_final'))
    values = {r['indicator_code']: r['value'] for r in rows}
    if (values['land_transfer_revenue'] > values['gov_fund_revenue']
            or not math.isclose((debt[2] + debt[5]) / 10000., total, rel_tol=0, abs_tol=.051)):
        raise ValueError('Same-report land/debt consistency checks failed.')
    # Repayment tables are deliberately not interpreted: unresolved narrative
    # versus component-table totals are documented in the cohort decision log.
    return rows
