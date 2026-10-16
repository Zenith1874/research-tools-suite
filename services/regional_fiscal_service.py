# -*- coding: utf-8 -*-
"""中美地方财政面板。

美国：Census ASFIN 官方免 key 打包文件，州政府本级财政年度口径。
中国：统计局年鉴优先读取官方 XLS，只有官方 JPG 时使用严格 OCR 回退；
省级财政决算用于补充细项。不抓第三方，不把财政部全国地方合计拆分到省。
"""
import csv
import hashlib
import io
import os
import re
import sqlite3
import time
import unicodedata
import zipfile
import json
import math
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
import xlrd
from bs4 import BeautifulSoup
from pypdf import PdfReader
from services.nbs_yearbook_ocr import extract_nbs_yearbook_image_values
from services.fiscal_source_authority import reviewed_issuer_fiscal_source
from services.provincial_issuer_visual_profiles import VISUAL_PROFILES, parse_provincial_issuer_visual_pages

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
    ('2019', 'general_debt_outstanding', 'https://yss.mof.gov.cn/2019qgczjs/202007/t20200731_3559742.htm'),
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
    ('2025', 'special_debt_outstanding', 'https://yss.mof.gov.cn/2025zyjs/202609/t20260916_3997518.htm'),
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


def parse_china_annual_fiscal_bulletin(html, province, period, source_title):
    """Read annual local-budget amounts, never budget targets or province-own data."""
    if province not in CN_PROVINCES or not re.fullmatch(r'20\d{2}', str(period)):
        raise ValueError('A known province and annual statistical year are required.')
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = _normalise_pdf_text(soup.get_text(' ', strip=True))
    text = re.sub(r'\[\d+\]', '', text)
    title = _normalise_pdf_text(source_title)
    if str(period) not in title or f'{period}年' not in text:
        raise ValueError('The annual statistical period must be stated by the source.')
    if re.search(r'上半年|前三季度|[一二三四]季度|\d{1,2}月|预算草案|预算报告|预算执行|决算', title):
        raise ValueError('This parser accepts annual statistical releases, not budget documents or subannual reports.')
    output, accepted = [], {}
    money = r'(?:[,，:：])?(?:完成|实现|为|达到|达)?(?P<amount>[\d,]+(?:\.[\d]+)?)(?P<unit>万亿元|亿元)'
    specs = [('general_budget_revenue', r'(?:地方)?一般公共预算收入'),
             ('general_budget_expenditure', r'(?:地方)?一般公共预算支出'),
             ('tax_revenue', r'(?<!非)税收收入(?:规模创历史新高,|规模)?')]
    municipalities = {'北京', '天津', '上海', '重庆'}
    autonomous = {'内蒙古', '广西', '西藏', '宁夏', '新疆'}
    for indicator, label in specs:
        for match in re.finditer(label + money, text):
            before = text[max(0, match.start()-90):match.start()]
            clause = re.split(r'。|；|[!?！？]', before)[-1]
            if re.search(r'预计|预算数|安排|力争|计划|目标|全国|中央', clause[-28:]):
                continue
            years = re.findall(r'(20\d{2})年(?!\d+月)', clause[-40:])
            if years and years[-1] != str(period):
                continue
            scopes = list(re.finditer(r'全省|全市|全区|全县|省本级|市本级|本级|省级|市级', clause))
            scope = scopes[-1][0] if scopes else None
            if scope in ('全县','省本级','市本级','本级','省级','市级'):
                continue
            if scope == '全市' and province not in municipalities:
                continue
            if scope == '全区' and province not in autonomous:
                continue
            if '不含' in clause[-25:]:
                continue
            named = [(clause.rfind(name), name) for name in CN_PROVINCES if name in clause[-24:]]
            if named and max(named)[1] != province:
                continue
            if indicator == 'tax_revenue':
                # Local-budget tax is not the tax authority's whole-territory collection.
                parent = accepted.get('general_budget_revenue')
                if not parent or not 0 <= match.start()-parent['match_end'] <= 240:
                    continue
                between = text[parent['match_end']:match.start()]
                if re.search(r'财政总收入|全国税收|税务部门|税务局|全口径税收', between):
                    continue
            value = float(match['amount'].replace(',', '')) * (10000 if match['unit'] == '万亿元' else 1)
            if value < 0 or (indicator == 'tax_revenue' and value > accepted['general_budget_revenue']['value']):
                continue
            evidence = text[max(0,match.start()-25):match.end()]
            output.append({'country_code':'CN','government_scope':'province_total',
                           'region_code':CN_PROVINCES[province],'region_name':province,
                           'indicator_code':indicator,'period':str(period),'value':value,
                           'unit':'亿元','frequency':'annual','period_type':'calendar_year',
                           'data_status':'official_preliminary','evidence':evidence,
                           'raw_amount':match['amount'],'raw_unit':match['unit']})
            accepted[indicator] = {'value':value,'match_end':match.end()}
            break
    return output


def parse_china_execution_report(html, province, period, profile):
    """Read a reviewed actual-execution chapter, excluding the next-year budget plan."""
    identity = (province, str(period), profile)
    reviewed_profiles = {
        ('云南', '2025', 'yunnan_2025_execution'),
        ('四川', '2025', 'sichuan_2025_execution'),
        ('福建', '2025', 'fujian_2025_execution'),
    }
    if identity not in reviewed_profiles:
        raise ValueError('Use an explicitly reviewed province/year execution-report profile.')
    soup=BeautifulSoup(html,'html.parser')
    for tag in soup(['script','style']):tag.decompose()
    text=_normalise_pdf_text(soup.get_text(' ',strip=True))

    if profile == 'yunnan_2025_execution':
        start_pattern = r'一、2025年地方财政预算执行'
        end_pattern = plan_pattern = r'二、[^。]{0,80}2026年地方财政预算安排'
    elif profile == 'sichuan_2025_execution':
        start_pattern = r'一、2025年预算执行情况'
        end_pattern = r'二、落实省人大预算决议和重点财政工作情况'
        plan_pattern = r'四、2026年预算草案'
    else:
        start_pattern = r'一、2025年预算执行情况'
        end_pattern = r'\(二\)主要财税政策落实和重点财政工作情况'
        plan_pattern = r'二、2026年预算草案'
    start = re.search(start_pattern, text)
    end = re.search(end_pattern, text)
    plan = re.search(plan_pattern, text)
    if not start or not end or not plan or not start.end() < end.start() <= plan.start():
        raise ValueError('Both actual-execution and next-year-plan boundaries must be confirmed.')
    actual=text[start.end():end.start()]
    amount = r'(?:完成|为|达到|达)?(?P<value>[\d,.]+)亿元'
    if profile == 'yunnan_2025_execution':
        general_end=actual.find('(二)政府性基金预算')
        if general_end<0:raise ValueError('General-budget section boundary is required.')
        general=actual[:general_end]
        specs=[('general_budget_revenue',general,r'全省地方一般公共预算收入'+amount),
               ('general_budget_expenditure',general,r'全省地方一般公共预算支出'+amount),
               ('tax_revenue',general,r'全省税收收入'+amount),
               ('gov_fund_revenue',actual,r'全省政府性基金预算收入'+amount),
               ('gov_fund_expenditure',actual,r'全省政府性基金预算支出'+amount),
               ('debt_outstanding',actual,r'2025年末全省地方政府债务余额'+amount)]
    else:
        fund_heading = '(二)政府性基金预算' if province == '四川' else '2.政府性基金预算'
        capital_heading = '(三)国有资本经营预算' if province == '四川' else '3.国有资本经营预算'
        debt_heading = '(五)地方政府债务' if province == '四川' else '5.地方政府债务情况'
        fund_start, fund_end, debt_start = (actual.find(h) for h in
                                          (fund_heading, capital_heading, debt_heading))
        if not 0 <= fund_start < fund_end < debt_start:
            raise ValueError('Reviewed general/fund/debt subsection boundaries are required.')
        general, fund, debt = actual[:fund_start], actual[fund_start:fund_end], actual[debt_start:]
        specs=[('general_budget_revenue',general,r'全省地方一般公共预算收入'+amount),
               ('general_budget_expenditure',general,r'全省一般公共预算支出'+amount),
               ('gov_fund_revenue',fund,r'全省政府性基金预算收入'+amount),
               ('debt_outstanding',debt,r'全省政府债务余额'+amount)]
        if province == '四川':
            specs += [
                ('tax_revenue', general,
                 r'全省地方一般公共预算收入[\d,.]+亿元[^。]{0,40}。其中:税收收入'+amount),
                ('gov_fund_expenditure', fund,
                 r'加上中央转移支付、专项债务等来源,实现支出'+amount),
                ('land_transfer_revenue', fund, r'其中:土地出让收入'+amount),
                ('general_debt_outstanding', debt,
                 r'全省一般债务限额[\d,.]+亿元,余额'+amount),
                ('principal_repayment', debt, r'减去偿还到期政府债务'+amount),
            ]
        else:
            specs += [
                ('gov_fund_expenditure', fund, r'全省政府性基金预算支出'+amount),
                ('general_debt_outstanding', debt, r'其中,一般债务'+amount),
                ('principal_repayment', debt, r'全省共偿还政府债务本金'+amount),
            ]
    rows=[]
    for code,section,pattern in specs:
        matches = list(re.finditer(pattern, section))
        values = {float(m['value'].replace(',', '')) for m in matches}
        if len(values) > 1:
            raise ValueError(f'Conflicting actual-execution amounts for {code}.')
        match = matches[0] if matches else None
        if match:
            value=float(match['value'].replace(',',''))
            rows.append({'country_code':'CN','government_scope':'province_total','region_code':CN_PROVINCES[province],
                         'region_name':province,'indicator_code':code,'period':str(period),'value':value,
                         'unit':'亿元','frequency':'annual','period_type':'calendar_year','data_status':'official_preliminary',
                         'evidence':match[0]})
    values={r['indicator_code']:r['value'] for r in rows}
    if set(values)!=set(code for code,_,_ in specs) or values.get('tax_revenue',0)>values['general_budget_revenue']:
        raise ValueError('Reviewed execution-report fields are missing or inconsistent.')
    if values.get('land_transfer_revenue', 0) > values['gov_fund_revenue']:
        raise ValueError('Land-transfer revenue exceeds its government-fund parent.')
    if values.get('general_debt_outstanding', 0) > values['debt_outstanding']:
        raise ValueError('General debt exceeds the same-report total government debt.')
    return rows


def _parse_china_yearend_fiscal_release(html, province, period, profile):
    """Read reviewed January-December paragraphs, not the separate December flow."""
    profiles = {
        ('江西', '2025', 'jiangxi_2025_annual_completion'): {
            'title': '2025年1-12月份,全省一般公共预算收入完成3079.2亿元',
            'selector': '#zoomcon',
        },
        ('青海', '2025', 'qinghai_2025_annual_completion'): {
            'title': '青海省2025年1—12月财政收支执行情况',
            'selector': '#html001',
        },
    }
    config = profiles.get((province, str(period), profile))
    if config is None:
        raise ValueError('A reviewed province/year January-December release is required.')
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('title')
    if not title or config['title'] not in _normalise_pdf_text(title.get_text()):
        raise ValueError('The inspected statistical year and full-year release title changed.')
    content = soup.select_one(config['selector'])
    if content is None:
        raise ValueError('The reviewed article body is missing.')
    paragraphs = [_normalise_pdf_text(p.get_text(' ', strip=True)) for p in content.find_all('p')]
    annual = [p for p in paragraphs if re.match(r'1[-—–]12月份?[,，]', p)]
    if not annual or any(re.search(r'预计|计划|预算安排|收入目标|支出预算|省本级|市本级|全县|全市', p) for p in annual):
        raise ValueError('Full-province actual January-December paragraphs are required.')
    money = r'(?P<value>[\d,]+(?:\.\d+)?)亿元'
    general = [p for p in annual if '一般公共预算收入' in p]
    if len(general) != 1:
        raise ValueError('One annual general-budget paragraph is required.')
    specs = [('general_budget_revenue', general[0],
              (r'全省一般公共预算收入' if province == '江西' else r'地方一般公共预算收入') + money),
             ('tax_revenue', general[0], r'(?<!非)税收收入' + money)]
    if province == '江西':
        specs.append(('general_budget_expenditure', general[0], r'一般公共预算支出' + money))
        fund = [p for p in annual if '全省政府性基金预算收入' in p]
        if len(fund) != 1:
            raise ValueError('One annual government-fund paragraph is required.')
        specs.extend([
            ('gov_fund_revenue', fund[0], r'全省政府性基金预算收入' + money),
            ('gov_fund_expenditure', fund[0], r'政府性基金预算支出' + money),
            ('land_transfer_revenue', fund[0], r'国有土地使用权出让收入' + money),
        ])
    else:
        spending = [p for p in annual if '全省一般公共预算支出' in p]
        if len(spending) != 1:
            raise ValueError('One annual full-province expenditure paragraph is required.')
        specs.append(('general_budget_expenditure', spending[0], r'全省一般公共预算支出' + money))
    rows = []
    for code, paragraph, pattern in specs:
        matches = list(re.finditer(pattern, paragraph))
        if len(matches) != 1:
            raise ValueError(f'One directly disclosed annual amount is required for {code}.')
        match = matches[0]
        rows.append({'country_code':'CN', 'government_scope':'province_total',
                     'region_code':CN_PROVINCES[province], 'region_name':province,
                     'indicator_code':code, 'period':str(period),
                     'value':float(match['value'].replace(',', '')), 'unit':'亿元',
                     'frequency':'annual', 'period_type':'calendar_year',
                     'data_status':'official_preliminary', 'evidence':paragraph})
    values = {r['indicator_code']:r['value'] for r in rows}
    if values['tax_revenue'] > values['general_budget_revenue']:
        raise ValueError('Annual local-budget tax exceeds its same-report parent.')
    if values.get('land_transfer_revenue', 0) > values.get('gov_fund_revenue', 0):
        raise ValueError('Annual land-transfer revenue exceeds government-fund revenue.')
    return rows


def parse_china_fiscal_completion_release(html, province, period, profile):
    """Read a reviewed annual completion release, not a mixed-year budget report."""
    if profile in ('jiangxi_2025_annual_completion', 'qinghai_2025_annual_completion'):
        return _parse_china_yearend_fiscal_release(html, province, period, profile)
    profiles = {
        ('内蒙古', '2025', 'inner_mongolia_2025_completion'): {
            'heading': '2025年全区一般公共预算和政府性基金预算收支完成情况',
            'scope': '全区',
        },
    }
    config = profiles.get((province, str(period), profile))
    if config is None:
        raise ValueError('A reviewed annual completion-release profile is required.')
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    text = _normalise_pdf_text(soup.get_text(' ', strip=True))
    start = text.find(config['heading'])
    if start < 0:
        raise ValueError('The exact annual completion-release heading is required.')
    actual = text[start + len(config['heading']):]
    end = actual.find('信息来源:')
    if end < 0:
        raise ValueError('The reviewed article footer boundary is required.')
    actual = actual[:end]
    if re.search(r'2026年[^。]{0,40}(?:预算|预计|安排)|省本级|自治区本级', actual):
        raise ValueError('Do not treat plans or province-own amounts as a completion release.')
    scope = config['scope']
    money = r'(?P<value>[\d,.]+)亿元'
    specs = [
        ('general_budget_revenue', scope + r'一般公共预算收入' + money),
        ('general_budget_expenditure', scope + r'一般公共预算支出' + money),
        ('tax_revenue', r'其中,税收' + money),
        ('gov_fund_revenue', scope + r'政府性基金预算收入' + money),
        ('gov_fund_expenditure', scope + r'政府性基金预算支出' + money),
    ]
    rows = []
    for code, pattern in specs:
        matches = list(re.finditer(pattern, actual))
        if len(matches) != 1:
            raise ValueError(f'One reviewed completion amount is required for {code}.')
        match = matches[0]
        rows.append({'country_code':'CN', 'government_scope':'province_total',
                     'region_code':CN_PROVINCES[province], 'region_name':province,
                     'indicator_code':code, 'period':str(period),
                     'value':float(match['value'].replace(',', '')), 'unit':'亿元',
                     'frequency':'annual', 'period_type':'calendar_year',
                     'data_status':'official_preliminary', 'evidence':match[0]})
    values = {r['indicator_code']:r['value'] for r in rows}
    if values['tax_revenue'] > values['general_budget_revenue']:
        raise ValueError('Completion-release tax exceeds local general-budget revenue.')
    return rows


def _parse_shanghai_2025_final_table(page_texts, province, period, profile):
    """Read the inspected final column/whole-city row of four one-page originals."""
    profiles = {
        'shanghai_2025_revenue_final': ('一般公共预算收入', [
            ('general_budget_revenue', '一般公共预算收入合计'), ('tax_revenue', '税收收入')]),
        'shanghai_2025_fund_revenue_final': ('政府性基金收入', [
            ('gov_fund_revenue', '政府性基金收入合计'),
            ('land_transfer_revenue', '国有土地使用权出让收入')]),
        'shanghai_2025_fund_expenditure_final': ('政府性基金支出', [
            ('gov_fund_expenditure', '政府性基金支出合计')]),
        'shanghai_2025_debt_balances_final': ('地方政府债务限额和余额', []),
    }
    if (province, str(period)) != ('上海', '2025') or profile not in profiles or set(page_texts) != {1}:
        raise ValueError('A reviewed Shanghai 2025 one-page final-account table is required.')
    text = unicodedata.normalize('NFKC', page_texts[1] or '')
    compact = _normalise_pdf_text(text)
    title, specs = profiles[profile]
    if '上海市2025年' + title + '决算情况表' not in compact or '单位:亿元' not in compact:
        raise ValueError('The reviewed full-city final-account heading or unit changed.')
    number = r'([\d,]+(?:\.\d+)?)'
    rows = []

    def record(code, value, evidence):
        rows.append({'country_code':'CN', 'government_scope':'province_total',
                     'region_code':CN_PROVINCES[province], 'region_name':province,
                     'indicator_code':code, 'period':str(period), 'value':value,
                     'unit':'亿元', 'frequency':'annual', 'period_type':'calendar_year',
                     'data_status':'official_final', 'evidence':evidence,
                     'evidence_page':1, 'raw_unit':'亿元'})

    if specs:
        header = ('项目年初预算数经人大批准的调整后预算数决算数'
                  '决算数为调整后预算数的%决算数为上年决算数的%')
        if header not in compact:
            raise ValueError('The reviewed budget/adjusted/final column order changed.')
        for code, label in specs:
            pattern = r'^[ \t]*' + re.escape(label) + r'\s+' + r'\s+'.join([number] * 5) + r'[ \t]*$'
            matches = list(re.finditer(pattern, text, re.MULTILINE))
            if len(matches) != 1:
                raise ValueError(f'One complete five-cell final-account row is required for {code}.')
            match = matches[0]
            record(code, float(match[3].replace(',', '')), match[0])
        values = {r['indicator_code']:r['value'] for r in rows}
        if values.get('tax_revenue', 0) > values.get('general_budget_revenue', math.inf):
            raise ValueError('Final tax exceeds its same-table revenue parent.')
        if values.get('land_transfer_revenue', 0) > values.get('gov_fund_revenue', math.inf):
            raise ValueError('Final land-transfer revenue exceeds its fund parent.')
    else:
        if ('2025年债务限额2025年债务余额决算数' not in compact or
                '小计一般债务专项债务小计一般债务专项债务' not in compact):
            raise ValueError('The reviewed limit/balance column groups changed.')
        pattern = r'^[ \t]*上海市合计\s+' + r'\s+'.join([number] * 6) + r'[ \t]*$'
        matches = list(re.finditer(pattern, text, re.MULTILINE))
        if len(matches) != 1:
            raise ValueError('One whole-city row with both three-cell debt groups is required.')
        match = matches[0]
        cells = [float(v.replace(',', '')) for v in match.groups()]
        if cells[3] > cells[0] or not math.isclose(cells[3], sum(cells[4:]), abs_tol=0.11, rel_tol=0):
            raise ValueError('Final government-debt balance components do not reconcile.')
        for code, value in zip(('debt_outstanding', 'general_debt_outstanding', 'special_debt_outstanding'), cells[3:]):
            record(code, value, match[0])
    return rows


def _parse_fujian_2025_completion_pdf(page_texts, province, period):
    """Read explicit local tax and fund/land statements from inspected pages."""
    if (province, str(period)) != ('福建', '2025') or set(page_texts) != {1,3,4,5}:
        raise ValueError('Use the four inspected Fujian annual-completion pages.')
    text = {n:_normalise_pdf_text(t) for n,t in page_texts.items()}
    if ('福建省财政厅2025年全省财政预算执行情况' not in text[1]
            or '一、一般公共预算收入情况' not in text[1]
            or '二、一般公共预算支出情况' not in text[3]
            or '三、政府性基金收入情况' not in text[4]
            or '四、政府性基金支出情况' not in text[5]
            or '福建省财政厅2026年1月26日' not in text[5]):
        raise ValueError('The inspected annual scope, section or signature changed.')
    amount = r'([\d,]+(?:\.\d+)?)亿元'
    specs = [
        ('general_budget_revenue',1,r'地方一般公共预算收入'+amount),
        ('tax_revenue',1,r'地方级税收收入'+amount),
        ('general_budget_expenditure',3,r'一般公共预算支出'+amount),
        ('gov_fund_revenue',4,r'政府性基金收入合计'+amount),
        ('land_transfer_revenue',4,r'国有土地使用权出让收入'+amount),
        ('gov_fund_expenditure',5,r'全省政府性基金支出'+amount),
    ]
    rows=[]
    for code,page,pattern in specs:
        matches=list(re.finditer(pattern,text[page]))
        if len(matches)!=1:
            raise ValueError('One explicit same-unit completion amount is required: '+code)
        match=matches[0]
        rows.append({'country_code':'CN','government_scope':'province_total',
                     'region_code':CN_PROVINCES[province],'region_name':province,
                     'indicator_code':code,'period':str(period),
                     'value':float(match[1].replace(',','')),'unit':'亿元',
                     'frequency':'annual','period_type':'calendar_year',
                     'data_status':'official_preliminary','evidence':match[0],
                     'evidence_page':page,'raw_unit':'亿元'})
    values={r['indicator_code']:r['value'] for r in rows}
    if values['tax_revenue']>values['general_budget_revenue'] or values['land_transfer_revenue']>values['gov_fund_revenue']:
        raise ValueError('A local tax or land component exceeds its same-report parent.')
    return rows


def _parse_shaanxi_issuer_fiscal_pdf(page_texts, province, period):
    """Read the full-province columns, retaining the source's final/execution vintages."""
    period=str(period)
    if province!='陕西' or period not in ('2023','2024','2025') or set(page_texts)!={1,7,8,10}:
        raise ValueError('Use the four reviewed Shaanxi issuer pages and their stated years.')
    text={n:unicodedata.normalize('NFKC',t or '') for n,t in page_texts.items()}
    compact={n:_normalise_pdf_text(t) for n,t in text.items()}
    if ('2026年陕西省政府专项债券(四至九期)信息披露文件' not in compact[1]
            or '信用评级报告' in compact[1]
            or '陕西省财政厅2026年4月22日' not in compact[10]
            or '2023年2024年2025年省本级全省省本级全省省本级全省' not in compact[7]
            or '注:2023-2024年数据为决算数,2025年数据为执行数。' not in compact[8]):
        raise ValueError('Issuer identity, fiscal column groups or vintage note changed.')
    number=r'([\d,]+(?:\.\d+)?)'
    selected=2*(int(period)-2023)+1
    rows=[]

    def record(code,value,evidence,page):
        rows.append({'country_code':'CN','government_scope':'province_total',
                     'region_code':CN_PROVINCES[province],'region_name':province,
                     'indicator_code':code,'period':period,'value':value,'unit':'亿元',
                     'frequency':'annual','period_type':'calendar_year',
                     'data_status':'official_preliminary' if period=='2025' else 'official_final',
                     'evidence':evidence,'evidence_page':page,
                     'raw_unit':'亿元（财政表未另印单位；须与同表历史NBS亿元收支交叉核对）'})

    for code,label in [('general_budget_revenue','一般公共预算收入'),
                       ('general_budget_expenditure','一般公共预算支出'),
                       ('gov_fund_revenue','政府性基金收入'),
                       ('gov_fund_expenditure','政府性基金支出')]:
        pattern=r'^[ \t]*'+label+r'\s+'+r'\s+'.join([number]*6)+r'[ \t]*$'
        matches=list(re.finditer(pattern,text[7],re.MULTILINE))
        if len(matches)!=1:
            raise ValueError('One complete six-column fiscal row is required: '+code)
        match=matches[0]
        record(code,float(match[selected+1].replace(',','')),match[0],7)
    land_pattern=r'^[ \t]*国有土地使用权出让收入\s+-\s+'+number+r'\s+-\s+'+number+r'\s+-\s+'+number+r'[ \t]*$'
    matches=list(re.finditer(land_pattern,text[8],re.MULTILINE))
    if len(matches)!=1:
        raise ValueError('Keep the three explicitly missing province-own land cells separate.')
    match=matches[0]
    record('land_transfer_revenue',float(match[int(period)-2023+1].replace(',','')),match[0],8)
    if period=='2025':
        for code,pattern in [('debt_outstanding',r'截至2025年底,全省政府债务余额'+number+'亿元'),
                             ('general_debt_outstanding',r'全省一般债务余额'+number+'亿元'),
                             ('special_debt_outstanding',r'专项债务余额'+number+'亿元。分级次看')]:
            matches=list(re.finditer(pattern,compact[8]))
            if len(matches)!=1:
                raise ValueError('The full-province closing-debt statement is required: '+code)
            match=matches[0]
            record(code,float(match[1].replace(',','')),match[0],8)
    values={r['indicator_code']:r['value'] for r in rows}
    if values['land_transfer_revenue']>values['gov_fund_revenue']:
        raise ValueError('Land-transfer income exceeds its same-table fund parent.')
    if period=='2025' and not math.isclose(values['debt_outstanding'],values['general_debt_outstanding']+values['special_debt_outstanding'],abs_tol=.011,rel_tol=0):
        raise ValueError('Same-vintage debt components do not reconcile.')
    return rows


def parse_china_fiscal_pdf_pages(page_texts, province, period, profile):
    """Parse selected, visually reviewed table pages; never infer blank cells."""
    if profile in VISUAL_PROFILES:
        return parse_provincial_issuer_visual_pages(page_texts,province,period,profile)
    if profile.startswith('shanghai_'):
        return _parse_shanghai_2025_final_table(page_texts, province, period, profile)
    if profile=='fujian_2025_annual_completion_pdf':
        return _parse_fujian_2025_completion_pdf(page_texts,province,period)
    if profile=='shaanxi_2026_primary_issuer_fiscal':
        return _parse_shaanxi_issuer_fiscal_pdf(page_texts,province,period)
    if (province, str(period), profile) != ('宁夏', '2025', 'ningxia_2025_execution_tables'):
        raise ValueError('A reviewed province/year PDF-table profile is required.')
    required_pages = {5, 6, 95, 96, 97, 98, 187, 188}
    if set(page_texts) != required_pages:
        raise ValueError('All reviewed table pages, including fund continuations, are required.')
    text = {number: unicodedata.normalize('NFKC', value or '')
            for number, value in page_texts.items()}
    headers = {
        5: ('2025年全区地方一般公共预算收入执行情况表', '万元',
            '2024年决算数2025年预算数2025年完成数'),
        6: ('2025年全区一般公共预算支出执行情况表', '万元',
            '2024年决算数2025年变动预算数2025年完成数'),
        95: ('2025年全区政府性基金预算收支执行情况表', '万元',
             '2024年决算数2025年预算数2025年完成数'),
        187: ('2025年全区政府债务基本情况表', '亿元', '政府债务限额政府债务余额'),
        188: ('2025年全区政府债务还本付息情况表', '亿元', '2025年政府债务偿还本金'),
    }
    for number, (heading, unit, columns) in headers.items():
        compact = _normalise_pdf_text(text[number])
        if heading not in compact or '单位:' + unit not in compact or columns not in compact:
            raise ValueError(f'Reviewed table heading, unit or actual-column order changed on page {number}.')
        if number in (5, 6, 95) and '财政快报数' not in compact:
            raise ValueError('The quick-report vintage must remain explicit.')

    number_pattern = r'([\d,]+(?:\.\d+)?)'
    rows = []

    def record(code, value, evidence, page, raw_unit):
        rows.append({'country_code':'CN', 'government_scope':'province_total',
                     'region_code':CN_PROVINCES[province], 'region_name':province,
                     'indicator_code':code, 'period':str(period), 'value':value,
                     'unit':'亿元', 'frequency':'annual', 'period_type':'calendar_year',
                     'data_status':'official_preliminary', 'evidence':evidence,
                     'evidence_page':page, 'raw_unit':raw_unit})

    def actual_cell(page, label, code):
        # Labels may wrap across lines; retain numeric cell separators.
        label_pattern = r'\s*'.join(re.escape(char) for char in label)
        pattern = label_pattern + r'\s+' + r'\s+'.join([number_pattern] * 3)
        matches = list(re.finditer(pattern, text[page]))
        if len(matches) != 1:
            raise ValueError(f'One inspected three-column row is required for {code}.')
        match = matches[0]
        value = float(match[3].replace(',', '')) / 10000
        record(code, value, match[0], page, '万元')
        return value

    revenue = actual_cell(5, '地方一般公共预算收入合计', 'general_budget_revenue')
    tax = actual_cell(5, '一、税收收入', 'tax_revenue')
    actual_cell(6, '一般公共预算支出', 'general_budget_expenditure')
    fund_revenue = actual_cell(98, '收入合计', 'gov_fund_revenue')
    actual_cell(98, '支出合计', 'gov_fund_expenditure')
    land = actual_cell(95, '国有土地使用权出让收入', 'land_transfer_revenue')

    def whole_region_row(page):
        matches = re.findall(r'^[ \t]*全区\s+([^\n]+)', text[page], re.MULTILINE)
        if len(matches) != 1:
            raise ValueError(f'One whole-region row is required on debt page {page}.')
        cells = matches[0].split()
        # This reviewed layout has a blank new-foreign-debt cell on page 188.
        # A zero appearing there would change the index; reject, never shift it.
        if len(cells) != 9 or any(not re.fullmatch(number_pattern, cell) for cell in cells):
            raise ValueError('The inspected debt-row layout changed; do not fill or shift blanks.')
        return [float(cell.replace(',', '')) for cell in cells], '全区 ' + matches[0]

    balance, balance_evidence = whole_region_row(187)
    service, service_evidence = whole_region_row(188)
    if not math.isclose(balance[3], service[7], abs_tol=0.005, rel_tol=0):
        raise ValueError('Same-report debt totals on the two tables do not agree.')
    if not math.isclose(balance[3], sum(balance[4:7]), abs_tol=0.02, rel_tol=0):
        raise ValueError('Bond/special/foreign debt components do not reconcile with the total.')
    record('debt_outstanding', balance[3], balance_evidence, 187, '亿元')
    record('principal_repayment', service[3], service_evidence, 188, '亿元')
    record('interest_expenditure', service[8], service_evidence, 188, '亿元')
    if tax > revenue or land > fund_revenue:
        raise ValueError('A fiscal component exceeds its same-report parent.')
    # The table says general BONDS, not general government DEBT. Do not relabel
    # 1819.70, sum it with foreign debt, or replace the MOF final special-debt row.
    return rows


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
    if '不含' in compact or '本级' in compact or compact in ('合计', '待分配'):
        return None
    for short, code in CN_PROVINCES.items():
        if compact.startswith(short):
            return code, short
    return None


def parse_mof_regional_debt_html(html, indicator_code, period, source_url, require_balance_header=False):
    """Parse the 31 province-total rows from an MOF debt final-account table."""
    soup = BeautifulSoup(html, 'html.parser')
    balance_column = None
    for tr in soup.find_all('tr'):
        headers = [_normalise_pdf_text(cell.get_text(' ',strip=True)) for cell in tr.find_all(['th','td'])]
        if headers and headers[0] in ('地区','地區'):
            candidates = [index for index, header in enumerate(headers)
                          if str(period) in header and '余额' in header and '限额' not in header]
            if len(candidates) == 1:
                balance_column = candidates[0]
                break
    if require_balance_header and balance_column is None:
        raise ValueError('An explicit same-year outstanding-balance column is required; limits are not balances.')
    rows = []
    for tr in soup.find_all('tr'):
        cells = [cell.get_text(' ', strip=True) for cell in tr.find_all(['th', 'td'])]
        if len(cells) < 2:
            continue
        identity = _province_identity(cells[0])
        if not identity:
            continue
        numbers = []
        if balance_column is not None and len(cells) <= balance_column:
            continue
        selected_cells = [cells[balance_column]] if balance_column is not None else cells[1:]
        for cell in selected_cells:
            cell = _normalise_pdf_text(cell)
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
                     'parser_notes': ('财政部全国财政决算分地区表；取年末余额而非限额；仅取31个省级合计行，'
                                      '排除计划单列市及“不含”子行。原行名：' + cells[0] +
                                      '；官方政府债务口径，不是城投企业信用债全口径。')})
    if len(rows) != 31 or len({row['region_code'] for row in rows}) != 31:
        raise ValueError(f'MOF table expected 31 province rows, got {len({r["region_code"] for r in rows})}')
    return rows


def validate_reviewed_regional_fiscal_snapshot(snapshot):
    """Validate observed annual fields while preserving explicitly partial coverage."""
    if snapshot.get('schema_version')!=1 or snapshot.get('review_status')!='source_values_reviewed':
        raise ValueError('A source-value-reviewed regional fiscal snapshot is required.')
    period=str(snapshot['statistical_year'])
    if not re.fullmatch(r'20\d{2}',period) or not snapshot.get('observations'):
        raise ValueError('An annual statistical period and nonempty observed rows are required.')
    keys=set()
    for row in snapshot['observations']:
        if row['country_code']!='CN' or row['government_scope']!='province_total' or CN_PROVINCES.get(row['region_name'])!=row['region_code']:
            raise ValueError('Only known full-province identities are accepted, not city/province-own replacements.')
        if row['period']!=period or row['frequency']!='annual' or row['period_type']!='calendar_year' or row['unit']!='亿元':
            raise ValueError('Annual calendar-period CNY amounts must not be mixed with months or fiscal years.')
        if row['indicator_code'] not in CN_INDICATORS or type(row['value']) not in (int,float) or not math.isfinite(row['value']) or row['value']<0:
            raise ValueError('Invalid or missing fiscal amounts cannot be observations.')
        source=urlsplit(row['source_url'])
        if ((source.scheme!='https' or not (source.hostname or '').endswith('.gov.cn') or source.username or source.password)
                and not reviewed_issuer_fiscal_source(row)):
            raise ValueError('An exact official government source URL is required.')
        if row['data_status'] not in ('official','official_preliminary','official_final','official_relayed'):
            raise ValueError('Scenario/derived/unknown values are not raw fiscal observations.')
        if not row.get('source_name') or not row.get('source_title') or not row.get('parser_notes'):
            raise ValueError('Source, reporting title and scope notes are required.')
        key=(row['region_code'],row['indicator_code'],period)
        if key in keys:raise ValueError('Duplicate fiscal observation grain.')
        keys.add(key)
    by_key={(r['region_code'],r['indicator_code']):r['value'] for r in snapshot['observations']}
    for (region,code),value in by_key.items():
        if code=='tax_revenue' and (region,'general_budget_revenue') in by_key and value>by_key[region,'general_budget_revenue']:
            raise ValueError('Local-budget tax exceeds its same-snapshot general revenue denominator.')
    return keys


def sync_reviewed_regional_fiscal(conn, snapshot_dir=None):
    """Load reviewed source snapshots idempotently; preserve revisions and unrelated data."""
    folder=Path(snapshot_dir) if snapshot_dir else Path(__file__).resolve().parents[1]/'data/regional_fiscal_reviewed'
    result={'inserted':0,'updated':0,'unchanged':0,'errors':[],'snapshots':[]}
    if not folder.exists():return result
    latest={}
    for path in folder.glob('*.json'):
        try:
            snapshot=json.loads(path.read_text(encoding='utf-8'))
            validate_reviewed_regional_fiscal_snapshot(snapshot)
            year=snapshot['statistical_year']
            if year not in latest or snapshot['generated_at']>latest[year][1]['generated_at']:
                latest[year]=(path,snapshot)
        except Exception as exc:result['errors'].append(f'{path.name}: {exc}')
    conn.execute('''CREATE TABLE IF NOT EXISTS regional_fiscal_revision_history (
        id INTEGER PRIMARY KEY, original_row_json TEXT NOT NULL,
        replacement_snapshot TEXT NOT NULL, preserved_at TEXT NOT NULL)''')
    for path,snapshot in (latest[year] for year in sorted(latest)):
        changes={'inserted':0,'updated':0,'unchanged':0}
        try:
            match=re.fullmatch(r'20\d{2}-([a-f0-9]{12})\.json',path.name)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if match and not digest.startswith(match[1]):raise ValueError('Snapshot filename does not match actual bytes.')
            conn.execute('SAVEPOINT reviewed_regional_fiscal')
            for row in snapshot['observations']:
                old=conn.execute('''SELECT * FROM regional_fiscal_observations WHERE country_code=? AND government_scope=?
                    AND region_code=? AND indicator_code=? AND period=?''',
                    (row['country_code'],row['government_scope'],row['region_code'],row['indicator_code'],row['period'])).fetchone()
                if old is not None:
                    columns=[r[1] for r in conn.execute('PRAGMA table_info(regional_fiscal_observations)')]
                    previous=dict(zip(columns,old))
                    if all(previous.get(field)==row.get(field) for field in columns if field not in ('id','updated_at')):
                        changes['unchanged']+=1;continue
                    conn.execute('''INSERT INTO regional_fiscal_revision_history VALUES (NULL,?,?,?)''',
                                 (json.dumps(previous,ensure_ascii=False),path.name,datetime.now().astimezone().isoformat()))
                    changes['updated']+=1
                else:changes['inserted']+=1
                _upsert(conn,row)
            conn.execute('RELEASE reviewed_regional_fiscal')
            for key in changes:result[key]+=changes[key]
            result['snapshots'].append({'file':path.name,'sha256':digest,'year':snapshot['statistical_year'],'observations':len(snapshot['observations'])})
        except Exception as exc:
            try:
                conn.execute('ROLLBACK TO reviewed_regional_fiscal');conn.execute('RELEASE reviewed_regional_fiscal')
            except sqlite3.Error:pass
            result['errors'].append(f'{path.name}: {exc}')
    return result


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
            for row in parse_mof_regional_debt_html(response.content, indicator_code, period, url, require_balance_header=True):
                _upsert(conn, row)
                imported += 1
        except Exception as exc:
            errors.append(f'MOF {period} {indicator_code}: {exc}')
    conn.commit()
    return {'rows': imported, 'errors': errors,
            'status': 'imported' if imported else 'source_blocked'}


def update_regional_fiscal(conn, china_csv_path=None):
    errors = []
    reviewed=sync_reviewed_regional_fiscal(conn)
    errors.extend(reviewed['errors'])
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
    cn_rows = cn['rows'] + live['rows'] + nbs['rows'] + debt['rows'] + reviewed['inserted'] + reviewed['updated']
    return {'success': us_rows > 0 or cn_rows > 0, 'us_rows': us_rows,
            'cn_rows': cn_rows, 'cn_status': live['status'] if live['rows'] else cn['status'],
            'nbs_fiscal_rows': nbs['rows'], 'mof_debt_rows': debt['rows'], 'reviewed_fiscal':reviewed,'errors': errors}


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
            if not other or (code != 'fiscal_balance' and not other['value']): continue
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
