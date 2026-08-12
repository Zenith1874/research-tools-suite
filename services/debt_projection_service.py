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
import os
import sqlite3
from datetime import datetime

from services.debt_ceiling_service import build_ceiling_payload
from services.lgfv_bond_scenario_service import build_lgfv_bond_scenario_payload

DEFAULT_HORIZON = 25          # 最多外推 25 年，超出则报"本世纪中叶前不触及"
THRESHOLDS = (0.10, 0.15, 0.20)
SENSITIVITY_DELTAS = (-0.02, 0.0, 0.02)

# 财政部首次连续披露“法定政府债务 + 地方隐性债务”的全口径锚点。
# 单位均为亿元；报告正文只给到 0.1 万亿元，因此保留 reported_* 字段，
# 与预算报告中的精确法定债务余额分开，避免把四舍五入差异误判为数据冲突。
OFFICIAL_BROAD_DEBT_ANCHORS = {
    '2023': {
        'reported_treasury_balance': 300000.0,
        'reported_local_legal_balance': 407000.0,
        'hidden_debt_balance': 143000.0,
        'reported_broad_total': 850000.0,
        'gdp': 1260600.0,
        'reported_debt_to_gdp_pct': 67.5,
        'source_url': ('https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/'
                       '202411/t20241109_3947230.htm'),
        'source_title': '增加地方政府债务限额置换存量隐性债务有关政策情况新闻发布会',
    },
    '2024': {
        'reported_treasury_balance': 346000.0,
        'reported_local_legal_balance': 475000.0,
        'hidden_debt_balance': 105000.0,
        'reported_broad_total': 926000.0,
        'gdp': 1349000.0,
        'reported_debt_to_gdp_pct': 68.7,
        'source_url': ('https://zwgls.mof.gov.cn/gzdt/202511/'
                       't20251102_3975538.htm'),
        'source_title': '国务院关于2024年度政府债务管理情况的报告',
    },
}

HIDDEN_DEBT_2025_SCENARIO = {
    'period': '2025',
    'anchor_period': '2024',
    'confirmed_swap': 20000.0,
    'annual_special_bond_resource': 8000.0,
    'gdp': 1401879.0,
    'swap_source_url': ('https://bgt.mof.gov.cn/zhuantilanmu/rdwyh/czyw/'
                        '202603/t20260316_3985331.htm'),
    'policy_source_url': ('https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/'
                          '202411/t20241109_3947230.htm'),
    'gdp_source_url': ('https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/'
                       '202601/t20260120_1962349.html'),
}

BROAD_ANCHOR_INDICATORS = {
    'reported_treasury_balance': ('treasury_debt_balance_reported_rounded', '国债余额（报告四舍五入口径）', '亿元'),
    'reported_local_legal_balance': ('local_legal_debt_balance_reported_rounded', '地方法定债务余额（报告四舍五入口径）', '亿元'),
    'hidden_debt_balance': ('local_hidden_debt_balance', '地方政府隐性债务余额', '亿元'),
    'reported_broad_total': ('broad_government_debt_reported', '全国政府全口径债务总额（报告值）', '亿元'),
    'gdp': ('gdp_for_broad_debt_ratio', '债务报告采用的GDP', '亿元'),
    'reported_debt_to_gdp_pct': ('broad_government_debt_to_gdp_reported', '全国政府全口径负债率（报告值）', '%'),
}


def _cagr(first, last, years):
    if not first or not last or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def _pct(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100.0, 4)


def upsert_broad_debt_anchors(db_path):
    """Persist manually registered official report values with full provenance."""
    from services.fiscal_debt_service import ensure_fiscal_tables

    now = datetime.now().isoformat()
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    written = 0
    try:
        ensure_fiscal_tables(conn)
        for period, anchor in sorted(OFFICIAL_BROAD_DEBT_ANCHORS.items()):
            for source_key, (code, name, unit) in BROAD_ANCHOR_INDICATORS.items():
                value = anchor[source_key]
                conn.execute('''
                    INSERT INTO fiscal_debt_observations
                      (indicator_code,indicator_name,value,unit_raw,unit_display,scale_factor,
                       period,date,frequency,source_name,source_type,source_url,source_title,
                       parser_notes,data_status,is_mock,is_seed,is_cache,debt_line,module_code,
                       raw_text,created_at,updated_at)
                    VALUES (?,?,?,?,?,1.0,?,?,'annual','财政部','mof_broad_debt_report',?,?,?,
                            'official',0,0,0,'broad_government_debt','broad_government_debt',?,?,?)
                    ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
                      value=excluded.value,unit_raw=excluded.unit_raw,
                      unit_display=excluded.unit_display,source_url=excluded.source_url,
                      source_title=excluded.source_title,parser_notes=excluded.parser_notes,
                      raw_text=excluded.raw_text,updated_at=excluded.updated_at
                ''', (code, name, value, unit, unit, period, f'{period}-12-31',
                      anchor['source_url'], anchor['source_title'],
                      ('财政部报告正文直陈值；金额按报告0.1万亿元口径登记。'
                       '法定债务限额分析继续使用预算报告精确值。'),
                      f'{period} {name}: {value} {unit}', now, now))
                written += 1
        conn.commit()
        count = conn.execute('''SELECT COUNT(*) FROM fiscal_debt_observations
                                WHERE module_code='broad_government_debt' ''').fetchone()[0]
        return {'success': True, 'records_upserted': written,
                'stored_record_count': count, 'periods': sorted(OFFICIAL_BROAD_DEBT_ANCHORS)}
    except Exception as exc:
        conn.rollback()
        return {'success': False, 'error': str(exc), 'records_upserted': 0}
    finally:
        conn.close()


def estimate_hidden_debt_range(anchor_hidden, confirmed_swap,
                               annual_special_bond_resource):
    """Build a transparent, non-probabilistic residual-hidden-debt interval.

    Upper path subtracts only the confirmed swap issuance.  Lower path also
    assumes the annual special-bond resource reduces hidden-debt principal
    one-for-one.  The latter is deliberately an assumption: the policy resource
    replenishes government-fund fiscal capacity and need not equal principal
    retired in the same year.
    """
    values = (anchor_hidden, confirmed_swap, annual_special_bond_resource)
    if any(value is None or value < 0 for value in values):
        return {'status': 'missing'}
    upper = max(0.0, anchor_hidden - confirmed_swap)
    lower = max(0.0, upper - annual_special_bond_resource)
    return {
        'status': 'scenario',
        'low': round(lower, 2),
        'mid': round((lower + upper) / 2.0, 2),
        'high': round(upper, 2),
        'formula_low': ('anchor_hidden_debt - confirmed_swap '
                        '- annual_special_bond_resource'),
        'formula_high': 'anchor_hidden_debt - confirmed_swap',
        'assumption': ('无新增隐性债务；低位另假设年度8000亿元化债资源全部按1:1冲减'
                       '隐性债务本金，高位只扣除已确认置换债。区间无概率含义。'),
    }


def audit_lgfv_records(conn):
    """Audit actual LGFV observations; placeholder registry rows do not count."""
    try:
        row = conn.execute('''
            SELECT COUNT(*) AS n, MIN(period) AS sample_start,
                   MAX(period) AS sample_end,
                   GROUP_CONCAT(DISTINCT source_type) AS source_types,
                   SUM(CASE WHEN COALESCE(TRIM(source_url),'')='' THEN 1 ELSE 0 END)
                       AS missing_source_count
            FROM fiscal_debt_observations
            WHERE debt_line='lgfv_debt' OR lower(indicator_code) LIKE 'lgfv%'
        ''').fetchone()
    except sqlite3.OperationalError:
        row = None
    count = int(row[0] or 0) if row else 0
    return {
        'data_status': 'missing' if count == 0 else 'available_not_integrated',
        'record_count': count,
        'sample_start': row[1] if row else None,
        'sample_end': row[2] if row else None,
        'source_types': (row[3].split(',') if row and row[3] else []),
        'missing_source_count': int(row[4] or 0) if row else 0,
        'included_in_broad_total': False,
        'reason': ('当前库只有 LGFV 字段和来源占位，没有任何城投债数值记录。'
                   if count == 0 else
                   '发现本地城投记录，但在完成发行人分类、跨市场去重和来源授权审计前不自动并表。'),
        'scope_note': ('城投债是按发行人名单识别的企业债券，不等于财政部监测的隐性债务；'
                       '两者不可相加，也不能互相替代。'),
    }


def build_broad_government_debt(years):
    """Combine exact legal debt with official hidden-debt anchors and 2025 range."""
    by_year = {row.get('period'): row for row in years}
    records = []
    for period, anchor in sorted(OFFICIAL_BROAD_DEBT_ANCHORS.items()):
        legal = by_year.get(period, {})
        treasury = legal.get('treasury_balance')
        local = legal.get('local_balance')
        if treasury is None:
            treasury = anchor['reported_treasury_balance']
        if local is None:
            local = anchor['reported_local_legal_balance']
        hidden = anchor['hidden_debt_balance']
        calculated = treasury + local + hidden
        records.append({
            'period': period,
            'label': f'{period} 官方',
            'treasury_balance': round(treasury, 2),
            'local_legal_balance': round(local, 2),
            'legal_debt_total': round(treasury + local, 2),
            'hidden_debt_low': hidden,
            'hidden_debt_mid': hidden,
            'hidden_debt_high': hidden,
            'broad_total_low': round(calculated, 2),
            'broad_total_mid': round(calculated, 2),
            'broad_total_high': round(calculated, 2),
            'gdp': anchor['gdp'],
            'debt_to_gdp_low_pct': _pct(calculated, anchor['gdp']),
            'debt_to_gdp_mid_pct': _pct(calculated, anchor['gdp']),
            'debt_to_gdp_high_pct': _pct(calculated, anchor['gdp']),
            'reported_broad_total': anchor['reported_broad_total'],
            'reported_debt_to_gdp_pct': anchor['reported_debt_to_gdp_pct'],
            'rounding_gap': round(calculated - anchor['reported_broad_total'], 2),
            'legal_data_status': 'official',
            'hidden_data_status': 'official',
            'data_status': 'derived',
            'source_url': anchor['source_url'],
            'source_title': anchor['source_title'],
            'formula': 'treasury_balance + local_legal_balance + hidden_debt_balance',
        })

    scenario = HIDDEN_DEBT_2025_SCENARIO
    legal = by_year.get(scenario['period'], {})
    treasury = legal.get('treasury_balance')
    local = legal.get('local_balance')
    anchor = OFFICIAL_BROAD_DEBT_ANCHORS.get(scenario['anchor_period'])
    hidden_range = estimate_hidden_debt_range(
        anchor.get('hidden_debt_balance') if anchor else None,
        scenario['confirmed_swap'], scenario['annual_special_bond_resource'])
    if treasury is not None and local is not None and hidden_range.get('status') == 'scenario':
        legal_total = treasury + local
        low = legal_total + hidden_range['low']
        mid = legal_total + hidden_range['mid']
        high = legal_total + hidden_range['high']
        records.append({
            'period': scenario['period'],
            'label': f"{scenario['period']} 情景区间",
            'treasury_balance': round(treasury, 2),
            'local_legal_balance': round(local, 2),
            'legal_debt_total': round(legal_total, 2),
            'hidden_debt_low': hidden_range['low'],
            'hidden_debt_mid': hidden_range['mid'],
            'hidden_debt_high': hidden_range['high'],
            'broad_total_low': round(low, 2),
            'broad_total_mid': round(mid, 2),
            'broad_total_high': round(high, 2),
            'gdp': scenario['gdp'],
            'debt_to_gdp_low_pct': _pct(low, scenario['gdp']),
            'debt_to_gdp_mid_pct': _pct(mid, scenario['gdp']),
            'debt_to_gdp_high_pct': _pct(high, scenario['gdp']),
            'reported_broad_total': None,
            'reported_debt_to_gdp_pct': None,
            'rounding_gap': None,
            'legal_data_status': 'official',
            'hidden_data_status': 'scenario',
            'data_status': 'scenario',
            'source_url': scenario['swap_source_url'],
            'source_title': '2025年预算执行报告、2024年隐性债务政策发布会与国家统计局GDP',
            'source_urls': [scenario['swap_source_url'], scenario['policy_source_url'],
                            scenario['gdp_source_url']],
            'formula': ('legal_debt_total + residual_hidden_debt; '
                        'residual_hidden_debt in [10.5-2.0-0.8, 10.5-2.0] trillion yuan'),
            'assumption': hidden_range['assumption'],
        })

    latest = records[-1] if records else None
    return {
        'status': 'mixed_official_scenario' if latest and latest['data_status'] == 'scenario'
                  else 'official_only',
        'records': records,
        'latest': latest,
        'official_latest': next((row for row in reversed(records)
                                 if row['hidden_data_status'] == 'official'), None),
        'method': {
            'legal_debt': '国债年末余额 + 地方政府法定债务年末余额',
            'broad_debt': '法定政府债务 + 财政部披露的地方政府隐性债务',
            '2025_range': ('低位 = 2024隐性债务10.5万亿 - 2025置换债2万亿 - '
                           '年度化债资源0.8万亿；高位 = 10.5 - 2.0。'),
        },
        'caveats': [
            '2023、2024隐性债务为财政部官方披露；与精确法定债务相加后的尾差来自官方万亿元口径四舍五入。',
            '2025隐性债务余额尚无官方公布值，7.7万亿—8.5万亿仅为政策资金桥接情景，无概率含义。',
            '2025区间假设没有新增隐性债务；若该假设不成立，隐性债务残余和广义总量都应相应上移。',
            '城投债券不等于隐性债务：有些城投债是企业经营性债务，有些隐性债务也不是债券。',
            '置换是债务口径转换；计算广义总量时，已转为法定债务的部分必须从隐性债务残余中扣除，避免重复。',
        ],
    }


def annual_yearend(conn, table, indicator_code):
    """月度 YTD 序列取每年 12 月值作为年度值。"""
    rows = conn.execute(
        f'SELECT period,value FROM {table} WHERE indicator_code=? ORDER BY period',
        (indicator_code,)).fetchall()
    return {period[:4]: value for period, value in rows if period.endswith('-12')}


def _growth_sample(years, value_key, window, status_key=None):
    """按“自然年跨度”而非“点数”选 CAGR 样本，并返回可审计元数据。"""
    usable = [row for row in years
              if row.get(value_key) is not None
              and (not status_key or row.get(status_key) != 'superseded')]
    if len(usable) < 2:
        return None
    usable.sort(key=lambda row: int(row['period']))
    latest_year = int(usable[-1]['period'])
    selected = [row for row in usable
                if int(row['period']) >= latest_year - int(window)]
    if len(selected) < 2:
        selected = usable[-2:]
    span = int(selected[-1]['period']) - int(selected[0]['period'])
    growth = _cagr(selected[0][value_key], selected[-1][value_key], span)
    if growth is None:
        return None
    return {
        'growth': growth,
        'sample_start': selected[0]['period'],
        'sample_end': selected[-1]['period'],
        'n_obs': len(selected),
        'span_years': span,
        'anchor_value': selected[-1][value_key],
    }


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
        status_key = f'{prefix}_limit_status'
        limit_sample = _growth_sample(years, limit_key, window, status_key)
        balance_sample = _growth_sample(years, balance_key, window)
        if not limit_sample or not balance_sample:
            out[prefix] = {'status': 'insufficient_history'}
            continue
        limit_growth = limit_sample['growth']
        balance_growth = balance_sample['growth']
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

        limit_by_year = {int(row['period']): row[limit_key] for row in years
                         if row.get(limit_key) is not None
                         and row.get(status_key) != 'superseded'}
        balance_by_year = {int(row['period']): row[balance_key] for row in years
                           if row.get(balance_key) is not None}
        latest_limit_year = max(limit_by_year)
        latest_balance_year = max(balance_by_year)
        base_year = max(latest_limit_year, latest_balance_year)

        def value_at(year, known, anchor_year, anchor_value, growth):
            if year in known:
                return known[year], 'official'
            return anchor_value * (1 + growth) ** (year - anchor_year), 'scenario'

        path, hit_year = [], None
        for step in range(0, horizon + 1):
            year = base_year + step
            projected_limit, limit_status = value_at(
                year, limit_by_year, latest_limit_year,
                limit_by_year[latest_limit_year], limit_growth)
            projected_balance, balance_status = value_at(
                year, balance_by_year, latest_balance_year,
                balance_by_year[latest_balance_year], balance_growth)
            headroom = projected_limit - projected_balance
            path.append({'period': str(year),
                         'limit': round(projected_limit, 2),
                         'balance': round(projected_balance, 2),
                         'headroom': round(headroom, 2),
                         'utilisation': round(projected_balance / projected_limit * 100, 3),
                         'limit_data_status': limit_status,
                         'balance_data_status': balance_status})
            if hit_year is None and headroom <= 0:
                hit_year = year
        base = path[0]
        out[prefix] = {
            'status': 'projected', 'base_year': str(base_year),
            'base_limit': base['limit'], 'base_balance': base['balance'],
            'base_utilisation': base['utilisation'],
            'base_limit_data_status': base['limit_data_status'],
            'base_balance_data_status': base['balance_data_status'],
            'limit_growth': round(limit_growth, 6), 'balance_growth': round(balance_growth, 6),
            'derived_limit_growth': round(derived['limit_growth'], 6),
            'derived_balance_growth': round(derived['balance_growth'], 6),
            'overridden': custom,
            'window_years': max(limit_sample['span_years'], balance_sample['span_years']),
            'limit_sample': {k: limit_sample[k] for k in
                             ('sample_start', 'sample_end', 'n_obs', 'span_years')},
            'balance_sample': {k: balance_sample[k] for k in
                               ('sample_start', 'sample_end', 'n_obs', 'span_years')},
            'latest_official_limit_year': str(latest_limit_year),
            'latest_actual_balance_year': str(latest_balance_year),
            'hit_year': str(hit_year) if hit_year else None,
            'path': path,
            'note': ('优先锚定最新已批准限额；若该年余额尚未公布，则余额为条件外推。'
                     '触及仅表示在所填增速下需要再次提额，不等于实际超限、违约或无力偿付。'),
        }
    return out


def current_local_limit_monitor(conn, ceiling_years):
    """用最新月度地方债务余额对照同年人大批准限额；缺月不插值。"""
    limits = [row for row in ceiling_years if row.get('local_limit') is not None
              and row.get('local_limit_status') != 'superseded']
    if not limits:
        return {'status': 'missing'}
    limit_row = max(limits, key=lambda row: int(row['period']))
    limit_year, limit_value = limit_row['period'], limit_row['local_limit']
    try:
        rows = conn.execute(
            '''SELECT period,value,source_url FROM fiscal_debt_observations
               WHERE indicator_code='local_debt_balance_total' AND period LIKE ?
               ORDER BY period''', (f'{limit_year}-%',)).fetchall()
    except sqlite3.OperationalError:
        return {'status': 'missing'}
    by_period = {}
    for period, value, source_url in rows:
        by_period[period] = {'value': value, 'source_url': source_url}
    series = []
    for period in sorted(by_period):
        balance = by_period[period]['value']
        series.append({
            'period': period, 'balance': balance, 'limit': limit_value,
            'headroom': round(limit_value - balance, 2),
            'utilisation': round(balance / limit_value * 100, 3),
            'source_url': by_period[period]['source_url'],
        })
    if not series:
        return {'status': 'missing', 'limit_year': limit_year, 'limit': limit_value}
    latest = series[-1]
    return {
        'status': 'official_monitor', 'data_status': 'derived',
        'balance_data_status': 'official', 'limit_data_status': 'official',
        'headroom_data_status': 'derived',
        'limit_year': limit_year, 'limit': limit_value,
        'latest_period': latest['period'], 'latest_balance': latest['balance'],
        'latest_headroom': latest['headroom'],
        'latest_utilisation': latest['utilisation'],
        'sample_start': series[0]['period'], 'sample_end': latest['period'],
        'n_obs': len(series),
        'source_url': latest['source_url'],
        'limit_source_url': limit_row.get('local_limit_source_url'),
        'series': series,
        'method': '同年全国人大批准地方债务限额－财政部最新月度地方政府债务余额；缺月不插值。',
    }


def build_sensitivity(years, revenue, interest, limit_window, interest_window,
                      horizon, overrides=None):
    """围绕当前有效假设做一致性 ±2pp 压力测试，不赋予概率含义。"""
    overrides = overrides or {}
    base_limits = project_limit_constraint(years, limit_window, horizon, overrides)
    base_interest = project_interest_burden(
        revenue, interest, interest_window, horizon, THRESHOLDS, overrides)
    if (base_interest.get('status') != 'projected'
            or any(base_limits.get(k, {}).get('status') != 'projected'
                   for k in ('treasury', 'local'))):
        return {'status': 'insufficient_history', 'rows': []}
    rows = []
    for delta in SENSITIVITY_DELTAS:
        tuned = dict(overrides)
        for prefix in ('treasury', 'local'):
            tuned[f'{prefix}_balance_growth'] = base_limits[prefix]['balance_growth'] + delta
        tuned['interest_growth'] = base_interest['interest_growth'] + delta
        limit_result = project_limit_constraint(years, limit_window, horizon, tuned)
        interest_result = project_interest_burden(
            revenue, interest, interest_window, horizon, THRESHOLDS, tuned)
        rows.append({
            'scenario': '缓释' if delta < 0 else '压力' if delta > 0 else '基准',
            'growth_delta_pp': round(delta * 100, 2),
            'treasury_hit_year': limit_result['treasury'].get('hit_year'),
            'local_hit_year': limit_result['local'].get('hit_year'),
            'interest_10_hit_year': interest_result.get('threshold_years', {}).get('10%'),
        })
    return {
        'status': 'scenario', 'rows': rows,
        'method': ('只把国债/地方债余额增速和付息增速同时下调、维持或上调 2 个百分点；'
                   '限额增速与一般预算收入增速保持当前有效假设。'),
        'caveat': ('这是方向一致的压力测试，不是单因素识别、概率区间或最好/最坏预测；'
                   '三项增速同时变化只用于观察结论稳健性。'),
    }


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
                             horizon=DEFAULT_HORIZON, overrides=None,
                             lgfv_options=None, lgfv_db_path=None):
    overrides = overrides or {}
    ceiling = build_ceiling_payload(db_path)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        revenue = annual_yearend(conn, 'fiscal_budget_observations',
                                 'general_budget_revenue_ytd')
        interest = annual_yearend(conn, 'fiscal_budget_observations',
                                  'budget_interest_expenditure_ytd')
        current_monitor = current_local_limit_monitor(conn, ceiling['years'])
        lgfv_audit = audit_lgfv_records(conn)
    finally:
        conn.close()
    limit_constraint = project_limit_constraint(
        ceiling['years'], limit_window, horizon, overrides)
    interest_burden = project_interest_burden(
        revenue, interest, interest_window, horizon, THRESHOLDS, overrides)
    broad_debt = build_broad_government_debt(ceiling['years'])
    private_db = lgfv_db_path or os.path.join(
        os.path.dirname(os.path.abspath(db_path)), 'data', 'lgfv_bond.db')
    lgfv_market_scenario = build_lgfv_bond_scenario_payload(
        private_db, **(lgfv_options or {}))
    return {
        'generated_at': datetime.now().isoformat(),
        'data_status': 'scenario',
        'ceiling': ceiling,
        'limit_constraint': limit_constraint,
        'interest_burden': interest_burden,
        'broad_government_debt': broad_debt,
        'lgfv_data_audit': lgfv_audit,
        'lgfv_market_scenario': lgfv_market_scenario,
        'current_local_monitor': current_monitor,
        'sensitivity': build_sensitivity(
            ceiling['years'], revenue, interest, limit_window,
            interest_window, horizon, overrides),
        'algorithm': {
            'cagr': 'g = (X_end / X_start) ^ (1 / calendar_year_span) - 1',
            'limit_path': 'limit_y = limit_anchor × (1 + limit_growth) ^ h',
            'balance_path': 'balance_y = balance_anchor × (1 + balance_growth) ^ h',
            'limit_trigger': 'first year where balance_y >= limit_y',
            'interest_path': 'interest_y / revenue_y; both numerator and denominator use their own CAGR',
            'broad_debt': 'treasury_balance + local_legal_balance + residual_hidden_debt',
            'lgfv_market_proxy': ('opening - maturity + refinancing + new_money; '
                                  'cash principal = maturity × (1-refinancing rate); '
                                  'interest = average balance × funding rate'),
        },
        'assumptions': {
            'limit_window_years': limit_window,
            'interest_window_years': interest_window,
            'horizon_years': horizon,
            'overrides': {k: round(v, 6) for k, v in overrides.items()},
            'method': ('限额与余额分别按各自最新可得年度样本的首末值复合增速外推；'
                       '优先使用已公布的下一年度官方限额作为锚点。'
                       '不含政策冲击、利率变动与经济周期。'),
        },
        'caveats': [
            '历史限额、年末余额和月度余额为 official；减法、比率为 derived；'
            '未来路径与触线年份为 scenario，不是预测或官方结论。',
            '限额是政策变量：人大可随时提高（2024 年 11 月即一次性增加 6 万亿地方专项限额），'
            '因此"剩余空间归零"只表示必须再次提额，不表示违约或无力偿付。',
            '2026 年限额为 official；在年末余额尚未公布前，限额约束路径中的 2026 年余额为'
            'scenario 条件外推。页面另列财政部最新月度实际余额，不把二者混为一谈。',
            '付息占比的 10%/15%/20% 为本模块设定的观察线，非官方红线。',
            '限额约束与付息路径仍不纳入城投债；新增全口径卡只使用财政部披露的隐性债务，'
            '且明确不把隐性债务冒充城投债券余额。',
            '私有市场候选债推演是关键词代理样本，仅用于独立的现金流敏感性分析；'
            '不并入法定债务、财政部隐性债务或广义政府债务合计。',
        ],
    }
