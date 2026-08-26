# -*- coding: utf-8 -*-
"""统一中国宏观数据页的只读 payload 与组合更新入口。"""
from __future__ import annotations

import math
from contextlib import closing
from datetime import datetime

from services.china_external_service import EXTERNAL_INDICATORS, update_china_external
from services.china_macro_service import (
    INDICATORS, connect, ensure_china_macro_tables, update_china_macro,
)
from services.china_demography_service import update_china_demography


DERIVED_META = {
    'CN_POPULATION_YOY_DERIVED': ('年末全国人口同比', '%', 'annual'),
    'CN_EMPLOYED_YOY_DERIVED': ('全国就业人员同比', '%', 'annual'),
    'CN_DISPOSABLE_INCOME_YOY_DERIVED': ('居民人均可支配收入名义同比', '%', 'annual'),
    'CN_BIRTHS_ESTIMATED': ('出生人口历史估算（率×人口）', '万人', 'annual'),
    'CN_DIVORCES_TOTAL_DERIVED': ('离婚合计（协议+法院）', '万对', 'annual'),
    'CN_DIVORCE_MARRIAGE_RATIO_DERIVED': ('当年离婚/结婚登记比（流量比）', '%', 'annual'),
}


def _chart(code, title, series, unit, subtitle='', threshold=None, currency=False,
           note=''):
    return {
        'code': code, 'title': title, 'series': list(series), 'unit': unit,
        'subtitle': subtitle, 'threshold': threshold,
        'currency_switch': bool(currency), 'note': note,
    }


def _evidence_tier(row):
    """Return a user-facing evidence label without upgrading a relayed source."""
    status = (row.get('data_status') or '').strip()
    return {
        'official': '一手官方',
        'official_revised': '一手官方·修订',
        'official_reprinted': '官方表重刊',
        'official_relayed': '官方数据转引',
        'derived': '派生',
    }.get(status, '未分类')


def _release_date_missing(row):
    """Backfill a display-only missingness flag for older demography rows."""
    if row.get('release_date'):
        return 0
    if row.get('source_type') == 'china_demography':
        return 1
    if row.get('release_date_not_provided') is not None:
        return int(row.get('release_date_not_provided') or 0)
    return None


def _release_date_reason(row):
    if row.get('release_date_reason'):
        return row.get('release_date_reason')
    if _release_date_missing(row) == 1:
        return '人口婚姻家庭 CSV 未提供逐行来源发布日期'
    return None


GROUPS = [
    {
        'code': 'growth', 'title': '增长与生产',
        'description': 'GDP、工业生产和主要工业品；金额、产量与增速分图展示。',
        'charts': [
            _chart('growth_rates', 'GDP 与工业增加值实际增速',
                   ('CN_GDP_Q_REAL_YOY', 'CN_IP_YOY'), '%',
                   '季度 GDP 与月度工业增加值均为实际同比，频率不同。'),
            _chart('ip_cumulative', '规模以上工业增加值累计同比',
                   ('CN_IP_YTD_YOY',), '%'),
            _chart('commodity_yoy', '主要工业品当月产量同比',
                   ('CN_COAL_OUTPUT_MONTH_YOY', 'CN_CRUDE_OIL_OUTPUT_MONTH_YOY',
                    'CN_NATGAS_OUTPUT_MONTH_YOY', 'CN_CRUDE_STEEL_OUTPUT_MONTH_YOY',
                    'CN_POWER_OUTPUT_MONTH_YOY'), '%'),
            _chart('auto_output_yoy', '汽车与新能源汽车产量当月同比',
                   ('CN_AUTO_OUTPUT_MONTH_YOY', 'CN_NEV_OUTPUT_MONTH_YOY'), '%'),
            _chart('power_output_month', '规模以上工业发电量当月',
                   ('CN_POWER_OUTPUT_MONTH',), '亿千瓦时'),
            _chart('power_output_ytd', '规模以上工业发电量累计',
                   ('CN_POWER_OUTPUT_YTD',), '亿千瓦时'),
        ],
    },
    {
        'code': 'demand', 'title': '消费与投资',
        'description': '社会消费、汽车消费和固定资产投资；累计指标不与当月指标混轴。',
        'charts': [
            _chart('retail_month_amount', '社会消费品零售额当月',
                   ('CN_RETAIL_MONTH', 'CN_RETAIL_EX_AUTO_MONTH'), '亿元'),
            _chart('retail_ytd_amount', '社会消费品零售额累计',
                   ('CN_RETAIL_YTD', 'CN_RETAIL_EX_AUTO_YTD',
                    'CN_RETAIL_ONLINE_GOODS_YTD'), '亿元'),
            _chart('retail_month_yoy', '消费当月同比',
                   ('CN_RETAIL_YOY', 'CN_RETAIL_EX_AUTO_MONTH_YOY',
                    'CN_AUTO_RETAIL_MONTH_YOY'), '%',
                   note='汽车类为限额以上单位口径，不等于全部汽车消费。'),
            _chart('auto_retail_month', '限额以上单位汽车类零售额当月',
                   ('CN_AUTO_RETAIL_MONTH',), '亿元',
                   note='该口径不是全社会汽车销售额。'),
            _chart('auto_retail_ytd', '限额以上单位汽车类零售额累计',
                   ('CN_AUTO_RETAIL_YTD',), '亿元',
                   note='该口径不是全社会汽车销售额。'),
            _chart('fai_amount', '固定资产投资累计额', ('CN_FAI_YTD',), '亿元'),
            _chart('fai_rates', '固定资产投资累计同比',
                   ('CN_FAI_YTD_YOY', 'CN_FAI_PRIVATE_YTD_YOY',
                    'CN_FAI_MANUFACTURING_YTD_YOY', 'CN_FAI_INFRA_YTD_YOY'), '%'),
            _chart('income', '居民人均可支配收入',
                   ('CN_DISPOSABLE_INCOME',), '元/人'),
        ],
    },
    {
        'code': 'prices', 'title': '价格与景气',
        'description': '消费端、生产端通胀和采购经理景气度；PMI 50 为荣枯线。',
        'charts': [
            _chart('inflation', 'CPI、PPI 与工业购进价格同比',
                   ('CN_CPI_YOY', 'CN_PPI_YOY', 'CN_PPIRM_YOY'), '%'),
            _chart('ppi_structure', '生产资料与生活资料出厂价格同比',
                   ('CN_PPI_PRODUCTION_YOY', 'CN_PPI_LIVING_YOY'), '%'),
            _chart('pmi', '采购经理指数',
                   ('CN_PMI_MFG', 'CN_PMI_NONMFG', 'CN_PMI_COMP'), '%',
                   threshold=50, note='50以上通常表示环比扩张，50以下通常表示环比收缩。'),
        ],
    },
    {
        'code': 'employment', 'title': '就业与收入',
        'description': '月度调查失业率与年度就业、收入；年度同比只按相邻年份计算。',
        'charts': [
            _chart('unemployment', '全国城镇调查失业率', ('CN_UNEMP_SURVEY',), '%'),
            _chart('employment', '全国就业人员',
                   ('CN_EMPLOYED', 'CN_URBAN_EMPLOYED', 'CN_LABOR_FORCE'), '万人'),
            _chart('employment_growth', '就业与收入年度同比',
                   ('CN_EMPLOYED_YOY_DERIVED',
                    'CN_DISPOSABLE_INCOME_YOY_DERIVED'), '%'),
            _chart('employment_flows', '城镇新增就业', ('CN_URBAN_NEW_JOBS',), '万人'),
        ],
    },
    {
        'code': 'demography', 'title': '人口与家庭',
        'description': '人口规模、人口流量、婚姻家庭和年龄结构；万人、万对与‰严格分开。',
        'charts': [
            _chart('population', '全国人口', ('CN_POPULATION',), '万人'),
            _chart('population_growth', '人口年度同比',
                   ('CN_POPULATION_YOY_DERIVED',), '%'),
            _chart('population_flows', '出生与死亡', ('CN_BIRTHS', 'CN_DEATHS'), '万人'),
            _chart('birth_history', '出生人口：官方绝对数与历史估算',
                   ('CN_BIRTHS', 'CN_BIRTHS_ESTIMATED'), '万人',
                   note='官方绝对数与历史估算分线显示；估算=人口出生率×上年末与本年末人口均值÷1000，不替代官方绝对数。'),
            _chart('family_flows', '结婚与离婚合计',
                   ('CN_MARRIAGES', 'CN_DIVORCES_TOTAL_DERIVED'), '万对',
                   subtitle='结婚和离婚均按夫妻对数保存，单位统一为万对；不乘二，也不与出生人数混图。'),
            _chart('divorce_routes', '协议离婚与法院判决/调解离婚',
                   ('CN_DIVORCES_AGREEMENT', 'CN_DIVORCES_COURT',
                    'CN_DIVORCES_TOTAL_DERIVED'), '万对',
                   note='协议离婚对应民政部门登记；法院序列对应法院判决/调解；合计仅在两项同时有值时派生。'),
            _chart('divorce_marriage_ratio', '当年离婚占结婚比例（流量比）',
                   ('CN_DIVORCE_MARRIAGE_RATIO_DERIVED',), '%',
                   note='年度流量比=当年离婚合计÷当年结婚登记×100%；离婚事件可能对应往年婚姻，不是同一婚姻队列的离婚概率。'),
            _chart('population_rates', '出生率、死亡率与自然增长率',
                   ('CN_BIRTH_RATE', 'CN_DEATH_RATE', 'CN_NATURAL_GROWTH_RATE'), '‰',
                   note='国家统计局年鉴率序列；与出生/死亡人数不是同一指标，单位为‰。'),
            _chart('population_age', '15—64岁劳动年龄人口（年鉴口径）',
                   ('CN_WORKING_AGE_15_64',), '万人',
                   note='年鉴15—64岁定义；与公报16—59岁序列不能直接拼接。'),
            _chart('population_age_16_59', '16—59岁人口（公报口径）',
                   ('CN_WORKING_AGE_POP',), '万人',
                   note='目前统一公报口径从2025年开始；不向前推算、不与15—64岁序列混合。'),
        ],
    },
    {
        'code': 'trade', 'title': '外贸',
        'description': '海关总署人民币/美元原始口径；当月、累计和同比严格分开。',
        'charts': [
            _chart('trade_month_amount', '进出口当月金额',
                   ('CN_GACC_TRADE_{currency}_MONTH', 'CN_GACC_EXPORT_{currency}_MONTH',
                    'CN_GACC_IMPORT_{currency}_MONTH'), '{currency_unit}', currency=True),
            _chart('trade_ytd_amount', '进出口累计金额',
                   ('CN_GACC_TRADE_{currency}_YTD', 'CN_GACC_EXPORT_{currency}_YTD',
                    'CN_GACC_IMPORT_{currency}_YTD'), '{currency_unit}', currency=True),
            _chart('trade_month_yoy', '进出口当月同比',
                   ('CN_GACC_TRADE_{currency}_MONTH_YOY',
                    'CN_GACC_EXPORT_{currency}_MONTH_YOY',
                    'CN_GACC_IMPORT_{currency}_MONTH_YOY'), '%', currency=True),
            _chart('trade_balance', '货物贸易差额',
                   ('CN_GACC_BALANCE_{currency}_MONTH',), '{currency_unit}', currency=True),
        ],
    },
    {
        'code': 'capital', 'title': '外资与跨境资金',
        'description': '商务部投资统计与外汇局资金流并列；三种统计概念不互相替代。',
        'charts': [
            _chart('fdi_odi', '实际使用外资与非金融类对外投资累计',
                   ('CN_MOFCOM_FDI_{currency}_YTD',
                    'CN_MOFCOM_ODI_NONFIN_{currency}_YTD'), '{currency_unit}', currency=True,
                   note='FDI 与非金融 ODI 统计范围不同，仅作规模并列，不计算净额。'),
            _chart('fdi_odi_yoy', '实际使用外资与非金融类对外投资累计同比',
                   ('CN_MOFCOM_FDI_{currency}_YTD_YOY',
                    'CN_MOFCOM_ODI_NONFIN_{currency}_YTD_YOY'), '%', currency=True),
            _chart('safe_fx_gross', '银行结汇与售汇当月',
                   ('CN_SAFE_FX_SETTLEMENT_{currency}', 'CN_SAFE_FX_SALES_{currency}'),
                   '{currency_unit}', currency=True),
            _chart('safe_fx_net', '银行结售汇差额当月',
                   ('CN_SAFE_FX_NET_{currency}',), '{currency_unit}', currency=True),
            _chart('safe_xb_gross', '银行代客涉外收入与支出当月',
                   ('CN_SAFE_XB_RECEIPTS_{currency}', 'CN_SAFE_XB_PAYMENTS_{currency}'),
                   '{currency_unit}', currency=True),
            _chart('safe_xb_net', '银行代客涉外收支差额当月',
                   ('CN_SAFE_XB_NET_{currency}',), '{currency_unit}', currency=True),
            _chart('safe_di', '银行代客直接投资项收支当月',
                   ('CN_SAFE_DI_RECEIPTS_{currency}', 'CN_SAFE_DI_PAYMENTS_{currency}'),
                   '{currency_unit}', currency=True,
                   note='这是外汇局银行代客涉外收付款的直接投资项，不等同于商务部实际使用外资。'),
            _chart('safe_di_net', '银行代客直接投资项差额当月',
                   ('CN_SAFE_DI_NET_{currency}',), '{currency_unit}', currency=True),
            _chart('safe_official_reserves', 'SAFE 官方储备资产',
                   ('CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD',
                    'CN_SAFE_FX_RESERVES_USD', 'CN_SAFE_MONETARY_GOLD_USD'), '亿美元',
                   note='这是 SAFE 官方储备资产表；不等同于 PBoC 资产负债表 foreign_exchange，亦不等同于结售汇或涉外收付款。'),
            _chart('safe_gold_quantity', 'SAFE 官方黄金数量',
                   ('CN_SAFE_MONETARY_GOLD_QUANTITY',), '万盎司',
                   note='黄金数量与黄金美元金额分开保存，不做跨单位相加。'),
        ],
    },
]


def _annual_yoy(rows, code, name):
    output = []
    for previous, current in zip(rows, rows[1:]):
        try:
            y0, y1 = int(previous['period'][:4]), int(current['period'][:4])
            v0, v1 = float(previous['value']), float(current['value'])
        except (TypeError, ValueError, KeyError):
            continue
        if y1 != y0 + 1 or v0 == 0 or not all(math.isfinite(v) for v in (v0, v1)):
            continue
        output.append({
            'period': current['period'], 'value': (v1 / v0 - 1.0) * 100.0,
            'unit': '%', 'frequency': 'annual', 'data_status': 'derived',
            'source_name': current.get('source_name'),
            'source_url': current.get('source_url'),
            'source_title': current.get('source_title'),
            'parser_notes': '仅相邻年度绝对值直除，不跨缺年',
            'formula': f'{name}同比=(本年/上年-1)×100%',
            'indicator_code': code, 'indicator_name': DERIVED_META[code][0],
        })
    return output


def _annual_births_estimate(rate_rows, population_rows):
    """用官方出生率与年末人口构造可追溯的历史估算线。

    出生率是每千人出生数，人口表是年末人口（万人）。这里用上年末与
    本年末人口的均值近似年中人口，因此结果明确标为 ``derived``，不与
    国家统计局直接公布的出生人口绝对数混为一条官方序列。
    """
    rates = {row.get('period'): row for row in rate_rows or []}
    population = {row.get('period'): row for row in population_rows or []}
    output = []
    for period in sorted(rates):
        try:
            year = int(str(period)[:4])
            rate = float(rates[period]['value'])
            previous_population = float(population[str(year - 1)]['value'])
            current_population = float(population[str(year)]['value'])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in
                   (rate, previous_population, current_population)):
            continue
        if rate < 0 or previous_population <= 0 or current_population <= 0:
            continue
        value = rate * (previous_population + current_population) / 2.0 / 1000.0
        output.append({
            'period': period, 'value': value, 'unit': '万人', 'frequency': 'annual',
            'data_status': 'derived',
            'source_name': '国家统计局出生率+年末人口（派生）',
            'source_url': None,
            'source_title': '出生人口历史估算序列',
            'parser_notes': (
                '估算=人口出生率（‰）×（上年末人口+本年末人口）÷2÷1000；'
                '年中人口采用两期年末人口均值近似；不替代官方绝对数'),
            'formula': '出生人口估算=出生率×（上年末人口+本年末人口）÷2÷1000',
            'indicator_code': 'CN_BIRTHS_ESTIMATED',
            'indicator_name': DERIVED_META['CN_BIRTHS_ESTIMATED'][0],
            'release_date_not_provided': 1,
            'release_date_reason': '派生序列没有单一来源发布日期',
        })
    return output


def _annual_divorce_total(agreement_rows, court_rows):
    """协议离婚与法院离婚按年相加；任一分项缺失则合计保持缺失。"""
    agreement = {row.get('period'): row for row in agreement_rows or []}
    court = {row.get('period'): row for row in court_rows or []}
    output = []
    for period in sorted(set(agreement) & set(court)):
        left, right = agreement[period], court[period]
        try:
            value = float(left['value']) + float(right['value'])
        except (TypeError, ValueError, KeyError):
            continue
        if not math.isfinite(value):
            continue
        output.append({
            'period': period, 'value': value, 'unit': '万对', 'frequency': 'annual',
            'data_status': 'derived',
            'source_name': '协议离婚+法院离婚（派生）',
            # 采用协议分项来源作为可点击入口；数据库中两项原始来源均保留。
            'source_url': left.get('source_url'),
            'source_title': '离婚合计派生序列',
            'parser_notes': '仅在协议离婚与法院判决/调解离婚同年均有值时相加；分项四舍五入可能造成与官方总计0.1万对差异',
            'formula': '离婚合计=协议离婚（民政登记）+法院判决/调解离婚',
            'indicator_code': 'CN_DIVORCES_TOTAL_DERIVED',
            'indicator_name': DERIVED_META['CN_DIVORCES_TOTAL_DERIVED'][0],
        })
    return output


def _annual_divorce_marriage_ratio(marriage_rows, divorce_total_rows):
    """计算同年离婚合计占结婚登记的比例，不跨缺失年份补齐。"""
    marriages = {row.get('period'): row for row in marriage_rows or []}
    divorces = {row.get('period'): row for row in divorce_total_rows or []}
    output = []
    for period in sorted(set(marriages) & set(divorces)):
        marriage = marriages[period]
        divorce = divorces[period]
        try:
            marriage_value = float(marriage['value'])
            divorce_value = float(divorce['value'])
        except (TypeError, ValueError, KeyError):
            continue
        if (not math.isfinite(marriage_value) or not math.isfinite(divorce_value)
                or marriage_value <= 0):
            continue
        output.append({
            'period': period,
            'value': divorce_value / marriage_value * 100.0,
            'unit': '%',
            'frequency': 'annual',
            'data_status': 'derived',
            'source_name': '离婚合计÷结婚登记（派生）',
            # 这是两个年度序列的组合，不把其中任一来源冒充为完整来源。
            'source_url': None,
            'source_title': '年度离婚/结婚登记比派生序列',
            'parser_notes': '同年离婚合计除以同年结婚登记；这是年度流量比，不是同一婚姻队列的离婚概率或官方人口学离婚率',
            'formula': '当年离婚/结婚登记比=当年离婚合计÷当年结婚登记×100%',
            'indicator_code': 'CN_DIVORCE_MARRIAGE_RATIO_DERIVED',
            'indicator_name': DERIVED_META['CN_DIVORCE_MARRIAGE_RATIO_DERIVED'][0],
            'release_date_not_provided': 1,
            'release_date_reason': '派生序列没有单一来源发布日期',
        })
    return output


def _card(code, series, metrics):
    rows = series.get(code) or []
    meta = metrics.get(code) or {}
    if not rows:
        return {'code': code, 'label': meta.get('name') or code, 'value': None,
                'period': None, 'unit': meta.get('unit'), 'data_status': 'missing',
                'evidence_tier': '缺失', 'release_date': None, 'retrieved_at': None,
                'release_date_not_provided': None, 'release_date_reason': None}
    row = rows[-1]
    return {
        'code': code, 'label': meta.get('name') or row.get('indicator_name') or code,
        'value': row.get('value'), 'period': row.get('period'),
        'unit': row.get('unit') or meta.get('unit'),
        'data_status': row.get('data_status'), 'source_name': row.get('source_name'),
        'source_url': row.get('source_url'),
        'source_title': row.get('source_title'),
        'evidence_tier': _evidence_tier(row),
        'release_date': row.get('release_date'),
        'retrieved_at': row.get('retrieved_at'),
        'release_date_not_provided': _release_date_missing(row),
        'release_date_reason': _release_date_reason(row),
    }


def build_china_macro_payload(db_path):
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        raw_rows = [dict(row) for row in conn.execute('''
            SELECT indicator_code,indicator_name,period,value,unit,frequency,data_status,
                   source_name,source_type,source_url,source_title,parser_notes,formula,
                   updated_at,release_date,retrieved_at,release_date_not_provided,
                   release_date_reason
            FROM china_macro_observations ORDER BY indicator_code,period''')]
    series = {}
    for row in raw_rows:
        if row.get('value') is None:
            continue
        series.setdefault(row['indicator_code'], []).append(row)

    derived_specs = (
        ('CN_POPULATION', 'CN_POPULATION_YOY_DERIVED', '年末全国人口'),
        ('CN_EMPLOYED', 'CN_EMPLOYED_YOY_DERIVED', '全国就业人员'),
        ('CN_DISPOSABLE_INCOME', 'CN_DISPOSABLE_INCOME_YOY_DERIVED', '居民人均可支配收入'),
    )
    for source_code, derived_code, name in derived_specs:
        series[derived_code] = _annual_yoy(series.get(source_code) or [], derived_code, name)
    series['CN_BIRTHS_ESTIMATED'] = _annual_births_estimate(
        series.get('CN_BIRTH_RATE') or [], series.get('CN_POPULATION') or [])
    series['CN_DIVORCES_TOTAL_DERIVED'] = _annual_divorce_total(
        series.get('CN_DIVORCES_AGREEMENT') or [],
        series.get('CN_DIVORCES_COURT') or [],
    )
    series['CN_DIVORCE_MARRIAGE_RATIO_DERIVED'] = _annual_divorce_marriage_ratio(
        series.get('CN_MARRIAGES') or [],
        series.get('CN_DIVORCES_TOTAL_DERIVED') or [],
    )

    all_meta = {**INDICATORS, **EXTERNAL_INDICATORS, **DERIVED_META}
    metrics = {}
    coverage = []
    for code, values in series.items():
        meta = all_meta.get(code) or (
            values[-1].get('indicator_name') or code,
            values[-1].get('unit'), values[-1].get('frequency'))
        metrics[code] = {'name': meta[0], 'unit': meta[1], 'frequency': meta[2]}
        if values:
            coverage.append({
                'code': code, 'name': meta[0], 'unit': meta[1], 'frequency': meta[2],
                'n_obs': len(values), 'start_period': values[0]['period'],
                'end_period': values[-1]['period'],
                'latest_status': values[-1].get('data_status'),
                'latest_source_tier': _evidence_tier(values[-1]),
                'source_name': values[-1].get('source_name'),
                'source_url': values[-1].get('source_url'),
                'source_title': values[-1].get('source_title'),
                'latest_release_date': values[-1].get('release_date'),
                'latest_retrieved_at': values[-1].get('retrieved_at'),
                'latest_release_date_not_provided': _release_date_missing(values[-1]),
                'latest_release_date_reason': _release_date_reason(values[-1]),
            })
    coverage.sort(key=lambda item: (item['name'], item['code']))

    card_codes = (
        'CN_GDP_Q_REAL_YOY', 'CN_IP_YOY', 'CN_RETAIL_YOY', 'CN_FAI_YTD_YOY',
        'CN_CPI_YOY', 'CN_PMI_MFG', 'CN_UNEMP_SURVEY',
        'CN_GACC_EXPORT_CNY_MONTH_YOY', 'CN_MOFCOM_FDI_CNY_YTD_YOY',
        'CN_SAFE_XB_NET_CNY', 'CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD',
        'CN_BIRTHS', 'CN_MARRIAGES', 'CN_DIVORCES_TOTAL_DERIVED',
    )
    warnings = [
        '人民币和美元均保存官方原币值，系统不以汇率反推缺失币种。',
        '当月、累计、绝对量和同比不会放在同一坐标轴；1—2月合并发布保持2月期点。',
        '商务部实际使用外资、对外直接投资与外汇局跨境收付款是不同统计体系，不计算伪“净外资”。',
        'SAFE 官方储备资产、PBoC 资产负债表 foreign_exchange、银行结售汇和涉外收付款是四个不同口径；页面不互相替代。',
        '汽车类零售额为限额以上单位口径；主要工业品产量只代表规模以上工业。',
        '出生人口单位为万人；结婚和离婚官方公布的是万对（夫妻对数），不将对数乘二后冒充人数。',
        '协议离婚对应民政部门登记，法院离婚对应法院判决/调解；离婚合计只在两项同年均有值时相加。',
        '年度离婚/结婚登记比=同年离婚合计÷同年结婚登记×100%，是年度流量比；离婚事件可能对应往年婚姻，不表示当年结婚者的离婚概率。',
        '出生绝对数采用年度公报/普查快照，出生率采用年鉴率序列；官方绝对数与历史估算分线显示，不把估算伪装成官方数。',
        '人口婚姻家庭数据来自仓库内经核验整理快照；一手官方、修订、重刊、转引和派生状态逐序列标注，来源发布日期未提供时保持空缺。',
    ]
    births = series.get('CN_BIRTHS') or []
    births_estimated = series.get('CN_BIRTHS_ESTIMATED') or []
    court = series.get('CN_DIVORCES_COURT') or []
    if births:
        warnings.append(
            f"出生人数官方绝对数的连续快照覆盖{births[0]['period']}—{births[-1]['period']}。")
    if births_estimated:
        warnings.append(
            f"出生人口历史估算覆盖{births_estimated[0]['period']}—{births_estimated[-1]['period']}；"
            '由官方出生率与年末人口均值派生，仅用于历史趋势和情景输入，不替代官方绝对数。')
    if court and court[-1].get('period') < '2025':
        warnings.append(
            '2025年公开民政数据给出离婚登记274.3万对，但尚未提供全国法院分项；'
            '因此2025年法律离婚合计留空，不把274.3误标为合计。')
    ratio = series.get('CN_DIVORCE_MARRIAGE_RATIO_DERIVED') or []
    marriages = series.get('CN_MARRIAGES') or []
    if ratio and marriages and ratio[-1].get('period') < marriages[-1].get('period'):
        warnings.append(
            f"年度离婚/结婚登记流量比目前覆盖{ratio[0]['period']}—{ratio[-1]['period']}；"
            '由于2025年法院离婚分项缺失，2025年不生成该比例。')
    cny_fdi = series.get('CN_MOFCOM_FDI_CNY_YTD') or []
    usd_fdi = series.get('CN_MOFCOM_FDI_USD_YTD') or []
    if cny_fdi and (not usd_fdi or usd_fdi[-1]['period'] < cny_fdi[-1]['period']):
        warnings.append(
            f"商务部美元实际使用外资序列最新为{usd_fdi[-1]['period'] if usd_fdi else '缺失'}，"
            f"人民币序列已到{cny_fdi[-1]['period']}；页面如实断线，不做汇率换算。")
    updated_values = [row.get('updated_at') for row in raw_rows if row.get('updated_at')]
    local_sync_at = max(updated_values) if updated_values else None
    # 数据库保留完整逐期审计字段；浏览器传输层只携带绘图、卡片和 CSV 实际使用
    # 的字段，避免把 indicator_name/frequency/parser_notes 等常量重复一万余次。
    public_series = {
        code: [{key: row.get(key) for key in (
            'period', 'value', 'unit', 'frequency', 'data_status', 'evidence_tier',
            'source_name', 'source_url', 'source_title', 'release_date', 'retrieved_at',
            'release_date_not_provided', 'release_date_reason', 'formula')}
               | {'evidence_tier': _evidence_tier(row),
                  'release_date_not_provided': _release_date_missing(row),
                  'release_date_reason': _release_date_reason(row)}
               for row in values]
        for code, values in series.items()
    }
    return {
        'success': True, 'generated_at': datetime.now().isoformat(),
        # ``updated_at`` 保留旧 API 字段；新字段明确它是本地记录最近变化时间，
        # 不把它称为官方发布日期。
        'updated_at': local_sync_at,
        'local_sync_at': local_sync_at,
        'groups': GROUPS, 'metrics': metrics, 'series': public_series,
        'cards': [_card(code, series, metrics) for code in card_codes],
        'coverage': coverage, 'warnings': warnings,
        'currency_options': [
            {'code': 'CNY', 'label': '人民币', 'unit': '亿元'},
            {'code': 'USD', 'label': '美元', 'unit': '亿美元'},
        ],
        'methodology': {
            'status': 'official + official_revised + derived',
            'missingness': '缺失不插值、不跨缺月、不以另一币种换算补齐',
            'sources': ['国家统计局', '民政部', '最高人民法院', '海关总署', '商务部', '国家外汇管理局'],
        },
    }


def update_china_macro_bundle(db_path, full_history=False, start_year=None):
    """组合统计局、外贸/跨境资金与人口婚姻家庭年度快照管线。"""
    nbs_start = int(start_year) if full_history and start_year else None
    nbs = update_china_macro(db_path, start_year=nbs_start)
    external = update_china_external(
        db_path, full_history=full_history,
        start_year=(int(start_year) if start_year else None))
    # 统计局年度快照中也有出生人口；最后同步人口婚姻家庭文件，确保其
    # 更完整的来源字段和历史序列不会被普通宏观快照覆盖。
    demography = update_china_demography(db_path)
    return {
        'success': bool(nbs.get('success') or external.get('success') or demography.get('success')),
        'records_upserted': int(nbs.get('records_upserted') or 0) +
                            int(external.get('records_upserted') or 0) +
                            int(demography.get('records_upserted') or 0),
        'nbs': nbs, 'external': external, 'demography': demography,
    }
