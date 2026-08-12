# -*- coding: utf-8 -*-
"""Long-horizon demographic capacity layer for the housing scenario page.

This module intentionally does not forecast house prices.  It combines the UN
WPP 2024 medium age structure with a user-visible household-formation scenario
and, where available, a bounded city population-concentration adjustment.  All
scenario assumptions and fallbacks are returned in the payload.
"""
from __future__ import annotations

import csv
import math
import statistics
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from services.housing_structural_driver_service import (
    CITY_REGION_CODES,
    _annualized_growths,
    _read_city_indicator,
    load_national_structural_drivers,
)


PROJECTION_INPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / 'data' / 'housing_demographic_capacity_inputs.csv'
)
PROJECTION_YEARS = (2025, 2030, 2040, 2050)
BASE_YEAR = 2025
TARGET_YEAR = 2050
FOCUS_CITIES = tuple(CITY_REGION_CODES)
SCENARIO_KEYS = ('optimistic', 'base', 'stress')
SCENARIO_LABELS = {'optimistic': '乐观', 'base': '基准', 'stress': '压力'}
DEFAULT_FORMATION_ADJUSTMENT_2050_PCT = {
    'optimistic': 10.0,
    'base': 0.0,
    'stress': -15.0,
}
FORMATION_ADJUSTMENT_BOUNDS_PCT = (-50.0, 50.0)
CITY_RELATIVE_GROWTH_CAP_PP = 2.0
CITY_TREND_HALF_LIFE_YEARS = 8.0
CITY_MIN_GROWTH_OBS = 3
CITY_MAX_STALENESS_YEARS = 3


def _clamp(value, lower, upper):
    return max(float(lower), min(float(upper), float(value)))


def _year(period):
    try:
        return int(str(period)[:4])
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=4)
def load_demographic_projection_inputs(path=None):
    """Load and validate the compact official UN projection snapshot."""
    source_path = Path(path) if path else PROJECTION_INPUT_PATH
    grouped, seen = {}, set()
    required_codes = {
        'un_total_population_1jan',
        'un_population_age_20_39',
        'un_population_age_60_plus',
    }
    with source_path.open('r', encoding='utf-8-sig', newline='') as handle:
        for raw in csv.DictReader(handle):
            code = (raw.get('indicator_code') or '').strip()
            year = int((raw.get('period') or '').strip())
            key = (code, year)
            if key in seen:
                raise ValueError(f'人口投影复合键重复：{code} {year}')
            seen.add(key)
            value = float(raw['value'])
            if code not in required_codes or year not in PROJECTION_YEARS:
                raise ValueError(f'人口投影出现未声明字段或年份：{code} {year}')
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'人口投影值无效：{code} {year}')
            source_url = (raw.get('source_url') or '').strip()
            if not source_url.startswith('https://population.un.org/'):
                raise ValueError(f'人口投影缺少联合国官方来源：{code} {year}')
            grouped.setdefault(year, {})[code] = {
                'indicator_code': code,
                'period': str(year),
                'value': value,
                'unit': (raw.get('unit') or '').strip(),
                'data_status': (raw.get('data_status') or '').strip(),
                'source_name': (raw.get('source_name') or '').strip(),
                'source_url': source_url,
                'parser_notes': (raw.get('parser_notes') or '').strip(),
            }
    if set(grouped) != set(PROJECTION_YEARS):
        raise ValueError('人口投影年份覆盖不完整')
    for year, values in grouped.items():
        if set(values) != required_codes:
            raise ValueError(f'人口投影字段覆盖不完整：{year}')
        total = values['un_total_population_1jan']['value']
        if values['un_population_age_20_39']['value'] >= total:
            raise ValueError(f'20-39岁人口不应大于总人口：{year}')
        if values['un_population_age_60_plus']['value'] >= total:
            raise ValueError(f'60岁以上人口不应大于总人口：{year}')
    return grouped


def normalise_formation_adjustments(values=None):
    output = dict(DEFAULT_FORMATION_ADJUSTMENT_2050_PCT)
    for key, value in (values or {}).items():
        if key in output and value is not None:
            output[key] = _clamp(
                value, FORMATION_ADJUSTMENT_BOUNDS_PCT[0],
                FORMATION_ADJUSTMENT_BOUNDS_PCT[1])
    if not (output['optimistic'] >= output['base'] >= output['stress']):
        raise ValueError('家庭形成倾向必须满足：乐观 ≥ 基准 ≥ 压力')
    return {key: round(output[key], 4) for key in SCENARIO_KEYS}


def formation_multiplier(year, adjustment_2050_pct,
                         base_year=BASE_YEAR, target_year=TARGET_YEAR):
    """Linearly phase a visible household-formation assumption to 2050."""
    if target_year <= base_year:
        raise ValueError('target_year 必须晚于 base_year')
    progress = _clamp((int(year) - base_year) / (target_year - base_year), 0.0, 1.0)
    return 1.0 + float(adjustment_2050_pct) / 100.0 * progress


def city_concentration_multiplier(year, relative_growth_pp,
                                  half_life_years=CITY_TREND_HALF_LIFE_YEARS):
    """Integrate a decaying relative city-population growth impulse."""
    elapsed = max(0.0, float(year) - BASE_YEAR)
    if elapsed == 0 or relative_growth_pp == 0:
        return 1.0
    half_life = float(half_life_years)
    if half_life <= 0:
        raise ValueError('人口集聚半衰期必须为正数')
    decay = math.log(2.0) / half_life
    effective_years = (1.0 - math.exp(-decay * elapsed)) / decay
    return math.exp(float(relative_growth_pp) / 100.0 * effective_years)


def _national_actual_anchor():
    grouped = load_national_structural_drivers()
    rows = grouped.get('national_population') or []
    if not rows:
        raise ValueError('缺少国家统计局全国人口锚点')
    latest = rows[-1]
    growths = _annualized_growths(rows, max_intervals=3)
    latest_growth = growths[-1]['value'] if growths else None
    return latest, latest_growth


def _projection_rows(grouped, actual_anchor):
    base = grouped[BASE_YEAR]
    base_total = base['un_total_population_1jan']['value']
    base_young = base['un_population_age_20_39']['value']
    base_old = base['un_population_age_60_plus']['value']
    actual_million = float(actual_anchor['value']) / 100.0
    scale = actual_million / (base_total / 1000.0)
    rows = []
    for year in PROJECTION_YEARS:
        values = grouped[year]
        total = values['un_total_population_1jan']['value']
        young = values['un_population_age_20_39']['value']
        old = values['un_population_age_60_plus']['value']
        rows.append({
            'year': year,
            'total_population_wpp_million': round(total / 1000.0, 3),
            'total_population_nbs_anchored_million': round(total / 1000.0 * scale, 3),
            'population_20_39_wpp_million': round(young / 1000.0, 3),
            'population_60_plus_wpp_million': round(old / 1000.0, 3),
            'total_population_index': round(total / base_total * 100.0, 3),
            'population_20_39_index': round(young / base_young * 100.0, 3),
            'population_60_plus_index': round(old / base_old * 100.0, 3),
            'population_20_39_share_pct': round(young / total * 100.0, 3),
            'population_60_plus_share_pct': round(old / total * 100.0, 3),
            'data_status': 'official_projection',
            'source_url': values['un_total_population_1jan']['source_url'],
        })
    return rows


def build_capacity_scenarios(projections, formation_adjustments=None,
                             relative_growth_pp=0.0):
    """Build transparent capacity and fixed-stock burden paths."""
    adjustments = normalise_formation_adjustments(formation_adjustments)
    scenarios = []
    for key in SCENARIO_KEYS:
        points = []
        for row in projections:
            multiplier = formation_multiplier(row['year'], adjustments[key])
            concentration = city_concentration_multiplier(
                row['year'], relative_growth_pp)
            capacity = row['population_20_39_index'] * multiplier * concentration
            points.append({
                'year': row['year'],
                'formation_multiplier': round(multiplier, 4),
                'city_concentration_multiplier': round(concentration, 4),
                'demand_capacity_index': round(capacity, 3),
                'fixed_stock_burden_index': round(10000.0 / capacity, 3),
                'data_status': 'scenario',
            })
        scenarios.append({
            'key': key,
            'label': SCENARIO_LABELS[key],
            'formation_adjustment_2050_pct': adjustments[key],
            'points': points,
            'data_status': 'scenario',
        })
    return scenarios


def _city_population_context(conn, city, national_growth_pct):
    rows = _read_city_indicator(conn, city, 'resident_population')
    growths = _annualized_growths(rows, max_intervals=5)
    latest_year = _year(rows[-1]['period']) if rows else None
    usable = (
        len(growths) >= CITY_MIN_GROWTH_OBS and latest_year is not None and
        latest_year >= BASE_YEAR - CITY_MAX_STALENESS_YEARS
    )
    city_growth = statistics.median(item['value'] for item in growths) if usable else None
    raw_relative = (
        city_growth - national_growth_pct
        if city_growth is not None and national_growth_pct is not None else None
    )
    applied_relative = (
        _clamp(raw_relative, -CITY_RELATIVE_GROWTH_CAP_PP,
               CITY_RELATIVE_GROWTH_CAP_PP)
        if raw_relative is not None else 0.0
    )
    latest = rows[-1] if rows else {}
    return {
        'coverage_status': 'city_trend' if usable else 'national_fallback',
        'n_obs': len(rows),
        'n_growth_obs': len(growths),
        'sample_start': rows[0]['period'] if rows else None,
        'sample_end': rows[-1]['period'] if rows else None,
        'latest_population': latest.get('value'),
        'unit': latest.get('unit'),
        'recent_city_population_growth_pct': (
            round(city_growth, 4) if city_growth is not None else None),
        'latest_national_population_growth_pct': (
            round(national_growth_pct, 4)
            if national_growth_pct is not None else None),
        'raw_relative_growth_pp': (
            round(raw_relative, 4) if raw_relative is not None else None),
        'applied_relative_growth_pp': round(applied_relative, 4),
        'data_status': latest.get('data_status'),
        'source_name': latest.get('source_name'),
        'source_url': latest.get('source_url'),
        'fallback_reason': (
            None if usable else
            f'至少需要{CITY_MIN_GROWTH_OBS}个近期常住人口增速且最新期不早于'
            f'{BASE_YEAR - CITY_MAX_STALENESS_YEARS}年；当前只有{len(growths)}个可用增速。'
        ),
    }


def build_demographic_capacity_payload(conn, cities=None,
                                       formation_adjustments=None,
                                       projection_path=None):
    grouped = load_demographic_projection_inputs(projection_path)
    actual, national_growth = _national_actual_anchor()
    projections = _projection_rows(grouped, actual)
    adjustments = normalise_formation_adjustments(formation_adjustments)
    national_scenarios = build_capacity_scenarios(projections, adjustments)
    selected = list(dict.fromkeys(cities or FOCUS_CITIES))
    city_rows = []
    for city in selected:
        context = _city_population_context(conn, city, national_growth)
        city_rows.append({
            'city': city,
            **context,
            'scenarios': build_capacity_scenarios(
                projections, adjustments,
                relative_growth_pp=context['applied_relative_growth_pp']),
        })
    city_specific = sum(row['coverage_status'] == 'city_trend' for row in city_rows)
    base_wpp_million = projections[0]['total_population_wpp_million']
    actual_million = float(actual['value']) / 100.0
    return {
        'status': 'ok',
        'generated_at': datetime.now().isoformat(),
        'data_status': 'scenario',
        'projection_data_status': 'official_projection',
        'base_year': BASE_YEAR,
        'target_years': list(PROJECTION_YEARS),
        'parameters': {
            'formation_adjustment_2050_pct': adjustments,
            'city_relative_growth_cap_pp': CITY_RELATIVE_GROWTH_CAP_PP,
            'city_trend_half_life_years': CITY_TREND_HALF_LIFE_YEARS,
            'city_min_growth_observations': CITY_MIN_GROWTH_OBS,
            'city_latest_year_threshold': BASE_YEAR - CITY_MAX_STALENESS_YEARS,
        },
        'national': {
            'latest_actual': {
                'year': int(actual['period']),
                'total_population_million': round(actual_million, 3),
                'unit': '百万人',
                'data_status': actual['data_status'],
                'source_name': actual['source_name'],
                'source_url': actual['source_url'],
            },
            'wpp_2025_vs_nbs_actual_pct': round(
                (base_wpp_million / actual_million - 1.0) * 100.0, 3),
            'projections': projections,
            'scenarios': national_scenarios,
        },
        'cities': city_rows,
        'coverage': {
            'tracked_cities': len(city_rows),
            'city_trend_cities': city_specific,
            'national_fallback_cities': len(city_rows) - city_specific,
            'city_trend_names': [row['city'] for row in city_rows
                                 if row['coverage_status'] == 'city_trend'],
            'national_fallback_names': [row['city'] for row in city_rows
                                        if row['coverage_status'] == 'national_fallback'],
        },
        'method': (
            '潜在家庭形成容量指数 = UN WPP 2024中方案20—39岁人口指数 × '
            '家庭形成倾向情景乘数 × 城市人口集聚乘数。家庭形成乘数从2025年的1线性'
            '变化到用户设定的2050终值；城市集聚乘数使用本市最近最多5个常住人口增速'
            '中位数相对全国最新增速，限制在±2个百分点并按8年半衰期衰减。'
            '固定存量负担指数 = 10000 / 容量指数。'
        ),
        'caveats': [
            '联合国WPP数值是官方人口投影，不是实际观测；中方案也不是概率最高的保证结果。',
            'WPP为1月1日口径，国家统计局锚点为年末口径；绝对人口路径按WPP相对变化缩放到2025年国家统计局实际值，标记derived。',
            '乐观、基准、压力只改变家庭形成倾向；默认+10%/0%/-15%是可调压力测试，不是视频中的70%或35%，也不是估计系数。',
            '城市常住人口不足连续年点时使用全国路径并明确标记national_fallback，不用户籍人口冒充迁移趋势。',
            '固定存量负担假设2025住房存量不变，未计新增、拆除、空置释放和城市间住房质量差异，因此只表示人口侧压力。',
            '本层不直接换算房价，也不叠加进现有2030价格路径；这样避免人口和婚姻变量被重复计算。',
        ],
        'sources': [
            {
                'name': 'United Nations WPP 2024 · Medium variant',
                'url': projections[0]['source_url'],
                'data_status': 'official_projection',
            },
            {
                'name': actual['source_name'],
                'url': actual['source_url'],
                'data_status': actual['data_status'],
            },
        ],
    }
