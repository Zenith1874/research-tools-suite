# -*- coding: utf-8 -*-
"""中国房价模块：
1) 国家统计局"70个大中城市商品住宅销售价格变动情况"月报(官方,城市级,新房+二手,指数)
   - 注意:统计局 data.stats.gov.cn API 对境外 IP 403,但 www.stats.gov.cn 新闻发布页可访问,
     故走月报正文表格解析(与 MOF/PBOC 爬虫同模式)。
2) BIS 中国住宅价格指数(经 FRED 免 key CSV,2005 起季度,全国口径,长趋势)。

数据纪律:逐条 official + månedsreport原文/FRED 系列页 source_url;上涨/下跌城市数等
统计为 derived+formula;解析失败只记日志不清旧数据;不用商业挂牌价(非成交口径)。
"""
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from bs4 import BeautifulSoup

NBS_SOURCE = '国家统计局'
SOURCE_TYPE = 'nbs_70city_housing'
NBS_LIST_URL = 'https://www.stats.gov.cn/sj/zxfb/'
NBS_SEARCH_API = 'https://api.so-gov.cn/query/s'
NBS_SEARCH_SITE_CODE = 'bm36000002'
NBS_HISTORY_QUERY = '70个大中城市住宅销售价格变动情况'
FRED_SERIES = [
    ('QCNR628BIS', 'BIS 中国实际住宅价格指数(2010=100)', 'real'),
    ('QCNN628BIS', 'BIS 中国名义住宅价格指数(2010=100)', 'nominal'),
]
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
HTTP_TIMEOUT = 25

TIER1 = ['北京', '上海', '广州', '深圳']

INDICATORS = {
    'new_home_mom_idx': '新建商品住宅价格指数(环比,上月=100)',
    'new_home_yoy_idx': '新建商品住宅价格指数(同比,上年同月=100)',
    'second_home_mom_idx': '二手住宅价格指数(环比,上月=100)',
    'second_home_yoy_idx': '二手住宅价格指数(同比,上年同月=100)',
}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_housing_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS housing_city_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT, period TEXT, indicator_code TEXT, value REAL,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, updated_at TEXT,
        UNIQUE(city, period, indicator_code)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS housing_national_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, period TEXT, value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_url TEXT, parser_notes TEXT, updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_housing_city_period ON housing_city_observations(period, indicator_code)')
    conn.commit()


# ── 解析(可单测) ──────────────────────────────────────────────────────────────
def _norm_city(s):
    normalized = re.sub(r'[\s　]', '', s or '')
    return re.sub(r'[*＊#＃]+$', '', normalized)


def parse_period_from_title(title):
    m = re.search(r'(20\d{2})年(\d{1,2})月份?70个大中城市', title or '')
    return f'{m.group(1)}-{int(m.group(2)):02d}' if m else None


def _is_num(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def parse_dual_column_table(table):
    """70城主表:每行两组 [城市,环比,同比,(均值)]。
    扫描式解析:在单元格序列里找 [城市名, 数, 数] 模式——对不同期数的
    空单元格/错位(如 2026-01 版式)免疫,不依赖固定步长。"""
    out = {}
    for tr in table.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
        i = 0
        while i < len(cells) - 2:
            city = _norm_city(cells[i])
            if (re.match(r'^[一-龥]{2,6}$', city) and city != '城市'
                    and _is_num(cells[i + 1]) and _is_num(cells[i + 2])):
                out[city] = (float(cells[i + 1]), float(cells[i + 2]))
                i += 3
            else:
                i += 1
    return out


def parse_70city_article(html):
    """月报正文 → {'new': {city:(mom,yoy)}, 'second': {...}}。
    两种官方版式自适应:
      A) 表0=新建(70城双列)、表1=二手(70城双列)——常见版式;
      B) 70城拆成两张 35 城表:表0+表1=新建、表2+表3=二手(如 2026-01 期)。
    识别依据:若表0与表1城市集合不相交(各~35城),则为版式B合并。"""
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if len(tables) < 2:
        raise ValueError(f'70城月报表格数异常: {len(tables)}')

    # 2011 年旧版同页包含“新建住宅 / 新建商品住宅 / 二手住宅”三张主表，
    # 且桌面/移动版重复；必须按表题选主表，不能把第 2 张新房表误当二手表。
    labelled = {'new': [], 'second': []}
    for table in tables:
        heading_rows = table.find_all('tr')[:3]
        # Some releases (notably 2018-01/02) put the table caption in the
        # paragraph immediately before a wrapping <div>, rather than in the
        # table itself. Include that nearby context before classifying tables.
        heading_parts = [row.get_text(' ', strip=True) for row in heading_rows]
        for node in (table, table.parent):
            previous = node.find_previous_sibling() if node else None
            if previous is not None:
                heading_parts.insert(0, previous.get_text(' ', strip=True))
        heading = re.sub(r'[\s　]', '', ' '.join(heading_parts))
        if '分类指数' in heading:
            continue
        parsed_table = parse_dual_column_table(table)
        if len(parsed_table) < 30:
            continue
        if '二手住宅价格指数' in heading or '二手住宅销售价格指数' in heading:
            labelled['second'].append(parsed_table)
        elif ('新建商品住宅价格指数' in heading
              or '新建商品住宅销售价格指数' in heading):
            labelled['new'].append(parsed_table)

    def merge_labelled(parts):
        merged = {}
        for part in parts:
            merged.update(part)
        return merged

    labelled_new = merge_labelled(labelled['new'])
    labelled_second = merge_labelled(labelled['second'])
    if len(labelled_new) == 70 and len(labelled_second) == 70:
        return {'new': labelled_new, 'second': labelled_second}

    # 无可用表题时保留原版式兼容逻辑（含 35+35 拆表）。
    parsed = [parse_dual_column_table(t) for t in tables[:4]]
    t0, t1 = parsed[0], parsed[1]
    if len(t0) >= 60:                                    # 版式A
        new, second = t0, t1
    elif (len(t0) >= 30 and len(t1) >= 30 and not (set(t0) & set(t1))
          and len(parsed) >= 4):                          # 版式B:两半合并
        new = {**t0, **t1}
        second = {**parsed[2], **parsed[3]}
    else:
        raise ValueError(f'70城版式无法识别: 表城市数 {[len(x) for x in parsed]}')
    if len(new) != 70 or len(second) != 70:
        raise ValueError(f'70城解析城市数异常: 新房{len(new)} 二手{len(second)}')
    return {'new': new, 'second': second}


def _release_path_rank(url):
    if '/sj/zxfb/' in url:
        return 0
    if '/sj/zxfbhjd/' in url:
        return 1
    if '/xxgk/sjfb/' in url:
        return 2
    return 9


def extract_70city_search_releases(payload, start_year=2011, end_year=None):
    """从国家统计局官网所用站内搜索 JSON 中提取严格匹配的月报链接。"""
    end_year = int(end_year or datetime.now().year)
    pattern = re.compile(
        r'^(20\d{2})年(\d{1,2})月份?70个大中城市'
        r'(?:及\d{1,2}月(?:上|下)半月一线和热点二线城市)?'
        r'(?:商品)?住宅销售价格变动情况$')
    by_period = {}
    for doc in (payload or {}).get('resultDocs') or []:
        data = doc.get('data') or {}
        title = re.sub(r'<[^>]+>', '', data.get('titleO') or data.get('title') or '').strip()
        url = (data.get('url') or '').strip()
        match = pattern.fullmatch(title)
        if not match or not url.startswith('https://www.stats.gov.cn/'):
            continue
        year, month = int(match.group(1)), int(match.group(2))
        if not start_year <= year <= end_year or not 1 <= month <= 12:
            continue
        period = f'{year}-{month:02d}'
        candidate = (url, title)
        current = by_period.get(period)
        if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
            by_period[period] = candidate
    return [(period, *by_period[period]) for period in sorted(by_period, reverse=True)]


def discover_70city_history(start_year=2011, end_year=None, max_pages=30):
    """通过统计局官网内置政务搜索发现 2011 年以来的月报原文。"""
    end_year = int(end_year or datetime.now().year)
    found = {}
    headers = {**UA, 'Referer': 'https://www.stats.gov.cn/search/s'}
    for page in range(1, int(max_pages) + 1):
        response = requests.post(NBS_SEARCH_API, data={
            'siteCode': NBS_SEARCH_SITE_CODE,
            'qt': NBS_HISTORY_QUERY,
            'page': page,
            'pageSize': 20,
            'keyPlace': '1',
            'sort': 'dateDesc',
        }, headers=headers, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not payload.get('ok'):
            raise ValueError(f'统计局站内搜索失败: {payload.get("msg") or payload.get("code")}')
        for period, url, title in extract_70city_search_releases(
                payload, int(start_year), end_year):
            current = found.get(period)
            if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
                found[period] = (url, title)
        current_hits = int(payload.get('currentHits') or 0)
        total_hits = int(payload.get('totalHits') or 0)
        if not current_hits or page * 20 >= total_hits:
            break
        time.sleep(0.15)
    return [(url, title) for _, (url, title) in sorted(found.items(), reverse=True)]


def discover_70city_releases(max_pages=6):
    """最新发布列表(含 index_N.html 翻页) → [(url,title)],新在前,按 url 去重。"""
    seen, out = set(), []
    for i in range(max_pages):
        url = NBS_LIST_URL + ('index.html' if i == 0 else f'index_{i}.html')
        try:
            r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                break
            r.encoding = 'utf-8'
        except Exception:
            break
        links = re.findall(r'href="([^"]+)"[^>]*>([^<]*70个大中城市商品住宅销售价格[^<]*)<', r.text)
        for href, title in links:
            if href.startswith('./'):
                href = NBS_LIST_URL + href[2:]
            elif href.startswith('/'):
                href = 'https://www.stats.gov.cn' + href
            if href not in seen:
                seen.add(href)
                out.append((href, title.strip()))
        time.sleep(0.4)
    return out


def _fetch_70city_article(url):
    response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    response.encoding = 'utf-8'
    return parse_70city_article(response.text)


def _upsert_70city_release(conn, data, period, url, title, updated_at):
    upserted = 0
    for kind, code_mom, code_yoy in [
            ('new', 'new_home_mom_idx', 'new_home_yoy_idx'),
            ('second', 'second_home_mom_idx', 'second_home_yoy_idx')]:
        for city, (mom, yoy) in data[kind].items():
            for code, value in ((code_mom, mom), (code_yoy, yoy)):
                cur = conn.execute('''INSERT INTO housing_city_observations
                    (city,period,indicator_code,value,data_status,source_name,source_type,
                     source_url,source_title,parser_notes,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(city,period,indicator_code) DO UPDATE SET
                      value=excluded.value, source_url=excluded.source_url,
                      source_title=excluded.source_title, parser_notes=excluded.parser_notes,
                      updated_at=excluded.updated_at''',
                    (city, period, code, value, 'official', NBS_SOURCE, SOURCE_TYPE,
                     url, title, '解析自统计局70城月报正文；按表题识别新建商品住宅/二手住宅主表',
                     updated_at))
                upserted += cur.rowcount
    return upserted


def backfill_housing_city_history(db_path, start_year=2011, end_year=None,
                                  sleep_seconds=0.5, max_search_pages=30, workers=1):
    """一次性回填现行 70 城逐城指数；2010 旧制度不混入该表。"""
    started = datetime.now().isoformat()
    end_year = int(end_year or datetime.now().year)
    releases = discover_70city_history(start_year, end_year, max_search_pages)
    errors = []
    counters = {'records_upserted': 0, 'releases_ok': 0,
                'releases_skipped_complete': 0, 'releases_failed': 0}
    actual_coverage = (None, None)
    with connect(db_path) as conn:
        ensure_housing_tables(conn)
        pending = []
        for url, title in releases:
            period = parse_period_from_title(title)
            if not period:
                continue
            existing = conn.execute('''SELECT COUNT(*) FROM housing_city_observations
                WHERE period=?''', (period,)).fetchone()[0]
            if existing >= 280:
                counters['releases_skipped_complete'] += 1
                continue
            pending.append((period, url, title))

        def store_result(item, data=None, error=None):
            period, url, title = item
            if error is not None:
                counters['releases_failed'] += 1
                errors.append(f'{period} {title[:30]}: {error}')
                return
            now = datetime.now().isoformat()
            counters['records_upserted'] += _upsert_70city_release(
                conn, data, period, url, title, now)
            counters['releases_ok'] += 1
            conn.commit()

        workers = max(1, min(int(workers), 4))
        if workers == 1:
            for index, item in enumerate(pending):
                if index and sleep_seconds > 0:
                    time.sleep(float(sleep_seconds))
                try:
                    store_result(item, _fetch_70city_article(item[1]))
                except Exception as exc:
                    store_result(item, error=exc)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_fetch_70city_article, url): (period, url, title)
                    for period, url, title in pending
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    try:
                        store_result(item, future.result())
                    except Exception as exc:
                        store_result(item, error=exc)
        actual_coverage = conn.execute('''SELECT MIN(period), MAX(period)
            FROM housing_city_observations WHERE period BETWEEN ? AND ?''',
            (f'{int(start_year)}-01', f'{end_year}-12')).fetchone()
    return {
        'success': counters['releases_ok'] > 0 or counters['releases_skipped_complete'] > 0,
        **counters,
        'releases_found': len(releases),
        'coverage_start': actual_coverage[0],
        'coverage_end': actual_coverage[1],
        'errors': errors[:20],
        'started_at': started,
        'finished_at': datetime.now().isoformat(),
    }


# ── 更新 ──────────────────────────────────────────────────────────────────────
def update_housing_prices(db_path):
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    releases = discover_70city_releases()
    with connect(db_path) as conn:
        ensure_housing_tables(conn)
        now = datetime.now().isoformat()
        # 1) 统计局 70城(只抓库里没有的期数)
        for url, title in releases:
            period = parse_period_from_title(title)
            if not period:
                continue
            n = conn.execute('SELECT COUNT(*) FROM housing_city_observations WHERE period=?', (period,)).fetchone()[0]
            if n >= 280:      # 70城×4指标=280；不完整月份必须重抓
                continue
            try:
                data = _fetch_70city_article(url)
            except Exception as exc:
                errors.append(f'{title[:40]}: {exc}')
                continue
            upserted += _upsert_70city_release(conn, data, period, url, title, now)
            time.sleep(0.5)
        # 2) BIS 长指数(FRED 免 key,幂等全量)
        for fred_id, name, kind in FRED_SERIES:
            try:
                r = requests.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}',
                                 headers=UA, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                lines = r.text.strip().splitlines()[1:]
            except Exception as exc:
                errors.append(f'{fred_id}: {exc}')
                continue
            for line in lines:
                parts = line.split(',')
                if len(parts) < 2 or parts[1].strip() in ('', '.'):
                    continue
                cur = conn.execute('''INSERT INTO housing_national_observations
                    (indicator_code,period,value,unit,frequency,data_status,source_name,source_url,parser_notes,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(indicator_code,period) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at''',
                    (fred_id, parts[0].strip(), float(parts[1]), '指数(2010=100)', 'quarterly',
                     'official', 'BIS via FRED', f'https://fred.stlouisfed.org/series/{fred_id}',
                     name, now))
                upserted += cur.rowcount
        conn.commit()
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'releases_found': len(releases), 'errors': errors[:6]}


# ── payload ───────────────────────────────────────────────────────────────────
def build_housing_payload(db_path):
    with connect(db_path) as conn:
        ensure_housing_tables(conn)
        latest = conn.execute('SELECT MAX(period) FROM housing_city_observations').fetchone()[0]
        cards, breadth, table_rows, city_series = [], None, [], {}
        if latest:
            rows = [dict(r) for r in conn.execute(
                'SELECT * FROM housing_city_observations WHERE period=?', (latest,))]
            by_city = {}
            for r in rows:
                by_city.setdefault(r['city'], {'city': r['city'], 'source_url': r['source_url']})[r['indicator_code']] = r['value']
            src = rows[0] if rows else {}
            # 一线城市卡片
            for city in TIER1:
                d = by_city.get(city, {})
                cards.append({'label': f'{city} 新房环比', 'value': d.get('new_home_mom_idx'),
                              'unit': '上月=100', 'period': latest, 'data_status': 'official' if d else 'missing',
                              'source_name': NBS_SOURCE, 'source_url': d.get('source_url'),
                              'extra': {'新房同比': d.get('new_home_yoy_idx'),
                                        '二手环比': d.get('second_home_mom_idx'),
                                        '二手同比': d.get('second_home_yoy_idx')}})
            # 涨跌家数(derived)
            moms = [d.get('new_home_mom_idx') for d in by_city.values() if d.get('new_home_mom_idx') is not None]
            if moms:
                breadth = {'period': latest, 'data_status': 'derived',
                           'formula': 'count(city where new_home_mom_idx >/=/< 100)',
                           'up': sum(1 for v in moms if v > 100), 'flat': sum(1 for v in moms if v == 100),
                           'down': sum(1 for v in moms if v < 100), 'total': len(moms),
                           'source_url': src.get('source_url')}
            table_rows = sorted(by_city.values(), key=lambda x: -(x.get('new_home_yoy_idx') or 0))
        # 一线城市历史序列(新房同比,随月份累积)
        for city in TIER1:
            city_series[city] = [dict(r) for r in conn.execute(
                """SELECT period, value FROM housing_city_observations
                   WHERE city=? AND indicator_code='new_home_yoy_idx' ORDER BY period""", (city,))]
        national = {}
        for fred_id, name, kind in FRED_SERIES:
            national[fred_id] = [dict(r) for r in conn.execute(
                'SELECT period, value FROM housing_national_observations WHERE indicator_code=? ORDER BY period',
                (fred_id,))]
        cov_city = dict(conn.execute("""SELECT COUNT(DISTINCT period) periods, MIN(period) earliest, MAX(period) latest,
                                        COUNT(*) records FROM housing_city_observations""").fetchone())
        cov_nat = dict(conn.execute('SELECT COUNT(*) records, MIN(period) earliest, MAX(period) latest FROM housing_national_observations').fetchone())
    return {
        'data_status': 'official' if latest else 'missing',
        'latest_period': latest, 'cards': cards, 'breadth': breadth,
        'city_table': table_rows, 'city_series': city_series, 'national': national,
        'coverage': {'nbs_70city': cov_city, 'bis_national': cov_nat},
        'source_pages': {'nbs': NBS_LIST_URL, 'fred': 'https://fred.stlouisfed.org/series/QCNR628BIS'},
        'warnings': [] if latest else ['尚未抓取;未生成 mock。'],
        'notes': ['70城指数为官方口径:环比上月=100、同比上年同月=100(100 以下即下跌)。',
                  '数据取自统计局月报正文表格(境外 IP 无法访问其 data API,新闻页可访问)。',
                  '现行逐城可比序列从 2011 年开始；2010 年旧制度仅有旧口径资料，不与现行逐城序列拼接。',
                  '不采用商业平台挂牌价(非成交口径);BIS 指数用于 2005 年以来长趋势。'],
    }
