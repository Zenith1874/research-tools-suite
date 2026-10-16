# -*- coding: utf-8 -*-
"""中国实体经济月度指标:CPI、PPI、PMI(统计局官方新闻稿)。

来源:统计局月度新闻稿(www.stats.gov.cn,与 70 城/销售同一发布体系;
数据 API 对境外 IP 403,新闻稿页可访问)。发现走站内搜索 api.so-gov.cn。

指标(逐条 official + source_url):
- CN_CPI_YOY / CN_CPI_MOM         《X年X月份居民消费价格同比…》正文
- CN_PPI_YOY / CN_PPI_MOM         《X年X月份工业生产者出厂价格…》正文
- CN_PMI_MFG / CN_PMI_NONMFG / CN_PMI_COMP  《X年X月中国采购经理指数运行情况》正文

数据纪律:缺失如实缺(核心CPI只取官方表或明确正文);失败不清旧数据;
幂等 upsert;"持平"解析为 0.0(官方措辞,非缺失)。
"""
import csv
import hashlib
import math
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from services.housing_price_service import (
    NBS_LIST_URL, NBS_SEARCH_API, NBS_SEARCH_SITE_CODE, UA, HTTP_TIMEOUT,
    _release_path_rank,
)
from services.china_macro_extended_service import (
    EXTENDED_INDICATORS, ANNUAL_RELEASE_CODES, profit_period, capacity_period,
    annual_period, parse_industrial_profit_article, parse_capacity_article,
    parse_annual_livelihood_article,
)
from services.bank_supervision_snapshot_service import BANK_INDICATORS
from services.nbs_release_evidence import (
    CAPTURE_VERSION, CAPTURE_CODE_SHA256, MAX_BYTES as NBS_RELEASE_MAX_BYTES,
    archive_nbs_release, nbs_https_url, preserve_prior_observation,
)

SOURCE_NAME = '国家统计局'
SOURCE_TYPE = 'china_macro'
PARSER_VERSION = 'macro-completeness-20261002'
PARSER_CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def macro_ingestion_runtime():
    """Report import-time code identities, never the potentially changed current disk bytes."""
    # Probe the actual callable used by the annual update dispatch, including a
    # negative hukou-only case. This detects a stale cached annual parser too.
    try:
        annual = PARSERS['annual']
        scope_probe = {
            'explicit_resident_parenthesis': annual('常住人口城镇化率）为59.58%。户籍人口城镇化率为43.37%。').get('CN_URBANIZATION_RATE') == 59.58,
            'hukou_only_rejected': 'CN_URBANIZATION_RATE' not in annual('户籍人口城镇化率为43.37%。'),
        }
    except Exception:
        scope_probe = {'explicit_resident_parenthesis': False, 'hukou_only_rejected': False}
    return {'parser_version':PARSER_VERSION,'parser_code_sha256':PARSER_CODE_SHA256,
            'capture_version':CAPTURE_VERSION,'capture_code_sha256':CAPTURE_CODE_SHA256,
            'annual_resident_scope_probe': scope_probe}

INDICATORS = {
    'CN_CPI_YOY': ('居民消费价格(CPI)同比', '%', 'monthly'),
    'CN_CPI_MOM': ('居民消费价格(CPI)环比', '%', 'monthly'),
    'CN_PPI_YOY': ('工业生产者出厂价格(PPI)同比', '%', 'monthly'),
    'CN_PPI_MOM': ('工业生产者出厂价格(PPI)环比', '%', 'monthly'),
    'CN_PPIRM_YOY': ('工业生产者购进价格同比', '%', 'monthly'),
    'CN_PPIRM_MOM': ('工业生产者购进价格环比', '%', 'monthly'),
    'CN_PPI_PRODUCTION_YOY': ('生产资料出厂价格同比', '%', 'monthly'),
    'CN_PPI_LIVING_YOY': ('生活资料出厂价格同比', '%', 'monthly'),
    'CN_PMI_MFG': ('制造业PMI', '%', 'monthly'),
    'CN_PMI_NONMFG': ('非制造业商务活动指数', '%', 'monthly'),
    'CN_PMI_COMP': ('综合PMI产出指数', '%', 'monthly'),
    'CN_IP_YOY': ('规模以上工业增加值当月同比(实际)', '%', 'monthly'),
    'CN_IP_YTD_YOY': ('规模以上工业增加值累计同比', '%', 'monthly'),
    'CN_COAL_OUTPUT_MONTH': ('原煤产量当月', '万吨', 'monthly'),
    'CN_COAL_OUTPUT_MONTH_YOY': ('原煤产量当月同比', '%', 'monthly'),
    'CN_COAL_OUTPUT_YTD': ('原煤产量累计', '万吨', 'monthly'),
    'CN_COAL_OUTPUT_YTD_YOY': ('原煤产量累计同比', '%', 'monthly'),
    'CN_CRUDE_OIL_OUTPUT_MONTH': ('原油产量当月', '万吨', 'monthly'),
    'CN_CRUDE_OIL_OUTPUT_MONTH_YOY': ('原油产量当月同比', '%', 'monthly'),
    'CN_CRUDE_OIL_OUTPUT_YTD': ('原油产量累计', '万吨', 'monthly'),
    'CN_CRUDE_OIL_OUTPUT_YTD_YOY': ('原油产量累计同比', '%', 'monthly'),
    'CN_NATGAS_OUTPUT_MONTH': ('天然气产量当月', '亿立方米', 'monthly'),
    'CN_NATGAS_OUTPUT_MONTH_YOY': ('天然气产量当月同比', '%', 'monthly'),
    'CN_NATGAS_OUTPUT_YTD': ('天然气产量累计', '亿立方米', 'monthly'),
    'CN_NATGAS_OUTPUT_YTD_YOY': ('天然气产量累计同比', '%', 'monthly'),
    'CN_CRUDE_STEEL_OUTPUT_MONTH': ('粗钢产量当月', '万吨', 'monthly'),
    'CN_CRUDE_STEEL_OUTPUT_MONTH_YOY': ('粗钢产量当月同比', '%', 'monthly'),
    'CN_CRUDE_STEEL_OUTPUT_YTD': ('粗钢产量累计', '万吨', 'monthly'),
    'CN_CRUDE_STEEL_OUTPUT_YTD_YOY': ('粗钢产量累计同比', '%', 'monthly'),
    'CN_POWER_OUTPUT_MONTH': ('规模以上工业发电量当月', '亿千瓦时', 'monthly'),
    'CN_POWER_OUTPUT_MONTH_YOY': ('规模以上工业发电量当月同比', '%', 'monthly'),
    'CN_POWER_OUTPUT_YTD': ('规模以上工业发电量累计', '亿千瓦时', 'monthly'),
    'CN_POWER_OUTPUT_YTD_YOY': ('规模以上工业发电量累计同比', '%', 'monthly'),
    'CN_AUTO_OUTPUT_MONTH': ('汽车产量当月', '万辆', 'monthly'),
    'CN_AUTO_OUTPUT_MONTH_YOY': ('汽车产量当月同比', '%', 'monthly'),
    'CN_AUTO_OUTPUT_YTD': ('汽车产量累计', '万辆', 'monthly'),
    'CN_AUTO_OUTPUT_YTD_YOY': ('汽车产量累计同比', '%', 'monthly'),
    'CN_NEV_OUTPUT_MONTH': ('新能源汽车产量当月', '万辆', 'monthly'),
    'CN_NEV_OUTPUT_MONTH_YOY': ('新能源汽车产量当月同比', '%', 'monthly'),
    'CN_NEV_OUTPUT_YTD': ('新能源汽车产量累计', '万辆', 'monthly'),
    'CN_NEV_OUTPUT_YTD_YOY': ('新能源汽车产量累计同比', '%', 'monthly'),
    'CN_RETAIL_YOY': ('社会消费品零售总额当月同比', '%', 'monthly'),
    'CN_RETAIL_YTD_YOY': ('社会消费品零售总额累计同比', '%', 'monthly'),
    'CN_RETAIL_MONTH': ('社会消费品零售总额当月', '亿元', 'monthly'),
    'CN_RETAIL_YTD': ('社会消费品零售总额累计', '亿元', 'monthly'),
    'CN_RETAIL_EX_AUTO_MONTH': ('除汽车以外消费品零售额当月', '亿元', 'monthly'),
    'CN_RETAIL_EX_AUTO_MONTH_YOY': ('除汽车以外消费品零售额当月同比', '%', 'monthly'),
    'CN_RETAIL_EX_AUTO_YTD': ('除汽车以外消费品零售额累计', '亿元', 'monthly'),
    'CN_RETAIL_EX_AUTO_YTD_YOY': ('除汽车以外消费品零售额累计同比', '%', 'monthly'),
    'CN_RETAIL_ONLINE_GOODS_YTD': ('网上商品零售额累计', '亿元', 'monthly'),
    'CN_RETAIL_ONLINE_GOODS_YTD_YOY': ('网上商品零售额累计同比', '%', 'monthly'),
    'CN_RETAIL_ONLINE_GOODS_MONTH': ('网上商品零售额当月', '亿元', 'monthly'),
    'CN_RETAIL_ONLINE_GOODS_MONTH_YOY': ('网上商品零售额当月同比', '%', 'monthly'),
    'CN_AUTO_RETAIL_MONTH': ('限额以上单位汽车类零售额当月', '亿元', 'monthly'),
    'CN_AUTO_RETAIL_MONTH_YOY': ('限额以上单位汽车类零售额当月同比', '%', 'monthly'),
    'CN_AUTO_RETAIL_YTD': ('限额以上单位汽车类零售额累计', '亿元', 'monthly'),
    'CN_AUTO_RETAIL_YTD_YOY': ('限额以上单位汽车类零售额累计同比', '%', 'monthly'),
    'CN_FAI_YTD': ('固定资产投资(不含农户)累计', '亿元', 'monthly'),
    'CN_FAI_YTD_YOY': ('固定资产投资(不含农户)累计同比', '%', 'monthly'),
    'CN_FAI_PRIVATE_YTD_YOY': ('民间固定资产投资累计同比', '%', 'monthly'),
    'CN_FAI_MANUFACTURING_YTD_YOY': ('制造业投资累计同比', '%', 'monthly'),
    'CN_FAI_INFRA_YTD_YOY': ('基础设施投资累计同比', '%', 'monthly'),
    'CN_GDP_Q_NOMINAL': ('GDP单季现价总量', '亿元', 'quarterly'),
    'CN_GDP_Q_REAL_YOY': ('GDP单季不变价同比', '%', 'quarterly'),
    'CN_UNEMP_SURVEY': ('全国城镇调查失业率(当月)', '%', 'monthly'),
    'CN_TRADE_YOY': ('货物进出口总额当月同比', '%', 'monthly'),
    'CN_EXPORT_YOY': ('出口当月同比', '%', 'monthly'),
    'CN_IMPORT_YOY': ('进口当月同比', '%', 'monthly'),
    'CN_POPULATION': ('年末全国人口', '万人', 'annual'),
    'CN_DISPOSABLE_INCOME': ('全国居民人均可支配收入', '元/人', 'annual'),
    'CN_LABOR_FORCE': ('全国劳动力', '万人', 'annual'),
    'CN_EMPLOYED': ('全国就业人员', '万人', 'annual'),
    'CN_URBAN_EMPLOYED': ('城镇就业人员', '万人', 'annual'),
    'CN_URBAN_NEW_JOBS': ('全国城镇新增就业', '万人', 'annual'),
    'CN_WORKING_AGE_POP': ('16—59岁人口', '万人', 'annual'),
    'CN_WORKING_AGE_15_64': ('15—64岁人口', '万人', 'annual'),
    'CN_BIRTHS': ('出生人口', '万人', 'annual'),
    'CN_MARRIAGES': ('结婚登记', '万对', 'annual'),
    'CN_DIVORCES_AGREEMENT': ('协议离婚（民政部门登记）', '万对', 'annual'),
    'CN_DIVORCES_COURT': ('法院离婚（判决/调解）', '万对', 'annual'),
    'CN_DIVORCES_TOTAL_OFFICIAL': ('离婚总数（公报公布）', '万对', 'annual'),
    'CN_DEATHS': ('死亡人口', '万人', 'annual'),
    'CN_BIRTH_RATE': ('人口出生率', '‰', 'annual'),
    'CN_DEATH_RATE': ('人口死亡率', '‰', 'annual'),
    'CN_NATURAL_GROWTH_RATE': ('人口自然增长率', '‰', 'annual'),
}
INDICATORS.update(EXTENDED_INDICATORS)
INDICATORS.update(BANK_INDICATORS)
INDICATORS.update({
    **{f'CN_CPI_{key}_{measure}': (f'{label}{"同比" if measure == "YOY" else "环比"}', '%', 'monthly')
       for key, label in (('CORE', '核心CPI（不含食品能源）'), ('FOOD', '食品CPI'),
                          ('NONFOOD', '非食品CPI'), ('GOODS', '消费品CPI'), ('SERVICES', '服务CPI'))
       for measure in ('YOY', 'MOM')},
    **{f'CN_PMI_MFG_{key}': (f'制造业PMI{label}指数', '%', 'monthly')
       for key, label in (('PRODUCTION', '生产'), ('NEW_ORDERS', '新订单'),
                          ('RAW_INVENTORY', '原材料库存'), ('EMPLOYMENT', '从业人员'),
                          ('DELIVERY', '供应商配送时间'), ('NEW_EXPORT_ORDERS', '新出口订单'),
                          ('INPUT_PRICES', '购进价格'), ('OUTPUT_PRICES', '出厂价格'),
                          ('EXPECTATIONS', '生产经营预期'))},
    'CN_PMI_SERVICE': ('服务业商务活动指数', '%', 'monthly'),
    'CN_PMI_CONSTRUCTION': ('建筑业商务活动指数', '%', 'monthly'),
    'CN_UNEMP_31_CITIES': ('31个大城市城镇调查失业率（当月）', '%', 'monthly'),
    'CN_RETAIL_SERVICES_YTD_YOY': ('服务零售额累计同比（官方）', '%', 'monthly'),
    'CN_CPI_CORE_YTD_AVG_YOY': ('核心CPI累计平均同比（官方）', '%', 'monthly'),
})

_ROOT = Path(__file__).resolve().parents[1]
ANNUAL_MACRO_PATH = _ROOT / 'data' / 'china_macro_annual_official.csv'
OFFICIAL_BACKFILL_PATH = _ROOT / 'data' / 'china_macro_official_backfill.csv'
ANNUAL_SUPPLEMENT_PATH = _ROOT / 'data' / 'china_macro_annual_supplement.csv'
ECON_RELEASE_MANIFEST_PATH = _ROOT / 'data' / 'china_econ_release_manifest.csv'
STRUCTURAL_DRIVER_PATH = _ROOT / 'data' / 'housing_structural_drivers.csv'

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


def _fai_period(title, url):
    """固定资产投资稿的统计期。

    月度稿使用“1—N月份”；年度稿常写成“YYYY年全国固定资产投资”，
    其统计期是该年的12月。不能把年度稿丢掉，否则每年末的累计额与同比
    会在序列中形成一个系统性缺口。
    """
    period = _month_period(title, '全国固定资产投资')
    if period:
        return period
    match = re.match(r'^(20\d{2})年(?:，|,)?全国固定资产投资', title)
    return f'{match.group(1)}-12' if match else None


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
    annual = re.match(r'^(20\d{2})年(?:经济运行|经济发展|国民经济)', title)
    if annual:
        return f'{annual[1]}-12'
    quarter = re.match(r'^(一季度|上半年|前三季度|全年)(?:国民经济|经济运行|经济发展)', title)
    if quarter:
        u = re.search(r'/(20\d{2})(\d{2})/t20', url or '')
        if not u or (u[1], u[2]) == ('2023', '02'):
            return None
        month = {'一季度': 3, '上半年': 6, '前三季度': 9, '全年': 12}[quarter[1]]
        return f'{int(u[1]) - (month > int(u[2]))}-{month:02d}'
    m = re.match(r'^(?:1[—-](\d{1,2})|(\d{1,2}))月份国民经济', title)
    u = re.search(r'/(20\d{2})(\d{2})/t20', url or '')
    if not m or not u:
        return None
    if (u.group(1), u.group(2)) == ('2023', '02'):
        return None  # Site migration date is not the reporting year.
    month = int(m.group(1) or m.group(2))
    year = int(u.group(1))
    if month > int(u.group(2)):
        year -= 1
    return f'{year}-{month:02d}'


def econ_period_from_article(html, title='', url=''):
    """Use the statistical table's explicit year/month, not an archive path."""
    text = _clean_text(html)
    match = re.search(r'(20\d{2})年(?:1[—－–-](\d{1,2})|([\d]{1,2}))月份?'
                      r'(?:及(一季度|上半年|前三季度|全年))?'
                      r'(?:国民经济)?主要(?:指标|统计)数据?', text)
    if match:
        month = int(match[2] or match[3])
        if match[4] and month != {'一季度':3,'上半年':6,'前三季度':9,'全年':12}[match[4]]:
            return None
        if 1 <= month <= 12:
            return f'{match[1]}-{month:02d}'
    return _econ_period(title, url)


RELEASES = {
    'cpi': {'query': '居民消费价格',
            'period_fn': lambda t, u: _month_period(t, '居民消费价格')},
    'ppi': {'query': '工业生产者出厂价格',
            'period_fn': lambda t, u: _month_period(t, '工业生产者出厂价格'),
            'codes': tuple(code for code in INDICATORS
                           if code.startswith('CN_PPI') or code.startswith('CN_PPIRM'))},
    'pmi': {'query': '中国采购经理指数运行情况',
            'period_fn': lambda t, u: _month_period(t, '中国采购经理指数运行情况')},
    'ip': {'query': '规模以上工业增加值',
           'period_fn': lambda t, u: _month_period(t, '规模以上工业增加值'),
           'codes': tuple(code for code in INDICATORS if code.startswith((
               'CN_IP_', 'CN_COAL_', 'CN_CRUDE_OIL_', 'CN_NATGAS_',
               'CN_CRUDE_STEEL_', 'CN_POWER_', 'CN_AUTO_OUTPUT_', 'CN_NEV_')))},
    'retail': {'query': '社会消费品零售总额',
               'period_fn': lambda t, u: _month_period(t, '社会消费品零售总额'),
               'codes': tuple(code for code in INDICATORS
                              if code.startswith(('CN_RETAIL_', 'CN_AUTO_RETAIL_')))},
    'fai': {'query': '全国固定资产投资',
            'period_fn': _fai_period,
            'codes': tuple(code for code in INDICATORS if code.startswith('CN_FAI_'))},
    'gdp': {'query': '国内生产总值初步核算结果', 'period_fn': lambda t, u: _gdp_period(t)},
    'econ': {'query': '国民经济', 'period_fn': _econ_period, 'flat_pages': 25,
             'codes': ('CN_UNEMP_SURVEY', 'CN_UNEMP_31_CITIES', 'CN_TRADE_YOY', 'CN_EXPORT_YOY',
                       'CN_IMPORT_YOY', 'CN_CPI_CORE_YTD_AVG_YOY', 'CN_RETAIL_SERVICES_YTD_YOY')},
    'profit': {'query': '全国规模以上工业企业利润', 'period_fn': profit_period,
               'codes': tuple(code for code in INDICATORS if code.startswith('CN_IND_'))},
    'capacity': {'query': '全国工业产能利用率', 'period_fn': capacity_period,
                 'codes': ('CN_CAPACITY_UTILIZATION',)},
    'annual': {'query': '国民经济和社会发展统计公报', 'period_fn': annual_period,
               'codes': ANNUAL_RELEASE_CODES},
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
    existing_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(china_macro_observations)')}
    for name, definition in (
            ('release_date', 'TEXT'),
            ('retrieved_at', 'TEXT'),
            ('raw_sha256', 'TEXT'),
            ('parser_version', 'TEXT'),
            ('missing_reason', 'TEXT'),
            ('original_value', 'REAL'),
            # SAFE's annual reserve-assets page is updated in place.  These
            # fields keep page/vintage time separate from an observation's
            # (often unavailable) release date.
            ('source_page_created_date', 'TEXT'),
            ('source_page_last_updated_date', 'TEXT'),
            ('release_date_not_provided', 'INTEGER NOT NULL DEFAULT 0'),
            ('release_date_reason', 'TEXT')):
        if name not in existing_columns:
            conn.execute(f'ALTER TABLE china_macro_observations ADD COLUMN {name} {definition}')
    conn.commit()


def _clean_text(html):
    return re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', html or ''))


def _number_cell(value):
    """表格数值转 float；破折号、省略号和口径说明保持缺失。"""
    if value is None:
        return None
    text = str(value).strip().replace(',', '').replace('，', '')
    text = re.sub(r'[（(].*?[）)]', '', text)
    if text in ('', '-', '—', '–', '…', '...', '－'):
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


def _table_rows(html):
    """返回新闻稿内所有表格行；保留首列标签，供不同年份的小幅措辞变化匹配。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or '', 'html.parser')
    rows = []
    for table in soup.find_all('table'):
        for tr in table.find_all('tr'):
            cells = [re.sub(r'\s+', '', cell.get_text(' ', strip=True))
                     for cell in tr.find_all(['td', 'th'])]
            if cells:
                rows.append(cells)
    return rows


def _five_column_row(rows, labels):
    """找“标签/当月量/当月同比/累计量/累计同比”式国家统计局表格行。"""
    for cells in rows:
        label = re.sub(r'^[其中：:]+', '', cells[0]).strip()
        if len(cells) >= 5 and any(label == candidate or label.endswith(candidate)
                                   for candidate in labels):
            return tuple(_number_cell(value) for value in cells[1:5])
    return (None, None, None, None)


def _signed(direction, number):
    """官方措辞定号:上涨/增长=+,下降=−;number 为字符串数值。"""
    return float(number) * (-1 if direction == '下降' else 1)


def _change(text, prefix):
    """解析 '<prefix>同比上涨X%' / '下降X%' / '持平' → (yoy, mom);未命中为 None。
    环比必须锚定:优先带前缀(现行措辞独立成句),否则只在同比命中位置后 80 字符窗口内找
    (早年措辞同比环比同句),绝不全篇任意匹配以免抓到分项数字。"""
    yoy = mom = None
    yoy_end = None
    yoy_label = r'(?:同比|比(?:去年|上年)同月)'
    mom_label = r'(?:环比|比上月)'
    yoy_candidates = []
    for pattern, is_flat in (
            (prefix + yoy_label + r'(上涨|下降)([\d.]+)%', False),
            (prefix + r'(?:同比|与(?:去年|上年)同月)持平', True),
            (prefix + mom_label + r'(?:上涨|下降|持平)[\d.]*%?[，,]?'
             + yoy_label + r'(上涨|下降)([\d.]+)%', False)):
        match = re.search(pattern, text)
        if match:
            yoy_candidates.append((match.start(), match.end(),
                                   0.0 if is_flat else _signed(match[1], match[2])))
    # Prefer the first actual headline, not a later YTD sentence that happens
    # to use the newer word order or a simpler comparison expression.
    if yoy_candidates:
        _, yoy_end, yoy = min(yoy_candidates, key=lambda item:item[0])
    mom_candidates = []
    m = re.search(prefix + mom_label + r'(上涨|下降)([\d.]+)%', text)
    if m:
        mom_candidates.append((m.start(), _signed(m.group(1), m.group(2))))
    m = re.search(prefix + r'环比(?:与上月)?持平', text)
    if m:
        mom_candidates.append((m.start(), 0.0))
    if yoy_end is not None:
        window = text[yoy_end:yoy_end + 80]
        # A later named series is not a continuation of this headline. Also
        # choose the first explicit change/flat phrase, not any later nonzero.
        window = re.split(r'工业生产者(?:出厂|购进)价格|全国居民消费价格|'
                          r'(?:非食品|食品|生产资料|生活资料)价格', window, maxsplit=1)[0]
        m = re.search(mom_label + r'(?:(上涨|下降)([\d.]+)%|(?:与上月)?(持平))', window)
        if m:
            mom_candidates.append((yoy_end+m.start(), 0.0 if m.group(3) else _signed(m.group(1), m.group(2))))
    if mom_candidates:
        _, mom = min(mom_candidates, key=lambda item:item[0])
    return yoy, mom


def parse_cpi_article(html):
    text = _clean_text(html)
    yoy, mom = _change(text, r'全国居民消费价格(?:总水平)?')
    out = {}
    if yoy is not None:
        out['CN_CPI_YOY'] = yoy
    if mom is not None:
        out['CN_CPI_MOM'] = mom
    # The table is month-on-month / year-on-year / year-to-date, not the reverse.
    labels = {'食品': 'FOOD', '非食品': 'NONFOOD', '消费品': 'GOODS', '服务': 'SERVICES',
              '不包括食品和能源': 'CORE', '不包含食品和能源': 'CORE',
              '扣除食品和能源': 'CORE'}
    for table in BeautifulSoup(html or '', 'html.parser').find_all('table'):
        rows = _table_rows(str(table))
        header = next((row for row in rows if len(row) >= 3
                       and '环比' in row[1] and '同比' in row[2]), None)
        if not header:
            continue
        for cells in rows:
            if len(cells) < 3:
                continue
            key = labels.get(re.sub(r'^其中[：:]', '', cells[0]))
            if not key:
                continue
            for suffix, cell in (('MOM', cells[1]), ('YOY', cells[2])):
                value = _number_cell(cell)
                if value is not None:
                    out[f'CN_CPI_{key}_{suffix}'] = value
            if key == 'CORE' and len(cells) >= 4 and len(header) >= 4 and '同比' in header[3]:
                value = _number_cell(cells[3])
                if value is not None:
                    out['CN_CPI_CORE_YTD_AVG_YOY'] = value
    return out


def _current_price_wording(text):
    """Keep the current side of explicit previous-month-to-current transitions."""
    text = re.sub(r'由(?:上月(?:的)?)?(?:(?:上涨|下降)[\d.]+%|持平)转为'
                  r'((?:上涨|下降)[\d.]+%|持平)', r'\1', text)
    return text.replace('环比继续持平', '环比持平')


def _paired_ppi_headline(text):
    """Decode only the headline's explicitly ordered factory/purchase pair."""
    lead = text.split('一、', 1)[0]
    first = lead.find('工业生产者出厂价格')
    second = lead.find('工业生产者购进价格')
    shared = lead.find('工业生产者出厂价格和购进价格')
    if first < 0 or (shared < 0 and (second < first or second < 0)):
        return {}
    output = {}
    match = re.search(r'工业生产者出厂价格和购进价格同比均(上涨|下降)([\d.]+)%', lead)
    first_individual = re.search(r'全国工业生产者出厂价格(?:同比|环比|比上月)|'
                                 r'工业生产者购进价格(?:同比|环比|比上月)', lead)
    if match and (first_individual is None or match.start()<first_individual.start()):
        output['CN_PPI_YOY'] = output['CN_PPIRM_YOY'] = _signed(match[1], match[2])
    token = r'(?:上涨|下降)[\d.]+%|持平'
    pair = re.search(r'环比分别(' + token + r')(?:、|和)(' + token + r'|[\d.]+%)', lead)
    if pair:
        values = []
        direction = None
        for item in pair.groups():
            if item == '持平':
                values.append(0.0)
                continue
            change = re.fullmatch(r'(上涨|下降)?([\d.]+)%', item)
            direction = change[1] or direction
            if direction is None:
                return output
            values.append(_signed(direction, change[2]))
        output.update(CN_PPI_MOM=values[0], CN_PPIRM_MOM=values[1])
    elif shared >= 0:
        same = re.search(r'环比均(上涨|下降)([\d.]+)%', lead)
        if same:
            output['CN_PPI_MOM'] = output['CN_PPIRM_MOM'] = _signed(same[1], same[2])
        elif re.search(r'环比均持平', lead):
            output['CN_PPI_MOM'] = output['CN_PPIRM_MOM'] = 0.0
    return output


def parse_ppi_article(html):
    text = _current_price_wording(_clean_text(html))
    yoy, mom = _change(text, r'全国工业生产者出厂价格')
    if (yoy is None or mom is None) and '全国工业生产者出厂价格' in text:
        # Some current headlines state the national MoM first, then repeat the
        # factory-price YoY in a separate sentence without repeating 全国.
        alternate_yoy, alternate_mom = _change(text, r'工业生产者出厂价格')
        if yoy is None:
            yoy = alternate_yoy
        if mom is None:
            mom = alternate_mom
    out = {}
    if yoy is not None:
        out['CN_PPI_YOY'] = yoy
    if mom is not None:
        out['CN_PPI_MOM'] = mom
    purchase_yoy, purchase_mom = _change(text, r'工业生产者购进价格')
    if purchase_yoy is not None:
        out['CN_PPIRM_YOY'] = purchase_yoy
    if purchase_mom is not None:
        out['CN_PPIRM_MOM'] = purchase_mom
    # 近年摘要有两种合并写法，单指标前缀无法直接命中：
    # “出厂价格和购进价格环比分别下降0.2%、0.3%”以及
    # “购进价格同比和环比均下降0.1%”。
    pair = re.search(r'工业生产者出厂价格和购进价格环比分别'
                     r'(上涨|下降)([\d.]+)%、([\d.]+)%', text)
    if pair:
        if mom is None:
            mom = _signed(pair.group(1), pair.group(2))
        if purchase_mom is None:
            purchase_mom = _signed(pair.group(1), pair.group(3))
    same_pair = re.search(r'工业生产者出厂价格和购进价格环比均'
                          r'(上涨|下降)([\d.]+)%', text)
    if same_pair:
        if mom is None:
            mom = _signed(same_pair.group(1), same_pair.group(2))
        if purchase_mom is None:
            purchase_mom = _signed(same_pair.group(1), same_pair.group(2))
    same_ppi = re.search(r'(?:全国)?工业生产者出厂价格同比(?:、|和)环比均?'
                         r'(上涨|下降)([\d.]+)%', text)
    if same_ppi:
        if yoy is None:
            yoy = _signed(same_ppi.group(1), same_ppi.group(2))
        if mom is None:
            mom = _signed(same_ppi.group(1), same_ppi.group(2))
    same_purchase = re.search(r'工业生产者购进价格同比(?:、|和)环比均?'
                              r'(上涨|下降)([\d.]+)%', text)
    if same_purchase:
        if purchase_yoy is None:
            purchase_yoy = _signed(same_purchase.group(1), same_purchase.group(2))
        if purchase_mom is None:
            purchase_mom = _signed(same_purchase.group(1), same_purchase.group(2))
    if yoy is not None:
        out['CN_PPI_YOY'] = yoy
    if mom is not None:
        out['CN_PPI_MOM'] = mom
    if purchase_yoy is not None:
        out['CN_PPIRM_YOY'] = purchase_yoy
    if purchase_mom is not None:
        out['CN_PPIRM_MOM'] = purchase_mom
    # 2021 年基期轮换后，正文同比段常写“生产资料价格上涨”，不再带
    # “同比”二字；环比段也会再次出现同一短语，所以只取同比段首次出现。
    yoy_section = re.split(r'二、(?:工业生产者价格|各类产品价格)环比变动情况', text, maxsplit=1)[0]
    match = re.search(r'生产资料价格[^。]{0,40}?(上涨|下降)([\d.]+)%', yoy_section)
    if match:
        out['CN_PPI_PRODUCTION_YOY'] = _signed(match.group(1), match.group(2))
    elif re.search(r'生产资料价格[^。]{0,40}?(?:同比)?持平', yoy_section):
        out['CN_PPI_PRODUCTION_YOY'] = 0.0
    match = re.search(r'生活资料价格[^。]{0,40}?(上涨|下降)([\d.]+)%', yoy_section)
    if match:
        out['CN_PPI_LIVING_YOY'] = _signed(match.group(1), match.group(2))
    elif re.search(r'生活资料价格[^。]{0,40}?(?:同比)?持平', yoy_section):
        out['CN_PPI_LIVING_YOY'] = 0.0
    out.update(_paired_ppi_headline(text))
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
    manufacturing = text.split('二、中国非制造业')[0]
    for key, label in (('PRODUCTION', '生产'), ('NEW_ORDERS', '新订单'),
                       ('RAW_INVENTORY', '原材料库存'), ('EMPLOYMENT', '从业人员'),
                       ('DELIVERY', '供应商配送时间')):
        match = re.search(label + r'指数为([\d.]+)%', manufacturing)
        if match:
            out[f'CN_PMI_MFG_{key}'] = float(match[1])
    for code, label in (('CN_PMI_SERVICE', '服务业'), ('CN_PMI_CONSTRUCTION', '建筑业')):
        match = re.search(label + r'商务活动指数为([\d.]+)%', text)
        if match:
            out[code] = float(match[1])
    for table in BeautifulSoup(html or '', 'html.parser').find_all('table'):
        rows = _table_rows(str(table))
        header = next((row for row in rows if row and row[0] == ''
                       and '主要原材料购进价格' in row and '出厂价格' in row), None)
        if not header:
            continue  # Do not confuse nonmanufacturing export/price indices with manufacturing.
        dated = [(int(m[1]) * 12 + int(m[2]), row) for row in rows if row
                 and (m := re.fullmatch(r'(20\d{2})年(\d{1,2})月', row[0]))]
        if not dated:
            continue
        row = max(dated, key=lambda item: item[0])[1]
        for key, label in (('NEW_EXPORT_ORDERS', '新出口订单'),
                           ('INPUT_PRICES', '主要原材料购进价格'),
                           ('OUTPUT_PRICES', '出厂价格'), ('EXPECTATIONS', '生产经营活动预期')):
            if label in header and header.index(label) < len(row):
                value = _number_cell(row[header.index(label)])
                if value is not None:
                    out[f'CN_PMI_MFG_{key}'] = value
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
    rows = _table_rows(html)
    products = {
        'CN_COAL_OUTPUT': ('原煤（万吨）', '原煤(万吨)'),
        'CN_CRUDE_OIL_OUTPUT': ('原油（万吨）', '原油(万吨)'),
        'CN_NATGAS_OUTPUT': ('天然气（亿立方米）', '天然气(亿立方米)'),
        'CN_CRUDE_STEEL_OUTPUT': ('粗钢（万吨）', '粗钢(万吨)'),
        'CN_POWER_OUTPUT': ('规模以上工业发电量（亿千瓦时）', '发电量（亿千瓦时）'),
        'CN_AUTO_OUTPUT': ('汽车（万辆）', '汽车(万辆)'),
        'CN_NEV_OUTPUT': ('新能源汽车（万辆）', '新能源汽车(万辆)'),
    }
    for prefix, labels in products.items():
        month, month_yoy, ytd, ytd_yoy = _five_column_row(rows, labels)
        for suffix, value in (('MONTH', month), ('MONTH_YOY', month_yoy),
                              ('YTD', ytd), ('YTD_YOY', ytd_yoy)):
            if value is not None:
                out[f'{prefix}_{suffix}'] = value
    return out


def parse_retail_article(html):
    """社零:当月'X月份，社会消费品零售总额…同比…';累计'1—X月份，…'。"""
    text = _clean_text(html)
    out = {}
    rows = _table_rows(html)

    def add_row(labels, prefix):
        month, month_yoy, ytd, ytd_yoy = _five_column_row(rows, labels)
        codes = ((f'{prefix}_MONTH', month), (f'{prefix}_MONTH_YOY', month_yoy),
                 (f'{prefix}_YTD', ytd), (f'{prefix}_YTD_YOY', ytd_yoy))
        if prefix == 'CN_RETAIL':
            codes = (('CN_RETAIL_MONTH', month), ('CN_RETAIL_YOY', month_yoy),
                     ('CN_RETAIL_YTD', ytd), ('CN_RETAIL_YTD_YOY', ytd_yoy))
        for code, value in codes:
            if value is not None:
                out[code] = value

    add_row(('社会消费品零售总额',), 'CN_RETAIL')
    add_row(('除汽车以外的消费品零售额', '除汽车以外消费品零售额'),
            'CN_RETAIL_EX_AUTO')
    add_row(('网上商品零售额', '实物商品网上零售额'), 'CN_RETAIL_ONLINE_GOODS')
    add_row(('汽车类',), 'CN_AUTO_RETAIL')

    # 早年新闻稿可能只有正文、无五列表格，保留锚定式回退。
    if 'CN_RETAIL_YOY' not in out:
        m = re.search(r'(?<![—-])\d{1,2}月份，社会消费品零售总额[\d,.]+亿元，同比(增长|下降)([\d.]+)%', text)
        if m:
            out['CN_RETAIL_YOY'] = _signed(m.group(1), m.group(2))
    if 'CN_RETAIL_YTD_YOY' not in out:
        m = re.search(r'1[—-]\d{1,2}月份，社会消费品零售总额[\d,.]+亿元，同比(增长|下降)([\d.]+)%', text)
        if m:
            out['CN_RETAIL_YTD_YOY'] = _signed(m.group(1), m.group(2))
    return out


def parse_fai_article(html):
    text = _clean_text(html)
    out = {}
    m = re.search(r'1[—-]\d{1,2}月份，全国固定资产投资（不含农户）([\d,.]+)亿元，'
                  r'同比(增长|下降)([\d.]+)%', text)
    if not m:
        m = re.search(r'(?:20\d{2}年)?(?:，|,)全国固定资产投资（不含农户）'
                      r'([\d,.]+)亿元，?(?:比上年(?:同比)?|同比)?(增长|下降)([\d.]+)%', text)
    if m:
        out['CN_FAI_YTD'] = float(m.group(1).replace(',', ''))
        out['CN_FAI_YTD_YOY'] = _signed(m.group(2), m.group(3))
    patterns = {
        'CN_FAI_PRIVATE_YTD_YOY': (
            r'民间固定资产投资(?:[\d,.]+亿元，?)?(?:同比)?(增长|下降)([\d.]+)%'),
        'CN_FAI_MANUFACTURING_YTD_YOY': r'制造业投资(?:同比)?(增长|下降)([\d.]+)%',
        'CN_FAI_INFRA_YTD_YOY': r'基础设施投资(?:（[^）]+）)?同比(增长|下降)([\d.]+)%',
    }
    for code, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            out[code] = _signed(match.group(1), match.group(2))
    if 'CN_FAI_PRIVATE_YTD_YOY' not in out:
        for cells in _table_rows(html):
            label = re.sub(r'^[其中：:]+', '', cells[0]).strip()
            if label == '民间投资' and len(cells) >= 2:
                # Older tables have absolute amount / growth; newer ones only growth.
                value = _number_cell(cells[2] if len(cells) >= 3 else cells[1])
                if value is not None and abs(value) <= 1000:
                    out['CN_FAI_PRIVATE_YTD_YOY'] = value
                    break
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


def parse_econ_article(html, period=None):
    """月度国民经济运行稿:当月城镇调查失业率 + 货物贸易(总额同比、出口/进口各自同比)。
    贸易段先当月后累计:出口/进口取货物进出口总额句之后 120 字符窗内的第一对,防串到累计。
    海关总署站点对境外访问不可达,此处为统计局官方转述的海关数据。"""
    text = _clean_text(html)
    out = {}
    target = period or econ_period_from_article(html)
    month = str(int(target[-2:])) if target else r'\d{1,2}'
    m = re.search(r'(?<![\d—-])' + month + r'月份[，,]?全国城镇调查失业率(?:为|是|升至|降至)([\d.]+)%', text)
    if m:
        out['CN_UNEMP_SURVEY'] = float(m.group(1))
    if ('CN_UNEMP_SURVEY' not in out
            and not (target and re.search(r'\d{1,2}月份[，,]?全国城镇调查失业率(?:为|是|升至|降至)', text))):
        match = re.search(r'全国城镇调查失业率(?:为|是|升至|降至)([\d.]+)%', text)
        if match:
            out['CN_UNEMP_SURVEY'] = float(match[1])
    if target and 'CN_UNEMP_SURVEY' not in out:
        from services.china_macro_extended_service import parse_reported_survey_months
        # Target year/month is checked against the release table before ingestion.
        for reported_period,code,value in parse_reported_survey_months(html,int(target[:4]),year_is_validated=True):
            if reported_period==target and code=='CN_UNEMP_SURVEY':out[code]=value
    for code, pattern in (
            ('CN_UNEMP_31_CITIES', r'31个大城市城镇调查失业率为([\d.]+)%'),
            ):
        match = re.search(pattern, text)
        if match:
            out[code] = float(match[1])
    services = re.search(r'服务零售额(?:同比)?(增长|下降)([\d.]+)%', text)
    if services:
        out['CN_RETAIL_SERVICES_YTD_YOY'] = _signed(services[1], services[2])
    core = re.search(r'1[—-](\d{1,2})月份，[\s\S]{0,36}?核心CPI同比(上涨|下降)([\d.]+)%', text)
    if core and (not target or int(core[1]) == int(target[-2:])):
        out['CN_CPI_CORE_YTD_AVG_YOY'] = _signed(core[2], core[3])
    m = re.search(r'(?<![—-])\d{1,2}月份，?货物进出口总额[\d.]+亿元，同比(增长|下降)([\d.]+)%', text)
    if not m:
        candidate = re.search(r'货物进出口总额[\d.]+亿元，同比(增长|下降)([\d.]+)%', text)
        if candidate and not re.search(r'(?:1[—-]\d{1,2}月|上半年|一季度|前三季度|全年)',
                                       text[max(0, candidate.start()-16):candidate.start()]):
            m = candidate
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


def parse_econ_unemployment_observations(html, period):
    """Keep exact monthly rates disclosed together, never allocate a period average."""
    from services.china_macro_extended_service import (
        parse_reported_survey_month_details, parse_reported_city_survey_month_details,
    )

    values = parse_econ_article(html, period=period)
    rows = [(period, code, values[code]) for code in ('CN_UNEMP_SURVEY', 'CN_UNEMP_31_CITIES') if code in values]
    if period.endswith('-02'):
        text = _clean_text(html)
        january = re.search(r'(?<![\d—-])1月份，?全国城镇调查失业率为([\d.]+)%', text)
        if january and 0 <= float(january[1]) <= 100:
            rows.append((period[:4] + '-01', 'CN_UNEMP_SURVEY', float(january[1])))
    # Reporting year/month is independently verified from the source before ingestion.
    # A first-quarter release can explicitly disclose January, February and March.
    reported = parse_reported_survey_month_details(
        html, int(period[:4]), year_is_validated=True)
    rows.extend(row for row in reported['rows'] if row[0] <= period)
    cities = parse_reported_city_survey_month_details(
        html, int(period[:4]), year_is_validated=True)
    rows.extend(row for row in cities['rows'] if row[0] <= period)
    unique={};conflicts=set(reported['conflicts']) | set(cities['conflicts'])
    for observed_period,code,value in rows:
        key=(observed_period,code)
        if key in unique and abs(unique[key]-value)>1e-8:conflicts.add(key)
        unique[key]=value
    return [(observed_period,code,value) for (observed_period,code),value in sorted(unique.items()) if (observed_period,code) not in conflicts]


PARSERS = {'cpi': parse_cpi_article, 'ppi': parse_ppi_article, 'pmi': parse_pmi_article,
           'ip': parse_ip_article, 'retail': parse_retail_article,
           'fai': parse_fai_article, 'gdp': parse_gdp_article, 'econ': parse_econ_article,
           'profit': parse_industrial_profit_article, 'capacity': parse_capacity_article,
           'annual': parse_annual_livelihood_article}

# 同一轮组合更新可能在搜索服务失败后为多个类型扫描同一批发布列表；只在
# 进程内缓存已读取的公开 HTML，避免重复请求，不写入数据库也不改变数据来源。
_RELEASE_LIST_PAGE_CACHE = {}


def discover_release_list_releases(kind, start_year, end_year=None, max_pages=90,
                                   sleep_seconds=0.2):
    """从统计局公开发布列表补充站内搜索不可用时的发布发现。

    这是公开列表的低频兜底，不是反爬绕过：只访问 ``/sj/zxfb/index_N.html``，
    不提交验证码、不调用隐藏接口。列表标题的统计期仍必须通过该类型的严格
    ``period_fn``，所以无关稿件和无法确定统计期的链接会被丢弃。
    """
    spec = RELEASES[kind]
    end_year = int(end_year or datetime.now().year)
    start_year = int(start_year)
    found = {}
    for index in range(max(1, int(max_pages))):
        page_url = NBS_LIST_URL + ('index.html' if index == 0 else f'index_{index}.html')
        if index not in _RELEASE_LIST_PAGE_CACHE:
            try:
                response = requests.get(page_url, headers=UA,
                                        timeout=min(HTTP_TIMEOUT, 8))
                if response.status_code == 404:
                    _RELEASE_LIST_PAGE_CACHE[index] = None
                    break
                response.raise_for_status()
                response.encoding = 'utf-8'
                _RELEASE_LIST_PAGE_CACHE[index] = response.text
            except Exception:
                # 列表页是可选的发现来源；已发现的链接可以安全返回，不能因最后
                # 一页的网络错误清空已有结果。
                _RELEASE_LIST_PAGE_CACHE[index] = None
                break
        html = _RELEASE_LIST_PAGE_CACHE[index]
        if html is None:
            break
        soup = BeautifulSoup(html, 'html.parser')
        for link in soup.find_all('a', href=True):
            title = re.sub(r'\s+', '', link.get_text(' ', strip=True))
            if spec['query'] not in title and not (
                    kind == 'econ' and re.search(r'经济(?:运行|发展)',title)):
                continue
            href = link['href'].strip()
            if href.startswith('./'):
                href = NBS_LIST_URL + href[2:]
            elif href.startswith('/'):
                href = 'https://www.stats.gov.cn' + href
            if not href.startswith('https://www.stats.gov.cn/'):
                continue
            period = spec['period_fn'](title, href)
            if not period or not re.fullmatch(r'20\d{2}-\d{2}', period):
                continue
            year = int(period[:4])
            if not start_year <= year <= end_year:
                continue
            current = found.get(period)
            if current is None or _release_path_rank(href) < _release_path_rank(current[0]):
                found[period] = (href, title)
        time.sleep(sleep_seconds)
    return found


def discover_releases(kind, start_year, end_year=None, max_pages=6, sleep_seconds=0.35,
                      workers=1):
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
    workers = max(1, min(3, int(workers or 1)))

    def search(job):
        year, page = job
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
        return year, page, payload

    try:
        # 年份模式的搜索页彼此独立，可温和并发；flat 模式必须按页顺序遇空即停。
        if workers > 1 and not spec.get('flat_pages'):
            with ThreadPoolExecutor(max_workers=workers) as executor:
                search_results = list(executor.map(search, year_pages))
        else:
            search_results = []
            exhausted_years = set()
            for job in year_pages:
                year, page = job
                if year in exhausted_years:
                    continue
                result = search(job)
                search_results.append(result)
                payload = result[2]
                if (not int(payload.get('currentHits') or 0)
                        or page * 20 >= int(payload.get('totalHits') or 0)):
                    exhausted_years.add(year)
                time.sleep(sleep_seconds)
    except Exception:
        found.update(discover_release_list_releases(kind, start_year, end_year,
                                                    max_pages=70))
        search_results=[]

    for year, page, payload in search_results:
        docs = payload.get('resultDocs') or []
        for doc in docs:
            data = doc.get('data', doc)
            title = re.sub(r'<[^>]+>', '', str(data.get('title') or '')).strip()
            url = data.get('url') or ''
            period = spec['period_fn'](title, url) if url else None
            if not period:
                continue
            # 站内搜索按年份查询仍会混入高相关度旧稿；年模式必须二次校验，
            # 否则“增量更新”会意外从十多年前开始并显著拖慢任务。
            if year is not None and int(period[:4]) != int(year):
                continue
            current = found.get(period)
            if current is None or _release_path_rank(url) < _release_path_rank(current[0]):
                found[period] = (url, title)
    if kind == 'econ' and ECON_RELEASE_MANIFEST_PATH.exists():
        with ECON_RELEASE_MANIFEST_PATH.open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                period = row['period']
                if int(start_year) <= int(period[:4]) <= end_year:
                    found.setdefault(period, (row['source_url'], row['source_title']))
    return found


def sync_annual_macro_snapshots(conn):
    """把仓库内已核验的统计局年度快照接入统一宏观表。

    人口和居民收入复用住房结构模块的同一份原始快照；就业数据单独保存在
    china_macro_annual_official.csv。这里不修改原始 CSV，只做幂等复制。
    """
    rows = []
    if STRUCTURAL_DRIVER_PATH.exists():
        mapping = {
            'national_population': 'CN_POPULATION',
            'national_disposable_income': 'CN_DISPOSABLE_INCOME',
        }
        with STRUCTURAL_DRIVER_PATH.open('r', encoding='utf-8-sig', newline='') as handle:
            for raw in csv.DictReader(handle):
                code = mapping.get((raw.get('indicator_code') or '').strip())
                if not code:
                    continue
                rows.append({
                    'indicator_code': code, 'period': (raw.get('period') or '').strip(),
                    'value': raw.get('value'), 'data_status': raw.get('data_status') or 'official',
                    'source_name': raw.get('source_name') or SOURCE_NAME,
                    'source_url': raw.get('source_url') or '',
                    'source_title': '国家统计局年度指标快照',
                    'parser_notes': raw.get('parser_notes') or '复用住房结构驱动官方快照',
                })
    if ANNUAL_MACRO_PATH.exists():
        with ANNUAL_MACRO_PATH.open('r', encoding='utf-8-sig', newline='') as handle:
            rows.extend(dict(raw) for raw in csv.DictReader(handle))
    if OFFICIAL_BACKFILL_PATH.exists():
        with OFFICIAL_BACKFILL_PATH.open('r', encoding='utf-8-sig', newline='') as handle:
            rows.extend(dict(raw) for raw in csv.DictReader(handle))
    if ANNUAL_SUPPLEMENT_PATH.exists():
        with ANNUAL_SUPPLEMENT_PATH.open('r', encoding='utf-8-sig', newline='') as handle:
            rows.extend(dict(raw) for raw in csv.DictReader(handle))

    now, upserted = datetime.now().isoformat(), 0
    for raw in rows:
        code = (raw.get('indicator_code') or '').strip()
        period = (raw.get('period') or '').strip()
        period_match = re.fullmatch(r'((?:19|20)\d{2})(?:-(\d{2}))?', period)
        if code not in INDICATORS or not period_match:
            continue
        if period_match.group(2) and not 1 <= int(period_match.group(2)) <= 12:
            continue
        try:
            value = float(raw.get('value'))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or not (raw.get('source_url') or '').strip():
            continue
        name, unit, frequency = INDICATORS[code]
        cur = conn.execute('''INSERT INTO china_macro_observations (
            indicator_code,indicator_name,period,value,unit,frequency,data_status,
            source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(indicator_code,period) DO UPDATE SET
            value=excluded.value, indicator_name=excluded.indicator_name,
            unit=excluded.unit, frequency=excluded.frequency,
            data_status=excluded.data_status, source_name=excluded.source_name,
            source_type=excluded.source_type, source_url=excluded.source_url,
            source_title=excluded.source_title, parser_notes=excluded.parser_notes,
            updated_at=excluded.updated_at''',
            (code, name, period, value, unit, frequency,
             (raw.get('data_status') or 'official').strip(),
             (raw.get('source_name') or SOURCE_NAME).strip(), 'china_macro_annual',
             (raw.get('source_url') or '').strip(),
             (raw.get('source_title') or '国家统计局年度指标快照').strip(),
             (raw.get('parser_notes') or '').strip(), None, now))
        upserted += cur.rowcount
    conn.commit()
    return upserted


def _fetch_macro_release(kind, period, url, title, timeout=HTTP_TIMEOUT, archive_root=None):
    response=None
    evidence=None
    original_url=url
    try:
        url=nbs_https_url(url)
        response = requests.get(url, headers=UA, timeout=timeout,stream=True)
        response.raise_for_status()
        content=bytearray()
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content)>NBS_RELEASE_MAX_BYTES:
                raise ValueError('NBS response exceeded the bounded16-MB download limit.')
        response._content=bytes(content)
        response._content_consumed=True
        response.encoding = 'utf-8'
        evidence=archive_nbs_release(response.content,response.url,original_url=original_url,
                                     kind=kind,period_hint=period,title=title,
                                     parser_version=PARSER_VERSION,parser_sha256=PARSER_CODE_SHA256,
                                     root=archive_root,http_status=response.status_code)
        url=nbs_https_url(response.url)
        if kind in ('cpi','ppi') and evidence.get('reported_period') and evidence['reported_period']!=period:
            raise ValueError('Price-table reporting period differs from the discovered period; no upsert.')
        if kind == 'econ':
            validated = econ_period_from_article(response.text, title, url)
            if not validated:
                raise ValueError('国民经济稿缺少可核对的资料年/月；不采用迁移地址年份。')
            period = validated
        values = PARSERS[kind](response.text, period=period) if kind == 'econ' else PARSERS[kind](response.text)
        survey_observations = []
        if kind == 'econ':
            survey_observations = parse_econ_unemployment_observations(response.text, period)
            # Drop a target-period rate when the exact-month parser found conflicting
            # statements. Preserve other economic indicators and their original grain.
            values = {code: value for code, value in values.items()
                      if code not in ('CN_UNEMP_SURVEY', 'CN_UNEMP_31_CITIES')}
            values.update({code: value for observed_period, code, value in survey_observations
                           if observed_period == period})
        return period, url, title, values, survey_observations, None, evidence
    except Exception as exc:
        return period, url, title, {}, [], str(exc), evidence
    finally:
        if response is not None:response.close()


def _upsert_captured_macro_observation(conn, code, period, value, url, title, notes, now, evidence):
    """Persist evidence with the value; preserve full originals before any replacement."""
    if not evidence or not re.fullmatch(r'[0-9a-f]{64}',evidence.get('raw_sha256') or ''):
        raise ValueError('An observation cannot be official before its original bytes are archived.')
    name,unit,frequency=INDICATORS[code]
    old=conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                     (code,period)).fetchone()
    old=dict(old) if old else None
    released=evidence.get('release_date') or (old or {}).get('release_date')
    if evidence.get('access_mode')=='archived_response_replay':
        notes+=';access_mode=archived_response_replay'
    row={'indicator_code':code,'indicator_name':name,'period':period,'value':value,'unit':unit,
         'frequency':frequency,'data_status':'official','source_name':SOURCE_NAME,'source_type':SOURCE_TYPE,
         'source_url':url,'source_title':title,'parser_notes':notes,'formula':None,
         'updated_at':now,'parser_version':PARSER_VERSION,'release_date':released,
         'retrieved_at':evidence['retrieved_at'],'raw_sha256':evidence['raw_sha256'],
         'source_page_created_date':evidence.get('source_page_created_date') or (old or {}).get('source_page_created_date'),
         'release_date_not_provided':0 if released else evidence.get('release_date_not_provided',0),
         'release_date_reason':None if released else evidence.get('release_date_reason'),
         'original_value':(old or {}).get('original_value')}
    if old and old['value']!=value and row['original_value'] is None:
        row['original_value']=old['value']
    if old and all(old.get(k)==v for k,v in row.items() if k!='updated_at'):
        return 0
    if old:preserve_prior_observation(evidence,old)
    columns=tuple(row)
    updates=','.join(k+'=excluded.'+k for k in columns if k not in ('indicator_code','period'))
    conn.execute('INSERT INTO china_macro_observations ('+','.join(columns)+') VALUES ('+
                 ','.join('?' for _ in columns)+') ON CONFLICT(indicator_code,period) DO UPDATE SET '+updates,
                 tuple(row.values()))
    return 1


def _public_capture_record(evidence,url):
    return {'source_url':url,'raw_sha256':evidence['raw_sha256'],
            'raw_archive_ref':evidence['raw_archive_ref'],'capture_version':CAPTURE_VERSION,
            'access_mode':evidence.get('access_mode','http_response')}


def _persist_captured_release(conn, period, url, title, values, survey_observations, evidence, repair=False):
    """Commit one release atomically; a later persistence failure cannot report partial writes."""
    observations={(period,code):value for code,value in values.items()}
    observations.update({(observed_period,code):value for observed_period,code,value in survey_observations})
    count=0;now=datetime.now().isoformat()
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        for (observed_period,code),value in observations.items():
            if code not in INDICATORS:
                continue
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('Only finite actually parsed values can be persisted.')
            notes='统计局新闻稿正文解析;'+('字段修复;' if repair else '')+'上涨/下降定号,持平=0'
            if observed_period!=period:
                notes+=';该月份由原文逐月明示，非累计值或期间均值拆分'
            count+=_upsert_captured_macro_observation(conn,code,observed_period,value,url,title,notes,now,evidence)
    return count


def repair_existing_release_fields(db_path, kind, workers=1, fetch_timeout=None, archive_root=None):
    """用库内已验证的官方 URL 修复同一新闻稿中后来补上的字段。

    发现服务不可用时，历史记录本身仍保留每期 ``source_url``；优先复用这些
    URL 比重新搜索更小、更可审计。当前主要用于 PPI 生产/生活资料和固定资产
    投资年度稿。只 upsert 解析到的字段，页面不可达或正文缺字段均不清旧值。
    """
    if kind not in RELEASES:
        raise ValueError(f'未知中国宏观发布类型: {kind}')
    spec = RELEASES[kind]
    codes = _kind_codes(kind)
    fetch_timeout = float(fetch_timeout or HTTP_TIMEOUT)
    errors, upserted, captures = [], 0, []
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        # 选该类已有记录最多的指标作为新闻稿 URL 锚点；不依赖某个字段一定存在。
        anchor = conn.execute(
            'SELECT indicator_code FROM china_macro_observations '
            'WHERE indicator_code IN (' + ','.join('?' * len(codes)) + ') '
            'GROUP BY indicator_code ORDER BY COUNT(*) DESC LIMIT 1', codes).fetchone()
        if not anchor:
            return {'success': True, 'records_upserted': 0, 'errors': [], 'source_archives':[]}
        candidates = conn.execute(
            'SELECT period,source_url,source_title FROM china_macro_observations '
            'WHERE indicator_code=? AND source_url IS NOT NULL AND source_url<>? '
            'ORDER BY period', (anchor[0], '')).fetchall()
        pending = []
        for row in candidates:
            have = conn.execute(
                'SELECT COUNT(*) FROM china_macro_observations WHERE period=? '
                'AND indicator_code IN (' + ','.join('?' * len(codes)) + ')',
                (row['period'], *codes)).fetchone()[0]
            parsed = conn.execute('SELECT 1 FROM china_macro_observations WHERE period=? '
                                  'AND indicator_code=? AND parser_version=? LIMIT 1',
                                  (row['period'], anchor[0], PARSER_VERSION)).fetchone()
            if have < len(codes) and not parsed:
                pending.append((kind, row['period'], row['source_url'],
                                row['source_title'] or '', fetch_timeout, archive_root))
        if workers > 1 and len(pending) > 1:
            with ThreadPoolExecutor(max_workers=max(1, min(4, int(workers)))) as executor:
                results = list(executor.map(lambda args: _fetch_macro_release(*args), pending))
        else:
            results = [_fetch_macro_release(*args) for args in pending]
        for period, url, title, values, survey_observations, error, evidence in results:
            if evidence:captures.append(_public_capture_record(evidence,url))
            if error:
                errors.append(f'{kind} {period}: {error}')
                continue
            try:
                upserted+=_persist_captured_release(conn,period,url,title,values,survey_observations,evidence,repair=True)
            except Exception as exc:
                errors.append(f'{kind} {period} persist: {exc}')
    return {'success': not errors or upserted > 0, 'records_upserted': upserted,
            'errors': errors,'source_archives':captures}


def update_china_macro(db_path, start_year=None, sleep_seconds=0.3, kinds=None,
                       workers=1, discover_max_pages=3, fetch_timeout=None, archive_root=None):
    """抓取并入库;默认只查今年+去年(增量),start_year 指定则深回填。
    单篇失败只记录,不影响其他;绝不清旧数据。"""
    started = datetime.now().isoformat()
    this_year = datetime.now().year
    start = int(start_year or this_year - 1)
    workers = max(1, min(4, int(workers or 1)))
    fetch_timeout = float(fetch_timeout or HTTP_TIMEOUT)
    errors, upserted, captures = [], 0, []
    selected_kinds = tuple(kinds or RELEASES.keys())
    unknown = [kind for kind in selected_kinds if kind not in RELEASES]
    if unknown:
        raise ValueError(f'未知中国宏观发布类型: {unknown}')
    # 解析规则升级后，优先用库内既有 URL 修复字段缺口；这一步只对有已知
    # 历史口径问题的类型启用，不让每次普通增量更新重复扫描所有旧稿。
    for repair_kind in ('cpi', 'ppi', 'fai'):
        if repair_kind in selected_kinds:
            repaired = repair_existing_release_fields(
                db_path, repair_kind, workers=workers, fetch_timeout=fetch_timeout,archive_root=archive_root)
            upserted += int(repaired.get('records_upserted') or 0)
            errors.extend(repaired.get('errors') or [])
            captures.extend(repaired.get('source_archives') or [])
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        upserted += sync_annual_macro_snapshots(conn)
        for kind in selected_kinds:
            try:
                releases = discover_releases(
                    kind, start, max_pages=max(1, min(6, int(discover_max_pages or 3))),
                    workers=workers)
            except Exception as exc:
                errors.append(f'{kind} discover: {exc}')
                continue
            pending = []
            for period in sorted(releases):
                url, title = releases[period]
                codes = _kind_codes(kind)
                have = conn.execute(
                    'SELECT COUNT(*) FROM china_macro_observations WHERE period=? '
                    f'AND indicator_code IN ({",".join("?"*len(codes))})',
                    (period, *codes)).fetchone()[0]
                parsed = conn.execute('SELECT 1 FROM china_macro_observations WHERE period=? '
                                      'AND indicator_code IN (' + ','.join('?' * len(codes)) + ') '
                                      'AND parser_version=? LIMIT 1',
                                      (period, *codes, PARSER_VERSION)).fetchone()
                if have >= len(codes) or parsed:
                    continue
                pending.append((kind, period, url, title, fetch_timeout,archive_root))
            if workers > 1 and len(pending) > 1:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    fetched = executor.map(lambda args: _fetch_macro_release(*args), pending)
                    results = list(fetched)
            else:
                results = [_fetch_macro_release(*args) for args in pending]
            for period, url, title, values, survey_observations, error, evidence in results:
                if evidence:captures.append(_public_capture_record(evidence,url))
                if error:
                    errors.append(f'{kind} {period}: {error}')
                    continue
                try:
                    upserted+=_persist_captured_release(conn,period,url,title,values,survey_observations,evidence)
                except Exception as exc:
                    errors.append(f'{kind} {period} persist: {exc}')
                if workers == 1:
                    time.sleep(sleep_seconds)
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(),
            'records_upserted': upserted, 'errors': errors,'source_archives':captures}
