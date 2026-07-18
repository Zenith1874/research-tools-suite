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
        positioning = [_position_item('M2 同比定位', m2y, transform='rate'),
                       _position_item('社融存量同比定位', sfy, transform='rate'),
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
        keys, vals = _align(central, local)
        debt_total = [{'period': k, 'value': a+b} for k, a, b in zip(keys, *vals)]
        debt_annual = [r for r in debt_total if str(r['period'])[5:7] == '12']
        debt_y = yoy(debt_annual, 1, 'annual')
        keys, vals = _align(debt_y, rev_y)
        debt_gap = [{'period': k[:4], 'value': round(a-b, 4)} for k, a, b in zip(keys, *vals)]
        gap_status = 'derived' if len(debt_gap) >= QUARTERLY_MIN_N else 'insufficient_sample'
        debt_item = _item('债务可持续性差', '年度同口径样本不足16期，拒绝方向判断。' if gap_status != 'derived' else ('债务增速高于收入增速。' if debt_gap[-1]['value'] > 0 else '收入增速高于债务增速。'),
                          debt_gap[-1]['value'] if debt_gap and gap_status == 'derived' else None, debt_gap,
                          '中央+地方政府债务余额YoY − 一般公共预算收入YoY；完整年度', gap_status)

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
    return {'positioning': positioning,
            'analyses': [scissors_item, transmission, fiscal, debt_item, spread_item, vol_item]}


def _monthly_average(rows):
    buckets = {}
    for row in rows:
        buckets.setdefault(str(row['period'])[:7], []).append(row['value'])
    return [{'period': key, 'value': round(float(np.mean(buckets[key])), 6)} for key in sorted(buckets)]


def build_us_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        raw = {code: _rows(conn, 'us_macro_observations', code) for code in
               ('UNRATE','PCEPILFE','GDPC1','DGS10','T10Y2Y','MORTGAGE30US','USREC','T10YIE','JTSJOL','JTSQUR','JTSHIR')}
        core_yoy = yoy(raw['PCEPILFE'], 12)
        gdp_qoq = []
        for i in range(1, len(raw['GDPC1'])):
            gdp_qoq.append({'period': raw['GDPC1'][i]['period'], 'value': round(((raw['GDPC1'][i]['value']/raw['GDPC1'][i-1]['value'])**4-1)*100, 4)})
        positioning = [_position_item('失业率定位', raw['UNRATE'], transform='rate'),
                       _position_item('核心PCE同比定位', core_yoy, transform='rate'),
                       _position_item('实际GDP环比年化定位', gdp_qoq, 'quarterly', 'rate'),
                       _position_item('10年期美债定位', _monthly_average(raw['DGS10']), transform='rate'),
                       _position_item('10Y－2Y期限利差定位', _monthly_average(raw['T10Y2Y']), transform='rate'),
                       _position_item('30年房贷利率定位', _monthly_average(raw['MORTGAGE30US']), transform='rate')]

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
        episodes = identify_inversion_episodes(spread_m)
        horizons = (6,12,18,24)
        for ep in episodes:
            ep['recession_after'] = {str(h): bool(max(rec_map.get(_shift_month(ep['end'], m), 0) for m in range(1,h+1))) for h in horizons}
        frequency = {str(h): {'hits': sum(ep['recession_after'][str(h)] for ep in episodes), 'episodes': len(episodes),
                              'frequency': round(sum(ep['recession_after'][str(h)] for ep in episodes)/len(episodes)*100, 1) if episodes else None} for h in horizons}
        inversion = _item('期限利差倒挂经验表', f'识别到 {len(episodes)} 个持续至少2个月的倒挂区间。',
                          {'episodes': episodes, 'frequency': frequency}, spread_m,
                          'T10Y2Y日频按月均值；<0连续至少2月；检查结束后6/12/18/24月USREC；仅报经验频率')

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
    return {'positioning': positioning, 'analyses': [sahm_item, inversion, inflation, real_item, labor]}


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
    return {'analyses':[short_item,link,policy,housing]}


def build_housing_analytics(db_path):
    with closing(_connect(db_path)) as conn:
        new_rows = [dict(r) for r in conn.execute(
            "SELECT city,period,value FROM housing_city_observations "
            "WHERE indicator_code='new_home_mom_idx' AND value IS NOT NULL ORDER BY period")]
        sec_rows = [dict(r) for r in conn.execute(
            "SELECT city,period,value FROM housing_city_observations "
            "WHERE indicator_code='second_home_mom_idx' AND value IS NOT NULL ORDER BY period")]
    new_diff, sec_diff = _diffusion_from_rows(new_rows), _diffusion_from_rows(sec_rows)

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

    return {'positioning': [new_pos, sec_pos], 'analyses': [diverge_item, split_item]}


def build_macro_analytics_payload(db_path):
    return {'china':build_china_analytics(db_path),'us':build_us_analytics(db_path),
            'cross':build_cross_analytics(db_path),'housing':build_housing_analytics(db_path),
            'generated_at':datetime.now().isoformat(),
            'notes':['所有结果均为derived；相关分析只使用同比或差分序列。',
                     '领先相关、滞后相关与同步不代表因果；v1不含预测、VAR、Granger或协整。']}
