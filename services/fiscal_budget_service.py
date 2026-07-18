# -*- coding: utf-8 -*-
"""全国财政收支模块：一般公共预算收入/支出 + 政府性基金收入/支出(月度累计 YTD)。

数据源：财政部国库司"财政收支情况"月度报告(gks.mof.gov.cn/tongjishuju/)。
口径说明：官方报告为年初至今累计值；差额=收入-支出 为 derived(带公式)，
不等于官方"赤字"(官方赤字按预算口径含调入资金/结转结余等)。
数据纪律：逐条 official + 报告原文 source_url；解析失败只记日志不清旧数据。
"""
import html
import re
import sqlite3
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from statistics import median
from urllib.parse import urljoin

import requests

from services.fiscal_debt_service import fetch_url

SOURCE_NAME = '财政部国库司'
SOURCE_TYPE = 'mof_fiscal_budget'
INDEX_URL = 'https://gks.mof.gov.cn/tongjishuju/index.htm'

INDICATORS = {
    'general_budget_revenue_ytd':  '全国一般公共预算收入(YTD)',
    'general_budget_expenditure_ytd': '全国一般公共预算支出(YTD)',
    'general_budget_balance_ytd': '全国一般公共预算收支差额(YTD)',
    'gov_fund_revenue_ytd': '全国政府性基金预算收入(YTD)',
    'gov_fund_expenditure_ytd': '全国政府性基金预算支出(YTD)',
    'govfund_land_transfer_revenue_ytd': '国有土地使用权出让收入(YTD)',
    'govfund_land_transfer_revenue_ytd_yoy_official': '国有土地使用权出让收入同比(官方可比口径)',
    'gov_fund_balance_ytd': '全国政府性基金预算收支差额(YTD)',
    'combined_budget_revenue_ytd': '一般公共预算 + 政府性基金收入(YTD，简单相加)',
    'combined_budget_expenditure_ytd': '一般公共预算 + 政府性基金支出(YTD，简单相加)',
    'combined_budget_balance_ytd': '一般公共预算 + 政府性基金收支差额(YTD，简单相加)',
}

CORE_OFFICIAL_INDICATORS = (
    'general_budget_revenue_ytd',
    'general_budget_expenditure_ytd',
    'gov_fund_revenue_ytd',
    'gov_fund_expenditure_ytd',
)

OFFICIAL_INDICATORS = CORE_OFFICIAL_INDICATORS + (
    'govfund_land_transfer_revenue_ytd',
    'govfund_land_transfer_revenue_ytd_yoy_official',
)

FORMULAS = {
    'general_budget_balance_ytd':
        'general_budget_revenue_ytd - general_budget_expenditure_ytd',
    'gov_fund_balance_ytd':
        'gov_fund_revenue_ytd - gov_fund_expenditure_ytd',
    'combined_budget_revenue_ytd':
        'general_budget_revenue_ytd + gov_fund_revenue_ytd',
    'combined_budget_expenditure_ytd':
        'general_budget_expenditure_ytd + gov_fund_expenditure_ytd',
    'combined_budget_balance_ytd':
        'combined_budget_revenue_ytd - combined_budget_expenditure_ytd',
}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_fiscal_budget_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_budget_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.commit()


# ── 纯解析(可单测) ────────────────────────────────────────────────────────────
def parse_budget_period_from_title(title):
    """报告标题 -> 截止月份 'YYYY-MM'。
    "2026年1-5月财政收支情况"->2026-05；"2026年一季度"->03；"上半年"->06；
    "前三季度"->09；"2025年财政收支情况"(全年)->2025-12。"""
    m = re.search(r'(20\d{2})年', title)
    if not m:
        return None
    year = m.group(1)
    m2 = re.search(r'1-(\d{1,2})月', title)
    if m2:
        return f'{year}-{int(m2.group(1)):02d}'
    direct_month = re.search(r'20\d{2}年(\d{1,2})月份?财政收支情况', title)
    if direct_month:
        return f'{year}-{int(direct_month.group(1)):02d}'
    for kw, mm in [('一季度', '03'), ('上半年', '06'), ('前三季度', '09'), ('三季度', '09')]:
        if kw in title:
            return f'{year}-{mm}'
    if re.search(r'20\d{2}年财政收支情况', title):
        return f'{year}-12'
    if re.search(r'20\d{2}年公共财政收支情况', title):
        return f'{year}-12'
    return None


def _normalise_report_text(text):
    """Normalize full-width digits/punctuation and remove HTML/spacing noise."""
    t = html.unescape(str(text or ''))
    t = unicodedata.normalize('NFKC', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = re.sub(r'\s+', '', t)
    # Values occasionally use a thousands separator. Removing commas also makes
    # historical punctuation variants harmless for the cumulative-value regex.
    return t.replace(',', '')


def _first_report_value(text, labels):
    label_group = '(?:' + '|'.join(labels) + ')'
    prefixes = (
        r'(?:1-\d{1,2}月(?:累计)?|上半年(?:累计)?|前三季度(?:累计)?|全年|20\d{2}年)'
    )
    patterns = [
        prefixes + r'全国' + label_group + r'(?:为)?([\d.]+)亿元',
        r'全国' + label_group + r'(?:为)?([\d.]+)亿元',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def derive_budget_values(values):
    """Return a copy with transparent analytical balances and two-account sums."""
    out = dict(values)
    general_revenue = out.get('general_budget_revenue_ytd')
    general_expenditure = out.get('general_budget_expenditure_ytd')
    fund_revenue = out.get('gov_fund_revenue_ytd')
    fund_expenditure = out.get('gov_fund_expenditure_ytd')
    if general_revenue is not None and general_expenditure is not None:
        out['general_budget_balance_ytd'] = round(general_revenue - general_expenditure, 2)
    if fund_revenue is not None and fund_expenditure is not None:
        out['gov_fund_balance_ytd'] = round(fund_revenue - fund_expenditure, 2)
    if general_revenue is not None and fund_revenue is not None:
        out['combined_budget_revenue_ytd'] = round(general_revenue + fund_revenue, 2)
    if general_expenditure is not None and fund_expenditure is not None:
        out['combined_budget_expenditure_ytd'] = round(general_expenditure + fund_expenditure, 2)
    if ('combined_budget_revenue_ytd' in out and
            'combined_budget_expenditure_ytd' in out):
        out['combined_budget_balance_ytd'] = round(
            out['combined_budget_revenue_ytd'] - out['combined_budget_expenditure_ytd'], 2)
    return out


def parse_budget_report_text(text):
    """报告正文 -> {indicator_code: value}，兼容 2010 年以来的旧称与全角数字。"""
    t = _normalise_report_text(text)
    out = {}
    label_variants = {
        'general_budget_revenue_ytd': (
            '一般公共预算收入', '一般公共财政收入', '公共财政收入', '财政收入'),
        'general_budget_expenditure_ytd': (
            '一般公共预算支出', '一般公共财政支出', '公共财政支出', '财政支出'),
        'gov_fund_revenue_ytd': ('政府性基金预算收入', '政府性基金收入'),
        'gov_fund_expenditure_ytd': ('政府性基金预算支出', '政府性基金支出'),
    }
    for code, labels in label_variants.items():
        value = _first_report_value(t, labels)
        if value is not None:
            out[code] = value
    land_match = re.search(
        r'国有土地使用权出让收入(?!相关支出)(?:为)?([\d.]+)亿元'
        r'[^。；;]{0,36}?(?:同比|比上年同期|比上年)(增长|上升|下降)([\d.]+)%', t)
    if land_match:
        out['govfund_land_transfer_revenue_ytd'] = float(land_match.group(1))
        sign = -1 if land_match.group(2) == '下降' else 1
        out['govfund_land_transfer_revenue_ytd_yoy_official'] = round(
            sign * float(land_match.group(3)), 4)
    return derive_budget_values(out)


def discover_budget_reports(max_pages=4):
    """索引页(含分页 index_1.htm…) -> [(url, title)]，新在前。
    常规增量默认 4 页足够(新报告永远在前几页,历史 2010+ 已入库、有完整性检查兜底);
    全量回填时显式传 max_pages=23。"""
    links_by_page = {}

    def fetch_index(i):
        url = INDEX_URL if i == 0 else INDEX_URL.replace('index.htm', f'index_{i}.htm')
        try:
            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': INDEX_URL,
            }, timeout=10)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'
            page_html = response.text
        except Exception:
            # A transient 502 on one historical index page must not hide every
            # older page. Individual report failures are still surfaced later.
            return i, []
        page_links = re.findall(r'href="(\./[^"]+|https?://gks\.mof\.gov\.cn[^"]+)"[^>]*>([^<]*财政收支情况[^<]*)<', page_html)
        return i, [(urljoin(url, href), title.strip()) for href, title in page_links]

    with ThreadPoolExecutor(max_workers=min(4, max(1, int(max_pages)))) as executor:
        futures = [executor.submit(fetch_index, i) for i in range(max_pages)]
        for future in as_completed(futures):
            page, page_links = future.result()
            links_by_page[page] = page_links
    links = [item for page in sorted(links_by_page) for item in links_by_page[page]]
    seen, out = set(), []
    for href, title in links:
        if href not in seen:
            seen.add(href)
            out.append((href, title))
    return out


def _is_annual_report(title):
    return bool(re.fullmatch(r'20\d{2}年(?:公共)?财政收支情况', title.strip()))


def _required_codes_for_period(period):
    # The regular fiscal release did not report the nationwide government-fund
    # account in 2010/2011. Keep the public-budget series instead of fabricating
    # a comparable fund value; fund-account history starts when directly present.
    if int(period[:4]) < 2012:
        return {
            'general_budget_revenue_ytd',
            'general_budget_expenditure_ytd',
            'general_budget_balance_ytd',
        }
    return set(INDICATORS)


def update_fiscal_budget(db_path, max_reports=30, full_history=False, sleep_seconds=0.5):
    """full_history=True 时深翻 23 页索引(新库重建 2010+ 年度史用);常规增量走默认 4 页。"""
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    reports = discover_budget_reports(max_pages=23 if full_history else 4)
    with connect(db_path) as conn:
        ensure_fiscal_budget_tables(conn)
        now = datetime.now().isoformat()
        annual_reports = [
            item for item in reports
            if _is_annual_report(item[1]) and int(item[1][:4]) >= 2010
        ]
        selected_reports = []
        seen_urls = set()
        # Full history must include monthly reports, not only annual history and
        # the latest max_reports slice; otherwise newly added official fields
        # can never be backfilled into older complete fiscal rows.
        candidates = ([item for item in reports
                       if (parse_budget_period_from_title(item[1]) or '0000')[:4] >= '2010']
                      if full_history else annual_reports + reports[:max_reports])
        for item in candidates:
            if item[0] not in seen_urls:
                seen_urls.add(item[0])
                selected_reports.append(item)
        pending = []
        for url, title in selected_reports:
            period = parse_budget_period_from_title(title)
            if not period:
                continue
            existing_codes = {row[0] for row in conn.execute(
                'SELECT indicator_code FROM fiscal_budget_observations WHERE period=?', (period,))}
            if _required_codes_for_period(period).issubset(existing_codes):
                continue
            pending.append((period, url, title))

        def fetch_report(item):
            return parse_budget_report_text(fetch_url(item[1], timeout=10))

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {executor.submit(fetch_report, item): item for item in pending}
            for future in as_completed(future_map):
                period, url, title = future_map[future]
                try:
                    vals = future.result()
                except Exception as exc:
                    errors.append(f'{title}: {exc}')
                    continue
                for code, value in vals.items():
                    derived = code not in OFFICIAL_INDICATORS
                    unit = '%' if code.endswith('_yoy_official') else '亿元'
                    parser_notes = (
                        '解析自财政部国库司“财政收支情况”政府性基金段；官方同比为可比口径。'
                        if code.startswith('govfund_land_transfer_') else
                        '解析自财政部国库司"财政收支情况"报告正文；官方口径为年初至今累计。旧报告名称已标准化但原文保留。')
                    cur = conn.execute('''INSERT INTO fiscal_budget_observations (
                        indicator_code,indicator_name,period,value,unit,data_status,
                        source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(indicator_code,period) DO UPDATE SET
                        value=excluded.value, source_url=excluded.source_url, updated_at=excluded.updated_at''',
                        (code, INDICATORS[code], period, value, unit,
                         'derived' if derived else 'official', SOURCE_NAME, SOURCE_TYPE, url, title,
                         parser_notes, FORMULAS.get(code), now))
                    upserted += cur.rowcount
                conn.commit()
                if sleep_seconds:
                    time.sleep(float(sleep_seconds))
        conn.commit()
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'reports_found': len(reports), 'reports_selected': len(selected_reports),
            'errors': errors[:8]}


def _annual_series(series):
    annual = []
    for row in series:
        if not row['period'].endswith('-12'):
            continue
        item = dict(row)
        item['source_period'] = item['period']
        item['year'] = int(item['period'][:4])
        item['period'] = item['period'][:4]
        official_count = sum(item.get(code) is not None for code in CORE_OFFICIAL_INDICATORS)
        item['data_status'] = 'official' if official_count == len(CORE_OFFICIAL_INDICATORS) else 'partial'
        annual.append(item)
    return annual


def _bounded_growth(value, lower=-0.20, upper=0.20):
    return max(lower, min(upper, float(value)))


def _historical_growth(annual, code, lookback=5):
    observations = [row for row in annual if isinstance(row.get(code), (int, float))]
    growth = []
    for previous, current in zip(observations, observations[1:]):
        if current['year'] != previous['year'] + 1 or previous[code] == 0:
            continue
        growth.append(current[code] / previous[code] - 1)
    if not growth:
        return 0.0
    return _bounded_growth(median(growth[-lookback:]))


def _forecast_row(year, raw_values, scenario_name, method):
    values = derive_budget_values(raw_values)
    return {
        'period': str(year), 'year': year, **values,
        'data_status': 'scenario', 'scenario': scenario_name,
        'method': method,
        'formula': 'previous_year_value × (1 + scenario_growth_rate)',
    }


def build_budget_forecast(annual, series, horizon=3):
    """Build three transparent scenarios without writing them as official data."""
    complete = [row for row in annual if all(
        isinstance(row.get(code), (int, float)) for code in CORE_OFFICIAL_INDICATORS)]
    if not complete:
        return {'data_status': 'missing', 'scenarios': {},
                'warnings': ['完整年度官方数据不足，未生成财政收支情景。']}
    anchor = complete[-1]
    by_period = {row['period']: row for row in series}
    latest_ytd = next((row for row in reversed(series)
                       if int(row['period'][:4]) > anchor['year'] and not row['period'].endswith('-12')),
                      None)
    prior_ytd = None
    if latest_ytd:
        prior_ytd = by_period.get(f"{int(latest_ytd['period'][:4]) - 1}{latest_ytd['period'][4:]}")

    historical_rates = {code: _historical_growth(complete, code) for code in CORE_OFFICIAL_INDICATORS}
    first_year_rates = dict(historical_rates)
    ytd_rate_codes = []
    if latest_ytd and prior_ytd:
        for code in CORE_OFFICIAL_INDICATORS:
            current = latest_ytd.get(code)
            previous = prior_ytd.get(code)
            if isinstance(current, (int, float)) and isinstance(previous, (int, float)) and previous:
                first_year_rates[code] = _bounded_growth(current / previous - 1)
                ytd_rate_codes.append(code)

    scenario_specs = {
        'baseline': {'label': '基准', 'revenue_adjustment': 0.0, 'expenditure_adjustment': 0.0},
        'improvement': {'label': '收支改善', 'revenue_adjustment': 0.02, 'expenditure_adjustment': -0.02},
        'pressure': {'label': '财政承压', 'revenue_adjustment': -0.02, 'expenditure_adjustment': 0.02},
    }
    scenarios = {}
    revenue_codes = {'general_budget_revenue_ytd', 'gov_fund_revenue_ytd'}
    for scenario_code, spec in scenario_specs.items():
        previous_values = {code: anchor[code] for code in CORE_OFFICIAL_INDICATORS}
        rows = []
        for offset in range(1, horizon + 1):
            year = anchor['year'] + offset
            values = {}
            for code in CORE_OFFICIAL_INDICATORS:
                base_rate = first_year_rates[code] if offset == 1 else historical_rates[code]
                adjustment = (spec['revenue_adjustment'] if code in revenue_codes
                              else spec['expenditure_adjustment'])
                applied_rate = _bounded_growth(base_rate + adjustment)
                values[code] = round(previous_values[code] * (1 + applied_rate), 1)
            method = ('latest same-period YTD growth for available indicators; ' if offset == 1 and ytd_rate_codes else '')
            method += 'five-change median annual growth with scenario adjustment; growth bounded to ±20%'
            rows.append(_forecast_row(year, values, scenario_code, method))
            previous_values = values
        scenarios[scenario_code] = {'label': spec['label'], 'records': rows}

    return {
        'data_status': 'scenario', 'anchor_year': anchor['year'], 'horizon_years': horizon,
        'latest_ytd_period': latest_ytd['period'] if latest_ytd else None,
        'comparison_ytd_period': prior_ytd['period'] if prior_ytd else None,
        'historical_growth_rates': historical_rates,
        'first_year_growth_rates': first_year_rates,
        'scenario_definitions': scenario_specs,
        'scenarios': scenarios,
        'warnings': [
            '情景估计不是财政部预测，不写入 official observation。',
            '基准情景优先用最新同月 YTD 同比估计下一完整年度，之后使用最近五个年度变动的中位数。',
            '改善/承压情景分别在收入与支出增速上作 ±2 个百分点调整；所有增速限制在 ±20%。',
        ],
    }


def build_fiscal_budget_payload(db_path):
    with connect(db_path) as conn:
        ensure_fiscal_budget_tables(conn)
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_budget_observations ORDER BY period, indicator_code')]
    by_period = {}
    for r in rows:
        rec = by_period.setdefault(r['period'], {
            'period': r['period'], 'source_url': r['source_url'], 'source_urls': [],
            'source_title': r['source_title'], 'data_status': 'official',
        })
        rec[r['indicator_code']] = r['value']
        if r['source_url'] and r['source_url'] not in rec['source_urls']:
            rec['source_urls'].append(r['source_url'])
    series = sorted(by_period.values(), key=lambda x: x['period'])
    annual = _annual_series(series)
    forecast = build_budget_forecast(annual, series)
    latest = series[-1] if series else None
    latest_rows = {r['indicator_code']: r for r in rows if latest and r['period'] == latest['period']}
    cards = []
    for code in INDICATORS:
        r = latest_rows.get(code)
        cards.append({
            'label': INDICATORS[code], 'value': r['value'] if r else None, 'unit': '亿元',
            'period': r['period'] if r else None,
            'data_status': r['data_status'] if r else 'missing',
            'source_name': SOURCE_NAME if r else None,
            'source_url': r['source_url'] if r else None,
            'source_title': r['source_title'] if r else None,
            'parser_notes': r['parser_notes'] if r else None,
            'formula': r['formula'] if r else None,
            'warning': None if r else '尚未抓取。',
        })
    latest_annual = annual[-1] if annual else None
    annual_cards = []
    for code in ('general_budget_revenue_ytd', 'general_budget_expenditure_ytd',
                 'general_budget_balance_ytd', 'gov_fund_balance_ytd',
                 'combined_budget_balance_ytd'):
        value = latest_annual.get(code) if latest_annual else None
        annual_cards.append({
            'label': INDICATORS[code].replace('(YTD)', '').replace('(YTD，简单相加)', '（简单相加）'),
            'value': value, 'unit': '亿元',
            'period': latest_annual['period'] if latest_annual else None,
            'data_status': ('derived' if code in FORMULAS else 'official') if value is not None else 'missing',
            'source_name': SOURCE_NAME if value is not None else None,
            'source_url': latest_annual.get('source_url') if latest_annual else None,
            'formula': FORMULAS.get(code),
            'warning': None if value is not None else '该年度口径尚无完整官方值。',
        })
    return {
        'data_status': 'official' if rows else 'missing',
        'coverage': {'periods': len(series),
                     'earliest': series[0]['period'] if series else None,
                     'latest': series[-1]['period'] if series else None,
                     'annual_periods': len(annual),
                     'annual_earliest': annual[0]['period'] if annual else None,
                     'annual_latest': annual[-1]['period'] if annual else None},
        'cards': cards, 'annual_cards': annual_cards,
        'series': series, 'annual_series': annual, 'forecast': forecast,
        'warnings': [] if rows else ['财政收支尚未抓取；未生成 mock。'],
        'notes': [
            '官方报告为年初至今累计(YTD)；收支差额为 derived，不等于官方预算口径赤字。',
            '一般公共预算与政府性基金的合计仅为简单相加分析视图，未抵销调入调出或跨账本转移。',
            '2010—2011 年国库司年度财政收支稿未同时披露全国政府性基金收支，基金年度序列从直接可核验的 2012 年开始。',
        ],
    }
