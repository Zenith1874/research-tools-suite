# -*- coding: utf-8 -*-
"""城市级官方指标采集：各市统计局《国民经济和社会发展统计公报》。

公报是各市每年发布的官方文本，直接写明本市地区生产总值与一般公共预算收支。
本模块只取这三项能被原文明确断言的数字，逐条带回原文 URL 与年份；
抽不到、或过不了校验的年份一律丢弃，不猜、不插值、不用省级数据顶替。

政府性基金收入/支出与土地出让收入不在公报口径内（属财政决算报告），
本模块不产出这些指标，页面继续显示缺口。
"""
import re
import sqlite3
from datetime import datetime
from urllib.parse import urljoin

import requests

from services.regional_fiscal_service import ensure_regional_fiscal_table, _upsert

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

# 每城的公报列表页；同城多个入口按顺序合并，去重后逐篇解析。
CITY_SOURCES = {
    '广州': {'region_code': '440100', 'indexes': [
        'http://tjj.gz.gov.cn/stats_newtjyw/tjsj/tjgb/qstjgb/index.html']},
    '深圳': {'region_code': '440300', 'indexes': [
        'http://www.sz.gov.cn/cn/xxgk/zfxxgj/tjsj/tjgb/'] + [
        f'http://www.sz.gov.cn/cn/xxgk/zfxxgj/tjsj/tjgb/index_{n}.html'
        for n in range(2, 7)]},
    '苏州': {'region_code': '320500', 'indexes': [
        'http://tjj.suzhou.gov.cn/sztjj/tjgb/nav_list.shtml'] + [
        f'http://tjj.suzhou.gov.cn/sztjj/tjgb/nav_list_{n}.shtml'
        for n in range(2, 5)]},
    '常州': {'region_code': '320400', 'indexes': [
        'https://tjj.changzhou.gov.cn/class/OEJQMFCO?pageIndex=1',
        'https://tjj.changzhou.gov.cn/class/OEJQMFCO?pageIndex=2',
        'https://tjj.changzhou.gov.cn/class/OEJQMFCO?pageIndex=3']},
}

BULLETIN_TITLE = '国民经济和社会发展统计公报'
# 公报正文里这三项都是"指标名 + 数字 + 亿元"的直陈句
# 2015 年前公报把同一指标写作"公共财政预算收入/支出"，是同口径的旧称
INDICATOR_PATTERNS = {
    # 深圳 2017 年前公报用"本市/全市生产总值"，与地区生产总值同口径
    'nominal_gdp': r'地区生产总值|(?:本市|全市)生产总值',
    'general_budget_revenue': r'(?:一般)?公共财政预算收入|一般公共预算收入',
    'general_budget_expenditure': r'(?:一般)?公共财政预算支出|一般公共预算支出',
}
# 指标名前 30 字内出现这些词就说明主语不是"全市"：
# 人均/占比是换算口径；开发区、园区、各区县是市内局部；全省是上级口径。
# 常州 2023 公报里"全市开发区完成一般公共预算收入410.8亿元"排在全市值 680.3 之前，
# 只取第一个匹配会抓错，因此既要排除局部主语，也要在合格候选里取最大值。
DISQUALIFY_BEFORE = ('人均', '占', '比重', '相当于', '折合', '开发区', '园区', '高新区',
                     '新区', '示范区', '各区', '城区', '县级', '全省', '省级', '市本级')
# 这十城任一年的总量都落在这个区间内，超出即判为抽取错误
VALUE_BOUNDS = {'nominal_gdp': (500.0, 60000.0),
                'general_budget_revenue': (50.0, 12000.0),
                'general_budget_expenditure': (50.0, 15000.0)}
MAX_YOY_JUMP = 0.40   # 相邻年份变动超过 40% 视为抽错，整条丢弃


def fetch(url, timeout=30):
    """取页面。深圳市政府门户的 https 证书链在本机握手失败，同一路径 http 正常，
    因此仅在 SSL 握手失败时回落到 http（公开统计公报，无凭据、无隐私数据）。"""
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.exceptions.SSLError:
        if not url.startswith('https://'):
            raise
        response = requests.get('http://' + url[len('https://'):],
                                headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or 'utf-8'
    return response.text


def plain_text(html):
    """去标签取正文，把全角空格和实体压平，便于用直陈句式匹配。"""
    text = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('&nbsp;', ' ').replace('　', ' ').replace('，', '，')
    return re.sub(r'\s+', ' ', text)


def find_bulletins(index_html, base_url, city):
    """从列表页取出本市公报链接：标题需同时含城市名与公报名，并带 4 位年份。"""
    found = {}
    for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                             index_html, re.S):
        title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        if BULLETIN_TITLE not in title or city not in title:
            continue
        year = re.search(r'(19|20)\d{2}', title)
        if not year:
            continue
        period = year.group(0)
        found.setdefault(period, (urljoin(base_url, match.group(1)), title))
    return found


# 里程碑说法后面跟的是整数关口，不是实际值：
# 苏州 2005 年公报写"地区生产总值突破4000亿元，达4026.52亿元"，要取后者。
MILESTONE_PREFIX = ('突破', '超过', '跃过', '接近', '逾', '约', '近')


def first_amount(window):
    """取窗口内第一个真正的"数字+亿元"，跳过里程碑关口数。"""
    for number in re.finditer(r'([\d,]+(?:\.\d+)?)\s*亿元', window):
        lead = window[max(0, number.start() - 4):number.start()]
        if any(word in lead for word in MILESTONE_PREFIX):
            continue
        try:
            return float(number.group(1).replace(',', ''))
        except ValueError:
            return None
    return None


def extract_value(text, indicator_code):
    """取指标全市总量：排除局部/换算口径后，在合格候选里取最大值。

    全市值必然不小于市内任一局部值，取最大可以兜住"局部句排在总量句之前"的排版。
    """
    pattern = INDICATOR_PATTERNS[indicator_code]
    low, high = VALUE_BOUNDS[indicator_code]
    candidates = []
    for match in re.finditer(pattern, text):
        # 只看指标名所在的那一句：跨句取词会把上一句的"占…比重"误当成本句的限定语
        before = re.split(r'[。；;！!]', text[max(0, match.start() - 40):match.start()])[-1]
        if any(word in before for word in DISQUALIFY_BEFORE):
            continue
        value = first_amount(text[match.end():match.end() + 60])
        if value is not None and low <= value <= high:
            candidates.append(round(value, 4))
    return max(candidates) if candidates else None


def parse_bulletin(html, city, period, url, title):
    """一篇公报产出 0-3 条观测；GDP 必须大于一般预算收入 3 倍才算通过。"""
    text = plain_text(html)
    values = {code: extract_value(text, code) for code in INDICATOR_PATTERNS}
    gdp, revenue = values.get('nominal_gdp'), values.get('general_budget_revenue')
    if gdp and revenue and gdp < revenue * 3:
        return []
    rows = []
    for code, value in values.items():
        if value is None:
            continue
        rows.append({'city': city, 'period': period, 'indicator_code': code,
                     'value': value, 'unit': '亿元', 'source_url': url,
                     'source_title': title})
    return rows


def drop_yoy_outliers(rows):
    """同一城市同一指标的相邻年份跳变过大 → 该年抽取不可信，整年丢弃。"""
    kept, by_key = [], {}
    for row in rows:
        by_key.setdefault((row['city'], row['indicator_code']), []).append(row)
    for series in by_key.values():
        series.sort(key=lambda r: r['period'])
        for index, row in enumerate(series):
            # 只判定两侧都有邻居的年份：首尾年只有一个邻居时，无法判断是谁不对，
            # 若那唯一的邻居本身就是异常值，会把正确的首尾年一并误杀。
            neighbours = [series[i]['value'] for i in (index - 1, index + 1)
                          if 0 <= i < len(series)]
            if len(neighbours) == 2 and all(
                    abs(row['value'] - other) / other > MAX_YOY_JUMP for other in neighbours):
                continue
            kept.append(row)
    return kept


def collect_city(city, config, limit_years=None):
    """抓一个城市的全部公报，返回 (观测行, 错误列表)。"""
    bulletins, errors = {}, []
    for index_url in config['indexes']:
        try:
            bulletins.update({k: v for k, v in
                              find_bulletins(fetch(index_url), index_url, city).items()
                              if k not in bulletins})
        except Exception as exc:
            errors.append(f'{city} 列表页 {index_url}: {exc}')
    rows = []
    for period, (url, title) in sorted(bulletins.items()):
        if limit_years and period not in limit_years:
            continue
        try:
            rows.extend(parse_bulletin(fetch(url), city, period, url, title))
        except Exception as exc:
            errors.append(f'{city} {period} 公报: {exc}')
    return drop_yoy_outliers(rows), errors


def store_rows(conn, rows):
    """GDP 进 gdp_region_observations，财政进 regional_fiscal_observations(city_total)。"""
    ensure_regional_fiscal_table(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS gdp_region_observations (
      id INTEGER PRIMARY KEY, country_code TEXT, region_code TEXT, region_name TEXT,
      indicator_code TEXT, period TEXT, value REAL, unit TEXT, data_status TEXT,
      source_name TEXT, source_url TEXT, parser_notes TEXT, updated_at TEXT,
      UNIQUE(country_code, region_code, indicator_code, period))''')
    now = datetime.now().isoformat()
    counts = {'gdp': 0, 'fiscal': 0}
    for row in rows:
        city = row['city']
        region_code = CITY_SOURCES[city]['region_code']
        notes = f"{city}市统计局《{row['source_title']}》原文直接值；全市口径、当年价。"
        # 早年公报常以整数关口表述（如苏州 2011"达到10500亿元"），如实标注
        if row['value'] >= 1000 and float(row['value']).is_integer():
            notes += '公报原文即为整数表述，未提供小数位。'
        if row['indicator_code'] == 'nominal_gdp':
            conn.execute('''INSERT INTO gdp_region_observations
              (country_code,region_code,region_name,indicator_code,period,value,unit,
               data_status,source_name,source_url,parser_notes,updated_at)
              VALUES ('CN',?,?,?,?,?,?,'official',?,?,?,?)
              ON CONFLICT(country_code,region_code,indicator_code,period)
              DO UPDATE SET value=excluded.value,source_url=excluded.source_url,
                            parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
              (region_code, city, 'nominal_gdp', row['period'], row['value'], '亿元',
               f'{city}市统计局', row['source_url'], notes, now))
            counts['gdp'] += 1
        else:
            _upsert(conn, {
                'country_code': 'CN', 'government_scope': 'city_total',
                'region_code': region_code, 'region_name': city,
                'indicator_code': row['indicator_code'], 'period': row['period'],
                'value': row['value'], 'unit': '亿元', 'frequency': 'annual',
                'period_type': 'calendar_year', 'source_name': f'{city}市统计局',
                'source_url': row['source_url'], 'source_title': row['source_title'],
                'parser_notes': notes})
            counts['fiscal'] += 1
    conn.commit()
    return counts


def update_city_official(db_path, cities=None):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    try:
        all_rows, errors, per_city = [], [], {}
        for city, config in CITY_SOURCES.items():
            if cities and city not in cities:
                continue
            rows, city_errors = collect_city(city, config)
            all_rows.extend(rows)
            errors.extend(city_errors)
            per_city[city] = sorted({row['period'] for row in rows})
        counts = store_rows(conn, all_rows)
    finally:
        conn.close()
    return {'success': bool(all_rows), 'records': counts,
            'years_by_city': per_city, 'errors': errors}
