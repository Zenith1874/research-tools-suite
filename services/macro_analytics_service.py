# -*- coding: utf-8 -*-
"""Source-backed macro statistical analytics using only sqlite3 + numpy.

All outputs are derived, non-causal, and carry method/window/sample metadata.
Level series are transformed to changes before correlation analysis.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from datetime import datetime

import numpy as np


MONTHLY_MIN_N = 24
QUARTERLY_MIN_N = 16


def _values(series):
    if not series:
        return np.asarray([], dtype=float)
    if isinstance(series[0], dict):
        return np.asarray([row['value'] for row in series if row.get('value') is not None], dtype=float)
    return np.asarray([value for value in series if value is not None], dtype=float)


def pct_rank(series, value):
    """Inclusive empirical percentile rank, 0..100."""
    arr = _values(series)
    if not len(arr) or value is None:
        return None
    return round(float(np.mean(arr <= float(value)) * 100), 4)


def rolling_z(series, window=60):
    """Latest population z-score; use all available observations if n < window."""
    arr = _values(series)
    if len(arr) < 2:
        return None
    arr = arr[-min(window, len(arr)):]
    sd = float(np.std(arr, ddof=0))
    return None if sd == 0 else round(float((arr[-1] - np.mean(arr)) / sd), 4)


def annualized_change(series, months):
    """Latest geometric annualized change for a monthly level/index series."""
    arr = _values(series)
    if months <= 0 or len(arr) <= months or arr[-months - 1] == 0:
        return None
    ratio = arr[-1] / arr[-months - 1]
    if ratio <= 0:
        return None
    return round(float((ratio ** (12.0 / months) - 1) * 100), 4)


def _period_key(period, frequency='monthly'):
    text = str(period)
    year, month = int(text[:4]), int(text[5:7]) if len(text) >= 7 else 1
    if frequency == 'quarterly':
        return year * 4 + (month - 1) // 3
    if frequency == 'annual':
        return year
    return year * 12 + month - 1


def yoy(series, lag=12, frequency='monthly'):
    """Calendar-aware percent change; missing calendar periods are not bridged."""
    if not series:
        return []
    lookup = {_period_key(row['period'], frequency): row for row in series if row.get('value') is not None}
    result = []
    for key in sorted(lookup):
        previous = lookup.get(key - lag)
        current = lookup[key]
        if not previous or previous['value'] in (None, 0):
            continue
        result.append({'period': current['period'],
                       'value': round((current['value'] / previous['value'] - 1) * 100, 4)})
    return result


def pearson_with_p(x, y):
    """Pearson r and two-sided large-sample t approximation p-value."""
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    n = len(xa)
    if n < 3 or np.std(xa) == 0 or np.std(ya) == 0:
        return {'r': None, 'p': None, 't': None, 'n': n}
    r = float(np.corrcoef(xa, ya)[0, 1])
    t = r * math.sqrt((n - 2) / max(1e-15, 1 - r * r))
    # Normal-tail approximation to Student t; transparent and dependency-free.
    p = math.erfc(abs(t) / math.sqrt(2))
    return {'r': round(r, 4), 'p': round(p, 6), 't': round(t, 4), 'n': n}


def cross_correlation(x, y, max_lag, min_n=MONTHLY_MIN_N):
    """Corr(x[t], y[t+lag]); positive peak lag means x leads y."""
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    results = []
    for lag in range(-max_lag, max_lag + 1):
        if lag > 0:
            xx, yy = xa[:-lag], ya[lag:]
        elif lag < 0:
            xx, yy = xa[-lag:], ya[:lag]
        else:
            xx, yy = xa, ya
        stat = pearson_with_p(xx, yy)
        results.append({'lag': lag, **stat})
    valid = [row for row in results if row['r'] is not None and row['n'] >= min_n]
    peak = max(valid, key=lambda row: abs(row['r'])) if valid else None
    return {'lags': results, 'peak_lag': peak['lag'] if peak else None,
            'peak_corr': peak['r'] if peak else None, 'n': peak['n'] if peak else 0,
            'data_status': 'derived' if peak else 'insufficient_sample'}


def rolling_corr(x, y, window=24, periods=None):
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    result = []
    for end in range(window, min(len(xa), len(ya)) + 1):
        stat = pearson_with_p(xa[end-window:end], ya[end-window:end])
        if stat['r'] is not None:
            result.append({'period': periods[end - 1] if periods else end - 1,
                           'value': stat['r'], 'n': stat['n']})
    return result


def calculate_sahm(unrate_rows):
    """Sahm = current 3m mean minus minimum 3m mean during current/prior 12 months."""
    rows = sorted((row for row in unrate_rows if row.get('value') is not None), key=lambda r: r['period'])
    means = []
    for i in range(2, len(rows)):
        means.append({'period': rows[i]['period'],
                      'value': float(np.mean([rows[i-2]['value'], rows[i-1]['value'], rows[i]['value']]))})
    result = []
    for i in range(11, len(means)):
        baseline = min(row['value'] for row in means[i-11:i+1])
        value = round(means[i]['value'] - baseline, 2)
        result.append({'period': means[i]['period'], 'value': value, 'triggered': value >= 0.5})
    return result


def identify_inversion_episodes(rows, min_months=2):
    episodes, current = [], []
    for row in rows:
        if row.get('value') is not None and row['value'] < 0:
            current.append(row)
        elif current:
            if len(current) >= min_months:
                episodes.append({'start': current[0]['period'], 'end': current[-1]['period'],
                                 'months': len(current), 'depth': round(min(r['value'] for r in current), 4)})
            current = []
    if len(current) >= min_months:
        episodes.append({'start': current[0]['period'], 'end': current[-1]['period'],
                         'months': len(current), 'depth': round(min(r['value'] for r in current), 4)})
    return episodes


def ytd_to_monthly_increment(rows):
    """Convert YTD values to monthly increments without bridging gaps or years."""
    ordered = sorted((r for r in rows if r.get('value') is not None), key=lambda r: r['period'])
    lookup = {str(r['period'])[:7]: r['value'] for r in ordered}
    result = []
    for period in sorted(lookup):
        month = int(period[5:7])
        if month == 1:
            result.append({'period': period, 'value': lookup[period]})
            continue
        previous = _shift_month(period, -1)
        if previous in lookup and previous[:4] == period[:4]:
            result.append({'period': period, 'value': round(lookup[period] - lookup[previous], 6)})
    return result


def cumulative_share(household_rows, corporate_rows):
    """Same-month YTD household share; missing sides and zero denominators are skipped."""
    keys, values = _align(household_rows, corporate_rows)
    result = []
    for period, household, corporate in zip(keys, *values):
        denominator = household + corporate
        if denominator:
            result.append({'period': period[:7],
                           'value': round(household / denominator * 100, 4),
                           'household': household, 'corporate': corporate})
    return result


def calendar_difference(rows, months):
    """Calendar-aligned level/rate difference; never bridges missing months."""
    lookup = {str(r['period'])[:7]: r['value'] for r in rows if r.get('value') is not None}
    return [{'period': period, 'value': round(lookup[period] - lookup[_shift_month(period, -months)], 6)}
            for period in sorted(lookup) if _shift_month(period, -months) in lookup]


def curve_snapshots(series_by_tenor):
    """Return five-tenor snapshots at latest common month, 3m ago and 12m ago."""
    tenors = list(series_by_tenor)
    if not tenors or any(not series_by_tenor[t] for t in tenors):
        return None
    maps = {t: {str(r['period'])[:7]: r['value'] for r in series_by_tenor[t]} for t in tenors}
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    for latest in reversed(common):
        periods = {'latest': latest, 'm3_ago': _shift_month(latest, -3), 'y1_ago': _shift_month(latest, -12)}
        if all(all(period in maps[t] for t in tenors) for period in periods.values()):
            return {'tenors': tenors,
                    'latest': [maps[t][periods['latest']] for t in tenors],
                    'm3_ago': [maps[t][periods['m3_ago']] for t in tenors],
                    'y1_ago': [maps[t][periods['y1_ago']] for t in tenors],
                    'periods': periods}
    return None


def interest_burden_series(interest_rows, receipt_rows):
    keys, values = _align(interest_rows, receipt_rows)
    return [{'period': period, 'value': round(interest / receipts * 100, 4)}
            for period, interest, receipts in zip(keys, *values) if receipts]


def ratio_series(numerator_rows, denominator_rows):
    """Same-period percentage ratio; zero denominators and missing periods are skipped."""
    keys, values = _align(numerator_rows, denominator_rows)
    return [{'period': period[:7], 'value': round(numerator / denominator * 100, 4)}
            for period, numerator, denominator in zip(keys, *values) if denominator]


def rollover_dependency(new_rows, refinancing_rows):
    """Refinancing share of local-government bond issuance, same-period YTD."""
    keys, values = _align(new_rows, refinancing_rows)
    return [{'period': period[:7], 'value': round(refi / (new + refi) * 100, 4)}
            for period, new, refi in zip(keys, *values) if new + refi]


def net_principal_pressure(principal_rows, refinancing_rows):
    """Principal due less refinancing issuance; negative values are valid."""
    keys, values = _align(principal_rows, refinancing_rows)
    return [{'period': period[:7], 'value': round(principal - refi, 4)}
            for period, principal, refi in zip(keys, *values)]


def monotonic_ytd(rows):
    """Drop within-year decreases that reveal a current-month/YTD parser mismatch."""
    result, previous = [], {}
    for row in sorted(rows, key=lambda item: item['period']):
        year = str(row['period'])[:4]
        value = row.get('value')
        if value is None or (year in previous and value < previous[year]):
            continue
        result.append(row)
        previous[year] = value
    return result


def preferred_official_yoy(official_rows, level_rows):
    """Use the published comparable-basis YoY whenever present; level-ratio YoY is audit-only."""
    official = sorted((row for row in official_rows if row.get('value') is not None),
                      key=lambda row: row['period'])
    derived = yoy(level_rows, 12)
    selected = official if official else derived
    return selected, derived, 'official' if official else ('derived' if derived else 'missing')


def land_fiscal_dependency(land_rows, fund_rows, general_rows):
    """Annual December-only land revenue dependency under two nationwide denominators."""
    december = lambda rows: [row for row in rows if str(row['period'])[5:7] == '12']
    keys, values = _align(december(land_rows), december(fund_rows), december(general_rows))
    fund_share, combined_share = [], []
    for period, land, fund, general in zip(keys, *values):
        if fund:
            fund_share.append({'period': period[:4], 'value': round(land / fund * 100, 4)})
        if fund + general:
            combined_share.append({'period': period[:4],
                                   'value': round(land / (fund + general) * 100, 4)})
    return fund_share, combined_share


LOAN_STOCK_COMPONENTS = (
    ('居民短期', 'loan_hh_st_bal'), ('居民中长期', 'loan_hh_lt_bal'),
    ('企业短期', 'loan_corp_st_bal'), ('企业中长期', 'loan_corp_lt_bal'),
    ('票据', 'loan_bill_bal'), ('非银', 'loan_nbfi_bal'),
)


def loan_stock_structure(row):
    """Latest descriptive loan-stock composition; requires total and all six components."""
    if not row or row.get('loan') in (None, 0) or any(row.get(column) is None for _, column in LOAN_STOCK_COMPONENTS):
        return None
    total = row['loan']
    return [{'label': label, 'value': round(row[column] / total * 100, 4), 'amount': row[column]}
            for label, column in LOAN_STOCK_COMPONENTS]


def build_inversion_analysis(spread_rows, recession_rows, title, series_code, sample_note=''):
    """Shared empirical inversion table for any monthly Treasury spread."""
    rec_map = {str(r['period'])[:7]: int(r['value']) for r in recession_rows}
    episodes = identify_inversion_episodes(spread_rows)
    horizons = (6, 12, 18, 24)
    for episode in episodes:
        episode['recession_after'] = {
            str(h): bool(max(rec_map.get(_shift_month(episode['end'], m), 0) for m in range(1, h + 1)))
            for h in horizons
        }
    frequency = {
        str(h): {'hits': sum(ep['recession_after'][str(h)] for ep in episodes),
                 'episodes': len(episodes),
                 'frequency': round(sum(ep['recession_after'][str(h)] for ep in episodes) / len(episodes) * 100, 1)
                              if episodes else None}
        for h in horizons
    }
    return _item(title, f'识别到 {len(episodes)} 个持续至少2个月的倒挂区间。',
                 {'episodes': episodes, 'frequency': frequency}, spread_rows,
                 f'{series_code}日频按月均值；<0连续至少2月；检查结束后6/12/18/24月USREC；'
                 f'仅报经验频率{sample_note}')


def _connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn, table, code, code_col='indicator_code'):
    return [dict(r) for r in conn.execute(
        f'SELECT period,value FROM {table} WHERE {code_col}=? AND value IS NOT NULL ORDER BY period', (code,))]


def _monthly_last(rows):
    out = {}
    for row in rows:
        out[str(row['period'])[:7]] = {'period': str(row['period'])[:7], 'value': row['value']}
    return [out[key] for key in sorted(out)]


def _align(*series):
    maps = [{str(r['period'])[:10]: r['value'] for r in rows} for rows in series]
    keys = sorted(set.intersection(*(set(m) for m in maps))) if maps else []
    return keys, [[m[key] for key in keys] for m in maps]


def _item(title, conclusion, value, series, method, status='derived', caveats=None, n_obs=None):
    valid = [row for row in (series or []) if row.get('value') is not None]
    return {'title': title, 'conclusion': conclusion, 'value': value, 'series': series or [],
            'method': method, 'sample_start': valid[0]['period'] if valid else None,
            'sample_end': valid[-1]['period'] if valid else None,
            'n_obs': n_obs if n_obs is not None else len(valid), 'data_status': status,
            'caveats': caveats or ['统计关联不代表因果。']}


def _position_item(title, rows, frequency='monthly', transform='level'):
    if not rows:
        return _item(title, '数据缺失，未计算。', None, [], 'missing', 'missing')
    current = rows[-1]['value']
    window = 20 if frequency == 'quarterly' else 60
    z = rolling_z(rows, window)
    stats = {'current': current, 'percentile': pct_rank(rows, current), 'z_score': z}
    if frequency == 'monthly' and transform == 'level':
        stats.update(momentum_3m=annualized_change(rows, 3), momentum_12m=annualized_change(rows, 12))
    elif frequency == 'monthly':
        vals = _values(rows)
        stats.update(momentum_3m=round(float(vals[-1] - vals[-4]), 4) if len(vals) >= 4 else None,
                     momentum_12m=round(float(vals[-1] - vals[-13]), 4) if len(vals) >= 13 else None)
    return _item(title, f'当前值 {current:.2f}，历史分位 {stats["percentile"]:.1f}%。', stats, rows,
                 f'历史分位=经验CDF；Z=最新值相对最近{window}期均值/标准差；动量按指标类型计算')


def _quarter_end_monthly(rows):
    selected = {}
    for row in rows:
        p = str(row['period'])[:7]
        y, m = int(p[:4]), int(p[5:7])
        q = (m - 1) // 3 + 1
        key = (y, q)
        if key not in selected or p > selected[key]['period']:
            selected[key] = {'period': f'{y:04d}-{(q-1)*3+1:02d}-01', 'value': row['value']}
    return [selected[key] for key in sorted(selected)]


def _annual_budget(conn, code):
    rows = _rows(conn, 'fiscal_budget_observations', code)
    return [row for row in rows if str(row['period'])[5:7] == '12']


def _annual_budget_like_debt(conn, code):
    return [dict(row) for row in conn.execute('''SELECT period,value FROM fiscal_debt_observations
        WHERE indicator_code=? AND value IS NOT NULL AND substr(period,6,2)='12'
        ORDER BY period''', (code,))]


CITY_TIER1 = ('北京', '上海', '广州', '深圳')


def _diffusion_from_rows(rows):
    """MoM 指数(上月=100 口径)按期统计上涨城市占比，得扩散指数(0-100，50为荣枯线)。"""
    buckets = {}
    for row in rows:
        buckets.setdefault(str(row['period'])[:7], []).append(row['value'])
    series = []
    for period in sorted(buckets):
        vals = buckets[period]
        up = sum(1 for v in vals if v > 100)
        down = sum(1 for v in vals if v < 100)
        series.append({'period': period, 'value': round(up / len(vals) * 100, 2),
                       'up': up, 'flat': len(vals) - up - down, 'down': down, 'total': len(vals)})
    return series


CITY_RENAMES = {'襄樊': '襄阳'}  # 2010年12月襄樊市更名襄阳市,统计局2011-07起改用新称


def chain_mom_index(rows):
    """环比指数(上月=100)链式累乘为定基指数(基期=首期前一月=100)。
    缺月即断链,只保留最后一段连续区间,绝不跨缺月桥接。"""
    ordered = sorted((r for r in rows if r.get('value') is not None),
                     key=lambda r: str(r['period']))
    segments, current, prev_key = [], [], None
    for row in ordered:
        key = _period_key(row['period'])
        if prev_key is not None and key != prev_key + 1:
            segments.append(current)
            current = []
        current.append(row)
        prev_key = key
    if current:
        segments.append(current)
    if not segments or not segments[-1]:
        return []
    index, out = 100.0, []
    for row in segments[-1]:
        index *= row['value'] / 100.0
        out.append({'period': str(row['period'])[:7], 'value': round(index, 4)})
    return out


def drawdown_from_index(index_rows):
    """定基指数的峰值回撤:峰值期、当前相对峰值涨跌幅、距峰值月数。"""
    if not index_rows:
        return None
    peak_i = max(range(len(index_rows)), key=lambda i: index_rows[i]['value'])
    peak, last = index_rows[peak_i], index_rows[-1]
    return {'peak_period': peak['period'],
            'drawdown_pct': round((last['value'] / peak['value'] - 1) * 100, 2),
            'months_since_peak': len(index_rows) - 1 - peak_i}


def current_decline_streak(mom_rows):
    """尾部连续环比<100的月数;>=100(持平或上涨)即中断。"""
    ordered = sorted((r for r in mom_rows if r.get('value') is not None),
                     key=lambda r: str(r['period']))
    streak = 0
    for row in reversed(ordered):
        if row['value'] < 100:
            streak += 1
        else:
            break
    return streak


def cross_city_dispersion(rows):
    """按期计算跨城市样本标准差(ddof=1);单城期不计。输入 rows 含 period,value。"""
    buckets = {}
    for row in rows:
        if row.get('value') is not None:
            buckets.setdefault(str(row['period'])[:7], []).append(row['value'])
    return [{'period': period, 'value': round(float(np.std(buckets[period], ddof=1)), 4)}
            for period in sorted(buckets) if len(buckets[period]) >= 2]


def rolling_four_quarter_sum(rows):
    """季度序列的滚动4季求和;只在连续4个日历季度上计算,缺季不桥接。
    输入 rows period 为 'YYYY-MM'(3/6/9/12);输出 period=窗口末季。"""
    ordered = sorted((r for r in rows if r.get('value') is not None),
                     key=lambda r: str(r['period']))
    keyed = [(_period_key(r['period'], 'quarterly'), r) for r in ordered]
    out = []
    for i in range(3, len(keyed)):
        window = keyed[i - 3:i + 1]
        if window[-1][0] - window[0][0] == 3:
            out.append({'period': str(window[-1][1]['period'])[:7],
                        'value': round(sum(w[1]['value'] for w in window), 4)})
    return out


def vu_ratio_series(vacancy_rows, unemployment_rows):
    """劳动力市场紧张度 V/U = 空缺率/失业率，同月配对，缺月不桥接，分母为0跳过。"""
    keys, values = _align(vacancy_rows, unemployment_rows)
    return [{'period': str(k)[:7], 'value': round(v / u, 4)}
            for k, v, u in zip(keys, *values) if u]


def beveridge_points(unemployment_rows, vacancy_rows, recent_n=24):
    """贝弗里奇曲线截面点集：同月配对的 {period,u,v}；recent 为末 recent_n 期。"""
    keys, values = _align(unemployment_rows, vacancy_rows)
    points = [{'period': str(k)[:7], 'u': u, 'v': v} for k, u, v in zip(keys, *values)]
    if not points:
        return None
    return {'points': points, 'recent': points[-recent_n:], 'latest': points[-1]}


def build_china_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        m2y = [dict(r) for r in conn.execute('SELECT month period,M2y value FROM monthly_data WHERE M2y IS NOT NULL ORDER BY month')]
        sfy = [dict(r) for r in conn.execute('SELECT month period,SFy value FROM monthly_data WHERE SFy IS NOT NULL ORDER BY month')]
        loany = [dict(r) for r in conn.execute('SELECT month period,loany value FROM monthly_data WHERE loany IS NOT NULL ORDER BY month')]
        lpr = _monthly_last(_rows(conn, 'china_rates_observations', 'LPR_1Y'))
        shibor3 = _monthly_last(_rows(conn, 'china_rates_observations', 'SHIBOR_3M'))
        shibor1y = _monthly_last(_rows(conn, 'china_rates_observations', 'SHIBOR_1Y'))
        fx_daily = _rows(conn, 'china_rates_observations', 'USDCNY_CENTRAL_PARITY')
        fx_monthly = _monthly_last(fx_daily)
        sf_position = _position_item('社融存量同比定位', sfy, transform='rate')
        if len(sfy) < MONTHLY_MIN_N:
            sf_position.update(conclusion='月频有效样本不足24期，拒绝定位判断。', value=None,
                               data_status='insufficient_sample')
        positioning = [_position_item('M2 同比定位', m2y, transform='rate'),
                       sf_position,
                       _position_item('贷款余额同比定位', loany, transform='rate'),
                       _position_item('LPR 1Y 定位', lpr, transform='rate'),
                       _position_item('SHIBOR 3M 定位', shibor3, transform='rate'),
                       _position_item('美元兑人民币中间价定位', fx_monthly)]

        house = _rows(conn, 'housing_national_observations', 'QCNR628BIS')
        house_yoy = yoy(house, 4, 'quarterly')
        m2q = _quarter_end_monthly(m2y)
        keys, aligned = _align(m2q, house_yoy)
        cc = cross_correlation(*aligned, 8, min_n=QUARTERLY_MIN_N) if keys else {'lags': [], 'data_status': 'insufficient_sample', 'n': 0, 'peak_lag': None, 'peak_corr': None}
        transmission = _item('货币与房价领先滞后相关',
            f'M2同比与实际房价同比的峰值领先相关在 {cc.get("peak_lag")} 季，r={cc.get("peak_corr")}。' if cc.get('peak_lag') is not None else '共同季度样本不足，拒绝计算相关。',
            {'peak_lag': cc.get('peak_lag'), 'peak_corr': cc.get('peak_corr')},
            [{'period': row['lag'], 'value': row['r']} for row in cc.get('lags', []) if row['r'] is not None],
            'M2同比按季度末采样；BIS中国实际房价指数同比；corr(M2[t], house[t+lag])，lag ±8季',
            cc['data_status'], n_obs=cc.get('n', 0))
        if keys:
            transmission.update(sample_start=keys[0], sample_end=keys[-1])

        rev = _annual_budget(conn, 'general_budget_revenue_ytd')
        exp = _annual_budget(conn, 'general_budget_expenditure_ytd')
        rev_y, exp_y = yoy(rev, 1, 'annual'), yoy(exp, 1, 'annual')
        keys, vals = _align(exp_y, rev_y)
        fiscal_series = [{'period': k[:4], 'value': round(a-b, 4)} for k, a, b in zip(keys, *vals)]
        fiscal = _item('财政脉冲', f'最新财政脉冲为 {fiscal_series[-1]["value"]:.2f} 个百分点。' if fiscal_series else '年度样本缺失。',
                       fiscal_series[-1]['value'] if fiscal_series else None, fiscal_series,
                       '一般公共预算支出YoY − 收入YoY；仅使用完整年度(12月YTD)')

        central = _rows(conn, 'fiscal_debt_observations', 'central_government_debt_balance')
        local = _rows(conn, 'fiscal_debt_observations', 'local_debt_balance_total')
        # 主序列:地方债务口径(2017年末起有官方月度余额,年度YoY可用);
        # 中央债务官方序列2024年起,全口径YoY仅1点,只作最新点补充,不做序列。
        local_annual = [r for r in local if str(r['period'])[5:7] == '12']
        local_y = yoy(local_annual, 1, 'annual')
        keys, vals = _align(local_y, rev_y)
        debt_gap = [{'period': str(k)[:4], 'value': round(a - b, 4)} for k, a, b in zip(keys, *vals)]
        keys, vals = _align(central, local)
        full_total = [{'period': k, 'value': a + b} for k, a, b in zip(keys, *vals)
                      if str(k)[5:7] == '12']
        full_y = yoy(full_total, 1, 'annual')
        full_note = ''
        if full_y and rev_y:
            rev_map = {str(r['period'])[:4]: r['value'] for r in rev_y}
            last = full_y[-1]
            year = str(last['period'])[:4]
            if year in rev_map:
                full_note = (f'全口径(含国债)最新 {year} 年为 '
                             f'{last["value"] - rev_map[year]:+.1f} 个百分点。')
        debt_item = _item('债务-收入增速差(地方口径)',
            (f'地方债务余额增速持续快于全国财政收入增速 {debt_gap[-1]["value"]:+.1f} 个百分点'
             f'({debt_gap[-1]["period"]}年)。{full_note}' if debt_gap else '年度同口径样本缺失。'),
            debt_gap[-1]['value'] if debt_gap else None, debt_gap,
            '地方政府债务余额年度YoY − 全国一般公共预算收入YoY；'
            '中央债务官方序列2024年起,全口径仅报最新点',
            'derived' if debt_gap else 'insufficient_sample',
            caveats=['分母为全国收入(地方分列收入无官方月度序列),是口径妥协。',
                     '年度样本少(2018年起),只报数值不作趋势外推。'])

        keys, vals = _align(lpr, shibor1y)
        spread = [{'period': k[:7], 'value': round(a-b, 4)} for k, a, b in zip(keys, *vals)]
        spread_item = _item('LPR－SHIBOR 1Y 利差', f'最新政策报价与资金价利差 {spread[-1]["value"]:.2f} 个百分点。' if spread else '数据缺失。',
                            spread[-1]['value'] if spread else None, spread,
                            '同月末 LPR_1Y − SHIBOR_1Y；LPR为报价利率，SHIBOR为资金市场报价')

        returns = []
        for i in range(1, len(fx_daily)):
            returns.append({'period': fx_daily[i]['period'], 'value': math.log(fx_daily[i]['value']/fx_daily[i-1]['value'])})
        vol = []
        for i in range(20, len(returns)):
            value = float(np.std([r['value'] for r in returns[i-20:i+1]], ddof=1) * math.sqrt(252) * 100)
            vol.append({'period': returns[i]['period'], 'value': round(value, 4)})
        vol_item = _item('人民币已实现波动率', f'最新21日年化波动率 {vol[-1]["value"]:.2f}%。' if vol else '数据缺失。',
                         vol[-1]['value'] if vol else None, vol, 'USDCNY日对数收益率21日滚动样本标准差 × sqrt(252) × 100')

        m1y = [dict(r) for r in conn.execute('SELECT month period,M1y value FROM monthly_data WHERE M1y IS NOT NULL ORDER BY month')]
        keys, vals = _align(m1y, m2y)
        scissors = [{'period': k, 'value': round(a - b, 4)} for k, a, b in zip(keys, *vals)]
        sc_status = 'derived' if len(scissors) >= MONTHLY_MIN_N else 'insufficient_sample'
        sc_val = scissors[-1]['value'] if scissors else None
        scissors_item = _item('M1-M2剪刀差',
            (f'最新M1-M2同比剪刀差 {sc_val:.2f} 个百分点，{"资金活化、需求偏强" if sc_val > 0 else "资金活期化走弱、需求偏弱"}。'
             if scissors and sc_status == 'derived' else ('样本不足24月，拒绝判断。' if scissors else '数据缺失。')),
            sc_val if sc_status == 'derived' else None, scissors,
            'M1同比 − M2同比；负值示企业活期存款增速慢于广义货币，常与经济活力偏弱相关', sc_status,
            caveats=['M1口径2024年含个人活期存款调整，历史可比性有断点。', '统计关联不代表因果。'])

        loan_acceleration = calendar_difference(loany, 12)
        loany_map = {str(row['period'])[:7]: row['value'] for row in loany}
        latest_loan_period = str(loany[-1]['period'])[:7] if loany else None
        prior_3m = loany_map.get(_shift_month(latest_loan_period, -3)) if latest_loan_period else None
        delta_3m = loany[-1]['value'] - prior_3m if loany and prior_3m is not None else None
        momentum_status = 'derived' if len(loany) >= MONTHLY_MIN_N else 'insufficient_sample'
        loan_momentum = _item('贷款增速动量',
            (f'贷款余额同比 {loany[-1]["value"]:.2f}%，较3个月前 {delta_3m:+.2f} 个百分点，'
             f'较12个月前 {loan_acceleration[-1]["value"]:+.2f} 个百分点。'
             if loany and delta_3m is not None and loan_acceleration else '贷款增速样本不足，拒绝动量判断。'),
            {'current': loany[-1]['value'] if loany else None,
             'delta_3m': delta_3m,
             'delta_12m': loan_acceleration[-1]['value'] if loan_acceleration else None},
            loan_acceleration, '贷款余额同比当前值；Δ3月/Δ12月均为百分点差；图示整条12月差分序列', momentum_status)

        hh_ytd = [dict(r) for r in conn.execute(
            'SELECT month period,loan_hh_ytd value FROM monthly_data WHERE loan_hh_ytd IS NOT NULL ORDER BY month')]
        corp_ytd = [dict(r) for r in conn.execute(
            'SELECT month period,loan_corp_ytd value FROM monthly_data WHERE loan_corp_ytd IS NOT NULL ORDER BY month')]
        hh_share = cumulative_share(hh_ytd, corp_ytd)
        share_status = 'derived' if len(hh_share) >= MONTHLY_MIN_N else 'insufficient_sample'
        share_value = hh_share[-1]['value'] if hh_share else None
        share_item = _item('新增贷款居民占比',
            (f'居民贷款占居民与企业累计新增贷款 {share_value:.2f}%，处历史第 {pct_rank(hh_share, share_value):.1f} 百分位。'
             if hh_share and share_status == 'derived' else '同月双列共同样本不足24月，拒绝判断。'),
            {'current': share_value, 'percentile': pct_rank(hh_share, share_value) if hh_share else None},
            hh_share, 'loan_hh_ytd / (loan_hh_ytd + loan_corp_ytd) × 100；同月年初以来累计口径', share_status,
            caveats=['分母未含票据与非银；居民早偿会压低净新增甚至为负。', '统计关联不代表因果。'])

        hh_lt_ytd = [dict(r) for r in conn.execute(
            'SELECT month period,loan_hh_lt_ytd value FROM monthly_data WHERE loan_hh_lt_ytd IS NOT NULL ORDER BY month')]
        hh_lt_yoy = yoy(hh_lt_ytd, 12)
        hh_lt_status = 'derived' if len(hh_lt_yoy) >= MONTHLY_MIN_N else 'insufficient_sample'
        hh_lt_item = _item('居民中长期贷款（房贷代理）',
            (f'居民中长期贷款年初累计同比 {hh_lt_yoy[-1]["value"]:.2f}%。'
             if hh_lt_yoy and hh_lt_status == 'derived' else '同月YTD同比有效样本不足24月，拒绝判断。'),
            hh_lt_yoy[-1]['value'] if hh_lt_yoy and hh_lt_status == 'derived' else None,
            hh_lt_yoy, '居民中长期贷款年初累计值同月对同月同比；缺月不跨越', hh_lt_status,
            caveats=['含消费与经营中长贷，非纯房贷；房贷主导。', '统计关联不代表因果。'])

        stock_row = conn.execute('''SELECT month,loan,loan_hh_st_bal,loan_hh_lt_bal,
            loan_corp_st_bal,loan_corp_lt_bal,loan_bill_bal,loan_nbfi_bal
            FROM monthly_data ORDER BY month DESC LIMIT 1''').fetchone()
        stock_row = dict(stock_row) if stock_row else None
        stock = loan_stock_structure(stock_row)
        stock_item = _item('最新贷款存量结构',
            (f'{stock_row["month"]}贷款存量结构：居民中长期 {next(x["value"] for x in stock if x["label"] == "居民中长期"):.1f}%，'
             f'企业中长期 {next(x["value"] for x in stock if x["label"] == "企业中长期"):.1f}%。'
             if stock else '最新月六项存量结构不完整，拒绝计算。'),
            {'period': stock_row['month'], 'components': stock, 'total': stock_row['loan']} if stock else None,
            [], '六项贷款存量 / 贷款总余额 × 100；仅最新月描述性截面，不作趋势分析',
            'derived' if stock else 'missing', n_obs=1 if stock else 0,
            caveats=['仅最新月截面，禁止趋势、相关或因果解读。'])
        if stock:
            stock_item.update(sample_start=stock_row['month'], sample_end=stock_row['month'])

        try:
            odc = _rows(conn, 'pboc_balance_sheet_observations', 'claims_on_other_depository_corporations_pct')
            fx_a = _rows(conn, 'pboc_balance_sheet_observations', 'foreign_assets_pct')
            gov = _rows(conn, 'pboc_balance_sheet_observations', 'claims_on_government_pct')
        except sqlite3.OperationalError:
            odc, fx_a, gov = [], [], []
        mk, mv = _align(odc, fx_a, gov)
        if mk:
            mix_series = [{'period': str(k)[:7], 'odc': round(o, 2), 'fx': round(f, 2), 'gov': round(g, 2)}
                          for k, o, f, g in zip(mk, *mv)]
            last = mix_series[-1]
            mix_item = _item('央行资产投放结构',
                (f'最新央行总资产中，对存款性公司债权占 {last["odc"]:.1f}%、国外资产 {last["fx"]:.1f}%、'
                 f'对政府债权 {last["gov"]:.1f}%；主动借贷(MLF/逆回购/PSL)与外汇占款是基础货币两大来源。'),
                last, mix_series,
                '三项占比取自央行资产负债表官方披露(各项/总资产×100)；同月对齐；仅结构描述',
                n_obs=len(mix_series),
                caveats=['仅2023年起月度，只反映近期结构非长期趋势；三项不穷尽总资产(另有黄金/其他资产等)。',
                         '对政府债权为央行持有的政府债权占比，非"央行认购国债"或赤字货币化。',
                         '统计关联不代表因果。'])
            mix_item['compare_keys'] = [
                {'key': 'odc', 'label': '对其他存款性公司债权(主动投放)', 'color': '#4f8fff'},
                {'key': 'fx', 'label': '国外资产(外汇占款为主)', 'color': '#00d4aa'},
                {'key': 'gov', 'label': '对政府债权', 'color': '#f5a623'}]
            mix_item.update(sample_start=mix_series[0]['period'], sample_end=last['period'])
        else:
            mix_item = _item('央行资产投放结构', '央行资产负债表占比序列缺失，未计算。', None, [],
                             '三项占比同月对齐', 'missing')

        try:
            cpi = _rows(conn, 'china_macro_observations', 'CN_CPI_YOY')
            ppi = _rows(conn, 'china_macro_observations', 'CN_PPI_YOY')
            pmi = _rows(conn, 'china_macro_observations', 'CN_PMI_MFG')
            ip_yoy = _rows(conn, 'china_macro_observations', 'CN_IP_YOY')
            retail_yoy = _rows(conn, 'china_macro_observations', 'CN_RETAIL_YOY')
            fai_yoy = _rows(conn, 'china_macro_observations', 'CN_FAI_YTD_YOY')
            gdp_nominal = _rows(conn, 'china_macro_observations', 'CN_GDP_Q_NOMINAL')
            gdp_real = _rows(conn, 'china_macro_observations', 'CN_GDP_Q_REAL_YOY')
            unemp = _rows(conn, 'china_macro_observations', 'CN_UNEMP_SURVEY')
            export_yoy = _rows(conn, 'china_macro_observations', 'CN_EXPORT_YOY')
            import_yoy = _rows(conn, 'china_macro_observations', 'CN_IMPORT_YOY')
            trade_yoy = _rows(conn, 'china_macro_observations', 'CN_TRADE_YOY')
        except sqlite3.OperationalError:
            cpi = ppi = pmi = ip_yoy = retail_yoy = fai_yoy = gdp_nominal = gdp_real = []
            unemp = export_yoy = import_yoy = trade_yoy = []
        reer = _rows(conn, 'china_rates_observations', 'REER_CNY_BIS')
        try:
            sf_stock = [dict(r) for r in conn.execute(
                'SELECT month period, SF value FROM monthly_data WHERE SF IS NOT NULL ORDER BY month')]
        except sqlite3.OperationalError:
            sf_stock = []
        cpi_pos = _position_item('CPI 同比定位', cpi, transform='rate')
        ppi_pos = _position_item('PPI 同比定位', ppi, transform='rate')
        pmi_pos = _position_item('制造业PMI定位', pmi, transform='rate')
        if pmi:
            pmi_pos['conclusion'] = (f'制造业PMI {pmi[-1]["value"]:.1f}%，'
                                     f'{"高于" if pmi[-1]["value"] >= 50 else "低于"}50%荣枯线，'
                                     f'历史分位 {pmi_pos["value"]["percentile"]:.1f}%。')
        keys, values = _align(cpi, ppi)
        cp_gap = [{'period': str(k)[:7], 'value': round(a - b, 2)} for k, a, b in zip(keys, *values)]
        gap_val = cp_gap[-1]['value'] if cp_gap else None
        cp_item = _item('CPI-PPI 剪刀差',
            (f'CPI同比减PPI同比 {gap_val:+.1f} 个百分点，'
             + ('下游价格强于上游，中下游利润空间改善。' if gap_val > 0
                else '上游价格强于下游，中下游利润承压。') if cp_gap else '数据缺失。'),
            gap_val, cp_gap,
            'CN_CPI_YOY − CN_PPI_YOY 同月相减；正值利中下游、负值利上游',
            'derived' if len(cp_gap) >= MONTHLY_MIN_N else 'insufficient_sample',
            caveats=['价差是利润分配的粗代理，不等于利润率。', '统计关联不代表因果。'])

        ip_pos = _position_item('工业增加值当月同比定位', ip_yoy, transform='rate')
        retail_pos = _position_item('社零当月同比定位', retail_yoy, transform='rate')
        fai_pos = _position_item('固投累计同比定位', fai_yoy, transform='rate')
        gdp_pos = _position_item('GDP单季实际同比定位', gdp_real, 'quarterly', 'rate')
        unemp_pos = _position_item('城镇调查失业率定位', unemp, transform='rate')
        if unemp and len(unemp) < MONTHLY_MIN_N:
            unemp_pos.update(
                conclusion=f'当前 {unemp[-1]["value"]:.1f}%；月频有效样本不足24期，拒绝分位/Z判断。',
                value=None, data_status='insufficient_sample')
        reer_pos = _position_item('人民币实际有效汇率定位', [
            {'period': str(r['period'])[:7], 'value': r['value']} for r in reer])
        if reer:
            reer_pos['method'] = 'BIS实际广义有效汇率(2020=100,升值=指数升);历史分位、60月Z与差分动量'

        keys, values = _align(export_yoy, import_yoy)
        trade_series = [{'period': str(k)[:7], 'exp': a, 'imp': b, 'value': a}
                        for k, a, b in zip(keys, *values)]
        trade_item = _item('出口与进口当月同比',
            (f'最新出口同比 {trade_series[-1]["exp"]:+.1f}%、进口 {trade_series[-1]["imp"]:+.1f}%，'
             f'总额同比 {trade_yoy[-1]["value"]:+.1f}%。' if trade_series and trade_yoy else '数据缺失。'),
            trade_series[-1] if trade_series else None, trade_series,
            '统计局月度国民经济运行稿转述的海关当月数据；出口/进口各自同比',
            'derived' if trade_series else 'missing',
            caveats=['海关总署站点对境外访问不可达，取统计局官方转述口径；人民币计价。',
                     '统计关联不代表因果。'])
        if trade_item['data_status'] == 'derived':
            trade_item['compare_keys'] = [
                {'key': 'exp', 'label': '出口当月同比', 'color': '#00d4aa'},
                {'key': 'imp', 'label': '进口当月同比', 'color': '#f5a623'}]

        rolling_gdp = rolling_four_quarter_sum(gdp_nominal)
        sf_q = {str(r['period'])[:7]: r['value'] for r in sf_stock
                if str(r['period'])[5:7] in ('03', '06', '09', '12')}
        leverage = [{'period': row['period'],
                     'value': round(sf_q[row['period']] * 10000 / row['value'] * 100, 2)}
                    for row in rolling_gdp if row['period'] in sf_q and row['value']]
        lev_item = _position_item('宏观杠杆率(社融口径)', leverage, 'quarterly', 'rate')
        if leverage:
            lev_item['conclusion'] = (f'社融存量/滚动4季名义GDP = {leverage[-1]["value"]:.1f}%'
                                      f'（{leverage[-1]["period"]}），历史分位 '
                                      f'{lev_item["value"]["percentile"]:.0f}%。')
        lev_item['method'] = ('社融存量(季末月,万亿→亿) / 最近4个连续季度现价GDP之和 ×100；'
                              '缺季不桥接')
        lev_item['caveats'] = ['社融口径杠杆率近似，非国家资产负债表研究中心(CNBS)官方口径；'
                               '社融存量含政府债券等，分子口径宽于私人部门债务。',
                               '统计关联不代表因果。']
    return {'positioning': positioning + [cpi_pos, ppi_pos, pmi_pos, ip_pos, retail_pos,
                                          fai_pos, gdp_pos, unemp_pos, reer_pos],
            'analyses': [loan_momentum, share_item, hh_lt_item, stock_item, mix_item, cp_item,
                         lev_item, trade_item, scissors_item, transmission, fiscal, debt_item,
                         spread_item, vol_item]}


def _monthly_average(rows):
    buckets = {}
    for row in rows:
        buckets.setdefault(str(row['period'])[:7], []).append(row['value'])
    return [{'period': key, 'value': round(float(np.mean(buckets[key])), 6)} for key in sorted(buckets)]


def build_us_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        raw = {code: _rows(conn, 'us_macro_observations', code) for code in
               ('UNRATE','PCEPILFE','GDPC1','DGS3MO','DGS2','DGS5','DGS10','DGS30',
                'T10Y2Y','T10Y3M','MORTGAGE30US','USREC','T10YIE','JTSJOL','JTSJOR','JTSQUR','JTSHIR',
                'A091RC1Q027SBEA','FGRECPT','VIXCLS')}
        core_yoy = yoy(raw['PCEPILFE'], 12)
        gdp_qoq = []
        for i in range(1, len(raw['GDPC1'])):
            gdp_qoq.append({'period': raw['GDPC1'][i]['period'], 'value': round(((raw['GDPC1'][i]['value']/raw['GDPC1'][i-1]['value'])**4-1)*100, 4)})
        spread3m = _monthly_average(raw['T10Y3M'])
        spread3m_position = _position_item('10Y−3M 定位', spread3m, transform='rate')
        if spread3m:
            spread3m_position['conclusion'] = (
                f'10Y−3M利差 {spread3m[-1]["value"]:.2f} 个百分点；3M端比10Y−2Y更贴近政策路径。')
            spread3m_position['method'] = 'T10Y3M日频按月均值；历史分位、60月Z与3/12月百分点动量'
        positioning = [_position_item('失业率定位', raw['UNRATE'], transform='rate'),
                       _position_item('核心PCE同比定位', core_yoy, transform='rate'),
                       _position_item('实际GDP环比年化定位', gdp_qoq, 'quarterly', 'rate'),
                       _position_item('10年期美债定位', _monthly_average(raw['DGS10']), transform='rate'),
                       _position_item('10Y－2Y期限利差定位', _monthly_average(raw['T10Y2Y']), transform='rate'),
                       spread3m_position,
                       _position_item('30年房贷利率定位', _monthly_average(raw['MORTGAGE30US']), transform='rate'),
                       _position_item('VIX 波动率定位', _monthly_average(raw['VIXCLS']), transform='rate')]

        sahm = calculate_sahm(raw['UNRATE'])
        rec_map = {str(r['period'])[:7]: int(r['value']) for r in raw['USREC']}
        for row in sahm:
            row['recession'] = rec_map.get(str(row['period'])[:7], 0)
        starts = [i for i, row in enumerate(sahm) if row['triggered'] and (i == 0 or not sahm[i-1]['triggered'])]
        checks = []
        for i in starts:
            period = str(sahm[i]['period'])[:7]
            future = [rec_map.get(_shift_month(period, m), 0) for m in range(0, 13)]
            checks.append({'period': period, 'value': sahm[i]['value'], 'recession_within_12m': bool(max(future))})
        current = sahm[-1] if sahm else None
        sahm_item = _item('Sahm Rule', f'当前Sahm值 {current["value"]:.2f}，{"达到" if current and current["triggered"] else "未达到"}0.50触发线。' if current else '数据不足。',
                          {'current': current['value'] if current else None, 'triggered': current['triggered'] if current else False,
                           'trigger_count': len(starts), 'recession_checks': checks}, sahm,
                          'UNRATE最近3月均值 − 最近12个3月均值的最低值；≥0.50触发')

        spread_m = _monthly_average(raw['T10Y2Y'])
        shared_start = max(spread_m[0]['period'], spread3m[0]['period']) if spread_m and spread3m else None
        spread_2y_shared = [row for row in spread_m if not shared_start or row['period'] >= shared_start]
        spread_3m_shared = [row for row in spread3m if not shared_start or row['period'] >= shared_start]
        sample_note = f'；两表统一共同样本起点 {shared_start}' if shared_start else ''
        inversion = build_inversion_analysis(spread_2y_shared, raw['USREC'],
                                             '期限利差倒挂经验表', 'T10Y2Y', sample_note)
        inversion_3m = build_inversion_analysis(spread_3m_shared, raw['USREC'],
                                                '10Y−3M倒挂经验表', 'T10Y3M', sample_note)

        pce = raw['PCEPILFE']
        momentum = {f'{m}m': annualized_change(pce, m) for m in (3,6,12)}
        direction = '再加速' if momentum['3m'] is not None and momentum['12m'] is not None and momentum['3m'] > momentum['12m'] else '降温'
        inflation = _item('核心PCE通胀动量', f'3个月年化相对12个月显示{direction}。', momentum,
                          [{'period': key, 'value': value} for key,value in momentum.items()],
                          '核心PCE价格指数3/6/12个月几何年化变化率')
        if pce:
            inflation.update(sample_start=pce[0]['period'], sample_end=pce[-1]['period'], n_obs=len(pce))

        dgs10m, ie10m = _monthly_average(raw['DGS10']), _monthly_average(raw['T10YIE'])
        keys, vals = _align(dgs10m, ie10m)
        real = [{'period': k[:7], 'value': round(a-b, 4)} for k,a,b in zip(keys,*vals)]
        real_item = _position_item('10年期实际利率定位', real, transform='rate')
        real_item['method'] = 'DGS10月均值 − T10YIE月均值；并计算历史分位、60月Z与动量'

        components, maps = [], []
        for code in ('JTSJOL','JTSQUR','JTSHIR'):
            rows = raw[code]; zrows=[]
            for i,row in enumerate(rows):
                z = rolling_z(rows[:i+1],60)
                if z is not None: zrows.append({'period':str(row['period'])[:7], 'value':z})
            components.append(code); maps.append({r['period']:r['value'] for r in zrows})
        keys = sorted(set.intersection(*(set(m) for m in maps)))
        composite = [{'period':k,'value':round(float(np.mean([m[k] for m in maps])),4)} for k in keys]
        labor = _item('劳动市场综合指数', f'最新等权综合Z为 {composite[-1]["value"]:.2f}。' if composite else '数据不足。',
                      {'current':composite[-1]['value'] if composite else None,'components':components,'weights':'各1/3'}, composite,
                      'JTSJOL、JTSQUR、JTSHIR各自60月滚动Z分数的等权均值')

        curve_data = curve_snapshots({
            '3M': _monthly_average(raw['DGS3MO']), '2Y': _monthly_average(raw['DGS2']),
            '5Y': _monthly_average(raw['DGS5']), '10Y': _monthly_average(raw['DGS10']),
            '30Y': _monthly_average(raw['DGS30']),
        })
        curve_item = _item('美债收益率曲线形态',
            (f'对比 {curve_data["periods"]["latest"]}、3个月前和12个月前的五期限月均收益率。'
             if curve_data else '五期限共同月份不足，无法构建曲线快照。'),
            curve_data, [], '3M/2Y/5Y/10Y/30Y各取最新共同月、3个月前、12个月前月均值；仅作形态对照',
            'derived' if curve_data else 'missing', n_obs=15 if curve_data else 0)
        if curve_data:
            curve_item.update(sample_start=curve_data['periods']['y1_ago'],
                              sample_end=curve_data['periods']['latest'])

        burden = interest_burden_series(raw['A091RC1Q027SBEA'], raw['FGRECPT'])
        burden_item = _position_item('美国联邦利息负担率', burden, 'quarterly', 'rate')
        if burden:
            rank = burden_item['value']['percentile']
            burden_item['conclusion'] = (f'联邦利息支出占经常性收入 {burden[-1]["value"]:.2f}%，'
                                         f'处 {str(burden[0]["period"])[:4]} 年以来第 {rank:.1f} 百分位。')
            burden_item['method'] = 'A091RC1Q027SBEA / FGRECPT × 100；同季度BEA NIPA季调年率对齐；20季Z'
            burden_item['caveats'] = ['NIPA 应计口径，非财政部现金口径。', '统计关联不代表因果。']

        vu = vu_ratio_series(raw['JTSJOR'], raw['UNRATE'])
        vu_item = _position_item('劳动力市场紧张度 V/U', vu, transform='rate')
        if vu:
            peak = max(vu, key=lambda r: r['value'])
            latest_vu = vu[-1]['value']
            vu_item['conclusion'] = (
                f'职位空缺率/失业率比 {latest_vu:.2f}，历史峰值 {peak["value"]:.2f}'
                f'（{peak["period"]}）；' + ('高于1表示空缺多于失业，劳动力仍偏紧。'
                                            if latest_vu > 1 else '低于1表示失业多于空缺，劳动力供过于求。'))
        vu_item['method'] = 'JTSJOR / UNRATE 同月相除；历史分位、60月Z与3/12月动量'
        vu_item['caveats'] = ['V/U 高=劳动力偏紧；JTSJOR为空缺率、UNRATE为失业率，量纲一致的紧张度近似。',
                              '统计关联不代表因果。']

        bev = beveridge_points(raw['UNRATE'], raw['JTSJOR'])
        if bev:
            lat, older = bev['latest'], bev['points'][:-24]
            same_u = [p['v'] for p in older if abs(p['u'] - lat['u']) <= 0.3]
            pos_note = ''
            if same_u:
                pos_note = (f'相同失业率(±0.3pp)的历史空缺率均值为 {float(np.mean(same_u)):.2f}%，'
                            f'当前 {lat["v"]:.2f}% ' + ('偏高，曲线仍外移(错配/摩擦偏高)。'
                                                        if lat['v'] > float(np.mean(same_u)) else '接近或低于历史，曲线基本回归。'))
            bev_item = _item('贝弗里奇曲线',
                f'最新点：失业率 {lat["u"]:.1f}%、空缺率 {lat["v"]:.1f}%（{lat["period"]}）。{pos_note}',
                bev, [],
                '横轴失业率UNRATE、纵轴空缺率JTSJOR；同月配对；曲线右移=给定失业率下空缺更高(错配/摩擦上升)，沿曲线左下移动=正常降温',
                n_obs=len(bev['points']),
                caveats=['截面散点非时序；位置描述不构成衰退预测。', '统计关联不代表因果。'])
            bev_item.update(sample_start=bev['points'][0]['period'], sample_end=lat['period'])
        else:
            bev_item = _item('贝弗里奇曲线', 'JTSJOR 与 UNRATE 无共同月份，未计算。', None, [],
                             'UNRATE×JTSJOR 同月配对', 'missing')
    return {'positioning': positioning,
            'analyses': [sahm_item, inversion, inversion_3m, curve_item, burden_item,
                         inflation, vu_item, bev_item, real_item, labor]}


def _shift_month(period, offset):
    y,m=int(str(period)[:4]),int(str(period)[5:7]); total=y*12+m-1+offset
    return f'{total//12:04d}-{total%12+1:02d}'


def build_cross_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        shibor = _monthly_last(_rows(conn,'china_rates_observations','SHIBOR_3M'))
        dgs3 = _monthly_average(_rows(conn,'us_macro_observations','DGS3MO'))
        fx = _monthly_last(_rows(conn,'china_rates_observations','USDCNY_CENTRAL_PARITY'))
        keys, vals = _align(shibor,dgs3)
        short = [{'period':k[:7],'value':round(a-b,4)} for k,a,b in zip(keys,*vals)]
        short_change=[{'period':short[i]['period'],'value':short[i]['value']-short[i-1]['value']} for i in range(1,len(short))]
        fx_change=[{'period':fx[i]['period'],'value':fx[i]['value']-fx[i-1]['value']} for i in range(1,len(fx))]
        keys, vals = _align(short_change,fx_change)
        rc=rolling_corr(*vals,window=24,periods=[k[:7] for k in keys]) if len(keys)>=24 else []
        link=_item('中美短端利差与汇率联动', f'最新24月滚动相关 {rc[-1]["value"]:.2f}。' if rc else '共同样本不足24月。',
                   rc[-1]['value'] if rc else None,rc,'Δ(SHIBOR_3M月末−DGS3MO月均) 与 ΔUSDCNY月末的24月滚动Pearson相关',
                   'derived' if rc else 'insufficient_sample')

        lpr=_monthly_last(_rows(conn,'china_rates_observations','LPR_1Y'))
        ffr=_monthly_average(_rows(conn,'us_macro_observations','FEDFUNDS'))
        keys,vals=_align(lpr,ffr)
        divergence=[{'period':k[:7],'value':round(a-b,4),'china':a,'us':b} for k,a,b in zip(keys,*vals)]
        policy=_item('中美政策利率分化',f'最新LPR 1Y－联邦基金利率为 {divergence[-1]["value"]:.2f} 个百分点。' if divergence else '数据缺失。',
                     divergence[-1] if divergence else None,divergence,'同月 LPR_1Y − FEDFUNDS；LPR是贷款报价利率，FFR是隔夜市场政策利率')

        china=_rows(conn,'housing_national_observations','QCNR628BIS'); us=_rows(conn,'us_macro_observations','QUSR628BIS')
        cy,uy=yoy(china,4,'quarterly'),yoy(us,4,'quarterly'); keys,vals=_align(cy,uy)
        cc=cross_correlation(*vals,8,min_n=QUARTERLY_MIN_N) if keys else {'lags':[],'peak_lag':None,'peak_corr':None,'n':0,'data_status':'insufficient_sample'}
        homes=[{'period':k,'china':a,'us':b,'value':a} for k,a,b in zip(keys,*vals)]
        housing=_item('中美实际房价周期',f'峰值相位差 {cc.get("peak_lag")} 季，r={cc.get("peak_corr")}。' if cc.get('peak_lag') is not None else '共同季度样本不足。',
                      {'peak_lag':cc.get('peak_lag'),'peak_corr':cc.get('peak_corr'),'cross_correlation':cc.get('lags',[])},homes,
                      'BIS中美实际住宅价格指数各自同比；corr(China[t], US[t+lag])，lag ±8季',cc['data_status'],n_obs=cc.get('n',0),
                      caveats=['同源BIS指数但两国住房市场结构不同。','统计关联不代表因果。'])
        if keys:
            housing.update(sample_start=keys[0], sample_end=keys[-1])
        short_item=_item('中美短端利差',f'最新SHIBOR 3M－3M美债为 {short[-1]["value"]:.2f} 个百分点。' if short else '数据缺失。',
                         short[-1]['value'] if short else None,short,'SHIBOR_3M月末 − DGS3MO月均；资金利率与国债收益率口径不同')
        china_interest = _annual_budget(conn, 'budget_interest_expenditure_ytd')
        china_revenue = _annual_budget(conn, 'general_budget_revenue_ytd')
        china_burden = ratio_series(china_interest, china_revenue)
        us_interest = _rows(conn, 'us_macro_observations', 'A091RC1Q027SBEA')
        us_receipts = _rows(conn, 'us_macro_observations', 'FGRECPT')
        us_quarterly = interest_burden_series(us_interest, us_receipts)
        us_annual = {}
        for row in us_quarterly:
            us_annual[str(row['period'])[:4]] = row['value']
        china_map = {str(row['period'])[:4]: row['value'] for row in china_burden}
        burden_years = sorted(set(china_map) & set(us_annual))
        burden_compare = [{'period': year + '-12-01', 'value': china_map[year],
                           'china': china_map[year], 'us': us_annual[year]}
                          for year in burden_years]
        burden_comparison = _item('中美付息负担对照',
            (f'最新共同年中国 {burden_compare[-1]["china"]:.2f}%，'
             f'美国 {burden_compare[-1]["us"]:.2f}%。' if burden_compare else '共同年度样本缺失。'),
            burden_compare[-1] if burden_compare else None, burden_compare,
            '中国=全国一般公共预算债务付息支出/收入（现金YTD的12月点）；'
            '美国=BEA NIPA A091RC1Q027SBEA/FGRECPT（各年最后可用季度）',
            'derived' if burden_compare else 'missing',
            caveats=['中国口径不含专项债在政府性基金预算中的付息。',
                     '中国是财政现金YTD口径，美国是NIPA应计口径，数值不完全同口径。'])

        try:
            cn_cpi = _rows(conn, 'china_macro_observations', 'CN_CPI_YOY')
        except sqlite3.OperationalError:
            cn_cpi = []
        us_cpi_yoy = yoy(_rows(conn, 'us_macro_observations', 'CPIAUCSL'), 12)
        keys, values = _align(cn_cpi, [{'period': str(r['period'])[:7], 'value': r['value']}
                                       for r in us_cpi_yoy])
        infl_series = [{'period': str(k)[:7], 'cn': a, 'us': b, 'value': a} for k, a, b in zip(keys, *values)]
        infl_item = _item('中美通胀对照',
            (f'最新同月中国CPI同比 {infl_series[-1]["cn"]:.1f}%、美国 {infl_series[-1]["us"]:.1f}%，'
             f'差 {infl_series[-1]["cn"]-infl_series[-1]["us"]:+.1f} 个百分点。'
             if infl_series else '共同月份缺失。'),
            infl_series[-1] if infl_series else None, infl_series,
            '中国=统计局CPI官方同比；美国=CPIAUCSL指数12月同比(derived)；同月对齐',
            'derived' if infl_series else 'missing',
            caveats=['两国CPI篮子与统计方法不同，水平差含结构因素。', '统计关联不代表因果。'])
        if infl_item['data_status'] == 'derived':
            infl_item['compare_keys'] = [
                {'key': 'cn', 'label': '中国CPI同比', 'color': '#ff5b78'},
                {'key': 'us', 'label': '美国CPI同比', 'color': '#4f8fff'}]

        walcl_yoy = yoy(_monthly_average(_rows(conn, 'us_macro_observations', 'WALCL')), 12)
        try:
            pboc_assets = _rows(conn, 'pboc_balance_sheet_observations', 'total_assets')
        except sqlite3.OperationalError:
            pboc_assets = []
        pboc_yoy = yoy(pboc_assets, 12)
        keys, values = _align([{'period': str(r['period'])[:7], 'value': r['value']} for r in pboc_yoy],
                              [{'period': str(r['period'])[:7], 'value': r['value']} for r in walcl_yoy])
        bs_series = [{'period': str(k)[:7], 'cn': round(a, 2), 'us': round(b, 2), 'value': round(a, 2)}
                     for k, a, b in zip(keys, *values)]
        bs_item = _item('中美央行扩表对照',
            (f'最新同月央行总资产同比：中国 {bs_series[-1]["cn"]:+.1f}%、美联储 {bs_series[-1]["us"]:+.1f}%。'
             if bs_series else '共同月份不足(央行月度序列2023年起,同比自2024年起)。'),
            bs_series[-1] if bs_series else None, bs_series,
            '中国人民银行资产负债表总资产同比 vs 美联储WALCL周频月均同比；同月对齐',
            'derived' if bs_series else 'missing',
            caveats=['中方序列2023年起，同比样本短，只作方向对照不作统计推断。',
                     '扩表机制不同：美联储以证券购买为主，中国央行以对银行债权与外汇占款为主。'])
        if bs_item['data_status'] == 'derived':
            bs_item['compare_keys'] = [
                {'key': 'cn', 'label': '中国央行总资产同比', 'color': '#ff5b78'},
                {'key': 'us', 'label': '美联储总资产同比', 'color': '#4f8fff'}]
    return {'analyses':[short_item,link,policy,housing,burden_comparison,infl_item,bs_item]}


def build_debt_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        def debt_rows(code):
            return [dict(row) for row in conn.execute('''SELECT period,value FROM fiscal_debt_observations
                WHERE indicator_code=? AND value IS NOT NULL AND source_type='mof_local_debt'
                ORDER BY period''', (code,))]

        interest = _rows(conn, 'fiscal_budget_observations', 'budget_interest_expenditure_ytd')
        revenue = _rows(conn, 'fiscal_budget_observations', 'general_budget_revenue_ytd')
        fund_revenue = _rows(conn, 'fiscal_budget_observations', 'gov_fund_revenue_ytd')
        land_revenue = _rows(conn, 'fiscal_budget_observations', 'govfund_land_transfer_revenue_ytd')
        since_2019 = lambda rows: [row for row in monotonic_ytd(rows)
                                   if str(row['period'])[:4] >= '2019']
        new_issuance = since_2019(debt_rows('local_new_bond_issuance_ytd'))
        refinancing = since_2019(debt_rows('local_refinancing_bond_issuance_ytd'))
        principal = since_2019(debt_rows('official_principal_repayment_ytd'))
        local_interest = since_2019(debt_rows('official_interest_payment_ytd'))
        issue_rate = debt_rows('local_bond_avg_issue_rate')
        stock_rate = debt_rows('local_bond_avg_interest_rate')

        burden = ratio_series(interest, revenue)
        annual_burden = [row for row in burden if row['period'][5:7] == '12']
        if annual_burden:
            five_year = next((row for row in reversed(annual_burden)
                              if int(annual_burden[-1]['period'][:4]) - int(row['period'][:4]) >= 5), None)
            compare = (f'，较5年前 {annual_burden[-1]["value"]-five_year["value"]:+.2f} 个百分点'
                       if five_year else '')
            burden_conclusion = f'{annual_burden[-1]["period"][:4]}年付息负担率 {annual_burden[-1]["value"]:.2f}%{compare}。'
        else:
            burden_conclusion = '完整年度数据缺失。'
        burden_item = _item('全国一般预算付息负担率', burden_conclusion,
            annual_burden[-1]['value'] if annual_burden else None, burden,
            '债务付息支出YTD/全国一般公共预算收入YTD×100；月度同月对齐，年度水平只取12月点',
            'derived' if burden else 'missing', caveats=['不含专项债在政府性基金预算中的付息。'])

        dependency = rollover_dependency(new_issuance, refinancing)
        dependency_item = _position_item('地方债借新还旧依赖度', dependency, transform='rate')
        dependency_item['method'] = '再融资债券YTD/(新增债券YTD+再融资债券YTD)×100；同期官方累计值'
        dependency_item['caveats'] = ['再融资债券不等于全部到期本金，本指标表示发行结构中的滚续依赖。',
                                       '2019年历史稿把置换债和再融资债合并披露，该段按官方合并口径保留。']
        if len(dependency) < MONTHLY_MIN_N:
            dependency_item.update(data_status='insufficient_sample',
                                   conclusion='月频有效样本不足24期，仅展示已有值。')

        net_pressure = net_principal_pressure(principal, refinancing)
        net_item = _item('地方债净偿还压力',
            (f'最新到期本金减再融资发行为 {net_pressure[-1]["value"]:.0f} 亿元。'
             if net_pressure else '数据缺失。'),
            net_pressure[-1]['value'] if net_pressure else None, net_pressure,
            '地方债到期偿还本金YTD − 再融资债券发行YTD；负值表示再融资发行超过已披露到期本金')

        interest_fund = ratio_series(local_interest, fund_revenue)
        interest_land = ratio_series(local_interest, land_revenue)
        service_rows = []
        fund_map = {row['period']: row['value'] for row in interest_fund}
        land_map = {row['period']: row['value'] for row in interest_land}
        for period in sorted(set(fund_map) | set(land_map)):
            service_rows.append({'period': period, 'value': fund_map.get(period),
                                 'fund': fund_map.get(period), 'land': land_map.get(period)})
        service_latest = service_rows[-1] if service_rows else None
        service_item = _item('地方债付息与基金收入承受力',
            (f'最新地方债付息占基金收入 {service_latest["fund"]:.2f}%'
             + (f'，占土地出让收入 {service_latest["land"]:.2f}%。' if service_latest.get('land') is not None else '。')
             if service_latest and service_latest.get('fund') is not None else '同期分子分母数据缺失。'),
            service_latest, service_rows,
            '地方政府债券付息YTD/全国政府性基金收入YTD；若有土地出让收入则同时计算其比率',
            'derived' if service_rows else 'missing',
            caveats=['分子含一般债与专项债付息，分母是全国政府性基金/土地收入，是口径妥协，不是专项债独立付息率。'])

        rate_item = _position_item('地方债发行成本', issue_rate or stock_rate, transform='rate')
        rate_item['method'] = ('主指标为月报年初至今平均发行利率的历史分位/Z；'
                               '对照线为当年新发行加权利率 vs 全部存续债券存量加权平均利率，同工具口径一致可比')
        rate_item['caveats'] = ['新发行利率为当年加权，存量为全部存续债券加权，二者口径一致可比；'
                                '地方债定价基准实为同期限国债收益率（库内暂无），此处只做同工具新旧对照。',
                                '统计关联不代表因果。']
        rk, rv = _align(issue_rate, stock_rate)
        if rk:
            rate_item['series'] = [{'period': k[:7], 'issue': iss, 'stock': stk}
                                   for k, iss, stk in zip(rk, rv[0], rv[1])]
            rate_item['compare_keys'] = [
                {'key': 'issue', 'label': '当年新发行加权利率', 'color': '#4f8fff'},
                {'key': 'stock', 'label': '存量加权平均利率', 'color': '#f5a623'}]
            latest_issue = rate_item['series'][-1]['issue']
            latest_stock = rate_item['series'][-1]['stock']
            gap = round(latest_stock - latest_issue, 4)
            rate_item['conclusion'] = (
                f'最新新发行利率 {latest_issue:.2f}%，'
                f'{"低于" if gap > 0 else "高于"}存量加权 {latest_stock:.2f}% {abs(gap):.2f} 个百分点，'
                + ('低成本再融资持续摊薄债务付息成本。' if gap > 0 else '新发行成本已高于存量存续债券。'))
            rate_item['sample_start'] = rate_item['series'][0]['period']
            rate_item['sample_end'] = rate_item['series'][-1]['period']
            rate_item['n_obs'] = len(rate_item['series'])

        central = _annual_budget_like_debt(conn, 'central_government_debt_balance')
        local = _annual_budget_like_debt(conn, 'local_debt_balance_total')
        general_annual = _annual_budget(conn, 'general_budget_revenue_ytd')
        fund_annual = _annual_budget(conn, 'gov_fund_revenue_ytd')
        keys, values = _align(central, local, general_annual, fund_annual)
        debt_capacity = [{'period': key[:4], 'value': round((c + l) / (g + f), 4)}
                         for key, c, l, g, f in zip(keys, *values) if g + f]
        capacity_item = _item('政府债务余额/综合财力',
            (f'{debt_capacity[-1]["period"]}年显性债务余额为两本账收入 {debt_capacity[-1]["value"]:.2f} 倍。'
             if debt_capacity else '中央债务史短，暂无完整同期年度点。'),
            debt_capacity[-1]['value'] if debt_capacity else None, debt_capacity,
            '(中央政府债务余额+地方政府债务余额)/(一般公共预算收入+政府性基金收入)；只取12月同期点',
            'derived' if debt_capacity else 'insufficient_sample',
            caveats=['中央债务官方序列2024年起，样本极少，只报最新点，不作趋势判断。'])

        try:
            gdp_nominal = _rows(conn, 'china_macro_observations', 'CN_GDP_Q_NOMINAL')
        except sqlite3.OperationalError:
            gdp_nominal = []
        rolling_gdp = {row['period']: row['value'] for row in rolling_four_quarter_sum(gdp_nominal)}
        keys, values = _align(central, local)
        debt_gdp = []
        for k, c_val, l_val in zip(keys, *values):
            quarter = str(k)[:7]
            if quarter in rolling_gdp and rolling_gdp[quarter]:
                debt_gdp.append({'period': quarter,
                                 'value': round((c_val + l_val) / rolling_gdp[quarter] * 100, 2)})
        gdp_ratio_item = _item('政府债务/GDP',
            (f'最新显性政府债务(国债+地方债)占滚动4季名义GDP {debt_gdp[-1]["value"]:.1f}%'
             f'（{debt_gdp[-1]["period"]}）。' if debt_gdp else '中央债务与GDP共同季度不足。'),
            debt_gdp[-1]['value'] if debt_gdp else None, debt_gdp,
            '(中央政府债务余额+地方政府债务余额)/最近4个连续季度现价GDP之和 ×100；同季对齐',
            'derived' if debt_gdp else 'insufficient_sample',
            caveats=['显性政府债券口径，不含城投等或有债务(无官方口径)。',
                     '中央债务季度序列2024年起，样本短，只作水平参考。'])

        latest_revenue = general_annual[-1]['value'] if general_annual else None
        latest_revenue_year = general_annual[-1]['period'][:4] if general_annual else None
        start_year = datetime.now().year
        maturity = [dict(row) for row in conn.execute('''SELECT maturity_year period,
            SUM(actual_issue_amount) value FROM mof_treasury_bond_issuances
            WHERE maturity_year BETWEEN ? AND ? AND actual_issue_amount IS NOT NULL
            GROUP BY maturity_year ORDER BY maturity_year''', (start_year, start_year + 4))]
        due_total = sum(row['value'] for row in maturity)
        due_ratio = due_total / latest_revenue if latest_revenue else None
        treasury_item = _item('未来五年国债到期壁',
            (f'已抓取国债未来五年到期 {due_total:.0f} 亿元，相当于'
             f'{latest_revenue_year}年一般预算收入 {due_ratio:.2f} 倍。'
             if maturity and due_ratio is not None else '国债到期表或年度收入缺失。'),
            {'maturity_total': due_total, 'revenue_multiple': due_ratio}, maturity,
            f'已抓取逐只国债{start_year}-{start_year+4}年actual_issue_amount按到期年汇总/最新年度一般预算收入',
            'derived' if maturity and due_ratio is not None else 'missing',
            caveats=['只覆盖已抓取的2024年起逐只国债，非全部存量到期表；票息付息仅可作下限估计。'])

    return {'positioning': [dependency_item, rate_item],
            'analyses': [burden_item, net_item, service_item, capacity_item, gdp_ratio_item,
                         treasury_item],
            'notes': ['城投等企业信用类政府关联债务无官方认定口径，本页仅覆盖政府债券，不提供城投债数字。']}


def build_housing_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        new_rows = [dict(r) for r in conn.execute(
            "SELECT city,period,value FROM housing_city_observations "
            "WHERE indicator_code='new_home_mom_idx' AND value IS NOT NULL ORDER BY period")]
        sec_rows = [dict(r) for r in conn.execute(
            "SELECT city,period,value FROM housing_city_observations "
            "WHERE indicator_code='second_home_mom_idx' AND value IS NOT NULL ORDER BY period")]
        sec_yoy_rows = [dict(r) for r in conn.execute(
            "SELECT period,value FROM housing_city_observations "
            "WHERE indicator_code='second_home_yoy_idx' AND value IS NOT NULL ORDER BY period")]
        sales_area_official = _rows(conn, 'housing_national_observations',
                                    'sales_area_ytd_yoy_official')
        sales_area_level = _rows(conn, 'housing_national_observations', 'sales_area_ytd')
        sales_value_official = _rows(conn, 'housing_national_observations',
                                     'sales_value_ytd_yoy_official')
        sales_value_level = _rows(conn, 'housing_national_observations', 'sales_value_ytd')
        land_official = _rows(conn, 'fiscal_budget_observations',
                              'govfund_land_transfer_revenue_ytd_yoy_official')
        land_level = _rows(conn, 'fiscal_budget_observations',
                           'govfund_land_transfer_revenue_ytd')
        fund_level = _rows(conn, 'fiscal_budget_observations', 'gov_fund_revenue_ytd')
        general_level = _rows(conn, 'fiscal_budget_observations', 'general_budget_revenue_ytd')
    new_diff, sec_diff = _diffusion_from_rows(new_rows), _diffusion_from_rows(sec_rows)

    area_yoy, area_derived, area_source = preferred_official_yoy(
        sales_area_official, sales_area_level)
    value_yoy, value_derived, value_source = preferred_official_yoy(
        sales_value_official, sales_value_level)
    land_yoy, land_derived, land_source = preferred_official_yoy(land_official, land_level)

    def comparison_caveat(official, derived, label):
        keys, values = _align(official, derived)
        if not keys:
            return '累计值直除同比仅作补充；统计范围调整年份与官方可比口径同比存在偏差。'
        difference = values[0][-1] - values[1][-1]
        return (f'{keys[-1][:7]}{label}官方同比与累计值直除同比相差 {difference:+.2f} 个百分点；'
                '统计范围调整年份与官方可比口径同比存在偏差。')

    area_pos = _position_item('商品房销售面积累计同比', area_yoy, transform='rate')
    area_pos['method'] = ('优先使用国家统计局公布的累计同比（可比口径）；无官方同比时才以同月累计值直除补充；'
                          f'本卡当前来源={area_source}')
    area_pos['caveats'] = [comparison_caveat(sales_area_official, area_derived, '销售面积'),
                           '1-2月合并记为2月，不拆分或桥接1月。', '统计关联不代表因果。']
    if len(area_yoy) < MONTHLY_MIN_N:
        area_pos.update(conclusion='月频有效样本不足24期，拒绝定位判断。', value=None,
                        data_status='insufficient_sample')

    land_pos = _position_item('土地出让收入累计同比', land_yoy, transform='rate')
    land_pos['method'] = ('优先使用财政部公布的国有土地使用权出让收入累计同比（可比口径）；'
                          f'无官方同比时才以同月累计值直除补充；本卡当前来源={land_source}')
    land_pos['caveats'] = [comparison_caveat(land_official, land_derived, '土地出让收入'),
                           '统计关联不代表因果。']
    if len(land_yoy) < MONTHLY_MIN_N:
        land_pos.update(conclusion='月频有效样本不足24期，拒绝定位判断。', value=None,
                        data_status='insufficient_sample')

    new_pos = _position_item('70城新房扩散指数', new_diff, transform='rate')
    n = new_diff[-1] if new_diff else None
    new_pos['conclusion'] = (f'最新70城中 {n["up"]}城新房环比上涨、{n["down"]}城下跌，扩散指数 {n["value"]:.1f}%（50%为荣枯线）。'
                             if n else '数据缺失。')
    new_pos['method'] = '每期统计新房环比指数>100(上涨)的城市占比；扩散指数=上涨城市数/总城市数×100，>50示涨多跌少'

    sec_pos = _position_item('70城二手扩散指数', sec_diff, transform='rate')
    s = sec_diff[-1] if sec_diff else None
    sec_pos['conclusion'] = (f'最新70城中 {s["up"]}城二手环比上涨、{s["down"]}城下跌，扩散指数 {s["value"]:.1f}%。'
                             if s else '数据缺失。')
    sec_pos['method'] = '每期统计二手房环比指数>100的城市占比；口径同新房扩散指数'

    keys, vals = _align(new_diff, sec_diff)
    diverge = [{'period': k, 'value': round(b - a, 2)} for k, a, b in zip(keys, *vals)]
    dv = diverge[-1]['value'] if diverge else None
    diverge_item = _item('新房-二手扩散背离',
        (f'二手扩散指数减新房 {dv:+.1f} 个百分点，二手市场{"更强" if dv > 0 else "更弱"}；二手更贴近真实供求。'
         if diverge else '数据缺失。'), dv, diverge,
        '二手扩散指数 − 新房扩散指数；二手房政策定价扰动小、更贴近市场供求，负值示真实需求弱于一手',
        caveats=['扩散指数只计涨跌广度，不含涨跌幅度。', '统计关联不代表因果。'])

    tier1 = _diffusion_from_rows([r for r in new_rows if r['city'] in CITY_TIER1])
    rest = _diffusion_from_rows([r for r in new_rows if r['city'] not in CITY_TIER1])
    keys, vals = _align(tier1, rest)
    split = [{'period': k, 'value': round(a - b, 2)} for k, a, b in zip(keys, *vals)]
    sp = split[-1]['value'] if split else None
    split_item = _item('一线-非一线分化',
        (f'一线扩散指数减其余城市 {sp:+.1f} 个百分点，一线{"领先" if sp > 0 else "落后"}于其他城市。'
         if split else '数据缺失。'), sp, split,
        '一线(北京/上海/广州/深圳)新房扩散指数 − 其余城市扩散指数；四个一线为公认口径',
        caveats=['一线仅4城，扩散指数粒度较粗。', '统计关联不代表因果。'])

    def lag_item(title, x_rows, y_rows, x_label, y_label):
        keys, values = _align(x_rows, y_rows)
        result = (cross_correlation(*values, 12, min_n=MONTHLY_MIN_N) if keys else
                  {'lags': [], 'peak_lag': None, 'peak_corr': None,
                   'n': 0, 'data_status': 'insufficient_sample'})
        conclusion = (
            f'峰值相关 lag={result["peak_lag"]:+d} 月，r={result["peak_corr"]:.3f}；'
            f'{"前者领先后者" if result["peak_lag"] > 0 else "前者滞后后者" if result["peak_lag"] < 0 else "两者同步"}。'
            if result.get('peak_lag') is not None else '共同月频同比样本不足24期，拒绝计算。')
        item = _item(title, conclusion,
                     {'peak_lag': result.get('peak_lag'), 'peak_corr': result.get('peak_corr')},
                     [{'period': row['lag'], 'value': row['r']} for row in result['lags']
                      if row['r'] is not None],
                     f'仅用官方累计同比；corr({x_label}[t], {y_label}[t+lag])，lag ±12月；正lag表示前者领先',
                     result['data_status'], n_obs=result.get('n', 0),
                     caveats=['领先、滞后与同步相关均不代表因果。'])
        if keys:
            item.update(sample_start=keys[0][:7], sample_end=keys[-1][:7])
        return item

    sales_price_lag = lag_item('销售与房价扩散领先滞后', area_yoy, sec_diff,
                               '销售面积官方累计同比', '70城二手扩散指数')
    sales_land_lag = lag_item('销售与土地收入领先滞后', value_yoy, land_yoy,
                              '销售额官方累计同比', '土地出让收入官方累计同比')

    roll_keys, roll_values = _align(value_yoy, land_yoy)
    roll = (rolling_corr(*roll_values, window=24, periods=[key[:7] for key in roll_keys])
            if len(roll_keys) >= 24 else [])
    rolling_item = _item('销售额与土地收入24月滚动相关',
        f'最新24月滚动相关为 {roll[-1]["value"]:.3f}。' if roll else '共同月频同比样本不足24期，拒绝计算。',
        roll[-1]['value'] if roll else None, roll,
        '销售额官方累计同比与土地出让收入官方累计同比，同月对齐后的24月滚动Pearson相关',
        'derived' if roll else 'insufficient_sample',
        n_obs=len(roll_keys),
        caveats=['滚动相关只描述传导紧密程度变化，不代表因果。'])
    if roll_keys:
        rolling_item.update(sample_start=roll_keys[0][:7], sample_end=roll_keys[-1][:7])

    fund_share, combined_share = land_fiscal_dependency(land_level, fund_level, general_level)
    if fund_share and combined_share:
        peak = max(fund_share, key=lambda row: row['value'])
        dependency_conclusion = (
            f'{fund_share[-1]["period"]}年土地收入占政府性基金收入 {fund_share[-1]["value"]:.1f}%，'
            f'占两本账收入 {combined_share[-1]["value"]:.1f}%；基金口径峰值为'
            f'{peak["period"]}年 {peak["value"]:.1f}%。')
        dependency_status = 'derived'
    else:
        dependency_conclusion, dependency_status = '完整年度共同样本缺失。', 'missing'
    dependency_series = [
        {'period': row['period'], 'value': row['value'],
         'combined_share': next((x['value'] for x in combined_share if x['period'] == row['period']), None)}
        for row in fund_share]
    dependency_item = _item('土地财政依赖度', dependency_conclusion,
        {'fund_share': fund_share, 'combined_share': combined_share}, dependency_series,
        '仅取12月累计：土地出让收入/政府性基金收入，以及土地出让收入/(一般公共预算收入+基金收入)×100',
        dependency_status,
        caveats=['分母为全国口径；常用的“/地方一般预算收入”口径因无地方分列数据不做。',
                 '年度描述性指标，不做相关或因果解读。'])

    by_city = {}
    for row in sec_rows:
        by_city.setdefault(CITY_RENAMES.get(row['city'], row['city']), []).append(
            {'period': row['period'], 'value': row['value']})
    city_table = []
    for city, rows in by_city.items():
        stats = drawdown_from_index(chain_mom_index(rows))
        if stats:
            city_table.append({'city': city, 'peak_period': stats['peak_period'],
                               'drawdown': stats['drawdown_pct'],
                               'months_since_peak': stats['months_since_peak'],
                               'streak': current_decline_streak(rows)})
    city_table.sort(key=lambda r: r['drawdown'])
    if city_table:
        deepest = city_table[0]
        median_dd = float(np.median([r['drawdown'] for r in city_table]))
        declining = sum(1 for r in city_table if r['streak'] > 0)
        drawdown_item = _item('70城二手累计回撤',
            (f'70城二手房自各自峰值的中位累计回撤 {median_dd:.1f}%；最深 {deepest["city"]} '
             f'{deepest["drawdown"]:.1f}%（峰值 {deepest["peak_period"]}）；'
             f'{declining}/{len(city_table)} 城最新仍在连跌。'),
            {'cities': city_table,
             'summary': {'median_drawdown': round(median_dd, 2), 'declining': declining,
                         'total': len(city_table)}}, [],
            '官方二手环比指数逐城链式累乘为定基指数(基期=首期前一月=100)，取峰值至今涨跌幅；'
            '连跌=尾部连续环比<100的月数；缺月断链不桥接',
            n_obs=len(sec_rows),
            caveats=['官方不发布定基指数，此为环比链式 derived 估计；环比保留0.1精度，'
                     '长期累乘存在约±1-2个百分点量级的舍入累积误差。',
                     '襄樊2010年更名襄阳，两段序列已按同城合并。',
                     '官方指数为成交结构加权，回撤幅度通常温和于挂牌价口径。'])
        drawdown_item.update(
            sample_start=str(min(rows[0]['period'] for rows in by_city.values()))[:7],
            sample_end=str(max(row['period'] for row in sec_rows))[:7])
    else:
        drawdown_item = _item('70城二手累计回撤', '逐城环比序列缺失，未计算。', None, [],
                              '官方二手环比链式累乘', 'missing')

    dispersion = cross_city_dispersion(sec_yoy_rows)
    dispersion_item = _position_item('70城同比分化度', dispersion, transform='rate')
    if dispersion:
        z = dispersion_item['value'].get('z_score')
        dispersion_item['conclusion'] = (
            f'70城二手同比的跨城标准差 {dispersion[-1]["value"]:.2f}，'
            f'历史分位 {dispersion_item["value"]["percentile"]:.0f}%——'
            + ('城市间分化偏高，各走各路。' if (z or 0) > 0 else '城市间趋同，同涨同跌。'))
    dispersion_item['method'] = '每期70城二手同比指数的跨城样本标准差(ddof=1)；高=分化、低=同涨同跌'
    dispersion_item['caveats'] = ['分化度只计离散程度，不区分涨跌方向。', '统计关联不代表因果。']

    return {'positioning': [new_pos, sec_pos, area_pos, land_pos],
            'analyses': [diverge_item, split_item, drawdown_item, dispersion_item,
                         sales_price_lag, sales_land_lag, rolling_item, dependency_item]}


# 全景摘要选卡:(tab, 卡标题, 摘要标签, 数值后缀)
SUMMARY_PICKS = [
    ('china', 'GDP单季实际同比定位', '中国GDP同比', '%'),
    ('china', 'CPI 同比定位', '中国CPI', '%'),
    ('china', '制造业PMI定位', '制造业PMI', '%'),
    ('china', '社融存量同比定位', '社融同比', '%'),
    ('china', '宏观杠杆率(社融口径)', '宏观杠杆率', '%'),
    ('housing', '70城二手扩散指数', '二手房扩散', '%'),
    ('us', '失业率定位', '美国失业率', '%'),
    ('us', '核心PCE同比定位', '美核心PCE', '%'),
    ('us', '10Y−3M 定位', '美10Y−3M', 'pp'),
    ('us', '劳动力市场紧张度 V/U', '美V/U比', ''),
    ('debt', '全国一般预算付息负担率', '付息/收入', '%'),
    ('debt', '地方债借新还旧依赖度', '借新还旧', '%'),
]


def build_panorama_summary(payload):
    """从各块既有定位卡提取当前值与历史分位,组成一屏摘要。
    只转述已计算结果,不新增判断;分位仅作色温展示,不代表好坏。"""
    summary = []
    for tab, title, label, suffix in SUMMARY_PICKS:
        block = payload.get(tab) or {}
        item = next((a for a in (block.get('positioning', []) + block.get('analyses', []))
                     if a.get('title') == title), None)
        if not item or item.get('data_status') not in ('derived',):
            continue
        value = item.get('value')
        if isinstance(value, dict):
            current, percentile = value.get('current'), value.get('percentile')
        elif isinstance(value, (int, float)):
            current, percentile = value, None
        else:
            continue
        if current is None:
            continue
        summary.append({'tab': tab, 'label': label, 'suffix': suffix,
                        'current': current, 'percentile': percentile,
                        'sample_end': item.get('sample_end')})
    return summary


def build_macro_analytics_payload(db_path):
    payload = {'china':build_china_analytics(db_path),'us':build_us_analytics(db_path),
               'cross':build_cross_analytics(db_path),'housing':build_housing_analytics(db_path),
               'debt':build_debt_analytics(db_path),
               'generated_at':datetime.now().isoformat(),
               'notes':['所有结果均为derived；相关分析只使用同比或差分序列。',
                        '领先相关、滞后相关与同步不代表因果；v1不含预测、VAR、Granger或协整。']}
    payload['summary'] = build_panorama_summary(payload)
    return payload
