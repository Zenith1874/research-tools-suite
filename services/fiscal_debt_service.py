import html as html_lib
import io
import json
import re
import sqlite3
import time
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
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202511/t20251101_3975518.htm', 'title': '2024年12月地方政府债券发行和债务余额情况'},
]

MOF_CENTRAL_DEBT_PDF = 'https://zwgls.mof.gov.cn/tjsj/202511/P020251101766789596876.pdf'
MOF_CENTRAL_DEBT_TITLE = '2024年中央政府月度收支及融资数据和季度债务余额情况'
# 财政部国库司中央政府季度债务余额 PDF（SDDS 口径）。新年度/季度 PDF 上线后在此追加一条即可。
MOF_CENTRAL_DEBT_PDFS = [
    {'url': MOF_CENTRAL_DEBT_PDF, 'title': MOF_CENTRAL_DEBT_TITLE,
     'periods': ['2024-03', '2024-06', '2024-09', '2024-12'], 'published': '2025-11-01'},
    {'url': 'https://zwgls.mof.gov.cn/tjsj/202511/P020251101766791526425.pdf',
     'title': '2025年9月中央政府收支及融资数据和二季度债务余额情况',
     'periods': ['2025-03', '2025-06'], 'published': '2025-10-27'},
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
    'mof_central_government_debt_sdds': {
        'source_name': '财政部国库司',
        'source_type': 'mof_central_government_debt_sdds',
        'source_label': '财政部国库司：中央政府收支、融资和季度债务余额',
        'entry_url': MOF_LOCAL_DEBT_INDEX,
        'candidate_paths': ['债务管理司 / 统计数据 / 中央政府月度收支及融资数据和季度债务余额情况'],
        'parser_notes': '解析财政部官方 PDF 中“中央政府债务余额（季度数据）”；债务余额与债券余额分别保存，不与央行对政府债权混用。'
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
        ('source_url', 'TEXT'), ('data_status', 'TEXT'), ('module_code', 'TEXT'),
        ('raw_text', 'TEXT'), ('formula', 'TEXT')
    ]:
        _add_col(conn, 'fiscal_debt_observations', col, typ)
    conn.execute('''UPDATE fiscal_debt_observations SET
        module_code=COALESCE(module_code,CASE debt_line
            WHEN 'central_government_debt' THEN 'government_debt_overview'
            WHEN 'local_government_debt' THEN 'debt_rollover_pressure'
            ELSE debt_line END),
        is_cache=CASE WHEN data_status='official' AND source_url LIKE 'http%' THEN 0 ELSE is_cache END,
        formula=CASE WHEN data_status='derived' AND derived_from_ytd_diff=1 AND COALESCE(formula,'')=''
            THEN 'official_principal_repayment_ytd - previous_month_official_principal_repayment_ytd'
            ELSE formula END
    ''')

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
        module_code TEXT,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT,
        started_at TEXT,
        finished_at TEXT,
        status TEXT,
        http_status INTEGER,
        success INTEGER,
        records_inserted INTEGER,
        records_updated INTEGER,
        new_records INTEGER,
        updated_records INTEGER,
        error_message TEXT,
        warnings TEXT
    )''')
    for col, typ in [
        ('module_code', 'TEXT'), ('source_url', 'TEXT'), ('status', 'TEXT'),
        ('http_status', 'INTEGER'), ('records_inserted', 'INTEGER DEFAULT 0'),
        ('records_updated', 'INTEGER DEFAULT 0')
    ]:
        _add_col(conn, 'fiscal_debt_update_logs', col, typ)
    conn.execute('''UPDATE fiscal_debt_update_logs SET
        module_code=COALESCE(module_code, CASE source_type
            WHEN 'mof_local_debt' THEN 'local_government_debt'
            ELSE source_type END),
        status=COALESCE(status, CASE WHEN success=1 THEN 'success' ELSE 'error' END),
        records_inserted=COALESCE(records_inserted,new_records,0),
        records_updated=COALESCE(records_updated,updated_records,0),
        http_status=COALESCE(http_status,CASE WHEN warnings LIKE '%502%' OR error_message LIKE '%502%' THEN 502 END)
    ''')
    conn.execute('''UPDATE fiscal_debt_update_logs SET status='partial'
        WHERE success=1 AND COALESCE(warnings,'') NOT IN ('','[]')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_debt_scenario_runs (
        id INTEGER PRIMARY KEY,
        scenario_name TEXT,
        initial_period TEXT,
        initial_cumulative_purchase REAL,
        quarterly_treasury_purchase REAL,
        local_bond_assumption_enabled INTEGER DEFAULT 0,
        quarterly_local_bond_purchase REAL,
        comparison_anchor TEXT,
        anchor_value REAL,
        quarters INTEGER,
        assumptions TEXT,
        result_json TEXT,
        data_status TEXT,
        created_at TEXT
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
    last_error = None
    for attempt in range(3):
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
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or 'utf-8'
    except Exception:
        raise last_error
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


def discover_local_debt_links(limit=48):
    links = []
    for page_url in [MOF_LOCAL_DEBT_INDEX, urljoin(MOF_LOCAL_DEBT_INDEX, 'index_1.htm')]:
        try:
            html = fetch_url(page_url)
        except Exception:
            continue
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
            href, title_html = m.group(1), m.group(2)
            title = normalize_text(title_html)
            if '地方政府债券发行和债务余额情况' not in title:
                continue
            links.append({'url': urljoin(page_url, href), 'title': title})
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


def fetch_binary(url, timeout=40):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/pdf,*/*',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(), resp.geturl()


def parse_central_government_debt_pdf(url=MOF_CENTRAL_DEBT_PDF,
                                      periods=('2024-03', '2024-06', '2024-09', '2024-12'),
                                      published='2025-11-01',
                                      title=MOF_CENTRAL_DEBT_TITLE):
    """解析财政部国库司 PDF 第2页“中央政府债务余额（季度数据）”。
    支持可变季度数（年中 PDF 可能只含已发布的 1-2 个季度）。原始单位十亿元，×10 转亿元。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError('解析中央政府债务 PDF 需要 pypdf') from exc
    periods = list(periods)
    n = len(periods)
    content, final_url = fetch_binary(url)
    reader = PdfReader(io.BytesIO(content))
    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
    # 债务余额行：Debt 后取连续的 1-4 个数字（季度值）
    section = re.search(r'中央政府债务余额（季度数据）.*?\bDebt\s+([\d.]+(?:\s+[\d.]+)*)', text, re.S)
    if not section:
        raise RuntimeError(f'未从财政部 PDF 解析出中央政府季度债务余额: {title}')
    debt_nums = [float(x) * 10 for x in section.group(1).split()]
    tail = text[section.end():]   # 债务余额段之后才有“债券 Bonds”余额行（融资段在页1，不在此 tail）
    bonds = re.search(r'债券\s*\n?\s*Bonds\s+([\d.]+(?:\s+[\d.]+)*)', tail)
    if not bonds:
        raise RuntimeError(f'未从财政部 PDF 解析出中央政府债券余额: {title}')
    bond_nums = [float(x) * 10 for x in bonds.group(1).split()]
    if len(debt_nums) < n or len(bond_nums) < n:
        raise RuntimeError(f'PDF 季度数不足({title})：debt={len(debt_nums)} bond={len(bond_nums)} 需要 {n}')
    debt_values, bond_values = debt_nums[:n], bond_nums[:n]
    notes = f'解析财政部官方 PDF“中央政府债务余额（季度数据）”（{title}）；原始单位十亿元，×10 转亿元。'
    records = []
    for period, debt, bond in zip(periods, debt_values, bond_values):
        for code, name, value in [
            ('central_government_debt_balance', '中央政府债务余额', debt),
            ('central_government_bond_balance', '中央政府债券余额', bond),
        ]:
            records.append({
                'module_code': 'government_debt_overview',
                'debt_line': 'central_government_debt',
                'indicator_code': code,
                'indicator_name': name,
                'value': value,
                'unit_raw': '十亿元',
                'unit_display': '亿元',
                'scale_factor': 10,
                'period': period,
                'date': period + ('-31' if period[-2:] in ('03', '12') else '-30'),
                'frequency': 'quarterly',
                'source_name': '财政部国库司',
                'source_type': 'mof_central_government_debt_sdds',
                'source_url': final_url,
                'source_title': title,
                'published_date': published,
                'parser_notes': notes,
                'raw_text': f'{period} {name}: {value / 10} 十亿元',
                'formula': None,
                'data_status': 'official',
            })
    return records


def update_central_government_debt(db_path):
    # 解析所有已配置的财政部中央债 PDF（2024、2025…），失败的单个 PDF 跳过不影响其它
    records, parse_errors = [], []
    for cfg in MOF_CENTRAL_DEBT_PDFS:
        try:
            records.extend(parse_central_government_debt_pdf(
                cfg['url'], cfg['periods'], cfg['published'], cfg['title']))
        except Exception as exc:
            parse_errors.append({'url': cfg['url'], 'title': cfg['title'], 'error': str(exc)})
    if not records:
        raise RuntimeError(f'中央政府债务 PDF 全部解析失败: {parse_errors}')
    now = datetime.now().isoformat()
    inserted = updated = 0
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        for rec in records:
            exists = conn.execute('''SELECT 1 FROM fiscal_debt_observations
                WHERE indicator_code=? AND period=? AND source_type=?''',
                (rec['indicator_code'], rec['period'], rec['source_type'])).fetchone()
            conn.execute('''INSERT INTO fiscal_debt_observations (
                module_code,debt_line,indicator_code,indicator_name,value,unit_raw,unit_display,
                scale_factor,period,date,frequency,source_name,source_type,source_url,source_title,
                published_date,parser_notes,raw_text,formula,data_status,is_mock,is_seed,is_cache,
                created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?)
            ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
                module_code=excluded.module_code,debt_line=excluded.debt_line,
                indicator_name=excluded.indicator_name,value=excluded.value,
                unit_raw=excluded.unit_raw,unit_display=excluded.unit_display,
                scale_factor=excluded.scale_factor,date=excluded.date,frequency=excluded.frequency,
                source_name=excluded.source_name,source_url=excluded.source_url,
                source_title=excluded.source_title,published_date=excluded.published_date,
                parser_notes=excluded.parser_notes,raw_text=excluded.raw_text,
                formula=excluded.formula,data_status=excluded.data_status,updated_at=excluded.updated_at
            ''', (
                rec['module_code'], rec['debt_line'], rec['indicator_code'], rec['indicator_name'],
                rec['value'], rec['unit_raw'], rec['unit_display'], rec['scale_factor'], rec['period'],
                rec['date'], rec['frequency'], rec['source_name'], rec['source_type'], rec['source_url'],
                rec['source_title'], rec['published_date'], rec['parser_notes'], rec['raw_text'],
                rec['formula'], rec['data_status'], now, now
            ))
            if exists:
                updated += 1
            else:
                inserted += 1
        # 每个不同来源 PDF 各登记一条
        for surl in sorted({r['source_url'] for r in records}):
            src_recs = [r for r in records if r['source_url'] == surl]
            source = src_recs[0]
            conn.execute('''INSERT INTO fiscal_debt_sources (
                source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                parsed_indicators,status,error,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_url) DO UPDATE SET source_title=excluded.source_title,
                published_date=excluded.published_date,parser_notes=excluded.parser_notes,
                parsed_indicators=excluded.parsed_indicators,status=excluded.status,error=NULL,
                updated_at=excluded.updated_at''', (
                source['source_name'], source['source_type'], source['source_url'], source['source_title'],
                source['published_date'], source['parser_notes'], 'PDF attachment',
                json.dumps(sorted({r['indicator_code'] for r in src_recs}), ensure_ascii=False),
                'success', None, now
            ))
        conn.commit()
    latest = max(r['period'] for r in records)
    return {'success': True, 'new_records': inserted, 'updated_records': updated,
            'records': len(records), 'latest_period': latest,
            'parse_errors': parse_errors, 'source_url': records[0]['source_url']}


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
            module_code,debt_line,indicator_code,indicator_name,value,unit_raw,unit_display,scale_factor,period,date,frequency,
            source_name,source_type,source_url,source_title,published_date,parser_notes,data_status,derived_from_ytd_diff,
            is_mock,is_seed,is_cache,notes,raw_text,formula,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
            module_code=excluded.module_code,value=excluded.value, source_url=excluded.source_url, source_title=excluded.source_title,
            published_date=excluded.published_date, parser_notes=excluded.parser_notes,
            data_status=excluded.data_status, derived_from_ytd_diff=excluded.derived_from_ytd_diff,
            is_cache=excluded.is_cache,raw_text=excluded.raw_text,formula=excluded.formula,
            updated_at=excluded.updated_at
        ''', (
            'debt_rollover_pressure', 'local_government_debt', field, name, value, unit, unit, 1,
            rec['period'], rec['period'] + '-01', 'monthly',
            '财政部债务管理司', 'mof_local_debt', rec['source_url'], rec['source_title'], rec['published_date'],
            rec['parser_notes'], status, derived, 0, 0, 0, '',
            f"{name}: {value} {unit}",
            ('official_principal_repayment_ytd - previous_month_official_principal_repayment_ytd' if derived else None),
            now, now
        ))
        if existing:
            updated_records += 1
        else:
            new_records += 1
    return new_records, updated_records


def update_fiscal_debt(db_path, limit=48):
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
                    conn.execute('''INSERT INTO fiscal_debt_sources (
                        source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                        parsed_indicators,status,error,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_url) DO UPDATE SET source_title=excluded.source_title,
                        published_date=excluded.published_date,parser_notes=excluded.parser_notes,
                        parsed_indicators=excluded.parsed_indicators,status=excluded.status,error=NULL,
                        updated_at=excluded.updated_at''', (
                        '财政部债务管理司', 'mof_local_debt', rec['source_url'], rec['source_title'],
                        rec['published_date'], rec['parser_notes'], '',
                        json.dumps(sorted(k for k in LOCAL_DEBT_FIELDS if rec.get(k) is not None), ensure_ascii=False),
                        'success', None, datetime.now().isoformat()
                    ))
                except Exception as exc:
                    status_match = re.search(r'(?:HTTP Error\s+|\b)([45]\d{2})(?:\s+Server Error|\b)', str(exc))
                    warning = {'source_url': item.get('url'), 'source_title': item.get('title'),
                               'http_status': int(status_match.group(1)) if status_match else None,
                               'error': str(exc)}
                    warnings.append(warning)
                    conn.execute('''INSERT INTO fiscal_debt_sources (
                        source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                        parsed_indicators,status,error,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_url) DO UPDATE SET status='error',error=excluded.error,updated_at=excluded.updated_at''', (
                        '财政部债务管理司', 'mof_local_debt', item.get('url'), item.get('title'), None,
                        '财政部地方政府债务月报抓取或解析失败。', '', '[]', 'error', str(exc),
                        datetime.now().isoformat()
                    ))
            conn.commit()
        return {'success': True, 'new_records': new_records, 'updated_records': updated_records, 'warnings': warnings}
    except Exception as exc:
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
            'data_status': r['data_status'],
            'source_name': r['source_name'],
            'source_type': r['source_type'],
        })
        rec[r['indicator_code']] = r['value']
        rec[f"{r['indicator_code']}__status"] = r['data_status']
        if r['derived_from_ytd_diff']:
            rec[f"{r['indicator_code']}__derived_from_ytd_diff"] = True
        if r.get('formula'):
            rec[f"{r['indicator_code']}__formula"] = r['formula']
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
        central_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM fiscal_debt_observations WHERE debt_line='central_government_debt' ORDER BY period, indicator_code"
        ).fetchall()]
        central_records = rows_to_wide(central_rows)
        gap_rows = [dict(r) for r in conn.execute('SELECT * FROM fiscal_gap_observations ORDER BY period').fetchall()]
        bond_rows = [dict(r) for r in conn.execute('SELECT * FROM bond_maturity_schedule ORDER BY maturity_date LIMIT 500').fetchall()]
        scenario_count = conn.execute('SELECT COUNT(*) FROM fiscal_debt_scenario_runs').fetchone()[0]
        registry = _source_registry(conn)
    warnings = []
    if not local_records:
        warnings.append('地方政府债务月度原文抓取待执行，未生成 mock 数据')
    warnings += [
        '中央政府季度债务余额已接入财政部官方 PDF；国债还本和付息数据仍待接入。',
        '城投债数据源待接入，未纳入官方地方政府债务余额。',
        '财政缺口为测算口径，不等于官方赤字定义；当前数据源待接入。',
    ]
    return {
        'success': True,
        'data_mode': 'official' if local_records or central_records else 'missing',
        'data_status': 'official' if local_records or central_records else 'missing',
        'local_government_debt': {
            'data_status': 'official' if local_records else 'missing',
            'latest_period': latest_record(local_records)['period'] if local_records else None,
            'records': local_records,
            'warnings': [] if local_records else ['地方政府债务月度原文抓取待执行，未生成 mock 数据'],
        },
        'treasury_debt': {
            'data_status': 'official' if central_records else 'missing',
            'latest_period': latest_record(central_records)['period'] if central_records else None,
            'records': central_records,
            'required_fields': TREASURY_FIELDS,
            'warnings': ([] if central_records else ['中央政府债务余额数据源待接入。']) +
                        ['国债还本和付息数据源待接入。'],
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
            'data_status': 'projected_from_bond_schedule' if bond_rows else 'missing',
            'bond_schedule_count': len(bond_rows),
            'records': bond_rows,
            'warnings': [] if bond_rows else ['尚未接入可验证的完整逐只债券到期表；不生成粗略到期还本估算。'],
        },
        'projection_scenarios': {
            'data_status': 'scenario_only',
            'records': [],
            'saved_run_count': scenario_count,
            'warnings': ['情景结果仅在用户显式运行后返回，不进入 official observation。'],
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
        for name in ['fiscal_debt_observations', 'fiscal_gap_observations', 'bond_maturity_schedule',
                     'debt_projection_scenarios', 'fiscal_debt_scenario_runs',
                     'fiscal_debt_update_logs', 'fiscal_source_registry']:
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
        indicator_coverage = [dict(r) for r in conn.execute('''
            SELECT module_code,indicator_code,COUNT(*) count,MIN(period) earliest_period,
                   MAX(period) latest_period,GROUP_CONCAT(DISTINCT data_status) data_statuses,
                   SUM(CASE WHEN COALESCE(TRIM(source_url),'')='' THEN 1 ELSE 0 END) missing_source_url
            FROM fiscal_debt_observations GROUP BY module_code,indicator_code ORDER BY module_code,indicator_code
        ''').fetchall()]
        logs = [dict(r) for r in conn.execute('SELECT * FROM fiscal_debt_update_logs ORDER BY id DESC LIMIT 20').fetchall()]
        registry = _source_registry(conn)
    return {
        'database_path': db_path,
        'tables': tables,
        'latest_by_indicator': latest,
        'indicators_by_source': by_source,
        'missing_source_url': missing_source,
        'status_counts': status_counts,
        'indicator_coverage': indicator_coverage,
        'source_registry': registry,
        'required_local_debt_fields': {k: v[0] for k, v in LOCAL_DEBT_FIELDS.items()},
        'required_treasury_fields': TREASURY_FIELDS,
        'required_lgfv_fields': LGFV_FIELDS,
        'required_fiscal_gap_fields': FISCAL_GAP_FIELDS,
        'last_update_logs': logs,
        'warnings': [
            '中央政府季度债务余额已接入；国债还本和付息数据源待接入。',
            '城投债数据源待接入，未纳入官方地方政府债务余额。',
            '逐只债券到期表未完整接入时，到期还本模块保持 missing，不生成估算。',
        ],
        'errors': [],
    }


def build_projection_payload(db_path):
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_debt_scenario_runs ORDER BY id DESC LIMIT 20'
        ).fetchall()]
    for row in rows:
        row['assumptions'] = json.loads(row.get('assumptions') or '{}')
        row['records'] = json.loads(row.pop('result_json') or '[]')
    return {
        'success': True,
        'data_status': 'scenario_only',
        'runs': rows,
        'warnings': ['情景推算不是官方事实，不进入 fiscal_debt_observations。'],
    }


def run_projection(db_path, payload=None):
    payload = payload or {}
    scenario_name = str(payload.get('scenario_name') or '用户情景').strip()
    quarters = max(1, min(int(payload.get('quarters') or 8), 40))
    if payload.get('quarterly_treasury_purchase') in (None, ''):
        raise ValueError('quarterly_treasury_purchase 必填；系统不会代填金融假设')
    quarterly_treasury = float(payload['quarterly_treasury_purchase'])
    local_enabled = bool(payload.get('local_bond_assumption_enabled'))
    quarterly_local = float(payload.get('quarterly_local_bond_purchase') or 0) if local_enabled else 0.0
    anchor_code = str(payload.get('comparison_anchor') or 'foreign_exchange')
    if anchor_code not in {'foreign_exchange', 'foreign_assets', 'total_assets'}:
        raise ValueError('comparison_anchor 必须是 foreign_exchange、foreign_assets 或 total_assets')
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        latest_omo = conn.execute('''SELECT period,cumulative_net_purchase_amount
            FROM pboc_gov_bond_omo_observations WHERE data_status='official'
            ORDER BY period DESC LIMIT 1''').fetchone()
        initial_period = str(payload.get('initial_period') or (latest_omo['period'] if latest_omo else '')).strip()
        if not re.fullmatch(r'20\d{2}-(?:0[1-9]|1[0-2])', initial_period):
            raise ValueError('initial_period 必须是 YYYY-MM，或先更新央行国债买卖 official 数据')
        if payload.get('initial_cumulative_purchase') in (None, ''):
            if not latest_omo:
                raise ValueError('没有 official 累计央行国债净买入，必须显式输入 initial_cumulative_purchase')
            initial = float(latest_omo['cumulative_net_purchase_amount'])
        else:
            initial = float(payload['initial_cumulative_purchase'])
        anchor = conn.execute('''SELECT period,value,unit,source_url FROM pboc_balance_sheet_observations
            WHERE indicator_code=? AND data_status IN ('official','derived')
            ORDER BY period DESC LIMIT 1''', (anchor_code,)).fetchone()
        if not anchor or anchor['value'] in (None, 0):
            raise ValueError(f'缺少可用的 {anchor_code} official 锚点，不能运行情景')
        anchor_value = float(anchor['value'])
        now = datetime.now().isoformat()
        records = []
        assumptions = {
            'initial_period': initial_period,
            'initial_cumulative_purchase': initial,
            'quarterly_treasury_purchase': quarterly_treasury,
            'local_bond_assumption_enabled': local_enabled,
            'quarterly_local_bond_purchase': quarterly_local if local_enabled else None,
            'comparison_anchor': anchor_code,
            'anchor_period': anchor['period'],
            'anchor_value': anchor_value,
            'method': 'user-triggered scenario; cumulative = initial + quarter_index * quarterly assumptions',
        }
        start_year, start_month = map(int, initial_period.split('-'))
        for i in range(1, quarters + 1):
            month_index = start_year * 12 + start_month - 1 + i * 3
            year, month0 = divmod(month_index, 12)
            month = month0 + 1
            cumulative_treasury = initial + quarterly_treasury * i
            cumulative_local = quarterly_local * i if local_enabled else 0.0
            cumulative_total = cumulative_treasury + cumulative_local
            row = {
                'period': f'{year:04d}-{month:02d}',
                'quarter_index': i,
                'cumulative_treasury_purchase': cumulative_treasury,
                'cumulative_local_bond_purchase': cumulative_local if local_enabled else None,
                'cumulative_assumed_purchase': cumulative_total,
                'comparison_anchor': anchor_code,
                'anchor_period': anchor['period'],
                'anchor_value': anchor_value,
                'purchase_to_anchor_pct': cumulative_total / anchor_value * 100,
                'data_status': 'scenario',
                'formula': '(initial_cumulative_purchase + quarter_index * quarterly assumptions) / anchor_value',
            }
            records.append(row)
        conn.execute('''INSERT INTO fiscal_debt_scenario_runs (
            scenario_name,initial_period,initial_cumulative_purchase,quarterly_treasury_purchase,
            local_bond_assumption_enabled,quarterly_local_bond_purchase,comparison_anchor,anchor_value,
            quarters,assumptions,result_json,data_status,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            scenario_name, initial_period, initial, quarterly_treasury, int(local_enabled),
            quarterly_local if local_enabled else None, anchor_code, anchor_value, quarters,
            json.dumps(assumptions, ensure_ascii=False), json.dumps(records, ensure_ascii=False),
            'scenario', now
        ))
        conn.commit()
    warnings = ['情景推算不是官方数据，所有假设随结果展示。']
    if local_enabled:
        warnings.append('央行资产负债表无地方政府债单列项目；地方债买入仅为用户输入的情景假设，不代表官方事实。')
    return {'success': True, 'data_status': 'scenario', 'scenario_name': scenario_name,
            'assumptions': assumptions, 'records': records, 'warnings': warnings}
