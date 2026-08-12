# -*- coding: utf-8 -*-
"""城市上市公司聚合：家数、市值与财务总量。

两套来源分开标注，绝不混为一谈：
  官方   巨潮资讯网（中国证监会指定信息披露平台）——公司概况、注册地/办公地、
         行业、上市日期与股本。
  第三方 东方财富——总市值及带真实报告期的利润表、资产负债表。巨潮公开的
         头部数据接口不提供可可靠识别报告期的完整三表，本项目不猜字段。

城市归属存双口径：注册地与办公地。两者常常不同（茅台注册仁怀、格力注册珠海，
更极端的是为税收优惠注册在霍尔果斯/西藏而总部在北上深），只用注册地会系统性
扭曲城市产业实力，因此都存下来由使用方选择。

营业收入与净利润只用最新完整年度，避免把一季度累计流量与全年 GDP 相除。
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
EASTMONEY_PROFIT_DATES = ('https://emweb.securities.eastmoney.com/PC_HSF10/'
                          'NewFinanceAnalysis/lrbDateAjaxNew')
EASTMONEY_PROFIT = ('https://emweb.securities.eastmoney.com/PC_HSF10/'
                    'NewFinanceAnalysis/lrbAjaxNew')

SOURCE_CNINFO = '巨潮资讯网（证监会指定披露平台）'
SOURCE_EASTMONEY = '东方财富（商业数据商）'

# 巨潮公司概况字段代号，来自接口原始返回；含义已用已知公司核对。
FIELD_REGISTER_ADDRESS = 'F004V'
FIELD_OFFICE_ADDRESS = 'F005V'
FIELD_INDUSTRY = 'F032V'
FIELD_LISTED_DATE = 'F006D'
# 巨潮头部数据只保留经核对确认的字段：股本。
#
# 曾把 F089N/F102N 当营收/净利、F109N 当净资产写入，前两个数值确实对得上，
# 但 F109N 与实际净资产差了数倍（平安银行 3880 亿 vs 实际 5441 亿、
# 茅台 488 亿 vs 约 2700 亿），是未经核对的臆断映射；而该接口的 ENDDATE
# 是行情日期（各股统一为 2026-07-25）不是报告期，用它当财务期同样是错的。
# 因此财务三项改由东财三表提供——那里有正确的 REPORT_DATE。
HEADSTRIP_FIELDS = {
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
    conn.execute('''CREATE TABLE IF NOT EXISTS listed_company_fetch_status (
      code TEXT NOT NULL, fetch_kind TEXT NOT NULL,
      start_period TEXT NOT NULL, end_period TEXT NOT NULL,
      status TEXT NOT NULL, records_stored INTEGER NOT NULL DEFAULT 0,
      error TEXT, updated_at TEXT NOT NULL,
      PRIMARY KEY(code,fetch_kind,start_period,end_period))''')
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


class UnsupportedCode(Exception):
    """接口明确表示不支持该代码（如北交所代码在巨潮公司概况接口上）。

    这类是确定性失败，重试毫无意义：251 个北交所代码若各退避 3 次，
    要白白消耗近一小时。与限流（返回拦截页）必须区别对待。
    """


def _get_json(url, params=None, headers=None, timeout=30):
    """限速 + 退避。仅对疑似限流重试；接口明确拒绝的代码立即放弃。"""
    last = None
    for attempt in range(RETRIES):
        time.sleep(REQUEST_PACING)
        try:
            response = requests.get(url, params=params,
                                    headers=headers or CNINFO_HEADERS, timeout=timeout)
            if response.status_code == 500:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                if str(body.get('msg') or '').startswith('validate fail'):
                    raise UnsupportedCode(f"{params}: {body.get('msg')}")
            response.raise_for_status()
            return response.json()
        except UnsupportedCode:
            raise
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
    # 北交所 2024 年起启用 920-929 新号段；必须先于上海 B 股的 9xx 判断，
    # 否则 92xxxx 会被错误拼成 SH92xxxx，东财 F10 只能返回空数据。
    return ('BJ' if code.startswith(('4', '8', '92')) else
            'SH' if code.startswith(('6', '9')) else 'SZ') + code


def _select_report_period(rows, annual_only=False):
    """从东财报告期清单选择可比期间；年度流量只取 12 月 31 日。"""
    periods = []
    for row in rows or []:
        period = str(row.get('REPORT_DATE') or '')[:10]
        if not period or (annual_only and not period.endswith('-12-31')):
            continue
        periods.append(period)
    return max(periods) if periods else None


def _fetch_em_statement(code, dates_url, detail_url, field_map, annual_only=False,
                        preferred_period=None):
    """东财 F10 报表通用取数：companyType 依公司类型不同，逐个探测。

    与巨潮头部数据不同，这里的 REPORT_DATE 是真正的报告期，可安全用作 period。
    """
    symbol = _market_symbol(code)
    for company_type in (4, 3, 2, 1):
        period = preferred_period
        if not period:
            try:
                dates = _get_json(dates_url,
                                  {'companyType': company_type, 'reportDateType': 0,
                                   'code': symbol}, headers=EASTMONEY_HEADERS)
            except Exception:
                continue
            rows = dates.get('data') or []
            if not rows:
                continue
            period = _select_report_period(rows, annual_only=annual_only)
        if not period:
            continue
        detail = _get_json(detail_url,
                           {'companyType': company_type, 'reportDateType': 0,
                            'reportType': 1, 'dates': period, 'code': symbol},
                           headers=EASTMONEY_HEADERS)
        records = detail.get('data') or []
        if not records:
            continue
        record = records[0]
        values = {}
        for indicator, field in field_map:
            value = record.get(field)
            if isinstance(value, (int, float)):
                values[indicator] = float(value)
        if values:
            return {'period': period, 'values': values, 'company_type': company_type}
    return None


def fetch_balance_sheet(code):
    return _fetch_em_statement(code, EASTMONEY_BALANCE_DATES, EASTMONEY_BALANCE,
                               (('total_assets', 'TOTAL_ASSETS'),
                                ('total_liabilities', 'TOTAL_LIABILITIES'),
                                ('net_assets', 'TOTAL_PARENT_EQUITY')))


def fetch_profit_sheet(code, annual_period=None):
    """取最新完整年度利润表；净利润使用归母口径。"""
    return _fetch_em_statement(code, EASTMONEY_PROFIT_DATES, EASTMONEY_PROFIT,
                               (('revenue', 'TOTAL_OPERATE_INCOME'),
                                ('net_profit', 'PARENT_NETPROFIT')),
                               annual_only=True, preferred_period=annual_period)


def _parse_profit_history_records(records, company_type=None):
    """把东财多年度利润表响应转为按报告期排列的标准记录。"""
    out = []
    for record in records or []:
        period = str(record.get('REPORT_DATE') or '')[:10]
        if not period.endswith('-12-31'):
            continue
        values = {}
        for indicator, field in (('revenue', 'TOTAL_OPERATE_INCOME'),
                                 ('net_profit', 'PARENT_NETPROFIT')):
            value = record.get(field)
            if isinstance(value, (int, float)):
                values[indicator] = float(value)
        if values:
            out.append({'period': period, 'values': values,
                        'company_type': company_type})
    return sorted(out, key=lambda item: item['period'])


def fetch_profit_history(code, start_year=2021, end_year=2025):
    """一次请求读取多期完整年度利润表，避免逐年重复访问。"""
    if int(start_year) > int(end_year):
        raise ValueError('start_year 不能晚于 end_year')
    dates = ','.join(f'{year}-12-31'
                     for year in range(int(start_year), int(end_year) + 1))
    symbol = _market_symbol(code)
    for company_type in (4, 3, 2, 1):
        payload = _get_json(
            EASTMONEY_PROFIT,
            {'companyType': company_type, 'reportDateType': 0,
             'reportType': 1, 'dates': dates, 'code': symbol},
            headers=EASTMONEY_HEADERS)
        parsed = _parse_profit_history_records(payload.get('data') or [], company_type)
        if parsed:
            return parsed
    return []


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
        ok, errors, unsupported = 0, [], []
        for index, item in enumerate(todo, 1):
            try:
                profile = fetch_profile(item['code'])
            except UnsupportedCode:
                unsupported.append(item['code'])
                continue
            except Exception as exc:
                errors.append(f"{item['code']}: {exc}")
                continue
            if not profile:
                errors.append(f"{item['code']}: 概况为空")
                continue
            upsert_company(conn, {**item, **profile}, datetime.now().isoformat())
            conn.commit()          # 绝不跨网络 I/O 持有写事务，否则服务器写入会被饿死
            ok += 1
            if index % progress_every == 0:
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
            'with_city': with_city,
            'unsupported_count': len(unsupported),
            'unsupported_sample': unsupported[:10]}


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
                      limit=None, include_balance=True, progress_every=50,
                      resume=True, include_headstrip=True, annual_period=None):
    """第三步之二：目标城市公司的财务。

    巨潮只给经核实的股本；东财提供最新完整年度利润表和最新资产负债表，均标
    third_party。只跑目标城市的公司，避免为十城分析拉全市场财务报表。
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
        if resume:
            if annual_period:
                done_rows = conn.execute(
                    '''SELECT DISTINCT code FROM listed_company_observations
                       WHERE indicator_code='revenue' AND source_name=? AND period=?''',
                    (SOURCE_EASTMONEY, annual_period))
            else:
                done_rows = conn.execute(
                    '''SELECT DISTINCT code FROM listed_company_observations
                       WHERE indicator_code='revenue' AND source_name=?
                       AND period LIKE '%-12-31' ''', (SOURCE_EASTMONEY,))
            done = {row[0] for row in done_rows}
            targets = [item for item in targets if item['code'] not in done]
        if limit:
            targets = targets[:int(limit)]
        now = datetime.now().isoformat()
        counts = {'cninfo': 0, 'eastmoney': 0}
        errors = []
        for index, item in enumerate(targets, 1):
            code, name = item['code'], item['name']
            if include_headstrip:
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
            profit_fetcher = lambda target_code: fetch_profit_sheet(
                target_code, annual_period=annual_period)
            fetchers = [(profit_fetcher, '年度利润表', EASTMONEY_PROFIT)]
            if include_balance:
                fetchers.insert(0, (fetch_balance_sheet, '资产负债表', EASTMONEY_BALANCE))
            for fetcher, label, url in fetchers:
                try:
                    statement = fetcher(code)
                    if not statement:
                        continue
                    for indicator, value in statement['values'].items():
                        upsert_observation(
                            conn, code, name, indicator, statement['period'], value,
                            'third_party', SOURCE_EASTMONEY, url,
                            f"东方财富 F10 {label}（companyType="
                            f"{statement['company_type']}）；报告期为披露口径。", now)
                        counts['eastmoney'] += 1
                except Exception as exc:
                    errors.append(f'{code} 东财{label}: {exc}')
            conn.commit()          # 每家一提交，写锁只在毫秒级持有
            if index % progress_every == 0:
                print(f'  …{index}/{len(targets)} 巨潮{counts["cninfo"]} '
                      f'东财{counts["eastmoney"]} 失败{len(errors)}', flush=True)
        conn.commit()
    finally:
        conn.close()
    return {'success': sum(counts.values()) > 0, 'targets': len(targets),
            'records': counts, 'error_count': len(errors), 'errors': errors[:20]}


def _upsert_fetch_status(conn, code, fetch_kind, start_period, end_period,
                         status, records_stored, error, now):
    conn.execute('''INSERT INTO listed_company_fetch_status
      (code,fetch_kind,start_period,end_period,status,records_stored,error,updated_at)
      VALUES (?,?,?,?,?,?,?,?)
      ON CONFLICT(code,fetch_kind,start_period,end_period) DO UPDATE SET
        status=excluded.status,records_stored=excluded.records_stored,
        error=excluded.error,updated_at=excluded.updated_at''',
      (code, fetch_kind, start_period, end_period, status,
       int(records_stored or 0), error, now))


def update_financial_history(db_path, cities=None, city_scope='office_city',
                             start_year=2021, end_year=2025, limit=None,
                             resume=True, retry_missing=False,
                             progress_every=50):
    """回填目标城市公司完整年度营收/归母净利润；每家公司一次多期请求。"""
    if city_scope not in ('office_city', 'register_city'):
        raise ValueError('city_scope 必须是 office_city 或 register_city')
    start_year, end_year = int(start_year), int(end_year)
    if start_year > end_year:
        raise ValueError('start_year 不能晚于 end_year')
    start_period, end_period = f'{start_year}-12-31', f'{end_year}-12-31'
    fetch_kind = 'profit_history'
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
        if resume:
            terminal_statuses = ('ok',) if retry_missing else ('ok', 'missing')
            done = {row[0] for row in conn.execute(
                f'''SELECT code FROM listed_company_fetch_status
                    WHERE fetch_kind=? AND start_period=? AND end_period=?
                    AND status IN ({','.join('?' for _ in terminal_statuses)})''',
                (fetch_kind, start_period, end_period, *terminal_statuses))}
            targets = [item for item in targets if item['code'] not in done]
        if limit:
            targets = targets[:int(limit)]
        stored, companies_ok, missing, errors = 0, 0, 0, []
        for index, item in enumerate(targets, 1):
            code, name = item['code'], item['name']
            now = datetime.now().isoformat()
            try:
                records = fetch_profit_history(code, start_year, end_year)
                company_stored = 0
                for statement in records:
                    for indicator, value in statement['values'].items():
                        upsert_observation(
                            conn, code, name, indicator, statement['period'], value,
                            'third_party', SOURCE_EASTMONEY, EASTMONEY_PROFIT,
                            f"东方财富 F10 多年度利润表（companyType="
                            f"{statement['company_type']}）；完整年度累计值。", now)
                        company_stored += 1
                status = 'ok' if company_stored else 'missing'
                _upsert_fetch_status(
                    conn, code, fetch_kind, start_period, end_period,
                    status, company_stored, None, now)
                stored += company_stored
                companies_ok += bool(company_stored)
                missing += not company_stored
            except Exception as exc:
                message = str(exc)
                _upsert_fetch_status(
                    conn, code, fetch_kind, start_period, end_period,
                    'error', 0, message[:1000], now)
                errors.append(f'{code}: {message}')
            conn.commit()
            if index % progress_every == 0:
                print(f'  …{index}/{len(targets)} 公司有值{companies_ok} '
                      f'缺失{missing} 记录{stored} 失败{len(errors)}', flush=True)
        conn.commit()
    finally:
        conn.close()
    return {
        'success': stored > 0 or (not targets and resume),
        'targets': len(targets), 'companies_with_data': companies_ok,
        'missing': missing, 'records': stored,
        'start_period': start_period, 'end_period': end_period,
        'error_count': len(errors), 'errors': errors[:20],
    }


AGGREGATE_INDICATORS = ('market_cap', 'revenue', 'net_profit', 'net_assets',
                        'total_assets', 'total_liabilities')
ANNUAL_FLOW_INDICATORS = ('revenue', 'net_profit')
# 少数停牌/退市公司的"最新"报表停在数年前（实测有 2013、2017 年的）。
# 金额虽小，但把 2013 年的报表和 2026 年的加进同一个合计属于口径错误，
# 因此按报告期下限剔除，并在结果里报告剔除了多少家。
STALE_REPORT_FLOOR = '2025-06-30'
# 市值是行情快照，不受报告期下限约束。
PERIOD_FLOOR_EXEMPT = ('market_cap', 'float_market_cap')


def _latest_by_code(conn, indicator, period_floor=STALE_REPORT_FLOOR):
    """同一公司同一指标可能有两个来源；官方优先，缺则用第三方，并记下用了谁。

    返回 (选中值, 因报告期过旧被剔除的代码集合)。
    """
    rows = conn.execute('''SELECT code,name,period,value,data_status,source_name
        FROM listed_company_observations WHERE indicator_code=?
        ORDER BY code,period''', (indicator,)).fetchall()
    chosen, stale = {}, set()
    apply_floor = period_floor and indicator not in PERIOD_FLOOR_EXEMPT
    for code, name, period, value, status, source in rows:
        if indicator in ANNUAL_FLOW_INDICATORS and not period.endswith('-12-31'):
            continue
        if apply_floor and period < period_floor:
            stale.add(code)
            continue
        current = chosen.get(code)
        better = (current is None
                  or (status == 'official' and current['data_status'] != 'official')
                  or (status == current['data_status'] and period > current['period']))
        if better:
            chosen[code] = {'name': name, 'period': period, 'value': value,
                            'data_status': status, 'source_name': source}
    return chosen, stale - set(chosen)


def _concentration_summary(entries, company_count, top_n=10):
    """城市聚合的头部贡献与 HHI；只在该指标有正值的公司中计算。"""
    valid = [dict(item) for item in entries if item.get('value', 0) > 0]
    valid.sort(key=lambda item: -item['value'])
    total = sum(item['value'] for item in valid)
    if not total:
        return {
            'n_obs': 0, 'company_count': company_count, 'coverage_pct': 0.0,
            'top1_share_pct': None, 'top5_share_pct': None, 'hhi': None,
            'top_companies': [],
        }
    shares = [item['value'] / total for item in valid]
    top_companies = []
    for item, share in zip(valid[:top_n], shares[:top_n]):
        top_companies.append({
            'code': item.get('code'), 'name': item.get('name'),
            'industry': item.get('industry'), 'category': item.get('category'),
            'office_city': item.get('office_city'),
            'register_city': item.get('register_city'),
            'period': item.get('period'), 'data_status': item.get('data_status'),
            'value_yi': round(item['value'] / 1e8, 4),
            'share_pct': round(share * 100, 2),
        })
    return {
        'n_obs': len(valid), 'company_count': company_count,
        'coverage_pct': round(len(valid) / company_count * 100, 2)
        if company_count else 0.0,
        'top1_share_pct': round(shares[0] * 100, 2),
        'top5_share_pct': round(sum(shares[:5]) * 100, 2),
        'hhi': round(sum(share * share for share in shares) * 10000, 2),
        'top_companies': top_companies,
        'method': 'HHI=各公司占该城市已覆盖公司指标合计的份额平方和×10000。',
    }


def _annual_values_by_code(conn, indicator, start_year=2021):
    """年度流量按公司/年份选一条；同年仍坚持 official 优先。"""
    rows = conn.execute('''SELECT code,name,period,value,data_status,source_name
        FROM listed_company_observations
        WHERE indicator_code=? AND period LIKE '%-12-31' AND period>=?
        ORDER BY code,period''', (indicator, f'{int(start_year)}-12-31')).fetchall()
    chosen = {}
    for code, name, period, value, status, source in rows:
        year = period[:4]
        current = chosen.setdefault(code, {}).get(year)
        better = (current is None
                  or (status == 'official' and current['data_status'] != 'official'))
        if better:
            chosen[code][year] = {
                'name': name, 'period': period, 'value': value,
                'data_status': status, 'source_name': source,
            }
    return chosen


def _build_city_annual_history(codes, annual_values, periods):
    """输出可变覆盖样本和平衡样本两套城市年度聚合，利润率只用同公司交集。"""
    codes = set(codes)
    revenue = annual_values.get('revenue') or {}
    profit = annual_values.get('net_profit') or {}

    def row_for(period, eligible_codes=None):
        pool = codes if eligible_codes is None else codes & set(eligible_codes)
        revenue_codes = {code for code in pool if period in revenue.get(code, {})}
        profit_codes = {code for code in pool if period in profit.get(code, {})}
        matched = revenue_codes & profit_codes
        revenue_total = sum(revenue[code][period]['value'] for code in revenue_codes)
        profit_total = sum(profit[code][period]['value'] for code in profit_codes)
        matched_revenue = sum(revenue[code][period]['value'] for code in matched)
        matched_profit = sum(profit[code][period]['value'] for code in matched)
        return {
            'period': period,
            'revenue_yi': round(revenue_total / 1e8, 4) if revenue_codes else None,
            'net_profit_yi': round(profit_total / 1e8, 4) if profit_codes else None,
            'profit_margin_pct': round(matched_profit / matched_revenue * 100, 2)
            if matched_revenue else None,
            'revenue_coverage': len(revenue_codes),
            'net_profit_coverage': len(profit_codes),
            'matched_coverage': len(matched),
        }

    balanced = {
        code for code in codes
        if all(period in revenue.get(code, {}) and period in profit.get(code, {})
               for period in periods)
    }
    return {
        'periods': list(periods),
        'available': [row_for(period) for period in periods],
        'balanced': [row_for(period, balanced) for period in periods],
        'balanced_company_count': len(balanced),
        'company_count': len(codes),
        'method': ('available 为各年已有值的当前公司样本；balanced 只保留所有年份均有'
                   '营收和净利润的当前公司。利润率在同公司交集上计算。'),
    }


def build_city_listed_payload(db_path, cities=None, city_scope='office_city',
                              period_floor=STALE_REPORT_FLOOR):
    """按城市汇总上市公司；同时给出与 GDP 的比值（证券化率、营收/GDP）。"""
    if city_scope not in ('office_city', 'register_city'):
        raise ValueError('city_scope 必须是 office_city 或 register_city')
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        ensure_tables(conn)
        company_rows = conn.execute(
            f'SELECT code,name,{city_scope} AS city,industry,category,listed_date,'
            'register_city,office_city '
            'FROM listed_companies').fetchall()
        by_code = {row['code']: dict(row) for row in company_rows}
        latest, stale_codes = {}, set()
        for ind in AGGREGATE_INDICATORS:
            latest[ind], dropped = _latest_by_code(conn, ind, period_floor)
            stale_codes |= dropped
        annual_values = {
            indicator: _annual_values_by_code(conn, indicator, start_year=2021)
            for indicator in ('revenue', 'net_profit')
        }
        annual_periods = sorted({
            period for indicator_values in annual_values.values()
            for code_values in indicator_values.values()
            for period in code_values
        })
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
            'totals': {}, 'sources': {}, 'periods': {}, 'industries': {},
            'company_values': {}, 'codes': []})
        bucket['company_count'] += 1
        bucket['codes'].append(code)
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
            period_counts = bucket['periods'].setdefault(indicator, {})
            period_counts[hit['period']] = period_counts.get(hit['period'], 0) + 1
            bucket['company_values'].setdefault(indicator, []).append({
                'code': code, 'name': company.get('name') or hit.get('name'),
                'industry': company.get('industry'), 'category': company.get('category'),
                'office_city': company.get('office_city'),
                'register_city': company.get('register_city'),
                'period': hit.get('period'), 'data_status': hit.get('data_status'),
                'value': hit.get('value'),
            })

    out = []
    for city, bucket in buckets.items():
        # 上市公司数据单位为元，城市 GDP 为亿元；比值前先统一到亿元。
        city_gdp = gdp.get(city)
        totals_yi = {k: round(v / 1e8, 4) for k, v in bucket['totals'].items()}
        report_periods = {}
        for indicator, counts in bucket['periods'].items():
            periods = sorted(counts)
            report_periods[indicator] = {
                'start': periods[0], 'end': periods[-1],
                'n_periods': len(periods), 'counts': counts,
            }
        derived = {}
        if city_gdp and city_gdp['value']:
            if 'market_cap' in totals_yi:
                derived['securitisation_rate'] = round(
                    totals_yi['market_cap'] / city_gdp['value'] * 100, 2)
            revenue_period = report_periods.get('revenue') or {}
            same_annual_period = (
                revenue_period.get('start') == revenue_period.get('end')
                and str(revenue_period.get('end') or '').startswith(
                    str(city_gdp['period'])[:4] + '-')
                and str(revenue_period.get('end') or '').endswith('-12-31')
            )
            if 'revenue' in totals_yi and same_annual_period:
                derived['listed_revenue_to_gdp'] = round(
                    totals_yi['revenue'] / city_gdp['value'] * 100, 2)
        out.append({
            'city': city, 'company_count': bucket['company_count'],
            'totals_yi': totals_yi, 'coverage': bucket['with_value'],
            'report_periods': report_periods,
            'data_statuses': {k: sorted(v) for k, v in bucket['sources'].items()},
            'top_industries': sorted(bucket['industries'].items(),
                                     key=lambda kv: -kv[1])[:5],
            'gdp_yi': city_gdp['value'] if city_gdp else None,
            'gdp_period': city_gdp['period'] if city_gdp else None,
            'derived': derived,
            'concentration': {
                indicator: _concentration_summary(
                    bucket['company_values'].get(indicator, []),
                    bucket['company_count'])
                for indicator in ('market_cap', 'revenue')
            },
            'annual_history': _build_city_annual_history(
                bucket['codes'], annual_values, annual_periods),
        })
    out.sort(key=lambda item: -(item['totals_yi'].get('market_cap') or 0))
    comparison_cities = list(cities) if cities else sorted({
        company.get('office_city') or company.get('register_city')
        for company in by_code.values()
        if company.get('office_city') or company.get('register_city')
    })
    scope_comparison = []
    for city in comparison_cities:
        office_count = sum(item.get('office_city') == city for item in by_code.values())
        register_count = sum(item.get('register_city') == city for item in by_code.values())
        known_both = [item for item in by_code.values()
                      if item.get('office_city') and item.get('register_city')]
        scope_comparison.append({
            'city': city, 'office_count': office_count,
            'register_count': register_count, 'delta': office_count - register_count,
            'office_gain_from_elsewhere': sum(
                item.get('office_city') == city and item.get('register_city') != city
                for item in known_both),
            'register_loss_to_elsewhere': sum(
                item.get('register_city') == city and item.get('office_city') != city
                for item in known_both),
        })
    return {
        'generated_at': datetime.now().isoformat(),
        'city_scope': city_scope,
        'period_floor': period_floor,
        'stale_excluded': sorted(stale_codes),
        'cities': out,
        'scope_comparison': scope_comparison,
        'indicator_names': INDICATOR_NAMES,
        'caveats': [
            '公司归属按地址解析：默认办公地，可切换注册地。两者常不同——'
            '茅台注册仁怀、格力注册珠海，为税收优惠注册在霍尔果斯/西藏而总部在'
            '北上深的更普遍；只用注册地会系统性扭曲城市产业实力。',
            '公司地址、行业、上市日期与股本来自巨潮资讯网（证监会指定披露平台），'
            '标为 official；总市值和财务三表来自东方财富，标为 third_party，两者不混。',
            '营业收入与净利润只采用各公司最新完整年度（12 月 31 日）累计值，并且只在'
            '该年度与 GDP 年份一致时计算营收/GDP；净资产、总资产、总负债采用最新报告期。',
            f'合计为最新披露期的简单加总，且只采用报告期不早于 {period_floor} 的报表；'
            '停牌或退市公司若最新报表停在数年前会被剔除，避免与当期混加。'
            '资产负债表的报告期仍可能因公司披露进度不同；母公司与子公司同时上市时'
            '存在重复计入，不做抵消。',
            '总资产与总负债含金融机构：北京、上海因银行总部集中，该两项主要由'
            '金融资产构成，与制造业城市不可直接比较。',
            '证券化率＝上市公司总市值/该市 GDP，营收比＝上市公司营收合计/该市 GDP；'
            '两者分子是全国乃至全球经营的上市主体口径，分母是本地生产口径，只可横向'
            '对比城市间相对高低，不能解读为"本地经济由上市公司贡献的比例"。',
            'Top1、Top5 与 HHI 均以该城市该指标已有值的公司合计为分母；覆盖不足时会'
            '单列覆盖率。办公地/注册地差异只使用两类地址均成功解析的公司解释迁移方向。',
            '历史趋势按当前仍在名录中的公司回看，存在存续者偏差，也沿用当前办公地/注册地'
            '归属；available 样本会随年份变化，balanced 样本保持同一批五年都有值的公司。',
        ],
    }
