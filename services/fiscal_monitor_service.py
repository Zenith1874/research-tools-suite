import json
import sqlite3
from datetime import datetime

from services.fiscal_debt_service import (
    MOF_CENTRAL_DEBT_PDF,
    MOF_LOCAL_DEBT_INDEX,
    build_fiscal_debt_debug_payload,
    build_fiscal_debt_payload,
    ensure_fiscal_tables,
    update_central_government_debt,
    update_fiscal_debt,
)
from services.mof_treasury_bond_service import (
    build_mof_treasury_bond_debug,
    build_mof_treasury_bond_payload,
    update_mof_treasury_bonds,
)
from services.pboc_balance_sheet_service import (
    PBOC_YEAR_INDEX,
    build_pboc_balance_sheet_debug,
    build_pboc_balance_sheet_payload,
    update_pboc_balance_sheet,
)
from services.pboc_buyout_reverse_repo_service import (
    ENTRY_URL as BUYOUT_REPO_ENTRY,
    build_pboc_buyout_reverse_repo_debug,
    build_pboc_buyout_reverse_repo_payload,
    update_pboc_buyout_reverse_repo,
)
from services.pboc_gov_bond_omo_service import (
    PBOC_OMO_COLUMN,
    build_pboc_gov_bond_omo_debug,
    build_pboc_gov_bond_omo_payload,
    update_pboc_gov_bond_omo,
)
from services.fiscal_budget_service import (
    INDEX_URL as FISCAL_BUDGET_INDEX,
    build_fiscal_budget_payload,
    update_fiscal_budget,
)


MODULE_UPDATES = {
    'local_government_debt': {
        'source_name': '财政部债务管理司', 'source_type': 'mof_local_debt',
        'source_url': MOF_LOCAL_DEBT_INDEX, 'update': update_fiscal_debt,
    },
    'central_government_debt': {
        'source_name': '财政部国库司', 'source_type': 'mof_central_government_debt_sdds',
        'source_url': MOF_CENTRAL_DEBT_PDF, 'update': update_central_government_debt,
    },
    'treasury_issuance': {
        'source_name': '财政部债务管理司', 'source_type': 'mof_treasury_bond',
        'source_url': 'https://zwgls.mof.gov.cn/ywgg/',
        'update': lambda db_path: update_mof_treasury_bonds(db_path, start_year=2024, max_pages=3),
    },
    'pboc_balance_sheet': {
        'source_name': '中国人民银行', 'source_type': 'pboc_balance_sheet',
        'source_url': PBOC_YEAR_INDEX, 'update': update_pboc_balance_sheet,
    },
    'pboc_gov_bond_omo': {
        'source_name': '中国人民银行', 'source_type': 'pboc_gov_bond_omo',
        'source_url': PBOC_OMO_COLUMN, 'update': update_pboc_gov_bond_omo,
    },
    'pboc_buyout_reverse_repo': {
        'source_name': '中国人民银行', 'source_type': 'pboc_buyout_reverse_repo',
        'source_url': BUYOUT_REPO_ENTRY, 'update': update_pboc_buyout_reverse_repo,
    },
    'fiscal_budget': {
        'source_name': '财政部国库司', 'source_type': 'mof_fiscal_budget',
        'source_url': FISCAL_BUDGET_INDEX, 'update': update_fiscal_budget,
    },
}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _card(label, value=None, unit=None, period=None, data_status='missing', source_name=None,
          source_url=None, source_title=None, parser_notes=None, formula=None, warning=None,
          source_urls=None):
    if data_status == 'official' and not source_url:
        data_status = 'missing'
        value = None
        warning = warning or 'official 数据缺少 source_url，已阻止展示。'
    if data_status == 'derived' and not formula:
        data_status = 'missing'
        value = None
        warning = warning or 'derived 数据缺少 formula，已阻止展示。'
    if data_status in ('missing', 'not_available', 'error'):
        value = None
    return {
        'label': label, 'value': value, 'unit': unit, 'period': period,
        'data_status': data_status, 'source_name': source_name,
        'source_url': source_url, 'source_urls': source_urls or ([source_url] if source_url else []),
        'source_title': source_title, 'formula': formula, 'parser_notes': parser_notes,
        'warning': warning,
    }


def _value_status(row, code, fallback='official'):
    return row.get(f'{code}__status') or fallback if row else 'missing'


def _local_card(row, code, label, unit='亿元'):
    if not row or row.get(code) is None:
        return _card(label, unit=unit, data_status='missing', warning='该指标当前月份没有可验证数值。')
    return _card(
        label, row.get(code), unit, row.get('period'), _value_status(row, code),
        row.get('source_name'), row.get('source_url'), row.get('source_title'),
        row.get('parser_notes'), row.get(f'{code}__formula'),
    )


def _section_status(cards):
    available = sum(1 for c in cards if c['data_status'] in ('official', 'derived'))
    return 'available' if available == len(cards) and cards else ('partial' if available else 'missing')


def _latest_by_period(records):
    return records[-1] if records else None


def _without_raw(records, limit=None):
    selected = records[:limit] if limit is not None else records
    return [{k: v for k, v in row.items() if k not in ('raw_text', 'raw_html', 'active_operations_json')}
            for row in selected]


def _last_update_time(conn):
    row = conn.execute('SELECT MAX(finished_at) value FROM fiscal_debt_update_logs').fetchone()
    return row['value'] if row else None


# ── 国债还本/付息(derived，仅覆盖已抓逐只国债；完整兑付源仍缺) ─────────────────
def _next_12_months():
    y, m = datetime.now().year, datetime.now().month
    out = []
    for _ in range(12):
        m += 1
        if m > 12:
            y, m = y + 1, 1
        out.append(f'{y}-{m:02d}')
    return out


def _treasury_principal_by_month(issuances):
    """按 maturity_date 逐月聚合到期还本(精确值，但仅含已抓国债)。"""
    agg = {}
    for r in issuances:
        md, amt = r.get('maturity_date'), r.get('actual_issue_amount')
        if md and amt:
            a = agg.setdefault(md[:7], {'month': md[:7], 'principal_due': 0.0, 'bonds': 0})
            a['principal_due'] += amt
            a['bonds'] += 1
    return sorted(agg.values(), key=lambda x: x['month'])


def _treasury_principal_card(issuances, entry_url):
    months = set(_next_12_months())
    total = sum(r['actual_issue_amount'] for r in issuances
                if r.get('maturity_date') and r.get('actual_issue_amount')
                and r['maturity_date'][:7] in months)
    urls = [r['source_url'] for r in issuances
            if r.get('maturity_date') and r['maturity_date'][:7] in months and r.get('source_url')]
    if not total:
        return _card('国债到期还本(未来12个月)', unit='亿元', data_status='missing',
                     warning='已抓国债中未来12个月无到期记录。')
    return _card(
        '国债到期还本(未来12个月，已抓国债)', round(total, 1), '亿元',
        f"{datetime.now().strftime('%Y-%m')} 起12个月", 'derived',
        '财政部债务管理司(逐只国债聚合)', entry_url, '逐只国债 maturity_date 聚合',
        '仅覆盖 2024 年起已抓的逐只国债；更早发行的存量国债到期未包含，实际到期还本更大。',
        'sum(actual_issue_amount where maturity_date within next 12 months)',
        source_urls=urls[:60])


def _treasury_interest_card(issuances, entry_url):
    today = datetime.now().strftime('%Y-%m-%d')
    annual, counted, missing_rate = 0.0, 0, 0
    urls = []
    for r in issuances:
        if r.get('bond_type') not in ('book_entry_interest_bearing', 'special_treasury_bond'):
            continue    # 贴现国债无票息
        md, amt = r.get('maturity_date'), r.get('actual_issue_amount')
        if not (md and md > today and amt):
            continue
        cr = r.get('coupon_rate')
        if cr:
            annual += amt * cr / 100.0
            counted += 1
            if r.get('source_url'):
                urls.append(r['source_url'])
        else:
            missing_rate += 1
    if not counted:
        return _card('国债年付息(估计)', unit='亿元/年', data_status='missing',
                     warning='已抓国债均无票面利率信息，无法估计。')
    return _card(
        '存量附息国债年付息(估计，已抓国债)', round(annual, 1), '亿元/年', today, 'derived',
        '财政部债务管理司(逐只国债聚合)', entry_url, '票面利率×发行额 汇总',
        f'覆盖 {counted} 只有票面利率的未到期附息/特别国债；另有 {missing_rate} 只未到期附息国债缺票面利率未计入；'
        '贴现国债折价发行无票息。2024 年前发行的存量国债不在内，实际全口径付息远大于此。',
        'sum(actual_issue_amount × coupon_rate / 100) for outstanding coupon-bearing bonds',
        source_urls=urls[:60])


def build_fiscal_monitor_payload(db_path):
    fiscal = build_fiscal_debt_payload(db_path)
    balance = build_pboc_balance_sheet_payload(db_path)
    omo = build_pboc_gov_bond_omo_payload(db_path)
    buyout = build_pboc_buyout_reverse_repo_payload(db_path)
    treasury_issuance = build_mof_treasury_bond_payload(db_path)
    budget = build_fiscal_budget_payload(db_path)
    local_records = fiscal['local_government_debt']['records']
    central_records = fiscal['treasury_debt']['records']
    local_latest = _latest_by_period(local_records)
    central_latest = _latest_by_period(central_records)

    overview_cards = [
        _local_card(central_latest, 'central_government_debt_balance', '中央政府债务余额'),
        _local_card(central_latest, 'central_government_bond_balance', '中央政府债券余额'),
        _local_card(local_latest, 'local_debt_balance_total', '地方政府债务余额'),
        _local_card(local_latest, 'local_general_debt_balance', '地方政府一般债务余额'),
        _local_card(local_latest, 'local_special_debt_balance', '地方政府专项债务余额'),
    ]
    central_by_period = {r['period']: r for r in central_records}
    local_by_period = {r['period']: r for r in local_records}
    common_periods = sorted(set(central_by_period) & set(local_by_period))
    if common_periods:
        period = common_periods[-1]
        central = central_by_period[period]
        local = local_by_period[period]
        cval = central.get('central_government_debt_balance')
        lval = local.get('local_debt_balance_total')
        if cval is not None and lval is not None:
            overview_cards.insert(2, _card(
                '中央 + 地方显性政府债务合计', cval + lval, '亿元', period, 'derived',
                '财政部国库司 + 财政部债务管理司', central.get('source_url'),
                '中央政府季度债务余额 + 地方政府月度债务余额',
                '仅在中央与地方数据期数一致时计算；不含城投债等广义债务。',
                'central_government_debt_balance + local_debt_balance_total',
                source_urls=[central.get('source_url'), local.get('source_url')],
            ))
    else:
        overview_cards.insert(2, _card(
            '中央 + 地方显性政府债务合计', unit='亿元', data_status='missing',
            warning='中央和地方债务没有共同期数，未进行跨期相加。'
        ))

    local_pressure_cards = [
        _local_card(local_latest, 'local_bond_issuance_current_month', '地方债当月发行'),
        _local_card(local_latest, 'local_general_bond_issuance_ytd', '一般债券年初至今发行'),
        _local_card(local_latest, 'local_special_bond_issuance_ytd', '专项债券年初至今发行'),
        _local_card(local_latest, 'local_new_bond_issuance_ytd', '新增债券年初至今发行'),
        _local_card(local_latest, 'local_refinancing_bond_issuance_ytd', '再融资债券年初至今发行'),
        _local_card(local_latest, 'official_principal_repayment_current_month', '地方债当月还本'),
        _local_card(local_latest, 'official_interest_payment_current_month', '地方债当月付息'),
        _local_card(local_latest, 'local_bond_avg_interest_rate', '地方债平均利率', '%'),
        _local_card(local_latest, 'local_bond_avg_remaining_maturity', '地方债平均剩余年限', '年'),
        _local_card(local_latest, 'local_debt_balance_total', '地方政府债务期末余额'),
    ]
    official_issuances = [r for r in treasury_issuance.get('records', []) if r.get('actual_issue_amount') is not None]
    latest_issue_period = max((r['issue_date'][:7] for r in official_issuances if r.get('issue_date')), default=None)
    latest_issue_rows = [r for r in official_issuances if r.get('issue_date', '').startswith(latest_issue_period or '---')]
    latest_issue_amount = sum(r['actual_issue_amount'] for r in latest_issue_rows) if latest_issue_rows else None
    issue_source = latest_issue_rows[0] if latest_issue_rows else None
    # —— 年初至今国债发行（官方逐笔）+ 按类型拆分；储蓄/香港单列 ——
    cur_year = str(datetime.now().year)
    ytd = treasury_issuance.get('current_year_ytd') or {}
    ytd_amount, ytd_records = ytd.get('actual_issue_amount'), ytd.get('records') or 0
    current_year_summary = treasury_issuance.get('current_year_summary') or {}
    q1_reconciliation = treasury_issuance.get('q1_reconciliation') or {}
    type_sums = {}
    for r in treasury_issuance.get('by_type', []):
        if str(r.get('year')) == cur_year and r.get('actual_issue_amount'):
            type_sums[r['bond_type']] = type_sums.get(r['bond_type'], 0) + r['actual_issue_amount']
    ytd_urls = [r['source_url'] for r in official_issuances if r.get('issue_date', '').startswith(cur_year)]
    entry = treasury_issuance.get('entry_url')
    treasury_ytd_cards = [
        _card(f'{cur_year} 年初至今国债发行（逐笔 actual）', ytd_amount, '亿元',
              current_year_summary.get('latest_result_published_date') or cur_year,
              'official' if ytd_amount else 'missing', '财政部债务管理司', entry,
              '国债业务公告逐笔实际发行额汇总',
              f'截至最新结果公告发布日期 {current_year_summary.get("latest_result_published_date") or "未知"}，汇总 {cur_year} 年 {ytd_records} 条 actual_issue_amount；不把 planned_only 当 actual。',
              f'sum(actual_issue_amount where year={cur_year} and data_status=official)',
              source_urls=ytd_urls[:60]),
        _card(f'{cur_year} 尚无结果公告的计划/额度', current_year_summary.get('planned_after_latest_result_amount'), '亿元',
              current_year_summary.get('latest_result_published_date') or cur_year,
              'derived' if current_year_summary.get('planned_after_latest_result_amount') else 'missing',
              '财政部债务管理司' if current_year_summary.get('planned_after_latest_result_amount') else None,
              entry if current_year_summary.get('planned_after_latest_result_amount') else None,
              '已发现计划公告但尚未解析到对应结果公告的金额',
              '仅提示后续待核验，不计入年初至今 actual 发行额。',
              f'sum(planned_issue_amount where year={cur_year} and data_status=planned_only and no later result announcement has the same bond_name)'),
    ]
    if q1_reconciliation:
        treasury_ytd_cards += [
            _card('财政部官方 2026Q1 国债发行汇总', q1_reconciliation.get('official_total_issue_amount'), '亿元',
                  '2026Q1', 'official', '财政部新闻办公室', q1_reconciliation.get('source_url'),
                  q1_reconciliation.get('source_title'), q1_reconciliation.get('parser_notes')),
            _card('2026Q1 官方汇总 - 逐笔 actual 差额', q1_reconciliation.get('difference_total_minus_detail'), '亿元',
                  '2026Q1', 'derived', '财政部新闻办公室 + 财政部债务管理司', q1_reconciliation.get('source_url'),
                  'Q1 官方总发行额与逐笔国债业务公告 actual 对账',
                  '该差额主要对应储蓄国债等未进入逐笔 actual 主表的口径；用于提示，不自动并入逐笔 actual YTD。',
                  'official_total_issue_amount - sum(detail actual_issue_amount for 2026-01..2026-03)'),
        ]
    for code, label in [('book_entry_interest_bearing', '其中：记账式附息国债'),
                        ('discount_bond', '其中：贴现国债'),
                        ('special_treasury_bond', '其中：特别国债')]:
        amt = type_sums.get(code)
        treasury_ytd_cards.append(_card(
            label, amt, '亿元', cur_year, 'official' if amt else 'missing',
            '财政部债务管理司' if amt else None, entry if amt else None, None,
            (f'{cur_year} 年 bond_type={code} 实际发行额合计。' if amt else None),
            (f'sum(actual_issue_amount where year={cur_year} and bond_type={code})' if amt else None),
            source_urls=ytd_urls[:60] if amt else None))
    treasury_ytd_cards.append(_card(
        '储蓄国债（年初至今）', type_sums.get('savings_bond'), '亿元', cur_year,
        'official' if type_sums.get('savings_bond') else 'missing', '财政部' if type_sums.get('savings_bond') else None,
        entry if type_sums.get('savings_bond') else None,
        warning=None if type_sums.get('savings_bond') else '储蓄国债逐笔公告抓取待接入；不并入境内记账式合计。'))
    treasury_ytd_cards.append(_card(
        '香港人民币国债（年初至今）', None, '亿元', cur_year, 'missing',
        warning='香港人民币国债单列，发行公告抓取待接入。'))
    overview_cards = treasury_ytd_cards[:2] + overview_cards
    treasury_pressure_cards = treasury_ytd_cards + [
        _card(
            '国债当月实际发行', latest_issue_amount, '亿元', latest_issue_period,
            'official' if issue_source else 'missing', issue_source.get('source_name') if issue_source else None,
            issue_source.get('source_url') if issue_source else None,
            '财政部国债招标结果公告月度汇总' if issue_source else None,
            f'汇总当月 {len(latest_issue_rows)} 条 actual_issue_amount；每条来源见国债发行明细。' if issue_source else None,
            source_urls=[r['source_url'] for r in latest_issue_rows],
        ),
        _treasury_principal_card(official_issuances, entry),
        _treasury_interest_card(official_issuances, entry),
        _local_card(central_latest, 'central_government_debt_balance', '中央政府债务余额'),
    ]
    treasury_principal_monthly = _treasury_principal_by_month(official_issuances)

    balance_latest = balance.get('latest')
    omo_latest = omo.get('latest')
    monetization_cards = []
    for code, label in [
        ('total_assets', '央行总资产'), ('foreign_assets_pct', '国外资产占比'),
        ('foreign_exchange_pct', '外汇占比'), ('claims_on_government_pct', '对政府债权占比'),
        ('claims_on_other_depository_corporations_pct', '对其他存款性公司债权占比'),
    ]:
        status = balance_latest.get(f'{code}__status') if balance_latest else 'missing'
        monetization_cards.append(_card(
            label, balance_latest.get(code) if balance_latest else None,
            '%' if code.endswith('_pct') else '亿元', balance_latest.get('period') if balance_latest else None,
            status or 'missing', balance_latest.get('source_name') if balance_latest else None,
            balance_latest.get('source_url') if balance_latest else None,
            balance_latest.get('source_title') if balance_latest else None,
            balance_latest.get('parser_notes') if balance_latest else None,
            balance_latest.get(f'{code}__formula') if balance_latest else None,
        ))
    monetization_cards += [
        _card(
            '最近月份是否开展国债买卖',
            ('已开展' if omo_latest and omo_latest['operation_status'] == 'conducted' else '未开展') if omo_latest else None,
            None, omo_latest.get('period') if omo_latest else None, 'official' if omo_latest else 'missing',
            omo_latest.get('source_name') if omo_latest else None, omo_latest.get('source_url') if omo_latest else None,
            omo_latest.get('source_title') if omo_latest else None, omo_latest.get('parser_notes') if omo_latest else None,
        ),
        _card(
            '最近月份国债净买入', omo_latest.get('net_purchase_amount') if omo_latest else None,
            '亿元', omo_latest.get('period') if omo_latest else None, 'official' if omo_latest else 'missing',
            omo_latest.get('source_name') if omo_latest else None, omo_latest.get('source_url') if omo_latest else None,
            omo_latest.get('source_title') if omo_latest else None, omo_latest.get('parser_notes') if omo_latest else None,
        ),
        _card(
            '已抓取 official 月份累计净买入', omo_latest.get('cumulative_net_purchase_amount') if omo_latest else None,
            '亿元', omo_latest.get('period') if omo_latest else None, 'derived' if omo_latest else 'missing',
            omo_latest.get('source_name') if omo_latest else None, omo_latest.get('source_url') if omo_latest else None,
            omo_latest.get('source_title') if omo_latest else None,
            '只累计已抓取并解析成功的 official 月份，不外推缺失或未来月份。',
            'sum(net_purchase_amount for parsed official months)' if omo_latest else None,
        ),
    ]
    repo_as_of = buyout.get('as_of_stock')
    repo_latest = buyout.get('latest')
    repo_projection = buyout.get('current_month_projection')
    repo_cards = [
        _card(
            '截至当前日期未到期本金余额', repo_as_of.get('outstanding_amount') if repo_as_of else None,
            '亿元', repo_as_of.get('as_of_date') if repo_as_of else None,
            'derived' if repo_as_of else 'missing', '中国人民银行' if repo_as_of else None,
            repo_as_of.get('source_url') if repo_as_of else None,
            '买断式逆回购逐笔招标公告汇总' if repo_as_of else None,
            '按操作日和到期日筛选截至当日仍未到期的逐笔本金。' if repo_as_of else None,
            repo_as_of.get('formula') if repo_as_of else None,
            source_urls=repo_as_of.get('source_urls') if repo_as_of else None,
        ),
        _card(
            '最近已完成月末余额', repo_latest.get('outstanding_amount') if repo_latest else None,
            '亿元', repo_latest.get('period') if repo_latest else None,
            'derived' if repo_latest else 'missing', repo_latest.get('source_name') if repo_latest else None,
            repo_latest.get('source_url') if repo_latest else None,
            '买断式逆回购月末未到期本金测算' if repo_latest else None,
            repo_latest.get('parser_notes') if repo_latest else None,
            repo_latest.get('formula') if repo_latest else None,
            source_urls=repo_latest.get('source_urls') if repo_latest else None,
        ),
        _card(
            '当前月末预测余额', repo_projection.get('outstanding_amount') if repo_projection else None,
            '亿元', repo_projection.get('period') if repo_projection else None,
            'derived' if repo_projection else 'missing', repo_projection.get('source_name') if repo_projection else None,
            repo_projection.get('source_url') if repo_projection else None,
            '买断式逆回购月末未到期本金测算' if repo_projection else None,
            repo_projection.get('parser_notes') if repo_projection else None,
            repo_projection.get('formula') if repo_projection else None,
            warning='仅按截至当前已公告操作预测；月末前新增操作会改变该数值。' if repo_projection else None,
            source_urls=repo_projection.get('source_urls') if repo_projection else None,
        ),
        _card(
            '当前未到期操作笔数', repo_as_of.get('operation_count') if repo_as_of else None,
            '笔', repo_as_of.get('as_of_date') if repo_as_of else None,
            'derived' if repo_as_of else 'missing', '中国人民银行' if repo_as_of else None,
            repo_as_of.get('source_url') if repo_as_of else None,
            '买断式逆回购逐笔招标公告汇总' if repo_as_of else None,
            '筛选截至当日仍未到期的逐笔操作。' if repo_as_of else None,
            repo_as_of.get('formula') if repo_as_of else None,
            source_urls=repo_as_of.get('source_urls') if repo_as_of else None,
        ),
    ]

    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        last_update = _last_update_time(conn)
        scenario_count = conn.execute('SELECT COUNT(*) FROM fiscal_debt_scenario_runs').fetchone()[0]

    sections = {
        'fiscal_revenue_expenditure': {
            'title': '全国财政收入、支出与收支差额',
            'status': ('partial' if any(row.get('data_status') == 'partial'
                                        for row in budget.get('annual_series', []))
                       else ('official' if budget.get('annual_series') else 'missing')),
            'cards': budget.get('annual_cards', []),
            'latest_ytd_cards': budget.get('cards', []),
            'tables': {
                'annual': budget.get('annual_series', []),
                'ytd': budget.get('series', []),
            },
            'forecast': budget.get('forecast', {}),
            'coverage': budget.get('coverage', {}),
            'notes': budget.get('notes', []),
            'warnings': budget.get('warnings', []) + [
                '收支差额均为收入减支出的 derived 分析值，不等于法定预算赤字。',
                '未来值为透明情景估计，不是财政部预测。',
            ],
        },
        'government_debt_overview': {
            'title': '政府债务总览', 'status': _section_status(overview_cards),
            'cards': overview_cards,
            'budget_cards': budget.get('cards', []),
            'tables': {'central_government_debt': central_records, 'local_government_debt': local_records,
                       'fiscal_budget': budget.get('series', [])},
            'warnings': ['中央政府债务与地方政府债务口径分开保存；显性合计只在同一期数计算。',
                         '财政收支为国库司月度报告 YTD 累计；收支差额为 derived，不等于官方预算口径赤字。'],
        },
        'debt_rollover_pressure': {
            'title': '发行、还本、付息压力',
            'status': 'partial', 'cards': local_pressure_cards + treasury_pressure_cards,
            'tables': {
                'local_government_debt': local_records,
                'treasury_monthly_issuance': treasury_issuance.get('monthly', []),
                'treasury_by_type': treasury_issuance.get('by_type', []),
                'treasury_maturity_by_year': treasury_issuance.get('by_maturity_year', []),
                'treasury_principal_due_monthly': treasury_principal_monthly,
                'treasury_planned_only': _without_raw(treasury_issuance.get('current_year_planned_only', []), 80),
                'treasury_issuance_details': _without_raw(treasury_issuance.get('records', []), 120),
            },
            'warnings': ['国债实际发行（境内逐笔）已接入并按类型/年份汇总；到期还本/年付息为已抓国债的 derived 估计(非全口径)；储蓄国债、香港人民币国债尚未接入。',
                         '国债到期分布仅来自已抓取的逐只国债（2024 起），不等于全部存量国债的完整到期表。'],
        },
        'pboc_monetization_pressure': {
            'title': '央行与货币化压力', 'status': _section_status(monetization_cards),
            'cards': monetization_cards,
            'tables': {
                'pboc_balance_sheet': balance.get('records', []),
                'pboc_gov_bond_omo': _without_raw(omo.get('records', [])),
                'pboc_buyout_reverse_repo_stock': buyout.get('records', []),
                'pboc_buyout_reverse_repo_completed_stock': buyout.get('completed_records', []),
                'pboc_buyout_reverse_repo_projection': buyout.get('projection_records', []),
                'pboc_buyout_reverse_repo_operations': _without_raw(buyout.get('operations', [])),
                'pboc_buyout_reverse_repo_active_operations': _without_raw(
                    repo_as_of.get('active_operations', []) if repo_as_of else []
                ),
            },
            'repo_cards': repo_cards,
            'warnings': balance.get('notes', []) + ['央行对政府债权不等于国债余额，也不能用于推断地方债持有量。'],
        },
        'scenario_projection': {
            'title': '央行买债压力情景推算', 'status': 'scenario_only', 'cards': [], 'tables': [],
            'saved_run_count': scenario_count,
            'warnings': ['仅在用户点击运行后返回结果；不进入 official observation。'],
        },
        'debug_summary': {
            'title': '数据来源与 Debug', 'status': 'available', 'href': '/fiscal-debt/debug',
            'cards': [], 'tables': [], 'warnings': [],
        },
    }
    coverage = {
        'central_government_debt': {'records': len(central_records), 'earliest_period': central_records[0]['period'] if central_records else None,
                                    'latest_period': central_records[-1]['period'] if central_records else None},
        'local_government_debt': {'records': len(local_records), 'earliest_period': local_records[0]['period'] if local_records else None,
                                  'latest_period': local_records[-1]['period'] if local_records else None},
        'pboc_balance_sheet': balance.get('coverage'), 'pboc_gov_bond_omo': omo.get('coverage'),
        'pboc_buyout_reverse_repo': buyout.get('coverage'), 'mof_treasury_bonds': treasury_issuance.get('coverage'),
        'fiscal_budget': {
            'records': budget.get('coverage', {}).get('periods', 0),
            'earliest_period': budget.get('coverage', {}).get('earliest'),
            'latest_period': budget.get('coverage', {}).get('latest'),
            'annual_periods': budget.get('coverage', {}).get('annual_periods', 0),
        },
    }
    warnings = [warning for section in sections.values() for warning in section.get('warnings', [])]
    return {
        'success': True, 'data_mode': 'official_partial', 'sections': sections,
        'warnings': warnings, 'coverage': coverage, 'last_update_time': last_update,
    }


def _result_counts(result):
    inserted = result.get('new_records', 0)
    updated = result.get('updated_records', 0)
    if not inserted and not updated:
        updated = result.get(
            'records_upserted',
            result.get('records', result.get('parsed_records', result.get('operation_records', 0)))
        ) or 0
    return int(inserted or 0), int(updated or 0)


def run_fiscal_module_update(db_path, module_code):
    if module_code not in MODULE_UPDATES:
        raise ValueError(f'未知 fiscal-debt module_code: {module_code}')
    cfg = MODULE_UPDATES[module_code]
    started = datetime.now().isoformat()
    try:
        result = cfg['update'](db_path)
        success = bool(result.get('success'))
        parser_errors = result.get('parser_errors') or []
        warnings = result.get('warnings') or []
        status = 'success' if success and not parser_errors and not warnings else ('partial' if success else 'error')
        error_message = result.get('error')
        issues = list(warnings) + list(parser_errors)
        if parser_errors and not error_message:
            error_message = f'{len(parser_errors)} source fetch/parse errors'
        http_status = None
        for issue in issues:
            if isinstance(issue, dict):
                if issue.get('http_status'):
                    http_status = issue['http_status']
                    break
                text = str(issue.get('error') or '')
                for code in (400, 403, 404, 429, 500, 502, 503, 504):
                    if str(code) in text:
                        http_status = code
                        break
                if http_status:
                    break
        inserted, updated = _result_counts(result)
    except Exception as exc:
        result = {'success': False, 'error': str(exc)}
        success, status, error_message, http_status, inserted, updated = False, 'error', str(exc), None, 0, 0
        warnings = []
        issues = []
    finished = datetime.now().isoformat()
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        conn.execute('''INSERT INTO fiscal_debt_update_logs (
            module_code,source_name,source_type,source_url,started_at,finished_at,status,http_status,
            success,records_inserted,records_updated,new_records,updated_records,error_message,warnings
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            module_code, cfg['source_name'], cfg['source_type'], result.get('source_url') or cfg['source_url'], started, finished,
            status, http_status, int(success), inserted, updated, inserted, updated, error_message,
            json.dumps(issues, ensure_ascii=False),
        ))
        conn.commit()
    result.update({'module_code': module_code, 'status': status, 'started_at': started, 'finished_at': finished})
    return result


def run_all_fiscal_updates(db_path):
    results = []
    for module_code in MODULE_UPDATES:
        results.append(run_fiscal_module_update(db_path, module_code))
    all_succeeded = all(r.get('success') for r in results)
    all_clean = all(r.get('status') == 'success' for r in results)
    return {
        'success': all_succeeded,
        'status': 'success' if all_clean else ('partial' if all_succeeded else 'error'),
        'results': results,
        'finished_at': datetime.now().isoformat(),
    }


def build_fiscal_monitor_debug(db_path):
    base = build_fiscal_debt_debug_payload(db_path)
    budget = build_fiscal_budget_payload(db_path)
    with connect(db_path) as conn:
        ensure_fiscal_tables(conn)
        balance = build_pboc_balance_sheet_debug(conn)
        omo = build_pboc_gov_bond_omo_debug(conn)
        buyout = build_pboc_buyout_reverse_repo_debug(conn)
        treasury = build_mof_treasury_bond_debug(conn)
        omo['latest_observations'] = _without_raw(omo.get('latest_observations', []))
        buyout['latest_announcements'] = _without_raw(buyout.get('latest_announcements', []))
        buyout['latest_operations'] = _without_raw(buyout.get('latest_operations', []))
        buyout['latest_monthly_stock'] = _without_raw(buyout.get('latest_monthly_stock', []))
        treasury['latest_records'] = _without_raw(treasury.get('latest_records', []))
        recent_sources = _without_raw([dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_debt_sources ORDER BY updated_at DESC LIMIT 20').fetchall()])
        update_logs = [dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_debt_update_logs ORDER BY id DESC LIMIT 20').fetchall()]
        recent_fiscal = _without_raw([dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_debt_observations ORDER BY updated_at DESC,period DESC LIMIT 20').fetchall()])
        last_update_time = conn.execute('SELECT MAX(finished_at) FROM fiscal_debt_update_logs').fetchone()[0]
        last_success_time = conn.execute(
            "SELECT MAX(finished_at) FROM fiscal_debt_update_logs WHERE status IN ('success','partial')").fetchone()[0]
        last_error_row = conn.execute(
            "SELECT * FROM fiscal_debt_update_logs WHERE status='error' ORDER BY id DESC LIMIT 1").fetchone()
    missing_modules = [
        {'module_code': 'lgfv_debt', 'reason': '没有官方统一城投债余额口径。',
         'next_source': '中国债券信息网、交易所或经授权的 Wind/Choice。'},
        {'module_code': 'fiscal_gap',
         'reason': '一般公共预算/政府性基金收支(YTD)已接入，收支差额为 derived；官方预算口径赤字(含调入资金/结转结余)仍未单列。',
         'next_source': '财政部预算执行报告、全国人大预算决议。'},
        {'module_code': 'treasury_principal_interest',
         'reason': '已用已抓逐只国债给出 derived 估计(未来12个月还本 + 存量附息年付息)；全口径(含2024年前存量)完整序列仍缺。',
         'next_source': '财政部国债发行兑付公告和中央国债登记结算公开统计。'},
        {'module_code': 'complete_maturity_schedule', 'reason': '当前国债发行明细不等于完整存量债券到期表。',
         'next_source': '财政部历史公告、中国债券信息网或中债登。'},
    ]
    base.update({
        'modules': {'fiscal_debt': {'indicator_coverage': base.get('indicator_coverage', [])},
                    'pboc_balance_sheet': balance, 'pboc_gov_bond_omo': omo,
                    'pboc_buyout_reverse_repo': buyout, 'mof_treasury_bonds': treasury,
                    'fiscal_budget': budget},
        'coverage': {'fiscal_debt': base.get('indicator_coverage', []),
                     'pboc_balance_sheet': balance.get('coverage'),
                     'pboc_gov_bond_omo': omo.get('coverage'),
                     'pboc_buyout_reverse_repo': buyout.get('coverage'),
                     'mof_treasury_bonds': treasury.get('coverage'),
                     'fiscal_budget': budget.get('coverage')},
        'recent_source_records': recent_sources,
        'recent_observation_records': recent_fiscal,
        'recent_update_logs': update_logs,
        'parser_errors': [r for r in recent_sources if r.get('status') == 'error'],
        'last_update_time': last_update_time,
        'last_success_time': last_success_time,
        'last_error': dict(last_error_row) if last_error_row else None,
        'missing_modules': missing_modules,
    })
    return base
