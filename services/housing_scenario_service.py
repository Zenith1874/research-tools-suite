# -*- coding: utf-8 -*-
"""城市房价情景推演。

统计局 70 城指数是同质可比的定基环比序列，把环比连乘成定基指数后，
才能回答"较峰值跌了多少""再持有两年会怎样"这类问题——成交均价做不到，
它会被成交结构（如厦门岛内外占比变化）带偏。

三个情景不拍脑袋设定，各自锚定一段真实观测到的动能窗口：
  乐观 = 近 6 个月平均环比    基准 = 近 12 个月    压力 = 近 36 个月
好处是每个情景都可被证伪：只要后续月份公布，就能看出实际走在哪条线上。
窗口速度可被调用方覆盖，改假设即改结论。

也可切换到本机独立库中的安居客二手房挂牌均价。月度层保留真实月点，年度层
保留年度榜单/年末快照，二者不互相补缺。该口径只代表卖方要价，不是成交价
或官方同质指数；只在本机读取，不复制进主库或公开快照。

全部输出为 scenario（情景），不是预测。房价拐点取决于政策、信贷与人口
流动，这些变量不在本库内。
"""
import hashlib
import math
import random
import sqlite3
import statistics
from datetime import datetime

from services.anjuke_listing_service import (
    ADDED_FOCUS_CITIES as LISTING_ADDED_FOCUS_CITIES,
    CORE_FOCUS_CITIES as LISTING_CORE_FOCUS_CITIES,
    FOCUS_CITIES as LISTING_FOCUS_CITIES,
    build_anjuke_payload,
)
from services.housing_structural_driver_service import (
    DEFAULT_STRUCTURAL_WEIGHT,
    build_structural_driver_snapshot,
    build_structural_scenarios,
)
from services.housing_demographic_capacity_service import (
    build_demographic_capacity_payload,
    normalise_formation_adjustments,
)

MOM_INDICATORS = {'second': 'second_home_mom_idx', 'new': 'new_home_mom_idx'}
SOURCE_OFFICIAL = 'official'
SOURCE_ANJUKE = 'anjuke'
SOURCE_ANJUKE_YEARLY = 'anjuke_yearly'
VALID_SOURCES = (SOURCE_OFFICIAL, SOURCE_ANJUKE, SOURCE_ANJUKE_YEARLY)
DEFAULT_WINDOWS = {'optimistic': 6, 'base': 12, 'stress': 36}
YEARLY_TREND_WINDOWS = (36, 60, 120)
SCENARIO_LABELS = {'optimistic': '乐观', 'base': '基准', 'stress': '压力'}
SCENARIO_KEYS = ('optimistic', 'base', 'stress')
DEFAULT_HORIZON = 24
DEFAULT_DOWN_PAYMENT = 0.35
DEFAULT_SIMULATIONS = 5000
SIMULATION_LOOKBACK = 60
SIMULATION_BLOCK = 3
MAX_LISTING_FORWARD_FILL_MONTHS = 1
# 杠杆放大只在首付比落在常见区间时才有意义
DOWN_PAYMENT_BOUNDS = (0.15, 1.0)

# 2011 年 7 月襄樊正式更名襄阳。统计局历史表保留了两个名称，但它们是同一城市，
# 展示和连乘时必须合并，否则会把 70 城错误显示成 71 个名称。
CITY_ALIASES = {'襄樊': '襄阳'}
CITY_CODE_MAP = {
    '北京': '110100', '上海': '310100', '广州': '440100', '深圳': '440300',
    '厦门': '350200', '南京': '320100', '合肥': '340100', '常州': '320400',
    '苏州': '320500', '无锡': '320200', '武汉': '420100', '长沙': '430100',
    '成都': '510100', '杭州': '330100', '福州': '350100',
}
FOCUS_CITIES = ('北京', '上海', '广州', '深圳', '厦门', '南京', '合肥', '无锡')


def _add_months(period, months):
    year, month = int(period[:4]), int(period[5:7])
    total = year * 12 + (month - 1) + months
    return f'{total // 12:04d}-{total % 12 + 1:02d}'


def _period_ordinal(period):
    """把 YYYY-MM 转成可相减的月序号；用于不规则低频观测的真实时距。"""
    year, month = int(period[:4]), int(period[5:7])
    return year * 12 + month - 1


def _horizon_to_end_period(series, end_period):
    """按每条序列的最新观测计算到指定结束月的月数。"""
    if not end_period or not series:
        return None
    latest = series[-1].get('period')
    if not latest:
        return None
    return max(6, min(120, _period_ordinal(end_period) - _period_ordinal(latest)))


def _is_listing_source(source):
    return source in (SOURCE_ANJUKE, SOURCE_ANJUKE_YEARLY)


def _canonical_city(city):
    return CITY_ALIASES.get(city, city)


def _normalise_source(source):
    source = source or SOURCE_OFFICIAL
    if source not in VALID_SOURCES:
        raise ValueError('source 必须是 official、anjuke 或 anjuke_yearly')
    return source


def _city_query_names(city):
    canonical = _canonical_city(city)
    names = [canonical]
    names.extend(old for old, new in CITY_ALIASES.items() if new == canonical)
    return tuple(sorted(set(names)))


def _is_next_month(previous, current):
    return _add_months(previous, 1) == current


def _latest_contiguous_rows(rows):
    """只保留最新连续月段；缺月不桥接、不插值。"""
    if not rows:
        return []
    start = 0
    for index in range(1, len(rows)):
        if not _is_next_month(rows[index - 1][0], rows[index][0]):
            start = index
    return rows[start:]


def chain_index(rows, base=100.0):
    """环比(上月=100)连乘成定基指数；首月前一期为隐含基期 100。"""
    index, out = base, []
    for period, value in rows:
        index *= value / 100.0
        out.append({'period': period, 'index': round(index, 4)})
    return out


def price_level_index(rows, base=100.0):
    """把绝对挂牌均价归一为可供同一模型计算的指数，同时保留元/㎡原值。"""
    if not rows or not rows[0][1] or rows[0][1] <= 0:
        return []
    first_price = float(rows[0][1])
    return [
        {'period': period, 'index': round(float(price) / first_price * base, 4),
         'price': round(float(price), 2)}
        for period, price in rows if price is not None and float(price) > 0
    ]


def _forward_fill_isolated_listing_gaps(rows):
    """仅把两个真实观测之间恰好缺失的一个月以前值补齐。

    这是情景计算层的可撤销派生值，不回写安居客原始库；连续缺两个月及以上
    仍保持断点，防止把长时间缺失伪装成横盘。
    """
    filled = []
    for raw_row in rows:
        row = dict(raw_row)
        if filled:
            previous = filled[-1]
            if _add_months(previous['period'], 2) == row['period']:
                filled.append({
                    'city': row.get('city') or previous.get('city'),
                    'period': _add_months(previous['period'], 1),
                    'avg_price': float(previous['avg_price']),
                    'mom_pct': 0.0,
                    'yoy_pct': None,
                    'data_status': 'derived_imputed',
                    'source_url': None,
                    'fetched_at': None,
                    'raw_cached': None,
                    'imputed': True,
                    'imputation_method': 'previous_month_carry_forward',
                    'imputed_from_period': previous['period'],
                })
        row['imputed'] = False
        filled.append(row)
    return filled


def _listing_rows(listing_payload, city):
    """读取挂牌历史；孤立单月缺口以前值补，长缺口仍只取最新连续段。"""
    history = (listing_payload or {}).get('city_history') or {}
    raw_rows = []
    for row in history.get(city, []):
        price = row.get('avg_price')
        period = row.get('period')
        if not period or price is None or float(price) <= 0:
            continue
        raw_rows.append(dict(row))
    by_period = {row['period']: row for row in raw_rows}
    ordered = [by_period[period] for period in sorted(by_period)]
    filled = _forward_fill_isolated_listing_gaps(ordered)
    contiguous = _latest_contiguous_rows(
        [(row['period'], float(row['avg_price'])) for row in filled])
    keep_periods = {period for period, _ in contiguous}
    kept = [row for row in filled if row['period'] in keep_periods]
    series = price_level_index(contiguous)
    metadata = {row['period']: row for row in kept}
    for point in series:
        observation = metadata[point['period']]
        point['imputed'] = bool(observation.get('imputed'))
        point['data_status'] = observation.get('data_status')
    return kept, series


def _yearly_listing_rows(listing_payload, city):
    """读取安居客年度层，保留原始年点，不拆月、不前值补齐。"""
    history = (listing_payload or {}).get('yearly_history_by_city') or {}
    valid = []
    for raw_row in history.get(city, []):
        row = dict(raw_row)
        period, price = row.get('period'), row.get('avg_price')
        if not period or price is None or float(price) <= 0:
            continue
        row['avg_price'] = float(price)
        valid.append(row)
    by_period = {row['period']: row for row in valid}
    observations = [by_period[period] for period in sorted(by_period)]
    series = price_level_index(
        [(row['period'], row['avg_price']) for row in observations])
    metadata = {row['period']: row for row in observations}
    for point in series:
        observation = metadata[point['period']]
        point['data_status'] = observation.get('data_status')
        point['source_grain'] = observation.get('source_grain')
        point['year'] = observation.get('year') or int(point['period'][:4])
    return observations, series


def _load_listing_payload(listing_payload=None):
    """允许测试注入；生产环境只读被 gitignore 的独立本地挂牌库。"""
    return listing_payload if listing_payload is not None else build_anjuke_payload()


def monthly_momentum(series, months):
    """近 N 个月的复合月度速度（%）；固定外推可精确复现窗口首尾变化。"""
    if len(series) < months + 1:
        return None
    start = series[-months - 1]['index']
    end = series[-1]['index']
    if not start or end <= 0:
        return None
    return round(((end / start) ** (1.0 / months) - 1.0) * 100.0, 4)


def sparse_trailing_momentum(series, target_months):
    """用最接近目标回看期的真实低频观测，按实际经过月份折算复合月速。

    年度榜单常记在年末，而当年最新点可能是 7 月，因此“近 3 年”的真实时距
    可能是 31 或 43 个月。计算必须使用实际时距，不能假装每个年点恰隔 12 个月。
    """
    if len(series) < 2:
        return None
    end = series[-1]
    end_ordinal = _period_ordinal(end['period'])
    candidates = []
    for point in series[:-1]:
        elapsed = end_ordinal - _period_ordinal(point['period'])
        if elapsed <= 0 or not point.get('index') or end['index'] <= 0:
            continue
        candidates.append((abs(elapsed - int(target_months)), -elapsed, point, elapsed))
    if not candidates:
        return None
    _, _, start, elapsed = min(candidates, key=lambda item: (item[0], item[1]))
    rate = ((end['index'] / start['index']) ** (1.0 / elapsed) - 1.0) * 100.0
    return {
        'target_months': int(target_months), 'actual_months': elapsed,
        'start_period': start['period'], 'end_period': end['period'],
        'monthly_rate': round(rate, 4),
        'annualised': round(((1 + rate / 100.0) ** 12 - 1.0) * 100.0, 3),
    }


def build_sparse_scenarios(series, horizon=DEFAULT_HORIZON,
                           windows=YEARLY_TREND_WINDOWS, overrides=None):
    """以约 3/5/10 年真实年点趋势生成月度等价情景路径。

    历史仍只有年度观测；逐月值只出现在未来 scenario 路径中。低频趋势不运行
    月度重抽样与月度机械回测，避免把 16--17 个年点包装成高频证据。
    """
    overrides = overrides or {}
    candidates = [sparse_trailing_momentum(series, months) for months in windows]
    candidates = [item for item in candidates if item is not None]
    candidates.sort(key=lambda item: item['monthly_rate'], reverse=True)
    peak = max(series, key=lambda item: item['index'])
    current = series[-1]
    out = []
    for position, key in enumerate(SCENARIO_KEYS):
        if position >= len(candidates):
            out.append({'key': key, 'label': SCENARIO_LABELS[key],
                        'status': 'insufficient_history'})
            continue
        candidate = candidates[position]
        derived = candidate['monthly_rate']
        rate = float(overrides.get(key, derived))
        path = project(series, rate, horizon)
        end = path[-1]['index']
        target_years = candidate['target_months'] // 12
        out.append({
            'key': key,
            'label': (f'{SCENARIO_LABELS[key]}（自定义月速）' if key in overrides else
                      f'{SCENARIO_LABELS[key]}（锚定约 {target_years} 年趋势，实际'
                      f'{candidate["actual_months"]}个月）'),
            'window_months': candidate['actual_months'],
            'requested_window_months': candidate['target_months'],
            'window_start_period': candidate['start_period'],
            'monthly_rate': round(rate, 4),
            'derived_monthly_rate': derived,
            'overridden': key in overrides,
            'annualised': round(((1 + rate / 100.0) ** 12 - 1.0) * 100.0, 3),
            'path': path, 'end_period': path[-1]['period'],
            'end_vs_peak': round((end / peak['index'] - 1) * 100.0, 2),
            'end_vs_now': round((end / current['index'] - 1) * 100.0, 2),
        })
    valid = [item for item in out if item.get('monthly_rate') is not None]
    if any(valid[index]['monthly_rate'] < valid[index + 1]['monthly_rate']
           for index in range(len(valid) - 1)):
        raise ValueError('情景月速必须满足：乐观 ≥ 基准 ≥ 压力')
    for position, item in enumerate(valid):
        item['rank_by_rate'] = position + 1
    return out


def project(series, monthly_rate, horizon):
    """按固定月度速度外推；返回逐月路径。"""
    last = series[-1]
    path, index = [], last['index']
    for step in range(1, horizon + 1):
        index *= (1 + monthly_rate / 100.0)
        path.append({'period': _add_months(last['period'], step),
                     'index': round(index, 4)})
    return path


def _read_observations(conn, city, key):
    names = _city_query_names(city)
    marks = ','.join('?' for _ in names)
    rows = conn.execute(
        f'''SELECT city,period,value,data_status,source_name,source_url
            FROM housing_city_observations
            WHERE city IN ({marks}) AND indicator_code=? ORDER BY period,city''',
        (*names, MOM_INDICATORS[key])).fetchall()
    # 同一月理论上只有一条；如来源异常重复，优先保留规范名称，仍不制造重复月份。
    by_period = {}
    canonical = _canonical_city(city)
    for row in rows:
        item = dict(row)
        current = by_period.get(item['period'])
        if current is None or item['city'] == canonical:
            by_period[item['period']] = item
    ordered = [by_period[period] for period in sorted(by_period)]
    contiguous = _latest_contiguous_rows([(row['period'], row['value']) for row in ordered])
    keep_periods = {period for period, _ in contiguous}
    return [row for row in ordered if row['period'] in keep_periods]


def _read_series(conn, city, key):
    rows = _read_observations(conn, city, key)
    return chain_index([(row['period'], row['value']) for row in rows])


def build_scenarios(series, horizon=DEFAULT_HORIZON, windows=None, overrides=None):
    """把三个真实动能窗口按速度排序为乐观/基准/压力，再按固定月速外推。

    近 6 个月不天然等于乐观。先排序可以保证“乐观 >= 基准 >= 压力”始终成立；
    每档仍保留实际锚定的窗口，便于审计。overrides 是显式用户假设，若顺序矛盾
    直接拒绝，避免页面标签与数值相反。
    """
    windows = windows or DEFAULT_WINDOWS
    overrides = overrides or {}
    window_months = list(dict.fromkeys(windows.values() if isinstance(windows, dict)
                                       else windows))
    candidates = [{'window_months': months,
                   'rate': monthly_momentum(series, months)}
                  for months in window_months]
    candidates = [item for item in candidates if item['rate'] is not None]
    candidates.sort(key=lambda item: item['rate'], reverse=True)
    peak = max(series, key=lambda x: x['index'])
    current = series[-1]
    out = []
    for position, key in enumerate(SCENARIO_KEYS):
        if position >= len(candidates):
            out.append({'key': key, 'label': SCENARIO_LABELS[key],
                        'status': 'insufficient_history'})
            continue
        candidate = candidates[position]
        months, derived = candidate['window_months'], candidate['rate']
        rate = float(overrides.get(key, derived))
        path = project(series, rate, horizon)
        end = path[-1]['index']
        out.append({
            'key': key,
            'label': (f'{SCENARIO_LABELS[key]}（自定义月速）' if key in overrides else
                      f'{SCENARIO_LABELS[key]}（锚定近 {months} 个月动能）'),
            'window_months': months, 'monthly_rate': round(rate, 4),
            'derived_monthly_rate': derived,
            'overridden': key in overrides,
            'annualised': round(((1 + rate / 100) ** 12 - 1) * 100, 3),
            'path': path,
            'end_period': path[-1]['period'],
            'end_vs_peak': round((end / peak['index'] - 1) * 100, 2),
            'end_vs_now': round((end / current['index'] - 1) * 100, 2),
        })
    valid = [item for item in out if item.get('monthly_rate') is not None]
    if any(valid[index]['monthly_rate'] < valid[index + 1]['monthly_rate']
           for index in range(len(valid) - 1)):
        raise ValueError('情景月速必须满足：乐观 ≥ 基准 ≥ 压力')
    for position, item in enumerate(valid):
        item['rank_by_rate'] = position + 1
    return out


def _quantile(values, probability):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def simulate_sensitivity(series, base_monthly_rate, horizon,
                         simulations=DEFAULT_SIMULATIONS,
                         lookback=SIMULATION_LOOKBACK, block_size=SIMULATION_BLOCK,
                         seed=20260727):
    """围绕基准路径对近期月度扰动做固定种子的移动块重抽样。

    这是模型敏感性区间，不是统计置信区间，也不是概率预测。三个月块只用于保留
    很短的连续性；政策、信贷、人口等库外结构变量不会凭空进入模拟。
    """
    if len(series) < 25 or horizon < 1:
        return {'status': 'insufficient_history', 'data_status': 'scenario'}
    returns = [math.log(series[index]['index'] / series[index - 1]['index'])
               for index in range(1, len(series))
               if series[index - 1]['index'] > 0 and series[index]['index'] > 0]
    returns = returns[-min(lookback, len(returns)):]
    if len(returns) < max(12, block_size):
        return {'status': 'insufficient_history', 'data_status': 'scenario'}
    residual_mean = statistics.mean(returns)
    residuals = [value - residual_mean for value in returns]
    base_log_rate = math.log1p(base_monthly_rate / 100.0)
    simulations = max(100, min(10000, int(simulations)))
    block_size = max(1, min(int(block_size), len(residuals)))
    rng = random.Random(int(seed))
    values_by_step = [[] for _ in range(horizon)]
    current = series[-1]['index']
    max_start = len(residuals) - block_size
    for _ in range(simulations):
        shocks = []
        while len(shocks) < horizon:
            start = rng.randint(0, max_start) if max_start > 0 else 0
            shocks.extend(residuals[start:start + block_size])
        index_value = current
        for step, shock in enumerate(shocks[:horizon]):
            index_value *= math.exp(base_log_rate + shock)
            values_by_step[step].append(index_value)
    points = []
    for step, values in enumerate(values_by_step, 1):
        points.append({
            'period': _add_months(series[-1]['period'], step),
            'p10': round(_quantile(values, 0.10), 4),
            'p50': round(_quantile(values, 0.50), 4),
            'p90': round(_quantile(values, 0.90), 4),
        })
    end = points[-1]
    return {
        'status': 'ok', 'data_status': 'scenario', 'simulations': simulations,
        'lookback_months': len(returns), 'block_months': block_size, 'seed': int(seed),
        'points': points,
        'end_vs_now': {key: round((end[key] / current - 1) * 100, 2)
                       for key in ('p10', 'p50', 'p90')},
        'method': ('固定种子移动块重抽样：取最近可用月度对数变动，减去样本均值后形成'
                   f'扰动，以 {block_size} 个月块重抽样并叠加到基准月速；逐月报告 P10/P50/P90。'),
    }


def backtest_scenarios(series, horizon=24, step=3):
    """用每个历史时点当时可见的数据做机械回测；不使用未来信息设定速度。"""
    horizon = max(6, min(24, int(horizon)))
    first_end = max(DEFAULT_WINDOWS.values())
    evaluations = []
    for end_index in range(first_end, len(series) - horizon, max(1, int(step))):
        history = series[:end_index + 1]
        scenarios = build_scenarios(history, horizon)
        by_key = {item['key']: item for item in scenarios if not item.get('status')}
        if len(by_key) != 3:
            continue
        start_index = history[-1]['index']
        actual = series[end_index + horizon]
        predicted = {key: by_key[key]['path'][-1]['index'] for key in SCENARIO_KEYS}
        lower, upper = sorted((predicted['stress'], predicted['optimistic']))
        actual_change = (actual['index'] / start_index - 1) * 100
        base_change = (predicted['base'] / start_index - 1) * 100
        evaluations.append({
            'as_of': history[-1]['period'], 'target_period': actual['period'],
            'actual_change': round(actual_change, 2),
            'base_change': round(base_change, 2),
            'base_error': round(base_change - actual_change, 2),
            'base_abs_error': round(abs(base_change - actual_change), 2),
            'inside_scenario_envelope': lower <= actual['index'] <= upper,
            'direction_hit': ((base_change >= 0) == (actual_change >= 0)),
        })
    if not evaluations:
        return {'status': 'insufficient_history', 'data_status': 'derived',
                'horizon_months': horizon, 'n_obs': 0}
    return {
        'status': 'ok', 'data_status': 'derived', 'horizon_months': horizon,
        'evaluation_step_months': max(1, int(step)), 'n_obs': len(evaluations),
        'median_absolute_error_pp': round(statistics.median(
            item['base_abs_error'] for item in evaluations), 2),
        'envelope_coverage_pct': round(100 * statistics.mean(
            item['inside_scenario_envelope'] for item in evaluations), 1),
        'direction_hit_pct': round(100 * statistics.mean(
            item['direction_hit'] for item in evaluations), 1),
        'sample_start': evaluations[0]['as_of'],
        'sample_end': evaluations[-1]['target_period'],
        'latest': evaluations[-1],
        'method': ('每隔 3 个月选一个历史起点，只用该时点以前的数据重算三档动能，'
                   f'与随后 {horizon} 个月实际指数比较；这是机械规则回测，不是样本外预测检验。'),
    }


def equity_impact(series, scenarios, purchase_periods, down_payment=DEFAULT_DOWN_PAYMENT):
    """买入时点 × 情景的自有资金变动。

    价格跌 x%，首付比 d，则自有资金变动约 x/d —— 这是价格变动对权益的杠杆
    放大，未计已还本金与利息支出，因此不等于家庭净值变动。
    """
    if not (DOWN_PAYMENT_BOUNDS[0] <= down_payment <= DOWN_PAYMENT_BOUNDS[1]):
        down_payment = DEFAULT_DOWN_PAYMENT
    by_period = {item['period']: item['index'] for item in series}
    current = series[-1]['index']
    rows = []
    for period in purchase_periods:
        base = by_period.get(period)
        if not base:
            continue
        now_change = (current / base - 1) * 100
        entry = {'purchase_period': period, 'price_change_to_now': round(now_change, 2),
                 'equity_change_to_now': round(now_change / down_payment, 2),
                 'by_scenario': {}}
        for scenario in scenarios:
            if scenario.get('status') == 'insufficient_history':
                continue
            end = scenario['path'][-1]['index']
            change = (end / base - 1) * 100
            entry['by_scenario'][scenario['key']] = {
                'price_change': round(change, 2),
                'equity_change': round(change / down_payment, 2),
            }
        rows.append(entry)
    return {'down_payment': down_payment, 'rows': rows}


def valuation_anchor(conn, city_code, series, price_label='同质可比房价指数'):
    """房价指数 / 工资指数：判断相对收入是贵还是便宜，不单独用于推演。"""
    wages = {r[0]: r[1] for r in conn.execute(
        '''SELECT period,value FROM city_indicator_observations
           WHERE indicator_code='avg_wage' AND region_code=?''', (city_code,))}
    if not wages:
        return None
    yearly = {}
    for item in series:
        yearly[item['period'][:4]] = item['index']
    years = sorted(set(yearly) & set(wages))
    if len(years) < 3:
        return None
    base = years[0]
    points = [{'period': year,
               'ratio': round(yearly[year] / yearly[base] /
                              (wages[year] / wages[base]) * 100, 2)}
              for year in years]
    peak = max(points, key=lambda p: p['ratio'])
    last = points[-1]
    return {'base_year': base, 'points': points, 'peak': peak, 'latest': last,
            'latest_vs_peak': round((last['ratio'] / peak['ratio'] - 1) * 100, 2),
            'note': (f'{price_label}除以在岗职工平均工资指数；衡量相对收入的贵贱，'
                     '不预示价格拐点——估值便宜可以持续很久。'),
            'wage_end': years[-1]}


def _series_summary(series, scenarios):
    peak = max(series, key=lambda item: item['index'])
    current = series[-1]
    return {
        'peak': peak, 'current': current,
        'current_vs_peak': round((current['index'] / peak['index'] - 1) * 100, 2),
        'momentum': {f'{months}m': monthly_momentum(series, months)
                     for months in (6, 12, 24, 36)},
        'scenarios': scenarios,
    }


def _sparse_series_summary(series, scenarios):
    peak = max(series, key=lambda item: item['index'])
    current = series[-1]
    windows = {
        f'{months}m': sparse_trailing_momentum(series, months)
        for months in YEARLY_TREND_WINDOWS
    }
    return {
        'peak': peak, 'current': current,
        'current_vs_peak': round((current['index'] / peak['index'] - 1) * 100.0, 2),
        'momentum': {key: item['monthly_rate'] if item else None
                     for key, item in windows.items()},
        'momentum_windows': windows,
        'scenarios': scenarios,
    }


def _official_city_catalog(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute('''SELECT city,indicator_code,COUNT(*) records,
          MIN(period) sample_start,MAX(period) sample_end
          FROM housing_city_observations
          WHERE indicator_code IN ('new_home_mom_idx','second_home_mom_idx')
          GROUP BY city,indicator_code''').fetchall()
    finally:
        conn.close()
    merged = {}
    for row in rows:
        city = _canonical_city(row['city'])
        item = merged.setdefault(city, {'city': city, 'new_records': 0,
                                        'second_records': 0, 'sample_start': None,
                                        'sample_end': None})
        prefix = 'new' if row['indicator_code'] == MOM_INDICATORS['new'] else 'second'
        item[f'{prefix}_records'] += row['records']
        item['sample_start'] = min(filter(None, (item['sample_start'], row['sample_start'])))
        item['sample_end'] = max(filter(None, (item['sample_end'], row['sample_end'])))
    focus_rank = {city: index for index, city in enumerate(FOCUS_CITIES)}
    return sorted(merged.values(), key=lambda item: (
        0 if item['city'] in focus_rank else 1,
        focus_rank.get(item['city'], 999), item['city']))


def _listing_city_catalog(listing_payload):
    history = (listing_payload or {}).get('city_history') or {}
    focus_rank = {city: index for index, city in enumerate(LISTING_FOCUS_CITIES)}
    cities = []
    ordered_cities = list(LISTING_FOCUS_CITIES) + sorted(
        city for city in history if city not in focus_rank)
    for city in ordered_cities:
        valid = [row for row in history[city]
                 if row.get('period') and row.get('avg_price') is not None
                 and float(row['avg_price']) > 0] if city in history else []
        observations, series = _listing_rows(listing_payload, city)
        if not valid:
            cities.append({
                'city': city, 'status': 'missing', 'listing_records': 0,
                'contiguous_records': 0, 'imputed_records': 0,
                'imputed_periods': [], 'second_records': 0, 'new_records': 0,
                'available_start': None, 'sample_start': None, 'sample_end': None,
                'excluded_before_latest_gap': 0,
            })
            continue
        imputed = [row for row in observations if row.get('imputed')]
        retained_raw = sum(not row.get('imputed') for row in observations)
        cities.append({
            'city': city, 'status': 'available', 'listing_records': len(valid),
            'contiguous_records': len(series),
            'imputed_records': len(imputed),
            'imputed_periods': [row['period'] for row in imputed],
            'second_records': len(valid), 'new_records': 0,
            'available_start': min(row['period'] for row in valid),
            'sample_start': series[0]['period'] if series else None,
            'sample_end': series[-1]['period'] if series else None,
            'excluded_before_latest_gap': max(0, len(valid) - retained_raw),
        })
    return sorted(cities, key=lambda item: (
        0 if item['city'] in focus_rank else 1,
        focus_rank.get(item['city'], 999), item['city']))


def _listing_yearly_city_catalog(listing_payload):
    history = (listing_payload or {}).get('yearly_history_by_city') or {}
    focus_rank = {city: index for index, city in enumerate(LISTING_FOCUS_CITIES)}
    cities = []
    ordered_cities = list(LISTING_FOCUS_CITIES) + sorted(
        city for city in history if city not in focus_rank)
    for city in ordered_cities:
        observations, series = _yearly_listing_rows(listing_payload, city)
        if not series:
            cities.append({
                'city': city, 'status': 'missing', 'listing_records': 0,
                'annual_records': 0, 'second_records': 0, 'new_records': 0,
                'sample_start': None, 'sample_end': None, 'available_start': None,
                'source_grains': [], 'ranking_points': 0, 'imputed_records': 0,
            })
            continue
        grains = sorted(set(row.get('source_grain') for row in observations
                            if row.get('source_grain')))
        cities.append({
            'city': city, 'status': 'available', 'listing_records': len(series),
            'annual_records': len(series), 'second_records': len(series),
            'new_records': 0, 'sample_start': series[0]['period'],
            'sample_end': series[-1]['period'], 'available_start': series[0]['period'],
            'source_grains': grains,
            'ranking_points': sum(row.get('source_grain') == 'ranking_page_snapshot'
                                  for row in observations),
            'imputed_records': 0,
        })
    return sorted(cities, key=lambda item: (
        0 if item['city'] in focus_rank else 1,
        focus_rank.get(item['city'], 999), item['city']))


def list_housing_scenario_cities(db_path, source=SOURCE_OFFICIAL,
                                 listing_payload=None):
    """按来源返回城市目录；两套历史保持独立，绝不混接。"""
    source = _normalise_source(source)
    if source == SOURCE_ANJUKE:
        payload = _load_listing_payload(listing_payload)
        cities = _listing_city_catalog(payload)
        available = sum(item['status'] == 'available' for item in cities)
        notes = [
            '挂牌价是卖方要价，不是成交价；安居客为非官方商业平台参考口径。',
            '目录固定列出十五个关注城市；尚无可信记录的城市保留 missing，不从界面隐藏。',
            '缺月不插值，只用每个城市最新连续月段进行推演。',
            '挂牌数据库与原始页面仅保存在本机，不进入主库或公开仓库。',
        ]
        notes.extend(payload.get('warnings') or [])
        return {
            'generated_at': datetime.now().isoformat(),
            'source': SOURCE_ANJUKE, 'source_label': '安居客挂牌价·参考',
            'data_status': 'listing_reference', 'cities': cities,
            'city_count': len(cities), 'tracked_city_count': len(LISTING_FOCUS_CITIES),
            'available_city_count': available,
            'core_cities': list(LISTING_CORE_FOCUS_CITIES),
            'added_cities': list(LISTING_ADDED_FOCUS_CITIES),
            'missing_cities': [item['city'] for item in cities
                               if item['status'] == 'missing'],
            'latest_period': payload.get('latest_period'),
            'notes': notes,
        }
    if source == SOURCE_ANJUKE_YEARLY:
        payload = _load_listing_payload(listing_payload)
        cities = _listing_yearly_city_catalog(payload)
        available = sum(item['status'] == 'available' for item in cities)
        notes = [
            '年度目录列出十五个关注城市，包含后来增加的武汉、长沙、成都、杭州、福州；历史只保留真实年点。',
            '尚无可信记录的城市保留 missing，不从界面隐藏，也不以前值或其他城市代填。',
            '年度榜单快照按年份定位展示，不代表对应月份成交价；不拆成 12 个月、不前值补齐。',
            '未来情景按约 3/5/10 年真实观测间隔折算月速；低频样本不运行月度模拟或回测。',
            '挂牌数据库与原始页面仅保存在本机，不进入主库或公开仓库。',
        ]
        notes.extend(payload.get('warnings') or [])
        return {
            'generated_at': datetime.now().isoformat(),
            'source': SOURCE_ANJUKE_YEARLY,
            'source_label': '安居客年度快照·十五城目录',
            'data_status': 'listing_annual_reference', 'history_grain': 'annual',
            'cities': cities, 'city_count': len(cities),
            'tracked_city_count': len(LISTING_FOCUS_CITIES),
            'available_city_count': available,
            'core_cities': list(LISTING_CORE_FOCUS_CITIES),
            'added_cities': list(LISTING_ADDED_FOCUS_CITIES),
            'missing_cities': [item['city'] for item in cities
                               if item['status'] == 'missing'],
            'latest_period': max((item['sample_end'] for item in cities
                                  if item['sample_end']), default=None),
            'notes': notes,
        }
    cities = _official_city_catalog(db_path)
    return {
        'generated_at': datetime.now().isoformat(), 'source': SOURCE_OFFICIAL,
        'source_label': '国家统计局 70 城官方指数', 'data_status': 'official',
        'cities': cities, 'city_count': len(cities),
        'latest_period': max((item['sample_end'] for item in cities), default=None),
        'notes': ['襄樊（2011-01至06）与襄阳（2011-07起）按同一城市连续展示。'],
    }


def _comparison_row(city, series, horizon, source, driver_snapshot=None,
                    structural_weight=DEFAULT_STRUCTURAL_WEIGHT):
    minimum = 4 if source == SOURCE_ANJUKE_YEARLY else max(DEFAULT_WINDOWS.values()) + 1
    if len(series) < minimum:
        return {'city': city, 'status': 'insufficient_history',
                'n_obs': len(series),
                'sample_start': series[0]['period'] if series else None,
                'sample_end': series[-1]['period'] if series else None}
    scenarios = (build_sparse_scenarios(series, horizon)
                 if source == SOURCE_ANJUKE_YEARLY else
                 build_scenarios(series, horizon))
    if len([item for item in scenarios if not item.get('status')]) < 3:
        return {'city': city, 'status': 'insufficient_history',
                'n_obs': len(series), 'sample_start': series[0]['period'],
                'sample_end': series[-1]['period']}
    price_scale = (series[0].get('price') / series[0]['index']
                   if _is_listing_source(source) else None)
    _add_projected_prices(scenarios, {}, price_scale)
    summary = (_sparse_series_summary(series, scenarios)
               if source == SOURCE_ANJUKE_YEARLY else
               _series_summary(series, scenarios))
    structural = (_compact_structural_scenarios(
        series, scenarios, driver_snapshot, structural_weight)
        if driver_snapshot else [])
    return {
        'city': city, 'status': 'ok', 'sample_start': series[0]['period'],
        'sample_end': series[-1]['period'], 'n_obs': len(series),
        'current_vs_peak': summary['current_vs_peak'],
        'current_price': summary['current'].get('price'),
        'peak_period': summary['peak']['period'], 'source': source,
        'momentum': summary['momentum'],
        'momentum_windows': summary.get('momentum_windows'),
        'history_grain': 'annual' if source == SOURCE_ANJUKE_YEARLY else 'monthly',
        'structural_scenarios': structural,
        'driver_coverage': ((driver_snapshot or {}).get('coverage') or {}),
        'scenarios': [dict(
            {field: item[field] for field in
             ('key', 'label', 'window_months', 'monthly_rate',
              'annualised', 'end_period', 'end_vs_peak', 'end_vs_now')},
            requested_window_months=item.get('requested_window_months'),
            window_start_period=item.get('window_start_period'),
            end_price=item.get('end_price'))
            for item in scenarios if not item.get('status')],
    }


def build_housing_scenario_comparison(db_path, cities=None, kind='second',
                                      horizon=DEFAULT_HORIZON,
                                      source=SOURCE_OFFICIAL,
                                      listing_payload=None, end_period=None,
                                      structural_weight=DEFAULT_STRUCTURAL_WEIGHT,
                                      formation_adjustments=None):
    """多城市三档终值比较；不为每城运行重抽样，保持页面响应轻量。"""
    source = _normalise_source(source)
    if source == SOURCE_OFFICIAL and kind not in MOM_INDICATORS:
        raise ValueError('kind 必须是 second 或 new')
    kind = 'listing' if _is_listing_source(source) else kind
    horizon = max(6, min(120, int(horizon)))
    structural_weight = max(0.0, min(1.0, float(structural_weight)))
    formation_adjustments = normalise_formation_adjustments(formation_adjustments)
    default_cities = LISTING_FOCUS_CITIES if _is_listing_source(source) else FOCUS_CITIES
    selected = list(dict.fromkeys(_canonical_city(city) for city in
                                  (cities or default_cities)))[:20]
    rows = []
    if source == SOURCE_ANJUKE:
        payload = _load_listing_payload(listing_payload)
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            for city in selected:
                _, series = _listing_rows(payload, city)
                city_horizon = _horizon_to_end_period(series, end_period) or horizon
                drivers = (build_structural_driver_snapshot(
                    conn, city, series[-1]['period']) if series else None)
                rows.append(_comparison_row(
                    city, series, city_horizon, source, drivers, structural_weight))
        finally:
            conn.close()
        method_prefix = '安居客二手房挂牌均价（卖方要价）'
        history_status = 'listing_reference'
        method = (f'{method_prefix}：每城分别计算近 6/12/36 个月复合月速，按实际速度'
                  '从高到低标为乐观/基准/压力，再以固定月速复利外推。')
        history_grain = 'monthly'
    elif source == SOURCE_ANJUKE_YEARLY:
        payload = _load_listing_payload(listing_payload)
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            for city in selected:
                _, series = _yearly_listing_rows(payload, city)
                city_horizon = _horizon_to_end_period(series, end_period) or horizon
                drivers = (build_structural_driver_snapshot(
                    conn, city, series[-1]['period']) if series else None)
                rows.append(_comparison_row(
                    city, series, city_horizon, source, drivers, structural_weight))
        finally:
            conn.close()
        history_status = 'listing_annual_reference'
        history_grain = 'annual'
        method = ('安居客年度榜单/年末快照（卖方要价）：分别寻找最接近约 3/5/10 年'
                  '回看期的真实年点，按实际经过月份折算复合月速，排序后生成未来情景。'
                  '历史年点不拆月，月度模拟与回测不适用。')
    else:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            for city in selected:
                series = _read_series(conn, city, kind)
                city_horizon = _horizon_to_end_period(series, end_period) or horizon
                drivers = (build_structural_driver_snapshot(
                    conn, city, series[-1]['period']) if series else None)
                rows.append(_comparison_row(
                    city, series, city_horizon, source, drivers, structural_weight))
        finally:
            conn.close()
        method_prefix = '统计局 70 城同质可比月度指数'
        history_status = 'official'
        history_grain = 'monthly'
        method = (f'{method_prefix}：每城分别计算近 6/12/36 个月复合月速，按实际速度'
                  '从高到低标为乐观/基准/压力，再以固定月速复利外推。')
    if end_period:
        method += f'本次结束期固定为 {end_period}；各城市按自身最新连续观测期计算实际外推月数。'
    method += (f'另提供结构驱动修正路径：修正强度 {structural_weight * 100:.0f}%，'
               '把乐观/压力驱动贡献相对基准的偏差叠加到原价格动能；结构系数为公开'
               '压力测试假设。')
    # 长期人口层固定覆盖十五个关注城市，与当前房价来源是否有该城历史无关。
    # 这样安居客缺失不会被误读成人口容量缺失，反之亦然。
    demographic_conn = sqlite3.connect(db_path, timeout=30)
    demographic_conn.row_factory = sqlite3.Row
    try:
        try:
            demographic_capacity = build_demographic_capacity_payload(
                demographic_conn, formation_adjustments=formation_adjustments)
        except (OSError, ValueError) as exc:
            demographic_capacity = {
                'status': 'unavailable', 'data_status': 'missing',
                'error': str(exc), 'cities': [],
                'coverage': {'tracked_cities': 0, 'city_trend_cities': 0,
                             'national_fallback_cities': 0},
                'caveats': ['长期人口输入不可用；既有房价比较仍正常返回。'],
            }
    finally:
        demographic_conn.close()
    return {
        'generated_at': datetime.now().isoformat(), 'data_status': 'scenario',
        'history_data_status': history_status, 'source': source, 'kind': kind,
        'history_grain': history_grain, 'horizon_months': horizon,
        'end_period': end_period, 'structural_weight': structural_weight, 'rows': rows,
        'method': method, 'demographic_capacity': demographic_capacity,
    }


def _add_projected_prices(scenarios, simulation, price_scale):
    if price_scale is None:
        return
    for scenario in scenarios:
        for point in scenario.get('path') or []:
            point['price'] = round(point['index'] * price_scale, 2)
        path = scenario.get('path') or []
        scenario['end_price'] = path[-1]['price'] if path else None
    for point in simulation.get('points') or []:
        for key in ('p10', 'p50', 'p90'):
            point[f'{key}_price'] = round(point[key] * price_scale, 2)


def _attach_structural_series(series_payload, driver_snapshot, structural_weight):
    """给既有动能结果追加结构路径；原 scenarios 字段保持不变。"""
    if not series_payload or series_payload.get('status') != 'ok':
        return
    structural = build_structural_scenarios(
        series_payload['points'], series_payload.get('scenarios') or [],
        driver_snapshot, structural_weight=structural_weight)
    series_payload['structural_scenarios'] = structural
    purchase_periods = [row['purchase_period']
                        for row in (series_payload.get('equity') or {}).get('rows', [])]
    down_payment = (series_payload.get('equity') or {}).get(
        'down_payment', DEFAULT_DOWN_PAYMENT)
    series_payload['structural_equity'] = equity_impact(
        series_payload['points'], structural, purchase_periods, down_payment)


def _compact_structural_scenarios(series, scenarios, driver_snapshot,
                                  structural_weight):
    structural = build_structural_scenarios(
        series, scenarios, driver_snapshot, structural_weight=structural_weight)
    fields = ('key', 'label', 'monthly_rate', 'annualised', 'end_period',
              'end_vs_peak', 'end_vs_now', 'end_price', 'structural_weight',
              'momentum_annualised', 'fundamental_annualised',
              'fundamental_base_annualised', 'structural_delta_pp')
    return [{field: item.get(field) for field in fields} for item in structural]


def _build_series_payload(city, key, observations, series, horizon, overrides,
                          purchase_periods, down_payment, simulations, source):
    if len(series) < max(DEFAULT_WINDOWS.values()) + 1:
        return {
            'status': 'insufficient_history', 'n_obs': len(series),
            'sample_start': series[0]['period'] if series else None,
            'sample_end': series[-1]['period'] if series else None,
        }
    scenarios = build_scenarios(series, horizon, overrides=(overrides or {}).get(key))
    periods = purchase_periods or _default_purchase_periods(series)
    summary = _series_summary(series, scenarios)
    by_key = {item['key']: item for item in scenarios if not item.get('status')}
    seed_text = f'{source}|{city}|{key}|{series[-1]["period"]}|{horizon}'
    seed = int(hashlib.sha256(seed_text.encode('utf-8')).hexdigest()[:12], 16)
    simulation = simulate_sensitivity(
        series, by_key['base']['monthly_rate'], horizon,
        simulations=simulations, seed=seed)
    price_scale = (series[0].get('price') / series[0]['index']
                   if source == SOURCE_ANJUKE else None)
    _add_projected_prices(scenarios, simulation, price_scale)
    latest = observations[-1] if observations else {}
    imputed_periods = [row['period'] for row in observations if row.get('imputed')]
    source_info = {
        'name': ('安居客二手房挂牌价（非官方参考）' if source == SOURCE_ANJUKE
                 else latest.get('source_name')),
        'url': latest.get('source_url'), 'latest_period': latest.get('period'),
        'data_status': ('listing_reference' if source == SOURCE_ANJUKE
                        else latest.get('data_status')),
    }
    return {
        'status': 'ok', 'points': series, **summary,
        'n_obs': len(series), 'sample_start': series[0]['period'],
        'sample_end': series[-1]['period'], 'source': source_info,
        'value_kind': 'price_level' if source == SOURCE_ANJUKE else 'index',
        'unit': '元/㎡' if source == SOURCE_ANJUKE else '指数',
        'price_scale': round(price_scale, 6) if price_scale is not None else None,
        'imputation': {
            'count': len(imputed_periods), 'periods': imputed_periods,
            'method': 'previous_month_carry_forward',
            'max_gap_months': MAX_LISTING_FORWARD_FILL_MONTHS,
            'data_status': 'derived_imputed',
        },
        'equity': equity_impact(series, scenarios, periods, down_payment),
        'simulation': simulation, 'backtest': backtest_scenarios(series, horizon),
    }


def _build_yearly_series_payload(city, observations, series, horizon, overrides,
                                 purchase_periods, down_payment):
    """构建十五城年度目录；历史低频与未来月度 scenario 在字段中明确分开。"""
    if len(series) < 4:
        return {
            'status': 'insufficient_history', 'n_obs': len(series),
            'sample_start': series[0]['period'] if series else None,
            'sample_end': series[-1]['period'] if series else None,
            'history_grain': 'annual',
        }
    scenarios = build_sparse_scenarios(
        series, horizon, overrides=(overrides or {}).get('listing'))
    if len([item for item in scenarios if not item.get('status')]) < 3:
        return {
            'status': 'insufficient_history', 'n_obs': len(series),
            'sample_start': series[0]['period'], 'sample_end': series[-1]['period'],
            'history_grain': 'annual',
        }
    summary = _sparse_series_summary(series, scenarios)
    price_scale = series[0].get('price') / series[0]['index']
    _add_projected_prices(scenarios, {}, price_scale)
    periods = purchase_periods or _default_yearly_purchase_periods(series)
    latest = observations[-1] if observations else {}
    source_grains = sorted(set(row.get('source_grain') for row in observations
                                if row.get('source_grain')))
    return {
        'status': 'ok', 'points': series, **summary,
        'n_obs': len(series), 'sample_start': series[0]['period'],
        'sample_end': series[-1]['period'], 'history_grain': 'annual',
        'observation_unit': '年点',
        'source': {
            'name': '安居客年度城市挂牌均价快照（非官方参考）',
            'url': latest.get('detail_url') or latest.get('source_url'),
            'latest_period': latest.get('period'),
            'data_status': latest.get('data_status') or 'listing_annual_reference',
            'source_grain': latest.get('source_grain'),
            'source_grains': source_grains,
        },
        'value_kind': 'price_level', 'unit': '元/㎡',
        'price_scale': round(price_scale, 6),
        'imputation': {
            'count': 0, 'periods': [], 'method': None,
            'data_status': None,
        },
        'equity': equity_impact(series, scenarios, periods, down_payment),
        'simulation': {
            'status': 'not_applicable', 'data_status': 'not_applicable',
            'reason': '年度层仅有 16–17 个真实年点，不把低频样本伪装成月度样本做重抽样。',
        },
        'backtest': {
            'status': 'not_applicable', 'data_status': 'not_applicable',
            'n_obs': 0,
            'reason': '年度层样本较少且部分城市存在榜单快照与年末月点口径切换，不运行月度机械回测。',
        },
    }


def build_housing_scenario_payload(db_path, city, horizon=DEFAULT_HORIZON,
                                   overrides=None, down_payment=DEFAULT_DOWN_PAYMENT,
                                   purchase_periods=None, city_code=None,
                                   simulations=DEFAULT_SIMULATIONS,
                                   source=SOURCE_OFFICIAL,
                                   listing_payload=None, end_period=None,
                                   structural_weight=DEFAULT_STRUCTURAL_WEIGHT):
    source = _normalise_source(source)
    city = _canonical_city(city)
    horizon = max(6, min(120, int(horizon)))
    structural_weight = max(0.0, min(1.0, float(structural_weight)))
    history_status = {
        SOURCE_OFFICIAL: 'official',
        SOURCE_ANJUKE: 'listing_reference',
        SOURCE_ANJUKE_YEARLY: 'listing_annual_reference',
    }[source]
    result = {'city': city, 'generated_at': datetime.now().isoformat(),
              'data_status': 'scenario', 'history_source': source,
              'history_data_status': history_status,
              'history_grain': ('annual' if source == SOURCE_ANJUKE_YEARLY else 'monthly'),
              'horizon_months': horizon, 'end_period': end_period,
              'structural_weight': structural_weight, 'series': {}}
    anchor = None
    if source == SOURCE_ANJUKE:
        payload = _load_listing_payload(listing_payload)
        observations, series = _listing_rows(payload, city)
        horizon = _horizon_to_end_period(series, end_period) or horizon
        result['horizon_months'] = horizon
        result['series']['listing'] = _build_series_payload(
            city, 'listing', observations, series, horizon, overrides,
            purchase_periods, down_payment, simulations, source)
        result['available_sample_start'] = (
            min((row.get('period') for row in
                 (payload.get('city_history') or {}).get(city, []) if row.get('period')),
                default=None))
    elif source == SOURCE_ANJUKE_YEARLY:
        payload = _load_listing_payload(listing_payload)
        observations, series = _yearly_listing_rows(payload, city)
        horizon = _horizon_to_end_period(series, end_period) or horizon
        result['horizon_months'] = horizon
        result['series']['listing'] = _build_yearly_series_payload(
            city, observations, series, horizon, overrides,
            purchase_periods, down_payment)
        result['available_sample_start'] = (
            min((row.get('period') for row in
                 (payload.get('yearly_history_by_city') or {}).get(city, [])
                 if row.get('period')), default=None))
    else:
        # 工资锚只允许使用后端已知的城市码，避免 city 与任意 city_code 被错配。
        city_code = CITY_CODE_MAP.get(city)
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            effective_horizons = []
            for key in MOM_INDICATORS:
                observations = _read_observations(conn, city, key)
                series = chain_index([(row['period'], row['value']) for row in observations])
                series_horizon = _horizon_to_end_period(series, end_period) or horizon
                effective_horizons.append(series_horizon)
                result['series'][key] = _build_series_payload(
                    city, key, observations, series, series_horizon, overrides,
                    purchase_periods, down_payment, simulations, source)
            if effective_horizons:
                result['horizon_months'] = effective_horizons[0]
            if city_code and result['series'].get('second', {}).get('status') == 'ok':
                anchor = valuation_anchor(conn, city_code, result['series']['second']['points'])
        finally:
            conn.close()
    # 人口、收入、婚姻、销售/竣工与LPR统一在价格序列建成后接入。这样三种历史
    # 来源共用同一结构口径，同时原始动能 scenarios 字段保持完全可回退。
    primary_key = 'listing' if _is_listing_source(source) else 'second'
    primary = result['series'].get(primary_key) or {}
    driver_snapshot = None
    if primary.get('status') == 'ok':
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            driver_snapshot = build_structural_driver_snapshot(
                conn, city, primary['sample_end'])
            for series_payload in result['series'].values():
                _attach_structural_series(
                    series_payload, driver_snapshot, structural_weight)
            known_city_code = CITY_CODE_MAP.get(city)
            if known_city_code:
                price_label = ('安居客挂牌价指数' if _is_listing_source(source)
                               else '统计局同质可比房价指数')
                anchor = valuation_anchor(
                    conn, known_city_code, primary['points'], price_label=price_label)
        finally:
            conn.close()
    result['structural_drivers'] = driver_snapshot or {
        'status': 'insufficient_data', 'drivers': [], 'context_drivers': [],
        'coverage': {'model_drivers_used': 0, 'city_specific_used': 0,
                     'national_fallback_used': 0, 'missing_optional': []},
        'national_history': [], 'caveats': ['价格历史不足，未运行结构驱动层。'],
    }
    result['valuation_anchor'] = anchor
    result['caveats'] = [
        '本模块全部为情景推演（scenario），不是预测。',
        '自有资金变动为价格变动的杠杆放大，未计已还本金与利息支出，不等于家庭净值变动。',
        ('结构修正层已纳入可取得的人口、收入、婚姻、住房量供给和LPR，但仍不包含'
         '政策突变、购房限制、城市内部迁移、库存去化周期和家庭资产负债表。'),
        ('结构修正强度为可调情景参数；设为0%即退回原价格动能路径。各驱动系数是公开的'
         '机械压力测试假设，不是回归估计。'),
    ]
    result['caveats'].extend((driver_snapshot or {}).get('caveats') or [])
    if source == SOURCE_ANJUKE:
        listing_series = result['series'].get('listing') or {}
        imputation = listing_series.get('imputation') or {}
        result['caveats'].extend([
            '近 6/12/36 个月复合月速按实际高低排序为乐观/基准/压力，因此不同城市对应的'
            '锚定窗口可能不同。',
            'P10/P50/P90 是围绕基准路径、对近期月度扰动做固定种子移动块重抽样得到的模型'
            '敏感性区间，不是统计置信区间，也不代表真实发生概率。',
            '安居客为商业平台；挂牌均价是卖方要价，不是成交价，也不是统计局同质可比指数。',
            '官方指数与挂牌价是两套独立路径，不拼接、不互相补缺，也不直接比较绝对点位。',
            '挂牌数据只从本机独立且被 gitignore 的 housing_listing.db 读取，不写入主库或公开快照。',
        ])
        if imputation.get('count'):
            periods = '、'.join(imputation['periods'])
            result['caveats'].append(
                f'情景计算层对孤立单月缺口采用前值法：{periods} 沿用前一月挂牌价，'
                '记为 derived_imputed 和 0% 月变动；不回写原始挂牌库。连续缺失两个月及以上不补。')
        result['method'] = {
            'index': ('安居客月度挂牌均价按最新连续段首月归一为 100，并保留元/㎡原值；'
                      '仅孤立单月缺口以前值法补齐并明确标记，长缺口不桥接。'),
            'scenario': ('近 6/12/36 月挂牌均价首尾变化折算为复合月速，按速度高/中/低分别'
                         '作为乐观/基准/压力，并按固定月速复利外推。'),
            'structural': (driver_snapshot or {}).get('method'),
            'status': 'scenario',
        }
    elif source == SOURCE_ANJUKE_YEARLY:
        result['caveats'].extend([
            '年度层面向十五城长期覆盖；有真实年点的城市才推演，缺失城市明确标记 missing；'
            '历史观测不拆月、不前值补齐，折线只连接已有年点。',
            '约 3/5/10 年趋势均按所选两个真实观测之间的实际月份折算月速，再按速度高低排序为'
            '乐观/基准/压力；逐月值只存在于未来 scenario 路径。',
            '年度历史可能混合“年度榜单快照”和“月度序列年末点”，榜单年份定位不等同于'
            '当年 12 月成交价；页面披露 source_grain，不把两者伪装成统一月度口径。',
            '年度低频年点不足以支持月度移动块模拟与月度机械回测，因此这两项明确标为'
            'not_applicable，而不是补造样本。',
            '安居客为商业平台；挂牌均价是卖方要价，不是成交价，也不是统计局同质可比指数。',
            '挂牌数据只从本机独立且被 gitignore 的 housing_listing.db 读取，不写入主库或公开快照。',
        ])
        result['method'] = {
            'index': ('安居客年度榜单/年末快照按真实观测期保留，首个年点归一为 100 并同时保留'
                      '元/㎡；缺年保持缺失，不拆分为月度。'),
            'scenario': ('寻找最接近约 3/5/10 年回看期的真实年点，按实际经过月份计算复合月速，'
                         '排序后作为乐观/基准/压力，并只对未来按固定月速复利外推。'),
            'structural': (driver_snapshot or {}).get('method'),
            'status': 'scenario',
        }
    else:
        result['caveats'].extend([
            '近 6/12/36 个月复合月速按实际高低排序为乐观/基准/压力，因此不同城市对应的'
            '锚定窗口可能不同。',
            'P10/P50/P90 是围绕基准路径、对近期月度扰动做固定种子移动块重抽样得到的模型'
            '敏感性区间，不是统计置信区间，也不代表真实发生概率。',
            '统计局 70 城为同质可比指数，已剔除成交结构影响；与成交均价或商业平台挂牌价'
            '不是同一口径，数值不可互换。',
            '估值锚只说明相对收入的贵贱，便宜可以持续很久。',
        ])
        result['method'] = {
            'index': '统计局月度环比指数（上月=100）逐月连乘；缺月不桥接，仅用最新连续段。',
            'scenario': ('近 6/12/36 月首尾变化折算为复合月速，按速度高/中/低分别作为'
                         '乐观/基准/压力，并按固定月速复利外推。'),
            'structural': (driver_snapshot or {}).get('method'),
            'status': 'scenario',
        }
    return result


def _default_purchase_periods(series):
    """默认给出峰值月与其前后若干年的年中，覆盖典型买入时点。"""
    peak = max(series, key=lambda x: x['index'])['period']
    available = {item['period'] for item in series}
    candidates = [peak]
    last_year = int(series[-1]['period'][:4])
    for year in range(last_year - 7, last_year + 1):
        candidates.append(f'{year}-06')
    return [p for p in sorted(set(candidates)) if p in available]


def _default_yearly_purchase_periods(series):
    """年度层只列真实观察期；默认展示最近八个年点并保留历史峰值。"""
    if not series:
        return []
    peak = max(series, key=lambda item: item['index'])['period']
    recent = [item['period'] for item in series[-8:]]
    return sorted(set([peak, *recent]))
