# -*- coding: utf-8 -*-
"""中国实体经济月度指标:CPI、PPI、PMI(统计局官方新闻稿)。

来源:统计局月度新闻稿(www.stats.gov.cn,与 70 城/销售同一发布体系;
数据 API 对境外 IP 403,新闻稿页可访问)。发现走站内搜索 api.so-gov.cn。

指标(逐条 official + source_url):
- CN_CPI_YOY / CN_CPI_MOM         《X年X月份居民消费价格同比…》正文
- CN_PPI_YOY / CN_PPI_MOM         《X年X月份工业生产者出厂价格…》正文
- CN_PMI_MFG / CN_PMI_NONMFG / CN_PMI_COMP  《X年X月中国采购经理指数运行情况》正文

数据纪律:缺失如实缺(核心CPI不在新闻稿正文,不抓不估);失败不清旧数据;
幂等 upsert;"持平"解析为 0.0(官方措辞,非缺失)。
"""
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime

import requests

from services.housing_price_service import (
    NBS_SEARCH_API, NBS_SEARCH_SITE_CODE, UA, HTTP_TIMEOUT, _release_path_rank,
)

SOURCE_NAME = '国家统计局'
SOURCE_TYPE = 'china_macro'

INDICATORS = {
    'CN_CPI_YOY': ('居民消费价格(CPI)同比', '%', 'monthly'),
    'CN_CPI_MOM': ('居民消费价格(CPI)环比', '%', 'monthly'),
    'CN_PPI_YOY': ('工业生产者出厂价格(PPI)同比', '%', 'monthly'),
    'CN_PPI_MOM': ('工业生产者出厂价格(PPI)环比', '%', 'monthly'),
    'CN_PMI_MFG': ('制造业PMI', '%', 'monthly'),
    'CN_PMI_NONMFG': ('非制造业商务活动指数', '%', 'monthly'),
    'CN_PMI_COMP': ('综合PMI产出指数', '%', 'monthly'),
    'CN_IP_YOY': ('规模以上工业增加值当月同比(实际)', '%', 'monthly'),
    'CN_IP_YTD_YOY': ('规模以上工业增加值累计同比', '%', 'monthly'),
    'CN_RETAIL_YOY': ('社会消费品零售总额当月同比', '%', 'monthly'),
    'CN_RETAIL_YTD_YOY': ('社会消费品零售总额累计同比', '%', 'monthly'),
    'CN_FAI_YTD_YOY': ('固定资产投资(不含农户)累计同比', '%', 'monthly'),
    'CN_GDP_Q_NOMINAL': ('GDP单季现价总量', '亿元', 'quarterly'),
    'CN_GDP_Q_REAL_YOY': ('GDP单季不变价同比', '%', 'quarterly'),
    'CN_UNEMP_SURVEY': ('全国城镇调查失业率(当月)', '%', 'monthly'),
    'CN_TRADE_YOY': ('货物进出口总额当月同比', '%', 'monthly'),
    'CN_EXPORT_YOY': ('出口当月同比', '%', 'monthly'),
    'CN_IMPORT_YOY': ('进口当月同比', '%', 'monthly'),
}

# 标题→period:月度类兼容"X月份"与累计"1—X月份"(全角—)与"上半年";
# GDP 季度:一季度→03、二季度和上半年→06、三季度和前三季度→09、四季度和全年→12
_GDP_QUARTER = {'一季度': '03', '二季度和上半年': '06', '二季度': '06',
                '三季度和前三季度': '09', '三季度': '09',
                '四季度和全年': '12', '四季度': '12'}


def _month_period(title, keyword):
    m = re.match(r'^(20\d{2})年(?:1[—-](\d{1,2})月份?|(\d{1,2})月份?|上半年)' + keyword, title)
    if not m:
        return None
    if m.group(2):
        month = int(m.group(2))
    elif m.group(3):
        month = int(m.group(3))
    else:
        month = 6  # 上半年
    return f'{m.group(1)}-{month:02d}'


def _gdp_period(title):
    m = re.match(r'^(20\d{2})年(一季度|二季度和上半年|二季度|三季度和前三季度|三季度|四季度和全年|四季度)'
                 r'国内生产总值(?:[（(]GDP[）)])?初步核算结果', title)
    if not m:
        return None
    return f'{m.group(1)}-{_GDP_QUARTER[m.group(2)]}'


def _econ_period(title, url):
    """月度《X月份国民经济运行…》标题无年份:月取标题,年取URL路径(/202606/),
    跨年规则:标题月>URL月(如12月稿发在次年1月)则年减一。季度稿含年份直接解析。"""
    m = re.match(r'^(20\d{2})年(?:1[—-](\d{1,2})月份?|(\d{1,2})月份?|上半年|一季度|前三季度|全年)国民经济', title)
    if m:
        month = int(m.group(2) or m.group(3) or 0)
        if not month:
            month = {'上半年': 6, '一季度': 3, '前三季度': 9, '全年': 12}[
                re.search(r'(上半年|一季度|前三季度|全年)', title).group(1)]
        return f'{m.group(1)}-{month:02d}'
    m = re.match(r'^(?:1[—-](\d{1,2})|(\d{1,2}))月份国民经济', title)
    u = re.search(r'/(20\d{2})(\d{2})/t20', url or '')
    if not m or not u:
        return None
    month = int(m.group(1) or m.group(2))
    year = int(u.group(1))
    if month > int(u.group(2)):
        year -= 1
    return f'{year}-{month:02d}'


RELEASES = {
    'cpi': {'query': '居民消费价格',
            'period_fn': lambda t, u: _month_period(t, '居民消费价格')},
    'ppi': {'query': '工业生产者出厂价格',
            'period_fn': lambda t, u: _month_period(t, '工业生产者出厂价格')},
    'pmi': {'query': '中国采购经理指数运行情况',
            'period_fn': lambda t, u: _month_period(t, '中国采购经理指数运行情况')},
    'ip': {'query': '规模以上工业增加值',
           'period_fn': lambda t, u: _month_period(t, '规模以上工业增加值')},
    'retail': {'query': '社会消费品零售总额',
               'period_fn': lambda t, u: _month_period(t, '社会消费品零售总额')},
    'fai': {'query': '全国固定资产投资',
            'period_fn': lambda t, u: _month_period(t, '全国固定资产投资')},
    'gdp': {'query': '国内生产总值初步核算结果', 'period_fn': lambda t, u: _gdp_period(t)},
    'econ': {'query': '月份国民经济运行', 'period_fn': _econ_period, 'flat_pages': 25,
             'codes': ('CN_UNEMP_SURVEY', 'CN_TRADE_YOY', 'CN_EXPORT_YOY', 'CN_IMPORT_YOY')},
}


def _kind_codes(kind):
    spec = RELEASES[kind]
    if 'codes' in spec:
        return spec['codes']
    return tuple(c for c in INDICATORS if c.startswith(f'CN_{kind.upper()}'))


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_china_macro_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS china_macro_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT, indicator_name TEXT, period TEXT,
        value REAL, unit TEXT, frequency TEXT,
        data_status TEXT, source_name TEXT, source_type TEXT,
        source_url TEXT, source_title TEXT, parser_notes TEXT, formula TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_china_macro_code_period
                    ON china_macro_observations(indicator_code, period)''')
    conn.commit()


def _clean_text(html):
    return re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', html or ''))


def _signed(direction, number):
    """官方措辞定号:上涨/增长=+,下降=−;number 为字符串数值。"""
    return float(number) * (-1 if direction == '下降' else 1)


def _change(text, prefix):
    """解析 '<prefix>同比上涨X%' / '下降X%' / '持平' → (yoy, mom);未命中为 None。
    环比必须锚定:优先带前缀(现行措辞独立成句),否则只在同比命中位置后 80 字符窗口内找
    (早年措辞同比环比同句),绝不全篇任意匹配以免抓到分项数字。"""
    yoy = mom = None
    yoy_end = None
    m = re.search(prefix + r'同比(上涨|下降)([\d.]+)%', text)
    if m:
        yoy, yoy_end = _signed(m.group(1), m.group(2)), m.end()
    else:
        m = re.search(prefix + r'同比持平', text)
        if m:
            yoy, yoy_end = 0.0, m.end()
    m = re.search(prefix + r'环比(上涨|下降)([\d.]+)%', text)
    if m:
        mom = _signed(m.group(1), m.group(2))
    elif re.search(prefix + r'环比持平', text):
        mom = 0.0
    elif yoy_end is not None:
        window = text[yoy_end:yoy_end + 80]
        m = re.search(r'环比(上涨|下降)([\d.]+)%', window)
        if m:
            mom = _signed(m.group(1), m.group(2))
        elif re.search(r'环比持平', window):
            mom = 0.0
    return yoy, mom


def parse_cpi_article(html):
    text = _clean_text(html)
    yoy, mom = _change(text, r'全国居民消费价格(?:总水平)?')
    out = {}
    if yoy is not None:
        out['CN_CPI_YOY'] = yoy
    if mom is not None:
        out['CN_CPI_MOM'] = mom
    return out


def parse_ppi_article(html):
    text = _clean_text(html)
    yoy, mom = _change(text, r'全国工业生产者出厂价格')
    out = {}
    if yoy is not None:
        out['CN_PPI_YOY'] = yoy
    if mom is not None:
        out['CN_PPI_MOM'] = mom
    return out


def parse_pmi_article(html):
    text = _clean_text(html)
    out = {}
    m = re.search(r'制造业采购经理指数(?:[（(]PMI[）)])?为([\d.]+)%', text)
    if m:
        out['CN_PMI_MFG'] = float(m.group(1))
    m = re.search(r'非制造业商务活动指数为([\d.]+)%', text)
    if m:
        out['CN_PMI_NONMFG'] = float(m.group(1))
    m = re.search(r'综合PMI产出指数为([\d.]+)%', text)
    if m:
        out['CN_PMI_COMP'] = float(m.group(1))
    return out


def parse_ip_article(html):
    """工业增加值:当月为'同比实际增长X%'(实际=扣价格),累计为'1—X月份…同比增长X%'。"""
    text = _clean_text(html)
    out = {}
    m = re.search(r'规模以上工业增加值同比实际(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_IP_YOY'] = _signed(m.group(1), m.group(2))
    m = re.search(r'1[—-]\d{1,2}月份，?规模以上工业增加值同比(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_IP_YTD_YOY'] = _signed(m.group(1), m.group(2))
    return out


def parse_retail_article(html):
    """社零:当月'X月份，社会消费品零售总额…同比…';累计'1—X月份，…'。"""
    text = _clean_text(html)
    out = {}
    m = re.search(r'(?<![—-])\d{1,2}月份，社会消费品零售总额[\d.]+亿元，同比(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_RETAIL_YOY'] = _signed(m.group(1), m.group(2))
    m = re.search(r'1[—-]\d{1,2}月份，社会消费品零售总额[\d.]+亿元，同比(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_RETAIL_YTD_YOY'] = _signed(m.group(1), m.group(2))
    return out


def parse_fai_article(html):
    text = _clean_text(html)
    out = {}
    m = re.search(r'1[—-]\d{1,2}月份，全国固定资产投资（不含农户）[\d.]+亿元，'
                  r'同比(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_FAI_YTD_YOY'] = _signed(m.group(1), m.group(2))
    return out


def parse_gdp_article(html):
    """初步核算结果表1:行首 GDP,列为 绝对额(单季[,累计]) + 同比(单季[,累计])。
    Q1 两个数,其余季度四个数;取单季现价绝对额与单季不变价同比。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    for table in soup.find_all('table'):
        for tr in table.find_all('tr'):
            cells = [re.sub(r'\s+', '', td.get_text()) for td in tr.find_all(['td', 'th'])]
            if not cells or cells[0] != 'GDP':
                continue
            numbers = []
            for cell in cells[1:]:
                m = re.fullmatch(r'-?[\d.]+', cell)
                if m:
                    numbers.append(float(cell))
            if len(numbers) == 2:      # Q1:绝对额、同比
                return {'CN_GDP_Q_NOMINAL': numbers[0], 'CN_GDP_Q_REAL_YOY': numbers[1]}
            if len(numbers) >= 4:     # 单季+累计两列:取单季
                return {'CN_GDP_Q_NOMINAL': numbers[0], 'CN_GDP_Q_REAL_YOY': numbers[2]}
    return {}


def parse_econ_article(html):
    """月度国民经济运行稿:当月城镇调查失业率 + 货物贸易(总额同比、出口/进口各自同比)。
    贸易段先当月后累计:出口/进口取货物进出口总额句之后 120 字符窗内的第一对,防串到累计。
    海关总署站点对境外访问不可达,此处为统计局官方转述的海关数据。"""
    text = _clean_text(html)
    out = {}
    m = re.search(r'(?<![—-])\d{1,2}月份，?全国城镇调查失业率为([\d.]+)%', text)
    if m:
        out['CN_UNEMP_SURVEY'] = float(m.group(1))
    m = re.search(r'货物进出口总额[\d.]+亿元，同比(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_TRADE_YOY'] = _signed(m.group(1), m.group(2))
        window = text[m.end():m.end() + 120]
        me = re.search(r'出口[\d.]+亿元，(增长|下降)([\d.]+)%', window)
        if me:
            out['CN_EXPORT_YOY'] = _signed(me.group(1), me.group(2))
        mi = re.search(r'进口[\d.]+亿元，(增长|下降)([\d.]+)%', window)
        if mi:
            out['CN_IMPORT_YOY'] = _signed(mi.group(1), mi.group(2))
    return out


PARSERS = {'cpi': parse_cpi_article, 'ppi': parse_ppi_article, 'pmi': parse_pmi_article,
           'ip': parse_ip_article, 'retail': parse_retail_article,
           'fai': parse_fai_article, 'gdp': parse_gdp_article, 'econ': parse_econ_article}


def discover_releases(kind, start_year, end_year=None, max_pages=6, sleep_seconds=0.35):
    """站内搜索按年发现某类新闻稿;返回 {period: (url, title)},优先 /sj/zxfb/ 路径。"""
    spec = RELEASES[kind]
    end_year = int(end_year or datetime.now().year)
    headers = {**UA, 'Referer': 'https://www.stats.gov.cn/search/s'}
    found = {}
    # flat 模式:标题无年份的稿件(如"5月份国民经济运行…"),单查询按时间降序深翻
    if spec.get('flat_pages'):
        year_pages = [(None, page) for page in range(1, spec['flat_pages'] + 1)]
    else:
        year_pages = [(year, page) for year in range(end_year, int(start_year) - 1, -1)
                      for page in range(1, max_pages + 1)]
    exhausted_years = set()
    for year, page in year_pages:
        if year in exhausted_years:
            continue
        response = requests.post(NBS_SEARCH_API, data={
            'siteCode': NBS_SEARCH_SITE_CODE,
            'qt': spec['query'] if year is None else f'{year}年{spec["query"]}',
            'page': page, 'pageSize': 20, 'keyPlace': '1',
            'sort': 'dateDesc' if year is None else 'relevance',
        }, headers=headers, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        if not payload.get('ok'):
            raise ValueError(f'统计局搜索失败: {payload.get("msg") or payload.get("code")}')
        docs = payload.get('resultDocs') or []
        for doc in docs:
            data = doc.get('data', doc)
            title = re.sub(r'<[^>]+>', '', str(data.get('title') or '')).strip()
            url = data.get('url') or ''
            period = spec['period_fn'](title, url) if url else None
            if not period:
                continue
            current = found.get(period)
            if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
                found[period] = (url, title)
        if (not int(payload.get('currentHits') or 0)
                or page * 20 >= int(payload.get('totalHits') or 0)):
            exhausted_years.add(year)   # 该查询翻尽:年模式跳过该年剩余页,flat 模式即全部结束
        time.sleep(sleep_seconds)
    return found


def update_china_macro(db_path, start_year=None, sleep_seconds=0.3):
    """抓取并入库;默认只查今年+去年(增量),start_year 指定则深回填。
    单篇失败只记录,不影响其他;绝不清旧数据。"""
    started = datetime.now().isoformat()
    this_year = datetime.now().year
    start = int(start_year or this_year - 1)
    errors, upserted = [], 0
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        for kind in RELEASES:
            try:
                releases = discover_releases(kind, start)
            except Exception as exc:
                errors.append(f'{kind} discover: {exc}')
                continue
            for period in sorted(releases):
                url, title = releases[period]
                codes = _kind_codes(kind)
                have = conn.execute(
                    'SELECT COUNT(*) FROM china_macro_observations WHERE period=? '
                    f'AND indicator_code IN ({",".join("?"*len(codes))})',
                    (period, *codes)).fetchone()[0]
                if have >= len(codes):
                    continue
                try:
                    response = requests.get(url, headers=UA, timeout=HTTP_TIMEOUT)
                    response.raise_for_status()
                    response.encoding = 'utf-8'
                    values = PARSERS[kind](response.text)
                except Exception as exc:
                    errors.append(f'{kind} {period}: {exc}')
                    continue
                now = datetime.now().isoformat()
                for code, value in values.items():
                    name, unit, freq = INDICATORS[code]
                    cur = conn.execute('''INSERT INTO china_macro_observations (
                        indicator_code,indicator_name,period,value,unit,frequency,data_status,
                        source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(indicator_code,period) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at''',
                        (code, name, period, value, unit, freq, 'official',
                         SOURCE_NAME, SOURCE_TYPE, url, title,
                         '统计局新闻稿正文解析;上涨/下降定号,持平=0', None, now))
                    upserted += cur.rowcount
                conn.commit()
                time.sleep(sleep_seconds)
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(),
            'records_upserted': upserted, 'errors': errors}
