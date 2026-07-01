# -*- coding: utf-8 -*-
"""中国利率与汇率模块：LPR、SHIBOR、人民币对美元中间价。

数据源(均为全国银行间同业拆借中心/中国货币网官方 JSON 接口，2026-07 实测可用)：
- LPR   POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis
- SHIBOR POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-shibor/ShiborHis
- 中间价 POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew

数据纪律：全部逐条 official + source_url；接口失败只写日志不清旧数据；不造数。
"""
import json
import sqlite3
import time
from datetime import date, datetime, timedelta

import requests

SOURCE_NAME = '全国银行间同业拆借中心(中国货币网)'
SOURCE_TYPE = 'china_rates'
LPR_API = 'https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis'
SHIBOR_API = 'https://www.chinamoney.com.cn/ags/ms/cm-u-bk-shibor/ShiborHis'
CCPR_API = 'https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew'
LPR_PAGE = 'https://www.chinamoney.com.cn/chinese/bklpr/'
SHIBOR_PAGE = 'https://www.chinamoney.com.cn/chinese/bkshibor/'
CCPR_PAGE = 'https://www.chinamoney.com.cn/chinese/bkccpr/'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
HTTP_TIMEOUT = 20

# 回填起点：LPR 改革首报 2019-08-20；SHIBOR/中间价取 2020 起(日频，够画趋势)
LPR_BACKFILL_START = date(2019, 8, 1)
DAILY_BACKFILL_START = date(2020, 1, 1)

SHIBOR_TENORS = ['ON', '1W', '2W', '1M', '3M', '6M', '9M', '1Y']


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_china_rates_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS china_rates_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_china_rates_code_period
                    ON china_rates_observations(indicator_code, period)''')
    conn.commit()


# ── 纯解析函数(可单测) ─────────────────────────────────────────────────────────
def parse_lpr_records(records):
    """chinamoney LprHis records -> obs 行。record 形如
    {"5Y":"3.50","1Y":"3.00","showDateCN":"2026-06-22"}"""
    rows = []
    for r in records or []:
        d = (r.get('showDateCN') or '').strip()
        if not d:
            continue
        for tenor, code, name in [('1Y', 'LPR_1Y', 'LPR 1年期'), ('5Y', 'LPR_5Y', 'LPR 5年期以上')]:
            v = r.get(tenor)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            rows.append({'indicator_code': code, 'indicator_name': name, 'period': d,
                         'value': v, 'unit': '%', 'frequency': 'monthly'})
    return rows


def parse_shibor_records(records):
    """ShiborHis records -> obs 行。record 含 ON/1W/.../1Y + showDateCN。"""
    rows = []
    for r in records or []:
        d = (r.get('showDateCN') or '').strip()
        if not d:
            continue
        for tenor in SHIBOR_TENORS:
            v = r.get(tenor)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            rows.append({'indicator_code': f'SHIBOR_{tenor}', 'indicator_name': f'SHIBOR {tenor}',
                         'period': d, 'value': v, 'unit': '%', 'frequency': 'daily'})
    return rows


def parse_ccpr_records(records):
    """CcprHisNew(currency=USD/CNY) records -> obs 行。record 形如
    {"date":"2026-07-01","values":["6.8067"]}"""
    rows = []
    for r in records or []:
        d = (r.get('date') or '').strip()
        vals = r.get('values') or []
        if not d or not vals:
            continue
        try:
            v = float(vals[0])
        except (TypeError, ValueError):
            continue
        rows.append({'indicator_code': 'USDCNY_CENTRAL_PARITY', 'indicator_name': '人民币对美元中间价',
                     'period': d, 'value': v, 'unit': 'CNY/USD', 'frequency': 'daily'})
    return rows


# ── 抓取 ──────────────────────────────────────────────────────────────────────
def _post_json(url, data):
    r = requests.post(url, headers=UA, data=data, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def _year_windows(start, end):
    cur = start
    while cur <= end:
        nxt = min(date(cur.year + 1, cur.month, cur.day) - timedelta(days=1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def fetch_lpr(start, end):
    rows = []
    for a, b in _year_windows(start, end):   # 接口单次窗口约一年
        d = _post_json(LPR_API, {'lang': 'CN', 'startDate': a.isoformat(), 'endDate': b.isoformat()})
        rows.extend(parse_lpr_records(d.get('records')))
        time.sleep(0.4)
    return rows


def fetch_shibor(start, end):
    rows = []
    for a, b in _year_windows(start, end):
        d = _post_json(SHIBOR_API, {'lang': 'CN', 't': '99',
                                    'startDate': a.isoformat(), 'endDate': b.isoformat()})
        rows.extend(parse_shibor_records(d.get('records')))
        time.sleep(0.4)
    return rows


def fetch_ccpr(start, end):
    rows = []
    for a, b in _year_windows(start, end):
        page = 1
        while True:
            d = _post_json(CCPR_API, {'startDate': a.isoformat(), 'endDate': b.isoformat(),
                                      'currency': 'USD/CNY', 'pageNum': page, 'pageSize': 500})
            rows.extend(parse_ccpr_records(d.get('records')))
            total = int(d.get('data', {}).get('pageTotal') or 1)
            if page >= total:
                break
            page += 1
            time.sleep(0.3)
        time.sleep(0.4)
    return rows


def update_china_rates(db_path, backfill=False):
    """增量(近45天)或全量回填。逐条 official+source_url；单源失败不影响其他源。"""
    started = datetime.now().isoformat()
    end = date.today()
    errors, inserted = [], 0
    sources = [
        ('LPR', fetch_lpr, LPR_PAGE, LPR_API, LPR_BACKFILL_START),
        ('SHIBOR', fetch_shibor, SHIBOR_PAGE, SHIBOR_API, DAILY_BACKFILL_START),
        ('USDCNY中间价', fetch_ccpr, CCPR_PAGE, CCPR_API, DAILY_BACKFILL_START),
    ]
    with connect(db_path) as conn:
        ensure_china_rates_tables(conn)
        now = datetime.now().isoformat()
        for label, fn, page_url, api_url, bf_start in sources:
            start = bf_start if backfill else max(bf_start, end - timedelta(days=45))
            try:
                rows = fn(start, end)
            except Exception as exc:
                errors.append(f'{label}: {exc}')
                continue
            for o in rows:
                cur = conn.execute('''INSERT INTO china_rates_observations (
                    indicator_code,indicator_name,period,value,unit,frequency,data_status,
                    source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at''',
                    (o['indicator_code'], o['indicator_name'], o['period'], o['value'], o['unit'],
                     o['frequency'], 'official', SOURCE_NAME, SOURCE_TYPE, page_url,
                     f'{label}历史数据(中国货币网)', f'官方 JSON 接口 {api_url}', None, now))
                inserted += cur.rowcount
        conn.commit()
    return {'success': not errors or inserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': inserted,
            'backfill': backfill, 'errors': errors}


# ── payload ───────────────────────────────────────────────────────────────────
def _series(conn, code, limit=None):
    q = 'SELECT period, value FROM china_rates_observations WHERE indicator_code=? ORDER BY period'
    rows = [dict(r) for r in conn.execute(q, (code,))]
    return rows[-limit:] if limit else rows


def _latest(conn, code):
    r = conn.execute('''SELECT * FROM china_rates_observations WHERE indicator_code=?
                        ORDER BY period DESC LIMIT 1''', (code,)).fetchone()
    return dict(r) if r else None


def build_china_rates_payload(db_path):
    with connect(db_path) as conn:
        ensure_china_rates_tables(conn)
        cov = dict(conn.execute('''SELECT COUNT(*) records, MIN(period) earliest, MAX(period) latest
                                   FROM china_rates_observations''').fetchone())
        cards = []
        for code, label in [('LPR_1Y', 'LPR 1年期'), ('LPR_5Y', 'LPR 5年期以上'),
                            ('SHIBOR_ON', 'SHIBOR 隔夜'), ('SHIBOR_1Y', 'SHIBOR 1年'),
                            ('USDCNY_CENTRAL_PARITY', '人民币对美元中间价')]:
            row = _latest(conn, code)
            cards.append({
                'label': label,
                'value': row['value'] if row else None,
                'unit': row['unit'] if row else None,
                'period': row['period'] if row else None,
                'data_status': row['data_status'] if row else 'missing',
                'source_name': row['source_name'] if row else None,
                'source_url': row['source_url'] if row else None,
                'parser_notes': row['parser_notes'] if row else None,
                'warning': None if row else '尚未抓取，点击"更新数据"。',
            })
        series = {
            'lpr': {'LPR_1Y': _series(conn, 'LPR_1Y'), 'LPR_5Y': _series(conn, 'LPR_5Y')},
            'shibor': {t: _series(conn, f'SHIBOR_{t}', limit=500) for t in ('ON', '3M', '1Y')},
            'usdcny': _series(conn, 'USDCNY_CENTRAL_PARITY', limit=800),
        }
    return {
        'data_status': 'official' if cov.get('records') else 'missing',
        'source_name': SOURCE_NAME, 'coverage': cov, 'cards': cards, 'series': series,
        'source_pages': {'lpr': LPR_PAGE, 'shibor': SHIBOR_PAGE, 'ccpr': CCPR_PAGE},
        'warnings': [] if cov.get('records') else ['尚无数据；未生成 mock。'],
        'notes': ['LPR 为每月 20 日(节假日顺延)报价；SHIBOR、中间价为交易日日频。',
                  '全部数据来自中国货币网官方接口，逐条 official。'],
    }
