# -*- coding: utf-8 -*-
"""房价情景的透明结构驱动层。

本模块不训练黑箱模型，也不把人口、婚姻或收入写成房价的因果系数。它把可核验
的年度驱动转换为一组机械压力测试贡献，再用“相对基准情景的结构偏差”扩展既有
价格动能区间。原始动能路径始终保留；结构强度设为 0 时应精确退回原路径。
"""
from __future__ import annotations

import csv
import math
import statistics
from functools import lru_cache
from pathlib import Path


DEFAULT_STRUCTURAL_WEIGHT = 0.40
STRUCTURAL_WEIGHT_BOUNDS = (0.0, 1.0)
SCENARIO_KEYS = ('optimistic', 'base', 'stress')
SCENARIO_LABELS = {'optimistic': '乐观', 'base': '基准', 'stress': '压力'}
NATIONAL_DRIVER_PATH = (
    Path(__file__).resolve().parents[1] / 'data' / 'housing_structural_drivers.csv'
)
MAX_CITY_DRIVER_STALENESS_YEARS = 2

# 城市一般指标可能同时保存直辖市行政区码和城市码；按城市名优先读取，精简测试库
# 没有 region_name 时才使用此映射。
CITY_REGION_CODES = {
    '北京': ('110100', '110000'), '上海': ('310100', '310000'),
    '广州': ('440100',), '深圳': ('440300',), '厦门': ('350200',),
    '南京': ('320100',), '合肥': ('340100',), '常州': ('320400',),
    '苏州': ('320500',), '无锡': ('320200',), '武汉': ('420100',),
    '长沙': ('430100',), '成都': ('510100',), '杭州': ('330100',),
    '福州': ('350100',),
}

STATUS_PRIORITY = {
    'official': 6, 'official_revised': 5, 'official_preliminary': 4,
    'official_mirror': 2, 'derived': 1,
}

# 这些是机械压力测试的“翻译系数”，不是回归估计。每项贡献另有上限，防止短期
# 极端同比被线性放大。单位均为“对年化房价速度的百分点贡献”。
DRIVER_RULES = {
    'income_growth': {
        'label': '收入增长', 'coefficient': 1.00, 'neutral': 0.0, 'cap_pp': 12.0,
        'explanation': '收入增长1个百分点，对可负担名义价格增速贡献1个百分点。',
    },
    'population_growth': {
        'label': '人口变化', 'coefficient': 2.00, 'neutral': 0.0, 'cap_pp': 3.0,
        'explanation': '人口增速每变化1个百分点，机械压力贡献2个百分点，上限±3。',
    },
    'marriage_growth': {
        'label': '粗结婚率变化', 'coefficient': 0.10, 'neutral': 0.0, 'cap_pp': 2.5,
        'explanation': '全国粗结婚率增速每变化10个百分点，机械贡献1个百分点。',
    },
    'sales_area_growth': {
        'label': '商品房销售面积变化', 'coefficient': 0.08, 'neutral': 0.0,
        'cap_pp': 3.0,
        'explanation': '销售面积增速每变化10个百分点，机械贡献0.8个百分点。',
    },
    'completion_sales_ratio': {
        'label': '竣工/销售供给比', 'coefficient': -3.00, 'neutral': 1.0,
        'cap_pp': 2.5,
        'explanation': '竣工/销售比每高于1.0约0.1，对年化速度形成0.3个百分点拖累。',
    },
    'lpr_change': {
        'label': '5年期LPR变化', 'coefficient': -0.80, 'neutral': 0.0,
        'cap_pp': 1.5,
        'explanation': '5年期LPR同比每下降1个百分点，机械支持0.8个百分点。',
    },
}


def _clamp(value, lower, upper):
    return max(lower, min(upper, float(value)))


def _quantile(values, probability):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _year(period):
    try:
        return int(str(period)[:4])
    except (TypeError, ValueError):
        return None


def _add_months(period, months):
    year, month = int(period[:4]), int(period[5:7])
    total = year * 12 + month - 1 + int(months)
    return f'{total // 12:04d}-{total % 12 + 1:02d}'


@lru_cache(maxsize=4)
def load_national_structural_drivers(path=None):
    """Read the baseline and share canonical marriage bulletin revisions."""
    source_path = Path(path) if path else NATIONAL_DRIVER_PATH
    grouped = {}
    seen = set()
    with source_path.open('r', encoding='utf-8-sig', newline='') as handle:
        for raw in csv.DictReader(handle):
            key = (raw['indicator_code'].strip(), raw['period'].strip())
            if key in seen:
                raise ValueError(f'国家结构驱动复合键重复：{key[0]} {key[1]}')
            seen.add(key)
            value = float(raw['value'])
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'国家结构驱动值无效：{key[0]} {key[1]}')
            row = {
                'indicator_code': key[0], 'period': key[1], 'value': value,
                'unit': raw['unit'].strip(), 'data_status': raw['data_status'].strip(),
                'source_name': raw['source_name'].strip(),
                'source_url': raw['source_url'].strip(),
                'parser_notes': raw.get('parser_notes', '').strip(),
            }
            if not row['source_url']:
                raise ValueError(f'国家结构驱动缺来源URL：{key[0]} {key[1]}')
            grouped.setdefault(key[0], []).append(row)
    if source_path.resolve() == NATIONAL_DRIVER_PATH.resolve():
        from services.china_demography_service import read_effective_demography_rows
        marriages = {row['period']: row for row in grouped.get('national_marriages', [])}
        start_period = min(marriages) if marriages else '2010'
        canonical_rows, _ = read_effective_demography_rows()
        for raw in canonical_rows:
            if raw['indicator_code'] != 'CN_MARRIAGES' or raw['period'] < start_period:
                continue
            marriages[raw['period']] = {
                **raw, 'indicator_code': 'national_marriages',
            }
        grouped['national_marriages'] = list(marriages.values())
    for rows in grouped.values():
        rows.sort(key=lambda item: item['period'])
    return grouped


def _table_columns(conn, table):
    try:
        return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    except Exception:
        return set()


def _read_city_indicator(conn, city, indicator_code):
    columns = _table_columns(conn, 'city_indicator_observations')
    if not {'region_code', 'indicator_code', 'period', 'value'} <= columns:
        return []
    optional = ('unit', 'data_status', 'source_name', 'source_url')
    select = ['region_code', 'period', 'value']
    select.extend(column if column in columns else f"NULL AS {column}"
                  for column in optional)
    if 'region_name' in columns:
        where, params = 'region_name=? AND indicator_code=?', (city, indicator_code)
    else:
        codes = CITY_REGION_CODES.get(city) or ()
        if not codes:
            return []
        marks = ','.join('?' for _ in codes)
        where, params = f'region_code IN ({marks}) AND indicator_code=?', (*codes,
                                                                           indicator_code)
    try:
        raw_rows = [dict(row) for row in conn.execute(
            f'''SELECT {','.join(select)} FROM city_indicator_observations
                WHERE {where} ORDER BY period''', params)]
    except Exception:
        return []
    by_period = {}
    for row in raw_rows:
        period = str(row.get('period') or '')[:4]
        value = row.get('value')
        if len(period) != 4 or value is None or not math.isfinite(float(value)):
            continue
        row['period'] = period
        row['value'] = float(value)
        current = by_period.get(period)
        rank = STATUS_PRIORITY.get(row.get('data_status'), 0)
        current_rank = STATUS_PRIORITY.get(current.get('data_status'), 0) if current else -1
        if current is None or rank > current_rank:
            by_period[period] = row
    return [by_period[period] for period in sorted(by_period)]


def _annualized_growths(rows, max_intervals=5, max_gap_years=3):
    clean = [row for row in rows if _year(row.get('period')) is not None and
             row.get('value') is not None and float(row['value']) > 0]
    clean.sort(key=lambda item: item['period'])
    growths = []
    for previous, current in zip(clean, clean[1:]):
        elapsed = _year(current['period']) - _year(previous['period'])
        if elapsed <= 0 or elapsed > max_gap_years:
            continue
        growth = ((float(current['value']) / float(previous['value'])) **
                  (1.0 / elapsed) - 1.0) * 100.0
        growths.append({
            'start_period': previous['period'], 'end_period': current['period'],
            'elapsed_years': elapsed, 'value': growth,
        })
    return growths[-max_intervals:]


def _scenario_distribution(values, higher_is_better=True):
    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not values:
        return None
    high, middle, low = _quantile(values, 0.75), _quantile(values, 0.50), _quantile(values, 0.25)
    if higher_is_better:
        return {'optimistic': high, 'base': middle, 'stress': low}
    return {'optimistic': low, 'base': middle, 'stress': high}


def _latest_growth(rows):
    growths = _annualized_growths(rows)
    return growths[-1]['value'] if growths else None


def _apply_scenario_guardrails(driver, *, national_population_rows=None):
    """用透明边界补足短年度序列的尾部情景。

    这些边界仍然是 scenario，不是极值、置信区间或未来概率。它们避免只有一两个
    城市增速时，25/50/75 分位完全重合而让好坏情景失去结构差异。
    """
    if not driver:
        return driver
    values = driver.get('scenario_values') or {}
    key = driver.get('key')
    notes = []
    if key == 'income_growth':
        values['stress'] = min(float(values['stress']), 0.0)
        notes.append('压力档至少覆盖名义收入零增长')
    elif key == 'population_growth':
        national_latest = _latest_growth(national_population_rows or [])
        if national_latest is not None:
            values['stress'] = min(float(values['stress']), float(national_latest))
            notes.append('压力档至少覆盖全国最新人口降幅延续')
    elif key == 'marriage_growth':
        latest = driver.get('latest_growth')
        values['optimistic'] = max(float(values['optimistic']), 0.0)
        if latest is not None:
            values['stress'] = min(float(values['stress']), float(latest))
        notes.append('乐观档覆盖止跌，压力档保留历史下行及最新变动边界')
    elif key == 'sales_area_growth':
        latest = driver.get('latest_growth')
        values['optimistic'] = max(float(values['optimistic']), 0.0)
        if latest is not None:
            values['stress'] = min(float(values['stress']), float(latest))
        notes.append('乐观档至少覆盖销售面积止跌，压力档覆盖最新降幅延续')
    elif key == 'completion_sales_ratio':
        latest = driver.get('latest_value')
        values['optimistic'] = min(float(values['optimistic']), 1.0)
        if latest is not None:
            values['stress'] = max(float(values['stress']), float(latest))
        notes.append('乐观档覆盖供需比回到1，压力档覆盖最新供给比延续')
    elif key == 'lpr_change':
        values['stress'] = max(float(values['stress']), 0.0)
        notes.append('压力档至少覆盖5年期LPR不再同比下降')
    driver['scenario_values'] = {
        name: round(float(value), 4) for name, value in values.items()
    }
    if notes:
        driver['scenario_guardrail'] = '；'.join(notes)
    return driver


def _growth_driver(key, rows, scope, scope_label, indicator_code, higher_is_better=True):
    growths = _annualized_growths(rows)
    scenarios = _scenario_distribution([item['value'] for item in growths],
                                       higher_is_better=higher_is_better)
    if not rows or not scenarios:
        return None
    latest = rows[-1]
    rule = DRIVER_RULES[key]
    return {
        'key': key, 'label': rule['label'], 'role': 'model', 'metric_kind': 'growth_pct',
        'indicator_code': indicator_code, 'scope': scope, 'scope_label': scope_label,
        'latest_period': latest['period'], 'latest_value': round(float(latest['value']), 4),
        'unit': latest.get('unit'), 'latest_growth': round(growths[-1]['value'], 4),
        'scenario_values': {name: round(value, 4) for name, value in scenarios.items()},
        'n_obs': len(rows), 'n_growth_obs': len(growths),
        'sample_start': rows[0]['period'], 'sample_end': rows[-1]['period'],
        'growth_sample_start': growths[0]['start_period'],
        'growth_sample_end': growths[-1]['end_period'],
        'coefficient': rule['coefficient'], 'neutral': rule['neutral'],
        'contribution_cap_pp': rule['cap_pp'], 'explanation': rule['explanation'],
        'data_status': latest.get('data_status'), 'source_name': latest.get('source_name'),
        'source_url': latest.get('source_url'),
    }


def _fresh_enough(rows, price_year):
    return bool(rows and _year(rows[-1]['period']) is not None and
                _year(rows[-1]['period']) >= price_year - MAX_CITY_DRIVER_STALENESS_YEARS)


def _select_city_or_national_growth(conn, city, city_code, national_code, price_year,
                                    key, city_label, national_rows):
    city_rows = _read_city_indicator(conn, city, city_code)
    if len(city_rows) >= 2 and _fresh_enough(city_rows, price_year):
        driver = _growth_driver(key, city_rows, 'city', f'{city}本市', city_code)
        if driver:
            return driver
    driver = _growth_driver(key, national_rows, 'national_fallback',
                            f'全国回退（{city_label}缺少近期连续值）', national_code)
    if driver:
        driver['fallback_reason'] = (
            f'{city}{city_label}不足2个近期年点或最新期早于{price_year - 2}年。'
        )
    return driver


def _supply_driver(sales_rows, completion_rows, price_year):
    sales = {row['period']: row for row in sales_rows if float(row.get('value') or 0) > 0}
    completions = {row['period']: row for row in completion_rows
                   if float(row.get('value') or 0) > 0}
    common = sorted(set(sales) & set(completions))
    ratio_rows = [{
        'period': period,
        'value': float(completions[period]['value']) / float(sales[period]['value']),
        'unit': '倍', 'data_status': 'derived',
        'source_name': '城市统计年鉴/公报派生',
        'source_url': completions[period].get('source_url') or sales[period].get('source_url'),
    } for period in common]
    if len(ratio_rows) < 2 or not _fresh_enough(ratio_rows, price_year):
        return None
    recent = ratio_rows[-5:]
    scenarios = _scenario_distribution([row['value'] for row in recent],
                                       higher_is_better=False)
    latest = ratio_rows[-1]
    rule = DRIVER_RULES['completion_sales_ratio']
    return {
        'key': 'completion_sales_ratio', 'label': rule['label'], 'role': 'model',
        'metric_kind': 'level_ratio', 'indicator_code': 'completion_sales_ratio',
        'scope': 'city', 'scope_label': '本市派生', 'latest_period': latest['period'],
        'latest_value': round(latest['value'], 4), 'unit': '倍',
        'latest_growth': None,
        'scenario_values': {name: round(value, 4) for name, value in scenarios.items()},
        'n_obs': len(ratio_rows), 'n_growth_obs': 0,
        'sample_start': ratio_rows[0]['period'], 'sample_end': ratio_rows[-1]['period'],
        'coefficient': rule['coefficient'], 'neutral': rule['neutral'],
        'contribution_cap_pp': rule['cap_pp'], 'explanation': rule['explanation'],
        'data_status': 'derived', 'source_name': latest['source_name'],
        'source_url': latest['source_url'],
        'formula': 'housing_completed_area / commercial_housing_sold_area',
    }


def _lpr_driver(conn):
    columns = _table_columns(conn, 'china_rates_observations')
    if not {'indicator_code', 'period', 'value'} <= columns:
        return None
    optional = ('unit', 'data_status', 'source_name', 'source_url')
    select = ['period', 'value']
    select.extend(column if column in columns else f"NULL AS {column}" for column in optional)
    try:
        raw = [dict(row) for row in conn.execute(
            f'''SELECT {','.join(select)} FROM china_rates_observations
                WHERE indicator_code='LPR_5Y' ORDER BY period''')]
    except Exception:
        return None
    monthly = {}
    for row in raw:
        period = str(row.get('period') or '')[:7]
        if len(period) == 7 and row.get('value') is not None:
            row['period'] = period
            row['value'] = float(row['value'])
            monthly[period] = row
    changes = []
    for period in sorted(monthly):
        previous = f'{int(period[:4]) - 1:04d}{period[4:]}'
        if previous in monthly:
            changes.append({
                'period': period,
                'value': monthly[period]['value'] - monthly[previous]['value'],
            })
    changes = changes[-24:]
    scenarios = _scenario_distribution([row['value'] for row in changes],
                                       higher_is_better=False)
    if not monthly or not scenarios:
        return None
    latest = monthly[sorted(monthly)[-1]]
    rule = DRIVER_RULES['lpr_change']
    return {
        'key': 'lpr_change', 'label': rule['label'], 'role': 'model',
        'metric_kind': 'change_pp', 'indicator_code': 'LPR_5Y',
        'scope': 'national_common', 'scope_label': '全国共同融资条件',
        'latest_period': latest['period'], 'latest_value': latest['value'],
        'unit': latest.get('unit') or '%',
        'latest_growth': round(changes[-1]['value'], 4),
        'scenario_values': {name: round(value, 4) for name, value in scenarios.items()},
        'n_obs': len(monthly), 'n_growth_obs': len(changes),
        'sample_start': sorted(monthly)[0], 'sample_end': latest['period'],
        'coefficient': rule['coefficient'], 'neutral': rule['neutral'],
        'contribution_cap_pp': rule['cap_pp'], 'explanation': rule['explanation'],
        'data_status': latest.get('data_status'), 'source_name': latest.get('source_name'),
        'source_url': latest.get('source_url'),
        'formula': '当月5年期LPR - 上年同月5年期LPR（百分点）',
    }


def _context_level(rows, key, label, ambiguous_note):
    if not rows:
        return {'key': key, 'label': label, 'status': 'missing', 'role': 'context_only',
                'note': ambiguous_note}
    recent = [float(row['value']) for row in rows[-5:] if row.get('value') is not None]
    median = statistics.median(recent) if recent else None
    latest = rows[-1]
    versus = ((float(latest['value']) / median - 1.0) * 100.0
              if median and median > 0 else None)
    return {
        'key': key, 'label': label, 'status': 'ok', 'role': 'context_only',
        'latest_period': latest['period'], 'latest_value': float(latest['value']),
        'unit': latest.get('unit'), 'latest_vs_recent_median_pct': (
            round(versus, 2) if versus is not None else None),
        'n_obs': len(rows), 'sample_start': rows[0]['period'],
        'sample_end': rows[-1]['period'], 'data_status': latest.get('data_status'),
        'source_name': latest.get('source_name'), 'source_url': latest.get('source_url'),
        'note': ambiguous_note,
    }


def _context_growth(rows, key, label, ambiguous_note):
    driver = _growth_driver('income_growth', rows, 'city', '本市', key) if rows else None
    if not driver:
        return {'key': key, 'label': label, 'status': 'missing', 'role': 'context_only',
                'note': ambiguous_note}
    return {
        'key': key, 'label': label, 'status': 'ok', 'role': 'context_only',
        'latest_period': driver['latest_period'], 'latest_value': driver['latest_value'],
        'latest_growth': driver['latest_growth'], 'unit': driver['unit'],
        'n_obs': driver['n_obs'], 'sample_start': driver['sample_start'],
        'sample_end': driver['sample_end'], 'data_status': driver['data_status'],
        'source_name': driver['source_name'], 'source_url': driver['source_url'],
        'note': ambiguous_note,
    }


def _national_marriage_rate_rows(grouped):
    """用登记对数/年末人口派生粗结婚率（每千人结婚对数）。"""
    populations = {row['period']: row for row in grouped.get('national_population', [])}
    output = []
    for marriage in grouped.get('national_marriages', []):
        population = populations.get(marriage['period'])
        if not population or float(population['value']) <= 0:
            continue
        output.append({
            'indicator_code': 'national_crude_marriage_rate',
            'period': marriage['period'],
            'value': float(marriage['value']) / float(population['value']) * 1000.0,
            'unit': '‰', 'data_status': 'derived',
            'source_name': f"{marriage.get('source_name') or '结婚登记来源'}与国家统计局人口派生",
            'source_url': marriage['source_url'],
            'parser_notes': '结婚登记总对数(万对) / 年末人口(万人) × 1000。',
        })
    return output


def _national_history(grouped):
    codes = ('national_population', 'national_disposable_income', 'national_marriages')
    by_code = {code: {row['period']: row for row in grouped.get(code, [])} for code in codes}
    periods = sorted(set().union(*(set(rows) for rows in by_code.values())))
    output = []
    for period in periods:
        item = {'period': period}
        for code in codes:
            row = by_code[code].get(period)
            item[code] = row['value'] if row else None
            previous = by_code[code].get(str(int(period) - 1)) if row else None
            item[f'{code}_growth'] = (
                round((row['value'] / previous['value'] - 1.0) * 100.0, 4)
                if row and previous and previous['value'] > 0 else None)
        output.append(item)
    rates = {row['period']: row for row in _national_marriage_rate_rows(grouped)}
    for item in output:
        row = rates.get(item['period'])
        previous = rates.get(str(int(item['period']) - 1)) if row else None
        item['national_crude_marriage_rate'] = (
            round(row['value'], 4) if row else None)
        item['national_crude_marriage_rate_growth'] = (
            round((row['value'] / previous['value'] - 1.0) * 100.0, 4)
            if row and previous and previous['value'] > 0 else None)
    return output


def build_structural_driver_snapshot(conn, city, price_period,
                                     national_driver_path=None):
    """构建单城结构驱动快照；缺失驱动不按0伪装，而是从模型贡献中剔除。"""
    grouped = load_national_structural_drivers(
        str(national_driver_path) if national_driver_path else None)
    price_year = _year(price_period) or max(_year(row['period'])
                                             for row in grouped['national_population'])
    drivers = []
    income = _select_city_or_national_growth(
        conn, city, 'avg_wage', 'national_disposable_income', price_year,
        'income_growth', '平均工资', grouped['national_disposable_income'])
    population = _select_city_or_national_growth(
        conn, city, 'resident_population', 'national_population', price_year,
        'population_growth', '常住人口', grouped['national_population'])
    marriage = _growth_driver(
        'marriage_growth', [row for row in _national_marriage_rate_rows(grouped)
                            if _year(row['period']) <= price_year], 'national_common',
        '全国粗结婚率（派生）', 'national_crude_marriage_rate')
    for driver in (income, population, marriage):
        if driver:
            _apply_scenario_guardrails(
                driver, national_population_rows=grouped['national_population'])
            drivers.append(driver)

    sales_rows = _read_city_indicator(conn, city, 'commercial_housing_sold_area')
    completion_rows = _read_city_indicator(conn, city, 'housing_completed_area')
    if len(sales_rows) >= 2 and _fresh_enough(sales_rows, price_year):
        sales = _growth_driver('sales_area_growth', sales_rows, 'city', f'{city}本市',
                               'commercial_housing_sold_area')
        if sales:
            _apply_scenario_guardrails(sales)
            drivers.append(sales)
    supply = _supply_driver(sales_rows, completion_rows, price_year)
    if supply:
        _apply_scenario_guardrails(supply)
        drivers.append(supply)
    lpr = _lpr_driver(conn)
    if lpr:
        _apply_scenario_guardrails(lpr)
        drivers.append(lpr)

    jobs = _context_level(
        _read_city_indicator(conn, city, 'urban_new_jobs'), 'urban_new_jobs',
        '城镇新增就业', '就业流量受统计口径与年度任务影响，只展示，不机械规定房价方向。')
    deposits = _context_growth(
        _read_city_indicator(conn, city, 'household_deposits'), 'household_deposits',
        '住户存款余额', '存款增长既可能代表购房能力，也可能代表预防性储蓄，只展示，不入价格公式。')
    registered = _context_growth(
        _read_city_indicator(conn, city, 'registered_population'), 'registered_population',
        '户籍人口', '户籍人口受落户政策与行政口径影响，不等同于常住购房人口，只展示。')
    investment = _context_growth(
        _read_city_indicator(conn, city, 'real_estate_investment'),
        'real_estate_investment', '房地产开发投资',
        '投资下降既可能代表供给收缩，也可能代表开发商风险上升，方向不唯一，只展示。')
    students = _context_growth(
        _read_city_indicator(conn, city, 'college_students'), 'college_students',
        '普通高校在校学生', '在校学生不是常住购房需求，且毕业后去向未知，只作为人才供给背景。')
    context_drivers = [jobs, deposits, registered, investment, students]
    for item in context_drivers:
        if item.get('status') != 'ok':
            continue
        latest_year = _year(item.get('latest_period'))
        staleness = max(0, price_year - latest_year) if latest_year else None
        item['staleness_years'] = staleness
        item['is_stale'] = staleness is None or staleness > MAX_CITY_DRIVER_STALENESS_YEARS

    city_specific = sum(driver['scope'] == 'city' for driver in drivers)
    fallback = sum(driver['scope'] == 'national_fallback' for driver in drivers)
    missing_optional = []
    if not any(driver['key'] == 'sales_area_growth' for driver in drivers):
        missing_optional.append('商品房销售面积近期连续值')
    if not any(driver['key'] == 'completion_sales_ratio' for driver in drivers):
        missing_optional.append('竣工/销售同年供给比')
    return {
        'status': 'ok' if drivers else 'insufficient_data',
        'data_status': 'derived_scenario_input', 'city': city,
        'price_as_of': price_period, 'drivers': drivers,
        'context_drivers': context_drivers,
        'coverage': {
            'model_drivers_used': len(drivers), 'city_specific_used': city_specific,
            'national_fallback_used': fallback, 'missing_optional': missing_optional,
            'unavailable_comparable_fields': [
                '15城可比结婚登记/初婚序列', '15城可比出生与年龄结构序列',
                '15城可比家庭户数与户均人口序列', '城市住房库存与去化月数',
            ],
        },
        'national_history': _national_history(grouped),
        'rules': DRIVER_RULES,
        'method': (
            '每个年度驱动先取最近最多5个可比增速的75/50/25分位作为乐观/基准/压力，'
            '再用收入停滞、全国最新人口降幅、婚姻与销售最新降幅、LPR停止下降等透明边界'
            '补足小样本尾部；供给比和LPR因数值越低越有利，分位方向反转。各项按公开系数换算为年化百分点'
            '贡献；乐观/压力分别取其相对基准贡献的偏差，按用户选择的结构强度叠加到'
            '对应价格动能。基准动能不因重复计入已反映在价格中的宏观因素而改变。'),
        'caveats': [
            '结构层是机械压力测试，不是回归、因果识别或概率预测；系数没有统计显著性含义。',
            '粗结婚率由全国结婚登记总对数/年末人口派生，登记包含再婚，不等于新增住房需求；因此仅给低权重。',
            '城市平均工资不是家庭可支配收入；缺少近期城市工资时回退到全国居民人均可支配收入。',
            '常住人口优先使用城市自身数据；缺少近期连续值时回退到全国人口，不能反映城市净流入。',
            '5年期LPR不是每户实际按揭利率；商品房销售面积与竣工面积也可能存在统计范围变化。',
        ],
    }


def driver_contribution(driver, scenario_key):
    value = (driver.get('scenario_values') or {}).get(scenario_key)
    if value is None:
        return None
    raw = float(driver['coefficient']) * (float(value) - float(driver.get('neutral') or 0.0))
    cap = abs(float(driver.get('contribution_cap_pp') or 100.0))
    return round(_clamp(raw, -cap, cap), 4)


def build_structural_scenarios(series, momentum_scenarios, driver_snapshot,
                               structural_weight=DEFAULT_STRUCTURAL_WEIGHT):
    """用结构贡献相对基准的偏差扩展动能区间；weight=0 精确回到原路径。"""
    if not series:
        return []
    weight = _clamp(structural_weight, *STRUCTURAL_WEIGHT_BOUNDS)
    current = series[-1]
    peak = max(series, key=lambda item: item['index'])
    price_scale = (float(series[0].get('price')) / float(series[0]['index'])
                   if series[0].get('price') is not None else None)
    output = []
    by_key = {item.get('key'): item for item in momentum_scenarios if not item.get('status')}
    base_contributions = [driver_contribution(driver, 'base')
                          for driver in driver_snapshot.get('drivers') or []]
    base_fundamental = sum(value for value in base_contributions if value is not None)
    for key in SCENARIO_KEYS:
        momentum = by_key.get(key)
        if not momentum:
            continue
        contributions = []
        for driver in driver_snapshot.get('drivers') or []:
            contribution = driver_contribution(driver, key)
            if contribution is None:
                continue
            contributions.append({
                'key': driver['key'], 'label': driver['label'],
                'assumption': driver['scenario_values'][key],
                'metric_kind': driver['metric_kind'], 'unit': (
                    '%' if driver['metric_kind'] == 'growth_pct' else
                    '百分点' if driver['metric_kind'] == 'change_pp' else driver.get('unit')),
                'contribution_pp': contribution, 'scope': driver['scope'],
                'scope_label': driver['scope_label'],
            })
        fundamental = round(sum(item['contribution_pp'] for item in contributions), 4)
        momentum_annual = float(momentum['annualised'])
        structural_delta = round(weight * (fundamental - base_fundamental), 4)
        if abs(structural_delta) < 1e-12:
            # 0% 强度和基准档必须逐点精确回退，不因年化/月化二次换算产生尾差。
            adjusted_annual = momentum_annual
            monthly_rate = float(momentum['monthly_rate'])
            path = [dict(point) for point in (momentum.get('path') or [])]
        else:
            adjusted_annual = momentum_annual + structural_delta
            adjusted_annual = round(_clamp(adjusted_annual, -30.0, 30.0), 4)
            monthly_rate = ((1.0 + adjusted_annual / 100.0) ** (1.0 / 12.0) - 1.0) * 100.0
            index_value = float(current['index'])
            path = []
            for step in range(1, len(momentum.get('path') or []) + 1):
                index_value *= 1.0 + monthly_rate / 100.0
                point = {
                    'period': _add_months(current['period'], step),
                    'index': round(index_value, 4),
                }
                if price_scale is not None:
                    point['price'] = round(index_value * price_scale, 2)
                path.append(point)
        if not path:
            continue
        end = path[-1]['index']
        output.append({
            'key': key, 'label': f'{SCENARIO_LABELS[key]}（结构驱动修正）',
            'data_status': 'scenario', 'structural_weight': round(weight, 4),
            'momentum_weight': 1.0,
            'momentum_annualised': round(momentum_annual, 4),
            'fundamental_annualised': fundamental,
            'fundamental_base_annualised': round(base_fundamental, 4),
            'structural_delta_pp': structural_delta,
            'annualised': adjusted_annual, 'monthly_rate': round(monthly_rate, 4),
            'path': path, 'end_period': path[-1]['period'],
            'end_vs_peak': round((end / float(peak['index']) - 1.0) * 100.0, 2),
            'end_vs_now': round((end / float(current['index']) - 1.0) * 100.0, 2),
            'end_price': path[-1].get('price'), 'driver_contributions': contributions,
            'formula': ('adjusted annual rate = momentum annual rate + structural_weight × '
                        '(scenario driver contributions - base driver contributions)'),
        })
    return output
