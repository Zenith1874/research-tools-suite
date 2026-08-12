# -*- coding: utf-8 -*-
"""统一中国宏观数据页的只读 payload 与组合更新入口。"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from datetime import datetime

from services.china_external_service import EXTERNAL_INDICATORS, update_china_external
from services.china_macro_service import (
    INDICATORS, connect, ensure_china_macro_tables, update_china_macro,
)


DERIVED_META = {
    'CN_POPULATION_YOY_DERIVED': ('年末全国人口同比', '%', 'annual'),
    'CN_EMPLOYED_YOY_DERIVED': ('全国就业人员同比', '%', 'annual'),
    'CN_DISPOSABLE_INCOME_YOY_DERIVED': ('居民人均可支配收入名义同比', '%', 'annual'),
}


def _chart(code, title, series, unit, subtitle='', threshold=None, currency=False,
           note=''):
    return {
        'code': code, 'title': title, 'series': list(series), 'unit': unit,
        'subtitle': subtitle, 'threshold': threshold,
        'currency_switch': bool(currency), 'note': note,
    }


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
        'code': 'labor', 'title': '就业与人口',
        'description': '月度调查失业率与年度人口、就业、收入；年度同比只按相邻年份计算。',
        'charts': [
            _chart('unemployment', '全国城镇调查失业率', ('CN_UNEMP_SURVEY',), '%'),
            _chart('population', '全国人口与就业人员',
                   ('CN_POPULATION', 'CN_EMPLOYED', 'CN_URBAN_EMPLOYED',
                    'CN_LABOR_FORCE'), '万人'),
            _chart('population_growth', '人口、就业与收入年度同比',
                   ('CN_POPULATION_YOY_DERIVED', 'CN_EMPLOYED_YOY_DERIVED',
                    'CN_DISPOSABLE_INCOME_YOY_DERIVED'), '%'),
            _chart('population_flows', '出生、死亡与城镇新增就业',
                   ('CN_BIRTHS', 'CN_DEATHS', 'CN_URBAN_NEW_JOBS'), '万人'),
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


def _card(code, series, metrics):
    rows = series.get(code) or []
    meta = metrics.get(code) or {}
    if not rows:
        return {'code': code, 'label': meta.get('name') or code, 'value': None,
                'period': None, 'unit': meta.get('unit'), 'data_status': 'missing'}
    row = rows[-1]
    return {
        'code': code, 'label': meta.get('name') or row.get('indicator_name') or code,
        'value': row.get('value'), 'period': row.get('period'),
        'unit': row.get('unit') or meta.get('unit'),
        'data_status': row.get('data_status'), 'source_name': row.get('source_name'),
        'source_url': row.get('source_url'),
    }


def build_china_macro_payload(db_path):
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        raw_rows = [dict(row) for row in conn.execute('''
            SELECT indicator_code,indicator_name,period,value,unit,frequency,data_status,
                   source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
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
                'source_name': values[-1].get('source_name'),
                'source_url': values[-1].get('source_url'),
            })
    coverage.sort(key=lambda item: (item['name'], item['code']))

    card_codes = (
        'CN_GDP_Q_REAL_YOY', 'CN_IP_YOY', 'CN_RETAIL_YOY', 'CN_FAI_YTD_YOY',
        'CN_CPI_YOY', 'CN_PMI_MFG', 'CN_UNEMP_SURVEY',
        'CN_GACC_EXPORT_CNY_MONTH_YOY', 'CN_MOFCOM_FDI_CNY_YTD_YOY',
        'CN_SAFE_XB_NET_CNY',
    )
    warnings = [
        '人民币和美元均保存官方原币值，系统不以汇率反推缺失币种。',
        '当月、累计、绝对量和同比不会放在同一坐标轴；1—2月合并发布保持2月期点。',
        '商务部实际使用外资、对外直接投资与外汇局跨境收付款是不同统计体系，不计算伪“净外资”。',
        '汽车类零售额为限额以上单位口径；主要工业品产量只代表规模以上工业。',
    ]
    cny_fdi = series.get('CN_MOFCOM_FDI_CNY_YTD') or []
    usd_fdi = series.get('CN_MOFCOM_FDI_USD_YTD') or []
    if cny_fdi and (not usd_fdi or usd_fdi[-1]['period'] < cny_fdi[-1]['period']):
        warnings.append(
            f"商务部美元实际使用外资序列最新为{usd_fdi[-1]['period'] if usd_fdi else '缺失'}，"
            f"人民币序列已到{cny_fdi[-1]['period']}；页面如实断线，不做汇率换算。")
    updated_values = [row.get('updated_at') for row in raw_rows if row.get('updated_at')]
    # 数据库保留完整逐期审计字段；浏览器传输层只携带绘图、卡片和 CSV 实际使用
    # 的字段，避免把 indicator_name/frequency/parser_notes 等常量重复一万余次。
    public_series = {
        code: [{key: row.get(key) for key in (
            'period', 'value', 'data_status', 'source_name', 'source_url')}
               for row in values]
        for code, values in series.items()
    }
    return {
        'success': True, 'generated_at': datetime.now().isoformat(),
        'updated_at': max(updated_values) if updated_values else None,
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
            'sources': ['国家统计局', '海关总署', '商务部', '国家外汇管理局'],
        },
    }


def update_china_macro_bundle(db_path, full_history=False, start_year=None):
    """组合现有统计局管线和新增外贸/跨境资金管线。"""
    nbs_start = int(start_year) if full_history and start_year else None
    nbs = update_china_macro(db_path, start_year=nbs_start)
    external = update_china_external(
        db_path, full_history=full_history,
        start_year=(int(start_year) if start_year else None))
    return {
        'success': bool(nbs.get('success') or external.get('success')),
        'records_upserted': int(nbs.get('records_upserted') or 0) +
                            int(external.get('records_upserted') or 0),
        'nbs': nbs, 'external': external,
    }
