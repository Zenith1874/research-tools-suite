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
    {'city': '武汉', 'city_code': '420100', 'province': '湖北', 'province_code': '420000', 'municipality': False},
    {'city': '长沙', 'city_code': '430100', 'province': '湖南', 'province_code': '430000', 'municipality': False},
    {'city': '成都', 'city_code': '510100', 'province': '四川', 'province_code': '510000', 'municipality': False},
    {'city': '杭州', 'city_code': '330100', 'province': '浙江', 'province_code': '330000', 'municipality': False},
    {'city': '福州', 'city_code': '350100', 'province': '福建', 'province_code': '350000', 'municipality': False},
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


INDICATOR_LABELS = {
    'residential_real_estate_investment': '住宅开发投资',
    'office_real_estate_investment': '办公楼开发投资',
    'commercial_real_estate_investment': '商业营业用房开发投资',
    'housing_under_construction_area': '房屋施工面积',
    'housing_completed_area': '房屋竣工面积',
    'residential_completed_area': '住宅竣工面积',
    'residential_avg_price': '住宅新房均价（官方）',
    'commercial_housing_avg_price': '商品房平均销售价格（官方）',
    'commercial_housing_sold_area': '商品房销售面积',
    'new_commercial_housing_filing_area': '新建商品房销售备案面积',
    'residential_housing_sold_area': '住宅商品房销售面积',
    'real_estate_investment': '房地产开发投资',
    'land_purchased_area': '房企购置土地面积',
    'land_developed_area': '房企土地开发面积',
    'retail_sales': '社会消费品零售总额',
    'trade_total': '货物进出口总额',
    'trade_total_cny': '货物进出口总额（亿元，公报口径）',
    'household_deposits': '住户存款余额',
    'registered_population': '年末户籍人口',
    'resident_population': '年末常住人口',
    'urban_new_jobs': '城镇新增就业',
    'avg_wage': '在岗职工平均工资',
    'passenger_transport_volume': '旅客运输量',
    'freight_transport_volume': '货物运输量',
    'postal_outlets': '邮政局（所）',
    'fixed_phone_subscribers': '固定电话用户',
    'college_students': '普通本专科在校生',
    'hospitals': '医院数',
    'medical_institutions': '医疗卫生机构',
    'physicians': '执业（助理）医师',
    'theaters': '剧场、影剧院数',
    'development_zone_high_tech_enterprises': '开发区高新技术企业数',
    'development_zone_high_tech_employees': '开发区高新技术企业从业人员',
    'development_zone_high_tech_output': '开发区高新技术企业总产值',
    'development_zone_high_tech_revenue': '开发区高新技术企业总收入',
    'development_zone_high_tech_exports': '开发区高新技术企业出口额',
    'traffic_noise_db': '道路交通等效声级',
    'environmental_noise_db': '环境噪声等效声级',
}


def _metric(key, label, source, unit, code=None, rate=False):
    """前后端共用的显式指标字典；不在浏览器里暗藏计算口径。"""
    return {'key': key, 'label': label, 'source': source, 'code': code or key,
            'field': 'value', 'unit': unit, 'rate': rate}


METRIC_CATALOG = (
    _metric('official_second_yoy', '官方二手房同比', 'official', '%',
            'second_home_yoy_pct', True),
    _metric('official_new_yoy', '官方新房同比', 'official', '%',
            'new_home_yoy_pct', True),
    _metric('listing_price', '安居客挂牌均价', 'listing', '元/㎡'),
    {'key': 'listing_yoy', 'label': '安居客挂牌同比', 'source': 'listing',
     'code': 'listing_yoy', 'field': 'yoy_pct', 'unit': '%', 'rate': True},
    _metric('nominal_gdp', '地区 GDP', 'gdp', '亿元'),
    _metric('nominal_gdp_yoy', '名义 GDP 同比（直除）', 'derived', '%', rate=True),
    _metric('primary_industry_value', '第一产业增加值', 'gdp', '亿元'),
    _metric('secondary_industry_value', '第二产业增加值', 'gdp', '亿元'),
    _metric('tertiary_industry_value', '第三产业增加值', 'gdp', '亿元'),
    _metric('tertiary_share', '第三产业占 GDP', 'derived', '%', rate=True),
    _metric('general_budget_revenue', '一般预算收入', 'fiscal', '亿元'),
    _metric('general_budget_expenditure', '一般预算支出', 'fiscal', '亿元'),
    _metric('fiscal_balance', '一般预算收支差额', 'fiscal', '亿元'),
    _metric('fiscal_self_sufficiency', '财政自给率（收入/支出）', 'derived', '%', rate=True),
    _metric('tax_revenue', '税收收入', 'fiscal', '亿元'),
    _metric('tax_share', '税收占一般预算收入', 'fiscal', '%', rate=True),
    _metric('gov_fund_revenue', '政府性基金收入', 'fiscal', '亿元'),
    _metric('gov_fund_expenditure', '政府性基金支出', 'fiscal', '亿元'),
    _metric('land_transfer_revenue', '卖地收入', 'fiscal', '亿元'),
    _metric('land_dependency', '卖地收入/基金收入', 'fiscal', '%', rate=True),
    _metric('debt_outstanding', '地方债余额', 'fiscal', '亿元'),
    _metric('debt_to_gdp', '地方债/GDP', 'fiscal', '%', rate=True),
    _metric('household_deposits', INDICATOR_LABELS['household_deposits'], 'indicator', '亿元'),
    _metric('registered_population', INDICATOR_LABELS['registered_population'], 'indicator', '万人'),
    _metric('resident_population', INDICATOR_LABELS['resident_population'], 'indicator', '万人'),
    _metric('urban_new_jobs', INDICATOR_LABELS['urban_new_jobs'], 'indicator', '万人'),
    _metric('avg_wage', INDICATOR_LABELS['avg_wage'], 'indicator', '元'),
    _metric('retail_sales', INDICATOR_LABELS['retail_sales'], 'indicator', '亿元'),
    _metric('trade_total', INDICATOR_LABELS['trade_total'], 'indicator', '百万美元'),
    _metric('trade_total_cny', INDICATOR_LABELS['trade_total_cny'], 'indicator', '亿元'),
    _metric('passenger_transport_volume', INDICATOR_LABELS['passenger_transport_volume'],
            'indicator', '万人'),
    _metric('freight_transport_volume', INDICATOR_LABELS['freight_transport_volume'],
            'indicator', '万吨'),
    _metric('postal_outlets', INDICATOR_LABELS['postal_outlets'], 'indicator', '处'),
    _metric('fixed_phone_subscribers', INDICATOR_LABELS['fixed_phone_subscribers'],
            'indicator', '万户'),
    _metric('college_students', INDICATOR_LABELS['college_students'], 'indicator', '万人'),
    _metric('hospitals', INDICATOR_LABELS['hospitals'], 'indicator', '个'),
    _metric('medical_institutions', INDICATOR_LABELS['medical_institutions'], 'indicator', '个'),
    _metric('physicians', INDICATOR_LABELS['physicians'], 'indicator', '万人'),
    _metric('theaters', INDICATOR_LABELS['theaters'], 'indicator', '个'),
    _metric('development_zone_high_tech_enterprises',
            INDICATOR_LABELS['development_zone_high_tech_enterprises'], 'indicator', '个'),
    _metric('development_zone_high_tech_employees',
            INDICATOR_LABELS['development_zone_high_tech_employees'], 'indicator', '人'),
    _metric('development_zone_high_tech_output',
            INDICATOR_LABELS['development_zone_high_tech_output'], 'indicator', '亿元'),
    _metric('development_zone_high_tech_revenue',
            INDICATOR_LABELS['development_zone_high_tech_revenue'], 'indicator', '亿元'),
    _metric('development_zone_high_tech_exports',
            INDICATOR_LABELS['development_zone_high_tech_exports'], 'indicator', '百万美元'),
    _metric('real_estate_investment', INDICATOR_LABELS['real_estate_investment'],
            'indicator', '亿元'),
    _metric('residential_real_estate_investment',
            INDICATOR_LABELS['residential_real_estate_investment'], 'indicator', '亿元'),
    _metric('office_real_estate_investment',
            INDICATOR_LABELS['office_real_estate_investment'], 'indicator', '亿元'),
    _metric('commercial_real_estate_investment',
            INDICATOR_LABELS['commercial_real_estate_investment'], 'indicator', '亿元'),
    _metric('real_estate_investment_to_gdp', '房地产开发投资/GDP', 'derived', '%', rate=True),
    _metric('commercial_housing_sold_area',
            INDICATOR_LABELS['commercial_housing_sold_area'], 'indicator', '万㎡'),
    _metric('new_commercial_housing_filing_area',
            INDICATOR_LABELS['new_commercial_housing_filing_area'], 'indicator', '万㎡'),
    _metric('residential_housing_sold_area',
            INDICATOR_LABELS['residential_housing_sold_area'], 'indicator', '万㎡'),
    _metric('commercial_housing_avg_price',
            INDICATOR_LABELS['commercial_housing_avg_price'], 'indicator', '元/㎡'),
    _metric('residential_avg_price', INDICATOR_LABELS['residential_avg_price'],
            'indicator', '元/㎡'),
    _metric('housing_under_construction_area',
            INDICATOR_LABELS['housing_under_construction_area'], 'indicator', '万㎡'),
    _metric('housing_completed_area', INDICATOR_LABELS['housing_completed_area'],
            'indicator', '万㎡'),
    _metric('residential_completed_area', INDICATOR_LABELS['residential_completed_area'],
            'indicator', '万㎡'),
    _metric('land_purchased_area', INDICATOR_LABELS['land_purchased_area'],
            'indicator', '万㎡'),
    _metric('land_developed_area', INDICATOR_LABELS['land_developed_area'],
            'indicator', '万㎡'),
    _metric('housing_sales_area_per_registered_person',
            '人均商品房销售面积（户籍人口）', 'derived', '㎡/人'),
    _metric('annual_wage_buyable_area', '平均年工资可购住宅面积', 'derived', '㎡'),
    _metric('physicians_per_10k_registered', '每万户籍人口医师数', 'derived', '人/万人'),
    _metric('traffic_noise_db', INDICATOR_LABELS['traffic_noise_db'], 'indicator', 'dB(A)'),
    _metric('environmental_noise_db', INDICATOR_LABELS['environmental_noise_db'],
            'indicator', 'dB(A)'),
)


CITY_ECONOMY_BOARDS = (
    {'key': 'growth', 'label': '增长总览',
     'description': '看经济总量、名义增速、消费、外贸和产业结构；名义 GDP 同比为同一修订序列直接计算。',
     'metrics': ['nominal_gdp', 'nominal_gdp_yoy', 'retail_sales', 'trade_total',
                 'trade_total_cny',
                 'primary_industry_value', 'secondary_industry_value',
                 'tertiary_industry_value', 'tertiary_share'],
     'defaults': ['nominal_gdp', 'nominal_gdp_yoy', 'retail_sales', 'tertiary_share']},
    {'key': 'people', 'label': '人口就业',
     'description': '以统计局可比的户籍人口、工资、教育和公共服务供给为主；没有常住人口时不代填。',
     'metrics': ['registered_population', 'resident_population', 'urban_new_jobs', 'avg_wage', 'college_students',
                 'passenger_transport_volume', 'hospitals', 'medical_institutions', 'physicians',
                 'physicians_per_10k_registered', 'postal_outlets',
                 'fixed_phone_subscribers'],
     'defaults': ['registered_population', 'avg_wage', 'college_students', 'physicians']},
    {'key': 'industry', 'label': '产业投资',
     'description': '分产业增加值、房地产投资、运输和开发区高新技术企业并列展示；开发区字段不冒充全市总量。',
     'metrics': ['primary_industry_value', 'secondary_industry_value',
                 'tertiary_industry_value', 'real_estate_investment',
                 'residential_real_estate_investment', 'office_real_estate_investment',
                 'commercial_real_estate_investment', 'trade_total', 'trade_total_cny',
                 'freight_transport_volume', 'development_zone_high_tech_enterprises',
                 'development_zone_high_tech_employees', 'development_zone_high_tech_output',
                 'development_zone_high_tech_revenue', 'development_zone_high_tech_exports'],
     'defaults': ['secondary_industry_value', 'tertiary_industry_value',
                  'real_estate_investment', 'freight_transport_volume']},
    {'key': 'finance', 'label': '金融财政',
     'description': '把存款、一般预算收支、税收、基金、卖地和债务放在同一板块，但各指标独立作图。',
     'metrics': ['household_deposits', 'general_budget_revenue',
                 'general_budget_expenditure', 'fiscal_balance',
                 'fiscal_self_sufficiency', 'tax_revenue', 'tax_share',
                 'gov_fund_revenue', 'gov_fund_expenditure', 'land_transfer_revenue',
                 'land_dependency', 'debt_outstanding', 'debt_to_gdp'],
     'defaults': ['household_deposits', 'general_budget_revenue',
                  'general_budget_expenditure', 'fiscal_self_sufficiency']},
    {'key': 'housing_capacity', 'label': '住房与城市承载力',
     'description': '房价、成交、开发建设、土地和医疗教育承载力分图比较；挂牌价仍是非官方本地参考。',
     'metrics': ['official_second_yoy', 'official_new_yoy', 'listing_price', 'listing_yoy',
                 'residential_avg_price', 'commercial_housing_avg_price',
                 'commercial_housing_sold_area', 'new_commercial_housing_filing_area',
                 'residential_housing_sold_area',
                 'housing_sales_area_per_registered_person', 'real_estate_investment',
                 'real_estate_investment_to_gdp', 'residential_real_estate_investment',
                 'housing_under_construction_area', 'housing_completed_area',
                 'residential_completed_area', 'land_purchased_area', 'land_developed_area',
                 'annual_wage_buyable_area', 'hospitals', 'medical_institutions',
                 'physicians', 'college_students',
                 'passenger_transport_volume', 'environmental_noise_db'],
     'defaults': ['official_second_yoy', 'residential_avg_price',
                  'commercial_housing_sold_area', 'housing_completed_area']},
)


def _read_city_indicators(conn):
    """城市年度一般指标；按城市码归到目标城市，落不到的地区直接丢弃。"""
    by_code = {item['city_code']: item['city'] for item in CITY_CONFIG}
    # 国家统计局和城市公报对北京、上海等直辖市使用省级行政区代码
    # （110000/310000），而城市级目录对普通地级市使用 110100/310100
    # 这类城市代码。两种代码都属于同一个直辖市全市口径，不能因为代码
    # 形式不同把官方人口/就业行从页面过滤掉。
    by_code.update({item['province_code']: item['city'] for item in CITY_CONFIG
                    if item['municipality']})
    marks = ','.join('?' for _ in by_code)
    try:
        rows = conn.execute(f'''SELECT region_code,region_name,indicator_code,period,value,
          unit,data_status,source_name,source_url FROM city_indicator_observations
          WHERE country_code='CN' AND region_code IN ({marks})
          ORDER BY region_code,indicator_code,period''', list(by_code)).fetchall()
    except sqlite3.OperationalError:
        return []
    result = []
    for row in rows:
        item = dict(row)
        code = item['indicator_code']
        if code.startswith('development_zone_'):
            geographic_scope, scope_label = 'city_development_zones', '开发区口径'
        elif code.endswith('_noise_db'):
            geographic_scope, scope_label = 'city_monitoring', '城市监测口径'
        else:
            geographic_scope, scope_label = 'city_total', '全市口径'
        result.append({**item, 'city': by_code[row['region_code']],
                       'indicator_name': INDICATOR_LABELS.get(code, code),
                       'geographic_scope': geographic_scope,
                       'scope_label': scope_label})
    return result


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

    数据状态保留原来源分类；不同采集版本的差异不可仅归因于经济普查。
    年鉴、初步核算与最终核实数据需逐期核对，不假定所有年鉴都是修订前。
    """
    revised = sorted({row['city'] for row in gdp_rows
                      if row.get('data_status') == 'official_revised'
                      and row.get('indicator_code') == 'nominal_gdp'})
    if not revised:
        return None
    return {
        'cities': revised,
        'text': (f'{"、".join(revised)} 的 GDP 取自国家统计局在线主要城市年度数据，'
                 '保留来源中的修订状态。各版年鉴、初步核算与最终核实值可能不同，'
                 '不能假定年鉴均为修订前，也不假定修订只能上调。未经逐期版本核对不可混用或机械相减；'
                 '论文引用时请注明地区范围、资料年和采集版本。'),
    }


def _derived_row(left, indicator_code, value, unit, formula, right=None):
    """保留输入来源与公式；派生值只进 payload，不伪装成官方观测入库。"""
    sources = []
    for row in (left, right):
        if row and row.get('source_url') and row['source_url'] not in sources:
            sources.append(row['source_url'])
    return {
        'city': left['city'], 'region_code': left.get('region_code'),
        'region_name': left.get('region_name') or left['city'],
        'indicator_code': indicator_code, 'period': left['period'],
        'value': round(float(value), 4), 'unit': unit,
        'data_status': 'derived', 'source_name': '由城市官方序列计算',
        'source_url': sources[0] if sources else None, 'source_urls': sources,
        'formula': formula, 'geographic_scope': 'city_total',
        'scope_label': '派生（城市口径）',
    }


def _build_city_derived_rows(gdp_rows, fiscal_rows, indicator_rows):
    """透明派生项：只做同城同年四则运算，缺年不桥接、缺项不估算。"""
    derived = []
    all_rows = list(gdp_rows) + list(fiscal_rows) + list(indicator_rows)
    index = {(row['city'], row['period'], row['indicator_code']): row
             for row in all_rows}

    # 名义同比必须是相邻日历年；遇到缺年直接断开。
    by_city = {}
    for row in gdp_rows:
        if row['indicator_code'] == 'nominal_gdp' and str(row['period']).isdigit():
            by_city.setdefault(row['city'], []).append(row)
    for rows in by_city.values():
        rows.sort(key=lambda row: row['period'])
        for previous, current in zip(rows, rows[1:]):
            if int(current['period']) != int(previous['period']) + 1 or not previous['value']:
                continue
            value = (current['value'] / previous['value'] - 1.0) * 100.0
            derived.append(_derived_row(
                current, 'nominal_gdp_yoy', value, '%',
                'nominal_gdp(t) / nominal_gdp(t-1) - 1；仅相邻日历年，同一修订序列',
                previous))

    ratio_specs = (
        ('tertiary_share', 'tertiary_industry_value', 'nominal_gdp', 100.0, '%',
         'tertiary_industry_value / nominal_gdp × 100'),
        ('fiscal_self_sufficiency', 'general_budget_revenue',
         'general_budget_expenditure', 100.0, '%',
         'general_budget_revenue / general_budget_expenditure × 100'),
        ('real_estate_investment_to_gdp', 'real_estate_investment',
         'nominal_gdp', 100.0, '%', 'real_estate_investment / nominal_gdp × 100'),
        # 万平方米 / 万人，数值上恰好等于平方米/人。
        ('housing_sales_area_per_registered_person', 'commercial_housing_sold_area',
         'registered_population', 1.0, '㎡/人',
         'commercial_housing_sold_area(万㎡) / registered_population(万人)'),
        ('annual_wage_buyable_area', 'avg_wage', 'residential_avg_price', 1.0, '㎡',
         'avg_wage(元/年) / residential_avg_price(元/㎡)'),
        ('physicians_per_10k_registered', 'physicians', 'registered_population',
         10000.0, '人/万人',
         'physicians(万人) / registered_population(万人) × 10000'),
    )
    for (code, left_code, right_code, multiplier, unit, formula) in ratio_specs:
        for (city, period, indicator), left in index.items():
            if indicator != left_code:
                continue
            right = index.get((city, period, right_code))
            if not right or not right.get('value'):
                continue
            derived.append(_derived_row(
                left, code, left['value'] / right['value'] * multiplier,
                unit, formula, right))
    return derived


def _metric_rows(metric, sources):
    rows = sources.get(metric['source'], [])
    if metric['source'] in ('listing',):
        return rows
    return [row for row in rows if row.get('indicator_code') == metric['code']]


def _build_metric_coverage(sources):
    """给页面一个可核查的覆盖矩阵，不把“有一条”误写成“全历史完整”。"""
    coverage = {}
    for metric in METRIC_CATALOG:
        rows = [row for row in _metric_rows(metric, sources)
                if isinstance(row.get(metric['field']), (int, float))]
        periods = sorted({row['period'] for row in rows})
        coverage[metric['key']] = {
            'records': len(rows), 'cities': len({row['city'] for row in rows}),
            'city_names': sorted({row['city'] for row in rows}),
            'start': periods[0] if periods else None,
            'end': periods[-1] if periods else None,
        }
    return coverage


def build_city_economy_payload(db_path, listing_payload=None):
    """Build a compact city selector payload without relabelling province data."""
    conn = _connect(db_path)
    try:
        ensure_regional_fiscal_table(conn)
        official_housing = _read_official_housing(conn)
        gdp_rows = _read_gdp_rows(conn)
        regional = build_regional_fiscal_payload(conn)
        indicator_rows = _read_city_indicators(conn)
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
        city_indicator = [row for row in indicator_rows if row['city'] == city]
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
                'indicator_records': len(city_indicator),
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

    derived_rows = _build_city_derived_rows(gdp_city_rows, fiscal_rows, indicator_rows)
    sources = {'official': official_housing, 'listing': listing, 'gdp': gdp_city_rows,
               'fiscal': fiscal_rows, 'indicator': indicator_rows,
               'derived': derived_rows}
    metric_coverage = _build_metric_coverage(sources)
    vintage_note = _vintage_note(gdp_city_rows)
    revised_city_count = len(vintage_note['cities']) if vintage_note else 0

    return {
        'generated_at': datetime.now().isoformat(), 'cities': city_items,
        'official_housing': official_housing, 'listing_housing': listing,
        'fiscal_rows': fiscal_rows, 'gdp_rows': gdp_city_rows,
        'indicator_rows': indicator_rows,
        'derived_rows': derived_rows,
        'metric_catalog': list(METRIC_CATALOG),
        'boards': list(CITY_ECONOMY_BOARDS),
        'metric_coverage': metric_coverage,
        'indicator_labels': {**FISCAL_LABELS, **GDP_INDICATORS, **INDICATOR_LABELS,
                             **{item['key']: item['label'] for item in METRIC_CATALOG}},
        # 多来源分歧：保留了城市已发布值，但统计局在线序列给出不同数字的观测。
        # 这是口径修订的证据，单列出来供人工判断，不影响上面的取值。
        'source_conflicts': conflicts,
        'vintage_note': vintage_note,
        'coverage': {
            'cities': len(CITY_CONFIG),
            'official_housing_cities': len({row['city'] for row in official_housing}),
            'listing_cities': len({row['city'] for row in listing}),
            'direct_city_fiscal_cities': sum(
                item['fiscal_scope'] == 'city_total' and item['coverage']['fiscal_records'] > 0
                for item in city_items),
            'city_gdp_cities': sum(item['gdp_scope'] == 'city_total' and
                                   item['coverage']['gdp_records'] > 0 for item in city_items),
            'city_indicator_cities': sum(item['coverage']['indicator_records'] > 0
                                         for item in city_items),
            'pending_fiscal_cities': [item['city'] for item in city_items
                                      if item['fiscal_scope'] == 'missing'],
            'pending_gdp_cities': [item['city'] for item in city_items
                                   if item['gdp_scope'] == 'missing'],
        },
        'data_status': 'city_grain_only',
        'caveats': [
            '本模块以城市粒度为主；开发区与城市监测口径会逐项标注，绝不冒充全市总量。',
            '省级数据属于省域经济，不在此模块出现，也不用于填补城市缺口；城市值未入库即显示为缺失。',
            '直辖市的省级行政区即该市本身，可作为全市口径；个别仅市本级披露的指标单独标注。',
            '政府性基金和土地出让数据仅在官方决算直接披露时展示，缺失不估算、不按比例拆分。',
            f'{revised_city_count} 个目标城市使用国家统计局在线年度序列补历史；official_revised 表示该在线序列可能包含历史修订。',
            '开发区高新技术企业字段只代表各市开发区口径，不代表全市全部高新技术企业。',
            '名义 GDP 同比、产业占比、财政自给率及人均项均为 derived，公式随每条数据返回；缺年不桥接。',
            '当前不生成黑箱城市综合得分；待十五城关键指标覆盖基本对齐后，再设计可拆解权重与贡献项的城市经济脉搏指数。',
            '安居客为商业挂牌参考，本地独立库存储，不进入公开数据库或公开快照。',
            '部分城市公报补充值来自第三方镜像转存的市统计局公报原件，逐格标为 official_mirror；同年已有统计局官方值时不被镜像替换。',
        ],
    }
