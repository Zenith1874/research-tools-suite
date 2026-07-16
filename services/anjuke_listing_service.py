# -*- coding: utf-8 -*-
"""安居客二手房挂牌价参考数据。

合规边界：低频、持久会话、原始 HTML 本地缓存；验证码/滑块/访问验证页
一律记录 blocked 并跳过，不尝试破解。商业挂牌数据只写入独立本地库，
不得进入 pboc_data.db 或公开仓库。
"""
import json
import logging
import os
import random
import re
import sqlite3
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from services.anjuke_city_map import (
    ANJUKE_CITY_SLUGS,
    ANJUKE_EXTRA_CITY_SLUGS,
    city_market_url,
    city_slug,
)

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(ROOT, 'data', 'housing_listing.db')
RAW_ROOT = os.path.join(ROOT, 'data', 'anjuke_raw')
DATA_STATUS = 'listing_reference'
PRICE_MIN = 2000
PRICE_MAX = 200000
MAX_REQUESTS = 100
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36')
BLOCK_MARKERS = ('访问验证', '请输入验证码', 'antibot/verifycode', '滑块验证')
TIER1 = ('北京', '上海', '广州', '深圳')


def connect(db_path=None):
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS anjuke_city_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT, period TEXT, avg_price REAL, mom_pct REAL, yoy_pct REAL,
        data_status TEXT DEFAULT 'listing_reference', source_url TEXT,
        fetched_at TEXT, raw_cached TEXT,
        UNIQUE(city, period)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS anjuke_fetch_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT, url TEXT, http_status INTEGER, bytes INTEGER,
        outcome TEXT, fetched_at TEXT
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_anjuke_listing_period ON anjuke_city_listings(period, city)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_anjuke_fetch_city_time ON anjuke_fetch_log(city, fetched_at)')
    conn.commit()


def is_blocked_response(content, final_url=''):
    """短验证壳或明确验证标记均判 blocked；不得继续解析或重试。"""
    if isinstance(content, str):
        raw = content.encode('utf-8', errors='ignore')
        text = content
    else:
        raw = content or b''
        text = raw.decode('utf-8', errors='ignore')
    haystack = final_url + '\n' + text
    return len(raw) < 5000 or any(marker in haystack for marker in BLOCK_MARKERS)


def _split_js_args(text):
    """拆分 Nuxt IIFE 的原始参数，仅处理顶层逗号和引号。"""
    out, start, quote, escaped = [], 0, None, False
    for i, ch in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == ',':
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return out


def _decode_js_literal(token):
    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return bytes(token[1:-1], 'utf-8').decode('unicode_escape')
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    if token in ('null', 'void 0', 'undefined'):
        return None
    if token == 'true':
        return True
    if token == 'false':
        return False
    try:
        return float(token) if any(c in token for c in '.eE') else int(token)
    except ValueError:
        return token


def _nuxt_aliases(script):
    prefix = 'window.__NUXT__=(function('
    if not script.lstrip().startswith(prefix):
        raise ValueError('未识别 window.__NUXT__ IIFE 结构')
    start = script.find(prefix) + len(prefix)
    params_end = script.find('){', start)
    args_mark = script.rfind('}(')
    args_end = script.rfind('));')
    if params_end < 0 or args_mark < 0 or args_end <= args_mark:
        raise ValueError('Nuxt IIFE 参数边界异常')
    names = [x.strip() for x in script[start:params_end].split(',') if x.strip()]
    values = [_decode_js_literal(x) for x in _split_js_args(script[args_mark + 2:args_end])]
    if len(names) != len(values):
        raise ValueError(f'Nuxt 参数不匹配: {len(names)} names / {len(values)} values')
    return dict(zip(names, values))


def _resolve(token, aliases):
    token = token.strip()
    return aliases[token] if token in aliases else _decode_js_literal(token)


def _object_fields(fragment, aliases):
    fields = {}
    for part in _split_js_args(fragment):
        if ':' not in part:
            continue
        key, token = part.split(':', 1)
        fields[key.strip().strip('"\'')] = _resolve(token, aliases)
    return fields


def _extract_nuxt_script(html):
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script'):
        text = script.string or script.get_text()
        if text and 'window.__NUXT__' in text:
            return text
    raise ValueError('页面没有 window.__NUXT__ 数据块')


def _period_from_short_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}-\d{2}', value):
        return None
    year, month = (int(x) for x in value.split('-'))
    if not 1 <= month <= 12:
        return None
    return f'20{year:02d}-{month:02d}'


def _pct(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return round((cur / prev - 1) * 100, 2)


def parse_anjuke_city_page(html, source_url, fetched_at=None, allow_small_fixture=False):
    """解析城市 market 页，返回当前值和页面内月度序列。

    页面当前采用 Nuxt SSR：priceTrendReportData.priceInfo 为当月官方展示值，
    trendType=3 的 city 数组为月度挂牌均价。历史环比/同比由同页价格序列计算，
    当月百分比优先采用页面直接字段。
    """
    raw = html.encode('utf-8') if isinstance(html, str) else html
    blocked = is_blocked_response(raw, source_url)
    if allow_small_fixture and len(raw) < 5000:
        decoded = raw.decode('utf-8', errors='ignore')
        blocked = any(marker in source_url + '\n' + decoded for marker in BLOCK_MARKERS)
    if blocked:
        raise PermissionError('blocked: 安居客访问验证页')
    text = raw.decode('utf-8', errors='replace')
    script = _extract_nuxt_script(text)
    aliases = _nuxt_aliases(script)
    start = script.find('priceTrendReportData:')
    if start < 0:
        raise ValueError('缺少 priceTrendReportData')
    region = script[start:script.find(',isXFEmpty:', start) if script.find(',isXFEmpty:', start) > start else None]

    city_match = re.search(r'cityName:([^,{}]+)', region)
    city = _resolve(city_match.group(1), aliases) if city_match else None
    info_match = re.search(r'priceInfo:\{([^{}]*)\}', region)
    price_info = _object_fields(info_match.group(1), aliases) if info_match else {}

    monthly = {}
    for group in re.finditer(r'\{trendType:([^,{}]+),city:\[(.*?)\],area:', region, re.S):
        trend_type = str(_resolve(group.group(1), aliases))
        if trend_type != '3':
            continue
        for item in re.finditer(r'\{date:([^,{}]+),price:([^,{}]+)\}', group.group(2)):
            period = _period_from_short_date(_resolve(item.group(1), aliases))
            try:
                price = float(_resolve(item.group(2), aliases))
            except (TypeError, ValueError):
                continue
            if period and PRICE_MIN <= price <= PRICE_MAX:
                monthly[period] = price

    fetched_dt = datetime.fromisoformat(fetched_at) if fetched_at else datetime.now()
    current_period = None
    if price_info.get('month') is not None:
        month = int(price_info['month'])
        year = fetched_dt.year - (1 if month > fetched_dt.month + 1 else 0)
        current_period = f'{year}-{month:02d}'
    try:
        current_price = float(price_info.get('price'))
    except (TypeError, ValueError):
        current_price = None
    if current_price is not None:
        if not PRICE_MIN <= current_price <= PRICE_MAX:
            raise ValueError(f'挂牌均价越界: {current_price}')
        if current_period:
            monthly[current_period] = current_price

    if not monthly:
        raise ValueError(f'{city or "未知城市"}页面正常返回但挂牌字段为空')

    records = []
    for period in sorted(monthly):
        price = monthly[period]
        year, month = (int(x) for x in period.split('-'))
        prev_month = f'{year - 1}-12' if month == 1 else f'{year}-{month - 1:02d}'
        prev_year = f'{year - 1}-{month:02d}'
        records.append({
            'city': city,
            'period': period,
            'avg_price': price,
            'mom_pct': _pct(price, monthly.get(prev_month)),
            'yoy_pct': _pct(price, monthly.get(prev_year)),
        })
    if current_period:
        current = next((r for r in records if r['period'] == current_period), None)
        if current:
            for key, src_key in (('mom_pct', 'monthChange'), ('yoy_pct', 'yearChange')):
                try:
                    current[key] = float(price_info[src_key])
                except (KeyError, TypeError, ValueError):
                    pass
    return {'city': city, 'current_period': current_period or max(monthly), 'records': records,
            'history_points': len(monthly), 'source_url': source_url}


def _cache_path(city, period):
    rel = os.path.join('data', 'anjuke_raw', period, f'{city_slug(city)}.html')
    return rel, os.path.join(ROOT, rel)


def _log_fetch(conn, city, url, status, size, outcome, fetched_at):
    conn.execute('''INSERT INTO anjuke_fetch_log
        (city,url,http_status,bytes,outcome,fetched_at) VALUES (?,?,?,?,?,?)''',
                 (city, url, status, size, outcome, fetched_at))


def update_anjuke_listings(db_path=None, cities=None, sleep_range=(2.0, 4.0), max_requests=MAX_REQUESTS):
    """低频更新 70 城；全局最多 100 次请求，blocked 不重试，旧数据不清除。"""
    selected = list(cities or ANJUKE_CITY_SLUGS)
    session = requests.Session()
    session.headers.update({
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.anjuke.com/fangjia/',
    })
    counters = {'cities_ok': 0, 'cities_blocked': 0, 'cities_failed': 0,
                'records_upserted': 0, 'requests': 0}
    errors = []
    with connect(db_path) as conn:
        ensure_tables(conn)
        for index, city in enumerate(selected):
            url = city_market_url(city)
            if not url:
                counters['cities_failed'] += 1
                errors.append(f'{city}: 无 URL 映射')
                continue
            fetched_at = datetime.now().isoformat()
            expected_period = datetime.now().strftime('%Y-%m')
            cached_rel, cached_abs = _cache_path(city, expected_period)
            if os.path.exists(cached_abs):
                try:
                    cache_fetched_at = datetime.fromtimestamp(os.path.getmtime(cached_abs)).isoformat()
                    with open(cached_abs, 'rb') as fh:
                        parsed = parse_anjuke_city_page(fh.read(), url, cache_fetched_at)
                    if parsed.get('city') and parsed['city'] != city:
                        raise ValueError(f"页面城市错配: expected={city} actual={parsed['city']}")
                    for record in parsed['records']:
                        cur = conn.execute('''INSERT INTO anjuke_city_listings
                            (city,period,avg_price,mom_pct,yoy_pct,data_status,source_url,fetched_at,raw_cached)
                            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(city,period) DO UPDATE SET
                              avg_price=excluded.avg_price,mom_pct=excluded.mom_pct,yoy_pct=excluded.yoy_pct,
                              data_status=excluded.data_status,source_url=excluded.source_url,
                              fetched_at=excluded.fetched_at,raw_cached=excluded.raw_cached''',
                            (city, record['period'], record['avg_price'], record['mom_pct'], record['yoy_pct'],
                             DATA_STATUS, url, cache_fetched_at, cached_rel))
                        counters['records_upserted'] += cur.rowcount
                    counters['cities_ok'] += 1
                    conn.commit()
                    continue
                except Exception as exc:
                    log.warning('安居客缓存无法复用 %s: %s；本轮重新抓取', cached_rel, exc)
            if index and sleep_range[1] > 0:
                time.sleep(random.uniform(*sleep_range))
            response = None
            last_error = None
            for attempt in range(3):
                if counters['requests'] >= max_requests:
                    last_error = RuntimeError(f'达到单轮请求上限 {max_requests}')
                    break
                if attempt:
                    time.sleep(min(8.0, 2 ** (attempt + 1)) + random.uniform(0, 1))
                try:
                    counters['requests'] += 1
                    response = session.get(url, timeout=25, allow_redirects=True)
                    if response.status_code >= 500:
                        last_error = RuntimeError(f'HTTP {response.status_code}')
                        continue
                    break
                except requests.RequestException as exc:
                    last_error = exc
            if response is None or response.status_code >= 500:
                counters['cities_failed'] += 1
                status = response.status_code if response is not None else None
                size = len(response.content) if response is not None else 0
                _log_fetch(conn, city, url, status, size, 'parse_fail', fetched_at)
                errors.append(f'{city}: {last_error}')
                conn.commit()
                continue
            content = response.content
            if is_blocked_response(content, response.url):
                counters['cities_blocked'] += 1
                _log_fetch(conn, city, url, response.status_code, len(content), 'blocked', fetched_at)
                conn.commit()
                continue
            try:
                parsed = parse_anjuke_city_page(content, url, fetched_at)
                if parsed.get('city') and parsed['city'] != city:
                    raise ValueError(f"页面城市错配: expected={city} actual={parsed['city']}")
                period = parsed['current_period']
                rel_path, abs_path = _cache_path(city, period)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, 'wb') as fh:
                    fh.write(content)
                for record in parsed['records']:
                    cur = conn.execute('''INSERT INTO anjuke_city_listings
                        (city,period,avg_price,mom_pct,yoy_pct,data_status,source_url,fetched_at,raw_cached)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(city,period) DO UPDATE SET avg_price=excluded.avg_price,
                          mom_pct=excluded.mom_pct,yoy_pct=excluded.yoy_pct,
                          data_status=excluded.data_status,source_url=excluded.source_url,
                          fetched_at=excluded.fetched_at,raw_cached=excluded.raw_cached''',
                        (city, record['period'], record['avg_price'], record['mom_pct'], record['yoy_pct'],
                         DATA_STATUS, url, fetched_at, rel_path))
                    counters['records_upserted'] += cur.rowcount
                _log_fetch(conn, city, url, response.status_code, len(content), 'success', fetched_at)
                counters['cities_ok'] += 1
            except Exception as exc:
                counters['cities_failed'] += 1
                _log_fetch(conn, city, url, response.status_code, len(content), 'parse_fail', fetched_at)
                errors.append(f'{city}: {exc}')
            conn.commit()
    return {'success': counters['cities_ok'] > 0, **counters, 'errors': errors[:8],
            'finished_at': datetime.now().isoformat()}


def build_anjuke_payload(db_path=None):
    with connect(db_path) as conn:
        ensure_tables(conn)
        latest = conn.execute('SELECT MAX(period) FROM anjuke_city_listings').fetchone()[0]
        rows = [] if not latest else [dict(r) for r in conn.execute(
            'SELECT * FROM anjuke_city_listings WHERE period=? ORDER BY city', (latest,))]
        latest_logs = [dict(r) for r in conn.execute('''SELECT f.* FROM anjuke_fetch_log f JOIN
            (SELECT city, MAX(id) id FROM anjuke_fetch_log GROUP BY city) x ON x.id=f.id''')]
        blocked = sum(1 for r in latest_logs if r['outcome'] == 'blocked')
        failed = sum(1 for r in latest_logs if r['outcome'] == 'parse_fail')
        by_city = {r['city']: r for r in rows}
        cards = []
        for city in TIER1:
            row = by_city.get(city)
            cards.append({
                'city': city, 'period': latest, 'avg_price': row['avg_price'] if row else None,
                'mom_pct': row['mom_pct'] if row else None, 'yoy_pct': row['yoy_pct'] if row else None,
                'data_status': DATA_STATUS if row else 'missing',
                'source_name': '安居客（非官方口径）', 'source_url': row['source_url'] if row else None,
            })
        cov = dict(conn.execute('''SELECT COUNT(DISTINCT city) cities, COUNT(DISTINCT period) periods,
            COUNT(*) records, MIN(period) earliest, MAX(period) latest FROM anjuke_city_listings''').fetchone())
    warnings = []
    if blocked:
        names = '、'.join(r['city'] for r in latest_logs if r['outcome'] == 'blocked')
        warnings.append(f'各城市最近一次记录中 {blocked} 个触发访问验证（{names}），已跳过且未绕过。')
    if failed:
        names = '、'.join(r['city'] for r in latest_logs if r['outcome'] == 'parse_fail')
        warnings.append(f'各城市最近一次记录中 {failed} 个正常返回但无可用字段或解析失败（{names}）；旧数据未清除。')
    if not latest:
        warnings.append('尚无可用挂牌数据；官方 70 城模块不受影响。')
    return {
        'data_status': DATA_STATUS if latest else 'missing', 'latest_period': latest,
        'cards': cards, 'city_table': rows,
        'coverage': {**cov, 'mapped_cities': len(ANJUKE_CITY_SLUGS),
                     'extra_mapped_cities': len(ANJUKE_EXTRA_CITY_SLUGS)},
        'warnings': warnings,
        'notes': ['挂牌价是卖方要价，不是成交价；安居客为商业平台，属于非官方参考口径。',
                  '原始 HTML 与独立 SQLite 仅保存在本机，不进入公开仓库或主库快照。'],
    }
