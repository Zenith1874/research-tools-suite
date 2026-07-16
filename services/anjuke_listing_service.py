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
from contextlib import closing
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from services.anjuke_city_map import (
    ANJUKE_CITY_SLUGS,
    ANJUKE_EXTRA_CITY_SLUGS,
    city_history_url,
    city_market_url,
    city_slug,
)

log = logging.getLogger(__name__)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(ROOT, 'data', 'housing_listing.db')
RAW_ROOT = os.path.join(ROOT, 'data', 'anjuke_raw')
DATA_STATUS = 'listing_reference'
YEARLY_DATA_STATUS = 'listing_year_snapshot'
RANKING_URL = 'https://www.anjuke.com/fangjia/'
PRICE_MIN = 2000
PRICE_MAX = 200000
MAX_REQUESTS = 100
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36')
BLOCK_MARKERS = ('访问验证', '请输入验证码', 'antibot/verifycode', '滑块验证')
TIER1 = ('北京', '上海', '广州', '深圳')
FOCUS_CITIES = ('北京', '上海', '广州', '深圳', '厦门', '南京', '合肥', '常州', '苏州', '无锡')


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
        outcome TEXT, fetched_at TEXT,
        fetch_scope TEXT DEFAULT 'current', period_hint TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS anjuke_city_yearly_rankings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT, year INTEGER, snapshot_period TEXT, avg_price REAL,
        source_change_pct REAL,
        data_status TEXT DEFAULT 'listing_year_snapshot',
        source_url TEXT, detail_url TEXT, fetched_at TEXT, raw_cached TEXT,
        UNIQUE(city, year)
    )''')
    log_columns = {row[1] for row in conn.execute('PRAGMA table_info(anjuke_fetch_log)')}
    if 'fetch_scope' not in log_columns:
        conn.execute("ALTER TABLE anjuke_fetch_log ADD COLUMN fetch_scope TEXT DEFAULT 'current'")
    if 'period_hint' not in log_columns:
        conn.execute('ALTER TABLE anjuke_fetch_log ADD COLUMN period_hint TEXT')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_anjuke_listing_period ON anjuke_city_listings(period, city)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_anjuke_yearly_year ON anjuke_city_yearly_rankings(year, city)')
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


def _as_float(value):
    if value is None:
        return None
    try:
        return float(str(value).replace('%', '').strip())
    except (TypeError, ValueError):
        return None


def parse_anjuke_year_page(html, source_url, expected_city, expected_year,
                           allow_small_fixture=False):
    """解析年度房价页的逐月二手房挂牌均价。

    年度页当前把 1--12 月记录放在 Nuxt ``yearAreaData.yearList`` 中；部分城市或
    早期年份虽有正常页面但价格为 ``-``。这种情况返回解析失败而不是写入 0。
    """
    raw = html.encode('utf-8') if isinstance(html, str) else html
    blocked = is_blocked_response(raw, source_url)
    if allow_small_fixture and len(raw) < 5000:
        decoded = raw.decode('utf-8', errors='ignore')
        blocked = any(marker in source_url + '\n' + decoded for marker in BLOCK_MARKERS)
    if blocked:
        raise PermissionError('blocked: 安居客访问验证页')
    text = raw.decode('utf-8', errors='replace')
    soup = BeautifulSoup(text, 'html.parser')
    page_title = soup.title.get_text(' ', strip=True) if soup.title else ''
    expected_year = int(expected_year)
    if expected_city not in page_title or str(expected_year) not in page_title:
        raise ValueError(
            f'年度页面城市/年份错配: expected={expected_city}/{expected_year} title={page_title[:80]}')

    script = _extract_nuxt_script(text)
    aliases = _nuxt_aliases(script)
    start = script.find('yearList:[')
    if start < 0:
        raise ValueError('年度页面缺少 yearList')
    end_match = re.search(r'\]\s*,\s*otherCitiesInSameProvince:', script[start:])
    if not end_match:
        raise ValueError('年度页面 yearList 边界异常')
    end = start + end_match.start()
    region = script[start:end]
    records = []
    item_pattern = re.compile(
        r'\{title:([^,{}]+),actionUrl:[^,{}]+,avgPrice:([^,{}]+),monthChange:([^,{}]+)\}')
    for match in item_pattern.finditer(region):
        title = str(_resolve(match.group(1), aliases) or '')
        title_match = re.fullmatch(r'(20\d{2})年(\d{1,2})月房价', title)
        if not title_match or int(title_match.group(1)) != expected_year:
            continue
        month = int(title_match.group(2))
        price = _as_float(_resolve(match.group(2), aliases))
        if price is None or not PRICE_MIN <= price <= PRICE_MAX:
            continue
        records.append({
            'city': expected_city,
            'period': f'{expected_year}-{month:02d}',
            'avg_price': price,
            'mom_pct': _as_float(_resolve(match.group(3), aliases)),
            'yoy_pct': None,
        })
    records.sort(key=lambda row: row['period'])
    if not records:
        raise ValueError(f'{expected_city}{expected_year}年度页面正常返回但逐月挂牌字段为空')
    return {
        'city': expected_city,
        'year': expected_year,
        'records': records,
        'history_points': len(records),
        'source_url': source_url,
    }


def parse_anjuke_ranking_page(html, source_url=RANKING_URL, fetched_at=None,
                               cities=None, allow_small_fixture=False):
    """解析全国历史页中的年度排名快照。

    该层与城市年度页的逐月 ``yearList`` 不同：历史年份的价格与同年 12 月
    城市页价格一致（允许页面舍入相差 1 元），当前年份代表抓取当月快照。
    因此返回独立的低频记录，不扩写为 12 个月。
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
    start = script.find('avgPriceData:[')
    if start < 0:
        raise ValueError('全国历史页缺少 avgPriceData')
    end = script.find(']}],fetch:', start)
    if end < 0:
        raise ValueError('全国历史页 avgPriceData 边界异常')
    selected = set(cities or FOCUS_CITIES)
    as_of = datetime.fromisoformat(fetched_at) if fetched_at else datetime.now()
    item_pattern = re.compile(
        r'\{title:([^,{}]+),actionUrl:([^,{}]+),avgPrice:([^,{}]+),monthChange:([^,{}]+)\}')
    records = []
    for match in item_pattern.finditer(script[start:end]):
        title = str(_resolve(match.group(1), aliases) or '')
        title_match = re.fullmatch(r'(20\d{2})年(.+?)房价', title)
        if not title_match:
            continue
        year, city = int(title_match.group(1)), title_match.group(2)
        if city not in selected or year > as_of.year:
            continue
        price = _as_float(_resolve(match.group(3), aliases))
        if price is None or not PRICE_MIN <= price <= PRICE_MAX:
            continue
        change = _as_float(_resolve(match.group(4), aliases))
        records.append({
            'city': city,
            'year': year,
            'snapshot_period': f'{year}-12' if year < as_of.year else f'{year}-{as_of.month:02d}',
            'avg_price': price,
            'source_change_pct': change,
            'data_status': YEARLY_DATA_STATUS,
            'source_url': source_url,
            'detail_url': str(_resolve(match.group(2), aliases) or ''),
        })
    records.sort(key=lambda row: (row['city'], row['year']))
    if not records:
        raise ValueError('全国历史页没有点名城市的年度排名记录')
    return {'records': records, 'history_points': len(records), 'source_url': source_url}


def _cache_path(city, period):
    rel = os.path.join('data', 'anjuke_raw', period, f'{city_slug(city)}.html')
    return rel, os.path.join(ROOT, rel)


def _history_cache_path(city, year):
    rel = os.path.join('data', 'anjuke_raw', 'history', city_slug(city), f'{int(year)}.html')
    return rel, os.path.join(ROOT, rel)


def _ranking_cache_candidates(cached_path=None):
    candidates = []
    if cached_path:
        candidates.append(os.path.abspath(cached_path))
    candidates.append(os.path.join(RAW_ROOT, 'yearly_rankings', 'index.html'))
    if os.path.isdir(RAW_ROOT):
        recon_dirs = sorted(
            (name for name in os.listdir(RAW_ROOT) if name.startswith('recon_')),
            reverse=True,
        )
        candidates.extend(os.path.join(RAW_ROOT, name, 'entry.html') for name in recon_dirs)
    return list(dict.fromkeys(candidates))


def _log_fetch(conn, city, url, status, size, outcome, fetched_at,
               fetch_scope='current', period_hint=None):
    conn.execute('''INSERT INTO anjuke_fetch_log
        (city,url,http_status,bytes,outcome,fetched_at,fetch_scope,period_hint)
        VALUES (?,?,?,?,?,?,?,?)''',
                 (city, url, status, size, outcome, fetched_at, fetch_scope, period_hint))


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
    with closing(connect(db_path)) as conn:
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


def _upsert_history_records(conn, city, records, source_url, fetched_at, raw_cached):
    upserted = 0
    for record in records:
        cur = conn.execute('''INSERT INTO anjuke_city_listings
            (city,period,avg_price,mom_pct,yoy_pct,data_status,source_url,fetched_at,raw_cached)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(city,period) DO UPDATE SET avg_price=excluded.avg_price,
              mom_pct=excluded.mom_pct,yoy_pct=COALESCE(excluded.yoy_pct,anjuke_city_listings.yoy_pct),
              data_status=excluded.data_status,source_url=excluded.source_url,
              fetched_at=excluded.fetched_at,raw_cached=excluded.raw_cached''',
            (city, record['period'], record['avg_price'], record.get('mom_pct'),
             record.get('yoy_pct'), DATA_STATUS, source_url, fetched_at, raw_cached))
        upserted += cur.rowcount
    return upserted


def _upsert_yearly_rankings(conn, records, fetched_at, raw_cached):
    upserted = 0
    for record in records:
        cur = conn.execute('''INSERT INTO anjuke_city_yearly_rankings
            (city,year,snapshot_period,avg_price,source_change_pct,data_status,
             source_url,detail_url,fetched_at,raw_cached)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(city,year) DO UPDATE SET
              snapshot_period=excluded.snapshot_period,
              avg_price=excluded.avg_price,
              source_change_pct=excluded.source_change_pct,
              data_status=excluded.data_status,
              source_url=excluded.source_url,
              detail_url=excluded.detail_url,
              fetched_at=excluded.fetched_at,
              raw_cached=excluded.raw_cached''',
            (record['city'], record['year'], record['snapshot_period'], record['avg_price'],
             record.get('source_change_pct'), YEARLY_DATA_STATUS, record['source_url'],
             record.get('detail_url'), fetched_at, raw_cached))
        upserted += cur.rowcount
    return upserted


def update_anjuke_yearly_rankings(db_path=None, cached_path=None, allow_network=True):
    """更新全国历史页年度排名快照；最多一次网络请求，验证页立即停止。"""
    fetched_at = None
    raw_cached = None
    content = None
    from_cache = False
    for candidate in _ranking_cache_candidates(cached_path):
        if os.path.exists(candidate):
            with open(candidate, 'rb') as fh:
                content = fh.read()
            fetched_at = datetime.fromtimestamp(os.path.getmtime(candidate)).isoformat()
            raw_cached = os.path.relpath(candidate, ROOT)
            from_cache = True
            break

    status = 200 if content is not None else None
    final_url = RANKING_URL
    if content is None:
        if not allow_network:
            return {'success': False, 'records_upserted': 0, 'from_cache': False,
                    'blocked': False, 'error': '没有年度排名缓存且网络读取被禁用'}
        session = requests.Session()
        session.headers.update({
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
            'Referer': RANKING_URL,
        })
        try:
            response = session.get(RANKING_URL, timeout=25, allow_redirects=True)
            status = response.status_code
            final_url = response.url
            content = response.content
            fetched_at = datetime.now().isoformat()
        except requests.RequestException as exc:
            return {'success': False, 'records_upserted': 0, 'from_cache': False,
                    'blocked': False, 'error': str(exc)}
        if is_blocked_response(content, final_url):
            with closing(connect(db_path)) as conn:
                ensure_tables(conn)
                _log_fetch(conn, '全国年度排名', RANKING_URL, status, len(content), 'blocked',
                           fetched_at, 'yearly_ranking', None)
                conn.commit()
            return {'success': False, 'records_upserted': 0, 'from_cache': False,
                    'blocked': True, 'error': '全国历史页触发访问验证，已停止且未绕过'}
        cache_abs = os.path.join(RAW_ROOT, 'yearly_rankings', 'index.html')
        os.makedirs(os.path.dirname(cache_abs), exist_ok=True)
        with open(cache_abs, 'wb') as fh:
            fh.write(content)
        raw_cached = os.path.relpath(cache_abs, ROOT)

    try:
        parsed = parse_anjuke_ranking_page(content, RANKING_URL, fetched_at, FOCUS_CITIES)
    except Exception as exc:
        with closing(connect(db_path)) as conn:
            ensure_tables(conn)
            _log_fetch(conn, '全国年度排名', RANKING_URL, status, len(content or b''),
                       'parse_fail', fetched_at or datetime.now().isoformat(),
                       'yearly_ranking', None)
            conn.commit()
        return {'success': False, 'records_upserted': 0, 'from_cache': from_cache,
                'blocked': isinstance(exc, PermissionError), 'error': str(exc)}

    with closing(connect(db_path)) as conn:
        ensure_tables(conn)
        upserted = _upsert_yearly_rankings(conn, parsed['records'], fetched_at, raw_cached)
        _log_fetch(conn, '全国年度排名', RANKING_URL, status, len(content), 'success', fetched_at,
                   'yearly_ranking', f"{min(r['year'] for r in parsed['records'])}-"
                                     f"{max(r['year'] for r in parsed['records'])}")
        conn.commit()
    return {
        'success': True,
        'records_upserted': upserted,
        'ranking_points': parsed['history_points'],
        'cities': sorted({row['city'] for row in parsed['records']}),
        'from_cache': from_cache,
        'raw_cached': raw_cached,
        'blocked': False,
        'fetched_at': fetched_at,
    }


def _recompute_city_changes(conn, cities):
    """按完整月度价格序列重算环比/同比，跨年度连接 12 月与 1 月。"""
    updates = []
    for city in cities:
        rows = conn.execute('''SELECT period, avg_price FROM anjuke_city_listings
            WHERE city=? ORDER BY period''', (city,)).fetchall()
        prices = {row['period']: row['avg_price'] for row in rows}
        for period, price in prices.items():
            year, month = (int(x) for x in period.split('-'))
            previous_month = f'{year - 1}-12' if month == 1 else f'{year}-{month - 1:02d}'
            previous_year = f'{year - 1}-{month:02d}'
            updates.append((_pct(price, prices.get(previous_month)),
                            _pct(price, prices.get(previous_year)), city, period))
    conn.executemany('''UPDATE anjuke_city_listings SET mom_pct=?, yoy_pct=?
        WHERE city=? AND period=?''', updates)
    return len(updates)


def update_anjuke_history(db_path=None, cities=None, start_year=2010, end_year=None,
                          sleep_range=(2.0, 4.0), max_requests=MAX_REQUESTS):
    """分批回填年度页历史；单次网络请求硬上限默认 100。

    已在数据库中完整覆盖的城市-年份直接跳过；已缓存的正常 HTML 只解析不联网。
    验证页不缓存、不重试；网络错误或 5xx 最多重试两次。
    """
    selected = list(cities or FOCUS_CITIES)
    now_dt = datetime.now()
    end_year = min(int(end_year or now_dt.year), now_dt.year)
    start_year = int(start_year)
    if start_year > end_year:
        raise ValueError('start_year 不能晚于 end_year')
    if not 1 <= int(max_requests) <= MAX_REQUESTS:
        raise ValueError(f'max_requests 必须在 1--{MAX_REQUESTS} 之间')

    session = requests.Session()
    session.headers.update({
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.7',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.anjuke.com/fangjia/',
    })
    counters = {
        'pages_ok': 0, 'pages_cached': 0, 'pages_skipped_complete': 0,
        'pages_empty': 0, 'pages_blocked': 0, 'pages_failed': 0,
        'records_upserted': 0, 'requests': 0,
    }
    errors = []
    tasks = [(year, city) for year in range(start_year, end_year + 1) for city in selected]
    processed = 0
    network_pages = 0
    limit_reached = False
    with closing(connect(db_path)) as conn:
        ensure_tables(conn)
        for year, city in tasks:
            expected_months = 12 if year < now_dt.year else now_dt.month
            existing = conn.execute('''SELECT COUNT(DISTINCT period) FROM anjuke_city_listings
                WHERE city=? AND period BETWEEN ? AND ?''',
                (city, f'{year}-01', f'{year}-12')).fetchone()[0]
            if existing >= expected_months:
                counters['pages_skipped_complete'] += 1
                processed += 1
                continue
            url = city_history_url(city, year)
            if not url:
                counters['pages_failed'] += 1
                errors.append(f'{city}{year}: 无年度 URL 映射')
                processed += 1
                continue
            fetched_at = datetime.now().isoformat()
            rel_path, abs_path = _history_cache_path(city, year)
            content = None
            status = None
            final_url = url
            from_cache = os.path.exists(abs_path)
            if from_cache:
                counters['pages_cached'] += 1
                with open(abs_path, 'rb') as fh:
                    content = fh.read()
                fetched_at = datetime.fromtimestamp(os.path.getmtime(abs_path)).isoformat()
                status = 200
            else:
                if counters['requests'] >= max_requests:
                    limit_reached = True
                    break
                if network_pages and sleep_range[1] > 0:
                    time.sleep(random.uniform(*sleep_range))
                response = None
                last_error = None
                for attempt in range(3):
                    if counters['requests'] >= max_requests:
                        limit_reached = True
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
                network_pages += 1
                if response is None or response.status_code >= 500:
                    counters['pages_failed'] += 1
                    status = response.status_code if response is not None else None
                    size = len(response.content) if response is not None else 0
                    _log_fetch(conn, city, url, status, size, 'http_fail', fetched_at,
                               'history', str(year))
                    errors.append(f'{city}{year}: {last_error}')
                    conn.commit()
                    processed += 1
                    if limit_reached:
                        break
                    continue
                content = response.content
                status = response.status_code
                final_url = response.url

            if is_blocked_response(content, final_url):
                counters['pages_blocked'] += 1
                _log_fetch(conn, city, url, status, len(content), 'blocked', fetched_at,
                           'history', str(year))
                conn.commit()
                processed += 1
                continue

            if not from_cache:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, 'wb') as fh:
                    fh.write(content)
            try:
                parsed = parse_anjuke_year_page(content, url, city, year)
                counters['records_upserted'] += _upsert_history_records(
                    conn, city, parsed['records'], url, fetched_at, rel_path)
                counters['pages_ok'] += 1
                _log_fetch(conn, city, url, status, len(content), 'success', fetched_at,
                           'history', str(year))
            except PermissionError:
                counters['pages_blocked'] += 1
                _log_fetch(conn, city, url, status, len(content), 'blocked', fetched_at,
                           'history', str(year))
            except Exception as exc:
                counters['pages_empty'] += 1
                _log_fetch(conn, city, url, status, len(content), 'history_empty', fetched_at,
                           'history', str(year))
                errors.append(f'{city}{year}: {exc}')
            conn.commit()
            processed += 1

        recalculated = _recompute_city_changes(conn, selected)
        conn.commit()
    return {
        'success': any(counters[key] for key in ('pages_ok', 'pages_cached', 'pages_skipped_complete')),
        **counters,
        'changes_recalculated': recalculated,
        'tasks_total': len(tasks),
        'tasks_processed': processed,
        'tasks_remaining': max(0, len(tasks) - processed),
        'request_limit_reached': limit_reached,
        'start_year': start_year,
        'end_year': end_year,
        'cities': selected,
        'errors': errors[:20],
        'finished_at': datetime.now().isoformat(),
    }


def build_anjuke_payload(db_path=None):
    with closing(connect(db_path)) as conn:
        ensure_tables(conn)
        latest = conn.execute('SELECT MAX(period) FROM anjuke_city_listings').fetchone()[0]
        rows = [] if not latest else [dict(r) for r in conn.execute(
            'SELECT * FROM anjuke_city_listings WHERE period=? ORDER BY city', (latest,))]
        history_rows = [dict(r) for r in conn.execute('''SELECT city, period, avg_price, mom_pct, yoy_pct,
            data_status, source_url FROM anjuke_city_listings ORDER BY city, period''')]
        yearly_rank_rows = [dict(r) for r in conn.execute('''SELECT city, year, snapshot_period,
            avg_price, source_change_pct, data_status, source_url, detail_url, fetched_at, raw_cached
            FROM anjuke_city_yearly_rankings ORDER BY city, year''')]
        latest_logs = [dict(r) for r in conn.execute('''SELECT f.* FROM anjuke_fetch_log f JOIN
            (SELECT city, MAX(id) id FROM anjuke_fetch_log
             WHERE COALESCE(fetch_scope,'current')='current' GROUP BY city) x ON x.id=f.id''')]
        blocked = sum(1 for r in latest_logs if r['outcome'] == 'blocked')
        failed = sum(1 for r in latest_logs if r['outcome'] == 'parse_fail')
        cov = dict(conn.execute('''SELECT COUNT(DISTINCT city) cities, COUNT(DISTINCT period) periods,
            COUNT(*) records, MIN(period) earliest, MAX(period) latest FROM anjuke_city_listings''').fetchone())
        coverage_by_city = [dict(r) for r in conn.execute('''SELECT city, COUNT(*) records,
            COUNT(DISTINCT SUBSTR(period,1,4)) years, MIN(period) earliest, MAX(period) latest,
            SUM(CASE WHEN yoy_pct IS NOT NULL THEN 1 ELSE 0 END) yoy_points
            FROM anjuke_city_listings GROUP BY city ORDER BY city''')]
    city_history = {}
    for row in history_rows:
        city_history.setdefault(row['city'], []).append(row)

    # 年度低频层：先由城市逐月页取当年最后一个有效月，再以全国历史排名页的
    # 原始快照覆盖同一城市-年份。两种来源均只保留一个年度点，不扩写成月度数据。
    yearly_index = {}
    for row in history_rows:
        if row['city'] not in FOCUS_CITIES:
            continue
        year = int(row['period'][:4])
        key = (row['city'], year)
        current = yearly_index.get(key)
        if current is None or row['period'] > current['period']:
            yearly_index[key] = {
                'city': row['city'],
                'year': year,
                'period': row['period'],
                'avg_price': row['avg_price'],
                'source_change_pct': None,
                'data_status': 'listing_year_end_from_monthly',
                'source_grain': 'monthly_year_end',
                'source_url': row['source_url'],
                'detail_url': row['source_url'],
            }
    for row in yearly_rank_rows:
        if row['city'] not in FOCUS_CITIES:
            continue
        yearly_index[(row['city'], int(row['year']))] = {
            'city': row['city'],
            'year': int(row['year']),
            'period': row['snapshot_period'],
            'avg_price': row['avg_price'],
            'source_change_pct': row['source_change_pct'],
            'data_status': row['data_status'],
            'source_grain': 'ranking_page_snapshot',
            'source_url': row['source_url'],
            'detail_url': row['detail_url'],
        }
    yearly_history_by_city = {city: [] for city in FOCUS_CITIES}
    for row in sorted(yearly_index.values(), key=lambda item: (item['city'], item['year'])):
        yearly_history_by_city[row['city']].append(row)
    yearly_coverage_by_city = []
    for city in FOCUS_CITIES:
        annual_rows = yearly_history_by_city[city]
        yearly_coverage_by_city.append({
            'city': city,
            'records': len(annual_rows),
            'earliest_year': annual_rows[0]['year'] if annual_rows else None,
            'latest_year': annual_rows[-1]['year'] if annual_rows else None,
            'ranking_points': sum(
                row['source_grain'] == 'ranking_page_snapshot' for row in annual_rows),
        })

    by_city = {r['city']: r for r in rows}
    cards = []
    for city in FOCUS_CITIES:
        row = by_city.get(city)
        annual_row = yearly_history_by_city.get(city, [])[-1] \
            if yearly_history_by_city.get(city) else None
        cards.append({
            'city': city,
            'period': row['period'] if row else (annual_row['period'] if annual_row else None),
            'avg_price': row['avg_price'] if row else (annual_row['avg_price'] if annual_row else None),
            'mom_pct': row['mom_pct'] if row else None,
            'yoy_pct': row['yoy_pct'] if row else None,
            'data_status': DATA_STATUS if row else (
                annual_row['data_status'] if annual_row else 'missing'),
            'source_grain': 'monthly' if row else (
                annual_row['source_grain'] if annual_row else None),
            'source_name': '安居客（非官方口径）',
            'source_url': row['source_url'] if row else (
                annual_row['detail_url'] or annual_row['source_url'] if annual_row else None),
        })
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
        'history_cities': sorted(city_history),
        'city_history': city_history,
        'coverage_by_city': coverage_by_city,
        'yearly_history_cities': [
            city for city in FOCUS_CITIES if yearly_history_by_city[city]],
        'yearly_history_by_city': yearly_history_by_city,
        'yearly_coverage_by_city': yearly_coverage_by_city,
        'coverage': {**cov, 'mapped_cities': len(ANJUKE_CITY_SLUGS),
                     'extra_mapped_cities': len(ANJUKE_EXTRA_CITY_SLUGS)},
        'warnings': warnings,
        'notes': ['挂牌价是卖方要价，不是成交价；安居客为商业平台，属于非官方参考口径。',
                  '全国历史排名页形成独立年度快照层：历史年份对应年末，当前年份对应抓取月；不扩写成 12 个月。',
                  '逐月层从 2010 年开始逐城侦察；正常页面中的空价格保持 missing，不补零。',
                  '年度快照不进入挂牌同比－官方二手同比的月度双口径计算。',
                  '原始 HTML 与独立 SQLite 仅保存在本机，不进入公开仓库或主库快照。'],
    }
