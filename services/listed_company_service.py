# -*- coding: utf-8 -*-
"""城市上市公司聚合：家数、市值与财务总量。

两套来源分开标注，绝不混为一谈：
  官方   巨潮资讯网（中国证监会指定信息披露平台）——公司概况、注册地/办公地、
         营业收入、净利润、净资产、股本。
  第三方 东方财富——总市值、总资产、总负债。巨潮公开接口不提供这三项，
         其完整数据 API 需要授权 token，本项目不绕过。

城市归属存双口径：注册地与办公地。两者常常不同（茅台注册仁怀、格力注册珠海，
更极端的是为税收优惠注册在霍尔果斯/西藏而总部在北上深），只用注册地会系统性
扭曲城市产业实力，因此都存下来由使用方选择。

营业收入与净利润两边都有，正好互为校验；差异超过容差的记入 data_source_conflicts。
"""
import re
import sqlite3
import time
from datetime import datetime

import requests

CNINFO_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Referer': 'http://www.cninfo.com.cn/',
    'Accept': 'application/json, text/plain, */*',
}
EASTMONEY_HEADERS = {
    'User-Agent': CNINFO_HEADERS['User-Agent'],
    'Referer': 'https://emweb.securities.eastmoney.com/',
    'Accept': 'application/json, text/plain, */*',
}

CNINFO_STOCK_LIST = 'http://www.cninfo.com.cn/new/data/szse_stock.json'
CNINFO_PROFILE = 'http://www.cninfo.com.cn/data20/companyOverview/getCompanyIntroduction'
CNINFO_HEADSTRIP = 'http://www.cninfo.com.cn/data20/companyOverview/getHeadStripData'
EASTMONEY_QUOTE = 'https://push2.eastmoney.com/api/qt/clist/get'
EASTMONEY_BALANCE_DATES = ('https://emweb.securities.eastmoney.com/PC_HSF10/'
                           'NewFinanceAnalysis/zcfzbDateAjaxNew')
EASTMONEY_BALANCE = ('https://emweb.securities.eastmoney.com/PC_HSF10/'
                     'NewFinanceAnalysis/zcfzbAjaxNew')

SOURCE_CNINFO = '巨潮资讯网（证监会指定披露平台）'
SOURCE_EASTMONEY = '东方财富（商业数据商）'

# 巨潮公司概况字段代号，来自接口原始返回；含义已用已知公司核对。
FIELD_REGISTER_ADDRESS = 'F004V'
FIELD_OFFICE_ADDRESS = 'F005V'
FIELD_INDUSTRY = 'F032V'
FIELD_LISTED_DATE = 'F006D'
# 头部数据字段代号：以平安银行、招商银行、农业银行三家实际披露值反推核对。
HEADSTRIP_FIELDS = {
    'revenue': 'F089N',
    'net_profit': 'F102N',
    'net_assets': 'F109N',
    'total_shares': 'F020N',
    'float_shares': 'F021N',
}

INDICATOR_UNITS = {
    'revenue': '元', 'net_profit': '元', 'net_assets': '元',
    'total_assets': '元', 'total_liabilities': '元', 'market_cap': '元',
    'float_market_cap': '元', 'total_shares': '股', 'float_shares': '股',
}
INDICATOR_NAMES = {
    'revenue': '营业收入', 'net_profit': '净利润', 'net_assets': '净资产',
    'total_assets': '总资产', 'total_liabilities': '总负债',
    'market_cap': '总市值', 'float_market_cap': '流通市值',
    'total_shares': '总股本', 'float_shares': '流通股本',
}

REQUEST_PACING = 0.35
RETRIES = 3
RETRY_BACKOFF = 4.0
CROSS_CHECK_TOLERANCE = 0.01

# 直辖市地址写作"北京市东城区…"，没有更下一级的市名；其余按"XX市"取。
MUNICIPALITIES = ('北京', '上海', '天津', '重庆')
# 省级前缀必须先剥掉再取市名，否则"内蒙古自治区呼和浩特市"会被截成"治区呼和浩特"。
_PROVINCE_PREFIX = re.compile(r'^([一-龥]{2,8}?)(省|自治区|特别行政区)')
# 省与市之间可能还夹一级：伊犁州、恩施州、阿坝藏族羌族自治州、兴安盟、阿里地区。
_SUB_PROVINCE_PREFIX = re.compile(r'^[一-龥]{2,12}?(?:自治州|州|盟|地区)')
_CITY_PATTERN = re.compile(r'^([一-龥]{2,6}?)市')
# 民族自治区全称过长，统一成通用简称，便于与统计局地区名对齐。
PROVINCE_ALIASES = {
    '新疆维吾尔': '新疆', '广西壮族': '广西', '宁夏回族': '宁夏',
    '西藏': '西藏', '内蒙古': '内蒙古',
}


def _normalise(address):
    return re.sub(r'\s+', '', str(address or ''))


def parse_province(address):
    text = _normalise(address)
    if not text:
        return None
    for name in MUNICIPALITIES:
        if text.startswith(name):
            return name
    match = _PROVINCE_PREFIX.match(text)
    if not match:
        return None
    return PROVINCE_ALIASES.get(match.group(1), match.group(1))


def parse_city(address):
    """从地址串解析城市；解析不出返回 None，绝不猜。

    先剥省级前缀，再剥州/盟/地区这一级，最后才取"XX市"。
    """
    text = _normalise(address)
    if not text:
        return None
    for name in MUNICIPALITIES:
        if text.startswith(name):
            return name
    remainder = _PROVINCE_PREFIX.sub('', text, count=1)
    # 州/盟/地区这一级必须先剥：否则"恩施州利川市"会被整段当成市名。
    prefecture = _SUB_PROVINCE_PREFIX.match(remainder)
    if prefecture:
        rest = remainder[prefecture.end():]
        match = _CITY_PATTERN.match(rest)
        if match:
            return match.group(1)
        # 州内是县而非市（如阿坝州汶川县），地级单位就是这个州本身
        return re.sub(r'(?:自治州|州|盟|地区)$', '',
                      re.sub(r'(?:藏族|羌族|彝族|苗族|回族|壮族|傣族|白族|哈尼族|傈僳族|'
                             r'蒙古族|朝鲜族|土家族|布依族|侗族|哈萨克族|柯尔克孜族|'
                             r'蒙古|维吾尔|自治)', '', prefecture.group(0))) or None
    match = _CITY_PATTERN.match(remainder)
    if match:
        return match.group(1)
    # 仍匹配不到就放弃，不猜
    return None


def ensure_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS listed_companies (
      code TEXT PRIMARY KEY, name TEXT, org_id TEXT, category TEXT,
      register_address TEXT, office_address TEXT,
      register_city TEXT, register_province TEXT,
      office_city TEXT, office_province TEXT,
      industry TEXT, listed_date TEXT,
      data_status TEXT NOT NULL, source_name TEXT NOT NULL, source_url TEXT,
      parser_notes TEXT, updated_at TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS listed_company_observations (
      id INTEGER PRIMARY KEY, code TEXT NOT NULL, name TEXT,
      indicator_code TEXT NOT NULL, period TEXT NOT NULL, value REAL NOT NULL,
      unit TEXT NOT NULL, data_status TEXT NOT NULL, source_name TEXT NOT NULL,
      source_url TEXT, parser_notes TEXT, updated_at TEXT NOT NULL,
      UNIQUE(code, indicator_code, period, source_name))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_listed_obs_lookup
                    ON listed_company_observations(indicator_code, period)''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_listed_companies_city
                    ON listed_companies(office_city, register_city)''')
    conn.commit()


def _connect(db_path):
    """写连接统一入口：WAL + 长 busy_timeout。

    抓取进程与常驻服务器同时写同一个库，WAL 下写者互斥；早先未显式设 WAL 且
    事务跨 200 条太长，撞上服务器的写入就会 database is locked。
    """
    conn = sqlite3.connect(db_path, timeout=120)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=120000')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def _get_json(url, params=None, headers=None, timeout=30):
    """限速 + 退避；返回非 JSON（多为反爬拦截页）时重试而不是当成空数据。"""
    last = None
    for attempt in range(RETRIES):
        time.sleep(REQUEST_PACING)
        try:
            response = requests.get(url, params=params,
                                    headers=headers or CNINFO_HEADERS, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
    raise RuntimeError(f'{url}: {last}')


def fetch_stock_list():
    payload = _get_json(CNINFO_STOCK_LIST)
    rows = payload.get('stockList') or []
    return [{'code': item['code'], 'name': item.get('zwjc'),
             'org_id': item.get('orgId'), 'category': item.get('category')}
            for item in rows if item.get('code')]


def fetch_profile(code):
    payload = _get_json(CNINFO_PROFILE, {'scode': code})
    records = ((payload.get('data') or {}).get('records') or [])
    if not records:
        return None
    basic = (records[0].get('basicInformation') or [{}])[0]
    register = basic.get(FIELD_REGISTER_ADDRESS)
    office = basic.get(FIELD_OFFICE_ADDRESS)
    return {
        'register_address': register, 'office_address': office,
        'register_city': parse_city(register), 'register_province': parse_province(register),
        'office_city': parse_city(office) or parse_city(register),
        'office_province': parse_province(office) or parse_province(register),
        'industry': basic.get(FIELD_INDUSTRY),
        'listed_date': str(basic.get(FIELD_LISTED_DATE) or '')[:10] or None,
    }


def fetch_headstrip(code):
    payload = _get_json(CNINFO_HEADSTRIP, {'scode': code})
    records = ((payload.get('data') or {}).get('records') or [])
    if not records:
        return None
    record = records[0]
    period = str(record.get('ENDDATE') or '')[:10]
    values = {}
    for indicator, field in HEADSTRIP_FIELDS.items():
        value = record.get(field)
        if isinstance(value, (int, float)):
            values[indicator] = float(value)
    return {'period': period, 'values': values} if period and values else None


def fetch_market_caps(page_size=100):
    """全市场行情：一次分页请求即可覆盖沪深京全部 A 股的总市值/流通市值。"""
    out, page = {}, 1
    while True:
        payload = _get_json(EASTMONEY_QUOTE, {
            'pn': page, 'pz': page_size, 'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
            'fid': 'f3', 'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
            'fields': 'f12,f14,f20,f21',
        }, headers=EASTMONEY_HEADERS)
        data = payload.get('data') or {}
        rows = data.get('diff') or []
        if not rows:
            break
        for item in rows:
            code = item.get('f12')
            if not code:
                continue
            entry = {}
            if isinstance(item.get('f20'), (int, float)):
                entry['market_cap'] = float(item['f20'])
            if isinstance(item.get('f21'), (int, float)):
                entry['float_market_cap'] = float(item['f21'])
            if entry:
                entry['name'] = item.get('f14')
                out[code] = entry
        total = data.get('total') or 0
        if page * page_size >= total:
            break
        page += 1
    return out


def _market_symbol(code):
    return ('SH' if code.startswith(('6', '9')) else
            'BJ' if code.startswith(('4', '8')) else 'SZ') + code


def fetch_balance_sheet(code):
    """东财 F10 资产负债表；companyType 依公司类型不同，逐个探测。"""
    symbol = _market_symbol(code)
    for company_type in (4, 3, 2, 1):
        try:
            dates = _get_json(EASTMONEY_BALANCE_DATES,
                              {'companyType': company_type, 'reportDateType': 0,
                               'code': symbol}, headers=EASTMONEY_HEADERS)
        except Exception:
            continue
        rows = dates.get('data') or []
        if not rows:
            continue
        period = str(rows[0].get('REPORT_DATE') or '')[:10]
        if not period:
            continue
        detail = _get_json(EASTMONEY_BALANCE,
                           {'companyType': company_type, 'reportDateType': 0,
                            'reportType': 1, 'dates': period, 'code': symbol},
                           headers=EASTMONEY_HEADERS)
        records = detail.get('data') or []
        if not records:
            continue
        record = records[0]
        values = {}
        for indicator, field in (('total_assets', 'TOTAL_ASSETS'),
                                 ('total_liabilities', 'TOTAL_LIABILITIES')):
            value = record.get(field)
            if isinstance(value, (int, float)):
                values[indicator] = float(value)
        if values:
            return {'period': period, 'values': values, 'company_type': company_type}
    return None


def upsert_company(conn, row, now):
    conn.execute('''INSERT INTO listed_companies
      (code,name,org_id,category,register_address,office_address,register_city,
       register_province,office_city,office_province,industry,listed_date,
       data_status,source_name,source_url,parser_notes,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(code) DO UPDATE SET
        name=excluded.name,org_id=excluded.org_id,category=excluded.category,
        register_address=excluded.register_address,office_address=excluded.office_address,
        register_city=excluded.register_city,register_province=excluded.register_province,
        office_city=excluded.office_city,office_province=excluded.office_province,
        industry=excluded.industry,listed_date=excluded.listed_date,
        updated_at=excluded.updated_at''',
      (row['code'], row.get('name'), row.get('org_id'), row.get('category'),
       row.get('register_address'), row.get('office_address'),
       row.get('register_city'), row.get('register_province'),
       row.get('office_city'), row.get('office_province'),
       row.get('industry'), row.get('listed_date'), 'official', SOURCE_CNINFO,
       CNINFO_PROFILE, '巨潮公司概况接口直接值；城市由注册地/办公地地址串解析。', now))


def upsert_observation(conn, code, name, indicator, period, value,
                       data_status, source_name, source_url, notes, now):
    conn.execute('''INSERT INTO listed_company_observations
      (code,name,indicator_code,period,value,unit,data_status,source_name,
       source_url,parser_notes,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(code,indicator_code,period,source_name) DO UPDATE SET
        name=excluded.name,value=excluded.value,unit=excluded.unit,
        data_status=excluded.data_status,source_url=excluded.source_url,
        parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
      (code, name, indicator, period, value, INDICATOR_UNITS.get(indicator, ''),
       data_status, source_name, source_url, notes, now))


def _existing_codes(conn, table, column='code', where=''):
    try:
        return {row[0] for row in conn.execute(
            f'SELECT DISTINCT {column} FROM {table} {where}')}
    except sqlite3.OperationalError:
        return set()


def update_company_directory(db_path, limit=None, refresh=False, progress_every=50):
    """第一步：全市场公司名录与城市归属（巨潮官方，一次性，可断点续跑）。"""
    conn = _connect(db_path)
    try:
        ensure_tables(conn)
        listing = fetch_stock_list()
        done = set() if refresh else _existing_codes(
            conn, 'listed_companies', where='WHERE register_address IS NOT NULL')
        todo = [item for item in listing if item['code'] not in done]
        if limit:
            todo = todo[:int(limit)]
        now = datetime.now().isoformat()
        ok, errors = 0, []
        for index, item in enumerate(todo, 1):
            try:
                profile = fetch_profile(item['code'])
            except Exception as exc:
                errors.append(f"{item['code']}: {exc}")
                continue
            if not profile:
                errors.append(f"{item['code']}: 概况为空")
                continue
            upsert_company(conn, {**item, **profile}, now)
            ok += 1
            if index % progress_every == 0:
                conn.commit()
                print(f'  …{index}/{len(todo)} 已入库 {ok}，失败 {len(errors)}', flush=True)
        conn.commit()
        total = conn.execute('SELECT COUNT(*) FROM listed_companies').fetchone()[0]
        with_city = conn.execute(
            'SELECT COUNT(*) FROM listed_companies WHERE office_city IS NOT NULL').fetchone()[0]
    finally:
        conn.close()
    return {'success': ok > 0 or not todo, 'listed_total': len(listing),
            'fetched': ok, 'pending_before': len(todo), 'errors': errors[:20],
            'error_count': len(errors), 'stored_total': total,
            'with_city': with_city}


def update_market_caps(db_path):
    """第三步之一：全市场市值（东方财富，一次分页拉完，标 third_party）。"""
    quotes = fetch_market_caps()
    now = datetime.now().isoformat()
    period = now[:10]
    conn = _connect(db_path)
    try:
        ensure_tables(conn)
        known = _existing_codes(conn, 'listed_companies')
        stored = 0
        for code, entry in quotes.items():
            if known and code not in known:
                continue
            for indicator in ('market_cap', 'float_market_cap'):
                if indicator in entry:
                    upsert_observation(
                        conn, code, entry.get('name'), indicator, period,
                        entry[indicator], 'third_party', SOURCE_EASTMONEY,
                        EASTMONEY_QUOTE,
                        '东方财富行情接口总市值/流通市值；商业数据商口径，非交易所披露原文。',
                        now)
                    stored += 1
        conn.commit()
    finally:
        conn.close()
    return {'success': stored > 0, 'quotes': len(quotes), 'stored': stored,
            'period': period, 'data_status': 'third_party'}


def update_financials(db_path, cities=None, city_scope='office_city',
                      limit=None, include_balance=True, progress_every=100):
    """第三步之二：目标城市公司的财务。

    巨潮给营收/净利/净资产（official），东财补总资产/总负债（third_party）。
    只跑目标城市的公司，避免为十城分析拉全市场资产负债表。
    """
    if city_scope not in ('office_city', 'register_city'):
        raise ValueError('city_scope 必须是 office_city 或 register_city')
    conn = _connect(db_path)
    try:
        ensure_tables(conn)
        sql = f'SELECT code,name FROM listed_companies WHERE {city_scope} IS NOT NULL'
        args = []
        if cities:
            sql += f" AND {city_scope} IN ({','.join('?' for _ in cities)})"
            args = list(cities)
        targets = [dict(zip(('code', 'name'), row))
                   for row in conn.execute(sql + ' ORDER BY code', args)]
        if limit:
            targets = targets[:int(limit)]
        now = datetime.now().isoformat()
        counts = {'cninfo': 0, 'eastmoney': 0}
        errors = []
        for index, item in enumerate(targets, 1):
            code, name = item['code'], item['name']
            try:
                head = fetch_headstrip(code)
                if head:
                    for indicator, value in head['values'].items():
                        upsert_observation(
                            conn, code, name, indicator, head['period'], value,
                            'official', SOURCE_CNINFO, CNINFO_HEADSTRIP,
                            '巨潮头部数据接口直接值；最新披露期。', now)
                        counts['cninfo'] += 1
            except Exception as exc:
                errors.append(f'{code} 巨潮: {exc}')
            if include_balance:
                try:
                    balance = fetch_balance_sheet(code)
                    if balance:
                        for indicator, value in balance['values'].items():
                            upsert_observation(
                                conn, code, name, indicator, balance['period'], value,
                                'third_party', SOURCE_EASTMONEY, EASTMONEY_BALANCE,
                                f"东方财富 F10 资产负债表（companyType="
                                f"{balance['company_type']}）；商业数据商口径。", now)
                            counts['eastmoney'] += 1
                except Exception as exc:
                    errors.append(f'{code} 东财: {exc}')
            if index % progress_every == 0:
                conn.commit()
                print(f'  …{index}/{len(targets)} 巨潮{counts["cninfo"]} '
                      f'东财{counts["eastmoney"]} 失败{len(errors)}', flush=True)
        conn.commit()
    finally:
        conn.close()
    return {'success': sum(counts.values()) > 0, 'targets': len(targets),
            'records': counts, 'error_count': len(errors), 'errors': errors[:20]}


AGGREGATE_INDICATORS = ('market_cap', 'revenue', 'net_profit', 'net_assets',
                        'total_assets', 'total_liabilities')


def _latest_by_code(conn, indicator):
    """同一公司同一指标可能有两个来源；官方优先，缺则用第三方，并记下用了谁。"""
    rows = conn.execute('''SELECT code,name,period,value,data_status,source_name
        FROM listed_company_observations WHERE indicator_code=?
        ORDER BY code,period''', (indicator,)).fetchall()
    chosen = {}
    for code, name, period, value, status, source in rows:
        current = chosen.get(code)
        better = (current is None
                  or (status == 'official' and current['data_status'] != 'official')
                  or (status == current['data_status'] and period > current['period']))
        if better:
            chosen[code] = {'name': name, 'period': period, 'value': value,
                            'data_status': status, 'source_name': source}
    return chosen


def build_city_listed_payload(db_path, cities=None, city_scope='office_city'):
    """按城市汇总上市公司；同时给出与 GDP 的比值（证券化率、营收/GDP）。"""
    if city_scope not in ('office_city', 'register_city'):
        raise ValueError('city_scope 必须是 office_city 或 register_city')
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        ensure_tables(conn)
        company_rows = conn.execute(
            f'SELECT code,name,{city_scope} AS city,industry,register_city,office_city '
            'FROM listed_companies').fetchall()
        by_code = {row['code']: dict(row) for row in company_rows}
        latest = {ind: _latest_by_code(conn, ind) for ind in AGGREGATE_INDICATORS}
        gdp = {}
        try:
            for row in conn.execute('''SELECT region_name,period,value
                FROM gdp_region_observations WHERE country_code='CN'
                AND indicator_code='nominal_gdp' ORDER BY period'''):
                gdp[row['region_name']] = {'period': row['period'], 'value': row['value']}
        except sqlite3.OperationalError:
            gdp = {}
    finally:
        conn.close()

    buckets = {}
    for code, company in by_code.items():
        city = company.get('city')
        if not city or (cities and city not in cities):
            continue
        bucket = buckets.setdefault(city, {
            'city': city, 'company_count': 0, 'with_value': {},
            'totals': {}, 'sources': {}, 'industries': {}})
        bucket['company_count'] += 1
        if company.get('industry'):
            bucket['industries'][company['industry']] = \
                bucket['industries'].get(company['industry'], 0) + 1
        for indicator in AGGREGATE_INDICATORS:
            hit = latest[indicator].get(code)
            if not hit:
                continue
            bucket['totals'][indicator] = bucket['totals'].get(indicator, 0.0) + hit['value']
            bucket['with_value'][indicator] = bucket['with_value'].get(indicator, 0) + 1
            bucket['sources'].setdefault(indicator, set()).add(hit['data_status'])

    out = []
    for city, bucket in buckets.items():
        # 上市公司数据单位为元，城市 GDP 为亿元；比值前先统一到亿元。
        city_gdp = gdp.get(city)
        totals_yi = {k: round(v / 1e8, 4) for k, v in bucket['totals'].items()}
        derived = {}
        if city_gdp and city_gdp['value']:
            for indicator, label in (('market_cap', 'securitisation_rate'),
                                     ('revenue', 'listed_revenue_to_gdp')):
                if indicator in totals_yi:
                    derived[label] = round(totals_yi[indicator] / city_gdp['value'] * 100, 2)
        out.append({
            'city': city, 'company_count': bucket['company_count'],
            'totals_yi': totals_yi, 'coverage': bucket['with_value'],
            'data_statuses': {k: sorted(v) for k, v in bucket['sources'].items()},
            'top_industries': sorted(bucket['industries'].items(),
                                     key=lambda kv: -kv[1])[:5],
            'gdp_yi': city_gdp['value'] if city_gdp else None,
            'gdp_period': city_gdp['period'] if city_gdp else None,
            'derived': derived,
        })
    out.sort(key=lambda item: -(item['totals_yi'].get('market_cap') or 0))
    return {
        'generated_at': datetime.now().isoformat(),
        'city_scope': city_scope,
        'cities': out,
        'indicator_names': INDICATOR_NAMES,
        'caveats': [
            '公司归属按地址解析：默认办公地，可切换注册地。两者常不同——'
            '茅台注册仁怀、格力注册珠海，为税收优惠注册在霍尔果斯/西藏而总部在'
            '北上深的更普遍；只用注册地会系统性扭曲城市产业实力。',
            '营业收入、净利润、净资产来自巨潮资讯网（证监会指定披露平台），标为 official；'
            '总市值、总资产、总负债来自东方财富，标为 third_party，两者不混。',
            '合计为最新披露期的简单加总：各公司报告期可能不同（年报/季报并存），'
            '且母公司与子公司同时上市时存在重复计入，不做抵消。',
            '证券化率＝上市公司总市值/该市 GDP，营收比＝上市公司营收合计/该市 GDP；'
            '两者分子是全国乃至全球经营的上市主体口径，分母是本地生产口径，只可横向'
            '对比城市间相对高低，不能解读为"本地经济由上市公司贡献的比例"。',
        ],
    }
