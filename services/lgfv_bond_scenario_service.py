# -*- coding: utf-8 -*-
"""Private market-proxy cash-flow scenarios for LGFV-related issuers.

The ChinaMoney universe has no official LGFV flag.  This module therefore
keeps three transparent scopes: a strict keyword proxy, a broader keyword
proxy, and the entire candidate-bond universe.  None is labelled an official
LGFV balance, and incomplete detail coverage is never scaled up mechanically.
"""

import os
import re
import sqlite3
from collections import defaultdict
from datetime import date, datetime


SOURCE_URL = 'https://www.chinamoney.com.cn/chinese/scsjzqxx/'

STRICT_KEYWORDS = (
    '城投', '城市投资集团', '城市建设投资', '城市建设开发', '城市开发建设',
    '城市发展投资', '城市发展集团', '城市基础设施', '城建投资', '城建集团',
    '新区建设投资', '开发区建设投资',
)
BROAD_KEYWORDS = STRICT_KEYWORDS + (
    '城市建设', '城市发展', '城市开发', '基础设施投资', '新区开发',
    '新区投资', '开发区开发', '开发区投资', '交通投资', '国有资产投资',
    '国有资产经营', '产业投资', '城市运营',
)

SCOPE_LABELS = {
    'strict': '严格关键词代理',
    'broad': '宽口径关键词代理',
    'all': '全部候选债券',
}

DEFAULT_HORIZON = 10
DEFAULT_REFINANCING_RATE = 0.90
DEFAULT_NEW_MONEY_RATE = 0.03
DEFAULT_FUNDING_RATE = 0.03
DEFAULT_TERM_YEARS = 3
# User-selected market benchmark, in 100 million yuan (亿元).  This is a
# scenario input, not an official observation and not a mechanically inferred
# LGFV balance.
DEFAULT_MARKET_BALANCE_ANCHOR = 150000.0


def _clean(value):
    if value is None:
        return ''
    return re.sub(r'\s+', '', str(value))


def classify_lgfv_proxy(issuer=None, bond_full_name=None, bond_name=None):
    """Return the strongest transparent keyword-proxy classification."""
    text = ''.join(_clean(value) for value in (issuer, bond_full_name, bond_name))
    for keyword in STRICT_KEYWORDS:
        if keyword in text:
            return {'classification': 'strict', 'matched_keyword': keyword}
    for keyword in BROAD_KEYWORDS[len(STRICT_KEYWORDS):]:
        if keyword in text:
            return {'classification': 'broad', 'matched_keyword': keyword}
    return {'classification': 'unmatched', 'matched_keyword': None}


def _in_scope(classification, scope):
    if scope == 'all':
        return True
    if scope == 'broad':
        return classification in {'strict', 'broad'}
    return classification == 'strict'


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def project_lgfv_cashflows(opening_balance, contracted_maturities,
                           start_year, horizon=DEFAULT_HORIZON,
                           refinancing_rate=DEFAULT_REFINANCING_RATE,
                           new_money_rate=DEFAULT_NEW_MONEY_RATE,
                           funding_rate=DEFAULT_FUNDING_RATE,
                           term_years=DEFAULT_TERM_YEARS,
                           first_period_fraction=1.0):
    """Project annual stock and cash needs with explicit financing rules.

    ``new_money_rate`` is gross new-money issuance as a share of opening stock,
    not a target balance growth rate.  Refinancing and new-money issuance are
    assigned the assumed term and re-enter the maturity wall when they mature.
    """
    opening = max(0.0, float(opening_balance or 0.0))
    horizon = int(_clamp(horizon, 1, 30))
    refinancing_rate = _clamp(refinancing_rate, 0.0, 1.0)
    new_money_rate = _clamp(new_money_rate, 0.0, 0.50)
    funding_rate = _clamp(funding_rate, 0.0, 0.30)
    term_years = int(_clamp(term_years, 1, 15))
    first_period_fraction = _clamp(first_period_fraction, 0.0, 1.0)
    projected_maturities = defaultdict(float)
    rows = []
    end_year = int(start_year) + horizon - 1

    for year in range(int(start_year), end_year + 1):
        period_fraction = first_period_fraction if year == int(start_year) else 1.0
        contracted = min(opening, max(0.0, float(contracted_maturities.get(year, 0.0))))
        remaining_stock = max(0.0, opening - contracted)
        projected = min(
            remaining_stock,
            max(0.0, float(projected_maturities.get(year, 0.0))),
        )
        maturity = contracted + projected
        refinancing = maturity * refinancing_rate
        new_money = opening * new_money_rate * period_fraction
        issuance = refinancing + new_money
        closing = max(0.0, opening - maturity + issuance)
        average_balance = (opening + closing) / 2.0
        interest = average_balance * funding_rate * period_fraction
        cash_principal = maturity - refinancing
        cash_need = cash_principal + interest
        maturity_year = year + term_years
        if issuance and maturity_year <= end_year:
            projected_maturities[maturity_year] += issuance
        rows.append({
            'period': str(year),
            'period_fraction': round(period_fraction, 6),
            'opening_balance': round(opening, 4),
            'contracted_maturity': round(contracted, 4),
            'projected_maturity': round(projected, 4),
            'total_maturity': round(maturity, 4),
            'refinancing_issuance': round(refinancing, 4),
            'new_money_issuance': round(new_money, 4),
            'total_issuance': round(issuance, 4),
            'cash_principal': round(cash_principal, 4),
            'estimated_interest': round(interest, 4),
            'cash_debt_service': round(cash_need, 4),
            'closing_balance': round(closing, 4),
            'data_status': 'scenario',
        })
        opening = closing
    return rows


def build_scenario_set(opening_balance, contracted_maturities, start_year,
                       horizon=DEFAULT_HORIZON,
                       refinancing_rate=DEFAULT_REFINANCING_RATE,
                       new_money_rate=DEFAULT_NEW_MONEY_RATE,
                       funding_rate=DEFAULT_FUNDING_RATE,
                       term_years=DEFAULT_TERM_YEARS,
                       first_period_fraction=1.0):
    """Build non-probabilistic easing/base/stress financing paths."""
    definitions = (
        ('easing', '融资宽松', min(1.0, refinancing_rate + 0.10),
         min(0.50, new_money_rate + 0.02), max(0.0, funding_rate - 0.005)),
        ('base', '基准', refinancing_rate, new_money_rate, funding_rate),
        ('stress', '融资压力', max(0.0, refinancing_rate - 0.20),
         max(0.0, new_money_rate - 0.03), min(0.30, funding_rate + 0.01)),
    )
    scenarios = []
    for code, label, refinance, new_money, rate in definitions:
        path = project_lgfv_cashflows(
            opening_balance, contracted_maturities, start_year, horizon,
            refinance, new_money, rate, term_years, first_period_fraction,
        )
        peak = max(path, key=lambda row: row['cash_debt_service']) if path else None
        scenarios.append({
            'scenario_code': code,
            'scenario': label,
            'data_status': 'scenario',
            'refinancing_rate': round(refinance, 6),
            'new_money_rate': round(new_money, 6),
            'funding_rate': round(rate, 6),
            'term_years': int(term_years),
            'ending_balance': path[-1]['closing_balance'] if path else None,
            'cumulative_cash_debt_service': round(
                sum(row['cash_debt_service'] for row in path), 4),
            'peak_cash_debt_service': peak['cash_debt_service'] if peak else None,
            'peak_cash_year': peak['period'] if peak else None,
            'path': path,
        })
    return scenarios


def _missing_payload(reason, db_exists=False):
    return {
        'status': 'missing',
        'data_status': 'missing',
        'db_exists': bool(db_exists),
        'reason': reason,
        'source_url': SOURCE_URL,
        'scenarios': [],
        'contracted_cashflows': [],
    }


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _is_active_term(row, as_of_date):
    """Return whether a successfully parsed bond term is active at ``as_of``."""
    maturity = _parse_date(row['maturity_date'])
    issue_date = _parse_date(row['issue_date'])
    amount = row['actual_issue_amount']
    return bool(
        maturity and maturity > as_of_date
        and (issue_date is None or issue_date <= as_of_date)
        and amount is not None and amount > 0
    )


def _field_coverage(rows, field):
    denominator = len(rows)
    count = sum(row[field] not in (None, '') for row in rows)
    return {
        'field': field,
        'n': count,
        'denominator': denominator,
        'pct': round(count / denominator * 100.0, 2) if denominator else None,
    }


def build_lgfv_bond_scenario_payload(
        db_path, scope='strict', horizon=DEFAULT_HORIZON,
        refinancing_rate=DEFAULT_REFINANCING_RATE,
        new_money_rate=DEFAULT_NEW_MONEY_RATE, funding_rate=None,
        term_years=DEFAULT_TERM_YEARS, as_of=None, balance_anchor=None):
    """Build a source-backed private market-proxy scenario payload."""
    if scope not in SCOPE_LABELS:
        scope = 'strict'
    if not db_path or not os.path.exists(db_path):
        return _missing_payload('本地候选债券私有库不存在。')
    horizon = int(_clamp(horizon, 5, 20))
    refinancing_rate = _clamp(refinancing_rate, 0.0, 1.0)
    new_money_rate = _clamp(new_money_rate, 0.0, 0.30)
    term_years = int(_clamp(term_years, 1, 10))
    try:
        balance_anchor = (None if balance_anchor in (None, '')
                          else float(balance_anchor))
    except (TypeError, ValueError):
        balance_anchor = None
    if balance_anchor is not None and balance_anchor <= 0:
        balance_anchor = None

    try:
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'lgfv_bond_inventory', 'lgfv_bond_terms'}
        if not required.issubset(tables):
            conn.close()
            return _missing_payload('私有库尚未建立清单与条款表。', True)
        snapshot_row = conn.execute(
            'SELECT MAX(snapshot_date) FROM lgfv_bond_inventory').fetchone()
        snapshot = snapshot_row[0] if snapshot_row else None
        if not snapshot:
            conn.close()
            return _missing_payload('候选债券清单为空。', True)
        as_of_date = _parse_date(as_of) or _parse_date(snapshot) or date.today()

        inventory = conn.execute('''
            SELECT bond_defined_code,issuer,bond_name
            FROM lgfv_bond_inventory WHERE snapshot_date=?
        ''', (snapshot,)).fetchall()
        terms = conn.execute('''
            SELECT bond_defined_code,bond_name,bond_full_name,issuer,bond_type_code,
                   bond_type,actual_issue_amount,planned_issue_amount,issue_date,
                   maturity_date,coupon_rate,coupon_frequency
            FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
        ''', (snapshot,)).fetchall()

        inventory_scope_codes = set()
        inventory_class_counts = defaultdict(int)
        for row in inventory:
            classified = classify_lgfv_proxy(row['issuer'], None, row['bond_name'])
            inventory_class_counts[classified['classification']] += 1
            if _in_scope(classified['classification'], scope):
                inventory_scope_codes.add(row['bond_defined_code'])

        selected = []
        strict_count = broad_extra_count = 0
        for row in terms:
            classified = classify_lgfv_proxy(
                row['issuer'], row['bond_full_name'], row['bond_name'])
            if classified['classification'] == 'strict':
                strict_count += 1
            elif classified['classification'] == 'broad':
                broad_extra_count += 1
            if _in_scope(classified['classification'], scope):
                selected.append(row)

        selected_codes = {row['bond_defined_code'] for row in selected}
        scope_universe_count = len(inventory_scope_codes | selected_codes)
        active = [row for row in selected if _is_active_term(row, as_of_date)]
        all_active = [row for row in terms if _is_active_term(row, as_of_date)]

        sample_opening_balance = sum(
            float(row['actual_issue_amount']) for row in active)
        candidate_opening_balance = sum(
            float(row['actual_issue_amount']) for row in all_active)
        use_anchor = balance_anchor is not None and candidate_opening_balance > 0
        opening_balance = balance_anchor if use_anchor else sample_opening_balance
        schedule_rows = all_active if use_anchor else active
        schedule_codes = {row['bond_defined_code'] for row in schedule_rows}
        schedule_scale_factor = (
            opening_balance / candidate_opening_balance
            if use_anchor else 1.0
        )
        coupon_rows = [row for row in schedule_rows
                       if row['coupon_rate'] is not None and row['coupon_rate'] >= 0]
        coupon_amount = sum(float(row['actual_issue_amount']) for row in coupon_rows)
        weighted_coupon_pct = (
            sum(float(row['actual_issue_amount']) * float(row['coupon_rate'])
                for row in coupon_rows) / coupon_amount
            if coupon_amount else None
        )
        effective_funding_rate = (
            _clamp(funding_rate, 0.0, 0.30)
            if funding_rate is not None
            else (weighted_coupon_pct / 100.0
                  if weighted_coupon_pct is not None else DEFAULT_FUNDING_RATE)
        )

        start_year = as_of_date.year
        end_year = start_year + horizon - 1
        maturity_by_year = defaultdict(float)
        for row in schedule_rows:
            maturity = _parse_date(row['maturity_date'])
            if maturity and start_year <= maturity.year <= end_year:
                maturity_by_year[maturity.year] += (
                    float(row['actual_issue_amount']) * schedule_scale_factor)

        year_start = date(as_of_date.year, 1, 1)
        next_year_start = date(as_of_date.year + 1, 1, 1)
        first_period_fraction = (
            (next_year_start - as_of_date).days /
            (next_year_start - year_start).days
        )

        known_interest_by_year = defaultdict(float)
        if 'lgfv_bond_cashflows' in tables and schedule_codes:
            interest_rows = conn.execute('''
                SELECT bond_defined_code,event_date,amount
                FROM lgfv_bond_cashflows
                WHERE snapshot_date=? AND event_type='scheduled_interest'
                  AND data_status='derived_schedule' AND event_date>?
                  AND event_date<=? AND amount IS NOT NULL
            ''', (snapshot, as_of_date.isoformat(), f'{end_year}-12-31')).fetchall()
            for row in interest_rows:
                if row['bond_defined_code'] in schedule_codes:
                    year = int(row['event_date'][:4])
                    known_interest_by_year[year] += (
                        float(row['amount']) * schedule_scale_factor)
        conn.close()
    except sqlite3.Error as exc:
        return _missing_payload(f'读取私有库失败：{type(exc).__name__}: {exc}', True)

    contracted = []
    for year in range(as_of_date.year, end_year + 1):
        principal = round(maturity_by_year.get(year, 0.0), 4)
        interest = round(known_interest_by_year.get(year, 0.0), 4)
        contracted.append({
            'period': str(year),
            'maturing_principal': principal,
            'known_coupon_interest': interest,
            'known_cash_total': round(principal + interest, 4),
            'principal_data_status': (
                'manual_anchor_scaled_candidate_schedule'
                if use_anchor else 'market_estimate_upper_bound'
            ),
            'interest_data_status': (
                'manual_anchor_scaled_derived_schedule'
                if use_anchor else 'derived_schedule'
            ),
        })

    scenarios = build_scenario_set(
        opening_balance, maturity_by_year, start_year, horizon,
        refinancing_rate, new_money_rate, effective_funding_rate, term_years,
        first_period_fraction,
    ) if opening_balance else []
    base = next((item for item in scenarios
                 if item['scenario_code'] == 'base'), None)
    next_three_end = as_of_date.year + 2
    next_three_maturity = sum(
        row['maturing_principal'] for row in contracted
        if as_of_date.year <= int(row['period']) <= next_three_end)
    inventory_count = len(inventory)
    term_count = len(terms)
    scope_detail_coverage = (
        len(selected) / scope_universe_count * 100.0
        if scope_universe_count else None
    )
    field_coverage = [
        _field_coverage(selected, field)
        for field in ('actual_issue_amount', 'issue_date', 'maturity_date', 'coupon_rate',
                      'coupon_frequency')
    ]
    active_coupon_coverage = (
        len(coupon_rows) / len(schedule_rows) * 100.0 if schedule_rows else None)
    data_status = 'scenario' if scenarios else 'insufficient_sample'
    coverage_status = (
        'complete' if inventory_count and term_count >= inventory_count
        else 'partial_backfill'
    )
    if use_anchor:
        opening_balance_method = (
            '用户指定的15万亿元市场基准（单位：亿元），不把关键词样本额当作全国余额。'
        )
        schedule_method = (
            '全候选债池的未到期条款结构 × 手动基准 / 全候选债池未到期发行额；'
            '仅为现金流图表提供内部一致的结构，不代表城投主体分类结果。'
        )
        anchor_caveats = [
            '15万亿元是用户指定的手动市场基准，data_status 为 scenario/manual_assumption，'
            '不是财政部官方观测，也不是本地关键词识别结果。',
            f'到期与条款推导付息按全候选债池结构缩放，缩放系数为'
            f'{schedule_scale_factor:.6f}；该缩放不等于城投主体覆盖率估计。',
        ]
    else:
        opening_balance_method = (
            '截至快照日尚未到期且有实际发行额的代理样本发行额之和；'
            '未扣除提前兑付/分期还本，因此是上限估计。'
        )
        schedule_method = '代理样本的未到期条款结构。'
        anchor_caveats = []
    return {
        'status': data_status,
        'data_status': data_status,
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'snapshot_date': snapshot,
        'as_of': as_of_date.isoformat(),
        'source_name': '中国货币网公开债券查询（私有本地快照）',
        'source_url': SOURCE_URL,
        'scope': scope,
        'scope_label': SCOPE_LABELS[scope],
        'scope_status': 'keyword_proxy_not_official_classification',
        'classification_rules': {
            'strict_keywords': list(STRICT_KEYWORDS),
            'broad_extra_keywords': list(BROAD_KEYWORDS[len(STRICT_KEYWORDS):]),
            'unmatched_policy': '仅在 all 诊断口径中纳入',
        },
        'coverage_status': coverage_status,
        'inventory_count': inventory_count,
        'terms_success_count': term_count,
        'overall_detail_coverage_pct': round(
            term_count / inventory_count * 100.0, 2) if inventory_count else None,
        'scope_inventory_count': scope_universe_count,
        'scope_terms_count': len(selected),
        'scope_detail_coverage_pct': round(scope_detail_coverage, 2)
        if scope_detail_coverage is not None else None,
        'strict_terms_count': strict_count,
        'broad_extra_terms_count': broad_extra_count,
        'inventory_class_counts': dict(inventory_class_counts),
        'active_bond_count': len(active),
        'active_missing_issue_date_count': sum(
            _parse_date(row['issue_date']) is None for row in active),
        'active_issuer_count': len({_clean(row['issuer']) for row in active
                                    if _clean(row['issuer'])}),
        'active_issue_amount_upper_bound': round(sample_opening_balance, 4),
        'scenario_opening_balance': round(opening_balance, 4),
        'manual_balance_anchor': round(balance_anchor, 4)
        if use_anchor else None,
        'manual_balance_anchor_enabled': use_anchor,
        'scenario_opening_data_status': (
            'manual_assumption' if use_anchor else data_status
        ),
        'candidate_active_bond_count': len(all_active),
        'candidate_active_issue_amount_upper_bound': round(
            candidate_opening_balance, 4),
        'scenario_active_bond_count': len(schedule_rows),
        'scenario_active_issuer_count': len({_clean(row['issuer'])
                                             for row in schedule_rows
                                             if _clean(row['issuer'])}),
        'schedule_scale_factor': round(schedule_scale_factor, 8),
        'weighted_coupon_rate_pct': round(weighted_coupon_pct, 4)
        if weighted_coupon_pct is not None else None,
        'active_coupon_coverage_pct': round(active_coupon_coverage, 2)
        if active_coupon_coverage is not None else None,
        'next_three_year_maturity': round(next_three_maturity, 4),
        'field_coverage': field_coverage,
        'contracted_cashflows': contracted,
        'scenarios': scenarios,
        'base_scenario': base,
        'assumptions': {
            'horizon_years': horizon,
            'start_year': str(start_year),
            'opening_balance_100m_yuan': round(opening_balance, 4),
            'opening_balance_source': (
                'user_manual_market_anchor' if use_anchor
                else 'selected_keyword_proxy_sample'
            ),
            'manual_balance_anchor_100m_yuan': round(balance_anchor, 4)
            if use_anchor else None,
            'schedule_scale_factor': round(schedule_scale_factor, 8),
            'first_period_fraction': round(first_period_fraction, 6),
            'base_refinancing_rate': round(refinancing_rate, 6),
            'base_new_money_rate': round(new_money_rate, 6),
            'base_funding_rate': round(effective_funding_rate, 6),
            'funding_rate_source': (
                'user_override' if funding_rate is not None
                else 'active_amount_weighted_coupon_rate'),
            'term_years': term_years,
            'scenario_offsets': {
                'easing': 'refinancing +10pp, new money +2pp, rate -0.5pp',
                'stress': 'refinancing -20pp, new money -3pp, rate +1pp',
            },
        },
        'method': {
            'opening_balance': opening_balance_method,
            'maturity_schedule': schedule_method,
            'closing_balance': ('opening - maturity + refinancing_issuance '
                                '+ new_money_issuance'),
            'cash_principal': 'maturity × (1 - refinancing_rate)',
            'estimated_interest': ('average(opening_balance, closing_balance) '
                                   '× funding_rate'),
            'projected_maturity': ('refinancing and new-money issuance mature '
                                   'after assumed term_years'),
            'first_period': ('current-year new-money issuance and estimated '
                             'interest are prorated from as_of to year-end; '
                             'known maturities are not prorated'),
        },
        'caveats': anchor_caveats + [
            '关键词代理不是财政部或市场机构的官方城投债认定；严格/宽口径差异本身就是识别不确定性。',
            '仅覆盖中国货币网当前候选银行间债券类型，未补交易所市场和跨市场去重。',
            '详情回填未完成时只计算已成功条款，不按缺失比例放大；页面必须同时显示覆盖率。',
            '存续额使用未到期实际发行额之和，未完整扣除回售、提前兑付和分期还本，属于上限估计。',
            '已披露发行日在快照日之后的债券不计入存续额；发行日缺失但其余条款可用的债券保留在上限样本。',
            '合同付息为条款推导日程；情景利息按平均余额乘融资利率估算，均不是实际已付金额。',
            '首年是截至快照日后的剩余年度：新增融资与估算利息按剩余天数折算，已知到期本金按实际到期日汇总。',
            '融资宽松、基准、融资压力没有概率含义，不代表最好/最可能/最坏预测。',
            '本市场代理样本不进入官方法定债务、人大限额或财政部隐性债务合计，避免重复相加。',
        ],
    }
