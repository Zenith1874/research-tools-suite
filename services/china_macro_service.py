# -*- coding: utf-8 -*-
"""中国实体经济月度指标:CPI、PPI、PMI(统计局官方新闻稿)。

来源:统计局月度新闻稿(www.stats.gov.cn,与 70 城/销售同一发布体系;
数据 API 对境外 IP 403,新闻稿页可访问)。发现走站内搜索 api.so-gov.cn。

指标(逐条 official + source_url):
- CN_CPI_YOY / CN_CPI_MOM         《X年X月份居民消费价格同比…》正文
- CN_PPI_YOY / CN_PPI_MOM         《X年X月份工业生产者出厂价格…》正文
- CN_PMI_MFG / CN_PMI_NONMFG / CN_PMI_COMP  《X年X月中国采购经理指数运行情况》正文

数据纪律:缺失如实缺(核心CPI不在新闻稿正文,不抓不估);失败不清旧数据;
幂等 upsert;"持平"解析为 0.0(官方措辞,非缺失)。
"""
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime

import requests

from services.housing_price_service import (
    NBS_SEARCH_API, NBS_SEARCH_SITE_CODE, UA, HTTP_TIMEOUT, _release_path_rank,
)

SOURCE_NAME = '国家统计局'
SOURCE_TYPE = 'china_macro'

INDICATORS = {
    'CN_CPI_YOY': ('居民消费价格(CPI)同比', '%', 'monthly'),
    'CN_CPI_MOM': ('居民消费价格(CPI)环比', '%', 'monthly'),
    'CN_PPI_YOY': ('工业生产者出厂价格(PPI)同比', '%', 'monthly'),
    'CN_PPI_MOM': ('工业生产者出厂价格(PPI)环比', '%', 'monthly'),
    'CN_PMI_MFG': ('制造业PMI', '%', 'monthly'),
    'CN_PMI_NONMFG': ('非制造业商务活动指数', '%', 'monthly'),
    'CN_PMI_COMP': ('综合PMI产出指数', '%', 'monthly'),
}

RELEASES = {
    'cpi': {'query': '居民消费价格',
            'title_re': re.compile(r'^(20\d{2})年(\d{1,2})月份?居民消费价格')},
    'ppi': {'query': '工业生产者出厂价格',
            'title_re': re.compile(r'^(20\d{2})年(\d{1,2})月份?工业生产者出厂价格')},
    'pmi': {'query': '中国采购经理指数运行情况',
            'title_re': re.compile(r'^(20\d{2})年(\d{1,2})月中国采购经理指数运行情况')},
}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_china_macro_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS china_macro_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_china_macro_code_period
                    ON china_macro_observations(indicator_code, period)''')
    conn.commit()


def _clean_text(html):
    return re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', html or ''))


def _signed(direction, number):
    """官方措辞定号:上涨/增长=+,下降=−;number 为字符串数值。"""
    return float(number) * (-1 if direction == '下降' else 1)


def _change(text, prefix):
    """解析 '<prefix>同比上涨X%' / '下降X%' / '持平' → (yoy, mom);未命中为 None。
    环比必须锚定:优先带前缀(现行措辞独立成句),否则只在同比命中位置后 80 字符窗口内找
    (早年措辞同比环比同句),绝不全篇任意匹配以免抓到分项数字。"""
    yoy = mom = None
    yoy_end = None
    m = re.search(prefix + r'同比(上涨|下降)([\d.]+)%', text)
    if m:
        yoy, yoy_end = _signed(m.group(1), m.group(2)), m.end()
    else:
        m = re.search(prefix + r'同比持平', text)
        if m:
            yoy, yoy_end = 0.0, m.end()
    m = re.search(prefix + r'环比(上涨|下降)([\d.]+)%', text)
    if m:
        mom = _signed(m.group(1), m.group(2))
    elif re.search(prefix + r'环比持平', text):
        mom = 0.0
    elif yoy_end is not None:
        window = text[yoy_end:yoy_end + 80]
        m = re.search(r'环比(上涨|下降)([\d.]+)%', window)
        if m:
            mom = _signed(m.group(1), m.group(2))
        elif re.search(r'环比持平', window):
            mom = 0.0
    return yoy, mom


def parse_cpi_article(html):
    text = _clean_text(html)
    yoy, mom = _change(text, r'全国居民消费价格(?:总水平)?')
    out = {}
    if yoy is not None:
        out['CN_CPI_YOY'] = yoy
    if mom is not None:
        out['CN_CPI_MOM'] = mom
    return out


def parse_ppi_article(html):
    text = _clean_text(html)
    yoy, mom = _change(text, r'全国工业生产者出厂价格')
    out = {}
    if yoy is not None:
        out['CN_PPI_YOY'] = yoy
    if mom is not None:
        out['CN_PPI_MOM'] = mom
    return out


def parse_pmi_article(html):
    text = _clean_text(html)
    out = {}
    m = re.search(r'制造业采购经理指数(?:[（(]PMI[）)])?为([\d.]+)%', text)
    if m:
        out['CN_PMI_MFG'] = float(m.group(1))
    m = re.search(r'非制造业商务活动指数为([\d.]+)%', text)
    if m:
        out['CN_PMI_NONMFG'] = float(m.group(1))
    m = re.search(r'综合PMI产出指数为([\d.]+)%', text)
    if m:
        out['CN_PMI_COMP'] = float(m.group(1))
    return out


PARSERS = {'cpi': parse_cpi_article, 'ppi': parse_ppi_article, 'pmi': parse_pmi_article}


def discover_releases(kind, start_year, end_year=None, max_pages=6, sleep_seconds=0.15):
    """站内搜索按年发现某类新闻稿;返回 {period: (url, title)},优先 /sj/zxfb/ 路径。"""
    spec = RELEASES[kind]
    end_year = int(end_year or datetime.now().year)
    headers = {**UA, 'Referer': 'https://www.stats.gov.cn/search/s'}
    found = {}
    for year in range(end_year, int(start_year) - 1, -1):
        for page in range(1, max_pages + 1):
            response = requests.post(NBS_SEARCH_API, data={
                'siteCode': NBS_SEARCH_SITE_CODE, 'qt': f'{year}年{spec["query"]}',
                'page': page, 'pageSize': 20, 'keyPlace': '1', 'sort': 'relevance',
            }, headers=headers, timeout=HTTP_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
            if not payload.get('ok'):
                raise ValueError(f'统计局搜索失败: {payload.get("msg") or payload.get("code")}')
            docs = payload.get('resultDocs') or []
            for doc in docs:
                data = doc.get('data', doc)
                title = re.sub(r'<[^>]+>', '', str(data.get('title') or '')).strip()
                url = data.get('url') or ''
                m = spec['title_re'].match(title)
                if not m or not url:
                    continue
                period = f'{m.group(1)}-{int(m.group(2)):02d}'
                current = found.get(period)
                if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
                    found[period] = (url, title)
            if (not int(payload.get('currentHits') or 0)
                    or page * 20 >= int(payload.get('totalHits') or 0)):
                break
            time.sleep(sleep_seconds)
        time.sleep(sleep_seconds)
    return found


def update_china_macro(db_path, start_year=None, sleep_seconds=0.3):
    """抓取并入库;默认只查今年+去年(增量),start_year 指定则深回填。
    单篇失败只记录,不影响其他;绝不清旧数据。"""
    started = datetime.now().isoformat()
    this_year = datetime.now().year
    start = int(start_year or this_year - 1)
    errors, upserted = [], 0
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        for kind in RELEASES:
            try:
                releases = discover_releases(kind, start)
            except Exception as exc:
                errors.append(f'{kind} discover: {exc}')
                continue
            for period in sorted(releases):
                url, title = releases[period]
                have = conn.execute(
                    'SELECT COUNT(*) FROM china_macro_observations '
                    'WHERE period=? AND indicator_code LIKE ?',
                    (period, f'CN_{kind.upper()}%')).fetchone()[0]
                expected = sum(1 for c in INDICATORS if c.startswith(f'CN_{kind.upper()}'))
                if have >= expected:
                    continue
                try:
                    response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    values = PARSERS[kind](response.text)
                except Exception as exc:
                    errors.append(f'{kind} {period}: {exc}')
                    continue
                now = datetime.now().isoformat()
                for code, value in values.items():
                    name, unit, freq = INDICATORS[code]
                    cur = conn.execute('''INSERT INTO china_macro_observations (
                        indicator_code,indicator_name,period,value,unit,frequency,data_status,
                        source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(indicator_code,period) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at''',
                        (code, name, period, value, unit, freq, 'official',
                         SOURCE_NAME, SOURCE_TYPE, url, title,
                         '统计局新闻稿正文解析;上涨/下降定号,持平=0', None, now))
                    upserted += cur.rowcount
                conn.commit()
                time.sleep(sleep_seconds)
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(),
            'records_upserted': upserted, 'errors': errors}
