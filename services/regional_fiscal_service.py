# -*- coding: utf-8 -*-
"""中美地方财政面板。

美国：Census ASFIN 官方免 key 打包文件，州政府本级财政年度口径。
中国：统计局年鉴优先读取官方 XLS，只有官方 JPG 时使用严格 OCR 回退；
省级财政决算用于补充细项。不抓第三方，不把财政部全国地方合计拆分到省。
"""
import csv
import io
import os
import re
import sqlite3
import time
import unicodedata
import zipfile
from datetime import datetime

import requests
import xlrd
from bs4 import BeautifulSoup
from pypdf import PdfReader
from services.nbs_yearbook_ocr import extract_nbs_yearbook_image_values

ASFIN_ZIP = 'https://www2.census.gov/programs-surveys/state/data/GS00STATEFIN01.zip'
ASFIN_SOURCE = 'https://data.census.gov/table/GOVSSTATEFINTIMESERIES.GS00STATEFIN01'
UA = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'),
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

CN_PROVINCES = {
    '北京': '110000', '天津': '120000', '河北': '130000', '山西': '140000',
    '内蒙古': '150000', '辽宁': '210000', '吉林': '220000', '黑龙江': '230000',
    '上海': '310000', '江苏': '320000', '浙江': '330000', '安徽': '340000',
    '福建': '350000', '江西': '360000', '山东': '370000', '河南': '410000',
    '湖北': '420000', '湖南': '430000', '广东': '440000', '广西': '450000',
    '海南': '460000', '重庆': '500000', '四川': '510000', '贵州': '520000',
    '云南': '530000', '西藏': '540000', '陕西': '610000', '甘肃': '620000',
    '青海': '630000', '宁夏': '640000', '新疆': '650000',
}

MOF_REGIONAL_DEBT_SOURCES = (
    ('2018', 'general_debt_outstanding', 'https://yss.mof.gov.cn/zhuantilanmu/dfzgl/sjtj/201907/t20190722_3305519.htm'),
    ('2018', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2018czjs/201907/t20190718_3303330.htm'),
    ('2019', 'general_debt_outstanding', 'https://yss.mof.gov.cn/zhuantilanmu/dfzgl/sjtj/202008/t20200827_3576191.htm'),
    ('2019', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2019qgczjs/202007/t20200731_3559758.htm'),
    ('2020', 'general_debt_outstanding', 'https://yss.mof.gov.cn/2020zyjs/202109/t20210917_3753565.htm'),
    ('2020', 'special_debt_outstanding', 'https://yss.mof.gov.cn/zhuantilanmu/dfzgl/sjtj/202111/t20211101_3762551.htm'),
    ('2021', 'general_debt_outstanding', 'https://yss.mof.gov.cn/2021zyjs/202207/t20220728_3830512.htm'),
    ('2021', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2021zyjs/202207/t20220728_3830608.htm'),
    ('2022', 'general_debt_outstanding', 'https://yss.mof.gov.cn/2022zyjs/202308/t20230825_3904111.htm'),
    ('2022', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2022zyjs/202308/t20230825_3904105.htm'),
    ('2023', 'general_debt_outstanding', 'https://yss.mof.gov.cn/2023zyjs/202408/t20240830_3942837.htm'),
    ('2023', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2023zyjs/202408/t20240830_3942829.htm'),
    ('2024', 'general_debt_outstanding', 'https://yss.mof.gov.cn/2024zyjs/202509/t20250904_3971508.htm'),
    ('2024', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2024zyjs/202509/t20250904_3971495.htm'),
)

NBS_YEARBOOK_FISCAL_XLS = {
    '2010': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2011/html/H0807C.xls',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2011/html/H0808C.xls'},
    '2011': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2012/html/H0807C.xls',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2012/html/H0808C.xls'},
    '2012': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2013/html/Z0905C.xls',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2013/html/Z0906C.xls'},
    '2013': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2014/zk/html/Z0705C.xls',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2014/zk/html/Z0706C.xls'},
    '2020': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2021/html/C07-05.xls',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2021/html/C07-06.xls'},
}
NBS_YEARBOOK_FISCAL_IMAGES = {
    '2014': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2015/html/CH0705.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2015/html/CH0706.jpg'},
    '2015': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2016/html/0705CH.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2016/html/0706CH.jpg'},
    '2016': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2017/html/CH0705.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2017/html/CH0706.jpg'},
    '2017': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2018/html/CH0705.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2018/html/CH0706.jpg'},
    '2018': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2019/html/C0705.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2019/html/C0706.jpg'},
    '2019': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2020/html/C0705.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2020/html/C0706.jpg'},
    '2020': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2021/html/C07-05.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2021/html/C07-06.jpg'},
    '2021': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2022/html/C07-05.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2022/html/C07-06.jpg'},
    '2022': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2023/html/C07-05.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2023/html/C07-06.jpg'},
    '2023': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2024/html/C07-05.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2024/html/C07-06.jpg'},
    '2024': {
        'revenue': 'https://www.stats.gov.cn/sj/ndsj/2025/html/C07-05.jpg',
        'expenditure': 'https://www.stats.gov.cn/sj/ndsj/2025/html/C07-06.jpg'},
}

# Census aggregate codes are stable classifications in GS00STATEFIN01.
ASFIN_INDICATORS = {
    'SF0001': ('total_revenue', '总收入'),
    'SF0036': ('tax_revenue', '税收收入'),
    'SF0037': ('property_tax', '财产税'),
    'SF0038': ('sales_tax', '销售及营业收入税'),
    'SF0050': ('income_tax', '所得税'),
    'SF0132': ('total_expenditure', '总支出'),
    'SF0401': ('interest_expenditure', '一般债务利息支出'),
    'SF0455': ('debt_outstanding', '财政年度末债务余额'),
}

CN_INDICATORS = {
    'general_budget_revenue': '一般公共预算收入',
    'general_budget_expenditure': '一般公共预算支出',
    'tax_revenue': '税收收入',
    'gov_fund_revenue': '政府性基金预算收入',
    'gov_fund_expenditure': '政府性基金预算支出',
    'land_transfer_revenue': '国有土地使用权出让收入',
    'debt_outstanding': '地方政府债务余额',
    'general_debt_outstanding': '一般债务余额',
    'special_debt_outstanding': '专项债务余额',
    'principal_repayment': '还本支出',
    'interest_expenditure': '付息支出',
}

CN_FINAL_ACCOUNT_SOURCES = (
    {'region_code': '110000', 'region_name': '北京', 'period': '2022',
     'source_url': 'https://czj.beijing.gov.cn/zwxx/czsj/czyjs/202308/P020250508598489310570.pdf',
     'source_title': '北京市2022年市级决算（含全市附表）', 'parser': 'beijing_2022'},
    {'region_code': '310000', 'region_name': '上海', 'period': '2023',
     'source_url': 'https://czj.sh.gov.cn/cmsres/c0/c018b52fa53940edb265f88086ee35c9/760ac7c37c42ebc51ca00b1fbd2f7900.pdf',
     'source_title': '关于上海市2023年市级决算及2024年上半年预算执行情况的报告',
     'parser': 'shanghai_2023'},
    {'region_code': '440000', 'region_name': '广东', 'period': '2023',
     'source_url': 'https://czt.gd.gov.cn/attachment/0/556/556744/4477341.pdf',
     'source_title': '广东省人民政府关于我省2023年省级决算草案的报告',
     'parser': 'guangdong_2023'},
)

INDICATOR_LABELS = {code: label for code, label in CN_INDICATORS.items()}
INDICATOR_LABELS.update({code: label for code, label in (v for v in ASFIN_INDICATORS.values())})


def ensure_regional_fiscal_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS regional_fiscal_observations (
      id INTEGER PRIMARY KEY, country_code TEXT NOT NULL, government_scope TEXT NOT NULL,
      region_code TEXT NOT NULL, region_name TEXT NOT NULL, indicator_code TEXT NOT NULL,
      period TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL, frequency TEXT NOT NULL,
      period_type TEXT NOT NULL, data_status TEXT NOT NULL, source_name TEXT NOT NULL,
      source_url TEXT NOT NULL, source_title TEXT, parser_notes TEXT, updated_at TEXT NOT NULL,
      UNIQUE(country_code,government_scope,region_code,indicator_code,period))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_regional_fiscal_lookup
                    ON regional_fiscal_observations(country_code,government_scope,indicator_code,period)''')
    conn.commit()


def parse_asfin_dat(text):
    """Parse Census pipe-delimited data; amounts are converted $000 -> million dollars."""
    out = []
    for row in csv.DictReader(io.StringIO(text), delimiter='|'):
        mapped = ASFIN_INDICATORS.get((row.get('AGG_DESC') or '').strip())
        state = (row.get('ST') or '').strip()
        if not mapped or state in ('', '00') or (row.get('GOVTYPE') or '').strip() != '002':
            continue
        raw = (row.get('AMOUNT') or '').strip()
        if raw in ('', 'X', 'N'):
            continue
        try:
            value = float(raw) / 1000.0
        except ValueError:
            continue
        period = (row.get('YEAR') or row.get('#YEAR') or '').strip()
        if not period:
            continue
        out.append({'region_code': state, 'region_name': (row.get('GEO_LABEL') or '').strip(),
                    'indicator_code': mapped[0], 'period': period,
                    'value': value, 'source_label': (row.get('AGG_DESC_LABEL') or '').strip()})
    return out


def _upsert(conn, row):
    conn.execute('''INSERT INTO regional_fiscal_observations (
      country_code,government_scope,region_code,region_name,indicator_code,period,value,
      unit,frequency,period_type,data_status,source_name,source_url,source_title,parser_notes,updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(country_code,government_scope,region_code,indicator_code,period) DO UPDATE SET
      region_name=excluded.region_name,value=excluded.value,unit=excluded.unit,
      frequency=excluded.frequency,period_type=excluded.period_type,
      data_status=excluded.data_status,source_name=excluded.source_name,
      source_url=excluded.source_url,source_title=excluded.source_title,
      parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
      (row['country_code'], row['government_scope'], row['region_code'], row['region_name'],
       row['indicator_code'], row['period'], row['value'], row['unit'], row['frequency'],
       row['period_type'], row.get('data_status', 'official'), row['source_name'], row['source_url'],
       row.get('source_title'), row.get('parser_notes'), datetime.now().isoformat()))


def _get_with_retry(session, url, attempts=3):
    last_error = None
    for attempt in range(attempts):
        try:
            response = session.get(url, headers=UA, timeout=90)
            if response.status_code >= 500 and attempt + 1 < attempts:
                time.sleep(1)
                continue
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1)
    raise last_error


def update_us_state_finance(conn, session=None):
    session = session or requests
    response = _get_with_retry(session, ASFIN_ZIP)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        name = next(n for n in archive.namelist() if n.endswith('.dat'))
        rows = parse_asfin_dat(archive.read(name).decode('utf-8-sig'))
    # Cleanup only rows produced by the earlier #YEAR parser defect; valid history is untouched.
    conn.execute("""DELETE FROM regional_fiscal_observations
                    WHERE country_code='US' AND source_name='U.S. Census Bureau' AND period=''""")
    for item in rows:
        _upsert(conn, {**item, 'country_code': 'US', 'government_scope': 'state_government',
                'unit': 'million current US$', 'frequency': 'annual', 'period_type': 'fiscal_year',
                'source_name': 'U.S. Census Bureau', 'source_url': ASFIN_SOURCE,
                'source_title': 'Annual Survey of State Government Finances',
                'parser_notes': 'GS00STATEFIN01; Census amount $000 converted to million dollars; state government only, not state-area state+local.'})
    conn.commit()
    return len(rows)


def import_china_official_csv(conn, path):
    """Import reviewed official CN province rows from UTF-8 CSV.

    Required columns: region_code,region_name,period,indicator_code,value,unit,source_url.
    Optional: government_scope,source_title,parser_notes. Every row must carry an official URL.
    """
    if not path or not os.path.exists(path):
        return {'rows': 0, 'status': 'missing_file'}
    count = 0
    with open(path, encoding='utf-8-sig', newline='') as handle:
        for line_no, row in enumerate(csv.DictReader(handle), 2):
            missing = [key for key in ('region_code','region_name','period','indicator_code','value','unit','source_url')
                       if not (row.get(key) or '').strip()]
            if missing:
                raise ValueError(f'China official CSV line {line_no}: missing {missing}')
            code = row['indicator_code'].strip()
            if code not in CN_INDICATORS:
                raise ValueError(f'China official CSV line {line_no}: unsupported indicator {code}')
            url = row['source_url'].strip()
            if not url.startswith('https://'):
                raise ValueError(f'China official CSV line {line_no}: source_url must be https')
            _upsert(conn, {'country_code': 'CN', 'government_scope': (row.get('government_scope') or 'province_total').strip(),
              'region_code': row['region_code'].strip(), 'region_name': row['region_name'].strip(),
              'indicator_code': code, 'period': row['period'].strip(), 'value': float(row['value'].replace(',','')),
              'unit': row['unit'].strip(), 'frequency': 'annual', 'period_type': 'calendar_year',
              'source_name': '国家统计局/省级财政部门', 'source_url': url,
              'source_title': (row.get('source_title') or '').strip(),
              'parser_notes': (row.get('parser_notes') or '用户审核的官方结构化导出').strip()})
            count += 1
    conn.commit()
    return {'rows': count, 'status': 'imported'}


def _normalise_pdf_text(text):
    text = unicodedata.normalize('NFKC', text or '').replace('\U001001b0', '.')
    return re.sub(r'\s+', '', text)


def _pdf_number(text, pattern):
    match = re.search(pattern, text)
    return float(match.group(1).replace(',', '')) if match else None


def parse_china_final_account_text(text, parser_name):
    """Extract reviewed final-account fields in 亿元; unmatched fields stay missing."""
    text = _normalise_pdf_text(text)
    if parser_name == 'beijing_2022':
        result = []
        for code, pattern in (
            ('general_budget_revenue', r'收入合计(57,143,583)注'),
            ('land_transfer_revenue', r'国有土地使用权出让收入(21,007,854)'),
        ):
            value = _pdf_number(text, pattern)
            if value is not None:
                result.append({'government_scope': 'province_total',
                               'indicator_code': code, 'value': value / 10000.0})
        return result
    if parser_name == 'shanghai_2023':
        specs = (
            ('province_total', 'general_budget_revenue', r'全市一般公共预算收入([\d,.]+)亿元'),
            ('province_total', 'general_budget_expenditure', r'全市一般公共预算支出([\d,.]+)亿元'),
            ('province_total', 'gov_fund_revenue', r'全市政府性基金预算收入([\d,.]+)亿元'),
            ('province_total', 'gov_fund_expenditure', r'全市政府性基金预算支出([\d,.]+)亿元'),
            ('province_total', 'debt_outstanding', r'截至2023年底,本市政府债务余额为([\d,.]+)亿元'),
            ('province_level', 'land_transfer_revenue', r'市级国有土地使用权出让收入([\d,.]+)亿元'),
        )
    elif parser_name == 'guangdong_2023':
        specs = (
            ('province_total', 'general_budget_revenue', r'全省一般公共预算收入([\d,.]+)亿元'),
            ('province_total', 'general_budget_expenditure', r'全省一般公共预算支出([\d,.]+)亿元'),
            ('province_total', 'gov_fund_revenue', r'全省政府性基金预算收入([\d,.]+)亿元'),
            ('province_total', 'gov_fund_expenditure', r'全省政府性基金预算支出([\d,.]+)亿元'),
            ('province_total', 'debt_outstanding', r'全省政府债务余额([\d,.]+)亿元'),
            ('province_total', 'general_debt_outstanding', r'其中一般债务([\d,.]+)亿元'),
            ('province_total', 'special_debt_outstanding', r'专项债务([\d,.]+)亿元'),
            ('province_total', 'principal_repayment', r'全省偿还地方政府债券本金([\d,.]+)亿元'),
            ('province_total', 'interest_expenditure', r'支付地方政府债券利息([\d,.]+)亿元'),
            ('province_total', 'land_transfer_revenue',
             r'国有土地使用权出让收入59,546,50440,960,318([\d,]+)'),
        )
    else:
        raise ValueError(f'unknown China final-account parser: {parser_name}')
    result = []
    for scope, code, pattern in specs:
        value = _pdf_number(text, pattern)
        if value is None:
            continue
        if parser_name == 'guangdong_2023' and code == 'land_transfer_revenue':
            value /= 10000.0  # table 20 is in 万元
        result.append({'government_scope': scope, 'indicator_code': code, 'value': value})
    return result


def update_china_final_accounts(conn, session=None, sources=CN_FINAL_ACCOUNT_SOURCES):
    """Fetch real official PDFs; verification/error pages are skipped without deleting old data."""
    session = session or requests
    imported, errors = 0, []
    for source in sources:
        try:
            response = _get_with_retry(session, source['source_url'])
            if not response.content.startswith(b'%PDF'):
                raise ValueError('response is not a PDF')
            reader = PdfReader(io.BytesIO(response.content))
            text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            rows = parse_china_final_account_text(text, source['parser'])
            if not rows:
                raise ValueError('no reviewed final-account fields matched')
            for item in rows:
                _upsert(conn, {**item, 'country_code': 'CN',
                    'region_code': source['region_code'], 'region_name': source['region_name'],
                    'period': source['period'], 'unit': '亿元', 'frequency': 'annual',
                    'period_type': 'calendar_year', 'source_name': '省级财政部门',
                    'source_url': source['source_url'], 'source_title': source['source_title'],
                    'parser_notes': '官方决算PDF直接披露值；按报告标题区分全省/全市与省级/市级口径。'})
                imported += 1
        except Exception as exc:
            errors.append(f"{source['region_name']} {source['period']}: {exc}")
    conn.commit()
    return {'rows': imported, 'errors': errors,
            'status': 'imported' if imported else 'source_blocked'}


def parse_nbs_regional_fiscal_sheet(sheet, period, table_type, source_url):
    """Parse NBS yearbook province fiscal totals; revenue also includes tax revenue."""
    if table_type not in ('revenue', 'expenditure'):
        raise ValueError(f'unsupported NBS fiscal table type: {table_type}')
    rows = []
    for row_index in range(sheet.nrows):
        compact = ''.join(str(sheet.cell_value(row_index, 0) or '').split())
        identity = next(((code, short) for short, code in CN_PROVINCES.items()
                         if compact.startswith(short)), None)
        if not identity:
            continue
        code, name = identity
        indicators = [('general_budget_revenue', 1), ('tax_revenue', 2)] \
            if table_type == 'revenue' else [('general_budget_expenditure', 1)]
        for indicator_code, column in indicators:
            if column >= sheet.ncols:
                continue
            value = sheet.cell_value(row_index, column)
            if not isinstance(value, (int, float)) or value < 0:
                continue
            rows.append({'country_code': 'CN', 'government_scope': 'province_total',
                         'region_code': code, 'region_name': name,
                         'indicator_code': indicator_code, 'period': str(period),
                         'value': round(float(value), 4), 'unit': '亿元',
                         'frequency': 'annual', 'period_type': 'calendar_year',
                         'source_name': '国家统计局《中国统计年鉴》', 'source_url': source_url,
                         'source_title': f'{period}年分地区一般公共预算{table_type}',
                         'parser_notes': '国家统计局年鉴官方XLS直接值；地方全口径、当年价。'})
    expected = 62 if table_type == 'revenue' else 31
    if len(rows) != expected:
        raise ValueError(f'NBS fiscal {period} {table_type}: expected {expected} rows, got {len(rows)}')
    return rows


def parse_nbs_regional_fiscal_image(content, period, table_type, source_url):
    """Parse the first one/two columns from an official NBS yearbook JPEG."""
    if table_type not in ('revenue', 'expenditure'):
        raise ValueError(f'unsupported NBS fiscal table type: {table_type}')
    needed = 2 if table_type == 'revenue' else 1
    extracted = extract_nbs_yearbook_image_values(content, needed_columns=needed)
    provinces = [(code, name) for name, code in CN_PROVINCES.items()]
    rows = []
    for (code, name), item in zip(provinces, extracted):
        values = item['values']
        if not values or values[0] < 0:
            raise ValueError(f'NBS fiscal {period} {name}: invalid total')
        if table_type == 'revenue' and (values[1] < 0 or values[1] > values[0]):
            raise ValueError(f'NBS fiscal {period} {name}: tax revenue exceeds total revenue')
        indicators = [('general_budget_revenue', values[0])]
        if table_type == 'revenue':
            indicators.append(('tax_revenue', values[1]))
        else:
            indicators = [('general_budget_expenditure', values[0])]
        for indicator_code, value in indicators:
            rows.append({'country_code': 'CN', 'government_scope': 'province_total',
                         'region_code': code, 'region_name': name,
                         'indicator_code': indicator_code, 'period': str(period),
                         'value': round(float(value), 4), 'unit': '亿元',
                         'frequency': 'annual', 'period_type': 'calendar_year',
                         'source_name': '国家统计局《中国统计年鉴》',
                         'source_url': source_url,
                         'source_title': f'{period}年分地区一般公共预算{table_type}',
                         'parser_notes': ('国家统计局年鉴官方JPG；本地OCR首数值列，'
                                          f'本行目标列最低置信度{item["confidence"]:.3f}；'
                                          '固定31省顺序，整表校验通过。')})
    expected = 62 if table_type == 'revenue' else 31
    if len(rows) != expected:
        raise ValueError(f'NBS fiscal image {period} {table_type}: expected {expected}, got {len(rows)}')
    return rows


def _complete_nbs_fiscal_table(conn, period, table_type):
    codes = ('general_budget_revenue', 'tax_revenue') if table_type == 'revenue' \
        else ('general_budget_expenditure',)
    placeholders = ','.join('?' for _ in codes)
    counts = dict(conn.execute(f'''SELECT indicator_code,COUNT(DISTINCT region_code)
      FROM regional_fiscal_observations WHERE country_code='CN' AND period=?
      AND government_scope='province_total' AND indicator_code IN ({placeholders})
      GROUP BY indicator_code''', (str(period), *codes)).fetchall())
    return all(counts.get(code, 0) >= 31 for code in codes)


def update_nbs_regional_fiscal(conn, session=None):
    session = session or requests
    imported, errors = 0, []
    for period, tables in NBS_YEARBOOK_FISCAL_XLS.items():
        for table_type, url in tables.items():
            if _complete_nbs_fiscal_table(conn, period, table_type):
                continue
            try:
                response = _get_with_retry(session, url)
                if not response.content.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
                    raise ValueError('response is not an Excel BIFF file')
                sheet = xlrd.open_workbook(file_contents=response.content).sheet_by_index(0)
                for row in parse_nbs_regional_fiscal_sheet(sheet, period, table_type, url):
                    _upsert(conn, row)
                    imported += 1
            except Exception as exc:
                errors.append(f'NBS fiscal {period} {table_type}: {exc}')
    for period, tables in NBS_YEARBOOK_FISCAL_IMAGES.items():
        for table_type, url in tables.items():
            if _complete_nbs_fiscal_table(conn, period, table_type):
                continue
            try:
                response = _get_with_retry(session, url)
                for row in parse_nbs_regional_fiscal_image(
                        response.content, period, table_type, url):
                    _upsert(conn, row)
                    imported += 1
            except Exception as exc:
                errors.append(f'NBS fiscal image {period} {table_type}: {exc}')
    conn.commit()
    return {'rows': imported, 'errors': errors,
            'status': 'imported' if imported else 'source_blocked'}


def _province_identity(raw_name):
    compact = re.sub(r'\s+', '', raw_name or '')
    if '不含' in compact or compact in ('合计', '待分配'):
        return None
    for short, code in CN_PROVINCES.items():
        if compact.startswith(short):
            return code, short
    return None


def parse_mof_regional_debt_html(html, indicator_code, period, source_url):
    """Parse the 31 province-total rows from an MOF debt final-account table."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for tr in soup.find_all('tr'):
        cells = [cell.get_text(' ', strip=True) for cell in tr.find_all(['th', 'td'])]
        if len(cells) < 3:
            continue
        identity = _province_identity(cells[0])
        if not identity:
            continue
        numbers = []
        for cell in cells[1:]:
            match = re.fullmatch(r'\s*(-?[\d,.]+)\s*', cell)
            if match:
                try:
                    numbers.append(float(match.group(1).replace(',', '')))
                except ValueError:
                    pass
        if not numbers:
            continue
        code, name = identity
        rows.append({'country_code': 'CN', 'government_scope': 'province_total',
                     'region_code': code, 'region_name': name,
                     'indicator_code': indicator_code, 'period': str(period),
                     'value': numbers[-1], 'unit': '亿元', 'frequency': 'annual',
                     'period_type': 'calendar_year', 'source_name': '中华人民共和国财政部',
                     'source_url': source_url,
                     'source_title': f'{period}年地方政府债务分地区余额表',
                     'parser_notes': '财政部全国财政决算分地区表；仅取31个省级合计行，排除计划单列市及“不含”子行。'})
    if len({row['region_code'] for row in rows}) != 31:
        raise ValueError(f'MOF table expected 31 province rows, got {len({r["region_code"] for r in rows})}')
    return rows


def discover_mof_regional_debt_sources(session=None):
    """Return individually verified official table URLs; no fragile all-or-nothing index crawl."""
    return list(MOF_REGIONAL_DEBT_SOURCES)


def update_mof_regional_debt(conn, session=None):
    session = session or requests
    imported, errors = 0, []
    try:
        sources = discover_mof_regional_debt_sources(session)
    except Exception as exc:
        return {'rows': 0, 'errors': [f'MOF debt discovery: {exc}'],
                'status': 'source_blocked'}
    for period, indicator_code, url in sources:
        try:
            response = _get_with_retry(session, url)
            for row in parse_mof_regional_debt_html(response.content, indicator_code, period, url):
                _upsert(conn, row)
                imported += 1
        except Exception as exc:
            errors.append(f'MOF {period} {indicator_code}: {exc}')
    conn.commit()
    return {'rows': imported, 'errors': errors,
            'status': 'imported' if imported else 'source_blocked'}


def update_regional_fiscal(conn, china_csv_path=None):
    errors = []
    try:
        us_rows = update_us_state_finance(conn)
    except Exception as exc:
        us_rows = 0; errors.append(f'US ASFIN: {exc}')
    try:
        cn = import_china_official_csv(conn, china_csv_path or os.environ.get('CHINA_REGIONAL_OFFICIAL_CSV'))
    except Exception as exc:
        cn = {'rows': 0, 'status': 'error'}; errors.append(f'CN official import: {exc}')
    live = update_china_final_accounts(conn)
    errors.extend(live['errors'])
    nbs = update_nbs_regional_fiscal(conn)
    errors.extend(nbs['errors'])
    debt = update_mof_regional_debt(conn)
    errors.extend(debt['errors'])
    cn_rows = cn['rows'] + live['rows'] + nbs['rows'] + debt['rows']
    return {'success': us_rows > 0 or cn_rows > 0, 'us_rows': us_rows,
            'cn_rows': cn_rows, 'cn_status': live['status'] if live['rows'] else cn['status'],
            'nbs_fiscal_rows': nbs['rows'], 'mof_debt_rows': debt['rows'], 'errors': errors}


def _derived_rows(rows):
    index = {(r['country_code'],r['government_scope'],r['region_code'],r['period'],r['indicator_code']): r for r in rows}
    derived = []
    specs = [('fiscal_balance','total_revenue','total_expenditure','总收支差额','left - right'),
             ('fiscal_balance','general_budget_revenue','general_budget_expenditure','一般预算收支差额','left - right'),
             ('tax_share','tax_revenue','total_revenue','税收占收入','left / right × 100'),
             ('tax_share','tax_revenue','general_budget_revenue','税收占一般预算收入','left / right × 100'),
             ('interest_burden','interest_expenditure','total_revenue','利息支出/收入','left / right × 100'),
             ('interest_burden','interest_expenditure','general_budget_revenue','付息/一般预算收入','left / right × 100'),
             ('land_dependency','land_transfer_revenue','gov_fund_revenue','土地出让/基金收入','left / right × 100')]
    for r in rows:
        for code,left,right,label,formula in specs:
            if r['indicator_code'] != left: continue
            other=index.get((r['country_code'],r['government_scope'],r['region_code'],r['period'],right))
            if not other or (right == 'total_revenue' and not other['value']): continue
            value=r['value']-other['value'] if code=='fiscal_balance' else r['value']/other['value']*100
            derived.append({**r,'indicator_code':code,'value':round(value,4),
                            'unit':r['unit'] if code=='fiscal_balance' else '%',
                            'data_status':'derived','formula':formula})
    for key, general in index.items():
        country, scope, region, period, code = key
        if code != 'general_debt_outstanding':
            continue
        special = index.get((country, scope, region, period, 'special_debt_outstanding'))
        existing_total = index.get((country, scope, region, period, 'debt_outstanding'))
        if special and not existing_total:
            derived.append({**general, 'indicator_code': 'debt_outstanding',
                            'value': round(general['value'] + special['value'], 4),
                            'data_status': 'derived',
                            'formula': 'general_debt_outstanding + special_debt_outstanding'})
    return rows + derived


def build_regional_fiscal_payload(conn):
    ensure_regional_fiscal_table(conn)
    rows = [dict(r) for r in conn.execute('''SELECT country_code,government_scope,region_code,
      region_name,indicator_code,period,value,unit,data_status,source_name,source_url,
      source_title,parser_notes
      FROM regional_fiscal_observations ORDER BY country_code,period,region_name,indicator_code''')]
    rows = _derived_rows(rows)
    # Same-country, same-year nominal GDP denominator; no FX conversion or cross-country ratio.
    try:
        gdp = {(r['country_code'],r['region_code'],r['period']): r['value'] for r in conn.execute('''
          SELECT country_code,region_code,period,value FROM gdp_region_observations
          WHERE indicator_code='nominal_gdp' ''')}
    except sqlite3.OperationalError:
        gdp = {}
    for row in list(rows):
        if row['indicator_code'] != 'debt_outstanding': continue
        denominator = gdp.get((row['country_code'],row['region_code'],row['period']))
        if denominator:
            rows.append({**row,'indicator_code':'debt_to_gdp','value':round(row['value']/denominator*100,4),
                         'unit':'%','data_status':'derived','formula':'debt_outstanding / nominal_gdp × 100'})
    coverage = {}
    for country in ('CN','US'):
        subset=[r for r in rows if r['country_code']==country]
        coverage[country]={'records':len(subset),'regions':len({r['region_code'] for r in subset}),
                           'start':min((r['period'] for r in subset),default=None),
                           'end':max((r['period'] for r in subset),default=None)}
    labels = dict(INDICATOR_LABELS)
    labels.update({'fiscal_balance':'财政收支差额','tax_share':'税收占收入',
                   'interest_burden':'利息支出/收入','land_dependency':'土地财政依赖度',
                   'debt_to_gdp':'债务/GDP'})
    return {'rows':rows,'coverage':coverage,'indicator_labels':labels,
            'scopes':{'US':{'state_government':'州政府本级（不含地方政府）'},
                      'CN':{'province_total':'全省口径','province_level':'省本级口径'}},
            'source_status':{'US':'official' if coverage['US']['records'] else 'missing',
              'CN':'official' if coverage['CN']['records'] else 'source_blocked'},
            'caveats':['美国 ASFIN 为州政府本级财政年度口径，不是州域内州和地方政府合计。',
                       '美国财产税不是中国土地出让收入的对应项，两者不做直接对比。',
                       '中国省级只接受统计局或财政决算直接披露值；全国地方合计不按比例拆省。']}
