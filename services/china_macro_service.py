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
import csv
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

SOURCE_NAME = '国家统计局'
SOURCE_TYPE = 'china_macro'

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
    'CN_DEATHS': ('死亡人口', '万人', 'annual'),
    'CN_BIRTH_RATE': ('人口出生率', '‰', 'annual'),
    'CN_DEATH_RATE': ('人口死亡率', '‰', 'annual'),
    'CN_NATURAL_GROWTH_RATE': ('人口自然增长率', '‰', 'annual'),
}

_ROOT = Path(__file__).resolve().parents[1]
ANNUAL_MACRO_PATH = _ROOT / 'data' / 'china_macro_annual_official.csv'
OFFICIAL_BACKFILL_PATH = _ROOT / 'data' / 'china_macro_official_backfill.csv'
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
    existing_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(china_macro_observations)')}
    for name, definition in (
            ('release_date', 'TEXT'),
            ('retrieved_at', 'TEXT'),
            ('raw_sha256', 'TEXT'),
            ('parser_version', 'TEXT'),
            ('missing_reason', 'TEXT'),
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
    m = re.search(prefix + r'同比(上涨|下降)([\d.]+)%', text)
    if m:
        yoy, yoy_end = _signed(m.group(1), m.group(2)), m.end()
    else:
        m = re.search(prefix + r'同比持平', text)
        if m:
            yoy, yoy_end = 0.0, m.end()
        else:
            # 早年 PPI 稿件常把“环比”放在“同比”前：
            # “出厂价格环比下降0.5%，同比下降5.3%”。
            m = re.search(prefix + r'环比(?:上涨|下降|持平)[\d.]*%?[，,]?'
                          r'同比(上涨|下降)([\d.]+)%', text)
            if m:
                yoy, yoy_end = _signed(m.group(1), m.group(2)), m.end()
    m = re.search(prefix + r'环比(上涨|下降)([\d.]+)%', text)
    if m:
        mom = _signed(m.group(1), m.group(2))
    elif re.search(prefix + r'环比(?:与上月)?持平', text):
        mom = 0.0
    elif yoy_end is not None:
        window = text[yoy_end:yoy_end + 80]
        m = re.search(r'环比(上涨|下降)([\d.]+)%', window)
        if m:
            mom = _signed(m.group(1), m.group(2))
        elif re.search(r'环比(?:与上月)?持平', window):
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
    yoy_section = text.split('二、工业生产者价格环比变动情况', 1)[0]
    match = re.search(r'生产资料价格[^。]{0,40}?(上涨|下降)([\d.]+)%', yoy_section)
    if match:
        out['CN_PPI_PRODUCTION_YOY'] = _signed(match.group(1), match.group(2))
    elif re.search(r'生产资料价格[^。]{0,40}?同比持平', yoy_section):
        out['CN_PPI_PRODUCTION_YOY'] = 0.0
    match = re.search(r'生活资料价格[^。]{0,40}?(上涨|下降)([\d.]+)%', yoy_section)
    if match:
        out['CN_PPI_LIVING_YOY'] = _signed(match.group(1), match.group(2))
    elif re.search(r'生活资料价格[^。]{0,40}?同比持平', yoy_section):
        out['CN_PPI_LIVING_YOY'] = 0.0
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
                value = _number_cell(cells[1])
                if value is not None:
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
                    kind == 'econ' and '国民经济运行' in title):
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
        return discover_release_list_releases(kind, start_year, end_year,
                                               max_pages=70)

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


def _fetch_macro_release(kind, period, url, title, timeout=HTTP_TIMEOUT):
    try:
        response = requests.get(url, headers=UA, timeout=timeout)
        response.raise_for_status()
        response.encoding = 'utf-8'
        return period, url, title, PARSERS[kind](response.text), None
    except Exception as exc:
        return period, url, title, {}, str(exc)


def repair_existing_release_fields(db_path, kind, workers=1, fetch_timeout=None):
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
    errors, upserted = [], 0
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        # 选该类已有记录最多的指标作为新闻稿 URL 锚点；不依赖某个字段一定存在。
        anchor = conn.execute(
            'SELECT indicator_code FROM china_macro_observations '
            'WHERE indicator_code IN (' + ','.join('?' * len(codes)) + ') '
            'GROUP BY indicator_code ORDER BY COUNT(*) DESC LIMIT 1', codes).fetchone()
        if not anchor:
            return {'success': True, 'records_upserted': 0, 'errors': []}
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
            if have < len(codes):
                pending.append((kind, row['period'], row['source_url'],
                                row['source_title'] or '', fetch_timeout))
        if workers > 1 and len(pending) > 1:
            with ThreadPoolExecutor(max_workers=max(1, min(4, int(workers)))) as executor:
                results = list(executor.map(lambda args: _fetch_macro_release(*args), pending))
        else:
            results = [_fetch_macro_release(*args) for args in pending]
        for period, url, title, values, error in results:
            if error:
                errors.append(f'{kind} {period}: {error}')
                continue
            now = datetime.now().isoformat()
            for code, value in values.items():
                if code not in INDICATORS:
                    continue
                name, unit, freq = INDICATORS[code]
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
                    (code, name, period, value, unit, freq, 'official', SOURCE_NAME,
                     SOURCE_TYPE, url, title,
                     '统计局新闻稿正文解析;字段修复;上涨/下降定号,持平=0', None, now))
                upserted += cur.rowcount
            conn.commit()
    return {'success': not errors or upserted > 0, 'records_upserted': upserted,
            'errors': errors}


def update_china_macro(db_path, start_year=None, sleep_seconds=0.3, kinds=None,
                       workers=1, discover_max_pages=3, fetch_timeout=None):
    """抓取并入库;默认只查今年+去年(增量),start_year 指定则深回填。
    单篇失败只记录,不影响其他;绝不清旧数据。"""
    started = datetime.now().isoformat()
    this_year = datetime.now().year
    start = int(start_year or this_year - 1)
    workers = max(1, min(4, int(workers or 1)))
    fetch_timeout = float(fetch_timeout or HTTP_TIMEOUT)
    errors, upserted = [], 0
    selected_kinds = tuple(kinds or RELEASES.keys())
    unknown = [kind for kind in selected_kinds if kind not in RELEASES]
    if unknown:
        raise ValueError(f'未知中国宏观发布类型: {unknown}')
    # 解析规则升级后，优先用库内既有 URL 修复字段缺口；这一步只对有已知
    # 历史口径问题的类型启用，不让每次普通增量更新重复扫描所有旧稿。
    for repair_kind in ('cpi', 'ppi', 'fai'):
        if repair_kind in selected_kinds:
            repaired = repair_existing_release_fields(
                db_path, repair_kind, workers=workers, fetch_timeout=fetch_timeout)
            upserted += int(repaired.get('records_upserted') or 0)
            errors.extend(repaired.get('errors') or [])
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
                if have >= len(codes):
                    continue
                pending.append((kind, period, url, title, fetch_timeout))
            if workers > 1 and len(pending) > 1:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    fetched = executor.map(lambda args: _fetch_macro_release(*args), pending)
                    results = list(fetched)
            else:
                results = [_fetch_macro_release(*args) for args in pending]
            for period, url, title, values, error in results:
                if error:
                    errors.append(f'{kind} {period}: {error}')
                    continue
                now = datetime.now().isoformat()
                for code, value in values.items():
                    name, unit, freq = INDICATORS[code]
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
                        (code, name, period, value, unit, freq, 'official',
                         SOURCE_NAME, SOURCE_TYPE, url, title,
                         '统计局新闻稿正文解析;上涨/下降定号,持平=0', None, now))
                    upserted += cur.rowcount
                conn.commit()
                if workers == 1:
                    time.sleep(sleep_seconds)
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(),
            'records_upserted': upserted, 'errors': errors}
