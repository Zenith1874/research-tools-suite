# -*- coding: utf-8 -*-
"""城市房价情景推演。

统计局 70 城指数是同质可比的定基环比序列，把环比连乘成定基指数后，
才能回答"较峰值跌了多少""再持有两年会怎样"这类问题——成交均价做不到，
它会被成交结构（如厦门岛内外占比变化）带偏。

三个情景不拍脑袋设定，各自锚定一段真实观测到的动能窗口：
  乐观 = 近 6 个月平均环比    基准 = 近 12 个月    压力 = 近 36 个月
好处是每个情景都可被证伪：只要后续月份公布，就能看出实际走在哪条线上。
窗口速度可被调用方覆盖，改假设即改结论。

全部输出为 scenario（情景），不是预测。房价拐点取决于政策、信贷与人口
流动，这些变量不在本库内。
"""
import sqlite3
import statistics
from datetime import datetime

MOM_INDICATORS = {'second': 'second_home_mom_idx', 'new': 'new_home_mom_idx'}
DEFAULT_WINDOWS = {'optimistic': 6, 'base': 12, 'stress': 36}
WINDOW_LABELS = {'optimistic': '乐观（近 6 个月动能）',
                 'base': '基准（近 12 个月动能）',
                 'stress': '压力（近 36 个月动能）'}
DEFAULT_HORIZON = 24
DEFAULT_DOWN_PAYMENT = 0.35
# 杠杆放大只在首付比落在常见区间时才有意义
DOWN_PAYMENT_BOUNDS = (0.15, 1.0)


def _add_months(period, months):
    year, month = int(period[:4]), int(period[5:7])
    total = year * 12 + (month - 1) + months
    return f'{total // 12:04d}-{total % 12 + 1:02d}'


def chain_index(rows, base=100.0):
    """环比(=100 基)连乘成定基指数；首月即基期。"""
    index, out = base, []
    for period, value in rows:
        index *= value / 100.0
        out.append({'period': period, 'index': round(index, 4)})
    return out


def monthly_momentum(series, months):
    """近 N 个月的平均月度变动（%）。样本不足返回 None。"""
    if len(series) < months + 1:
        return None
    changes = []
    for i in range(len(series) - months, len(series)):
        prev = series[i - 1]['index']
        if prev:
            changes.append((series[i]['index'] / prev - 1) * 100)
    return round(statistics.mean(changes), 4) if changes else None


def project(series, monthly_rate, horizon):
    """按固定月度速度外推；返回逐月路径。"""
    last = series[-1]
    path, index = [], last['index']
    for step in range(1, horizon + 1):
        index *= (1 + monthly_rate / 100.0)
        path.append({'period': _add_months(last['period'], step),
                     'index': round(index, 4)})
    return path


def _read_series(conn, city, key):
    rows = conn.execute(
        '''SELECT period,value FROM housing_city_observations
           WHERE city=? AND indicator_code=? ORDER BY period''',
        (city, MOM_INDICATORS[key])).fetchall()
    return chain_index([(r[0], r[1]) for r in rows])


def build_scenarios(series, horizon=DEFAULT_HORIZON, windows=None, overrides=None):
    """三个情景各锚定一段观测窗口；overrides 用月度百分比覆盖某一档速度。"""
    windows = windows or DEFAULT_WINDOWS
    overrides = overrides or {}
    peak = max(series, key=lambda x: x['index'])
    current = series[-1]
    out = []
    for key, months in windows.items():
        derived = monthly_momentum(series, months)
        rate = overrides.get(key, derived)
        if rate is None:
            out.append({'key': key, 'label': WINDOW_LABELS.get(key, key),
                        'status': 'insufficient_history'})
            continue
        path = project(series, rate, horizon)
        end = path[-1]['index']
        out.append({
            'key': key, 'label': WINDOW_LABELS.get(key, key),
            'window_months': months, 'monthly_rate': round(rate, 4),
            'derived_monthly_rate': derived,
            'overridden': key in overrides,
            'annualised': round(((1 + rate / 100) ** 12 - 1) * 100, 3),
            'path': path,
            'end_period': path[-1]['period'],
            'end_vs_peak': round((end / peak['index'] - 1) * 100, 2),
            'end_vs_now': round((end / current['index'] - 1) * 100, 2),
        })
    # 速度高者为乐观：窗口口径若反直觉，按实际速度重排，避免标签与数值打架
    ranked = sorted([s for s in out if s.get('monthly_rate') is not None],
                    key=lambda s: -s['monthly_rate'])
    for position, item in enumerate(ranked):
        item['rank_by_rate'] = position + 1
    return out


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


def valuation_anchor(conn, city_code, series):
    """房价指数 / 工资指数：判断相对收入是贵还是便宜，不用于推演。"""
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
            'note': ('同质可比房价指数除以在岗职工平均工资指数；衡量相对收入的贵贱，'
                     '不预示价格拐点——估值便宜可以持续很久。'),
            'wage_end': years[-1]}


def build_housing_scenario_payload(db_path, city, horizon=DEFAULT_HORIZON,
                                   overrides=None, down_payment=DEFAULT_DOWN_PAYMENT,
                                   purchase_periods=None, city_code=None):
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        result = {'city': city, 'generated_at': datetime.now().isoformat(),
                  'data_status': 'scenario', 'horizon_months': horizon, 'series': {}}
        for key in MOM_INDICATORS:
            series = _read_series(conn, city, key)
            if len(series) < 13:
                result['series'][key] = {'status': 'insufficient_history'}
                continue
            peak = max(series, key=lambda x: x['index'])
            current = series[-1]
            scenarios = build_scenarios(series, horizon, overrides=(overrides or {}).get(key))
            periods = purchase_periods or _default_purchase_periods(series)
            result['series'][key] = {
                'status': 'ok', 'points': series,
                'peak': peak, 'current': current,
                'current_vs_peak': round((current['index'] / peak['index'] - 1) * 100, 2),
                'momentum': {f'{m}m': monthly_momentum(series, m) for m in (6, 12, 24, 36)},
                'scenarios': scenarios,
                'equity': equity_impact(series, scenarios, periods, down_payment),
            }
        anchor = None
        if city_code and result['series'].get('second', {}).get('status') == 'ok':
            anchor = valuation_anchor(conn, city_code, result['series']['second']['points'])
        result['valuation_anchor'] = anchor
    finally:
        conn.close()
    result['caveats'] = [
        '本模块全部为情景推演（scenario），不是预测。三档速度各锚定一段真实观测窗口，'
        '后续月份公布即可验证实际走在哪条线上。',
        '统计局 70 城为同质可比指数，已剔除成交结构影响；与成交均价（如厦门受岛内外'
        '成交占比变化影响）不是同一口径，数值不可互换。',
        '自有资金变动为价格变动的杠杆放大，未计已还本金与利息支出，不等于家庭净值变动。',
        '房价拐点取决于政策、信贷与人口流动，这些变量不在本库内；估值锚只说明相对'
        '收入的贵贱，便宜可以持续很久。',
    ]
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
