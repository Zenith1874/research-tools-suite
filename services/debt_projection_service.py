# -*- coding: utf-8 -*-
"""债务"时间上限"推演：两条互相独立的约束线。

A 限额约束：余额与限额各按近年复合增速外推，剩余空间哪年归零。
  归零不等于违约，而是"必须再次提高限额"的时点——限额是政策变量，
  这条线量的是当前节奏还能在现行额度框架内跑多久。
B 付息压力：债务付息支出与一般公共预算收入各按近年复合增速外推，
  付息占收入比重哪年触及 10%/15%/20%。阈值是主观设定，不是官方红线。

全部输出为 scenario（情景推演），不是预测，更不是官方数字。
每条结果都带假设、基期与增速，改假设就应改结论。
"""
import sqlite3
from datetime import datetime

from services.debt_ceiling_service import build_ceiling_payload

DEFAULT_HORIZON = 25          # 最多外推 25 年，超出则报"本世纪中叶前不触及"
THRESHOLDS = (0.10, 0.15, 0.20)


def _cagr(first, last, years):
    if not first or not last or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def annual_yearend(conn, table, indicator_code):
    """月度 YTD 序列取每年 12 月值作为年度值。"""
    rows = conn.execute(
        f'SELECT period,value FROM {table} WHERE indicator_code=? ORDER BY period',
        (indicator_code,)).fetchall()
    return {period[:4]: value for period, value in rows if period.endswith('-12')}


def project_limit_constraint(years, window=4, horizon=DEFAULT_HORIZON, overrides=None):
    """余额与限额各自外推，找剩余空间归零的年份。

    overrides 形如 {'treasury_balance_growth': 0.10}：用户指定增速时覆盖历史推算值，
    并在结果里记下哪些增速是人为设定的，页面据此标注"已改假设"。
    """
    overrides = overrides or {}
    out = {}
    for prefix, limit_key, balance_key in (
            ('treasury', 'treasury_limit', 'treasury_balance'),
            ('local', 'local_limit', 'local_balance')):
        usable = [y for y in years
                  if y.get(limit_key) is not None and y.get(balance_key) is not None]
        usable = usable[-window:]
        if len(usable) < 2:
            out[prefix] = {'status': 'insufficient_history'}
            continue
        span = int(usable[-1]['period']) - int(usable[0]['period'])
        limit_growth = _cagr(usable[0][limit_key], usable[-1][limit_key], span)
        balance_growth = _cagr(usable[0][balance_key], usable[-1][balance_key], span)
        base_year = int(usable[-1]['period'])
        limit, balance = usable[-1][limit_key], usable[-1][balance_key]
        if limit_growth is None or balance_growth is None:
            out[prefix] = {'status': 'insufficient_history'}
            continue
        derived = {'limit_growth': limit_growth, 'balance_growth': balance_growth}
        custom = []
        for key in ('limit_growth', 'balance_growth'):
            value = overrides.get(f'{prefix}_{key}')
            if value is not None:
                custom.append(key)
                if key == 'limit_growth':
                    limit_growth = value
                else:
                    balance_growth = value
        path, hit_year = [], None
        for step in range(0, horizon + 1):
            projected_limit = limit * (1 + limit_growth) ** step
            projected_balance = balance * (1 + balance_growth) ** step
            headroom = projected_limit - projected_balance
            path.append({'period': str(base_year + step),
                         'limit': round(projected_limit, 2),
                         'balance': round(projected_balance, 2),
                         'headroom': round(headroom, 2),
                         'utilisation': round(projected_balance / projected_limit * 100, 3)})
            if hit_year is None and headroom <= 0 and step > 0:
                hit_year = base_year + step
        out[prefix] = {
            'status': 'projected', 'base_year': str(base_year),
            'base_limit': limit, 'base_balance': balance,
            'base_utilisation': round(balance / limit * 100, 3),
            'limit_growth': round(limit_growth, 6), 'balance_growth': round(balance_growth, 6),
            'derived_limit_growth': round(derived['limit_growth'], 6),
            'derived_balance_growth': round(derived['balance_growth'], 6),
            'overridden': custom,
            'window_years': span, 'hit_year': str(hit_year) if hit_year else None,
            'path': path,
            'note': ('余额增速低于限额增速时剩余空间反而扩大，此情景下不会归零；'
                     '归零意味着必须再次提高限额，不等于违约。'),
        }
    return out


def project_interest_burden(revenue, interest, window=7, horizon=DEFAULT_HORIZON,
                            thresholds=THRESHOLDS, overrides=None):
    """付息与收入各按近年复合增速外推，找占比触及各阈值的年份。

    overrides 可给 revenue_growth / interest_growth，覆盖历史推算值。
    """
    overrides = overrides or {}
    common = sorted(set(revenue) & set(interest))
    if len(common) < 2:
        return {'status': 'insufficient_history'}
    used = common[-(window + 1):]
    span = int(used[-1]) - int(used[0])
    revenue_growth = _cagr(revenue[used[0]], revenue[used[-1]], span)
    interest_growth = _cagr(interest[used[0]], interest[used[-1]], span)
    if revenue_growth is None or interest_growth is None:
        return {'status': 'insufficient_history'}
    derived_revenue_growth, derived_interest_growth = revenue_growth, interest_growth
    custom = []
    if overrides.get('revenue_growth') is not None:
        revenue_growth = overrides['revenue_growth']; custom.append('revenue_growth')
    if overrides.get('interest_growth') is not None:
        interest_growth = overrides['interest_growth']; custom.append('interest_growth')
    base_year = int(used[-1])
    base_revenue, base_interest = revenue[used[-1]], interest[used[-1]]
    path, hits = [], {}
    for step in range(0, horizon + 1):
        projected_revenue = base_revenue * (1 + revenue_growth) ** step
        projected_interest = base_interest * (1 + interest_growth) ** step
        ratio = projected_interest / projected_revenue
        path.append({'period': str(base_year + step),
                     'revenue': round(projected_revenue, 2),
                     'interest': round(projected_interest, 2),
                     'ratio': round(ratio * 100, 4)})
        for threshold in thresholds:
            key = f'{int(threshold * 100)}%'
            if key not in hits and ratio >= threshold:
                hits[key] = str(base_year + step)
    return {
        'status': 'projected', 'base_year': str(base_year),
        'base_revenue': base_revenue, 'base_interest': base_interest,
        'base_ratio': round(base_interest / base_revenue * 100, 4),
        'revenue_growth': round(revenue_growth, 6),
        'interest_growth': round(interest_growth, 6),
        'derived_revenue_growth': round(derived_revenue_growth, 6),
        'derived_interest_growth': round(derived_interest_growth, 6),
        'overridden': custom, 'window_years': span,
        'history': [{'period': year, 'revenue': revenue[year], 'interest': interest[year],
                     'ratio': round(interest[year] / revenue[year] * 100, 4)}
                    for year in common],
        'threshold_years': {f'{int(t * 100)}%': hits.get(f'{int(t * 100)}%') for t in thresholds},
        'path': path,
        'note': ('阈值 10%/15%/20% 为本模块设定的观察线，不是任何官方红线；'
                 '收入增速与付息增速任一改变，结论即改变。'),
    }


OVERRIDE_KEYS = ('treasury_balance_growth', 'treasury_limit_growth',
                 'local_balance_growth', 'local_limit_growth',
                 'revenue_growth', 'interest_growth')
GROWTH_BOUNDS = (-0.50, 1.00)   # 增速只接受 -50%~100%，挡住手滑输入的离谱值


def parse_overrides(raw):
    """把查询参数里的百分数（如 '12.5'）转成小数增速，越界或非数字一律忽略。"""
    out = {}
    for key in OVERRIDE_KEYS:
        value = (raw or {}).get(key)
        if value in (None, ''):
            continue
        try:
            growth = float(value) / 100.0
        except (TypeError, ValueError):
            continue
        if GROWTH_BOUNDS[0] <= growth <= GROWTH_BOUNDS[1]:
            out[key] = growth
    return out


def build_projection_payload(db_path, limit_window=4, interest_window=7,
                             horizon=DEFAULT_HORIZON, overrides=None):
    overrides = overrides or {}
    ceiling = build_ceiling_payload(db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        revenue = annual_yearend(conn, 'fiscal_budget_observations',
                                 'general_budget_revenue_ytd')
        interest = annual_yearend(conn, 'fiscal_budget_observations',
                                  'budget_interest_expenditure_ytd')
    finally:
        conn.close()
    return {
        'generated_at': datetime.now().isoformat(),
        'data_status': 'scenario',
        'ceiling': ceiling,
        'limit_constraint': project_limit_constraint(ceiling['years'], limit_window,
                                                     horizon, overrides),
        'interest_burden': project_interest_burden(revenue, interest, interest_window,
                                                   horizon, THRESHOLDS, overrides),
        'assumptions': {
            'limit_window_years': limit_window,
            'interest_window_years': interest_window,
            'horizon_years': horizon,
            'overrides': {k: round(v, 6) for k, v in overrides.items()},
            'method': '各序列按窗口首末年复合增速定速外推，不含政策冲击、利率变动与经济周期。',
        },
        'caveats': [
            '本页全部为情景推演（scenario），不是预测，也不是任何官方口径的数字。',
            '限额是政策变量：人大可随时提高（2024 年 11 月即一次性增加 6 万亿地方专项限额），'
            '因此"剩余空间归零"只表示必须再次提额，不表示违约或无力偿付。',
            '付息占比的 10%/15%/20% 为本模块设定的观察线，非官方红线。',
            '推演不含城投债等隐性债务：其无官方口径，本项目一贯不给数字。',
        ],
    }
