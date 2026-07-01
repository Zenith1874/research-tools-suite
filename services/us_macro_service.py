# -*- coding: utf-8 -*-
"""美国宏观模块：失业率、JOLTS 离职率、联邦基金利率、10 年期美债收益率。

数据源：圣路易斯联储 FRED 的免 key CSV 端点(2026-07 实测可用)
    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES>
数据本源分别为 BLS(UNRATE/JTSQUR)与美联储 H.15(FEDFUNDS/DGS10)，FRED 为官方镜像。

数据纪律：逐条 official + source_url(FRED series 页)；失败不清旧数据；缺失值('.')跳过。
"""
import csv
import io
import sqlite3
from datetime import datetime

import requests

SOURCE_NAME = 'FRED (Federal Reserve Bank of St. Louis)'
SOURCE_TYPE = 'us_macro'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
HTTP_TIMEOUT = 25

SERIES = [
    # code, 名称, 单位, 频率, 本源说明
    ('UNRATE',   '美国失业率',            '%', 'monthly', 'BLS 经季调失业率'),
    ('JTSQUR',   'JOLTS 离职率(quits)',   '%', 'monthly', 'BLS JOLTS 主动离职率(经季调)'),
    ('FEDFUNDS', '联邦基金有效利率',       '%', 'monthly', '美联储 H.15'),
    ('DGS10',    '10年期美债收益率',       '%', 'daily',   '美联储 H.15(市场日频)'),
]


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_us_macro_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS us_macro_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_us_macro_code_period
                    ON us_macro_observations(indicator_code, period)''')
    conn.commit()


def parse_fred_csv(text, code):
    """fredgraph.csv -> obs 行。首列 observation_date，次列为系列值；缺失是 '.'。"""
    rows = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header or len(header) < 2 or 'date' not in header[0].lower():
        raise ValueError(f'{code}: 非预期的 CSV 头 {header!r}')
    for line in reader:
        if len(line) < 2:
            continue
        d, v = line[0].strip(), line[1].strip()
        if not d or v in ('', '.'):
            continue
        try:
            rows.append({'period': d, 'value': float(v)})
        except ValueError:
            continue
    return rows


def fetch_series(code):
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}'
    r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return parse_fred_csv(r.text, code)


def update_us_macro(db_path):
    """全量拉取(FRED CSV 本身就是整段历史，幂等 upsert)。单系列失败不影响其他。"""
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    with connect(db_path) as conn:
        ensure_us_macro_tables(conn)
        now = datetime.now().isoformat()
        for code, name, unit, freq, origin in SERIES:
            try:
                rows = fetch_series(code)
            except Exception as exc:
                errors.append(f'{code}: {exc}')
                continue
            page = f'https://fred.stlouisfed.org/series/{code}'
            for o in rows:
                cur = conn.execute('''INSERT INTO us_macro_observations (
                    indicator_code,indicator_name,period,value,unit,frequency,data_status,
                    source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at''',
                    (code, name, o['period'], o['value'], unit, freq, 'official',
                     SOURCE_NAME, SOURCE_TYPE, page, f'FRED {code}',
                     f'fredgraph.csv 免key端点；本源：{origin}', None, now))
                upserted += cur.rowcount
        conn.commit()
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'errors': errors}


def _series_rows(conn, code, limit=None):
    rows = [dict(r) for r in conn.execute(
        'SELECT period, value FROM us_macro_observations WHERE indicator_code=? ORDER BY period', (code,))]
    return rows[-limit:] if limit else rows


def build_us_macro_payload(db_path):
    with connect(db_path) as conn:
        ensure_us_macro_tables(conn)
        cov = dict(conn.execute('''SELECT COUNT(*) records, MIN(period) earliest, MAX(period) latest
                                   FROM us_macro_observations''').fetchone())
        cards, series = [], {}
        for code, name, unit, freq, origin in SERIES:
            r = conn.execute('''SELECT * FROM us_macro_observations WHERE indicator_code=?
                                ORDER BY period DESC LIMIT 1''', (code,)).fetchone()
            cards.append({
                'label': name, 'value': r['value'] if r else None,
                'unit': unit, 'period': r['period'] if r else None,
                'data_status': r['data_status'] if r else 'missing',
                'source_name': SOURCE_NAME if r else None,
                'source_url': r['source_url'] if r else None,
                'parser_notes': r['parser_notes'] if r else None,
                'warning': None if r else '尚未抓取，点击"更新数据"。',
            })
            # 月频给全量(几百点)；日频截近 ~3 年
            series[code] = _series_rows(conn, code, limit=800 if freq == 'daily' else None)
    return {
        'data_status': 'official' if cov.get('records') else 'missing',
        'source_name': SOURCE_NAME, 'coverage': cov, 'cards': cards, 'series': series,
        'warnings': [] if cov.get('records') else ['尚无数据；未生成 mock。'],
        'notes': ['FRED 免key CSV 为官方镜像，本源 BLS / 美联储 H.15；逐条 official。',
                  'JOLTS 离职率(quits rate)是劳动力市场"用脚投票"指标，与 WFH/RTO 研究相关。'],
    }
