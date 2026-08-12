# -*- coding: utf-8 -*-
"""中国房价模块：
1) 国家统计局"70个大中城市商品住宅销售价格变动情况"月报(官方,城市级,新房+二手,指数)
   - 注意:统计局 data.stats.gov.cn API 对境外 IP 403,但 www.stats.gov.cn 新闻发布页可访问,
     故走月报正文表格解析(与 MOF/PBOC 爬虫同模式)。
2) BIS 中国住宅价格指数(经 FRED 免 key CSV,2005 起季度,全国口径,长趋势)。

数据纪律:逐条 official + månedsreport原文/FRED 系列页 source_url;上涨/下跌城市数等
统计为 derived+formula;解析失败只记日志不清旧数据;不用商业挂牌价(非成交口径)。
"""
import csv
import os
import re
import sqlite3
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from datetime import datetime

import requests
from bs4 import BeautifulSoup

NBS_SOURCE = '国家统计局'
SOURCE_TYPE = 'nbs_70city_housing'
NBS_LIST_URL = 'https://www.stats.gov.cn/sj/zxfb/'
NBS_SEARCH_API = 'https://api.so-gov.cn/query/s'
NBS_SEARCH_SITE_CODE = 'bm36000002'
NBS_HISTORY_QUERY = '70个大中城市住宅销售价格变动情况'
NBS_SALES_QUERIES = ('全国房地产开发投资和销售情况', '全国房地产开发和销售情况',
                     '全国房地产市场基本情况')
FRED_SERIES = [
    ('QCNR628BIS', 'BIS 中国实际住宅价格指数(2010=100)', 'real'),
    ('QCNN628BIS', 'BIS 中国名义住宅价格指数(2010=100)', 'nominal'),
]
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
HTTP_TIMEOUT = 25
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANNUAL_SALES_HISTORY_PATH = os.path.join(
    ROOT, 'data', 'housing_nbs_annual_sales_history.csv')

TIER1 = ['北京', '上海', '广州', '深圳']

INDICATORS = {
    'new_home_mom_idx': '新建商品住宅价格指数(环比,上月=100)',
    'new_home_yoy_idx': '新建商品住宅价格指数(同比,上年同月=100)',
    'second_home_mom_idx': '二手住宅价格指数(环比,上月=100)',
    'second_home_yoy_idx': '二手住宅价格指数(同比,上年同月=100)',
}

SALES_INDICATORS = {
    'sales_area_ytd': ('新建商品房销售面积累计', '万平方米'),
    'sales_area_ytd_yoy_official': ('新建商品房销售面积累计同比', '%'),
    'sales_value_ytd': ('新建商品房销售额累计', '亿元'),
    'sales_value_ytd_yoy_official': ('新建商品房销售额累计同比', '%'),
}

ANNUAL_SALES_INDICATOR = 'sales_area_annual_official'


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_housing_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS housing_city_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        city TEXT, period TEXT, indicator_code TEXT, value REAL,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, updated_at TEXT,
        UNIQUE(city, period, indicator_code)
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS housing_national_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, period TEXT, value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_url TEXT, parser_notes TEXT, updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_housing_city_period ON housing_city_observations(period, indicator_code)')
    conn.commit()


def load_nbs_annual_sales_history(path=ANNUAL_SALES_HISTORY_PATH):
    """Load the checked-in official annual sales-area source table.

    The annual observations are deliberately kept separate from the monthly
    cumulative series.  In particular, an annual point is not expanded into
    twelve monthly observations and therefore cannot silently enter monthly
    comparisons or lead/lag calculations.
    """
    records = []
    with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            period = str(row.get('period') or '').strip()
            value_text = str(row.get('value') or '').strip().replace(',', '')
            if not re.fullmatch(r'(?:19|20)\d{2}-12', period) or not value_text:
                continue
            records.append({
                'period': period,
                'value': float(value_text),
                'source_url': str(row.get('source_url') or '').strip(),
                'source_title': str(row.get('source_title') or '').strip(),
                'parser_notes': str(row.get('parser_notes') or '').strip(),
            })
    return records


def seed_housing_annual_sales_history(conn, records=None, updated_at=None):
    """Upsert official annual sales-area history and monthly year-end points.

    ``records`` is injectable for tests.  Existing monthly December cumulative
    observations are copied to the annual indicator for 2015 onward, so the
    long series stays current without splitting or re-estimating months.
    """
    records = load_nbs_annual_sales_history() if records is None else list(records)
    updated_at = updated_at or datetime.now().isoformat()
    upserted = 0
    static_periods = set()
    for row in records:
        period = row['period']
        static_periods.add(period)
        cur = conn.execute('''INSERT INTO housing_national_observations
            (indicator_code,period,value,unit,frequency,data_status,source_name,source_url,parser_notes,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period) DO UPDATE SET
              value=excluded.value, unit=excluded.unit, frequency=excluded.frequency,
              data_status=excluded.data_status, source_name=excluded.source_name,
              source_url=excluded.source_url, parser_notes=excluded.parser_notes,
              updated_at=excluded.updated_at''',
            (ANNUAL_SALES_INDICATOR, period, row['value'], '万平方米', 'annual',
             'official', NBS_SOURCE, row['source_url'],
             row['parser_notes'] or '国家统计局官方年度销售面积；年度点不拆分为月度。',
             updated_at))
        upserted += cur.rowcount

    # December YTD is the official annual total for the modern monthly series.
    # Do not overwrite a checked-in historical annual record if sources ever
    # overlap; the explicit annual source remains authoritative for that year.
    monthly_rows = conn.execute('''SELECT period, value, source_url, parser_notes
        FROM housing_national_observations
        WHERE indicator_code='sales_area_ytd' AND substr(period, 6, 2)='12'
        ORDER BY period''').fetchall()
    for row in monthly_rows:
        period, value, source_url, parser_notes = row[0], row[1], row[2], row[3]
        if period in static_periods:
            continue
        note = '年末点从月度累计官方新闻稿同步；' + (parser_notes or '')
        cur = conn.execute('''INSERT INTO housing_national_observations
            (indicator_code,period,value,unit,frequency,data_status,source_name,source_url,parser_notes,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period) DO UPDATE SET
              value=excluded.value, unit=excluded.unit, frequency=excluded.frequency,
              data_status=excluded.data_status, source_name=excluded.source_name,
              source_url=excluded.source_url, parser_notes=excluded.parser_notes,
              updated_at=excluded.updated_at''',
            (ANNUAL_SALES_INDICATOR, period, value, '万平方米', 'annual',
             'official', NBS_SOURCE, source_url, note, updated_at))
        upserted += cur.rowcount
    return {'rows_upserted': upserted, 'static_rows': len(records),
            'year_end_rows': len([row for row in monthly_rows if row[0] not in static_periods])}


# ── 解析(可单测) ──────────────────────────────────────────────────────────────
def _norm_city(s):
    normalized = re.sub(r'[\s　]', '', s or '')
    return re.sub(r'[*＊#＃]+$', '', normalized)


def _month_number(period):
    text = str(period)[:7]
    return int(text[:4]) * 12 + int(text[5:7])


def _period_from_month_number(month):
    year, month_index = divmod(month - 1, 12)
    return f'{year:04d}-{month_index + 1:02d}'


def build_equal_weighted_price_index(rows):
    """Chain the equal-weighted 70-city monthly mom index, base=100.

    A missing calendar month breaks the chain instead of being bridged. The
    first observation after a break starts a new indexed segment at 100.
    ``rows`` must contain period, city and value fields.
    """
    buckets = {}
    for row in rows or []:
        if row.get('value') is None:
            continue
        period = str(row['period'])[:7]
        buckets.setdefault(period, []).append(float(row['value']))

    result, previous_month, current_index = [], None, None
    if not buckets:
        return result
    first_month = min(_month_number(period) for period in buckets)
    last_month = max(_month_number(period) for period in buckets)
    for month in range(first_month, last_month + 1):
        period = _period_from_month_number(month)
        values = buckets.get(period)
        if not values:
            result.append({'period': period, 'index': None,
                           'average_mom_idx': None, 'city_count': 0})
            previous_month = month
            current_index = None
            continue
        average_mom = sum(values) / len(values)
        contiguous = previous_month is not None and month == previous_month + 1
        if previous_month is None:
            current_index = 100.0
        elif not contiguous:
            # Keep the observation for coverage/QA, but make the visual break.
            current_index = None
        elif current_index is None:
            current_index = 100.0
        else:
            current_index *= average_mom / 100.0
        result.append({'period': period,
                       'index': round(current_index, 4) if current_index is not None else None,
                       'average_mom_idx': round(average_mom, 4),
                       'city_count': len(values)})
        previous_month = month
    return result


def build_70city_composite_price_index(new_rows, second_rows):
    """Merge chained equal-weighted new/second-hand 70-city index series."""
    new = {row['period']: row for row in build_equal_weighted_price_index(new_rows)}
    second = {row['period']: row for row in build_equal_weighted_price_index(second_rows)}
    series = []
    for period in sorted(set(new) | set(second)):
        n, s = new.get(period), second.get(period)
        series.append({
            'period': period,
            'new_home_index': n['index'] if n else None,
            'second_home_index': s['index'] if s else None,
            'new_home_average_mom_idx': n['average_mom_idx'] if n else None,
            'second_home_average_mom_idx': s['average_mom_idx'] if s else None,
            'new_home_city_count': n['city_count'] if n else 0,
            'second_home_city_count': s['city_count'] if s else 0,
        })
    return series


def _national_monthly_momentum(series, value_key, months):
    """Return a monthly compound rate only when the trailing window is contiguous."""
    rows = [
        (row.get('period'), row.get(value_key))
        for row in (series or [])
        if row.get('period') and isinstance(row.get(value_key), (int, float))
    ]
    if len(rows) < int(months) + 1:
        return None
    start_period, start_value = rows[-int(months) - 1]
    end_period, end_value = rows[-1]
    if (_month_number(end_period) - _month_number(start_period)) != int(months):
        return None
    if start_value <= 0 or end_value <= 0:
        return None
    rate = ((float(end_value) / float(start_value)) ** (1.0 / int(months)) - 1.0) * 100.0
    return round(rate, 4)


def _national_projection_path(period, value, monthly_rate, horizon_months):
    path = []
    current = float(value)
    for step in range(1, int(horizon_months) + 1):
        current *= 1.0 + float(monthly_rate) / 100.0
        path.append({'period': _period_from_month_number(_month_number(period) + step),
                     'value': round(current, 4)})
    return path


def _national_price_component_scenarios(composite_series, value_key, target_index,
                                        end_period, scenario_keys):
    rows = [row for row in (composite_series or [])
            if row.get('period') and isinstance(row.get(value_key), (int, float))]
    if not rows:
        return {'status': 'missing', 'current': None, 'scenarios': {}, 'rates': {}}
    current = rows[-1]
    candidates = []
    for months in (6, 12, 36):
        rate = _national_monthly_momentum(composite_series, value_key, months)
        if rate is not None:
            candidates.append({'window_months': months, 'monthly_rate': rate})
    candidates.sort(key=lambda item: item['monthly_rate'], reverse=True)
    horizon = max(0, _month_number(end_period) - _month_number(current['period']))
    scenarios = {}
    for index, key in enumerate(scenario_keys):
        if index >= len(candidates):
            scenarios[key] = {'status': 'insufficient_history', 'key': key}
            continue
        candidate = candidates[index]
        path = _national_projection_path(current['period'], current[value_key],
                                          candidate['monthly_rate'], horizon)
        target_period = next((point['period'] for point in path
                              if point['value'] <= target_index), None)
        scenarios[key] = {
            'key': key, 'status': 'ok', 'window_months': candidate['window_months'],
            'monthly_rate': candidate['monthly_rate'],
            'annualised': round((1 + candidate['monthly_rate'] / 100.0) ** 12 * 100 - 100, 3),
            'path': path,
            'end_period': path[-1]['period'] if path else current['period'],
            'end_value': path[-1]['value'] if path else current[value_key],
            'target_index': target_index,
            'target_period': target_period,
        }
    return {
        'status': 'scenario' if any(item.get('status') == 'ok' for item in scenarios.values()) else 'missing',
        'current': {'period': current['period'], 'value': current[value_key]},
        'target_index': target_index, 'scenarios': scenarios,
        'rates': {key: {'monthly_rate': item.get('monthly_rate'),
                        'window_months': item.get('window_months'),
                        'annualised': item.get('annualised')}
                  for key, item in scenarios.items()},
    }


def build_national_housing_scenarios(annual_sales_rows, latest_sales_yoy,
                                     composite_series, target_year=2030):
    """Build transparent national sales/price paths through December target_year.

    Sales uses the latest official cumulative yoy as the base 2026 assumption.
    The improvement case narrows that decline by 5 percentage points in 2026
    and assumes +3% annual recovery from 2027; base holds the latest yoy and
    stress widens the decline by 5 percentage points.  Prices reuse the same
    trailing 6/12/36-month momentum ranking as the city scenario module.
    These are conditional scenario paths, never official observations.
    """
    annual = [dict(row) for row in (annual_sales_rows or [])
              if row.get('period') and isinstance(row.get('value'), (int, float))]
    annual.sort(key=lambda row: row['period'])
    if not annual or latest_sales_yoy is None:
        return {'data_status': 'missing', 'target_year': int(target_year),
                'sales': {'series': [], 'scenarios': {}},
                'price': {'series': [], 'scenarios': {}}}

    target_year = int(target_year)
    latest = annual[-1]
    first_forecast_year = int(latest['period'][:4]) + 1
    end_period = f'{target_year}-12'
    target_sales = next((row['value'] for row in annual if row['period'] == '2007-12'), None)
    yoy = float(latest_sales_yoy)
    sales_definitions = {
        'optimistic': {
            'label': '改善/修复', 'rate_2026': yoy + 5.0,
            'rate_after_2026': 3.0,
            'assumption': '2026年同比跌幅收窄5个百分点，2027年起年增长3%。',
        },
        'base': {
            'label': '基准', 'rate_2026': yoy,
            'rate_after_2026': yoy,
            'assumption': '最新官方累计同比在预测期内保持。',
        },
        'stress': {
            'label': '压力', 'rate_2026': yoy - 5.0,
            'rate_after_2026': yoy - 5.0,
            'assumption': '最新官方累计同比再恶化5个百分点并保持。',
        },
    }
    sales_series = [{
        'period': row['period'], 'actual': row['value'],
        'target_2007': target_sales,
    } for row in annual]
    sales_scenarios = {}
    for key, definition in sales_definitions.items():
        value = float(latest['value'])
        forecast = []
        for year in range(first_forecast_year, target_year + 1):
            rate = definition['rate_2026'] if year == first_forecast_year else definition['rate_after_2026']
            value *= 1.0 + rate / 100.0
            point = {'period': f'{year}-12', 'value': round(value, 2), 'rate': rate}
            forecast.append(point)
            sales_series.append({
                'period': point['period'], key: point['value'],
                'target_2007': target_sales,
            })
        target_period = next((point['period'] for point in forecast
                              if target_sales is not None and point['value'] <= target_sales), None)
        sales_scenarios[key] = {
            'key': key, 'label': definition['label'], 'data_status': 'scenario',
            'rate_2026': definition['rate_2026'],
            'rate_after_2026': definition['rate_after_2026'],
            'assumption': definition['assumption'], 'path': forecast,
            'target_2007': target_sales, 'target_period': target_period,
            'end_value': forecast[-1]['value'] if forecast else latest['value'],
        }
    # Merge repeated period rows created by the three scenario paths.
    merged = {}
    for row in sales_series:
        merged.setdefault(row['period'], {'period': row['period']}).update(row)
    sales_series = [merged[period] for period in sorted(merged)]

    price_series = []
    price_rows = [row for row in (composite_series or [])
                  if isinstance(row.get('new_home_index'), (int, float))
                  and isinstance(row.get('second_home_index'), (int, float))]
    for row in price_rows[-13:]:
        price_series.append({
            'period': row['period'], 'new_actual': row['new_home_index'],
            'second_actual': row['second_home_index'], 'target_100': 100.0,
        })
    new_component = _national_price_component_scenarios(
        composite_series, 'new_home_index', 100.0, end_period,
        ('optimistic', 'base', 'stress'))
    second_component = _national_price_component_scenarios(
        composite_series, 'second_home_index', 100.0, end_period,
        ('optimistic', 'base', 'stress'))
    path_by_period = {row['period']: row for row in price_series}
    for component_name, component in (('new', new_component), ('second', second_component)):
        for key, scenario in component.get('scenarios', {}).items():
            for point in scenario.get('path') or []:
                path_by_period.setdefault(point['period'], {'period': point['period'],
                                                              'target_100': 100.0})[
                    f'{component_name}_{key}'] = point['value']
    for row in path_by_period.values():
        row.setdefault('target_100', 100.0)
    price_series = [path_by_period[period] for period in sorted(path_by_period)]
    return {
        'data_status': 'scenario', 'target_year': target_year,
        'latest_period': latest['period'],
        'sales': {
            'data_status': 'scenario', 'latest_period': latest['period'],
            'latest_actual': latest['value'],
            'latest_official_yoy': yoy, 'target_2007': target_sales,
            'series': sales_series, 'scenarios': sales_scenarios,
            'method': '2026年以最新官方累计同比为锚；改善/基准/压力分别为同比+5pp、原值、同比-5pp；改善情景2027年起假设年增长3%。',
        },
        'price': {
            'data_status': 'scenario', 'latest_period': price_rows[-1]['period'] if price_rows else None,
            'target_index': 100.0, 'series': price_series,
            'components': {'new': new_component, 'second': second_component},
            'method': '70城等权链式指数沿用近6/12/36个月复合月速，按速度排序为乐观/基准/压力，固定外推至2030年12月。',
        },
        'caveats': [
            '全部未来点为 scenario，不是官方观测，也不是概率预测。',
            '销售面积2026年仍是年中累计值，年度路径将其按官方最新累计同比外推到年末。',
            '房价目标100是70城等权指数首个连续期（2011-01）=100的低位代理，不是可与旧制度2010年逐城值直接拼接的官方序列。',
            '改善情景需要销售跌幅收窄后真正恢复增长；仅仅跌得慢仍可能跌破2007年水平。',
        ],
    }


def parse_period_from_title(title):
    m = re.search(r'(20\d{2})年(\d{1,2})月份?70个大中城市', title or '')
    return f'{m.group(1)}-{int(m.group(2)):02d}' if m else None


def parse_sales_period_from_title(title):
    """房地产销售新闻稿标题 -> 累计截止月；1-2月合并只记 02。"""
    text = unicodedata.normalize('NFKC', title or '').replace('—', '-').replace('–', '-')
    match = re.search(r'(20\d{2})年1\s*-\s*(\d{1,2})月', text)
    if match:
        return f'{match.group(1)}-{int(match.group(2)):02d}'
    match = re.search(
        r'^(20\d{2})年(?:全国)?(?:房地产开发(?:投资)?和销售情况|房地产市场基本情况)', text)
    if not match:
        match = re.search(r'^(20\d{2})年全国房地产开发投资(?:增长|下降)', text)
    return f'{match.group(1)}-12' if match else None


def _normalise_sales_text(text):
    value = unicodedata.normalize('NFKC', BeautifulSoup(text or '', 'html.parser').get_text(' '))
    value = value.replace('—', '-').replace('–', '-').replace(',', '')
    return re.sub(r'\s+', '', value)


def parse_sales_article(text):
    """统计局房地产新闻稿 -> 四个销售累计字段；只取总计，不取住宅子项。"""
    result = {}
    specs = (
        ('sales_area_ytd', 'sales_area_ytd_yoy_official', '销售面积', '万平方米'),
        ('sales_value_ytd', 'sales_value_ytd_yoy_official', '销售额', '亿元'),
    )

    # Prefer the national-total table: it is more precise than prose such as
    # "增长 1.05 倍" and prevents a later regional subtotal from matching.
    soup = BeautifulSoup(text or '', 'html.parser')
    for row in soup.find_all('tr'):
        cells = [unicodedata.normalize('NFKC', cell.get_text(' ', strip=True))
                 for cell in row.find_all(['td', 'th'])]
        cells = [re.sub(r'[\s,]', '', cell) for cell in cells]
        if len(cells) < 3:
            continue
        for level_code, yoy_code, label, unit in specs:
            if (re.fullmatch(rf'(?:新建)?商品房{label}\({unit}\)', cells[0])
                    and re.fullmatch(r'-?[\d.]+', cells[1])
                    and re.fullmatch(r'-?[\d.]+', cells[2])):
                result[level_code] = float(cells[1])
                result[yoy_code] = float(cells[2])

    normalized = _normalise_sales_text(text)
    for level_code, yoy_code, label, unit in specs:
        if level_code in result and yoy_code in result:
            continue
        pattern = (rf'(?:新建)?商品房{label}(?:为)?([\d.]+){unit}'
                   rf'[^。；;]{{0,28}}?(?:(?:同比|比上年(?:同期)?))?'
                   rf'(增长|上升|下降)([\d.]+)(%|倍)')
        match = re.search(pattern, normalized)
        if not match:
            continue
        direction, yoy_value, suffix = match.group(2), float(match.group(3)), match.group(4)
        if suffix == '倍':
            yoy_value *= 100
        result[level_code] = float(match.group(1))
        result[yoy_code] = round((-1 if direction == '下降' else 1) * yoy_value, 4)
    return result


def _is_sales_release_title(title):
    normalized = unicodedata.normalize('NFKC', title or '').replace('—', '-').replace('–', '-')
    standard = re.fullmatch(
        r'20\d{2}年(?:1-\d{1,2}月份?)?(?:全国)?房地产(?:开发(?:投资)?和销售情况|市场基本情况)',
        normalized.strip())
    headline = re.fullmatch(
        r'20\d{2}年(?:1-\d{1,2}月份?)?全国房地产开发投资(?:增长|下降)[\d.]+%',
        normalized.strip())
    return bool(standard or headline)


def _is_num(s):
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def parse_dual_column_table(table):
    """70城主表:每行两组 [城市,环比,同比,(均值)]。
    扫描式解析:在单元格序列里找 [城市名, 数, 数] 模式——对不同期数的
    空单元格/错位(如 2026-01 版式)免疫,不依赖固定步长。"""
    out = {}
    for tr in table.find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
        i = 0
        while i < len(cells) - 2:
            city = _norm_city(cells[i])
            if (re.match(r'^[一-龥]{2,6}$', city) and city != '城市'
                    and _is_num(cells[i + 1]) and _is_num(cells[i + 2])):
                out[city] = (float(cells[i + 1]), float(cells[i + 2]))
                i += 3
            else:
                i += 1
    return out


def parse_70city_article(html):
    """月报正文 → {'new': {city:(mom,yoy)}, 'second': {...}}。
    两种官方版式自适应:
      A) 表0=新建(70城双列)、表1=二手(70城双列)——常见版式;
      B) 70城拆成两张 35 城表:表0+表1=新建、表2+表3=二手(如 2026-01 期)。
    识别依据:若表0与表1城市集合不相交(各~35城),则为版式B合并。"""
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    if len(tables) < 2:
        raise ValueError(f'70城月报表格数异常: {len(tables)}')

    # 2011 年旧版同页包含“新建住宅 / 新建商品住宅 / 二手住宅”三张主表，
    # 且桌面/移动版重复；必须按表题选主表，不能把第 2 张新房表误当二手表。
    labelled = {'new': [], 'second': []}
    for table in tables:
        heading_rows = table.find_all('tr')[:3]
        # Some releases (notably 2018-01/02) put the table caption in the
        # paragraph immediately before a wrapping <div>, rather than in the
        # table itself. Include that nearby context before classifying tables.
        heading_parts = [row.get_text(' ', strip=True) for row in heading_rows]
        for node in (table, table.parent):
            previous = node.find_previous_sibling() if node else None
            if previous is not None:
                heading_parts.insert(0, previous.get_text(' ', strip=True))
        heading = re.sub(r'[\s　]', '', ' '.join(heading_parts))
        if '分类指数' in heading:
            continue
        parsed_table = parse_dual_column_table(table)
        if len(parsed_table) < 30:
            continue
        if '二手住宅价格指数' in heading or '二手住宅销售价格指数' in heading:
            labelled['second'].append(parsed_table)
        elif ('新建商品住宅价格指数' in heading
              or '新建商品住宅销售价格指数' in heading):
            labelled['new'].append(parsed_table)

    def merge_labelled(parts):
        merged = {}
        for part in parts:
            merged.update(part)
        return merged

    labelled_new = merge_labelled(labelled['new'])
    labelled_second = merge_labelled(labelled['second'])
    if len(labelled_new) == 70 and len(labelled_second) == 70:
        return {'new': labelled_new, 'second': labelled_second}

    # 无可用表题时保留原版式兼容逻辑（含 35+35 拆表）。
    parsed = [parse_dual_column_table(t) for t in tables[:4]]
    t0, t1 = parsed[0], parsed[1]
    if len(t0) >= 60:                                    # 版式A
        new, second = t0, t1
    elif (len(t0) >= 30 and len(t1) >= 30 and not (set(t0) & set(t1))
          and len(parsed) >= 4):                          # 版式B:两半合并
        new = {**t0, **t1}
        second = {**parsed[2], **parsed[3]}
    else:
        raise ValueError(f'70城版式无法识别: 表城市数 {[len(x) for x in parsed]}')
    if len(new) != 70 or len(second) != 70:
        raise ValueError(f'70城解析城市数异常: 新房{len(new)} 二手{len(second)}')
    return {'new': new, 'second': second}


def _release_path_rank(url):
    if '/sj/zxfb/' in url:
        return 0
    if '/sj/zxfbhjd/' in url:
        return 1
    if '/xxgk/sjfb/' in url:
        return 2
    return 9


def extract_70city_search_releases(payload, start_year=2011, end_year=None):
    """从国家统计局官网所用站内搜索 JSON 中提取严格匹配的月报链接。"""
    end_year = int(end_year or datetime.now().year)
    pattern = re.compile(
        r'^(20\d{2})年(\d{1,2})月份?70个大中城市'
        r'(?:及\d{1,2}月(?:上|下)半月一线和热点二线城市)?'
        r'(?:商品)?住宅销售价格变动情况$')
    by_period = {}
    for doc in (payload or {}).get('resultDocs') or []:
        data = doc.get('data') or {}
        title = re.sub(r'<[^>]+>', '', data.get('titleO') or data.get('title') or '').strip()
        url = (data.get('url') or '').strip()
        match = pattern.fullmatch(title)
        if not match or not url.startswith('https://www.stats.gov.cn/'):
            continue
        year, month = int(match.group(1)), int(match.group(2))
        if not start_year <= year <= end_year or not 1 <= month <= 12:
            continue
        period = f'{year}-{month:02d}'
        candidate = (url, title)
        current = by_period.get(period)
        if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
            by_period[period] = candidate
    return [(period, *by_period[period]) for period in sorted(by_period, reverse=True)]


def discover_70city_history(start_year=2011, end_year=None, max_pages=30):
    """通过统计局官网内置政务搜索发现 2011 年以来的月报原文。"""
    end_year = int(end_year or datetime.now().year)
    found = {}
    headers = {**UA, 'Referer': 'https://www.stats.gov.cn/search/s'}
    for page in range(1, int(max_pages) + 1):
        response = requests.post(NBS_SEARCH_API, data={
            'siteCode': NBS_SEARCH_SITE_CODE,
            'qt': NBS_HISTORY_QUERY,
            'page': page,
            'pageSize': 20,
            'keyPlace': '1',
            'sort': 'dateDesc',
        }, headers=headers, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not payload.get('ok'):
            raise ValueError(f'统计局站内搜索失败: {payload.get("msg") or payload.get("code")}')
        for period, url, title in extract_70city_search_releases(
                payload, int(start_year), end_year):
            current = found.get(period)
            if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
                found[period] = (url, title)
        current_hits = int(payload.get('currentHits') or 0)
        total_hits = int(payload.get('totalHits') or 0)
        if not current_hits or page * 20 >= total_hits:
            break
        time.sleep(0.15)
    return [(url, title) for _, (url, title) in sorted(found.items(), reverse=True)]


def discover_70city_releases(max_pages=6):
    """最新发布列表(含 index_N.html 翻页) → [(url,title)],新在前,按 url 去重。"""
    seen, out = set(), []
    for i in range(max_pages):
        url = NBS_LIST_URL + ('index.html' if i == 0 else f'index_{i}.html')
        try:
            r = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                break
            r.encoding = 'utf-8'
        except Exception:
            break
        links = re.findall(r'href="([^"]+)"[^>]*>([^<]*70个大中城市商品住宅销售价格[^<]*)<', r.text)
        for href, title in links:
            if href.startswith('./'):
                href = NBS_LIST_URL + href[2:]
            elif href.startswith('/'):
                href = 'https://www.stats.gov.cn' + href
            if href not in seen:
                seen.add(href)
                out.append((href, title.strip()))
        time.sleep(0.4)
    return out


def extract_sales_search_releases(payload, start_year=2015, end_year=None):
    """从统计局官网搜索结果提取房地产销售月报，按累计截止月去重。"""
    end_year = int(end_year or datetime.now().year)
    found = {}
    for doc in (payload or {}).get('resultDocs') or []:
        data = doc.get('data') or {}
        title = re.sub(r'<[^>]+>', '', data.get('titleO') or data.get('title') or '').strip()
        url = (data.get('url') or '').strip()
        period = parse_sales_period_from_title(title)
        if (not period or not _is_sales_release_title(title)
                or not url.startswith('https://www.stats.gov.cn/')
                or not int(start_year) <= int(period[:4]) <= end_year):
            continue
        current = found.get(period)
        if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
            found[period] = (url, title)
    return [(period, *found[period]) for period in sorted(found, reverse=True)]


def discover_sales_history(start_year=2015, end_year=None, max_pages=30):
    """搜索两代官方标题，发现历史房地产开发与销售新闻稿。"""
    end_year = int(end_year or datetime.now().year)
    found = {}
    headers = {**UA, 'Referer': 'https://www.stats.gov.cn/search/s'}
    # The endpoint silently caps currentHits at 20 even when a larger pageSize
    # is requested; keep pagination arithmetic on the effective server cap.
    page_size = 20
    for year in range(int(end_year), int(start_year) - 1, -1):
        for base_query in NBS_SALES_QUERIES:
            query = f'{year}年{base_query}'
            for page in range(1, int(max_pages) + 1):
                response = requests.post(NBS_SEARCH_API, data={
                    'siteCode': NBS_SEARCH_SITE_CODE, 'qt': query, 'page': page,
                    'pageSize': page_size, 'keyPlace': '1', 'sort': 'relevance',
                }, headers=headers, timeout=HTTP_TIMEOUT)
                response.raise_for_status()
                payload = response.json()
                if not payload.get('ok'):
                    raise ValueError(f'统计局站内搜索失败: {payload.get("msg") or payload.get("code")}')
                for period, url, title in extract_sales_search_releases(payload, start_year, end_year):
                    current = found.get(period)
                    if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
                        found[period] = (url, title)
                if (not int(payload.get('currentHits') or 0)
                        or page * page_size >= int(payload.get('totalHits') or 0)):
                    break
                time.sleep(0.15)
    return [(url, title) for _, (url, title) in sorted(found.items(), reverse=True)]


def discover_sales_releases(max_pages=8):
    """从统计局发布列表发现近期房地产销售新闻稿。"""
    found = {}
    for index in range(max_pages):
        page_url = NBS_LIST_URL + ('index.html' if index == 0 else f'index_{index}.html')
        response = requests.get(page_url, headers=UA, timeout=HTTP_TIMEOUT)
        if response.status_code != 200:
            continue
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        for link in soup.find_all('a', href=True):
            title = link.get_text(' ', strip=True)
            if not _is_sales_release_title(title):
                continue
            href = link['href']
            if href.startswith('./'):
                href = NBS_LIST_URL + href[2:]
            elif href.startswith('/'):
                href = 'https://www.stats.gov.cn' + href
            period = parse_sales_period_from_title(title)
            if period:
                found[period] = (href, title)
        time.sleep(0.2)
    return [found[period] for period in sorted(found, reverse=True)]


def discover_sales_archive(start_year=2015, end_year=None, max_pages=90):
    """Deep-scan official release-list pages; covers headline-style 2022 releases missed by search."""
    end_year = int(end_year or datetime.now().year)

    def fetch_page(index):
        page_url = NBS_LIST_URL + ('index.html' if index == 0 else f'index_{index}.html')
        try:
            response = requests.get(page_url, headers=UA, timeout=10)
            response.raise_for_status(); response.encoding = 'utf-8'
        except Exception:
            return []
        rows = []
        for link in BeautifulSoup(response.text, 'html.parser').find_all('a', href=True):
            title = link.get_text(' ', strip=True)
            period = parse_sales_period_from_title(title)
            if not period or not _is_sales_release_title(title):
                continue
            if not int(start_year) <= int(period[:4]) <= end_year:
                continue
            href = link['href']
            if href.startswith('./'):
                href = NBS_LIST_URL + href[2:]
            elif href.startswith('/'):
                href = 'https://www.stats.gov.cn' + href
            rows.append((period, href, title))
        return rows

    found = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for rows in executor.map(fetch_page, range(int(max_pages))):
            for period, url, title in rows:
                found[period] = (url, title)
    return [found[period] for period in sorted(found, reverse=True)]


def _upsert_sales_release(conn, values, period, url, updated_at):
    upserted = 0
    for code, value in values.items():
        if code not in SALES_INDICATORS:
            continue
        name, unit = SALES_INDICATORS[code]
        cursor = conn.execute('''INSERT INTO housing_national_observations
            (indicator_code,period,value,unit,frequency,data_status,source_name,source_url,parser_notes,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period) DO UPDATE SET
              value=excluded.value, updated_at=excluded.updated_at''',
            (code, period, value, unit, 'monthly', 'official', NBS_SOURCE, url,
             f'{name}；解析自国家统计局新闻稿；累计同比按统计局可比口径公布。', updated_at))
        upserted += cursor.rowcount
    return upserted


def backfill_housing_sales_history(db_path, start_year=2015, end_year=None,
                                   sleep_seconds=0.4, max_search_pages=30, workers=4):
    """回填房地产销售累计值与官方同比；失败保留旧数据并如实返回。"""
    started = datetime.now().isoformat()
    releases = discover_sales_history(start_year, end_year, max_search_pages)
    if int(start_year) <= 2022:
        combined = {parse_sales_period_from_title(title): (url, title) for url, title in releases}
        for url, title in discover_sales_archive(start_year, end_year):
            combined[parse_sales_period_from_title(title)] = (url, title)
        releases = [combined[key] for key in sorted(combined, reverse=True) if key]
    errors, upserted, ok = [], 0, 0
    annual_seed = {'rows_upserted': 0, 'static_rows': 0, 'year_end_rows': 0}
    with connect(db_path) as conn:
        ensure_housing_tables(conn)
        try:
            annual_seed = seed_housing_annual_sales_history(conn)
            conn.commit()
        except Exception as exc:
            errors.append(f'年度销售面积历史载入失败: {exc}')
        pending = []
        for url, title in releases:
            period = parse_sales_period_from_title(title)
            existing = conn.execute('''SELECT COUNT(*) FROM housing_national_observations
                WHERE period=? AND indicator_code IN (?,?,?,?)''',
                (period, *SALES_INDICATORS)).fetchone()[0]
            if existing == len(SALES_INDICATORS):
                continue
            pending.append((period, url, title))

        def fetch_sales(item):
            period, url, title = item
            response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
            response.raise_for_status(); response.encoding = 'utf-8'
            values = parse_sales_article(response.text)
            if not values:
                raise ValueError('未解析到商品房销售面积或销售额')
            return values

        with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 4))) as executor:
            future_map = {executor.submit(fetch_sales, item): item for item in pending}
            for future in as_completed(future_map):
                period, url, title = future_map[future]
                try:
                    values = future.result()
                    upserted += _upsert_sales_release(
                        conn, values, period, url, datetime.now().isoformat())
                    conn.commit(); ok += 1
                except Exception as exc:
                    errors.append(f'{period} {title[:32]}: {exc}')
                if sleep_seconds:
                    time.sleep(float(sleep_seconds))
        coverage = conn.execute('''SELECT COUNT(DISTINCT period),MIN(period),MAX(period)
            FROM housing_national_observations WHERE indicator_code='sales_area_ytd_yoy_official' ''').fetchone()
    return {'success': ok > 0 or bool(coverage[0]) or annual_seed['static_rows'] > 0,
            'records_upserted': upserted, 'annual_history_upserted': annual_seed['rows_upserted'],
            'annual_history_static_rows': annual_seed['static_rows'],
            'annual_history_year_end_rows': annual_seed['year_end_rows'],
            'releases_found': len(releases), 'releases_ok': ok,
            'coverage_periods': coverage[0], 'coverage_start': coverage[1], 'coverage_end': coverage[2],
            'errors': errors[:20], 'started_at': started, 'finished_at': datetime.now().isoformat()}


def _fetch_70city_article(url):
    response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    response.encoding = 'utf-8'
    return parse_70city_article(response.text)


def _upsert_70city_release(conn, data, period, url, title, updated_at):
    upserted = 0
    for kind, code_mom, code_yoy in [
            ('new', 'new_home_mom_idx', 'new_home_yoy_idx'),
            ('second', 'second_home_mom_idx', 'second_home_yoy_idx')]:
        for city, (mom, yoy) in data[kind].items():
            for code, value in ((code_mom, mom), (code_yoy, yoy)):
                cur = conn.execute('''INSERT INTO housing_city_observations
                    (city,period,indicator_code,value,data_status,source_name,source_type,
                     source_url,source_title,parser_notes,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(city,period,indicator_code) DO UPDATE SET
                      value=excluded.value, source_url=excluded.source_url,
                      source_title=excluded.source_title, parser_notes=excluded.parser_notes,
                      updated_at=excluded.updated_at''',
                    (city, period, code, value, 'official', NBS_SOURCE, SOURCE_TYPE,
                     url, title, '解析自统计局70城月报正文；按表题识别新建商品住宅/二手住宅主表',
                     updated_at))
                upserted += cur.rowcount
    return upserted


def backfill_housing_city_history(db_path, start_year=2011, end_year=None,
                                  sleep_seconds=0.5, max_search_pages=30, workers=1):
    """一次性回填现行 70 城逐城指数；2010 旧制度不混入该表。"""
    started = datetime.now().isoformat()
    end_year = int(end_year or datetime.now().year)
    releases = discover_70city_history(start_year, end_year, max_search_pages)
    errors = []
    counters = {'records_upserted': 0, 'releases_ok': 0,
                'releases_skipped_complete': 0, 'releases_failed': 0}
    actual_coverage = (None, None)
    with connect(db_path) as conn:
        ensure_housing_tables(conn)
        pending = []
        for url, title in releases:
            period = parse_period_from_title(title)
            if not period:
                continue
            existing = conn.execute('''SELECT COUNT(*) FROM housing_city_observations
                WHERE period=?''', (period,)).fetchone()[0]
            if existing >= 280:
                counters['releases_skipped_complete'] += 1
                continue
            pending.append((period, url, title))

        def store_result(item, data=None, error=None):
            period, url, title = item
            if error is not None:
                counters['releases_failed'] += 1
                errors.append(f'{period} {title[:30]}: {error}')
                return
            now = datetime.now().isoformat()
            counters['records_upserted'] += _upsert_70city_release(
                conn, data, period, url, title, now)
            counters['releases_ok'] += 1
            conn.commit()

        workers = max(1, min(int(workers), 4))
        if workers == 1:
            for index, item in enumerate(pending):
                if index and sleep_seconds > 0:
                    time.sleep(float(sleep_seconds))
                try:
                    store_result(item, _fetch_70city_article(item[1]))
                except Exception as exc:
                    store_result(item, error=exc)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {
                    executor.submit(_fetch_70city_article, url): (period, url, title)
                    for period, url, title in pending
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    try:
                        store_result(item, future.result())
                    except Exception as exc:
                        store_result(item, error=exc)
        actual_coverage = conn.execute('''SELECT MIN(period), MAX(period)
            FROM housing_city_observations WHERE period BETWEEN ? AND ?''',
            (f'{int(start_year)}-01', f'{end_year}-12')).fetchone()
    return {
        'success': counters['releases_ok'] > 0 or counters['releases_skipped_complete'] > 0,
        **counters,
        'releases_found': len(releases),
        'coverage_start': actual_coverage[0],
        'coverage_end': actual_coverage[1],
        'errors': errors[:20],
        'started_at': started,
        'finished_at': datetime.now().isoformat(),
    }


# ── 更新 ──────────────────────────────────────────────────────────────────────
def update_housing_prices(db_path):
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    annual_seed = {'rows_upserted': 0, 'static_rows': 0, 'year_end_rows': 0}
    releases = discover_70city_releases()
    try:
        sales_releases = discover_sales_releases()
    except Exception as exc:
        # Sales discovery is additive: a temporary NBS failure must not block
        # the existing 70-city/BIS refresh or delete previously stored sales.
        sales_releases = []
        errors.append(f'商品房销售新闻稿发现失败: {exc}')
    with connect(db_path) as conn:
        ensure_housing_tables(conn)
        now = datetime.now().isoformat()
        # 1) 统计局 70城(只抓库里没有的期数)
        for url, title in releases:
            period = parse_period_from_title(title)
            if not period:
                continue
            n = conn.execute('SELECT COUNT(*) FROM housing_city_observations WHERE period=?', (period,)).fetchone()[0]
            if n >= 280:      # 70城×4指标=280；不完整月份必须重抓
                continue
            try:
                data = _fetch_70city_article(url)
            except Exception as exc:
                errors.append(f'{title[:40]}: {exc}')
                continue
            upserted += _upsert_70city_release(conn, data, period, url, title, now)
            time.sleep(0.5)
        # 2) 全国房地产销售累计与官方可比口径同比
        for url, title in sales_releases:
            period = parse_sales_period_from_title(title)
            if not period:
                continue
            existing = conn.execute('''SELECT COUNT(*) FROM housing_national_observations
                WHERE period=? AND indicator_code IN (?,?,?,?)''',
                (period, *SALES_INDICATORS)).fetchone()[0]
            if existing == len(SALES_INDICATORS):
                continue
            try:
                response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
                response.raise_for_status(); response.encoding = 'utf-8'
                values = parse_sales_article(response.text)
                if not values:
                    raise ValueError('未解析到商品房销售面积或销售额')
                upserted += _upsert_sales_release(conn, values, period, url, now)
            except Exception as exc:
                errors.append(f'{title[:40]}: {exc}')
            time.sleep(0.3)
        try:
            annual_seed = seed_housing_annual_sales_history(conn, updated_at=now)
            upserted += annual_seed['rows_upserted']
        except Exception as exc:
            errors.append(f'年度销售面积历史载入失败: {exc}')
        # 3) BIS 长指数(FRED 免 key,幂等全量)
        for fred_id, name, kind in FRED_SERIES:
            try:
                r = requests.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}',
                                 headers=UA, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                lines = r.text.strip().splitlines()[1:]
            except Exception as exc:
                errors.append(f'{fred_id}: {exc}')
                continue
            for line in lines:
                parts = line.split(',')
                if len(parts) < 2 or parts[1].strip() in ('', '.'):
                    continue
                cur = conn.execute('''INSERT INTO housing_national_observations
                    (indicator_code,period,value,unit,frequency,data_status,source_name,source_url,parser_notes,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(indicator_code,period) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at''',
                    (fred_id, parts[0].strip(), float(parts[1]), '指数(2010=100)', 'quarterly',
                     'official', 'BIS via FRED', f'https://fred.stlouisfed.org/series/{fred_id}',
                     name, now))
                upserted += cur.rowcount
        conn.commit()
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'annual_history_upserted': annual_seed['rows_upserted'],
            'annual_history_static_rows': annual_seed['static_rows'],
            'annual_history_year_end_rows': annual_seed['year_end_rows'],
            'releases_found': len(releases), 'sales_releases_found': len(sales_releases),
            'errors': errors[:8]}


# ── payload ───────────────────────────────────────────────────────────────────
def build_housing_payload(db_path):
    with closing(connect(db_path)) as conn:
        ensure_housing_tables(conn)
        latest = conn.execute('SELECT MAX(period) FROM housing_city_observations').fetchone()[0]
        cards, breadth, table_rows, city_series = [], None, [], {}
        if latest:
            rows = [dict(r) for r in conn.execute(
                'SELECT * FROM housing_city_observations WHERE period=?', (latest,))]
            by_city = {}
            for r in rows:
                by_city.setdefault(r['city'], {'city': r['city'], 'source_url': r['source_url']})[r['indicator_code']] = r['value']
            src = rows[0] if rows else {}
            # 一线城市卡片
            for city in TIER1:
                d = by_city.get(city, {})
                cards.append({'label': f'{city} 新房环比', 'value': d.get('new_home_mom_idx'),
                              'unit': '上月=100', 'period': latest, 'data_status': 'official' if d else 'missing',
                              'source_name': NBS_SOURCE, 'source_url': d.get('source_url'),
                              'extra': {'新房同比': d.get('new_home_yoy_idx'),
                                        '二手环比': d.get('second_home_mom_idx'),
                                        '二手同比': d.get('second_home_yoy_idx')}})
            # 涨跌家数(derived)
            moms = [d.get('new_home_mom_idx') for d in by_city.values() if d.get('new_home_mom_idx') is not None]
            if moms:
                breadth = {'period': latest, 'data_status': 'derived',
                           'formula': 'count(city where new_home_mom_idx >/=/< 100)',
                           'up': sum(1 for v in moms if v > 100), 'flat': sum(1 for v in moms if v == 100),
                           'down': sum(1 for v in moms if v < 100), 'total': len(moms),
                           'source_url': src.get('source_url')}
            table_rows = sorted(by_city.values(), key=lambda x: -(x.get('new_home_yoy_idx') or 0))
        # 一线城市历史序列(新房同比,随月份累积)
        for city in TIER1:
            city_series[city] = [dict(r) for r in conn.execute(
                """SELECT period, value FROM housing_city_observations
                   WHERE city=? AND indicator_code='new_home_yoy_idx' ORDER BY period""", (city,))]
        national = {}
        for fred_id, name, kind in FRED_SERIES:
            national[fred_id] = [dict(r) for r in conn.execute(
                'SELECT period, value FROM housing_national_observations WHERE indicator_code=? ORDER BY period',
                (fred_id,))]
        composite_rows = {}
        for indicator in ('new_home_mom_idx', 'second_home_mom_idx'):
            composite_rows[indicator] = [dict(r) for r in conn.execute(
                'SELECT city, period, value FROM housing_city_observations '
                'WHERE indicator_code=? AND value IS NOT NULL ORDER BY period, city',
                (indicator,))]
        composite_series = build_70city_composite_price_index(
            composite_rows['new_home_mom_idx'], composite_rows['second_home_mom_idx'])
        composite_valid = [row for row in composite_series
                           if row['new_home_index'] is not None
                           or row['second_home_index'] is not None]
        composite_complete = [row for row in composite_series
                              if row['new_home_index'] is not None
                              and row['second_home_index'] is not None]
        national_composite = {
            'data_status': 'derived' if composite_complete else 'missing',
            'series': composite_series,
            'latest_period': composite_complete[-1]['period'] if composite_complete else None,
            'coverage': {
                'earliest': composite_valid[0]['period'] if composite_valid else None,
                'latest': composite_valid[-1]['period'] if composite_valid else None,
                'complete_periods': len(composite_complete),
            },
            'method': ('每月对有值的70城新建商品住宅/二手住宅环比指数分别等权平均，'
                       '再链式累计，首个连续观测期=100；缺月不桥接。'),
            'notes': [
                '这是70城等权综合代理指数，不是统计局发布的全国价值加权新房/二手房价格指数。',
                '一手使用新建商品住宅环比指数，二手使用二手住宅环比指数；每月正常应为70城。',
                '指数用于比较走势，不代表全国成交金额或全国平均单价。',
            ],
        }
        cov_city = dict(conn.execute("""SELECT COUNT(DISTINCT period) periods, MIN(period) earliest, MAX(period) latest,
                                        COUNT(*) records FROM housing_city_observations""").fetchone())
        cov_nat = dict(conn.execute('SELECT COUNT(*) records, MIN(period) earliest, MAX(period) latest FROM housing_national_observations').fetchone())
        # 全国商品房销售(统计局官方累计,2015 起;只读,缺失置 missing 不补零)
        sales_codes = {'area': 'sales_area_ytd', 'area_yoy': 'sales_area_ytd_yoy_official',
                       'value': 'sales_value_ytd', 'value_yoy': 'sales_value_ytd_yoy_official'}
        sales_raw = {key: {r['period']: r['value'] for r in conn.execute(
            'SELECT period, value FROM housing_national_observations WHERE indicator_code=? ORDER BY period', (code,))}
            for key, code in sales_codes.items()}
        sales_periods = sorted(set(sales_raw['area']) | set(sales_raw['value']) |
                               set(sales_raw['area_yoy']) | set(sales_raw['value_yoy']))
        sales_area_periods = sorted(sales_raw['area'])
        annual_rows = [dict(r) for r in conn.execute('''SELECT period, value, source_url,
                data_status, parser_notes FROM housing_national_observations
                WHERE indicator_code=? ORDER BY period''', (ANNUAL_SALES_INDICATOR,))]
        annual_history = [{
            'period': row['period'], 'label_period': f"{row['period'][:4]}年",
            'value': row['value'], 'source_url': row['source_url'],
            'data_status': row['data_status'] or 'official', 'frequency': 'annual',
            'parser_notes': row['parser_notes'],
        } for row in annual_rows]
        if sales_periods or annual_history:
            sp = sales_periods[-1] if sales_periods else annual_history[-1]['period']
            sales = {
                'data_status': 'official', 'latest_period': sp,
                'cards': [
                    {'label': '销售面积累计', 'value': sales_raw['area'].get(sp), 'unit': '万平方米',
                     'yoy': sales_raw['area_yoy'].get(sp), 'period': sp},
                    {'label': '销售额累计', 'value': sales_raw['value'].get(sp), 'unit': '亿元',
                     'yoy': sales_raw['value_yoy'].get(sp), 'period': sp}],
                'series': [{'period': p, 'area_yoy': sales_raw['area_yoy'].get(p),
                            'value_yoy': sales_raw['value_yoy'].get(p)} for p in sales_periods],
                'area_series': [{'period': p, 'value': sales_raw['area'].get(p)}
                                for p in sales_area_periods],
                'annual_history': annual_history,
                'notes': ['累计同比为统计局官方可比口径;1-2月合并计入2月,不拆分。',
                          '销售面积/销售额为年初至今累计值,非当月值。',
                          '销售面积累计图显示实际累计规模，不是单月销售流量。',
                          '年度长序列从1991年起；2004年以前为实际销售统计口径，2005年起包括期房和现房合同面积；年度点不拆分为月度。']}
        else:
            sales = {'data_status': 'missing', 'latest_period': None, 'cards': [], 'series': [],
                     'area_series': [], 'annual_history': [],
                     'notes': ['暂无全国销售官方数据。']}
        latest_sales_yoy_period = next(
            (period for period in sorted(sales_raw['area_yoy'], reverse=True)
             if isinstance(sales_raw['area_yoy'].get(period), (int, float))),
            None)
        national_scenario = build_national_housing_scenarios(
            annual_history,
            sales_raw['area_yoy'].get(latest_sales_yoy_period),
            composite_series,
            target_year=2030,
        )
        if national_scenario.get('sales') is not None:
            national_scenario['sales']['latest_official_yoy_period'] = latest_sales_yoy_period
    return {
        'data_status': 'official' if latest else 'missing',
        'latest_period': latest, 'cards': cards, 'breadth': breadth,
        'city_table': table_rows, 'city_series': city_series, 'national': national,
        'national_composite': national_composite, 'sales': sales,
        'national_scenario': national_scenario,
        'coverage': {'nbs_70city': cov_city, 'bis_national': cov_nat},
        'source_pages': {'nbs': NBS_LIST_URL, 'fred': 'https://fred.stlouisfed.org/series/QCNR628BIS'},
        'warnings': [] if latest else ['尚未抓取;未生成 mock。'],
        'notes': ['70城指数为官方口径:环比上月=100、同比上年同月=100(100 以下即下跌)。',
                  '数据取自统计局月报正文表格(境外 IP 无法访问其 data API,新闻页可访问)。',
                  '现行逐城可比序列从 2011 年开始；2010 年旧制度仅有旧口径资料，不与现行逐城序列拼接。',
                  '不采用商业平台挂牌价(非成交口径);BIS 指数用于 2005 年以来长趋势。'],
    }
