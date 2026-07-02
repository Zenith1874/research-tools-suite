# -*- coding: utf-8 -*-
"""全国财政收支模块：一般公共预算收入/支出 + 政府性基金收入/支出(月度累计 YTD)。

数据源：财政部国库司"财政收支情况"月度报告(gks.mof.gov.cn/tongjishuju/)。
口径说明：官方报告为年初至今累计值；差额=收入-支出 为 derived(带公式)，
不等于官方"赤字"(官方赤字按预算口径含调入资金/结转结余等)。
数据纪律：逐条 official + 报告原文 source_url；解析失败只记日志不清旧数据。
"""
import re
import sqlite3
import time
from datetime import datetime

from services.fiscal_debt_service import fetch_url

SOURCE_NAME = '财政部国库司'
SOURCE_TYPE = 'mof_fiscal_budget'
INDEX_URL = 'https://gks.mof.gov.cn/tongjishuju/index.htm'

INDICATORS = {
    'general_budget_revenue_ytd':  '全国一般公共预算收入(YTD)',
    'general_budget_expenditure_ytd': '全国一般公共预算支出(YTD)',
    'general_budget_balance_ytd': '全国一般公共预算收支差额(YTD)',
    'gov_fund_revenue_ytd': '全国政府性基金预算收入(YTD)',
    'gov_fund_expenditure_ytd': '全国政府性基金预算支出(YTD)',
}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_fiscal_budget_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_budget_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.commit()


# ── 纯解析(可单测) ────────────────────────────────────────────────────────────
def parse_budget_period_from_title(title):
    """报告标题 -> 截止月份 'YYYY-MM'。
    "2026年1-5月财政收支情况"->2026-05；"2026年一季度"->03；"上半年"->06；
    "前三季度"->09；"2025年财政收支情况"(全年)->2025-12。"""
    m = re.search(r'(20\d{2})年', title)
    if not m:
        return None
    year = m.group(1)
    m2 = re.search(r'1-(\d{1,2})月', title)
    if m2:
        return f'{year}-{int(m2.group(1)):02d}'
    for kw, mm in [('一季度', '03'), ('上半年', '06'), ('前三季度', '09'), ('三季度', '09')]:
        if kw in title:
            return f'{year}-{mm}'
    if re.search(r'20\d{2}年财政收支情况', title):
        return f'{year}-12'
    return None


def parse_budget_report_text(text):
    """报告正文 -> {indicator_code: value}。正文数字与"亿元"间可能有空格。"""
    t = re.sub(r'\s|&nbsp;', '', text)
    out = {}
    pats = [
        ('general_budget_revenue_ytd', r'全国一般公共预算收入([\d.]+)亿元'),
        ('general_budget_expenditure_ytd', r'全国一般公共预算支出([\d.]+)亿元'),
        ('gov_fund_revenue_ytd', r'全国政府性基金预算收入([\d.]+)亿元'),
        ('gov_fund_expenditure_ytd', r'全国政府性基金预算支出([\d.]+)亿元'),
    ]
    for code, pat in pats:
        m = re.search(pat, t)
        if m:
            out[code] = float(m.group(1))
    return out


def discover_budget_reports(max_pages=4):
    """索引页(含分页 index_1.htm…) -> [(url, title)]，新在前。"""
    links = []
    for i in range(max_pages):
        url = INDEX_URL if i == 0 else INDEX_URL.replace('index.htm', f'index_{i}.htm')
        try:
            html = fetch_url(url)
        except Exception:
            break
        page_links = re.findall(r'href="(\./[^"]+|https?://gks\.mof\.gov\.cn[^"]+)"[^>]*>([^<]*财政收支情况[^<]*)<', html)
        for href, title in page_links:
            if href.startswith('./'):
                href = 'https://gks.mof.gov.cn/tongjishuju/' + href[2:]
            links.append((href, title.strip()))
        if not page_links:
            break
        time.sleep(0.4)
    seen, out = set(), []
    for href, title in links:
        if href not in seen:
            seen.add(href)
            out.append((href, title))
    return out


def update_fiscal_budget(db_path, max_reports=30):
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    reports = discover_budget_reports()
    with connect(db_path) as conn:
        ensure_fiscal_budget_tables(conn)
        now = datetime.now().isoformat()
        for url, title in reports[:max_reports]:
            period = parse_budget_period_from_title(title)
            if not period:
                continue
            # 已完整入库的期数跳过(5 项指标齐)
            n = conn.execute('SELECT COUNT(*) FROM fiscal_budget_observations WHERE period=?', (period,)).fetchone()[0]
            if n >= 5:
                continue
            try:
                html = fetch_url(url)
                text = re.sub(r'<[^>]+>', ' ', html)
                vals = parse_budget_report_text(text)
            except Exception as exc:
                errors.append(f'{title}: {exc}')
                continue
            if 'general_budget_revenue_ytd' in vals and 'general_budget_expenditure_ytd' in vals:
                vals['general_budget_balance_ytd'] = round(
                    vals['general_budget_revenue_ytd'] - vals['general_budget_expenditure_ytd'], 1)
            for code, value in vals.items():
                derived = code == 'general_budget_balance_ytd'
                cur = conn.execute('''INSERT INTO fiscal_budget_observations (
                    indicator_code,indicator_name,period,value,unit,data_status,
                    source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                    value=excluded.value, source_url=excluded.source_url, updated_at=excluded.updated_at''',
                    (code, INDICATORS[code], period, value, '亿元',
                     'derived' if derived else 'official', SOURCE_NAME, SOURCE_TYPE, url, title,
                     '解析自财政部国库司"财政收支情况"月度报告正文；官方口径为年初至今累计。',
                     'general_budget_revenue_ytd - general_budget_expenditure_ytd（不等于官方预算口径赤字）' if derived else None,
                     now))
                upserted += cur.rowcount
            time.sleep(0.5)
        conn.commit()
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'reports_found': len(reports), 'errors': errors[:8]}


def build_fiscal_budget_payload(db_path):
    with connect(db_path) as conn:
        ensure_fiscal_budget_tables(conn)
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_budget_observations ORDER BY period, indicator_code')]
    by_period = {}
    for r in rows:
        by_period.setdefault(r['period'], {'period': r['period'], 'source_url': r['source_url']})[r['indicator_code']] = r['value']
    series = sorted(by_period.values(), key=lambda x: x['period'])
    latest = series[-1] if series else None
    latest_rows = {r['indicator_code']: r for r in rows if latest and r['period'] == latest['period']}
    cards = []
    for code in ('general_budget_revenue_ytd', 'general_budget_expenditure_ytd',
                 'general_budget_balance_ytd', 'gov_fund_revenue_ytd', 'gov_fund_expenditure_ytd'):
        r = latest_rows.get(code)
        cards.append({
            'label': INDICATORS[code], 'value': r['value'] if r else None, 'unit': '亿元',
            'period': r['period'] if r else None,
            'data_status': r['data_status'] if r else 'missing',
            'source_name': SOURCE_NAME if r else None,
            'source_url': r['source_url'] if r else None,
            'source_title': r['source_title'] if r else None,
            'parser_notes': r['parser_notes'] if r else None,
            'formula': r['formula'] if r else None,
            'warning': None if r else '尚未抓取。',
        })
    return {
        'data_status': 'official' if rows else 'missing',
        'coverage': {'periods': len(series),
                     'earliest': series[0]['period'] if series else None,
                     'latest': series[-1]['period'] if series else None},
        'cards': cards, 'series': series,
        'warnings': [] if rows else ['财政收支尚未抓取；未生成 mock。'],
        'notes': ['官方报告为年初至今累计(YTD)；收支差额为 derived，不等于官方预算口径赤字。'],
    }
