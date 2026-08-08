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
     'url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202603/t20260316_3985331.htm',
     'title': '关于2025年中央和地方预算执行情况与2026年中央和地方预算草案的报告'},
    {'execution_year': '2024', 'budget_year': '2025',
     'url': 'https://www.gov.cn/yaowen/liebiao/202503/content_7013431.htm',
     'title': '关于2024年中央和地方预算执行情况与2025年中央和地方预算草案的报告'},
    {'execution_year': '2023', 'budget_year': '2024',
     'url': 'https://www.gov.cn/yaowen/liebiao/202403/content_6939289.htm',
     'title': '关于2023年中央和地方预算执行情况与2024年中央和地方预算草案的报告'},
    {'execution_year': '2022', 'budget_year': '2023',
     'url': 'http://www.gov.cn/xinwen/2023-03/15/content_5746960.htm',
     'title': '关于2022年中央和地方预算执行情况与2023年中央和地方预算草案的报告'},
)

# 人大常委会年中追加限额的决议/议案说明：3 月预算报告之后改变限额的官方文件。
# 2024-11-08 决议把 6 万亿一次性加在专项债务限额上，正是当年余额反超年初限额的原因。
LIMIT_AMENDMENTS = (
    {'period': '2024', 'indicator_code': 'local_special_debt_limit',
     'url': 'https://www.gov.cn/yaowen/liebiao/202411/content_6985598.htm',
     'title': '关于提请审议增加地方政府债务限额置换存量隐性债务的议案的说明',
     'pattern': r'2024年末地方政府专项债务限额将由[\d.]+亿元增加到' + r'([\d]+(?:\.\d+)?)\s*亿元',
     'source_name': '财政部（十四届全国人大常委会第十二次会议议案说明）'},
)

SOURCE_NAME = '财政部（提请全国人大审议的预算报告）'

# 2024 年化债方案的完整链条。网上普遍说的"12 万亿"是三段相加，但三段性质不同：
#   6 万亿  新增地方政府专项债务限额，2024-2026 每年 2 万亿（人大常委会批准）
#   4 万亿  2024 起连续五年每年从新增专项债中安排 8000 亿元补充政府性基金财力
#   2 万亿  2029 年及以后到期的棚改隐性债务，仍按原合同偿还
# 官方表述的"直接增加地方化债资源"只有前两段合计 10 万亿；第三段不是新增资源，
# 而是既有债务的偿还安排。把三段混作一个数会高估政策力度，因此分项存放。
DEBT_RESOLUTION_PACKAGE = (
    {'indicator_code': 'debt_swap_new_limit', 'period': '2024',
     'value': 60000.0, 'name': '化债方案：新增专项债务限额',
     'note': '一次报批分三年实施，2024—2026 年每年 2 万亿元。'},
    {'indicator_code': 'debt_swap_special_bond_allocation', 'period': '2024',
     'value': 40000.0, 'name': '化债方案：新增专项债中安排的化债资金',
     'note': '2024 年起连续五年每年 8000 亿元补充政府性基金财力，累计 4 万亿元。'},
    {'indicator_code': 'debt_resolution_direct_resources', 'period': '2024',
     'value': 100000.0, 'name': '化债方案：直接增加的地方化债资源',
     'note': '官方表述为 6 万亿限额与 4 万亿专项债安排之和；'
             '不含 2029 年及以后到期、仍按原合同偿还的棚改隐性债务。'},
)
DEBT_RESOLUTION_SOURCE = {
    'url': 'https://www.gov.cn/yaowen/shipin/202411/content_6985706.htm',
    'title': '全国人大常委会办公厅新闻发布会：增加地方政府债务限额6万亿元置换存量隐性债务',
    'source_name': '全国人大常委会办公厅新闻发布会（中国政府网转载）',
}

# 财政部在议案说明中公开披露的隐性债务余额与政府负债率。
# 本项目此前按"隐性债务无官方口径"处理，实为漏采：这一句是财政部部长受国务院
# 委托在全国人大常委会上的正式表述，属官方值。
HIDDEN_DEBT_DISCLOSURES = (
    {'indicator_code': 'hidden_debt_balance', 'period': '2023',
     'value': 143000.0, 'name': '全国地方政府隐性债务余额',
     'note': '财政部部长受国务院委托在十四届全国人大常委会第十二次会议上的说明：'
             '"截至2023年末，全国地方政府隐性债务余额14.3万亿元"。'},
    {'indicator_code': 'government_debt_to_gdp_incl_hidden', 'period': '2023',
     'value': 67.5, 'name': '政府负债率（含隐性债务）',
     'note': '同一说明：按2023年GDP初步核算数126.06万亿元计算，'
             '考虑法定政府债务和隐性债务后的全国政府负债率为67.5%。单位为百分比。'},
)
HIDDEN_DEBT_SOURCE = {
    'url': 'https://www.gov.cn/yaowen/liebiao/202411/content_6985598.htm',
    'title': '关于提请审议增加地方政府债务限额置换存量隐性债务的议案的说明',
    'source_name': '财政部（十四届全国人大常委会第十二次会议议案说明）',
}
NUM = r'([\d]+(?:\.\d+)?)\s*亿元'

INDICATOR_NAMES = {
    'treasury_debt_balance_yearend': '国债余额（年末）',
    'treasury_debt_limit': '国债限额（全国人大批准）',
    'local_debt_balance_yearend': '地方政府债务余额（年末）',
    'local_general_debt_balance_yearend': '地方政府一般债务余额（年末）',
    'local_special_debt_balance_yearend': '地方政府专项债务余额（年末）',
    'local_general_debt_limit': '地方政府一般债务限额（全国人大批准）',
    'local_special_debt_limit': '地方政府专项债务限额（全国人大批准）',
    'local_debt_limit_effective': '地方政府债务限额（年末有效值）',
    'debt_swap_new_limit': '化债方案：新增专项债务限额',
    'debt_swap_special_bond_allocation': '化债方案：新增专项债中安排的化债资金',
    'debt_resolution_direct_resources': '化债方案：直接增加的地方化债资源',
    'hidden_debt_balance': '全国地方政府隐性债务余额',
    'government_debt_to_gdp_incl_hidden': '政府负债率（含隐性债务）',
}
# 负债率是百分比，不能与亿元金额同表相加，单独标注单位。
PERCENT_INDICATORS = ('government_debt_to_gdp_incl_hidden',)
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

    各年表述不完全一致：2022 年报告写"中央财政国债余额…控制在全国人大批准的债务限额
    267008.35亿元以内"，并把地方年末有效限额也写了出来；2025 年报告则只说地方
    "控制在…限额以内"而不给数。按分句定位，抽得到就抽，抽不到留空。
    """
    rows = []

    def add(period, code, value):
        if value is not None:
            rows.append({'period': period, 'indicator_code': code, 'value': value})

    # 执行年那段用 。和；分句：国债与地方各占一个分句
    clauses = re.split(r'[。；]', text)
    treasury = next((c for c in clauses if '国债余额' in c), '')
    add(execution_year, 'treasury_debt_balance_yearend',
        _amount(treasury, r'国债余额' + NUM))
    # "控制在全国人大批准的债务限额X亿元以内" —— 这是该年末的有效限额，优先于
    # 上一年报告里前瞻给出的限额（年中可能被人大常委会追加过）
    add(execution_year, 'treasury_debt_limit',
        _amount(treasury, r'(?:国债|债务)限额' + NUM))

    local = next((c for c in clauses if '地方政府债务余额' in c), '')
    add(execution_year, 'local_debt_balance_yearend',
        _amount(local, r'地方政府债务余额' + NUM))
    add(execution_year, 'local_general_debt_balance_yearend',
        _amount(local, r'一般债务余额' + NUM))
    add(execution_year, 'local_special_debt_balance_yearend',
        _amount(local, r'专项债务余额' + NUM))
    add(execution_year, 'local_debt_limit_effective',
        _amount(local, r'(?:地方政府债务|债务)限额' + NUM))

    # 预算年那句形如"2026年，(中央财政)国债限额X亿元；地方政府一般债务限额Y、专项债务限额Z"
    forward = re.search(budget_year + r'年，\s*(?:中央财政)?国债限额' + NUM, text)
    if forward:
        add(budget_year, 'treasury_debt_limit', float(forward.group(1)))
        tail = text[forward.end():forward.end() + 200]
        add(budget_year, 'local_general_debt_limit',
            _amount(tail, r'一般债务限额' + NUM))
        add(budget_year, 'local_special_debt_limit',
            _amount(tail, r'专项债务限额' + NUM))
    return rows


def _store_static_rows(conn, rows, source, now):
    """写入不随年份滚动的政策口径值（化债方案分项、隐性债务披露）。"""
    stored = 0
    for row in rows:
        _upsert(conn, row, {'url': source['url'], 'title': source['title']}, now,
                source_name=source['source_name'], note=row.get('note'),
                indicator_name=row.get('name'))
        stored += 1
    return stored


def _upsert(conn, row, report, now, source_name=SOURCE_NAME, note=None,
            indicator_name=None):
    conn.execute('''INSERT INTO fiscal_debt_observations
      (indicator_code,indicator_name,value,unit_raw,unit_display,scale_factor,period,date,
       frequency,source_name,source_type,source_url,source_title,parser_notes,data_status,
       is_mock,is_seed,is_cache,debt_line,module_code,raw_text,created_at,updated_at)
      VALUES (?,?,?,?,?,1.0,?,?, 'annual',?,'mof_budget_report',?,?,?,'official',
              0,0,0,?,'debt_ceiling',?,?,?)
      ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
        value=excluded.value,source_url=excluded.source_url,
        source_title=excluded.source_title,parser_notes=excluded.parser_notes,
        raw_text=excluded.raw_text,updated_at=excluded.updated_at''',
      (row['indicator_code'],
       indicator_name or INDICATOR_NAMES[row['indicator_code']], row['value'],
       '%' if row['indicator_code'] in PERCENT_INDICATORS else '亿元',
       '%' if row['indicator_code'] in PERCENT_INDICATORS else '亿元',
       row['period'], f"{row['period']}-12-31", source_name, report['url'], report['title'],
       note or f"《{report['title']}》正文直陈值；全国人大批准口径，未做任何折算。",
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
        # 逐条幂等 upsert，抓取或解析失败时绝不先清旧数据。唯一键已经是
        # indicator_code + period + source_type；同年较新的执行报告或追加决议会
        # 覆盖旧值，不需要用“先删后写”换取去重。
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
        # 追加决议最后写入，覆盖 3 月预算报告里已被取代的限额
        for amendment in LIMIT_AMENDMENTS:
            try:
                text = plain_text(fetch(amendment['url']))
                match = re.search(amendment['pattern'], text)
                if not match:
                    errors.append(f"{amendment['title']}: 未匹配到追加后的限额")
                    continue
                _upsert(conn, {'period': amendment['period'],
                               'indicator_code': amendment['indicator_code'],
                               'value': float(match.group(1))},
                        {'url': amendment['url'], 'title': amendment['title']}, now,
                        source_name=amendment['source_name'])
                collected += 1
            except Exception as exc:
                errors.append(f"{amendment['title']}: {exc}")
        # 化债方案分项与隐性债务披露：不随年份滚动，直接按官方原文写入
        # 化债方案分项与隐性债务披露是常量口径，写入不依赖本轮抓取是否成功；
        # 因此它们单独计数，绝不参与 success 判定——否则全网失败也会显示成功，
        # 把"这轮什么都没抓到"掩盖过去。
        static_rows = (_store_static_rows(
                           conn, DEBT_RESOLUTION_PACKAGE, DEBT_RESOLUTION_SOURCE, now)
                       + _store_static_rows(
                           conn, HIDDEN_DEBT_DISCLOSURES, HIDDEN_DEBT_SOURCE, now))
        conn.commit()
    finally:
        conn.close()
    return {'success': collected > 0, 'records': collected,
            'static_records': static_rows, 'errors': errors,
            'retained_existing_on_failure': True}


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
        # 年末有效限额由执行年报告直接给出，已含人大常委会年中追加；
        # 拿不到时才退回上一年报告前瞻批准的"一般＋专项"之和。
        effective = get('local_debt_limit_effective')
        local_limit = effective if effective is not None else (
            (general_limit or 0) + (special_limit or 0)
            if (general_limit or special_limit) else None)
        years.append({
            'period': period,
            'treasury_limit': treasury_limit, 'treasury_balance': treasury_balance,
            'treasury_limit_source_url': (item.get('treasury_debt_limit') or {}).get('source_url'),
            'treasury_headroom': (treasury_limit - treasury_balance)
            if treasury_limit is not None and treasury_balance is not None else None,
            'local_general_limit': general_limit, 'local_special_limit': special_limit,
            'local_limit': local_limit,
            'local_limit_source_url': (
                (item.get('local_debt_limit_effective') or {}).get('source_url')
                or (item.get('local_general_debt_limit') or {}).get('source_url')
                or (item.get('local_special_debt_limit') or {}).get('source_url')),
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
            '城投债和隐性债务不进入人大限额、剩余空间或触线计算；广义债务卡另列财政部披露的'
            '隐性债务口径，并与城投债严格区分。',
        ],
    }
