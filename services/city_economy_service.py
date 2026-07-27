# -*- coding: utf-8 -*-
"""城市经济聚合视图。

全部指标一律城市粒度：房价、GDP、财政都只取这座城市自己的官方值。
省级数据属于省域经济，不在本模块出现，也不做背景填充——
城市值没入库就是缺口，宁可空着，也不让读者把江苏当成南京。
直辖市例外：省级行政区本身就是这座城市，可直接作为全市口径。
"""
import sqlite3
from datetime import datetime

from services.anjuke_listing_service import build_anjuke_payload
from services.data_conflict_service import list_conflicts
from services.regional_fiscal_service import (
    build_regional_fiscal_payload,
    ensure_regional_fiscal_table,
)


CITY_CONFIG = (
    {'city': '北京', 'city_code': '110100', 'province': '北京', 'province_code': '110000', 'municipality': True},
    {'city': '上海', 'city_code': '310100', 'province': '上海', 'province_code': '310000', 'municipality': True},
    {'city': '广州', 'city_code': '440100', 'province': '广东', 'province_code': '440000', 'municipality': False},
    {'city': '深圳', 'city_code': '440300', 'province': '广东', 'province_code': '440000', 'municipality': False},
    {'city': '厦门', 'city_code': '350200', 'province': '福建', 'province_code': '350000', 'municipality': False},
    {'city': '南京', 'city_code': '320100', 'province': '江苏', 'province_code': '320000', 'municipality': False},
    {'city': '合肥', 'city_code': '340100', 'province': '安徽', 'province_code': '340000', 'municipality': False},
    {'city': '常州', 'city_code': '320400', 'province': '江苏', 'province_code': '320000', 'municipality': False},
    {'city': '苏州', 'city_code': '320500', 'province': '江苏', 'province_code': '320000', 'municipality': False},
    {'city': '无锡', 'city_code': '320200', 'province': '江苏', 'province_code': '320000', 'municipality': False},
)

HOUSING_INDICATORS = {
    'new_home_mom_idx': ('new_home_mom_pct', '新房环比'),
    'new_home_yoy_idx': ('new_home_yoy_pct', '新房同比'),
    'second_home_mom_idx': ('second_home_mom_pct', '二手房环比'),
    'second_home_yoy_idx': ('second_home_yoy_pct', '二手房同比'),
}

FISCAL_LABELS = {
    'general_budget_revenue': '一般公共预算收入',
    'general_budget_expenditure': '一般公共预算支出',
    'fiscal_balance': '一般预算收支差额',
    'tax_revenue': '税收收入',
    'tax_share': '税收占一般预算收入',
    'gov_fund_revenue': '政府性基金预算收入',
    'gov_fund_expenditure': '政府性基金预算支出',
    'land_transfer_revenue': '国有土地使用权出让收入',
    'land_dependency': '土地出让/基金收入',
    'debt_outstanding': '地方政府债务余额',
    'general_debt_outstanding': '一般债务余额',
    'special_debt_outstanding': '专项债务余额',
    'debt_to_gdp': '地方债务/GDP',
    'principal_repayment': '地方债还本',
    'interest_expenditure': '地方债付息',
    'interest_burden': '付息/一般预算收入',
}

GDP_INDICATORS = {
    'nominal_gdp': '地区 GDP',
    'primary_industry_value': '第一产业增加值',
    'secondary_industry_value': '第二产业增加值',
    'tertiary_industry_value': '第三产业增加值',
}


def _connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _latest(rows, indicator_code=None):
    candidates = [row for row in rows
                  if indicator_code is None or row.get('indicator_code') == indicator_code]
    return max(candidates, key=lambda row: row.get('period') or '') if candidates else None


def _read_official_housing(conn):
    cities = [item['city'] for item in CITY_CONFIG]
    marks = ','.join('?' for _ in cities)
    try:
        rows = conn.execute(f'''SELECT city,period,indicator_code,value,data_status,
          source_name,source_url FROM housing_city_observations
          WHERE city IN ({marks}) AND indicator_code IN
          ('new_home_mom_idx','new_home_yoy_idx','second_home_mom_idx','second_home_yoy_idx')
          ORDER BY city,period,indicator_code''', cities).fetchall()
    except sqlite3.OperationalError:
        rows = []
    result = []
    for row in rows:
        code, label = HOUSING_INDICATORS[row['indicator_code']]
        result.append({
            'city': row['city'], 'period': row['period'], 'indicator_code': code,
            'indicator_name': label, 'value': round(float(row['value']) - 100.0, 4),
            'unit': '%', 'data_status': row['data_status'],
            'geographic_scope': 'city', 'scope_label': '城市房价',
            'source_name': row['source_name'], 'source_url': row['source_url'],
            'formula': f"{row['indicator_code']} - 100",
        })
    return result


def _read_gdp_rows(conn):
    codes = sorted({item['city_code'] for item in CITY_CONFIG} |
                   {item['province_code'] for item in CITY_CONFIG})
    marks = ','.join('?' for _ in codes)
    try:
        return [dict(row) for row in conn.execute(f'''SELECT country_code,region_code,
          region_name,indicator_code,period,value,unit,data_status,source_name,source_url
          FROM gdp_region_observations WHERE country_code='CN' AND region_code IN ({marks})
          AND indicator_code IN ('nominal_gdp','primary_industry_value',
          'secondary_industry_value','tertiary_industry_value')
          ORDER BY region_code,period,indicator_code''', codes)]
    except sqlite3.OperationalError:
        return []


def _listing_rows(listing_payload):
    rows = []
    target = {item['city'] for item in CITY_CONFIG}
    for city, history in (listing_payload.get('city_history') or {}).items():
        if city not in target:
            continue
        for row in history:
            rows.append({
                'city': city, 'period': row.get('period'),
                'value': row.get('avg_price'), 'avg_price': row.get('avg_price'),
                'mom_pct': row.get('mom_pct'),
                'yoy_pct': row.get('yoy_pct'), 'unit': '元/㎡',
                'data_status': row.get('data_status') or 'listing_reference',
                'geographic_scope': 'city', 'scope_label': '城市挂牌价参考',
                'source_name': '安居客（非官方口径）', 'source_url': row.get('source_url'),
            })
    return rows


def _merge_fiscal_rows(*groups):
    """Merge fiscal rows in priority order, de-duplicating indicator-period pairs."""
    selected = {}
    for group in groups:
        for row in group:
            selected.setdefault((row['indicator_code'], row['period']), row)
    return list(selected.values())


def _vintage_note(gdp_rows):
    """按实际落库的 data_status 生成口径提示，避免写死城市名日后失真。

    统计局在线序列是经济普查修订后的口径，与《中国统计年鉴》各年初值不同，
    也与本站"中美 GDP"页的中国省级序列（修订前）不可混用。
    """
    revised = sorted({row['city'] for row in gdp_rows
                      if row.get('data_status') == 'official_revised'
                      and row.get('indicator_code') == 'nominal_gdp'})
    if not revised:
        return None
    return {
        'cities': revised,
        'text': (f'{"、".join(revised)} 的 GDP 取自国家统计局在线主要城市年度数据，'
                 '为经济普查修订后的统一口径，整段可比，但与旧版《中国统计年鉴》'
                 '各年初值不同。本站"中美 GDP"页的中国省级序列仍为年鉴修订前口径，'
                 '两者不可混用或相减；论文引用时请注明所用版本。'),
    }


def build_city_economy_payload(db_path, listing_payload=None):
    """Build a compact city selector payload without relabelling province data."""
    conn = _connect(db_path)
    try:
        ensure_regional_fiscal_table(conn)
        official_housing = _read_official_housing(conn)
        gdp_rows = _read_gdp_rows(conn)
        regional = build_regional_fiscal_payload(conn)
        conflicts = list_conflicts(conn, domain='city_economy')
    finally:
        conn.close()

    listing_payload = listing_payload if listing_payload is not None else build_anjuke_payload()
    listing = _listing_rows(listing_payload)
    target_provinces = {item['province_code'] for item in CITY_CONFIG}
    target_cities = ({item['city_code'] for item in CITY_CONFIG} |
                     {item['province_code'] for item in CITY_CONFIG
                      if item['municipality']})
    fiscal_all = [row for row in regional['rows'] if row['country_code'] == 'CN']
    province_fiscal = [row for row in fiscal_all
                       if row['region_code'] in target_provinces and
                       row['government_scope'] == 'province_total']
    province_level_fiscal = [row for row in fiscal_all
                             if row['region_code'] in target_provinces and
                             row['government_scope'] == 'province_level']
    city_fiscal = [row for row in fiscal_all
                   if row['region_code'] in target_cities and
                   row['government_scope'] in ('city_total', 'city_level')]

    city_items = []
    for config in CITY_CONFIG:
        city = config['city']
        direct_code = config['province_code'] if config['municipality'] else config['city_code']
        direct_city_fiscal = [row for row in city_fiscal
                              if row['region_code'] == direct_code]
        direct_fiscal = direct_city_fiscal
        province_rows = [row for row in province_fiscal
                         if row['region_code'] == config['province_code']]
        if config['municipality']:
            level_rows = [row for row in province_level_fiscal
                          if row['region_code'] == config['province_code']]
            direct_fiscal = _merge_fiscal_rows(
                direct_city_fiscal, province_rows, level_rows)
            fiscal_scope = 'city_total'
            fiscal_scope_label = '全市口径为主（直辖市；个别指标为市本级补充）'
        elif direct_fiscal:
            fiscal_scope = 'city_total'
            fiscal_scope_label = '城市本级/全市直接披露'
        else:
            fiscal_scope = 'missing'
            fiscal_scope_label = f'{city}市级财政官方值待入库（不以{config["province"]}省值代替）'
        # 省级不再回填:非直辖市没有城市值就是空,由页面显示缺口
        selected_fiscal = direct_fiscal

        city_gdp = [row for row in gdp_rows if row['region_code'] == config['city_code']]
        if config['municipality']:
            city_gdp = city_gdp or [row for row in gdp_rows
                                    if row['region_code'] == config['province_code']]
        selected_gdp = city_gdp
        gdp_scope = 'city_total' if city_gdp else 'missing'
        gdp_scope_label = ('城市 GDP' if gdp_scope == 'city_total'
                           else f'{city}市 GDP 官方值待入库（不以{config["province"]}省值代替）')

        city_official = [row for row in official_housing if row['city'] == city]
        city_listing = [row for row in listing if row['city'] == city]
        latest_official = _latest(city_official, 'second_home_yoy_pct')
        latest_listing = _latest(city_listing)
        latest_gdp = _latest(selected_gdp, 'nominal_gdp')
        latest_revenue = _latest(selected_fiscal, 'general_budget_revenue')
        latest_expenditure = _latest(selected_fiscal, 'general_budget_expenditure')
        latest_fund = _latest(selected_fiscal, 'gov_fund_revenue')
        latest_land = _latest(selected_fiscal, 'land_transfer_revenue')
        latest_debt = _latest(selected_fiscal, 'debt_outstanding')
        city_items.append({
            **config,
            'fiscal_scope': fiscal_scope, 'fiscal_scope_label': fiscal_scope_label,
            'gdp_scope': gdp_scope, 'gdp_scope_label': gdp_scope_label,
            'coverage': {
                'official_housing_records': len(city_official),
                'listing_records': len(city_listing), 'fiscal_records': len(selected_fiscal),
                'direct_city_fiscal_records': len(direct_fiscal), 'gdp_records': len(selected_gdp),
            },
            'latest': {
                'official_second_yoy': latest_official,
                'listing': latest_listing, 'gdp': latest_gdp,
                'general_budget_revenue': latest_revenue,
                'general_budget_expenditure': latest_expenditure,
                'gov_fund_revenue': latest_fund,
                'land_transfer_revenue': latest_land,
                'debt_outstanding': latest_debt,
            },
        })

    fiscal_rows = []
    for config in CITY_CONFIG:
        if config['municipality']:
            direct_rows = [row for row in city_fiscal
                           if row['region_code'] == config['province_code']]
            total_rows = [row for row in province_fiscal
                          if row['region_code'] == config['province_code']]
            level_rows = [row for row in province_level_fiscal
                          if row['region_code'] == config['province_code']]
            rows = _merge_fiscal_rows(direct_rows, total_rows, level_rows)
        else:
            rows = [row for row in city_fiscal if row['region_code'] == config['city_code']]
        for row in rows:
            fiscal_rows.append({**row, 'city': config['city'],
                                'geographic_scope': 'city_total',
                                'scope_label': ('市本级补充' if config['municipality'] and
                                                row['government_scope'] == 'province_level'
                                                else '全市口径（直辖市）' if config['municipality']
                                                else '市本级' if row['government_scope'] == 'city_level'
                                                else '全市口径')})

    gdp_city_rows = []
    for config in CITY_CONFIG:
        rows = [row for row in gdp_rows if row['region_code'] == config['city_code']]
        if config['municipality'] and not rows:
            rows = [row for row in gdp_rows if row['region_code'] == config['province_code']]
        for row in rows:
            gdp_city_rows.append({**row, 'city': config['city'],
                                  'geographic_scope': 'city_total', 'scope_label': '城市 GDP'})

    return {
        'generated_at': datetime.now().isoformat(), 'cities': city_items,
        'official_housing': official_housing, 'listing_housing': listing,
        'fiscal_rows': fiscal_rows, 'gdp_rows': gdp_city_rows,
        'indicator_labels': {**FISCAL_LABELS, **GDP_INDICATORS},
        # 多来源分歧：保留了城市已发布值，但统计局在线序列给出不同数字的观测。
        # 这是口径修订的证据，单列出来供人工判断，不影响上面的取值。
        'source_conflicts': conflicts,
        'vintage_note': _vintage_note(gdp_city_rows),
        'coverage': {
            'cities': len(CITY_CONFIG),
            'official_housing_cities': len({row['city'] for row in official_housing}),
            'listing_cities': len({row['city'] for row in listing}),
            'direct_city_fiscal_cities': sum(
                item['fiscal_scope'] == 'city_total' and item['coverage']['fiscal_records'] > 0
                for item in city_items),
            'city_gdp_cities': sum(item['gdp_scope'] == 'city_total' and
                                   item['coverage']['gdp_records'] > 0 for item in city_items),
            'pending_fiscal_cities': [item['city'] for item in city_items
                                      if item['fiscal_scope'] == 'missing'],
            'pending_gdp_cities': [item['city'] for item in city_items
                                   if item['gdp_scope'] == 'missing'],
        },
        'data_status': 'city_grain_only',
        'caveats': [
            '本模块所有指标均为城市粒度：房价、GDP、财政都只取该市自己的官方值。',
            '省级数据属于省域经济，不在此模块出现，也不用于填补城市缺口；城市值未入库即显示为缺失。',
            '直辖市的省级行政区即该市本身，可作为全市口径；个别仅市本级披露的指标单独标注。',
            '政府性基金和土地出让数据仅在官方决算直接披露时展示，缺失不估算、不按比例拆分。',
            '七个国家统计局主要城市使用在线年度序列补历史；official_revised 表示该在线序列可能包含历史修订。',
            '安居客为商业挂牌参考，本地独立库存储，不进入公开数据库或公开快照。',
        ],
    }
