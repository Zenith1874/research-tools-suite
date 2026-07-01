# -*- coding: utf-8 -*-
"""中国利率与汇率模块：LPR、SHIBOR、人民币对美元中间价。

数据源(均为全国银行间同业拆借中心/中国货币网官方 JSON 接口，2026-07 实测可用)：
- LPR   POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis
- SHIBOR POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-shibor/ShiborHis
- 中间价 POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew

数据纪律：全部逐条 official + source_url；接口失败只写日志不清旧数据；不造数。
"""
import json
import re
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

# 回填起点：LPR 改革首报 2019-08-20(旧版 2013-2019 贷款基础利率官方接口不提供历史数值，
# LprHis 的日期区间模式只返回日期不返回值——实测 2026-07，故不接入)；
# SHIBOR 2006-10-08 创设；中间价接口实测最早到 2006 年。
LPR_BACKFILL_START = date(2019, 8, 20)
DAILY_BACKFILL_START = date(2006, 1, 1)
# LPR 历史改用"公告栏"接口：每月公告一篇(含正文页 URL)，逐条 official。
LPR_NOTICE_API = 'https://www.chinamoney.com.cn/ags/ms/cm-s-notice-query/contentsinshorttime'
LPR_NOTICE_CHANNEL = '3686'   # bklprmkn2 = LPR 市场公告栏目

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
def parse_lpr_announcement_text(text):
    """LPR 公告正文 -> (1Y, 5Y)。官方正文空格位置随年代乱飘
    ("1年期LPR为 3. 0 %" / "1 年期 LPR 为 3.85%")——先删光空白再匹配最稳。"""
    t = re.sub(r'\s', '', text)
    m1 = re.search(r'1年期LPR为([\d.]+)%', t)
    m5 = re.search(r'5年期以上LPR为([\d.]+)%', t)
    return (float(m1.group(1)) if m1 else None,
            float(m5.group(1)) if m5 else None)


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


def fetch_lpr(start, end, max_pages=8):
    """从中国货币网 LPR 公告栏抓取：列表 API 分页(15/页) → 逐篇正文解析 1Y/5Y。
    每行带各自公告正文 source_url，逐条 official。
    (LprHis 数值接口的日期区间模式只回日期不回值，不可用。)"""
    rows = []
    for pg in range(1, max_pages + 1):
        d = _post_json(LPR_NOTICE_API, {'channelId': LPR_NOTICE_CHANNEL, 'pageSize': 15, 'pageNo': pg})
        recs = d.get('records') or []
        if not recs:
            break
        reached_older = False
        for x in recs:
            title = x.get('title') or ''
            if '公布贷款市场报价利率' not in title:
                continue
            md = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', title)
            if not md:
                continue
            period = f'{md.group(1)}-{int(md.group(2)):02d}-{int(md.group(3)):02d}'
            pdate = date.fromisoformat(period)
            if pdate > end:
                continue
            if pdate < start:
                reached_older = True
                break                      # 列表按时间倒序，更老的不用再翻
            url = 'https://www.chinamoney.com.cn' + (x.get('draftPath') or '')
            try:
                r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
                r.encoding = 'utf-8'
                text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', r.text))
                v1, v5 = parse_lpr_announcement_text(text)
            except Exception:
                continue                   # 单篇失败跳过，不影响其余
            for v, code, name in [(v1, 'LPR_1Y', 'LPR 1年期'), (v5, 'LPR_5Y', 'LPR 5年期以上')]:
                if v is not None:
                    rows.append({'indicator_code': code, 'indicator_name': name, 'period': period,
                                 'value': v, 'unit': '%', 'frequency': 'monthly', 'source_url': url})
            time.sleep(0.4)
        if reached_older:
            break
        time.sleep(0.3)
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
                    value=excluded.value, source_url=excluded.source_url, updated_at=excluded.updated_at''',
                    (o['indicator_code'], o['indicator_name'], o['period'], o['value'], o['unit'],
                     o['frequency'], 'official', SOURCE_NAME, SOURCE_TYPE,
                     o.get('source_url') or page_url,   # LPR 逐篇公告有各自正文 URL
                     f'{label}历史数据(中国货币网)', f'官方接口 {api_url}', None, now))
                inserted += cur.rowcount
        conn.commit()
    return {'success': not errors or inserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': inserted,
            'backfill': backfill, 'errors': errors}


# ── payload ───────────────────────────────────────────────────────────────────
def _downsample(rows, max_points=1200):
    """长日频序列等距降采样到 max_points(保首尾)，只影响图表密度不影响存储。"""
    n = len(rows)
    if n <= max_points:
        return rows
    stride = (n - 1) / (max_points - 1)
    idxs = sorted({round(i * stride) for i in range(max_points)} | {0, n - 1})
    return [rows[i] for i in idxs]


def _series(conn, code, max_points=1200):
    q = 'SELECT period, value FROM china_rates_observations WHERE indicator_code=? ORDER BY period'
    rows = [dict(r) for r in conn.execute(q, (code,))]
    return _downsample(rows, max_points)


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
            'shibor': {t: _series(conn, f'SHIBOR_{t}') for t in ('ON', '3M', '1Y')},
            'usdcny': _series(conn, 'USDCNY_CENTRAL_PARITY'),
        }
    return {
        'data_status': 'official' if cov.get('records') else 'missing',
        'source_name': SOURCE_NAME, 'coverage': cov, 'cards': cards, 'series': series,
        'source_pages': {'lpr': LPR_PAGE, 'shibor': SHIBOR_PAGE, 'ccpr': CCPR_PAGE},
        'warnings': [] if cov.get('records') else ['尚无数据；未生成 mock。'],
        'notes': ['LPR：2019-08-20 改革首报起，逐月取自中国货币网 LPR 公告正文(每条带原文链接)。'
                  '旧版贷款基础利率(2013-2019)官方接口不提供历史数值，未接入。',
                  'SHIBOR 自 2006-10 创设；中间价历史取自 2006 年起。日频长序列图表按等距降采样展示(约1200点)，存储为全量。',
                  '全部数据来自中国货币网官方接口，逐条 official。'],
    }
