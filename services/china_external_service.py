# -*- coding: utf-8 -*-
"""中国外贸与跨境资金官方数据管线。

来源边界：
- 海关总署英文统计站：进出口当月/累计金额与同比，人民币和美元原始口径；
- 商务部数据中心与官方搜索：实际使用外资、全行业/非金融类对外投资；
- 国家外汇管理局时间序列表：银行结售汇、银行代客涉外收付款及直接投资项。

纪律：不做币种换算；不把银行结售汇或全部跨境收支写成 FDI；缺失保持缺失；
所有写入均幂等，失败不清理旧数据。
"""
from __future__ import annotations

import io
import math
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date, datetime
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from services.china_macro_service import connect, ensure_china_macro_tables


UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 Chrome/124 Safari/537.36')}
TIMEOUT = 40

GACC_LIST_URL = 'http://english.customs.gov.cn/Statistics/Statistics'
MOFCOM_SEARCH_URL = 'http://search.mofcom.gov.cn/search/'
MOFCOM_FDI_API = 'https://data.mofcom.gov.cn/datamofcom/front/lywz/direct/query'
MOFCOM_ODI_API = 'https://data.mofcom.gov.cn/datamofcom/front/tzhz/fordirinvest/dateQuery'
MOFCOM_DATA_URL = 'https://data.mofcom.gov.cn/'
MOFCOM_FEC_BASE = 'https://fec.mofcom.gov.cn/'
MOFCOM_FEC_LIST_API = urljoin(MOFCOM_FEC_BASE, 'edi_ecms_web_front/front/fec/list')
MOFCOM_FEC_LIST_PAGE = urljoin(
    MOFCOM_FEC_BASE, 'list/ggfw/tjsj/ydjmtjsj/1/cateinfo.html')
SAFE_SETTLEMENT_PAGE = 'https://www.safe.gov.cn/safe/2023/0215/22329.html'
SAFE_PAYMENT_PAGE = 'https://www.safe.gov.cn/safe/2018/0419/8806.html'


def _new_session():
    """官方站点偶有连接重置；只做有限重试，不绕过证书或验证页。"""
    session = requests.Session()
    retry = Retry(
        total=3, connect=3, read=2, status=2, backoff_factor=0.45,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(('GET', 'POST')),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


_THREAD_LOCAL = threading.local()


def _worker_session():
    session = getattr(_THREAD_LOCAL, 'session', None)
    if session is None:
        session = _new_session()
        _THREAD_LOCAL.session = session
    return session


def _meta(name, unit, frequency='monthly'):
    return name, unit, frequency


EXTERNAL_INDICATORS = {}
for currency, unit in (('CNY', '亿元'), ('USD', '亿美元')):
    for subject, label in (('TRADE', '货物进出口总额'), ('EXPORT', '货物出口'),
                           ('IMPORT', '货物进口')):
        EXTERNAL_INDICATORS.update({
            f'CN_GACC_{subject}_{currency}_MONTH': _meta(f'{label}当月({currency})', unit),
            f'CN_GACC_{subject}_{currency}_YTD': _meta(f'{label}累计({currency})', unit),
            f'CN_GACC_{subject}_{currency}_MONTH_YOY': _meta(f'{label}当月同比({currency})', '%'),
            f'CN_GACC_{subject}_{currency}_YTD_YOY': _meta(f'{label}累计同比({currency})', '%'),
        })
    EXTERNAL_INDICATORS.update({
        f'CN_GACC_BALANCE_{currency}_MONTH': _meta(f'货物贸易差额当月({currency})', unit),
        f'CN_GACC_BALANCE_{currency}_YTD': _meta(f'货物贸易差额累计({currency})', unit),
        f'CN_MOFCOM_FDI_{currency}_YTD': _meta(f'实际使用外资累计({currency})', unit),
        f'CN_MOFCOM_FDI_{currency}_YTD_YOY': _meta(f'实际使用外资累计同比({currency})', '%'),
        f'CN_MOFCOM_ODI_ALL_{currency}_YTD': _meta(f'全行业对外直接投资累计({currency})', unit),
        f'CN_MOFCOM_ODI_ALL_{currency}_YTD_YOY': _meta(f'全行业对外直接投资累计同比({currency})', '%'),
        f'CN_MOFCOM_ODI_NONFIN_{currency}_YTD': _meta(f'非金融类对外直接投资累计({currency})', unit),
        f'CN_MOFCOM_ODI_NONFIN_{currency}_YTD_YOY': _meta(f'非金融类对外直接投资累计同比({currency})', '%'),
        f'CN_SAFE_FX_SETTLEMENT_{currency}': _meta(f'银行结汇当月({currency})', unit),
        f'CN_SAFE_FX_SALES_{currency}': _meta(f'银行售汇当月({currency})', unit),
        f'CN_SAFE_FX_NET_{currency}': _meta(f'银行结售汇差额当月({currency})', unit),
        f'CN_SAFE_XB_RECEIPTS_{currency}': _meta(f'银行代客涉外收入当月({currency})', unit),
        f'CN_SAFE_XB_PAYMENTS_{currency}': _meta(f'银行代客涉外支出当月({currency})', unit),
        f'CN_SAFE_XB_NET_{currency}': _meta(f'银行代客涉外收支差额当月({currency})', unit),
        f'CN_SAFE_DI_RECEIPTS_{currency}': _meta(f'银行代客直接投资项收入当月({currency})', unit),
        f'CN_SAFE_DI_PAYMENTS_{currency}': _meta(f'银行代客直接投资项支出当月({currency})', unit),
        f'CN_SAFE_DI_NET_{currency}': _meta(f'银行代客直接投资项差额当月({currency})', unit),
    })

EXTERNAL_INDICATORS.update({
    'CN_MOFCOM_FDI_NEW_FIRMS_YTD': _meta('新设外商投资企业累计', '家'),
    'CN_MOFCOM_FDI_NEW_FIRMS_YTD_YOY': _meta('新设外商投资企业累计同比', '%'),
    'CN_MOFCOM_ODI_ENTERPRISES_YTD': _meta('境外非金融类投资企业累计', '家'),
})


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    text = str(value).strip().replace(',', '').replace('，', '')
    if text in ('', '-', '—', '–', '…', '...'):
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


def _period_yyyymm(value):
    text = re.sub(r'\D', '', str(value or ''))
    if len(text) >= 6 and 1980 <= int(text[:4]) <= 2100 and 1 <= int(text[4:6]) <= 12:
        return f'{text[:4]}-{text[4:6]}'
    return None


def _signed(direction, value):
    number = _number(value)
    if number is None:
        return None
    return -abs(number) if direction in ('下降', '减少', '回落') else abs(number)


def _observation(code, period, value, source_name, source_type, source_url,
                 source_title, parser_notes, data_status='official', formula=None):
    if code not in EXTERNAL_INDICATORS or value is None or not period:
        return None
    name, unit, frequency = EXTERNAL_INDICATORS[code]
    return {
        'indicator_code': code, 'indicator_name': name, 'period': period,
        'value': float(value), 'unit': unit, 'frequency': frequency,
        'data_status': data_status, 'source_name': source_name,
        'source_type': source_type, 'source_url': source_url,
        'source_title': source_title, 'parser_notes': parser_notes,
        'formula': formula,
    }


def upsert_external_observations(conn, rows):
    now, count = datetime.now().isoformat(), 0
    for row in rows:
        if not row:
            continue
        cur = conn.execute('''INSERT INTO china_macro_observations (
            indicator_code,indicator_name,period,value,unit,frequency,data_status,
            source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(indicator_code,period) DO UPDATE SET
            indicator_name=excluded.indicator_name,value=excluded.value,
            unit=excluded.unit,frequency=excluded.frequency,
            data_status=excluded.data_status,source_name=excluded.source_name,
            source_type=excluded.source_type,source_url=excluded.source_url,
            source_title=excluded.source_title,parser_notes=excluded.parser_notes,
            formula=excluded.formula,updated_at=excluded.updated_at''', (
            row['indicator_code'], row['indicator_name'], row['period'], row['value'],
            row['unit'], row['frequency'], row['data_status'], row['source_name'],
            row['source_type'], row['source_url'], row['source_title'],
            row['parser_notes'], row.get('formula'), now))
        count += cur.rowcount
    conn.commit()
    return count


# ── 海关总署：双币种贸易 ──────────────────────────────────────────────────────

_MONTHS = {name: index for index, name in enumerate(
           ('jan', 'feb', 'mar', 'apr', 'may', 'jun',
            'jul', 'aug', 'sep', 'oct', 'nov', 'dec'), 1)}


def parse_gacc_title(title):
    text = re.sub(r'\s+', ' ', title or '').strip()
    combined = re.search(
        r"Total Export\s*&\s*Import Values,\s*(?:January|Jan\.?)[-–—]"
        r"(?:February|Feb\.?)\s*(20\d{2}).*?\(in\s*(CNY|USD)\)", text, re.I)
    if combined:
        return f'{combined.group(1)}-02', combined.group(2).upper()
    match = re.search(r"Total Export\s*&\s*Import Values,\s*([A-Za-z]+)\.?\s*(20\d{2}).*?\(in\s*(CNY|USD)\)",
                      text, re.I)
    if not match:
        return None, None
    month = _MONTHS.get(match.group(1)[:3].lower())
    return (f'{match.group(2)}-{month:02d}', match.group(3).upper()) if month else (None, None)


def parse_gacc_article(html, title='', source_url=''):
    soup = BeautifulSoup(html or '', 'html.parser')
    page_title = title or (soup.find('tr').get_text(' ', strip=True) if soup.find('tr') else '')
    period, currency = parse_gacc_title(page_title)
    if not period:
        return []
    labels = {
        'Total Export & Import': 'TRADE', 'Total Export': 'EXPORT',
        'Total Import': 'IMPORT', 'Export-Import Balance': 'BALANCE',
    }
    rows = []
    for tr in soup.find_all('tr'):
        cells = [re.sub(r'\s+', ' ', cell.get_text(' ', strip=True)).strip()
                 for cell in tr.find_all(['td', 'th'])]
        if not cells or cells[0] not in labels:
            continue
        subject = labels[cells[0]]
        values = [_number(value) for value in cells[1:]]
        if subject == 'BALANCE':
            pairs = ((f'CN_GACC_BALANCE_{currency}_MONTH', values[0] if values else None),
                     (f'CN_GACC_BALANCE_{currency}_YTD', values[1] if len(values) > 1 else None))
        else:
            pairs = (
                (f'CN_GACC_{subject}_{currency}_MONTH', values[0] if values else None),
                (f'CN_GACC_{subject}_{currency}_YTD', values[1] if len(values) > 1 else None),
                (f'CN_GACC_{subject}_{currency}_MONTH_YOY', values[3] if len(values) > 3 else None),
                (f'CN_GACC_{subject}_{currency}_YTD_YOY', values[4] if len(values) > 4 else None),
            )
        for code, value in pairs:
            row = _observation(
                code, period, value, '海关总署', 'gacc_trade', source_url,
                page_title, '海关总署月度总值表原始币种；未做汇率换算')
            if row:
                rows.append(row)
    return rows


def _fetch_gacc_listing_page(page, session=None):
    active = session or _worker_session()
    response = active.get(GACC_LIST_URL, params={'page': page}, headers=UA, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or 'utf-8'
    return page, response.text


def _parse_gacc_listing_page(html):
    links, periods = [], []
    for anchor in BeautifulSoup(html, 'html.parser').find_all('a', href=True):
        title = re.sub(r'\s+', ' ', anchor.get_text(' ', strip=True)).strip()
        if not re.match(r"^\(1\)\s*China's Total Export\s*&\s*Import Values", title, re.I):
            continue
        period, currency = parse_gacc_title(title)
        if period:
            periods.append(period)
            links.append((period, currency, urljoin(GACC_LIST_URL, anchor['href']), title))
    return periods, links


def discover_gacc_releases(start_year, max_pages=180, sleep_seconds=0.12, session=None):
    session = session or _new_session()
    found, empty_pages = {}, 0
    parallel = max_pages > 60
    page = 1
    executor = ThreadPoolExecutor(max_workers=3) if parallel else None
    try:
        while page <= max_pages:
            batch = list(range(page, min(max_pages + 1, page + (9 if parallel else 1))))
            if parallel:
                fetched = executor.map(lambda number: _fetch_gacc_listing_page(number), batch)
            else:
                fetched = [_fetch_gacc_listing_page(batch[0], session)]
            should_stop = False
            for _, html in sorted(fetched):
                page_periods, links = _parse_gacc_listing_page(html)
                for period, currency, url, title in links:
                    if int(period[:4]) >= int(start_year):
                        found[(period, currency)] = (url, title)
                empty_pages = empty_pages + 1 if not page_periods else 0
                if page_periods and max(int(period[:4]) for period in page_periods) < int(start_year):
                    should_stop = True
                if empty_pages >= 3:
                    should_stop = True
            if should_stop:
                break
            page = batch[-1] + 1
            time.sleep(sleep_seconds)
    finally:
        if executor:
            executor.shutdown(wait=True)
    return found


def update_gacc_trade(conn, start_year, max_pages=180, sleep_seconds=0.12, session=None):
    session = session or _new_session()
    errors, parsed = [], []
    try:
        releases = discover_gacc_releases(start_year, max_pages, sleep_seconds, session)
    except Exception as exc:
        return {'records_upserted': 0, 'releases': 0, 'errors': [f'discover: {exc}']}
    release_items = [(url, title) for (_, _), (url, title) in sorted(releases.items())]

    def fetch(item):
        url, title = item
        try:
            active = _worker_session() if len(release_items) > 60 else session
            response = active.get(url, headers=UA, timeout=TIMEOUT)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'
            return parse_gacc_article(response.text, title, url), None
        except Exception as exc:
            return [], f'{title}: {exc}'

    if len(release_items) > 60:
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = executor.map(fetch, release_items)
            for rows, error in results:
                parsed.extend(rows)
                if error:
                    errors.append(error)
    else:
        for item in release_items:
            rows, error = fetch(item)
            parsed.extend(rows)
            if error:
                errors.append(error)
            time.sleep(sleep_seconds)
    return {'records_upserted': upsert_external_observations(conn, parsed),
            'releases': len(releases), 'observations_parsed': len(parsed), 'errors': errors}


# ── 国家外汇管理局：结售汇与涉外收付款时间序列 ───────────────────────────────

def _discover_safe_attachment(page_url, link_keyword, session=None):
    session = session or _new_session()
    response = session.get(page_url, headers=UA, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or 'utf-8'
    for anchor in BeautifulSoup(response.text, 'html.parser').find_all('a', href=True):
        text = re.sub(r'\s+', '', anchor.get_text(' ', strip=True))
        if link_keyword in text and '时间序列' in text:
            return urljoin(page_url, anchor['href'])
    raise ValueError(f'未发现{link_keyword}时间序列附件')


def _excel_month(value, datemode=0):
    if isinstance(value, datetime):
        return value.strftime('%Y-%m')
    if isinstance(value, date):
        return value.strftime('%Y-%m')
    if isinstance(value, (int, float)):
        try:
            import xlrd
            return xlrd.xldate_as_datetime(float(value), datemode).strftime('%Y-%m')
        except Exception:
            return None
    text = str(value or '').strip()
    match = re.search(r'(20\d{2})[年./-]?(1[0-2]|0?[1-9])', text)
    return f'{match.group(1)}-{int(match.group(2)):02d}' if match else None


def parse_safe_wide_rows(headers, value_rows, code_by_row, source_name, source_type,
                         source_url, source_title, datemode=0):
    """解析 SAFE 横向月份表；公开为纯函数，测试可用小型列表而非二进制工作簿。"""
    observations = []
    for column, raw_date in enumerate(headers):
        period = _excel_month(raw_date, datemode)
        if not period:
            continue
        for row_key, values in value_rows.items():
            value = _number(values[column]) if column < len(values) else None
            code = code_by_row.get(row_key)
            row = _observation(
                code, period, value, source_name, source_type, source_url, source_title,
                '外汇局官方月度时间序列表原值；差额采用官方表中差额行，未做币种换算')
            if row:
                observations.append(row)
    return observations


def _parse_safe_settlement_workbook(content, attachment_url):
    import openpyxl
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    observations = []
    for currency, sheet_name in (('CNY', '以人民币计价（月度）'),
                                 ('USD', '以美元计价（月度）')):
        sheet = workbook[sheet_name]
        raw = [list(row) for row in sheet.iter_rows(min_row=1, max_row=45,
                                                     max_col=420, values_only=True)]
        labels = {str(row[0]).strip(): index for index, row in enumerate(raw) if row and row[0]}
        header_index = next(index for index, row in enumerate(raw)
                            if row and str(row[0]).strip() == '项目')
        headers = raw[header_index]
        row_names = {'settlement': '一、结汇', 'sales': '二、售汇', 'net': '三、差额'}
        value_rows = {key: raw[labels[label]] for key, label in row_names.items()}
        codes = {
            'settlement': f'CN_SAFE_FX_SETTLEMENT_{currency}',
            'sales': f'CN_SAFE_FX_SALES_{currency}',
            'net': f'CN_SAFE_FX_NET_{currency}',
        }
        observations.extend(parse_safe_wide_rows(
            headers, value_rows, codes, '国家外汇管理局', 'safe_fx_settlement',
            attachment_url, '银行结售汇数据时间序列'))
    return observations


def _parse_safe_payment_workbook(content, attachment_url):
    import xlrd
    workbook = xlrd.open_workbook(file_contents=content)
    observations = []
    for currency, sheet_name in (('CNY', '以人民币计值（月度）'),
                                 ('USD', '以美元计值（月度）')):
        sheet = workbook.sheet_by_name(sheet_name)
        matrix = [sheet.row_values(index) for index in range(sheet.nrows)]
        header_index = next(index for index, row in enumerate(matrix)
                            if row and str(row[0]).strip() == '项目')
        top_rows, direct_rows = {}, []
        for index, row in enumerate(matrix):
            label = re.sub(r'\s+', '', str(row[0] if row else ''))
            if label == '一、收入':
                top_rows['receipts'] = row
            elif label == '二、支出':
                top_rows['payments'] = row
            elif label == '三、收支差额':
                top_rows['net'] = row
            elif label in ('其中：直接投资', '其中:直接投资'):
                direct_rows.append(row)
        if len(direct_rows) < 3 or len(top_rows) < 3:
            raise ValueError(f'{sheet_name} 行标签结构不完整')
        value_rows = {
            **top_rows, 'di_receipts': direct_rows[0],
            'di_payments': direct_rows[1], 'di_net': direct_rows[2],
        }
        codes = {
            'receipts': f'CN_SAFE_XB_RECEIPTS_{currency}',
            'payments': f'CN_SAFE_XB_PAYMENTS_{currency}',
            'net': f'CN_SAFE_XB_NET_{currency}',
            'di_receipts': f'CN_SAFE_DI_RECEIPTS_{currency}',
            'di_payments': f'CN_SAFE_DI_PAYMENTS_{currency}',
            'di_net': f'CN_SAFE_DI_NET_{currency}',
        }
        observations.extend(parse_safe_wide_rows(
            matrix[header_index], value_rows, codes, '国家外汇管理局',
            'safe_cross_border_payments', attachment_url,
            '银行代客涉外收付款数据时间序列', workbook.datemode))
    return observations


def update_safe_flows(conn, session=None):
    session = session or _new_session()
    errors, rows, attachments = [], [], {}
    jobs = (
        ('settlement', SAFE_SETTLEMENT_PAGE, '银行结售汇数据', _parse_safe_settlement_workbook),
        ('payments', SAFE_PAYMENT_PAGE, '银行代客涉外收付款数据', _parse_safe_payment_workbook),
    )
    for key, page_url, keyword, parser in jobs:
        try:
            attachment = _discover_safe_attachment(page_url, keyword, session)
            response = session.get(attachment, headers=UA, timeout=TIMEOUT)
            response.raise_for_status()
            attachments[key] = attachment
            rows.extend(parser(response.content, attachment))
        except Exception as exc:
            errors.append(f'{key}: {exc}')
    return {'records_upserted': upsert_external_observations(conn, rows),
            'observations_parsed': len(rows), 'attachments': attachments, 'errors': errors}


# ── 商务部：吸收外资与对外直接投资 ────────────────────────────────────────────

def _mofcom_period(text):
    compact = re.sub(r'\s+', '', text or '')
    match = re.search(
        r'(20\d{2})年(?:(?:1|一)[—\-至](\d{1,2})月|前(\d{1,2})个月|'
        r'(\d{1,2})月|(一季度|上半年|前三季度|全年))', compact)
    if not match:
        # “2025年全国吸收外资……”这类不带月份的年度发布才回落到 12 月；
        # 不能用可选月份正则，否则“一季度”会先被裸年份吞掉并误记为全年。
        match = re.search(r'(20\d{2})年(?=[，,:：]?(?:全年)?(?:全国|我国).{0,18}'
                          r'(?:吸收外资|外商投资|全行业对外直接投资))',
                          compact)
        return f'{match.group(1)}-12' if match else None
    quarter_months = {'一季度': 3, '上半年': 6, '前三季度': 9, '全年': 12}
    month = int(match.group(2) or match.group(3) or match.group(4) or
                quarter_months.get(match.group(5), 12))
    return f'{match.group(1)}-{month:02d}'


def parse_mofcom_fdi_text(title, summary='', source_url=''):
    period = _mofcom_period(summary) or _mofcom_period(title)
    text = re.sub(r'\s+', '', summary or '')
    title_text = re.sub(r'\s+', '', title or '')
    # 年末发布常在同一篇正文先列全年累计、后列“12月当月”。YTD 指标只能读取
    # 当月段之前的累计句；否则 2017 年会把 8775.6 亿元误写成当月 739.4 亿元。
    current_month = re.search(r'(?:\d{1,2}月)?当月', text)
    cumulative_text = text[:current_month.start()] if current_month else text
    values = {}
    amount = re.search(
        r'(?:实际使用外资(?:金额)?|全国吸收外资)([\d.]+)亿元(?:人民币)?',
        cumulative_text)
    if not amount:
        amount = re.search(
            r'(?:实际使用外资(?:金额)?|全国吸收外资)([\d.]+)亿元(?:人民币)?',
            title_text)
    if amount:
        values['CN_MOFCOM_FDI_CNY_YTD'] = float(amount.group(1))
    yoy = re.search(
        r'实际使用外资(?:金额)?[\d.]+亿元(?:人民币)?，?(?:同比|比上年)'
        r'(增长|下降)([\d.]+)%', cumulative_text)
    if yoy:
        values['CN_MOFCOM_FDI_CNY_YTD_YOY'] = _signed(yoy.group(1), yoy.group(2))
    firms = re.search(
        r'新设立外商投资企业(\d+)家，?(?:同比|比上年)(增长|下降)([\d.]+)%',
        cumulative_text)
    if firms:
        values['CN_MOFCOM_FDI_NEW_FIRMS_YTD'] = float(firms.group(1))
        values['CN_MOFCOM_FDI_NEW_FIRMS_YTD_YOY'] = _signed(firms.group(2), firms.group(3))
    return [_observation(code, period, value, '商务部', 'mofcom_fdi', source_url,
                         title, '商务部吸收外资官方发布；累计口径')
            for code, value in values.items() if value is not None]


def parse_mofcom_odi_text(title, summary='', source_url=''):
    period = _mofcom_period(summary) or _mofcom_period(title)
    text = re.sub(r'\s+', '', summary or '')
    values = {}
    all_match = re.search(
        r'全行业对外直接投资([\d.]+)亿元人民币，?(?:同比|比上年)(增长|下降)([\d.]+)%'
        r'（以美元计为([\d.]+)亿美元，?(增长|下降)([\d.]+)%）', text)
    if all_match:
        values.update({
            'CN_MOFCOM_ODI_ALL_CNY_YTD': float(all_match.group(1)),
            'CN_MOFCOM_ODI_ALL_CNY_YTD_YOY': _signed(all_match.group(2), all_match.group(3)),
            'CN_MOFCOM_ODI_ALL_USD_YTD': float(all_match.group(4)),
            'CN_MOFCOM_ODI_ALL_USD_YTD_YOY': _signed(all_match.group(5), all_match.group(6)),
        })
    nonfin = re.search(
        r'非金融类直接投资，?累计投资([\d.]+)亿元人民币，?(增长|下降)([\d.]+)%'
        r'（以美元计为([\d.]+)亿美元，?(增长|下降)([\d.]+)%）', text)
    if nonfin:
        values.update({
            'CN_MOFCOM_ODI_NONFIN_CNY_YTD': float(nonfin.group(1)),
            'CN_MOFCOM_ODI_NONFIN_CNY_YTD_YOY': _signed(nonfin.group(2), nonfin.group(3)),
            'CN_MOFCOM_ODI_NONFIN_USD_YTD': float(nonfin.group(4)),
            'CN_MOFCOM_ODI_NONFIN_USD_YTD_YOY': _signed(nonfin.group(5), nonfin.group(6)),
        })
    return [_observation(code, period, value, '商务部、国家外汇管理局', 'mofcom_odi',
                         source_url, title, '商务部对外投资官方发布；累计口径')
            for code, value in values.items() if value is not None]


def _mofcom_search_records(query_text, max_pages, session=None, sleep_seconds=0.12):
    session = session or _new_session()
    records, seen = [], set()
    for page in range(1, max_pages + 1):
        response = session.get(MOFCOM_SEARCH_URL, params={
            'keyWordType': 'title', 'acSuggest': query_text, 'page': page,
        }, headers=UA, timeout=TIMEOUT)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        page_count = 0
        for item in soup.select('li'):
            anchor = item.select_one('a.a2[href]') or item.select_one('.title a[href]')
            if not anchor:
                continue
            title = re.sub(r'\s+', ' ', anchor.get_text(' ', strip=True)).strip()
            if not title or not _mofcom_period(title):
                continue
            url = urljoin(MOFCOM_SEARCH_URL, anchor['href'])
            summary_node = item.select_one('.summary')
            summary = re.sub(r'\s+', ' ', summary_node.get_text(' ', strip=True)).strip() if summary_node else ''
            key = (url, title, summary)
            if key not in seen:
                seen.add(key)
                records.append({'title': title, 'summary': summary, 'url': url})
                page_count += 1
        if page_count == 0 and page > 1:
            break
        time.sleep(sleep_seconds)
    return records


def _mofcom_fec_odi_records(years, session=None, sleep_seconds=0.08):
    """从商务部对外投资合作司官方列表补最新 ODI 发布。

    该列表接口的中文标题目前会被服务端替换成问号，因此只使用其 URL/发布日期，
    再读取文章正文并用完整统计句筛选；不从问号标题推断任何数值。
    """
    session = session or _new_session()
    records, seen = [], set()
    headers = {**UA, 'Referer': MOFCOM_FEC_LIST_PAGE}
    for year in years:
        page, max_page = 1, 1
        while page <= max_page:
            response = session.post(MOFCOM_FEC_LIST_API, data={
                'pageNumber': page, 'cid': 'ggfw/tjsj/ydjmtjsj', 'year': int(year),
            }, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            info = payload.get('pageInfo') or {}
            max_page = int(info.get('maxPageNum') or 1)
            for raw in info.get('rows') or []:
                url = urljoin(MOFCOM_FEC_BASE, raw.get('url') or '')
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    article = session.get(url, headers=UA, timeout=TIMEOUT)
                    article.raise_for_status()
                    article.encoding = article.apparent_encoding or 'utf-8'
                    text = re.sub(r'\s+', ' ', BeautifulSoup(
                        article.text, 'html.parser').get_text(' ', strip=True))
                    if '全行业对外直接投资' not in text or '非金融类直接投资' not in text:
                        continue
                    compact = re.sub(r'\s+', '', text)
                    match = re.search(r'(20\d{2}年(?:1[—\-至]\d{1,2}月|\d{1,2}月|上半年|全年)?)，?我国全行业对外直接投资',
                                      compact)
                    title = ((match.group(1) if match else str(year) + '年') +
                             '我国全行业对外直接投资简明统计')
                    records.append({'title': title, 'summary': text, 'url': url})
                except Exception:
                    # 单篇失败由上层搜索/API互补；列表继续，不清旧记录。
                    continue
                time.sleep(sleep_seconds)
            page += 1
    return records


def _mofcom_api_rows(session=None):
    session = session or _new_session()
    headers = {**UA, 'Referer': MOFCOM_DATA_URL}
    rows, errors = [], []
    try:
        payload = session.post(MOFCOM_FDI_API, json={}, headers=headers, timeout=TIMEOUT).json()
        for raw in payload[0] if payload and isinstance(payload[0], list) else []:
            period = _period_yyyymm(raw.get('data_time'))
            pairs = (
                ('CN_MOFCOM_FDI_USD_YTD', _number(raw.get('actual_amount'))),
                ('CN_MOFCOM_FDI_USD_YTD_YOY', _number(raw.get('actual_amount_per'))),
                ('CN_MOFCOM_FDI_NEW_FIRMS_YTD', _number(raw.get('project_number'))),
                ('CN_MOFCOM_FDI_NEW_FIRMS_YTD_YOY', _number(raw.get('project_per'))),
            )
            for code, value in pairs:
                item = _observation(code, period, value, '商务部', 'mofcom_data_api',
                                    MOFCOM_DATA_URL, '吸收外商直接投资月报图表',
                                    '商务部数据中心官方接口；美元累计值按原表保存')
                if item:
                    rows.append(item)
    except Exception as exc:
        errors.append(f'fdi api: {exc}')
    try:
        payload = session.post(MOFCOM_ODI_API, json={}, headers=headers, timeout=TIMEOUT).json()
        for raw in payload[0] if payload and isinstance(payload[0], list) else []:
            period = _period_yyyymm(raw.get('time'))
            pairs = (
                ('CN_MOFCOM_ODI_NONFIN_USD_YTD', _number(raw.get('non_financial'))),
                ('CN_MOFCOM_ODI_NONFIN_USD_YTD_YOY', _number(raw.get('yoy'))),
                ('CN_MOFCOM_ODI_ENTERPRISES_YTD', _number(raw.get('num_enterprice'))),
            )
            for code, value in pairs:
                item = _observation(code, period, value, '商务部', 'mofcom_data_api',
                                    MOFCOM_DATA_URL, '非金融类对外直接投资月报图表',
                                    '商务部数据中心官方接口；美元累计值按原表保存')
                if item:
                    rows.append(item)
    except Exception as exc:
        errors.append(f'odi api: {exc}')
    return rows, errors


def update_mofcom_investment(conn, full_history=False, session=None):
    session = session or _new_session()
    rows, errors = _mofcom_api_rows(session)
    jobs = (
        ('全国吸收外资', 18 if full_history else 4, parse_mofcom_fdi_text),
        ('全行业对外直接投资简明统计', 12 if full_history else 4, parse_mofcom_odi_text),
    )
    for query_text, pages, parser in jobs:
        try:
            for record in _mofcom_search_records(query_text, pages, session):
                summary = record['summary']
                if parser is parse_mofcom_fdi_text:
                    try:
                        article = session.get(record['url'], headers=UA, timeout=TIMEOUT)
                        article.raise_for_status()
                        article.encoding = article.apparent_encoding or 'utf-8'
                        summary = BeautifulSoup(article.text, 'html.parser').get_text(' ', strip=True)
                    except Exception:
                        # 搜索摘要仍可作为降级输入；解析器会在“当月”之前找累计句。
                        summary = summary or ''
                rows.extend(parser(record['title'], summary, record['url']))
        except Exception as exc:
            errors.append(f'{query_text}: {exc}')
    try:
        current_year = datetime.now().year
        fec_years = range(2021 if full_history else current_year - 1, current_year + 1)
        for record in _mofcom_fec_odi_records(fec_years, session):
            rows.extend(parse_mofcom_odi_text(
                record['title'], record['summary'], record['url']))
    except Exception as exc:
        errors.append(f'对外投资合作司列表: {exc}')
    # 一篇商务部官方文章只对应一个累计统计期。若此前把发布日期年份或季度误作
    # 全年，仅清理同 code + 同 source_url 的错误期重复；绝不按模块清空旧数据。
    valid_periods = {}
    for row in rows:
        if (row and row.get('source_type') in ('mofcom_fdi', 'mofcom_odi')
                and row.get('source_url') not in (MOFCOM_DATA_URL, '')):
            valid_periods[(row['indicator_code'], row['source_url'])] = row['period']
    corrected = 0
    for (code, url), period in valid_periods.items():
        cur = conn.execute('''DELETE FROM china_macro_observations
                              WHERE indicator_code=? AND source_url=? AND period<>?''',
                           (code, url, period))
        corrected += cur.rowcount
    conn.commit()
    return {'records_upserted': upsert_external_observations(conn, rows),
            'observations_parsed': len(rows), 'period_rows_corrected': corrected,
            'errors': errors}


def update_china_external(db_path, full_history=False, start_year=None, sleep_seconds=0.12):
    """更新三组外部官方源。默认回查近两年海关页；full_history 回填到 start_year。"""
    started = datetime.now().isoformat()
    start = int(start_year or (2015 if full_history else datetime.now().year - 1))
    max_gacc_pages = 360 if full_history else 30
    session = _new_session()
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        safe = update_safe_flows(conn, session)
        mofcom = update_mofcom_investment(conn, full_history, session)
        gacc = update_gacc_trade(conn, start, max_gacc_pages, sleep_seconds, session)
    total = sum(item.get('records_upserted', 0) for item in (safe, mofcom, gacc))
    errors = safe.get('errors', []) + mofcom.get('errors', []) + gacc.get('errors', [])
    return {
        'success': total > 0 or not errors, 'started_at': started,
        'finished_at': datetime.now().isoformat(), 'records_upserted': total,
        'start_year': start, 'full_history': bool(full_history),
        'safe': safe, 'mofcom': mofcom, 'gacc': gacc, 'errors': errors,
    }
