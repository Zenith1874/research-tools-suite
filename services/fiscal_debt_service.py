import html as html_lib
import json
import re
import sqlite3
import urllib.request
from datetime import datetime
from urllib.parse import urljoin


MOF_LOCAL_DEBT_INDEX = 'https://zwgls.mof.gov.cn/tjsj/'
KNOWN_LOCAL_DEBT_URLS = [
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202606/t20260611_3991502.htm', 'title': '2026年4月地方政府债券发行和债务余额情况'},
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202605/t20260508_3989284.htm', 'title': '2026年3月地方政府债券发行和债务余额情况'},
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202603/t20260309_3984956.htm', 'title': '2026年1月地方政府债券发行和债务余额情况'},
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202601/t20260130_3983021.htm', 'title': '2025年12月地方政府债券发行和债务余额情况'},
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202511/t20251128_3977820.htm', 'title': '2025年10月地方政府债券发行和债务余额情况'},
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202511/t20251101_3975527.htm', 'title': '2025年9月地方政府债券发行和债务余额情况'},
]

LOCAL_DEBT_FIELDS = {
    'local_debt_balance_total': ('地方政府债务余额', '亿元', 'official'),
    'local_general_debt_balance': ('一般债务余额', '亿元', 'official'),
    'local_special_debt_balance': ('专项债务余额', '亿元', 'official'),
    'local_bond_balance': ('政府债券余额', '亿元', 'official'),
    'local_non_bond_debt_balance': ('非政府债券形式存量政府债务', '亿元', 'official'),
    'local_bond_issuance_current_month': ('地方政府债券当月发行合计', '亿元', 'official'),
    'local_bond_issuance_ytd': ('地方政府债券年初至今发行合计', '亿元', 'official'),
    'local_general_bond_issuance_ytd': ('一般债券年初至今发行', '亿元', 'official'),
    'local_special_bond_issuance_ytd': ('专项债券年初至今发行', '亿元', 'official'),
    'local_new_bond_issuance_ytd': ('新增地方政府债券年初至今发行', '亿元', 'official'),
    'local_refinancing_bond_issuance_ytd': ('再融资债券年初至今发行', '亿元', 'official'),
    'official_principal_repayment_current_month': ('当月到期偿还本金', '亿元', 'official'),
    'official_principal_repayment_ytd': ('年初至今到期偿还本金', '亿元', 'official'),
    'official_refinancing_repayment_ytd': ('发行再融资债券偿还本金', '亿元', 'official'),
    'official_fiscal_funds_repayment_ytd': ('安排财政资金等偿还本金', '亿元', 'official'),
    'official_interest_payment_current_month': ('当月支付利息', '亿元', 'official'),
    'official_interest_payment_ytd': ('年初至今支付利息', '亿元', 'official'),
    'local_bond_avg_remaining_maturity': ('地方政府债券剩余平均年限', '年', 'official'),
    'local_general_bond_avg_remaining_maturity': ('一般债券剩余平均年限', '年', 'official'),
    'local_special_bond_avg_remaining_maturity': ('专项债券剩余平均年限', '年', 'official'),
    'local_bond_avg_interest_rate': ('地方政府债券平均利率', '%', 'official'),
    'local_general_bond_avg_interest_rate': ('一般债券平均利率', '%', 'official'),
    'local_special_bond_avg_interest_rate': ('专项债券平均利率', '%', 'official'),
}

TREASURY_FIELDS = {
    'treasury_debt_balance_total': '国债余额',
    'treasury_bond_issuance_current_month': '国债当月发行',
    'treasury_bond_issuance_ytd': '国债年初至今发行',
    'treasury_principal_repayment_current_month': '国债当月还本',
    'treasury_principal_repayment_ytd': '国债年初至今还本',
    'treasury_interest_payment_current_month': '国债当月付息',
    'treasury_interest_payment_ytd': '国债年初至今付息',
    'treasury_avg_remaining_maturity': '国债平均剩余年限',
}

LGFV_FIELDS = {
    'lgfv_bond_balance': '城投债余额',
    'lgfv_bond_issuance_current_month': '城投债当月发行',
    'lgfv_bond_issuance_ytd': '城投债年初至今发行',
    'lgfv_bond_maturity_current_month': '城投债当月到期',
    'lgfv_bond_maturity_ytd': '城投债年初至今到期',
    'lgfv_interest_payment_current_month': '城投债当月付息',
    'lgfv_interest_payment_ytd': '城投债年初至今付息',
}

FISCAL_GAP_FIELDS = {
    'local_fiscal_revenue_total': '地方财政收入合计',
    'local_public_budget_revenue': '地方一般公共预算收入',
    'local_gov_fund_revenue': '地方政府性基金收入',
    'local_fiscal_expenditure_total': '地方财政支出合计',
    'local_public_budget_expenditure': '地方一般公共预算支出',
    'local_gov_fund_expenditure': '地方政府性基金支出',
    'local_fiscal_balance': '地方财政收支差额',
    'central_to_local_transfer': '中央对地方转移支付',
    'local_absolute_gap': '地方财政绝对缺口测算',
}

FISCAL_SOURCE_REGISTRY = {
    'mof_local_debt_statistics': {
        'source_name': '财政部债务管理司',
        'source_type': 'mof_local_debt',
        'source_label': '财政部债务管理司：统计数据',
        'entry_url': MOF_LOCAL_DEBT_INDEX,
        'candidate_paths': ['债务管理司 / 统计数据'],
        'parser_notes': '用于发现每月“地方政府债券发行和债务余额情况”原文页面。'
    },
    'mof_budget_local_debt_backup': {
        'source_name': '财政部预算司',
        'source_type': 'mof_local_debt',
        'source_label': '财政部预算司：地方政府债务管理 / 数据统计（备用）',
        'entry_url': 'https://yss.mof.gov.cn/zhuantilanmu/dfzgl/sjtj/',
        'candidate_paths': ['预算司 / 地方政府债务管理 / 数据统计'],
        'parser_notes': '地方政府债务数据备用入口。'
    },
    'treasury_debt_placeholder': {
        'source_name': '财政部/债券市场公开信息',
        'source_type': 'treasury_debt',
        'source_label': '国债数据源待接入',
        'entry_url': None,
        'candidate_paths': [
            '财政部国债管理相关公告 / 国债发行兑付公告',
            '中国债券信息网',
            '中央国债登记结算有限责任公司相关公开统计',
            '上海证券交易所 / 深圳证券交易所债券信息公开页面',
        ],
        'parser_notes': '仅登记候选来源；未实现稳定抓取前 API 返回 missing，不生成 mock。'
    },
    'mof_treasury_bond_issuance': {
        'source_name': '财政部债务管理司',
        'source_type': 'mof_treasury_bond',
        'source_label': '财政部债务管理司：业务公告 / 国债发行明细',
        'entry_url': 'https://zwgls.mof.gov.cn/ywgg/',
        'candidate_paths': ['债务管理司 / 业务公告 / 国债业务公告', '债务管理司 / 业务公告 / 国债发行工作通知'],
        'parser_notes': '用于发现逐只国债发行通知、续发行通知和招标结果公告；主口径只汇总 actual_issue_amount，planned_only 不计入实际发行。'
    },
    'lgfv_placeholder': {
        'source_name': 'Wind/Choice/中债/交易所等待接入',
        'source_type': 'lgfv_debt',
        'source_label': '城投债 / LGFV 数据源待接入',
        'entry_url': None,
        'candidate_paths': ['Wind', 'Choice', '中国债券信息网', '交易所债券信息公开'],
        'parser_notes': '城投债不是财政部官方政府债务余额；未接入可靠数据源前不纳入官方地方政府债务。'
    },
    'fiscal_gap_placeholder': {
        'source_name': '财政部',
        'source_type': 'fiscal_gap',
        'source_label': '财政缺口测算数据源待接入',
        'entry_url': 'https://www.mof.gov.cn/',
        'candidate_paths': ['预算执行报告', '财政收支情况', '年度财政决算'],
        'parser_notes': '财政缺口为测算口径，不等于官方赤字定义。'
    },
}

DATA_STATUS = [
    'official', 'derived', 'projected_from_bond_schedule', 'rough_estimate',
    'scenario', 'cache', 'missing', 'error'
]


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _add_col(conn, table, col, typ):
    try:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
    except sqlite3.OperationalError:
        pass


def ensure_fiscal_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_debt_observations (
        id INTEGER PRIMARY KEY,
        debt_line TEXT,
        indicator_code TEXT,
        indicator_name TEXT,
        value REAL,
        unit_raw TEXT,
        unit_display TEXT,
        scale_factor REAL,
        period TEXT,
        date TEXT,
        frequency TEXT,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT,
        source_title TEXT,
        published_date TEXT,
        parser_notes TEXT,
        data_status TEXT,
        derived_from_ytd_diff INTEGER DEFAULT 0,
        is_mock INTEGER DEFAULT 0,
        is_seed INTEGER DEFAULT 0,
        is_cache INTEGER DEFAULT 0,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period, source_type)
    )''')
    for col, typ in [
        ('debt_line', 'TEXT'), ('derived_from_ytd_diff', 'INTEGER DEFAULT 0'),
        ('source_title', 'TEXT'), ('published_date', 'TEXT'), ('parser_notes', 'TEXT'),
        ('source_url', 'TEXT'), ('data_status', 'TEXT')
    ]:
        _add_col(conn, 'fiscal_debt_observations', col, typ)

    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_gap_observations (
        id INTEGER PRIMARY KEY,
        year INTEGER,
        period TEXT,
        local_fiscal_revenue_total REAL,
        local_public_budget_revenue REAL,
        local_gov_fund_revenue REAL,
        local_fiscal_expenditure_total REAL,
        local_public_budget_expenditure REAL,
        local_gov_fund_expenditure REAL,
        local_fiscal_balance REAL,
        central_to_local_transfer REAL,
        local_absolute_gap REAL,
        source_url TEXT,
        source_title TEXT,
        published_date TEXT,
        data_status TEXT,
        parser_notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(period, source_url)
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS bond_maturity_schedule (
        id INTEGER PRIMARY KEY,
        bond_code TEXT,
        bond_name TEXT,
        issuer TEXT,
        province TEXT,
        bond_type TEXT,
        general_or_special TEXT,
        new_or_refinancing TEXT,
        issue_date TEXT,
        maturity_date TEXT,
        principal_amount REAL,
        remaining_balance REAL,
        coupon_rate REAL,
        source_name TEXT,
        source_url TEXT,
        data_status TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(bond_code)
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS debt_projection_scenarios (
        id INTEGER PRIMARY KEY,
        projection_year INTEGER,
        beginning_debt_balance REAL,
        new_bond_issuance REAL,
        refinancing_bond_issuance REAL,
        principal_repayment REAL,
        interest_payment REAL,
        ending_debt_balance REAL,
        avg_interest_rate REAL,
        avg_maturity_years REAL,
        debt_service_total REAL,
        fiscal_gap REAL,
        financing_gap REAL,
        scenario_name TEXT,
        assumptions TEXT,
        data_status TEXT,
        source_url TEXT,
        source_title TEXT,
        published_date TEXT,
        parser_notes TEXT,
        created_at TEXT,
        updated_at TEXT
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_debt_update_logs (
        id INTEGER PRIMARY KEY,
        source_name TEXT,
        source_type TEXT,
        started_at TEXT,
        finished_at TEXT,
        success INTEGER,
        new_records INTEGER,
        updated_records INTEGER,
        error_message TEXT,
        warnings TEXT
    )''')

    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_source_registry (
        source_key TEXT PRIMARY KEY,
        source_name TEXT,
        source_type TEXT,
        source_label TEXT,
        entry_url TEXT,
        candidate_paths TEXT,
        parser_notes TEXT,
        updated_at TEXT
    )''')
    now = datetime.now().isoformat()
    for key, src in FISCAL_SOURCE_REGISTRY.items():
        conn.execute('''INSERT INTO fiscal_source_registry (
            source_key,source_name,source_type,source_label,entry_url,candidate_paths,parser_notes,updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(source_key) DO UPDATE SET
            source_name=excluded.source_name,
            source_type=excluded.source_type,
            source_label=excluded.source_label,
            entry_url=excluded.entry_url,
            candidate_paths=excluded.candidate_paths,
            parser_notes=excluded.parser_notes,
            updated_at=excluded.updated_at
        ''', (
            key, src.get('source_name'), src.get('source_type'), src.get('source_label'),
            src.get('entry_url'), json.dumps(src.get('candidate_paths', []), ensure_ascii=False),
            src.get('parser_notes'), now
        ))
    conn.commit()


def fetch_url(url, timeout=25):
    try:
        import requests
        resp = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://zwgls.mof.gov.cn/',
        }, timeout=timeout)
        resp.raise_for_status()
        if not resp.encoding or resp.encoding.lower() == 'iso-8859-1':
            resp.encoding = resp.apparent_encoding or 'utf-8'
        return resp.text
    except Exception:
        pass
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or 'utf-8'
    for enc in [charset, 'utf-8', 'gb18030', 'gbk']:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('utf-8', errors='replace')


def normalize_text(html):
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html or '', flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_lib.unescape(text).replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'(?<=\d)\s+(?=\d)', '', text)
    text = re.sub(r'(?<=\d)\.\s+(?=\d)', '.', text)
    text = re.sub(r'(?<=\d)\s+\.(?=\d)', '.', text)
    return text


def n(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(',', '').replace(' ', ''))
    except Exception:
        return None


def first(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return n(m.group(1)) if m else None


def discover_local_debt_links(limit=24):
    try:
        html = fetch_url(MOF_LOCAL_DEBT_INDEX)
    except Exception:
        return KNOWN_LOCAL_DEBT_URLS[:limit]
    links = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href, title_html = m.group(1), m.group(2)
        title = normalize_text(title_html)
        if '地方政府债券发行和债务余额情况' not in title:
            continue
        url = urljoin(MOF_LOCAL_DEBT_INDEX, href)
        links.append({'url': url, 'title': title})
    seen, out = set(), []
    for item in links:
        if item['url'] in seen:
            continue
        seen.add(item['url'])
        out.append(item)
        if len(out) >= limit:
            break
    if not out:
        return KNOWN_LOCAL_DEBT_URLS[:limit]
    for item in KNOWN_LOCAL_DEBT_URLS:
        if item['url'] not in seen:
            out.append(item)
            if len(out) >= limit:
                break
    return out


def parse_local_debt_page(url):
    html = fetch_url(url)
    text = normalize_text(html)
    title_match = re.search(r'((?:20\d{2})年(?:\d{1,2})月地方政府债券发行和债务余额情况)', text)
    title = title_match.group(1) if title_match else '地方政府债券发行和债务余额情况'
    period_match = re.search(r'(20\d{2})年(\d{1,2})月地方政府债券发行和债务余额情况', title)
    if not period_match:
        return None
    period = f"{period_match.group(1)}-{int(period_match.group(2)):02d}"
    published = None
    m = re.search(r'((?:20\d{2})年\d{2}月\d{2}日)\s+来源', text)
    if m:
        published = m.group(1).replace('年', '-').replace('月', '-').replace('日', '')

    month_section = re.search(r'（一）当月发行情况。(.*?)(?:（二）|1-\s*\d+月\s*发行情况)', text)
    ytd_section = re.search(r'（二）.*?发行情况。(.*?)(?:（\s*三\s*）|还本付息情况)', text)
    repay_section = re.search(r'还本付息情况。(.*?)(?:二、全国地方政府债务余额情况|全国地方政府债务余额情况)', text)
    balance_section = re.search(r'全国地方政府债务余额情况(.*?)(?:注\s*:|附件下载|相关文章|$)', text)
    month = month_section.group(1) if month_section else text
    ytd = ytd_section.group(1) if ytd_section else text
    repay = repay_section.group(1) if repay_section else text
    balance = balance_section.group(1) if balance_section else text

    data = {
        'period': period,
        'source_url': url,
        'source_title': title,
        'published_date': published,
        'parser_notes': '解析自财政部债务管理司“地方政府债券发行和债务余额情况”月度原文：发行情况、还本付息情况、债务余额情况。',
        'data_status': 'official',
        'derived_from_ytd_diff': False,
        'local_bond_issuance_current_month': first(r'全国发行地方政府债券合计\s*(\d+\.?\d*)\s*亿元', month),
        'local_new_bond_issuance_ytd': first(r'全国发行新增地方政府债券\s*(\d+\.?\d*)\s*亿元', ytd),
        'local_refinancing_bond_issuance_ytd': first(r'全国发行再融资债券\s*(\d+\.?\d*)\s*亿元', ytd),
        'local_bond_issuance_ytd': first(r'全国发行地方政府债券合计\s*(\d+\.?\d*)\s*亿元', ytd),
        'official_principal_repayment_ytd': first(r'地方政府债券到期偿还本金\s*(\d+\.?\d*)\s*亿元', repay),
        'official_refinancing_repayment_ytd': first(r'发行再融资债券偿还本金\s*(\d+\.?\d*)\s*亿元', repay),
        'official_fiscal_funds_repayment_ytd': first(r'安排财政资金等偿还本金\s*(\d+\.?\d*)\s*亿元', repay),
        'official_principal_repayment_current_month': first(r'当月到期偿还本金\s*(\d+\.?\d*)\s*亿元', repay),
        'official_interest_payment_ytd': first(r'地方政府债券支付利息\s*(\d+\.?\d*)\s*亿元', repay),
        'official_interest_payment_current_month': first(r'当月地方政府债券支付利息\s*(\d+\.?\d*)\s*亿元', repay),
        'local_debt_balance_total': first(r'地方政府债务余额\s*(\d+\.?\d*)\s*亿\s*元', balance),
        'local_general_debt_balance': first(r'一般债务\s*(\d+\.?\d*)\s*亿元', balance),
        'local_special_debt_balance': first(r'专项债务\s*(\d+\.?\d*)\s*亿元', balance),
        'local_bond_balance': first(r'政府债券\s*(\d+\.?\d*)\s*亿元', balance),
        'local_non_bond_debt_balance': first(r'非政府债券形式存量政府债务\s*(\d+\.?\d*)\s*亿元', balance),
        'local_bond_avg_remaining_maturity': first(r'地方政府债券剩余平均年限\s*(\d+\.?\d*)\s*年', balance),
        'local_general_bond_avg_remaining_maturity': first(r'剩余平均年限\s*\d+\.?\d*\s*年，其中一般债券\s*(\d+\.?\d*)\s*年', balance),
        'local_special_bond_avg_remaining_maturity': first(r'专项债券\s*(\d+\.?\d*)\s*年\s*；平均利率', balance),
        'local_bond_avg_interest_rate': first(r'平均利率\s*(\d+\.?\d*)\s*%', balance),
        'local_general_bond_avg_interest_rate': first(r'平均利率\s*\d+\.?\d*\s*%\s*，其中一般债券\s*(\d+\.?\d*)\s*%', balance),
        'local_special_bond_avg_interest_rate': first(r'专项债券\s*(\d+\.?\d*)\s*%\s*。', balance),
    }

    total_ytd = ytd
    m = re.search(r'全国发行地方政府债券合计\s*\d+\.?\d*\s*亿元，其中一般债券\s*(\d+\.?\d*)\s*亿元、专项债券\s*(\d+\.?\d*)\s*亿元', total_ytd)
    if m:
        data['local_general_bond_issuance_ytd'] = n(m.group(1))
        data['local_special_bond_issuance_ytd'] = n(m.group(2))

    return data


def _latest_ytd(conn, field, period):
    year = period[:4]
    row = conn.execute('''
        SELECT value FROM fiscal_debt_observations
        WHERE indicator_code=? AND period < ? AND substr(period, 1, 4)=? AND data_status IN ('official','derived','cache')
        ORDER BY period DESC LIMIT 1
    ''', (field, period, year)).fetchone()
    return row['value'] if row else None


def upsert_local_debt_record(conn, rec):
    now = datetime.now().isoformat()
    new_records = updated_records = 0
    for field, (name, unit, default_status) in LOCAL_DEBT_FIELDS.items():
        value = rec.get(field)
        status = default_status
        derived = 0
        if value is None and field == 'official_principal_repayment_current_month' and rec.get('official_principal_repayment_ytd') is not None:
            if rec['period'].endswith('-01'):
                value = rec['official_principal_repayment_ytd']
                status = 'derived'
                derived = 1
            else:
                prev = _latest_ytd(conn, 'official_principal_repayment_ytd', rec['period'])
                if prev is not None:
                    value = rec['official_principal_repayment_ytd'] - prev
                    status = 'derived'
                    derived = 1
        if value is None:
            if field == 'official_principal_repayment_current_month':
                conn.execute('''
                    DELETE FROM fiscal_debt_observations
                    WHERE indicator_code=? AND period=? AND source_type=? AND derived_from_ytd_diff=1
                ''', (field, rec['period'], 'mof_local_debt'))
            continue
        if field == 'official_principal_repayment_current_month' and derived and value < 0:
            conn.execute('''
                DELETE FROM fiscal_debt_observations
                WHERE indicator_code=? AND period=? AND source_type=? AND derived_from_ytd_diff=1
            ''', (field, rec['period'], 'mof_local_debt'))
            continue
        existing = conn.execute(
            'SELECT id FROM fiscal_debt_observations WHERE indicator_code=? AND period=? AND source_type=?',
            (field, rec['period'], 'mof_local_debt')
        ).fetchone()
        conn.execute('''INSERT INTO fiscal_debt_observations (
            debt_line,indicator_code,indicator_name,value,unit_raw,unit_display,scale_factor,period,date,frequency,
            source_name,source_type,source_url,source_title,published_date,parser_notes,data_status,derived_from_ytd_diff,
            is_mock,is_seed,is_cache,notes,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
            value=excluded.value, source_url=excluded.source_url, source_title=excluded.source_title,
            published_date=excluded.published_date, parser_notes=excluded.parser_notes,
            data_status=excluded.data_status, derived_from_ytd_diff=excluded.derived_from_ytd_diff,
            is_cache=excluded.is_cache, updated_at=excluded.updated_at
        ''', (
            'local_government_debt', field, name, value, unit, unit, 1, rec['period'], rec['period'] + '-01', 'monthly',
            '财政部债务管理司', 'mof_local_debt', rec['source_url'], rec['source_title'], rec['published_date'],
            rec['parser_notes'], status, derived, 0, 0, 1, '', now, now
        ))
        if existing:
            updated_records += 1
        else:
            new_records += 1
    return new_records, updated_records


def update_fiscal_debt(db_path, limit=24):
    started = datetime.now().isoformat()
    warnings = []
    new_records = updated_records = 0
    try:
        links = discover_local_debt_links(limit=limit)
        with connect(db_path) as conn:
            ensure_fiscal_tables(conn)
            for item in reversed(links):
                try:
                    rec = parse_local_debt_page(item['url'])
                    if not rec:
                        continue
                    n_new, n_upd = upsert_local_debt_record(conn, rec)
                    new_records += n_new
                    updated_records += n_upd
                except Exception as exc:
                    warnings.append(f"{item.get('title')}: {exc}")
            conn.execute('''INSERT INTO fiscal_debt_update_logs (
                source_name,source_type,started_at,finished_at,success,new_records,updated_records,error_message,warnings
            ) VALUES (?,?,?,?,?,?,?,?,?)''', (
                '财政部债务管理司', 'mof_local_debt', started, datetime.now().isoformat(), 1,
                new_records, updated_records, None, json.dumps(warnings, ensure_ascii=False)
            ))
            conn.commit()
        return {'success': True, 'new_records': new_records, 'updated_records': updated_records, 'warnings': warnings}
    except Exception as exc:
        with connect(db_path) as conn:
            ensure_fiscal_tables(conn)
            conn.execute('''INSERT INTO fiscal_debt_update_logs (
                source_name,source_type,started_at,finished_at,success,new_records,updated_records,error_message,warnings
            ) VALUES (?,?,?,?,?,?,?,?,?)''', (
                '财政部债务管理司', 'mof_local_debt', started, datetime.now().isoformat(), 0,
                0, 0, str(exc), json.dumps(warnings, ensure_ascii=False)
            ))
            conn.commit()
        return {'success': False, 'error': str(exc), 'warnings': warnings}


def rows_to_wide(rows):
    by_period = {}
    for r in rows:
        period = r['period']
        rec = by_period.setdefault(period, {
            'period': period,
            'source_url': r['source_url'],
            'source_title': r['source_title'],
            'published_date': r['published_date'],
            'parser_notes': r['parser_notes'],
            'data_status': 'cache' if r['data_status'] == 'official' else r['data_status'],
            'source_name': r['source_name'],
            'source_type': r['source_type'],
        })
        rec[r['indicator_code']] = r['value']
        rec[f"{r['indicator_code']}__status"] = r['data_status']
        if r['derived_from_ytd_diff']:
            rec[f"{r['indicator_code']}__derived_from_ytd_diff"] = True
    return [by_period[k] for k in sorted(by_period)]


def latest_record(records):
    return records[-1] if records else None


def _source_registry(conn):
    return [dict(r) for r in conn.execute('SELECT * FROM fiscal_source_registry ORDER BY source_key').fetchall()]


def build_fiscal_debt_payload(db_path):
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        local_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM fiscal_debt_observations WHERE debt_line='local_government_debt' ORDER BY period, indicator_code"
        ).fetchall()]
        local_records = rows_to_wide(local_rows)
        gap_rows = [dict(r) for r in conn.execute('SELECT * FROM fiscal_gap_observations ORDER BY period').fetchall()]
        bond_rows = [dict(r) for r in conn.execute('SELECT * FROM bond_maturity_schedule ORDER BY maturity_date LIMIT 500').fetchall()]
        scenario_rows = [dict(r) for r in conn.execute('SELECT * FROM debt_projection_scenarios ORDER BY scenario_name, projection_year').fetchall()]
        registry = _source_registry(conn)
    warnings = []
    if not local_records:
        warnings.append('地方政府债务月度原文抓取待执行，未生成 mock 数据')
    warnings += [
        '国债数据源待接入，未生成 mock 数据',
        '城投债数据源待接入，未纳入官方地方政府债务余额。',
        '财政缺口为测算口径，不等于官方赤字定义；当前数据源待接入。',
    ]
    return {
        'success': True,
        'data_mode': 'cache' if local_records else 'missing',
        'data_status': 'cache' if local_records else 'missing',
        'local_government_debt': {
            'data_status': 'cache' if local_records else 'missing',
            'latest_period': latest_record(local_records)['period'] if local_records else None,
            'records': local_records,
            'warnings': [] if local_records else ['地方政府债务月度原文抓取待执行，未生成 mock 数据'],
        },
        'treasury_debt': {
            'data_status': 'missing',
            'records': [],
            'required_fields': TREASURY_FIELDS,
            'warnings': ['国债余额、发行、到期还本数据源待接入。'],
        },
        'lgfv_debt': {
            'data_status': 'missing',
            'records': [],
            'required_fields': LGFV_FIELDS,
            'warnings': ['城投债数据源待接入，未纳入官方地方政府债务余额。'],
        },
        'fiscal_gap': {
            'data_status': 'missing' if not gap_rows else 'cache',
            'records': gap_rows,
            'formula': {
                'local_fiscal_balance': 'local_fiscal_revenue_total - local_fiscal_expenditure_total',
                'local_absolute_gap': 'local_fiscal_balance + central_to_local_transfer',
            },
            'warnings': ['财政缺口是测算口径，不等于官方赤字定义。'] + ([] if gap_rows else ['财政缺口数据源待接入，未生成 mock 数据']),
        },
        'maturity_projection': {
            'data_status': 'projected_from_bond_schedule' if bond_rows else 'rough_estimate',
            'bond_schedule_count': len(bond_rows),
            'records': bond_rows,
            'warnings': [] if bond_rows else ['尚未接入逐只债券到期表；未来到期还本只能使用余额/平均剩余年限粗略估算。'],
        },
        'projection_scenarios': {
            'data_status': 'scenario' if scenario_rows else 'missing',
            'records': scenario_rows,
        },
        'source_registry': registry,
        'metadata': {
            'warnings': warnings,
            'errors': [],
            'source_summary': registry,
            'data_status_values': DATA_STATUS,
        }
    }


def build_fiscal_debt_debug_payload(db_path):
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        tables = {}
        for name in ['fiscal_debt_observations', 'fiscal_gap_observations', 'bond_maturity_schedule', 'debt_projection_scenarios', 'fiscal_debt_update_logs', 'fiscal_source_registry']:
            tables[name] = conn.execute(f'SELECT COUNT(*) AS c FROM {name}').fetchone()['c']
        latest = [dict(r) for r in conn.execute('''
            SELECT indicator_code, indicator_name, value, unit_display, period,
                   source_name, source_type, source_url, source_title, published_date,
                   parser_notes, data_status, derived_from_ytd_diff, is_mock, is_seed, is_cache, updated_at
            FROM fiscal_debt_observations fo
            WHERE period = (SELECT MAX(period) FROM fiscal_debt_observations WHERE indicator_code=fo.indicator_code)
            ORDER BY indicator_code
        ''').fetchall()]
        by_source = [dict(r) for r in conn.execute('''
            SELECT COALESCE(source_url, '') AS source_url,
                   MAX(source_title) AS source_title,
                   MAX(published_date) AS published_date,
                   COUNT(DISTINCT indicator_code) AS indicator_count,
                   GROUP_CONCAT(DISTINCT indicator_code) AS indicators
            FROM fiscal_debt_observations
            GROUP BY COALESCE(source_url, '')
            ORDER BY MAX(period) DESC
        ''').fetchall()]
        missing_source = [dict(r) for r in conn.execute('''
            SELECT indicator_code, COUNT(*) AS records
            FROM fiscal_debt_observations
            WHERE source_url IS NULL OR source_url=''
            GROUP BY indicator_code
        ''').fetchall()]
        status_counts = [dict(r) for r in conn.execute('''
            SELECT data_status, source_type, is_mock, is_seed, is_cache, COUNT(*) AS records
            FROM fiscal_debt_observations
            GROUP BY data_status, source_type, is_mock, is_seed, is_cache
            ORDER BY records DESC
        ''').fetchall()]
        logs = [dict(r) for r in conn.execute('SELECT * FROM fiscal_debt_update_logs ORDER BY id DESC LIMIT 10').fetchall()]
        registry = _source_registry(conn)
    return {
        'database_path': db_path,
        'tables': tables,
        'latest_by_indicator': latest,
        'indicators_by_source': by_source,
        'missing_source_url': missing_source,
        'status_counts': status_counts,
        'source_registry': registry,
        'required_local_debt_fields': {k: v[0] for k, v in LOCAL_DEBT_FIELDS.items()},
        'required_treasury_fields': TREASURY_FIELDS,
        'required_lgfv_fields': LGFV_FIELDS,
        'required_fiscal_gap_fields': FISCAL_GAP_FIELDS,
        'last_update_logs': logs,
        'warnings': [
            '国债数据源待接入，未生成 mock 数据',
            '城投债数据源待接入，未纳入官方地方政府债务余额。',
            '逐只债券到期表未接入时，未来还本为 rough_estimate。',
        ],
        'errors': [],
    }


def build_projection_payload(db_path):
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        rows = [dict(r) for r in conn.execute('SELECT * FROM debt_projection_scenarios ORDER BY scenario_name, projection_year').fetchall()]
    return {'success': True, 'data_status': 'scenario' if rows else 'missing', 'records': rows}


def run_projection(db_path, payload=None):
    payload = payload or {}
    scenario_name = payload.get('scenario_name') or 'baseline'
    years = int(payload.get('years') or 5)
    new_bond = float(payload.get('new_bond_issuance') or 50000)
    refinancing = float(payload.get('refinancing_bond_issuance') or 30000)
    fiscal_gap = float(payload.get('fiscal_gap') or 0)
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        latest = conn.execute('''
            SELECT period,
                   MAX(CASE WHEN indicator_code='local_debt_balance_total' THEN value END) AS debt,
                   MAX(CASE WHEN indicator_code='local_bond_avg_interest_rate' THEN value END) AS rate,
                   MAX(CASE WHEN indicator_code='local_bond_avg_remaining_maturity' THEN value END) AS maturity
            FROM fiscal_debt_observations
            GROUP BY period ORDER BY period DESC LIMIT 1
        ''').fetchone()
        beginning = float(payload.get('beginning_debt_balance') or (latest['debt'] if latest and latest['debt'] else 0))
        rate = float(payload.get('avg_interest_rate') or (latest['rate'] if latest and latest['rate'] else 3.25))
        maturity = float(payload.get('avg_maturity_years') or (latest['maturity'] if latest and latest['maturity'] else 13))
        start_year = int(payload.get('start_year') or datetime.now().year)
        now = datetime.now().isoformat()
        conn.execute('DELETE FROM debt_projection_scenarios WHERE scenario_name=?', (scenario_name,))
        records = []
        debt = beginning
        assumptions = {
            'new_bond_issuance': new_bond,
            'refinancing_bond_issuance': refinancing,
            'avg_interest_rate': rate,
            'avg_maturity_years': maturity,
            'fiscal_gap': fiscal_gap,
            'method': 'scenario projection, not official data',
        }
        for i in range(years):
            year = start_year + i
            principal = debt / maturity if maturity else 0
            interest = debt * rate / 100
            ending = debt + new_bond + refinancing - principal
            debt_service = principal + interest
            financing_gap = fiscal_gap + debt_service - refinancing
            row = {
                'projection_year': year,
                'beginning_debt_balance': debt,
                'new_bond_issuance': new_bond,
                'refinancing_bond_issuance': refinancing,
                'principal_repayment': principal,
                'interest_payment': interest,
                'ending_debt_balance': ending,
                'avg_interest_rate': rate,
                'avg_maturity_years': maturity,
                'debt_service_total': debt_service,
                'fiscal_gap': fiscal_gap,
                'financing_gap': financing_gap,
                'scenario_name': scenario_name,
                'assumptions': json.dumps(assumptions, ensure_ascii=False),
                'data_status': 'scenario',
                'source_url': None,
                'source_title': '情景测算，不是官方数据',
                'published_date': None,
                'parser_notes': 'ending_debt_balance=beginning+new+refinancing-principal; debt_service=principal+interest; financing_gap=fiscal_gap+debt_service-refinancing。',
            }
            conn.execute('''INSERT INTO debt_projection_scenarios (
                projection_year,beginning_debt_balance,new_bond_issuance,refinancing_bond_issuance,
                principal_repayment,interest_payment,ending_debt_balance,avg_interest_rate,avg_maturity_years,
                debt_service_total,fiscal_gap,financing_gap,scenario_name,assumptions,data_status,
                source_url,source_title,published_date,parser_notes,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                row['projection_year'], row['beginning_debt_balance'], row['new_bond_issuance'], row['refinancing_bond_issuance'],
                row['principal_repayment'], row['interest_payment'], row['ending_debt_balance'], row['avg_interest_rate'], row['avg_maturity_years'],
                row['debt_service_total'], row['fiscal_gap'], row['financing_gap'], row['scenario_name'], row['assumptions'], row['data_status'],
                row['source_url'], row['source_title'], row['published_date'], row['parser_notes'], now, now
            ))
            records.append(row)
            debt = ending
        conn.commit()
    return {'success': True, 'data_status': 'scenario', 'records': records, 'warnings': ['情景测算不是官方数据，所有假设必须随结果展示。']}
