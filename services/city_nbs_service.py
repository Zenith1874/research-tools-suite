# -*- coding: utf-8 -*-
"""国家统计局“主要城市年度数据”官方管线。

该接口覆盖 36 个主要城市，全部纳入。本项目十城中的常州、苏州、无锡不在这
36 城名单内，其数据继续走各市统计局公报那一路。统计局在线序列可能
包含历次修订，因此写入时遵循：补空缺、替换第三方镜像，但不静默覆盖城市官网
公报的已发布版本；冲突会随更新结果返回，便于审计。
"""
import re
import sqlite3
import time
from datetime import datetime

import requests

from services.regional_fiscal_service import ensure_regional_fiscal_table
from services.data_conflict_service import (
    ensure_conflict_table, record_conflict, clear_conflict, prune_stale,
)


NBS_PAGE = 'https://data.stats.gov.cn/dg/website/page.html#/pc/national/mainYearData'
NBS_API = 'https://data.stats.gov.cn/dg/website/publicrelease/web/external'
NBS_SOURCE_NAME = '国家统计局“主要城市年度数据”'
NBS_ROOT_CODE = 8

HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://data.stats.gov.cn',
    'Referer': NBS_PAGE,
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                   'AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'),
}

# db_region_code/scope 与既有库保持一致：直辖市财政存省级行政区代码，
# 其他城市存地级市代码；nbs_da 是统计局接口中的地区维度值。
#
# gdp_region_code 单独给：统计局在线序列是五经普修订后的口径，而库里省级行政区
# 那批 GDP 是年鉴修订前口径且覆盖 31 个省。若把直辖市的修订值写回省级码，
# 省级排行就会变成 2 个省用新口径、29 个用旧口径——那是新造一个断点。
# 因此直辖市的 GDP 写到城市码，省级码原样保留，两套口径各自内部自洽。
NBS_CITIES = {
    '北京': {'db_region_code': '110000', 'gdp_region_code': '110100',
             'scope': 'province_total', 'nbs_da': '110000000000'},
    '天津': {'db_region_code': '120000', 'gdp_region_code': '120100',
             'scope': 'province_total', 'nbs_da': '120000000000'},
    '石家庄': {'db_region_code': '130100', 'scope': 'city_total', 'nbs_da': '130100000000'},
    '太原': {'db_region_code': '140100', 'scope': 'city_total', 'nbs_da': '140100000000'},
    '呼和浩特': {'db_region_code': '150100', 'scope': 'city_total', 'nbs_da': '150100000000'},
    '沈阳': {'db_region_code': '210100', 'scope': 'city_total', 'nbs_da': '210100000000'},
    '大连': {'db_region_code': '210200', 'scope': 'city_total', 'nbs_da': '210200000000'},
    '长春': {'db_region_code': '220100', 'scope': 'city_total', 'nbs_da': '220100000000'},
    '哈尔滨': {'db_region_code': '230100', 'scope': 'city_total', 'nbs_da': '230100000000'},
    '上海': {'db_region_code': '310000', 'gdp_region_code': '310100',
             'scope': 'province_total', 'nbs_da': '310000000000'},
    '南京': {'db_region_code': '320100', 'scope': 'city_total', 'nbs_da': '320100000000'},
    '杭州': {'db_region_code': '330100', 'scope': 'city_total', 'nbs_da': '330100000000'},
    '宁波': {'db_region_code': '330200', 'scope': 'city_total', 'nbs_da': '330200000000'},
    '合肥': {'db_region_code': '340100', 'scope': 'city_total', 'nbs_da': '340100000000'},
    '福州': {'db_region_code': '350100', 'scope': 'city_total', 'nbs_da': '350100000000'},
    '厦门': {'db_region_code': '350200', 'scope': 'city_total', 'nbs_da': '350200000000'},
    '南昌': {'db_region_code': '360100', 'scope': 'city_total', 'nbs_da': '360100000000'},
    '济南': {'db_region_code': '370100', 'scope': 'city_total', 'nbs_da': '370100000000'},
    '青岛': {'db_region_code': '370200', 'scope': 'city_total', 'nbs_da': '370200000000'},
    '郑州': {'db_region_code': '410100', 'scope': 'city_total', 'nbs_da': '410100000000'},
    '武汉': {'db_region_code': '420100', 'scope': 'city_total', 'nbs_da': '420100000000'},
    '长沙': {'db_region_code': '430100', 'scope': 'city_total', 'nbs_da': '430100000000'},
    '广州': {'db_region_code': '440100', 'scope': 'city_total', 'nbs_da': '440100000000'},
    '深圳': {'db_region_code': '440300', 'scope': 'city_total', 'nbs_da': '440300000000'},
    '南宁': {'db_region_code': '450100', 'scope': 'city_total', 'nbs_da': '450100000000'},
    '海口': {'db_region_code': '460100', 'scope': 'city_total', 'nbs_da': '460100000000'},
    '重庆': {'db_region_code': '500000', 'gdp_region_code': '500100',
             'scope': 'province_total', 'nbs_da': '500000000000'},
    '成都': {'db_region_code': '510100', 'scope': 'city_total', 'nbs_da': '510100000000'},
    '贵阳': {'db_region_code': '520100', 'scope': 'city_total', 'nbs_da': '520100000000'},
    '昆明': {'db_region_code': '530100', 'scope': 'city_total', 'nbs_da': '530100000000'},
    '拉萨': {'db_region_code': '540100', 'scope': 'city_total', 'nbs_da': '540100000000'},
    '西安': {'db_region_code': '610100', 'scope': 'city_total', 'nbs_da': '610100000000'},
    '兰州': {'db_region_code': '620100', 'scope': 'city_total', 'nbs_da': '620100000000'},
    '西宁': {'db_region_code': '630100', 'scope': 'city_total', 'nbs_da': '630100000000'},
    '银川': {'db_region_code': '640100', 'scope': 'city_total', 'nbs_da': '640100000000'},
    '乌鲁木齐': {'db_region_code': '650100', 'scope': 'city_total', 'nbs_da': '650100000000'},
}

# label 使用前缀匹配，避免统计局在括号前后调整空格。destination 决定落库表。
CATEGORY_INDICATORS = {
    '国民经济核算': {
        '地区生产总值': ('nominal_gdp', '亿元', 'gdp'),
        '第一产业增加值': ('primary_industry_value', '亿元', 'gdp'),
        '第二产业增加值': ('secondary_industry_value', '亿元', 'gdp'),
        '第三产业增加值': ('tertiary_industry_value', '亿元', 'gdp'),
    },
    '财政和金融': {
        '地方一般公共预算收入': ('general_budget_revenue', '亿元', 'fiscal'),
        '地方一般公共预算支出': ('general_budget_expenditure', '亿元', 'fiscal'),
        '住户存款余额': ('household_deposits', '亿元', 'indicator'),
    },
    # 以下几类同属该接口，落 city_indicator_observations（城市年度一般指标）。
    # 其中"住宅商品房平均销售价格"是官方城市级价格水平，与统计局 70 城指数
    # （只有涨跌幅）和安居客挂牌价（商业参考）互补，本站此前没有这一项。
    '房地产': {
        '房地产开发投资额': ('real_estate_investment', '亿元', 'indicator'),
        '商品房销售面积': ('commercial_housing_sold_area', '万平方米', 'indicator'),
        '住宅商品房平均销售价格': ('residential_avg_price', '元/平方米', 'indicator'),
        '房地产开发企业购置土地面积': ('land_purchased_area', '万平方米', 'indicator'),
    },
    '贸易经济': {
        '社会消费品零售总额': ('retail_sales', '亿元', 'indicator'),
        '货物进出口总额': ('trade_total', '百万美元', 'indicator'),
    },
    '人口和就业': {
        '年末户籍人口': ('registered_population', '万人', 'indicator'),
        '城镇非私营单位在岗职工平均工资': ('avg_wage', '元', 'indicator'),
    },
}


def _normal(text):
    return re.sub(r'\s+', '', text or '')


# 36 城 × 5 分类是近两百个请求，连打会被统计局限流（返回非 JSON 的拦截页）。
# 两道措施：请求间固定间隔放慢节奏；命中限流时指数退避重试，而不是丢掉整个分类。
RETRIES = 4
RETRY_BACKOFF = 5.0
REQUEST_PACING = 0.8


def _with_retry(call, label):
    last = None
    for attempt in range(RETRIES):
        try:
            time.sleep(REQUEST_PACING)
            return call()
        except ValueError as exc:          # 含 JSONDecodeError：多为限流页
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
    raise ValueError(f'{label}: {last}')


def _json_get(session, path, params):
    def once():
        response = session.get(f'{NBS_API}/{path}', params=params,
                               headers=HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not payload.get('success', True):
            raise ValueError(payload.get('message') or f'国家统计局接口失败: {path}')
        return payload.get('data') or []
    return _with_retry(once, path)


def _catalogs(session):
    roots = _json_get(session, 'new/queryIndexTreeAsync', {'pid': '', 'code': NBS_ROOT_CODE})
    if not roots:
        raise ValueError('国家统计局主要城市年度数据根目录为空')
    root_id = roots[0]['_id']
    children = _json_get(
        session, 'new/queryIndexTreeAsync', {'pid': root_id, 'code': NBS_ROOT_CODE})
    return root_id, {_normal(item.get('_name')): item['_id'] for item in children}


def _indicator_ids(session, cid, requested):
    payload = _json_get(session, 'new/queryIndicatorsByCid',
                        {'cid': cid, 'dt': '', 'name': ''})
    # 此接口 data 外还有 list；兼容直接传入 list 的测试 fixture。
    if isinstance(payload, dict):
        payload = payload.get('list') or []
    selected = {}
    for item in payload:
        label = _normal(item.get('i_showname') or item.get('_name'))
        for prefix, spec in requested.items():
            if label.startswith(_normal(prefix)):
                selected[item['_id']] = spec
                break
    missing = [prefix for prefix in requested
               if not any(_normal((item.get('i_showname') or item.get('_name'))).startswith(
                   _normal(prefix)) for item in payload)]
    if missing:
        raise ValueError(f'国家统计局指标目录缺少: {", ".join(missing)}')
    return selected


def parse_nbs_periods(data, city, config, indicator_specs, category):
    """把统计局 esData 返回值转换成可审计的统一观测行。"""
    rows = []
    for period_item in data or []:
        code = str(period_item.get('code') or period_item.get('name') or '')
        match = re.search(r'(19|20)\d{2}', code)
        if not match:
            continue
        period = match.group(0)
        for value_item in period_item.get('values') or []:
            spec = indicator_specs.get(value_item.get('_id'))
            if not spec or value_item.get('value') in ('', None):
                continue
            try:
                value = float(str(value_item['value']).replace(',', ''))
            except ValueError:
                continue
            indicator_code, unit, destination = spec
            source_url = ('https://data.stats.gov.cn/easyquery.htm?cn=E0105'
                          f'&reg={config["nbs_da"][:6]}&sj={period}')
            # GDP 与一般指标都是城市口径，直辖市统一落城市码；只有财政沿用
            # 既有的省级码（与年鉴、决算那两路保持一致）。
            region_code = (config.get('gdp_region_code') or config['db_region_code']
                           if destination in ('gdp', 'indicator')
                           else config['db_region_code'])
            rows.append({
                'city': city,
                'region_code': region_code,
                'government_scope': config['scope'],
                'indicator_code': indicator_code,
                'period': period,
                'value': value,
                'unit': unit,
                'destination': destination,
                'data_status': 'official_revised',
                'source_name': NBS_SOURCE_NAME,
                'source_url': source_url,
                'source_title': f'主要城市年度数据—{category}',
                'parser_notes': ('国家统计局在线主要城市年度数据直接值；全市口径。'
                                 '该在线序列为经济普查修订后的统一口径，整段可比，'
                                 '与年鉴各年初值不同，标为 official_revised。'),
            })
    return rows


def _post_city_data(session, cid, root_id, indicator_ids, city, config,
                    start_year, end_year):
    return _with_retry(lambda: _post_once(
        session, cid, root_id, indicator_ids, city, config, start_year, end_year), city)


def _post_once(session, cid, root_id, indicator_ids, city, config,
               start_year, end_year):
    response = session.post(
        f'{NBS_API}/stream/esData',
        json={
            'cid': cid,
            'indicatorIds': list(indicator_ids),
            'daCatalogId': '',
            'das': [{'text': city, 'value': config['nbs_da']}],
            'showType': '1',
            'rootId': root_id,
            'dts': [f'{start_year}YY-{end_year}YY'],
        },
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get('success', True):
        raise ValueError(payload.get('message') or f'{city} {cid} 数据请求失败')
    return payload.get('data') or []


def fetch_nbs_city_rows(session=None, cities=None, start_year=2010, end_year=None):
    """低频抓取七个目标城市；单城/单分类失败不影响其他城市。"""
    session = session or requests.Session()
    end_year = end_year or datetime.now().year
    session.get(NBS_PAGE, headers=HEADERS, timeout=30).raise_for_status()
    root_id, catalogs = _catalogs(session)
    targets = cities or list(NBS_CITIES)
    rows, errors = [], []
    for category, requested in CATEGORY_INDICATORS.items():
        cid = catalogs.get(_normal(category))
        if not cid:
            errors.append(f'国家统计局目录缺少分类: {category}')
            continue
        try:
            specs = _indicator_ids(session, cid, requested)
        except Exception as exc:
            errors.append(f'{category} 指标目录: {exc}')
            continue
        for city in targets:
            config = NBS_CITIES.get(city)
            if not config:
                errors.append(f'{city}: 不在国家统计局主要城市年度数据覆盖范围')
                continue
            try:
                data = _post_city_data(session, cid, root_id, specs, city, config,
                                       start_year, end_year)
                rows.extend(parse_nbs_periods(data, city, config, specs, category))
            except Exception as exc:
                errors.append(f'{city} {category}: {exc}')
    return rows, errors


def ensure_city_indicator_table(conn):
    """城市年度一般指标：房地产、消费、外贸、人口、储蓄等，与 GDP/财政分表存放。

    这些指标既不是 GDP 核算项，也不是财政收支项，塞进那两张表会污染其语义；
    单独一张表，同样带 region_code/来源/口径状态，写入规则与另两张一致。
    """
    conn.execute('''CREATE TABLE IF NOT EXISTS city_indicator_observations (
      id INTEGER PRIMARY KEY, country_code TEXT NOT NULL, region_code TEXT NOT NULL,
      region_name TEXT NOT NULL, indicator_code TEXT NOT NULL, period TEXT NOT NULL,
      value REAL NOT NULL, unit TEXT NOT NULL, data_status TEXT NOT NULL,
      source_name TEXT NOT NULL, source_url TEXT, source_title TEXT,
      parser_notes TEXT, updated_at TEXT NOT NULL,
      UNIQUE(country_code, region_code, indicator_code, period))''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_city_indicator_lookup
                    ON city_indicator_observations(region_code, indicator_code, period)''')


def _ensure_gdp_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS gdp_region_observations (
      id INTEGER PRIMARY KEY, country_code TEXT, region_code TEXT, region_name TEXT,
      indicator_code TEXT, period TEXT, value REAL, unit TEXT, data_status TEXT,
      source_name TEXT, source_url TEXT, parser_notes TEXT, updated_at TEXT,
      UNIQUE(country_code, region_code, indicator_code, period))''')


def purge_misplaced_gdp(conn):
    """删除写错落点的统计局 GDP 行。

    直辖市的 GDP 落点从省级码改成了城市码；早先按省级码写入的那批若不清掉，
    省级排行的尾部就会混进修订后口径，与其余 29 个省的修订前口径不可比。
    按来源名精确定位，只删统计局主要城市这一路写的行，年鉴值不受影响。
    """
    removed = 0
    for config in NBS_CITIES.values():
        gdp_code = config.get('gdp_region_code')
        if not gdp_code or gdp_code == config['db_region_code']:
            continue
        cursor = conn.execute('''DELETE FROM gdp_region_observations
          WHERE country_code='CN' AND region_code=? AND source_name=?''',
          (config['db_region_code'], NBS_SOURCE_NAME))
        removed += cursor.rowcount or 0
    return removed


def _replace_allowed(existing_status, existing_source):
    """官方在线序列只替换镜像或自身旧抓取；城市官网已发布值保留。"""
    return existing_status == 'official_mirror' or existing_source == NBS_SOURCE_NAME


def _conflict_key(row, government_scope=''):
    return {'domain': 'city_economy', 'region_code': row['region_code'],
            'region_name': row['city'], 'government_scope': government_scope,
            'indicator_code': row['indicator_code'], 'period': row['period'],
            'candidate_source_name': NBS_SOURCE_NAME}


def _settle(conn, row, existing, government_scope, tolerance, counts):
    """保留已发布值时，把被舍弃的统计局修订值作为分歧落库；收敛则清除旧记录。

    统计局改了口径本身就是研究信息，只放在返回值里会随进程消失。
    """
    key = _conflict_key(row, government_scope)
    kept_value = existing[0]
    if kept_value and abs(row['value'] - kept_value) / abs(kept_value) > tolerance:
        difference = (row['value'] - kept_value) / kept_value
        record_conflict(conn, {
            **key, 'kept_value': kept_value, 'kept_data_status': existing[1],
            'kept_source_name': existing[2], 'candidate_value': row['value'],
            'candidate_data_status': row['data_status'],
            'candidate_source_url': row['source_url'],
            'relative_diff': round(difference, 6), 'resolution': 'kept_published',
            'note': ('城市官网已发布值优先于国家统计局在线修订值；'
                     '两者差异说明该指标发生过口径修订。'),
        })
        counts['conflicts'].append({
            'city': row['city'], 'indicator_code': row['indicator_code'],
            'period': row['period'], 'kept_value': kept_value,
            'nbs_revised_value': row['value'], 'kept_source': existing[2],
            'relative_diff': round(difference, 6),
        })
    else:
        clear_conflict(conn, key)


def store_nbs_rows(conn, rows, tolerance=0.005):
    ensure_regional_fiscal_table(conn)
    ensure_conflict_table(conn)
    _ensure_gdp_table(conn)
    ensure_city_indicator_table(conn)
    purged = purge_misplaced_gdp(conn)
    counts = {'inserted': 0, 'replaced_mirror': 0, 'refreshed': 0,
              'kept_published': 0, 'conflicts': [], 'pruned_stale_conflicts': 0,
              'purged_misplaced_gdp': purged, 'indicators': 0}
    now = datetime.now().isoformat()
    evaluated = set()
    for row in rows:
        # 一般指标表按城市+指标+年份唯一，来源只有统计局这一路，直接写入即可，
        # 不参与"保留已发布值"的优先级判定（另两表才有多来源竞争）。
        if row['destination'] == 'indicator':
            conn.execute('''INSERT INTO city_indicator_observations
              (country_code,region_code,region_name,indicator_code,period,value,unit,
               data_status,source_name,source_url,source_title,parser_notes,updated_at)
              VALUES ('CN',?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(country_code,region_code,indicator_code,period) DO UPDATE SET
                region_name=excluded.region_name,value=excluded.value,unit=excluded.unit,
                data_status=excluded.data_status,source_name=excluded.source_name,
                source_url=excluded.source_url,source_title=excluded.source_title,
                parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
              (row['region_code'], row['city'], row['indicator_code'], row['period'],
               row['value'], row['unit'], row['data_status'], row['source_name'],
               row['source_url'], row['source_title'], row['parser_notes'], now))
            counts['indicators'] += 1
            continue
        scope = '' if row['destination'] == 'gdp' else row['government_scope']
        evaluated.add((row['region_code'], scope, row['indicator_code'], row['period']))
        if row['destination'] == 'gdp':
            existing = conn.execute('''SELECT value,data_status,source_name
              FROM gdp_region_observations WHERE country_code='CN' AND region_code=?
              AND indicator_code=? AND period=?''',
              (row['region_code'], row['indicator_code'], row['period'])).fetchone()
            if existing and not _replace_allowed(existing[1], existing[2]):
                counts['kept_published'] += 1
                _settle(conn, row, existing, '', tolerance, counts)
                continue
            previous_status = existing[1] if existing else None
            # 统计局值这次被采纳，之前登记过的分歧不再成立
            clear_conflict(conn, _conflict_key(row))
            conn.execute('''INSERT INTO gdp_region_observations
              (country_code,region_code,region_name,indicator_code,period,value,unit,
               data_status,source_name,source_url,parser_notes,updated_at)
              VALUES ('CN',?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(country_code,region_code,indicator_code,period) DO UPDATE SET
                region_name=excluded.region_name,value=excluded.value,unit=excluded.unit,
                data_status=excluded.data_status,source_name=excluded.source_name,
                source_url=excluded.source_url,parser_notes=excluded.parser_notes,
                updated_at=excluded.updated_at''',
              (row['region_code'], row['city'], row['indicator_code'], row['period'],
               row['value'], row['unit'], row['data_status'], row['source_name'],
               row['source_url'], row['parser_notes'], now))
        else:
            existing = conn.execute('''SELECT value,data_status,source_name
              FROM regional_fiscal_observations WHERE country_code='CN'
              AND government_scope=? AND region_code=? AND indicator_code=? AND period=?''',
              (row['government_scope'], row['region_code'], row['indicator_code'],
               row['period'])).fetchone()
            if existing and not _replace_allowed(existing[1], existing[2]):
                counts['kept_published'] += 1
                _settle(conn, row, existing, row['government_scope'], tolerance, counts)
                continue
            previous_status = existing[1] if existing else None
            clear_conflict(conn, _conflict_key(row, row['government_scope']))
            conn.execute('''INSERT INTO regional_fiscal_observations (
              country_code,government_scope,region_code,region_name,indicator_code,period,
              value,unit,frequency,period_type,data_status,source_name,source_url,
              source_title,parser_notes,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(country_code,government_scope,region_code,indicator_code,period)
              DO UPDATE SET region_name=excluded.region_name,value=excluded.value,
                unit=excluded.unit,frequency=excluded.frequency,
                period_type=excluded.period_type,data_status=excluded.data_status,
                source_name=excluded.source_name,source_url=excluded.source_url,
                source_title=excluded.source_title,parser_notes=excluded.parser_notes,
                updated_at=excluded.updated_at''',
              ('CN', row['government_scope'], row['region_code'], row['city'],
               row['indicator_code'], row['period'], row['value'], row['unit'], 'annual',
               'calendar_year', row['data_status'], row['source_name'], row['source_url'],
               row['source_title'], row['parser_notes'], now))
        if not existing:
            counts['inserted'] += 1
        elif previous_status == 'official_mirror':
            counts['replaced_mirror'] += 1
        else:
            counts['refreshed'] += 1
    counts['pruned_stale_conflicts'] = prune_stale(
        conn, 'city_economy', NBS_SOURCE_NAME, evaluated)
    conn.commit()
    return counts


def is_fresh(db_path, max_age_days=30):
    """统计局年度序列一年只动几次，没必要每次点"更新"都重抓 7 城 × 2 分类。"""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        row = conn.execute('''SELECT MAX(updated_at) FROM gdp_region_observations
          WHERE source_name=?''', (NBS_SOURCE_NAME,)).fetchone()
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()
    if not row or not row[0]:
        return False
    try:
        age = datetime.now() - datetime.fromisoformat(row[0])
    except ValueError:
        return False
    return age.days < max_age_days


def update_city_nbs(db_path, cities=None, start_year=2010, end_year=None, session=None,
                    force=False, max_age_days=30):
    if not force and not cities and is_fresh(db_path, max_age_days):
        return {'success': True, 'skipped': 'fresh', 'records_fetched': 0,
                'note': f'国家统计局序列在 {max_age_days} 天内已抓取过；force=True 可强制重抓。',
                'source': NBS_SOURCE_NAME}
    rows, errors = fetch_nbs_city_rows(
        session=session, cities=cities, start_year=start_year, end_year=end_year)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    try:
        counts = store_nbs_rows(conn, rows)
    finally:
        conn.close()
    coverage = {}
    for row in rows:
        coverage.setdefault(row['city'], set()).add(row['period'])
    return {
        'success': bool(rows),
        'records_fetched': len(rows),
        'store': counts,
        'years_by_city': {city: sorted(years) for city, years in coverage.items()},
        'errors': errors,
        'source': NBS_SOURCE_NAME,
    }
