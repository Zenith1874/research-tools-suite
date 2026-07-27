# -*- coding: utf-8 -*-
"""债务限额与余额：全国人大批准的"上限"及其剩余空间。

中国没有美国式的统一法定债务上限，但全国人大每年批准两项硬约束：
国债限额、地方政府债务限额（一般债务限额与专项债务限额分列）。
这两个数字连同当年年末实际余额，都写在财政部提交人大的
《关于XX年中央和地方预算执行情况与XX年中央和地方预算草案的报告》正文里，
是"债务上限"唯一有官方依据的定义。

一份报告同时给出两组数：执行年年末的余额与限额、次年批准的新限额，
因此每份报告落两个年度的观测。数字一律来自报告原文直陈句，不做推算。
"""
import re
import sqlite3
from datetime import datetime

from services.city_official_service import fetch, plain_text

# 中国政府网转载的财政部预算报告全文。URL 无规律，逐份登记；新报告发布后追加。
BUDGET_REPORTS = (
    {'execution_year': '2025', 'budget_year': '2026',
     'url': 'https://www.gov.cn/yaowen/liebiao/202603/content_7062689.htm',
     'title': '关于2025年中央和地方预算执行情况与2026年中央和地方预算草案的报告'},
    {'execution_year': '2024', 'budget_year': '2025',
     'url': 'https://www.gov.cn/yaowen/liebiao/202503/content_7013431.htm',
     'title': '关于2024年中央和地方预算执行情况与2025年中央和地方预算草案的报告'},
    {'execution_year': '2023', 'budget_year': '2024',
     'url': 'https://www.gov.cn/yaowen/liebiao/202403/content_6939289.htm',
     'title': '关于2023年中央和地方预算执行情况与2024年中央和地方预算草案的报告'},
)

SOURCE_NAME = '财政部（提请全国人大审议的预算报告）'
NUM = r'([\d]+(?:\.\d+)?)\s*亿元'

INDICATOR_NAMES = {
    'treasury_debt_balance_yearend': '国债余额（年末）',
    'treasury_debt_limit': '国债限额（全国人大批准）',
    'local_debt_balance_yearend': '地方政府债务余额（年末）',
    'local_general_debt_balance_yearend': '地方政府一般债务余额（年末）',
    'local_special_debt_balance_yearend': '地方政府专项债务余额（年末）',
    'local_general_debt_limit': '地方政府一般债务限额（全国人大批准）',
    'local_special_debt_limit': '地方政府专项债务限额（全国人大批准）',
}
# 余额与限额都是十万亿量级，用宽区间兜住抽错列
VALUE_BOUNDS = (10000.0, 2000000.0)


def _amount(text, pattern):
    match = re.search(pattern, text)
    if not match:
        return None
    value = float(match.group(1))
    return value if VALUE_BOUNDS[0] <= value <= VALUE_BOUNDS[1] else None


def parse_budget_report(text, execution_year, budget_year):
    """从报告正文抽取两个年度的余额与限额。

    执行年那句形如：
      "2025年年末，国债余额412317.68亿元，控制在全国人大批准的国债限额418608.35亿元
       以内；地方政府债务余额548230.82亿元…包括一般债务余额175120.36亿元、
       专项债务余额373110.46亿元"
    预算年那句形如：
      "2026年，国债限额485508.35亿元；地方政府一般债务限额188689.22亿元、
       专项债务限额443185.08亿元"
    """
    rows = []

    def add(period, code, value):
        if value is not None:
            rows.append({'period': period, 'indicator_code': code, 'value': value})

    add(execution_year, 'treasury_debt_balance_yearend',
        _amount(text, r'国债余额' + NUM))
    add(execution_year, 'treasury_debt_limit',
        _amount(text, r'国债余额.{0,40}?国债限额' + NUM))
    add(execution_year, 'local_debt_balance_yearend',
        _amount(text, r'地方政府债务余额' + NUM))
    add(execution_year, 'local_general_debt_balance_yearend',
        _amount(text, r'一般债务余额' + NUM))
    add(execution_year, 'local_special_debt_balance_yearend',
        _amount(text, r'专项债务余额' + NUM))

    # 预算年限额句以"YYYY年，国债限额"开头，与执行年那句区分
    forward = re.search(budget_year + r'年，\s*国债限额' + NUM, text)
    if forward:
        add(budget_year, 'treasury_debt_limit', float(forward.group(1)))
        tail = text[forward.end():forward.end() + 160]
        add(budget_year, 'local_general_debt_limit',
            _amount(tail, r'一般债务限额' + NUM))
        add(budget_year, 'local_special_debt_limit',
            _amount(tail, r'专项债务限额' + NUM))
    return rows


def _upsert(conn, row, report, now):
    conn.execute('''INSERT INTO fiscal_debt_observations
      (indicator_code,indicator_name,value,unit_raw,unit_display,scale_factor,period,date,
       frequency,source_name,source_type,source_url,source_title,parser_notes,data_status,
       is_mock,is_seed,is_cache,debt_line,module_code,raw_text,created_at,updated_at)
      VALUES (?,?,?,'亿元','亿元',1.0,?,?, 'annual',?,'mof_budget_report',?,?,?,'official',
              0,0,0,?,'debt_ceiling',?,?,?)
      ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
        value=excluded.value,source_url=excluded.source_url,
        source_title=excluded.source_title,parser_notes=excluded.parser_notes,
        raw_text=excluded.raw_text,updated_at=excluded.updated_at''',
      (row['indicator_code'], INDICATOR_NAMES[row['indicator_code']], row['value'],
       row['period'], f"{row['period']}-12-31", SOURCE_NAME, report['url'], report['title'],
       f"《{report['title']}》正文直陈值；全国人大批准口径，未做任何折算。",
       'central_government_debt' if row['indicator_code'].startswith('treasury')
       else 'local_government_debt',
       f"{row['period']} {INDICATOR_NAMES[row['indicator_code']]}: {row['value']} 亿元",
       now, now))


def update_debt_ceiling(db_path):
    now = datetime.now().isoformat()
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute('PRAGMA busy_timeout=30000')
    collected, errors = 0, []
    try:
        # 同一年度可能被两份报告覆盖（执行年 vs 预算年），后者以更新的报告为准，
        # 因此先删除本模块旧值再整体重写，避免重复行。
        conn.execute("DELETE FROM fiscal_debt_observations WHERE module_code='debt_ceiling'")
        for report in sorted(BUDGET_REPORTS, key=lambda r: r['execution_year']):
            try:
                text = plain_text(fetch(report['url']))
            except Exception as exc:
                errors.append(f"{report['title']}: {exc}")
                continue
            rows = parse_budget_report(text, report['execution_year'], report['budget_year'])
            if not rows:
                errors.append(f"{report['title']}: 未抽到任何限额/余额")
                continue
            for row in rows:
                _upsert(conn, row, report, now)
                collected += 1
        conn.commit()
    finally:
        conn.close()
    return {'success': collected > 0, 'records': collected, 'errors': errors}


def build_ceiling_payload(db_path):
    """限额 vs 余额，以及每年剩余空间。剩余空间是减法，标为 derived。"""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            '''SELECT indicator_code,indicator_name,period,value,source_url,source_title
               FROM fiscal_debt_observations WHERE module_code='debt_ceiling'
               ORDER BY period,indicator_code''')]
    finally:
        conn.close()
    by_period = {}
    for row in rows:
        by_period.setdefault(row['period'], {})[row['indicator_code']] = row
    years = []
    for period in sorted(by_period):
        item = by_period[period]
        get = lambda code: (item.get(code) or {}).get('value')
        treasury_limit, treasury_balance = get('treasury_debt_limit'), get('treasury_debt_balance_yearend')
        general_limit, special_limit = get('local_general_debt_limit'), get('local_special_debt_limit')
        general_balance = get('local_general_debt_balance_yearend')
        special_balance = get('local_special_debt_balance_yearend')
        local_limit = (general_limit or 0) + (special_limit or 0) if (general_limit or special_limit) else None
        years.append({
            'period': period,
            'treasury_limit': treasury_limit, 'treasury_balance': treasury_balance,
            'treasury_headroom': (treasury_limit - treasury_balance)
            if treasury_limit is not None and treasury_balance is not None else None,
            'local_general_limit': general_limit, 'local_special_limit': special_limit,
            'local_limit': local_limit,
            'local_balance': get('local_debt_balance_yearend'),
            'local_general_balance': general_balance, 'local_special_balance': special_balance,
        })
    # 年初预算报告给出的是当时批准的限额；人大常委会可在年中追加（如 2024 年 11 月
    # 增加地方政府债务限额用于置换隐性债务）。若年末余额反超年初限额，说明该年限额
    # 已被追加决议取代，此时不给"剩余空间"，只标出限额口径已过时，绝不呈现负剩余。
    for year in years:
        limit, balance = year['local_limit'], year['local_balance']
        if limit is None or balance is None:
            year['local_headroom'] = None
            year['local_limit_status'] = 'incomplete'
        elif balance > limit:
            year['local_headroom'] = None
            year['local_limit_status'] = 'superseded'
        else:
            year['local_headroom'] = limit - balance
            year['local_limit_status'] = 'as_approved'
        t_limit, t_balance = year['treasury_limit'], year['treasury_balance']
        year['treasury_limit_status'] = (
            'incomplete' if t_limit is None or t_balance is None
            else 'superseded' if t_balance > t_limit else 'as_approved')
        if year['treasury_limit_status'] != 'as_approved':
            year['treasury_headroom'] = None
    return {
        'generated_at': datetime.now().isoformat(), 'years': years, 'rows': rows,
        'definition': ('中国无统一法定债务上限；此处"上限"指全国人大每年批准的国债限额与'
                       '地方政府债务限额（一般＋专项），来自财政部预算报告正文。'),
        'caveats': [
            '限额与余额均为报告原文直陈值，剩余空间＝限额−余额，为 derived 减法。',
            '限额取自当年 3 月预算报告，为当时人大批准值；人大常委会可在年中追加'
            '（2024 年 11 月即增加地方政府债务限额用于置换存量隐性债务）。'
            '年末余额反超该限额的年份标为 superseded，不计算剩余空间，待补入追加决议原文。',
            '城投债等隐性债务不在人大限额口径内，本模块不含其数字。',
        ],
    }
