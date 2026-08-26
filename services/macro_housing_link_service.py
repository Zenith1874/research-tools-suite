# -*- coding: utf-8 -*-
"""Transparent macro-to-housing scenario linkage.

This module deliberately sits between the existing macro scenario laboratory and
the existing housing momentum model. It does not replace either model and it
does not claim causal estimates. The macro paths provide a documented stress-test
overlay; the raw housing paths remain available as the baseline.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing

from services.housing_structural_driver_service import load_national_structural_drivers
from services.macro_scenario_service import (
    SCENARIO_LABELS as MACRO_SCENARIO_LABELS,
    SERIES_CATALOG,
    _minimum_history,
    _rows_for_config,
    _scenario_paths,
)


HOUSING_SCENARIO_KEYS = ('optimistic', 'base', 'stress')
TRACK_KEYS = ('upper', 'base', 'lower')

# Coefficients are deliberately small, inspectable assumptions. A coefficient
# translates a one-percentage-point difference in a macro indicator into
# annualised housing-speed percentage points. It is not a regression estimate.
LINK_COMPONENTS = (
    {
        'key': 'growth', 'code': 'CN_GDP_Q_REAL_YOY', 'label': 'GDP实际增速',
        'coefficient': 0.20, 'interpretation': '增长轨道较基准每高1个百分点，房价年化速度压力测试增加0.20个百分点。',
    },
    {
        'key': 'credit', 'code': 'loany', 'label': '人民币贷款余额同比',
        'coefficient': 0.10, 'interpretation': '贷款余额同比轨道较基准每高1个百分点，房价年化速度压力测试增加0.10个百分点。',
    },
    {
        'key': 'sales', 'code': 'sales_area_ytd_yoy_official', 'label': '商品房销售面积累计同比',
        'coefficient': 0.08, 'interpretation': '销售面积同比轨道较基准每高1个百分点，房价年化速度压力测试增加0.08个百分点。',
    },
    {
        'key': 'population', 'code': 'national_population_growth', 'label': '全国人口增速',
        'coefficient': 2.00, 'interpretation': '人口增速轨道较基准每高1个百分点，房价年化速度压力测试增加2.00个百分点。',
        'source_kind': 'structural_csv',
    },
    {
        'key': 'lpr', 'code': 'LPR_5Y', 'label': '5年期LPR',
        'coefficient': -0.80, 'interpretation': 'LPR轨道较基准每低1个百分点，房价年化速度压力测试增加0.80个百分点。',
    },
)


def normalize_selectors(selectors=None):
    """Normalize user-selected component tracks without inventing values."""
    selectors = selectors or {}
    return {
        component['key']: (selectors.get(component['key'])
                           if selectors.get(component['key']) in ('auto', *TRACK_KEYS)
                           else 'auto')
        for component in LINK_COMPONENTS
    }


def _default_track(housing_key, component_key):
    if housing_key == 'base':
        return 'base'
    if component_key == 'lpr':
        return 'lower' if housing_key == 'optimistic' else 'upper'
    return 'upper' if housing_key == 'optimistic' else 'lower'


def default_track_map(selectors=None):
    selectors = normalize_selectors(selectors)
    return {
        housing_key: {
            component['key']: (selectors[component['key']]
                               if selectors[component['key']] != 'auto'
                               else _default_track(housing_key, component['key']))
            for component in LINK_COMPONENTS
        }
        for housing_key in HOUSING_SCENARIO_KEYS
    }


def _population_growth_rows():
    grouped = load_national_structural_drivers()
    rows = grouped.get('national_population') or []
    output = []
    for previous, current in zip(rows, rows[1:]):
        try:
            previous_year = int(str(previous['period'])[:4])
            current_year = int(str(current['period'])[:4])
            previous_value = float(previous['value'])
            current_value = float(current['value'])
        except (KeyError, TypeError, ValueError):
            continue
        if current_year != previous_year + 1 or previous_value <= 0:
            continue
        output.append({
            'period': str(current['period'])[:4],
            'value': (current_value / previous_value - 1.0) * 100.0,
            'data_status': current.get('data_status'),
            'source_name': current.get('source_name'),
            'source_url': current.get('source_url'),
        })
    return output


def _component_payload(definition, config, rows, horizon_months):
    frequency = config['frequency'] if config else 'annual'
    minimum = _minimum_history(frequency)
    component = {
        'key': definition['key'], 'code': definition['code'],
        'label': definition['label'], 'frequency': frequency,
        'unit': config.get('unit', '%') if config else '%',
        'mode': config.get('mode', 'rate') if config else 'rate',
        'coefficient': definition['coefficient'],
        'interpretation': definition['interpretation'],
        'n_obs': len(rows),
        'sample_start': rows[0].get('period') if rows else None,
        'sample_end': rows[-1].get('period') if rows else None,
        'latest_value': rows[-1].get('value') if rows else None,
        'latest_source_name': rows[-1].get('source_name') if rows else None,
        'latest_source_url': rows[-1].get('source_url') if rows else None,
        'paths': {}, 'track_keys': [],
    }
    if not rows:
        component.update(status='missing', reason='当前数据库/结构驱动文件没有可用观测。')
        return component
    if len(rows) < minimum:
        component.update(
            status='insufficient_sample',
            reason=f'连续历史只有{len(rows)}个点，少于{minimum}个点的推演门槛。',
        )
        return component
    periods = max(1, math.ceil(int(horizon_months) /
                               {'monthly': 1, 'quarterly': 3, 'annual': 12}.get(frequency, 1)))
    mode = config.get('mode', 'rate') if config else 'rate'
    paths = _scenario_paths(rows, frequency, mode, periods)
    if not paths:
        component.update(status='insufficient_sample', reason='变化序列不足，未形成三条宏观情景路径。')
        return component
    component['status'] = 'ok'
    component['track_keys'] = [path['key'] for path in paths]
    component['paths'] = {
        path['key']: [{'period': point['period'], 'value': point['value']}
                      for point in path.get('path') or []]
        for path in paths
    }
    component['annualised_drifts'] = {
        path['key']: path.get('annualised_drift') for path in paths
    }
    return component


def build_macro_housing_linkage(db_path, horizon_months=24, selectors=None):
    """Build read-only macro component paths for a housing horizon."""
    try:
        horizon_months = max(6, min(120, int(horizon_months)))
    except (TypeError, ValueError):
        horizon_months = 24
    selectors = normalize_selectors(selectors)
    configs = {item['code']: item for item in SERIES_CATALOG}
    by_code = {}
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        for definition in LINK_COMPONENTS:
            if definition.get('source_kind') == 'structural_csv':
                continue
            config = configs.get(definition['code'])
            try:
                by_code[definition['code']] = _rows_for_config(conn, config) if config else []
            except (OSError, ValueError, sqlite3.Error):
                by_code[definition['code']] = []
    try:
        by_code['national_population_growth'] = _population_growth_rows()
    except (OSError, ValueError, KeyError):
        by_code['national_population_growth'] = []

    components = []
    for definition in LINK_COMPONENTS:
        config = configs.get(definition['code'])
        components.append(_component_payload(
            definition, config, by_code.get(definition['code'], []), horizon_months))
    available = [component for component in components if component['status'] == 'ok']
    status = 'ok' if len(available) == len(components) else (
        'partial' if available else 'insufficient_data')
    caveats = [
        '宏观联动是透明压力测试，不是回归估计、因果识别、概率预测或官方预测。',
        'GDP为季度、人口为年度；低频路径按对应月数阶梯展开到房价月度路径。',
        '组件缺失或历史不足只减少覆盖并保留状态，不以零值、其他指标或文字稿数字代填。',
        '默认 auto 方向：乐观为增长/信用/销售/人口上行、LPR下行；压力情景相反。',
    ]
    return {
        'status': status, 'data_status': 'derived_scenario_input',
        'horizon_months': horizon_months, 'selectors': selectors,
        'track_map': default_track_map(selectors),
        'components': components,
        'available_component_count': len(available),
        'component_count': len(components),
        'method': ('以现有宏观情景实验室的连续尾段75/50/25分位路径为组件输入；'
                   '每个组件相对其基准轨道的差值乘透明系数，合计为年化房价速度调整，'
                   '再除以12叠加到原房价月速并复利。'),
        'caveats': caveats,
    }


def _track_value(component, track, housing_step_index):
    path = (component.get('paths') or {}).get(track) or []
    if not path:
        return None
    frequency = component.get('frequency')
    divisor = {'monthly': 1, 'quarterly': 3, 'annual': 12}.get(frequency, 1)
    index = min(len(path) - 1, housing_step_index // divisor)
    try:
        value = float(path[index].get('value'))
    except (TypeError, ValueError, AttributeError):
        return None
    return value if math.isfinite(value) else None


def apply_macro_housing_linkage(series, momentum_scenarios, linkage):
    """Overlay macro component deviations on raw housing momentum paths."""
    if not series or not linkage or not linkage.get('components'):
        return []
    components = [component for component in linkage['components']
                  if component.get('status') == 'ok' and component.get('paths')]
    if not components:
        return []
    track_map = linkage.get('track_map') or default_track_map(linkage.get('selectors'))
    current = float(series[-1].get('index'))
    peak = max(float(point.get('index')) for point in series if point.get('index') is not None)
    output = []
    for raw in momentum_scenarios or []:
        if raw.get('status') or not raw.get('path'):
            continue
        raw_rate = float(raw.get('monthly_rate'))
        index_value = current
        path = []
        adjustments = []
        final_component_values = {}
        for step_index, raw_point in enumerate(raw.get('path') or []):
            total_annual_pp = 0.0
            contributions = []
            for component in components:
                component_key = component['key']
                selected_track = (track_map.get(raw['key'], {}).get(component_key)
                                  or _default_track(raw['key'], component_key))
                selected_value = _track_value(component, selected_track, step_index)
                base_value = _track_value(component, 'base', step_index)
                if selected_value is None or base_value is None:
                    continue
                delta = selected_value - base_value
                contribution = float(component['coefficient']) * delta
                total_annual_pp += contribution
                contributions.append({
                    'key': component_key, 'label': component['label'],
                    'track': selected_track, 'selected_value': round(selected_value, 6),
                    'base_value': round(base_value, 6), 'delta': round(delta, 6),
                    'coefficient': component['coefficient'],
                    'contribution_pp': round(contribution, 6),
                })
                final_component_values[component_key] = contributions[-1]
            monthly_adjustment_pp = total_annual_pp / 12.0
            linked_monthly_rate = raw_rate + monthly_adjustment_pp
            index_value *= 1.0 + linked_monthly_rate / 100.0
            adjustments.append(total_annual_pp)
            point = dict(raw_point)
            point['index'] = round(index_value, 4)
            point['macro_adjustment_pp'] = round(total_annual_pp, 6)
            point['macro_monthly_adjustment_pp'] = round(monthly_adjustment_pp, 6)
            path.append(point)
        if not path:
            continue
        monthly_rate = (path[-1]['index'] / current) ** (1.0 / len(path)) - 1.0
        monthly_rate *= 100.0
        item = dict(raw)
        item.update({
            'label': f"{MACRO_SCENARIO_LABELS.get(raw['key'], raw.get('label', raw['key']))}（宏观联动）",
            'path': path,
            'monthly_rate': round(monthly_rate, 6),
            'annualised': round(((1.0 + monthly_rate / 100.0) ** 12 - 1.0) * 100.0, 4),
            'end_period': path[-1]['period'],
            'end_vs_now': round((path[-1]['index'] / current - 1.0) * 100.0, 4),
            'end_vs_peak': round((path[-1]['index'] / peak - 1.0) * 100.0, 4),
            'base_momentum_monthly_rate': raw_rate,
            'macro_adjustment_mean_pp': round(sum(adjustments) / len(adjustments), 6),
            'macro_adjustment_end_pp': round(adjustments[-1], 6),
            'macro_contributions': list(final_component_values.values()),
            'data_status': 'scenario',
        })
        output.append(item)
    rates = {item['key']: item.get('monthly_rate') for item in output}
    ordering_valid = bool(output) and all(
        rates.get(key) is not None for key in HOUSING_SCENARIO_KEYS
    ) and rates['optimistic'] >= rates['base'] >= rates['stress']
    for item in output:
        item['ordering_valid'] = ordering_valid
        if not ordering_valid:
            item['ordering_warning'] = '逐项固定组件后，用户假设使三档月速不再保持乐观≥基准≥压力。'
    return output


__all__ = [
    'LINK_COMPONENTS', 'TRACK_KEYS', 'apply_macro_housing_linkage',
    'build_macro_housing_linkage', 'default_track_map', 'normalize_selectors',
]
