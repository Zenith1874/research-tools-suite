# -*- coding: utf-8 -*-
"""从城市统计公报补充主要城市目录缺口的叙述型年度指标。

国家统计局“主要城市年度数据”接口不覆盖常州、苏州、无锡。三市公报页面
通常直接给出消费、外贸、常住人口和卫生资源等总量；武汉、长沙、成都、杭州、
福州的统计局目录部分年份也会出现同类缺口。本模块只解析可由原文明确断言、
单位明确的字段，并把镜像来源标成 ``official_mirror``。不把“销售备案面积”
伪装成统计局商品房销售面积，也不把省级数据下放到城市。
"""
import re
import sqlite3
from datetime import datetime

from services.city_mirror_service import (
    MIRROR_NAME,
    discover_bulletins,
    fetch,
    plain_text,
)
from services.city_nbs_service import ensure_city_indicator_table


TARGETS = {
    '常州': '320400',
    '苏州': '320500',
    '无锡': '320200',
    # 这些城市的统计公报镜像可补充 NBS 主要城市目录没有覆盖的年份/字段。
    # 已有 official/official_revised 行由 _upsert_indicator 保护，不会被镜像替换。
    '武汉': '420100',
    '长沙': '430100',
    '成都': '510100',
    '杭州': '330100',
    '福州': '350100',
}

SOURCE_STATUS = 'official_mirror'

PATTERNS = {
    'resident_population': (
        r'年末(?:全市)?常住(?:总)?人口([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万人', '万人'),
    'registered_population': (
        r'年末(?:全市)?户籍人口(?:数)?([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万人', '万人'),
    'urban_new_jobs': (
        r'城镇新增就业([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万人', '万人'),
    'retail_sales': (
        r'社会消费品零售总额([0-9０-９,，]+(?:[.．][0-9０-９]+)?)亿元', '亿元'),
    'trade_total_cny': (
        r'(?:货物)?进出口(?:总额|总值)([0-9０-９,，]+(?:[.．][0-9０-９]+)?)亿元', '亿元'),
    'real_estate_investment': (
        r'房地产开发投资([0-9０-９,，]+(?:[.．][0-9０-９]+)?)亿元', '亿元'),
    'residential_real_estate_investment': (
        r'住宅投资([0-9０-９,，]+(?:[.．][0-9０-９]+)?)亿元', '亿元'),
    'commercial_housing_sold_area': (
        r'商品房销售面积([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万平方米', '万㎡'),
    'new_commercial_housing_filing_area': (
        r'新建商品房销售备案面积([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万平方米', '万㎡'),
    'housing_under_construction_area': (
        r'(?:房屋|商品房)施工面积([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万平方米', '万㎡'),
    'housing_completed_area': (
        r'房屋竣工面积([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万平方米', '万㎡'),
    'residential_completed_area': (
        r'住宅竣工面积([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万平方米', '万㎡'),
    'land_purchased_area': (
        r'购置土地面积([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万平方米', '万㎡'),
    'physicians': (
        r'执业[（(]助理[）)]医师([0-9０-９,，]+(?:[.．][0-9０-９]+)?)万人', '万人'),
    'hospitals': (
        r'(?:其中[，,]?|综合)医院([0-9０-９,，]+(?:[.．][0-9０-９]+)?)家', '个'),
    'medical_institutions': (
        r'医疗卫生机构([0-9０-９,，]+(?:[.．][0-９０-９]+)?)(?:家|个)', '个'),
}


def _normal(text):
    table = str.maketrans('０１２３４５６７８９．，', '0123456789.,')
    return re.sub(r'\s+', '', text or '').translate(table)


def _number(value):
    try:
        return float(value.replace(',', ''))
    except (AttributeError, TypeError, ValueError):
        return None


def parse_bulletin_indicators(text, city, period, source_url, source_title):
    """Parse only explicit levels from one bulletin body."""
    normalized = _normal(text)
    rows = []
    for code, (pattern, unit) in PATTERNS.items():
        match = re.search(pattern, normalized)
        if not match:
            continue
        value = _number(match.group(1))
        if value is None or value < 0:
            continue
        rows.append({
            'city': city,
            'region_code': TARGETS[city],
            'indicator_code': code,
            'period': str(period),
            'value': value,
            'unit': unit,
            'data_status': SOURCE_STATUS,
            'source_name': f'{city}市统计局（经{MIRROR_NAME}）',
            'source_url': source_url,
            'source_title': source_title,
            'parser_notes': (
                '三市统计公报原文经第三方镜像转存；仅取“指标名+数值+单位”'
                '的直接表述。镜像只用于本机无法稳定直连的城市，未用省级值替代。'
            ),
        })
    return rows


def collect_city_indicator_rows(city, start_year=None, end_year=None):
    """Discover and parse all available target-city bulletin years."""
    if city not in TARGETS:
        raise ValueError(f'unsupported city: {city}')
    bulletins = discover_bulletins(city)
    rows, errors = [], []
    for period, (page_url, title) in sorted(bulletins.items()):
        if start_year is not None and int(period) < int(start_year):
            continue
        if end_year is not None and int(period) > int(end_year):
            continue
        try:
            html = fetch(page_url)
            rows.extend(parse_bulletin_indicators(
                plain_text(html), city, period, page_url, title))
        except Exception as exc:
            errors.append(f'{city} {period}: {exc}')
    return rows, errors


def _upsert_indicator(conn, row, now):
    """Do not let a mirror replace an official or official-revised row."""
    existing = conn.execute('''SELECT data_status,source_name FROM city_indicator_observations
      WHERE country_code='CN' AND region_code=? AND indicator_code=? AND period=?''',
      (row['region_code'], row['indicator_code'], row['period'])).fetchone()
    if existing and existing[0] != SOURCE_STATUS and not str(existing[1]).endswith('第三方镜像）'):
        return False
    conn.execute('''INSERT INTO city_indicator_observations
      (country_code,region_code,region_name,indicator_code,period,value,unit,data_status,
       source_name,source_url,source_title,parser_notes,updated_at)
      VALUES ('CN',?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(country_code,region_code,indicator_code,period) DO UPDATE SET
        region_name=excluded.region_name,value=excluded.value,unit=excluded.unit,
        data_status=excluded.data_status,source_name=excluded.source_name,
        source_url=excluded.source_url,source_title=excluded.source_title,
        parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
      (row['region_code'], row['city'], row['indicator_code'], row['period'], row['value'],
       row['unit'], row['data_status'], row['source_name'], row['source_url'],
       row['source_title'], row['parser_notes'], now))
    return True


def update_city_bulletin_indicators(db_path, cities=None, start_year=None, end_year=None):
    """Idempotently backfill narrative indicators for configured city gaps.

    The default set is deliberately limited to the eight cities whose official
    annual directory coverage is incomplete or whose local bulletin route is
    unstable. Official rows always win over mirror rows at the same key.
    """
    targets = list(cities or TARGETS)
    all_rows, errors, years_by_city = [], [], {}
    for city in targets:
        rows, city_errors = collect_city_indicator_rows(city, start_year, end_year)
        all_rows.extend(rows)
        errors.extend(city_errors)
        years_by_city[city] = sorted({row['period'] for row in rows})

    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    inserted_or_updated = 0
    skipped_official = 0
    try:
        ensure_city_indicator_table(conn)
        now = datetime.now().isoformat()
        for row in all_rows:
            if _upsert_indicator(conn, row, now):
                inserted_or_updated += 1
            else:
                skipped_official += 1
        conn.commit()
    finally:
        conn.close()
    return {
        'success': bool(all_rows),
        'rows_parsed': len(all_rows),
        'rows_upserted': inserted_or_updated,
        'skipped_official': skipped_official,
        'years_by_city': years_by_city,
        'errors': errors,
        'source': MIRROR_NAME,
    }
