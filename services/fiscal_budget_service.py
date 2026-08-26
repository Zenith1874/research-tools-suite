# -*- coding: utf-8 -*-
"""全国财政收支模块：一般公共预算收入/支出 + 政府性基金收入/支出(月度累计 YTD)。

数据源：财政部国库司"财政收支情况"月度报告(gks.mof.gov.cn/tongjishuju/)。
口径说明：官方报告为年初至今累计值；差额=收入-支出 为 derived(带公式)，
不等于官方"赤字"(官方赤字按预算口径含调入资金/结转结余等)。
数据纪律：逐条 official + 报告原文 source_url；解析失败只记日志不清旧数据。
"""
import html
import math
import random
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
# gks.mof.gov.cn 的索引页在部分网络环境会返回 502；财政部主站保留同一份
#“全国财政收支情况”归档目录，作为发现报告的备用入口。报告原文 URL 仍保留
# 财政部国库司原链接，不把主站目录误当成数据来源。
ARCHIVE_INDEX_URL = (
    'https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/'
    'quanguocaizhengshouzhiqingkuang/index.html'
)

INDICATORS = {
    'general_budget_revenue_ytd':  '全国一般公共预算收入(YTD)',
    'general_budget_revenue_ytd_yoy_official': '全国一般公共预算收入同比(官方可比口径)',
    'general_budget_expenditure_ytd': '全国一般公共预算支出(YTD)',
    'general_budget_expenditure_ytd_yoy_official': '全国一般公共预算支出同比(官方可比口径)',
    'general_budget_balance_ytd': '全国一般公共预算收支差额(YTD)',
    'gov_fund_revenue_ytd': '全国政府性基金预算收入(YTD)',
    'gov_fund_expenditure_ytd': '全国政府性基金预算支出(YTD)',
    'gov_fund_revenue_ytd_yoy_official': '全国政府性基金预算收入同比(官方可比口径)',
    'gov_fund_expenditure_ytd_yoy_official': '全国政府性基金预算支出同比(官方可比口径)',
    'govfund_land_transfer_revenue_ytd': '国有土地使用权出让收入(YTD)',
    'govfund_land_transfer_revenue_ytd_yoy_official': '国有土地使用权出让收入同比(官方可比口径)',
    'budget_interest_expenditure_ytd': '全国债务付息支出(YTD)',
    'budget_interest_expenditure_ytd_yoy_official': '全国债务付息支出同比(官方可比口径)',
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
    'general_budget_revenue_ytd_yoy_official',
    'general_budget_expenditure_ytd_yoy_official',
    'gov_fund_revenue_ytd_yoy_official',
    'gov_fund_expenditure_ytd_yoy_official',
    'govfund_land_transfer_revenue_ytd',
    'govfund_land_transfer_revenue_ytd_yoy_official',
    'budget_interest_expenditure_ytd',
    'budget_interest_expenditure_ytd_yoy_official',
)

OFFICIAL_YOY_INDICATORS = (
    'general_budget_revenue_ytd_yoy_official',
    'general_budget_expenditure_ytd_yoy_official',
    'gov_fund_revenue_ytd_yoy_official',
    'gov_fund_expenditure_ytd_yoy_official',
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

# Official annual documents that sit outside the monthly Treasury archive.
# These are kept as a small, source-linked supplement so the annual table can
# cover the historical years that the current monthly archive discovery misses.
# 2007-2008 are intentionally absent: no directly verified comparable national
# fiscal amount is inserted from media, research, or contract-price series.
LAND_TRANSFER_ANNUAL_OFFICIAL_BACKFILL = (
    {
        'year': 2009, 'value': 13964.76,
        'source_url': 'https://www.mof.gov.cn/zhuantihuigu/10nianyusuanbaogao/'
                      'yusuanbaogao10/201004/t20100413_286891.htm',
        'source_title': '关于2009年中央和地方预算执行情况与2010年中央和地方预算草案的报告',
        'parser_notes': '财政部报告披露的地方政府性基金本级收入中的国有土地使用权出让收入；单位：亿元。',
    },
    {
        'year': 2010, 'value': 29397.98,
        'source_url': 'https://www.mof.gov.cn/zhuantihuigu/czjbqk2010/3czsr/'
                      '201110/t20111031_603359.htm',
        'source_title': '全国土地出让收入管理及使用情况（2010年）',
        'parser_notes': '财政部披露的2010年全国实际缴入地方国库土地出让收入；单位：亿元。',
    },
    {
        'year': 2011, 'value': 33477.0,
        'source_url': 'https://www.mof.gov.cn/zhuantihuigu/czjbqk2011/czsr2011/'
                      '201208/t20120831_679821.htm',
        'source_title': '全国土地出让收入管理及使用情况（2011年）',
        'parser_notes': '财政部披露的2011年全国缴入国库土地出让收入；单位：亿元。',
    },
    {
        'year': 2012, 'value': 27404.01,
        'source_url': 'https://m.mof.gov.cn/czxw/201303/t20130319_782332.htm',
        'source_title': '关于2012年中央和地方预算执行情况与2013年中央和地方预算草案的报告',
        'parser_notes': '财政部报告披露的地方政府性基金本级收入中的国有土地使用权出让收入；单位：亿元。',
    },
    {
        'year': 2013, 'value': 41249.52,
        'source_url': 'https://m.mof.gov.cn/czxw/201403/t20140315_1055691.htm',
        'source_title': '关于2013年中央和地方预算执行情况与2014年中央和地方预算草案的报告',
        'parser_notes': '财政部报告披露的地方政府性基金本级收入中的国有土地使用权出让收入；单位：亿元。',
    },
    {
        'year': 2014, 'value': 42940.30,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/'
                      '201503/t20150325_1206491.htm',
        'source_title': '去年4万多亿元土地出让收入超8成用于拆迁征地等补偿',
        'parser_notes': '财政部公布的2014年全国土地出让收入；单位：亿元。',
    },
    {
        'year': 2015, 'value': 33657.73,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caijingshidian/'
                      'renminwang/201604/t20160406_1937647.htm',
        'source_title': '土地出让收支双降',
        'parser_notes': '财政部公布的2015年全国缴入国库土地出让收入；单位：亿元。',
    },
    {
        'year': 2018, 'value': 65168.26,
        'source_url': 'https://yss.mof.gov.cn/2018czjs/201907/t20190718_3303323.htm',
        'source_title': '2018年地方政府性基金收入决算表',
        'parser_notes': '财政部地方政府性基金收入决算表注释口径：国有土地使用权出让金收入、国有土地收益基金收入、农业土地开发资金收入合计；单位：亿元。',
    },
    {
        'year': 2019, 'value': 72584.42,
        'source_url': 'https://m.mof.gov.cn/czsj/202005/t20200523_3518993.htm',
        'source_title': '关于2019年中央和地方预算执行情况与2020年中央和地方预算草案的报告（摘要）',
        'parser_notes': '财政部报告披露的地方政府性基金预算本级收入中的国有土地使用权出让收入；单位：亿元。',
    },
)

# The Treasury index published the 2026 Jan-Jul release on 2026-08-21.  Keep
# this source-linked supplement because the article body can be intermittently
# unavailable from the runtime network even when the official index is
# available.  It is not a replacement for the parser: the normal updater still
# discovers and parses the report when the source responds, while this
# idempotent supplement prevents a transient 502 from leaving the current-year
# forecast anchored to June.
LATEST_OFFICIAL_FISCAL_BUDGET_BACKFILL = (
    {
        'period': '2026-07',
        'source_url': 'https://gks.mof.gov.cn/tongjishuju/202608/t20260814_3995497.htm',
        'source_title': '2026年1-7月财政收支情况',
        'parser_notes': (
            '财政部国库司2026年1-7月财政收支情况；数值为年初至今累计，'
            '同比为财政部公布的可比口径；单位：亿元。'
        ),
        'values': {
            'general_budget_revenue_ytd': 143696.0,
            'general_budget_revenue_ytd_yoy_official': 5.8,
            'general_budget_expenditure_ytd': 162889.0,
            'general_budget_expenditure_ytd_yoy_official': 1.3,
            'gov_fund_revenue_ytd': 18219.0,
            'gov_fund_revenue_ytd_yoy_official': -21.2,
            'gov_fund_expenditure_ytd': 45410.0,
            'gov_fund_expenditure_ytd_yoy_official': -16.4,
            'govfund_land_transfer_revenue_ytd': 11731.0,
            'govfund_land_transfer_revenue_ytd_yoy_official': -30.8,
            'budget_interest_expenditure_ytd': 7966.0,
            'budget_interest_expenditure_ytd_yoy_official': 5.2,
        },
    },
)

# Annual statutory fiscal deficit figures published in the Ministry of
# Finance's annual budget execution reports.  These are deliberately kept
# separate from the monthly Treasury YTD balance (revenue - expenditure): the
# latter is a cash-flow/accounting gap, while the statutory deficit incorporates
# budget transfers, carry-over funds, and other budget-balance adjustments.
OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR = 'official_national_fiscal_deficit'
OFFICIAL_NATIONAL_FISCAL_DEFICIT_LABEL = '全国法定财政赤字（财政部年度报告）'
OFFICIAL_NATIONAL_FISCAL_DEFICIT_SOURCE_NAME = '财政部年度预算报告'
OFFICIAL_NATIONAL_FISCAL_DEFICIT_SOURCE_TYPE = 'mof_annual_budget_report'
OFFICIAL_NATIONAL_FISCAL_DEFICIT_ANNUAL = (
    {
        'year': 2009, 'value': 9500.0,
        'source_url': 'https://www.mof.gov.cn/gkml/caizhengshuju/201006/t20100628_324488.htm',
        'source_title': '关于2009年中央决算的报告',
        'parser_notes': '全国财政收支相抵差额9500亿元；单位：亿元。',
    },
    {
        'year': 2010, 'value': 10000.0,
        'source_url': 'https://m.mof.gov.cn/czsj/201103/t20110317_505087.htm',
        'source_title': '关于2010年中央和地方预算执行情况与2011年中央和地方预算草案的报告',
        'parser_notes': '全国财政收支总量相抵差额10000亿元；单位：亿元。',
    },
    {
        'year': 2011, 'value': 8500.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/201203/t20120306_632884.htm',
        'source_title': '“国家账本”凸显“为国理财、为民服务”',
        'parser_notes': '财政部公开预算报告解读披露2011年全国财政收支相抵差额8500亿元；单位：亿元。',
    },
    {
        'year': 2012, 'value': 8000.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/201303/t20130319_782332.htm',
        'source_title': '关于2012年中央和地方预算执行情况与2013年中央和地方预算草案的报告',
        'parser_notes': '全国财政收支总量相抵差额8000亿元；单位：亿元。',
    },
    {
        'year': 2013, 'value': 12000.0,
        'source_url': 'https://www.mof.gov.cn/gkml/caizhengshuju/201406/t20140624_1103948.htm',
        'source_title': '关于2013年中央决算的报告',
        'parser_notes': '汇总中央和地方决算，全国公共财政收支差额12000亿元；单位：亿元。',
    },
    {
        'year': 2014, 'value': 13500.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/201506/t20150629_1262257.htm',
        'source_title': '国务院关于2014年中央决算的报告',
        'parser_notes': '汇总中央和地方决算，全国一般公共预算收支差额13500亿元；单位：亿元。',
    },
    {
        'year': 2015, 'value': 16200.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/201603/t20160306_1895173.htm',
        'source_title': '关于2015年中央和地方预算执行情况与2016年中央和地方预算草案的报告（摘要）',
        'parser_notes': '全国一般公共预算收支总量相抵赤字16200亿元；单位：亿元。',
    },
    {
        'year': 2016, 'value': 21800.0,
        'source_url': 'https://www.mof.gov.cn/gkml/caizhengshuju/201703/t20170317_2559812.htm',
        'source_title': '关于2016年中央和地方预算执行情况与2017年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算收支总量相抵赤字21800亿元；单位：亿元。',
    },
    {
        'year': 2017, 'value': 23800.0,
        'source_url': 'https://www.mof.gov.cn/gkml/caizhengshuju/201803/t20180323_2847996.htm',
        'source_title': '关于2017年中央和地方预算执行情况与2018年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算收支总量相抵赤字23800亿元；单位：亿元。',
    },
    {
        'year': 2018, 'value': 23800.0,
        'source_url': 'https://www.mof.gov.cn/gp/xxgkml/bgt/201904/t20190402_3210848.htm',
        'source_title': '关于2018年中央和地方预算执行情况与2019年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算收支总量相抵赤字23800亿元；单位：亿元。',
    },
    {
        'year': 2019, 'value': 27600.0,
        'source_url': 'https://m.mof.gov.cn/czsj/202005/t20200530_3523307.htm',
        'source_title': '关于2019年中央和地方预算执行情况与2020年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算收支总量相抵赤字27600亿元；单位：亿元。',
    },
    {
        'year': 2020, 'value': 37600.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202103/t20210314_3670203.htm',
        'source_title': '关于2020年中央和地方预算执行情况与2021年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算赤字37600亿元；单位：亿元。',
    },
    {
        'year': 2021, 'value': 35700.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202203/t20220314_3794760.htm',
        'source_title': '关于2021年中央和地方预算执行情况与2022年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算赤字35700亿元；单位：亿元。',
    },
    {
        'year': 2022, 'value': 33700.0,
        'source_url': 'https://www.mof.gov.cn/gkml/caizhengshuju/202303/t20230316_3872867.htm',
        'source_title': '关于2022年中央和地方预算执行情况与2023年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算赤字33700亿元；单位：亿元。',
    },
    {
        'year': 2023, 'value': 48800.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202403/t20240314_3930581.htm',
        'source_title': '关于2023年中央和地方预算执行情况与2024年中央和地方预算草案的报告',
        'parser_notes': '考虑四季度增发1万亿元国债并纳入中央财政赤字管理后的全国财政赤字48800亿元；单位：亿元。',
    },
    {
        'year': 2024, 'value': 40600.0,
        'source_url': 'https://m.mof.gov.cn/czxw/202503/t20250314_3959885.htm',
        'source_title': '关于2024年中央和地方预算执行情况与2025年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算赤字40600亿元；单位：亿元。',
    },
    {
        'year': 2025, 'value': 56600.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202603/t20260316_3985331.htm',
        'source_title': '关于2025年中央和地方预算执行情况与2026年中央和地方预算草案的报告',
        'parser_notes': '全国一般公共预算赤字56600亿元；单位：亿元。',
    },
)

# Current-year budget plan is not an actual deficit observation. It is exposed
# only in the current-year summary with an explicit ``official_plan`` status.
OFFICIAL_NATIONAL_FISCAL_DEFICIT_PLAN = (
    {
        'year': 2026, 'value': 58900.0,
        'source_url': 'https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/202603/t20260316_3985331.htm',
        'source_title': '关于2025年中央和地方预算执行情况与2026年中央和地方预算草案的报告',
        'parser_notes': '2026年全国一般公共预算赤字预算安排58900亿元；这是预算计划，不是2026年全年实际赤字。',
    },
)

# 官方报告披露的是 YTD 累计值。以下字段只在相邻 YTD 截止月都存在时由差分
# 得到，属于 derived，不回写 official observation 表。
MONTHLY_FLOW_FROM_YTD = {
    'general_budget_revenue_ytd': 'general_budget_revenue_monthly',
    'general_budget_expenditure_ytd': 'general_budget_expenditure_monthly',
    'gov_fund_revenue_ytd': 'gov_fund_revenue_monthly',
    'gov_fund_expenditure_ytd': 'gov_fund_expenditure_monthly',
}

MONTHLY_FLOW_INDICATORS = {
    'general_budget_revenue_monthly': '全国一般公共预算收入(当期流量)',
    'general_budget_expenditure_monthly': '全国一般公共预算支出(当期流量)',
    'gov_fund_revenue_monthly': '全国政府性基金收入(当期流量)',
    'gov_fund_expenditure_monthly': '全国政府性基金支出(当期流量)',
    'general_budget_balance_monthly': '全国一般公共预算收支差额(当期流量)',
    'gov_fund_balance_monthly': '全国政府性基金收支差额(当期流量)',
    'combined_budget_revenue_monthly': '两本账总收入(当期流量，简单相加)',
    'combined_budget_expenditure_monthly': '两本账总支出(当期流量，简单相加)',
    'combined_budget_balance_monthly': '两本账收支差额(当期流量，简单相加)',
    'combined_budget_expenditure_monthly_yoy': '财政全口径支出同比(同月，derived)',
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
    fund_revenue_yoy_match = re.search(
        r'全国(?:政府性基金预算收入|政府性基金收入)(?:为)?[\d.]+亿元'
        r'[^。；;]{0,36}?(?:同比|比上年同期|比上年)(增长|上升|下降)([\d.]+)%', t)
    if fund_revenue_yoy_match:
        sign = -1 if fund_revenue_yoy_match.group(1) == '下降' else 1
        out['gov_fund_revenue_ytd_yoy_official'] = round(
            sign * float(fund_revenue_yoy_match.group(2)), 4)
    total_yoy_patterns = {
        'general_budget_revenue_ytd_yoy_official':
            r'全国(?:一般公共预算收入|一般公共财政收入|公共财政收入)(?:为)?[\d.]+亿元',
        'general_budget_expenditure_ytd_yoy_official':
            r'全国(?:一般公共预算支出|一般公共财政支出|公共财政支出)(?:为)?[\d.]+亿元',
        'gov_fund_expenditure_ytd_yoy_official':
            r'全国(?:政府性基金预算支出|政府性基金支出)(?:为)?[\d.]+亿元',
    }
    for code, value_pattern in total_yoy_patterns.items():
        match = re.search(
            value_pattern + r'[^。；;]{0,36}?(?:同比|比上年同期|比上年)'
            r'(增长|上升|下降)([\d.]+)%', t)
        if match:
            sign = -1 if match.group(1) == '下降' else 1
            out[code] = round(sign * float(match.group(2)), 4)
    land_match = re.search(
        r'国有土地使用权出让收入(?!相关支出)(?:为)?([\d.]+)亿元'
        r'[^。；;]{0,36}?(?:同比|比上年同期|比上年)(增长|上升|下降)([\d.]+)%', t)
    if land_match:
        out['govfund_land_transfer_revenue_ytd'] = float(land_match.group(1))
        sign = -1 if land_match.group(2) == '下降' else 1
        out['govfund_land_transfer_revenue_ytd_yoy_official'] = round(
            sign * float(land_match.group(3)), 4)
    interest_match = re.search(
        r'债务付息支出(?:为)?([\d.]+)亿元'
        r'[^。；;]{0,36}?(?:同比|比上年同期|比上年)(增长|上升|下降)([\d.]+)%', t)
    if interest_match:
        out['budget_interest_expenditure_ytd'] = float(interest_match.group(1))
        sign = -1 if interest_match.group(2) == '下降' else 1
        out['budget_interest_expenditure_ytd_yoy_official'] = round(
            sign * float(interest_match.group(3)), 4)
    return derive_budget_values(out)


def parse_budget_index_links(page_html, page_url):
    """Parse an official MOF archive page into ``[(url, title)]``.

    The main MOF archive and the Treasury Department index use slightly
    different HTML quoting and link hosts.  The title is the stable key, so
    discovery accepts either form while excluding the archive's self-link.
    """
    links = []
    for match in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            page_html or '', flags=re.I | re.S):
        href, raw_title = match.groups()
        title = html.unescape(re.sub(r'<[^>]+>', ' ', raw_title))
        title = re.sub(r'\s+', ' ', title).strip()
        if '财政收支情况' not in title or title == '全国财政收支情况':
            continue
        resolved = urljoin(page_url, html.unescape(href.strip()))
        # The Treasury archive sometimes emits http links even though the same
        # official report is available over https; the http endpoint often
        # returns a gateway error from this environment.
        if resolved.startswith('http://gks.mof.gov.cn/'):
            resolved = 'https://' + resolved[len('http://'):]
        links.append((resolved, title))
    return links


def _budget_index_url(base_url, page):
    if page == 0:
        return base_url
    suffix = '.htm' if base_url.endswith('.htm') else '.html'
    stem = base_url[:-len(suffix)]
    return f'{stem}_{page}{suffix}'


def discover_budget_reports(max_pages=4):
    """Official index pages -> ``[(url, title)]``, newest first.

    The Treasury index is attempted first through both the Treasury host and
    the Ministry main-site archive.  This keeps discovery working when the
    Treasury host returns a transient gateway error, while each report still
    carries its original official source URL and is fetched independently.
    """
    page_specs = [
        (source_order, page, _budget_index_url(base, page))
        for source_order, base in enumerate((INDEX_URL, ARCHIVE_INDEX_URL))
        for page in range(max(1, int(max_pages)))
    ]
    links_by_page = {}

    def fetch_index(spec):
        source_order, page, url = spec
        try:
            response = requests.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': INDEX_URL,
            }, timeout=10)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'
            return source_order, page, parse_budget_index_links(response.text, url)
        except Exception:
            # A transient failure on one index must not hide the other official
            # archive. Individual report failures are surfaced by the updater.
            return source_order, page, []

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(page_specs)))) as executor:
        futures = [executor.submit(fetch_index, spec) for spec in page_specs]
        for future in as_completed(futures):
            source_order, page, page_links = future.result()
            links_by_page[(source_order, page)] = page_links
    links = [item for key in sorted(links_by_page) for item in links_by_page[key]]
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
    required = set(INDICATORS)
    # The explicit nationwide fund-revenue comparable-rate field was added to
    # this pipeline in 2026. Older reports remain useful even when their prose
    # does not expose a parseable official rate.
    if period < '2026-01':
        required.difference_update(OFFICIAL_YOY_INDICATORS)
    return required


def update_fiscal_budget(db_path, max_reports=30, full_history=False, sleep_seconds=0.5):
    """full_history=True 时深翻 23 页索引(新库重建 2010+ 年度史用);常规增量走默认 4 页。"""
    started = datetime.now().isoformat()
    errors, upserted = [], 0
    reports = discover_budget_reports(max_pages=23 if full_history else 4)
    with connect(db_path) as conn:
        ensure_fiscal_budget_tables(conn)
        now = datetime.now().isoformat()
        # Reuse every official report URL already attached to observations.
        # This is essential when an archive index temporarily omits/502s an
        # older page after a new field is added to the parser.
        report_map = {url: title for url, title in reports}
        for row in conn.execute('''SELECT source_url,MAX(source_title) FROM fiscal_budget_observations
            WHERE source_url LIKE 'http%' GROUP BY source_url'''):
            if row[0] and row[1]:
                report_map.setdefault(row[0], row[1])
        reports = [(url, title) for url, title in report_map.items()]
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
                        '解析自财政部国库司“财政收支情况”政府性基金预算收入段；官方同比为可比口径。'
                        if code == 'gov_fund_revenue_ytd_yoy_official' else
                        '解析自财政部国库司“财政收支情况”政府性基金段；官方同比为可比口径。'
                        if code.startswith('govfund_land_transfer_') else
                        '解析自财政部国库司“财政收支情况”一般公共预算支出分项；为中央+地方合计、不含专项债付息，官方同比为可比口径。'
                        if code.startswith('budget_interest_expenditure_') else
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
    try:
        annual_supplement = upsert_land_transfer_annual_backfill(db_path)
        upserted += annual_supplement['records_upserted']
    except Exception as exc:
        errors.append(f'土地出让年度官方补充: {exc}')
    try:
        deficit_supplement = upsert_official_national_fiscal_deficit_backfill(db_path)
        upserted += deficit_supplement['records_upserted']
    except Exception as exc:
        errors.append(f'财政赤字年度官方补充: {exc}')
    try:
        latest_supplement = upsert_latest_official_fiscal_budget_backfill(db_path)
        upserted += latest_supplement['records_upserted']
    except Exception as exc:
        errors.append(f'最新财政YTD官方补充: {exc}')
    return {'success': not errors or upserted > 0, 'started_at': started,
            'finished_at': datetime.now().isoformat(), 'records_upserted': upserted,
            'reports_found': len(reports), 'reports_selected': len(selected_reports),
            'errors': errors[:8]}


def upsert_land_transfer_annual_backfill(db_path):
    """Upsert source-linked annual official values missed by monthly discovery."""
    now = datetime.now().isoformat()
    upserted = 0
    conn = connect(db_path)
    try:
        ensure_fiscal_budget_tables(conn)
        for record in LAND_TRANSFER_ANNUAL_OFFICIAL_BACKFILL:
            cursor = conn.execute('''INSERT INTO fiscal_budget_observations (
                indicator_code,indicator_name,period,value,unit,data_status,
                source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period) DO UPDATE SET
                value=excluded.value, unit=excluded.unit, data_status=excluded.data_status,
                source_name=excluded.source_name, source_type=excluded.source_type,
                source_url=excluded.source_url, source_title=excluded.source_title,
                parser_notes=excluded.parser_notes, formula=excluded.formula,
                updated_at=excluded.updated_at''', (
                'govfund_land_transfer_revenue_ytd', INDICATORS['govfund_land_transfer_revenue_ytd'],
                f"{record['year']}-12", record['value'], '亿元', 'official',
                SOURCE_NAME, SOURCE_TYPE, record['source_url'], record['source_title'],
                record['parser_notes'], None, now))
            upserted += cursor.rowcount
            cursor.close()
        conn.commit()
    finally:
        conn.close()
    return {
        'success': True,
        'records_upserted': upserted,
        'years': [record['year'] for record in LAND_TRANSFER_ANNUAL_OFFICIAL_BACKFILL],
    }


def upsert_latest_official_fiscal_budget_backfill(db_path):
    """Upsert the newest source-linked official YTD release.

    This is deliberately idempotent and updates metadata as well as values.  A
    manually maintained supplement is acceptable here only because every value
    is tied to the official Ministry of Finance article and the regular parser
    remains the primary path.
    """
    now = datetime.now().isoformat()
    upserted = 0
    conn = connect(db_path)
    try:
        ensure_fiscal_budget_tables(conn)
        for record in LATEST_OFFICIAL_FISCAL_BUDGET_BACKFILL:
            values = derive_budget_values(record['values'])
            for code, value in values.items():
                if code not in INDICATORS:
                    continue
                is_official = code in OFFICIAL_INDICATORS
                unit = '%' if code.endswith('_yoy_official') else '亿元'
                if code in FORMULAS:
                    notes = '由同一财政部报告中的官方YTD收入与支出字段按公式计算。'
                    formula = FORMULAS[code]
                    status = 'derived'
                else:
                    notes = record['parser_notes']
                    if code.startswith('govfund_land_transfer_'):
                        notes = record['parser_notes'] + ' 土地出让字段来自政府性基金预算收入段。'
                    elif code.startswith('budget_interest_expenditure_'):
                        notes = record['parser_notes'] + ' 付息支出为一般公共预算支出分项。'
                    formula = None
                    status = 'official' if is_official else 'derived'
                cursor = conn.execute('''INSERT INTO fiscal_budget_observations (
                    indicator_code,indicator_name,period,value,unit,data_status,
                    source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                    value=excluded.value, unit=excluded.unit, data_status=excluded.data_status,
                    source_name=excluded.source_name, source_type=excluded.source_type,
                    source_url=excluded.source_url, source_title=excluded.source_title,
                    parser_notes=excluded.parser_notes, formula=excluded.formula,
                    updated_at=excluded.updated_at''', (
                    code, INDICATORS[code], record['period'], value, unit, status,
                    SOURCE_NAME, SOURCE_TYPE, record['source_url'], record['source_title'],
                    notes, formula, now))
                upserted += cursor.rowcount
                cursor.close()
        conn.commit()
    finally:
        conn.close()
    return {
        'success': True,
        'records_upserted': upserted,
        'periods': [record['period'] for record in LATEST_OFFICIAL_FISCAL_BUDGET_BACKFILL],
    }


def upsert_official_national_fiscal_deficit_backfill(db_path):
    """Upsert source-linked annual statutory deficit observations.

    The normal Treasury monthly parser cannot recover this budget-balance
    concept from monthly YTD reports, so the annual report supplement is
    stored in the same observation table with a distinct indicator code and
    source type.  The operation is idempotent and does not overwrite any
    monthly revenue/expenditure observations.
    """
    now = datetime.now().isoformat()
    upserted = 0
    conn = connect(db_path)
    try:
        ensure_fiscal_budget_tables(conn)
        for record in OFFICIAL_NATIONAL_FISCAL_DEFICIT_ANNUAL:
            cursor = conn.execute('''INSERT INTO fiscal_budget_observations (
                indicator_code,indicator_name,period,value,unit,data_status,
                source_name,source_type,source_url,source_title,parser_notes,formula,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period) DO UPDATE SET
                value=excluded.value, unit=excluded.unit, data_status=excluded.data_status,
                source_name=excluded.source_name, source_type=excluded.source_type,
                source_url=excluded.source_url, source_title=excluded.source_title,
                parser_notes=excluded.parser_notes, formula=excluded.formula,
                updated_at=excluded.updated_at''', (
                OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR,
                OFFICIAL_NATIONAL_FISCAL_DEFICIT_LABEL,
                f"{record['year']}-12", record['value'], '亿元', 'official',
                OFFICIAL_NATIONAL_FISCAL_DEFICIT_SOURCE_NAME,
                OFFICIAL_NATIONAL_FISCAL_DEFICIT_SOURCE_TYPE,
                record['source_url'], record['source_title'], record['parser_notes'],
                None, now))
            upserted += cursor.rowcount
            cursor.close()
        conn.commit()
    finally:
        conn.close()
    return {
        'success': True,
        'records_upserted': upserted,
        'years': [record['year'] for record in OFFICIAL_NATIONAL_FISCAL_DEFICIT_ANNUAL],
    }


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


def _official_deficit_index(deficit_rows=None):
    """Return annual deficit records, using the curated official fallback.

    The fallback makes the API/page deterministic immediately after a code
    deployment; the database rows written by the updater add the same values
    to the auditable observation store and preserve any source metadata.
    """
    index = {record['year']: dict(record)
             for record in OFFICIAL_NATIONAL_FISCAL_DEFICIT_ANNUAL}
    for row in deficit_rows or []:
        period = str(row.get('period') or '')
        match = re.match(r'^(20\d{2})(?:-12)?$', period)
        if not match or not _is_number(row.get('value')):
            continue
        record = dict(row)
        record['year'] = int(match.group(1))
        record['value'] = float(row['value'])
        index[record['year']] = record
    return index


def attach_official_national_fiscal_deficit(annual, deficit_rows=None):
    """Attach the official annual deficit column without changing YTD fields."""
    deficit_by_year = _official_deficit_index(deficit_rows)
    out = []
    for raw in annual or []:
        item = dict(raw)
        year = item.get('year')
        if year is None:
            try:
                year = int(str(item.get('period') or '')[:4])
            except (TypeError, ValueError):
                year = None
        record = deficit_by_year.get(year)
        item[OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR] = (
            record.get('value') if record else None)
        item['official_national_fiscal_deficit_data_status'] = (
            'official' if record else 'missing')
        item['official_national_fiscal_deficit_source_url'] = (
            record.get('source_url') if record else None)
        item['official_national_fiscal_deficit_source_title'] = (
            record.get('source_title') if record else None)
        item['official_national_fiscal_deficit_parser_notes'] = (
            record.get('parser_notes') if record else None)
        out.append(item)
    return out


def _deficit_gap(expenditure, revenue):
    """Positive expenditure-minus-revenue gap; None when either side is absent."""
    if not (_is_number(expenditure) and _is_number(revenue)):
        return None
    return round(float(expenditure) - float(revenue), 4)


def build_historical_fiscal_summary(annual, deficit_rows=None):
    """Build the standalone historical fiscal summary used by the dashboard.

    ``official_national_fiscal_deficit`` is the statutory annual figure from
    the Ministry's budget report.  The ``*_deficit_gap`` fields are transparent
    expenditure-minus-revenue calculations from the monthly Treasury YTD
    series and are intentionally shown side by side rather than conflated.
    """
    enriched = attach_official_national_fiscal_deficit(annual, deficit_rows)
    records = []
    for source in enriched:
        general_revenue = source.get('general_budget_revenue_ytd')
        general_expenditure = source.get('general_budget_expenditure_ytd')
        fund_revenue = source.get('gov_fund_revenue_ytd')
        fund_expenditure = source.get('gov_fund_expenditure_ytd')
        combined_revenue = source.get('combined_budget_revenue_ytd')
        combined_expenditure = source.get('combined_budget_expenditure_ytd')
        official_deficit = source.get(OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR)
        general_gap = _deficit_gap(general_expenditure, general_revenue)
        fund_gap = _deficit_gap(fund_expenditure, fund_revenue)
        combined_gap = _deficit_gap(combined_expenditure, combined_revenue)
        records.append({
            'period': str(source.get('year') or source.get('period')),
            'year': source.get('year'),
            'source_period': source.get('source_period'),
            'general_budget_revenue': general_revenue,
            'general_budget_expenditure': general_expenditure,
            'general_budget_deficit_gap': general_gap,
            'gov_fund_revenue': fund_revenue,
            'gov_fund_expenditure': fund_expenditure,
            'gov_fund_deficit_gap': fund_gap,
            'combined_budget_revenue': combined_revenue,
            'combined_budget_expenditure': combined_expenditure,
            'combined_budget_deficit_gap': combined_gap,
            OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR: official_deficit,
            'official_national_fiscal_deficit_data_status': source.get(
                'official_national_fiscal_deficit_data_status', 'missing'),
            'official_national_fiscal_deficit_source_url': source.get(
                'official_national_fiscal_deficit_source_url'),
            'official_national_fiscal_deficit_source_title': source.get(
                'official_national_fiscal_deficit_source_title'),
            'official_national_fiscal_deficit_parser_notes': source.get(
                'official_national_fiscal_deficit_parser_notes'),
            'official_deficit_minus_general_gap': (
                round(float(official_deficit) - general_gap, 4)
                if _is_number(official_deficit) and _is_number(general_gap) else None),
            'data_status': source.get('data_status', 'missing'),
            'source_url': source.get('source_url'),
            'source_urls': source.get('source_urls', []),
            'source_title': source.get('source_title'),
            'definition': '法定赤字来自财政部年度预算报告；账面缺口=支出−收入，derived。',
        })
    observed = [row for row in records if _is_number(row.get(
        OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR))]
    latest = records[-1] if records else None
    cards = []
    if latest:
        cards = [
            {
                'indicator_code': OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR,
                'label': f"{latest['period']}年法定财政赤字",
                'value': latest.get(OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR),
                'unit': '亿元', 'period': latest['period'], 'data_status': 'official',
                'source_name': OFFICIAL_NATIONAL_FISCAL_DEFICIT_SOURCE_NAME,
                'source_url': latest.get('official_national_fiscal_deficit_source_url'),
                'warning': '财政部年度报告口径；不等于月度收入减支出。',
            },
            {
                'indicator_code': 'general_budget_deficit_gap',
                'label': f"{latest['period']}年一般预算账面缺口",
                'value': latest.get('general_budget_deficit_gap'),
                'unit': '亿元', 'period': latest['period'], 'data_status': 'derived',
                'source_name': SOURCE_NAME, 'source_url': latest.get('source_url'),
                'formula': 'general_budget_deficit_gap = general_budget_expenditure - general_budget_revenue',
                'warning': '由财政部12月YTD收入、支出计算，不是法定赤字。',
            },
            {
                'indicator_code': 'combined_budget_deficit_gap',
                'label': f"{latest['period']}年两本账账面缺口",
                'value': latest.get('combined_budget_deficit_gap'),
                'unit': '亿元', 'period': latest['period'], 'data_status': 'derived',
                'source_name': SOURCE_NAME, 'source_url': latest.get('source_url'),
                'formula': 'combined_budget_deficit_gap = combined_budget_expenditure - combined_budget_revenue',
                'warning': '一般公共预算与政府性基金简单相加，未抵销跨账本转移。',
            },
        ]
    coverage = {
        'periods': len(records),
        'earliest': records[0]['period'] if records else None,
        'latest': records[-1]['period'] if records else None,
        'official_deficit_periods': len(observed),
        'official_deficit_earliest': observed[0]['period'] if observed else None,
        'official_deficit_latest': observed[-1]['period'] if observed else None,
        'official_deficit_missing_years': [
            row['period'] for row in records
            if not _is_number(row.get(OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR))
        ],
    }
    return {
        'data_status': 'official' if observed else ('partial' if records else 'missing'),
        'coverage': coverage,
        'cards': cards,
        'records': records,
        'warnings': ([
            '法定财政赤字与账面缺口是不同口径；历史表并列展示，不互相替代。'
        ] + ([
            '部分年度缺少可直接核验的法定赤字，已保留为空，未用账面缺口填补。'
        ] if coverage['official_deficit_missing_years'] else [])),
        'notes': [
            '法定财政赤字来自财政部年度预算执行报告，单位为亿元。',
            '一般预算/两本账账面缺口均为支出减收入的derived分析值。',
            '两本账账面缺口只是简单相加，不等同于官方法定赤字，也未抵销调入调出。',
        ],
    }


def build_current_year_fiscal_summary(series, annual, plans=None):
    """Build a separate current-year YTD summary and explicit budget plan."""
    annual_years = [int(row.get('year')) for row in annual or []
                    if row.get('year') is not None]
    latest_full_year = max(annual_years) if annual_years else None
    candidates = []
    for row in series or []:
        parsed = _period_year_month(row.get('period'))
        if not parsed:
            continue
        year, month = parsed
        if latest_full_year is not None and year <= latest_full_year:
            continue
        if _is_number(row.get('general_budget_revenue_ytd')) and _is_number(
                row.get('general_budget_expenditure_ytd')):
            candidates.append(row)
    latest = candidates[-1] if candidates else None
    plan_by_year = {record['year']: record for record in (
        plans if plans is not None else OFFICIAL_NATIONAL_FISCAL_DEFICIT_PLAN)}
    if not latest:
        return {
            'data_status': 'missing', 'period': None, 'year': None, 'records': [],
            'cards': [], 'plan': None,
            'warnings': ['尚无高于最新完整年度的财政部YTD观测。'],
            'notes': ['当前年度实际值只接收官方YTD累计，不把全年计划或情景值当作实际。'],
        }
    year, month = _period_year_month(latest['period'])
    general_revenue = latest.get('general_budget_revenue_ytd')
    general_expenditure = latest.get('general_budget_expenditure_ytd')
    fund_revenue = latest.get('gov_fund_revenue_ytd')
    fund_expenditure = latest.get('gov_fund_expenditure_ytd')
    record = {
        'period': latest['period'], 'reporting_period': latest['period'], 'year': year,
        'month': month, 'period_label': f'{year}年截至{month}月',
        'general_budget_revenue_ytd': general_revenue,
        'general_budget_expenditure_ytd': general_expenditure,
        'general_budget_deficit_gap_ytd': _deficit_gap(general_expenditure, general_revenue),
        'gov_fund_revenue_ytd': fund_revenue,
        'gov_fund_expenditure_ytd': fund_expenditure,
        'gov_fund_deficit_gap_ytd': _deficit_gap(fund_expenditure, fund_revenue),
        'combined_budget_revenue_ytd': latest.get('combined_budget_revenue_ytd'),
        'combined_budget_expenditure_ytd': latest.get('combined_budget_expenditure_ytd'),
        'combined_budget_deficit_gap_ytd': _deficit_gap(
            latest.get('combined_budget_expenditure_ytd'),
            latest.get('combined_budget_revenue_ytd')),
        'official_national_fiscal_deficit': None,
        'official_national_fiscal_deficit_data_status': 'not_available',
        'data_status': latest.get('data_status', 'official'),
        'source_url': latest.get('source_url'),
        'source_urls': latest.get('source_urls', []),
        'source_title': latest.get('source_title'),
        'definition': '当前年度为财政部YTD累计；账面缺口=支出−收入，法定全年赤字待年度报告。',
    }
    plan = plan_by_year.get(year)
    if plan:
        record.update({
            'official_national_fiscal_deficit_plan': plan['value'],
            'official_national_fiscal_deficit_plan_data_status': 'official_plan',
            'official_national_fiscal_deficit_plan_source_url': plan['source_url'],
            'official_national_fiscal_deficit_plan_source_title': plan['source_title'],
            'official_national_fiscal_deficit_plan_parser_notes': plan['parser_notes'],
        })
    cards = [
        {
            'indicator_code': 'general_budget_deficit_gap_ytd',
            'label': f'{record["period_label"]}一般预算账面缺口',
            'value': record['general_budget_deficit_gap_ytd'], 'unit': '亿元',
            'period': record['period'], 'data_status': 'derived',
            'source_name': SOURCE_NAME, 'source_url': record['source_url'],
            'formula': 'general_budget_deficit_gap_ytd = general_budget_expenditure_ytd - general_budget_revenue_ytd',
            'warning': 'YTD累计账面缺口，不是全年法定赤字。',
        },
        {
            'indicator_code': 'combined_budget_deficit_gap_ytd',
            'label': f'{record["period_label"]}两本账账面缺口',
            'value': record['combined_budget_deficit_gap_ytd'], 'unit': '亿元',
            'period': record['period'], 'data_status': 'derived',
            'source_name': SOURCE_NAME, 'source_url': record['source_url'],
            'formula': 'combined_budget_deficit_gap_ytd = combined_budget_expenditure_ytd - combined_budget_revenue_ytd',
            'warning': '两本账简单相加，不是法定赤字。',
        },
    ]
    if plan:
        cards.append({
            'indicator_code': 'official_national_fiscal_deficit_plan',
            'label': f'{year}年预算安排财政赤字', 'value': plan['value'], 'unit': '亿元',
            'period': str(year), 'data_status': 'official_plan',
            'source_name': OFFICIAL_NATIONAL_FISCAL_DEFICIT_SOURCE_NAME,
            'source_url': plan['source_url'], 'warning': '官方预算计划，不是全年实际赤字。',
        })
    return {
        'data_status': 'official', 'period': record['period'], 'year': year,
        'latest_full_year': latest_full_year, 'records': [record], 'cards': cards,
        'plan': plan, 'warnings': [
            f'当前年度显示财政部{record["period"]}YTD累计；2026年法定全年赤字尚未形成年度执行值。',
            '账面缺口是支出减收入；预算安排赤字单独标记为official_plan，不与实际YTD相加。',
        ], 'notes': [
            '当前年度不把YTD累计外推成官方全年赤字。',
            '当前年度预算计划与年度实际执行属于两条不同时间序列。',
        ],
    }


LAND_TRANSFER_ANNUAL_START_YEAR = 2007


def build_land_transfer_annual_series(series, start_year=LAND_TRANSFER_ANNUAL_START_YEAR):
    """Build an auditable annual land-transfer-revenue table.

    Source observations are December YTD values. The table keeps every
    calendar year from the comparable institutional start (2007) through the
    latest observed December point, including explicit missing rows. It never
    turns an annual point into a monthly value or fills a missing year from
    neighbouring years.
    """
    annual_by_year = {}
    for row in series or []:
        period = str(row.get('period') or '')
        if not re.fullmatch(r'20\d{2}-12', period):
            continue
        year = int(period[:4])
        if year < int(start_year):
            continue
        annual_by_year[year] = dict(row)
    if not annual_by_year:
        return []

    end_year = max(annual_by_year)
    rows = []
    for year in range(int(start_year), end_year + 1):
        source = annual_by_year.get(year, {})
        land = source.get('govfund_land_transfer_revenue_ytd')
        fund = source.get('gov_fund_revenue_ytd')
        general = source.get('general_budget_revenue_ytd')
        land_available = isinstance(land, (int, float)) and not isinstance(land, bool)
        fund_available = isinstance(fund, (int, float)) and not isinstance(fund, bool)
        general_available = isinstance(general, (int, float)) and not isinstance(general, bool)
        source_urls = list(dict.fromkeys(filter(None, [
            source.get('source_url'), *(source.get('source_urls') or [])
        ])))
        rows.append({
            'period': str(year),
            'year': year,
            'source_period': f'{year}-12',
            'indicator_code': 'govfund_land_transfer_revenue_ytd',
            'land_transfer_revenue': land if land_available else None,
            'land_transfer_revenue_ytd': land if land_available else None,
            'land_transfer_yoy_official': source.get(
                'govfund_land_transfer_revenue_ytd_yoy_official'),
            'gov_fund_revenue': fund if fund_available else None,
            'general_budget_revenue': general if general_available else None,
            'land_share_of_fund_pct': (
                round(land / fund * 100, 4)
                if land_available and fund_available and fund else None),
            'land_share_of_combined_revenue_pct': (
                round(land / (fund + general) * 100, 4)
                if land_available and fund_available and general_available and (fund + general)
                else None),
            'data_status': 'official' if land_available else 'missing',
            'source_url': source.get('source_url'),
            'source_urls': source_urls,
            'source_title': source.get('source_title'),
            'formula': (
                'land_share_of_fund_pct = land_transfer_revenue / gov_fund_revenue × 100; '
                'land_share_of_combined_revenue_pct = land_transfer_revenue / '
                '(general_budget_revenue + gov_fund_revenue) × 100'
            ),
            'missing_reason': (
                None if land_available else
                '当前本地库尚无该年度12月官方观测；未用估算或前后年份填充。'
            ),
        })
    return rows


def _period_year_month(period):
    match = re.fullmatch(r'(20\d{2})-(0[1-9]|1[0-2])', str(period or ''))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dedupe(values):
    return list(dict.fromkeys(value for value in values if value))


def _land_transfer_quantile(values, probability):
    """Linear-interpolated quantile without pandas/numpy dependencies."""
    ordered = sorted(float(value) for value in values if _is_number(value))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * min(1.0, max(0.0, float(probability)))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _pearson_correlation(left, right):
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_sum = sum((x - left_mean) ** 2 for x in left)
    right_sum = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_sum * right_sum)
    return round(numerator / denominator, 4) if denominator else None


def build_land_transfer_half_year_analysis(series, start_year=LAND_TRANSFER_ANNUAL_START_YEAR,
                                            min_history=3):
    """Compare June YTD land revenue with the same year's December YTD result.

    June and December are matched by calendar year. The historical seasonal
    share is descriptive; the current-year full-year number is a transparent
    mechanical implication, not an official forecast. Backtest estimates use
    only matched years available before the target year, avoiding look-ahead.
    """
    by_year = {}
    for raw in series or []:
        year_month = _period_year_month(raw.get('period'))
        if not year_month:
            continue
        year, month = year_month
        if year < int(start_year) or month not in (6, 12):
            continue
        by_year.setdefault(year, {})['half' if month == 6 else 'full'] = dict(raw)
    if not by_year:
        return {
            'rows': [], 'cards': [], 'current': None,
            'predictive_power': {'data_status': 'missing', 'n_obs': 0},
            'method': '仅匹配同一自然年的6月累计值与12月累计值；无可用观测。',
            'sample_start': None, 'sample_end': None, 'n_obs': 0,
            'data_status': 'missing',
            'caveats': ['尚无财政部土地出让收入6月或12月官方累计观测。'],
        }

    end_year = max(by_year)
    rows = []
    for year in range(int(start_year), end_year + 1):
        half = by_year.get(year, {}).get('half', {})
        full = by_year.get(year, {}).get('full', {})
        half_value = half.get('govfund_land_transfer_revenue_ytd')
        full_value = full.get('govfund_land_transfer_revenue_ytd')
        half_available = _is_number(half_value)
        full_available = _is_number(full_value)
        previous = by_year.get(year - 1, {})
        previous_half = previous.get('half', {}).get('govfund_land_transfer_revenue_ytd')
        previous_full = previous.get('full', {}).get('govfund_land_transfer_revenue_ytd')
        half_yoy_derived = (
            round((half_value / previous_half - 1) * 100, 2)
            if half_available and _is_number(previous_half) and previous_half else None)
        full_yoy_derived = (
            round((full_value / previous_full - 1) * 100, 2)
            if full_available and _is_number(previous_full) and previous_full else None)
        direction_match = None
        if half_yoy_derived is not None and full_yoy_derived is not None:
            if half_yoy_derived != 0 and full_yoy_derived != 0:
                direction_match = (half_yoy_derived > 0) == (full_yoy_derived > 0)
        share = round(half_value / full_value * 100, 4) if (
            half_available and full_available and full_value) else None
        if half_available and full_available:
            analysis_status = 'matched'
        elif half_available:
            analysis_status = 'half_year_only'
        elif full_available:
            analysis_status = 'full_year_only'
        else:
            analysis_status = 'missing'
        source_urls = _dedupe([half.get('source_url'), full.get('source_url')])
        reasons = []
        if not half_available:
            reasons.append('缺少该年度6月累计官方观测')
        if not full_available:
            reasons.append('缺少该年度12月累计官方观测')
        rows.append({
            'period': str(year), 'year': year,
            'half_year_period': f'{year}-06', 'full_year_period': f'{year}-12',
            'half_year_revenue': half_value if half_available else None,
            'full_year_revenue': full_value if full_available else None,
            'h1_share_of_full_year_pct': share,
            'half_year_yoy_official': half.get(
                'govfund_land_transfer_revenue_ytd_yoy_official'),
            'full_year_yoy_official': full.get(
                'govfund_land_transfer_revenue_ytd_yoy_official'),
            'half_year_yoy_derived': half_yoy_derived,
            'full_year_yoy_derived': full_yoy_derived,
            'direction_match': direction_match,
            'full_year_estimate_by_prior_median': None,
            'estimate_error_pct': None,
            'analysis_status': analysis_status,
            'data_status': 'official' if (half_available or full_available) else 'missing',
            'source_url': half.get('source_url') or full.get('source_url'),
            'source_urls': source_urls,
            'source_title': half.get('source_title') or full.get('source_title'),
            'formula': (
                'h1_share_of_full_year_pct = half_year_revenue / full_year_revenue × 100; '
                'derived yoy = current value / prior calendar-year value − 1'
            ),
            'missing_reason': '；'.join(reasons) or None,
        })

    matched = [row for row in rows if row['analysis_status'] == 'matched']
    shares = [row['h1_share_of_full_year_pct'] for row in matched]
    prior_shares = []
    backtest_errors = []
    for row in matched:
        if len(prior_shares) >= int(min_history) and prior_shares:
            reference_share = median(prior_shares)
            estimate = row['half_year_revenue'] / (reference_share / 100)
            row['full_year_estimate_by_prior_median'] = round(estimate, 2)
            row['estimate_error_pct'] = round(
                (estimate / row['full_year_revenue'] - 1) * 100, 2)
            backtest_errors.append(row['estimate_error_pct'])
        prior_shares.append(row['h1_share_of_full_year_pct'])

    directional = [row for row in matched if row['direction_match'] is not None]
    direction_count = sum(bool(row['direction_match']) for row in directional)
    backtest = {
        'method': '目标年度全年值 = 目标年度上半年累计值 / 目标年度之前已匹配年份H1/全年比例中位数；至少需要3个历史匹配年份。',
        'n_obs': len(backtest_errors),
        'error_unit': 'relative_pct_of_actual_full_year',
        'mae_relative_pct': round(sum(abs(value) for value in backtest_errors) / len(backtest_errors), 2)
        if backtest_errors else None,
        'median_abs_relative_pct': round(median(abs(value) for value in backtest_errors), 2)
        if backtest_errors else None,
        'within_10pct_relative_error_pct': round(
            sum(abs(value) <= 10 for value in backtest_errors) / len(backtest_errors) * 100, 2)
        if backtest_errors else None,
        # Compatibility aliases retained for existing consumers. These are
        # relative-percent errors, not percentage-point errors.
        'mae_pct': round(sum(abs(value) for value in backtest_errors) / len(backtest_errors), 2)
        if backtest_errors else None,
        'median_abs_error_pct': round(median(abs(value) for value in backtest_errors), 2)
        if backtest_errors else None,
        'mean_error_pct': round(sum(backtest_errors) / len(backtest_errors), 2)
        if backtest_errors else None,
        'within_10pp_pct': round(
            sum(abs(value) <= 10 for value in backtest_errors) / len(backtest_errors) * 100, 2)
        if backtest_errors else None,
        'data_status': 'derived' if backtest_errors else 'insufficient_sample',
    }
    predictive_power = {
        'data_status': 'derived' if len(matched) >= 2 else 'insufficient_sample',
        'n_obs': len(matched),
        'sample_start': str(matched[0]['year']) if matched else None,
        'sample_end': str(matched[-1]['year']) if matched else None,
        'level_correlation_h1_vs_full_year': _pearson_correlation(
            [row['half_year_revenue'] for row in matched],
            [row['full_year_revenue'] for row in matched]),
        'directional_n': len(directional),
        'directional_same_count': direction_count,
        'directional_same_pct': round(direction_count / len(directional) * 100, 2)
        if directional else None,
        'backtest': backtest,
        'interpretation': (
            '上半年对全年有方向性和季节性参考价值，但历史样本少且年度比例会变化；'
            '不能把上半年同比直接当作全年同比，也不能把机械推演当作官方预测。'
        ),
    }

    partial = [row for row in rows if row['analysis_status'] == 'half_year_only']
    current_row = max(partial or [row for row in rows if _is_number(row.get('half_year_revenue'))],
                       key=lambda row: row['year'], default=None)
    current = None
    cards = []
    if current_row and _is_number(current_row.get('half_year_revenue')):
        current_year = current_row['year']
        half_value = current_row['half_year_revenue']
        q25 = _land_transfer_quantile(shares, 0.25)
        q75 = _land_transfer_quantile(shares, 0.75)
        share_median = median(shares) if shares else None
        share_mean = sum(shares) / len(shares) if shares else None
        previous_full_rows = [row for row in rows
                              if row['year'] < current_year and _is_number(row.get('full_year_revenue'))]
        last_full = previous_full_rows[-1] if previous_full_rows else None
        estimate_low = half_value / (q75 / 100) if q75 else None
        estimate_median = half_value / (share_median / 100) if share_median else None
        estimate_high = half_value / (q25 / 100) if q25 else None
        yoy_low = ((estimate_low / last_full['full_year_revenue']) - 1) * 100 \
            if estimate_low and last_full else None
        yoy_median = ((estimate_median / last_full['full_year_revenue']) - 1) * 100 \
            if estimate_median and last_full else None
        yoy_high = ((estimate_high / last_full['full_year_revenue']) - 1) * 100 \
            if estimate_high and last_full else None
        current = {
            'year': current_year,
            'period': current_row['half_year_period'],
            'half_year_revenue': half_value,
            'half_year_yoy_official': current_row.get('half_year_yoy_official'),
            'data_status': 'official',
            'source_url': current_row.get('source_url'),
            'source_urls': current_row.get('source_urls', []),
            'historical_sample_n': len(matched),
            'historical_sample_start': str(matched[0]['year']) if matched else None,
            'historical_sample_end': str(matched[-1]['year']) if matched else None,
            'historical_share_mean_pct': round(share_mean, 4) if share_mean is not None else None,
            'historical_share_median_pct': round(share_median, 4) if share_median is not None else None,
            'historical_share_q25_pct': round(q25, 4) if q25 is not None else None,
            'historical_share_q75_pct': round(q75, 4) if q75 is not None else None,
            'implied_full_year_low': round(estimate_low, 2) if estimate_low is not None else None,
            'implied_full_year_median': round(estimate_median, 2)
            if estimate_median is not None else None,
            'implied_full_year_high': round(estimate_high, 2) if estimate_high is not None else None,
            'implied_full_year_yoy_low_pct': round(yoy_low, 2) if yoy_low is not None else None,
            'implied_full_year_yoy_median_pct': round(yoy_median, 2)
            if yoy_median is not None else None,
            'implied_full_year_yoy_high_pct': round(yoy_high, 2) if yoy_high is not None else None,
            'comparison_full_year': last_full['year'] if last_full else None,
            'formula': '全年机械推演 = 上半年累计值 / 历史H1/全年比例；区间使用历史比例第25—75百分位。',
            'caveats': [
                '这是基于历史季节性的 derived 机械推演，不是官方预测，也未纳入土地市场政策、供地节奏和一次性结算变化。',
                '当前年只有6月累计值，12月官方值尚未公布；不能与完整年度官方值混列。',
            ],
        }
        if current_row['analysis_status'] == 'half_year_only':
            current_row['full_year_estimate_by_prior_median'] = current['implied_full_year_median']
        current_source = current.get('source_url')
        cards = [
            {'label': f'{current_year}年上半年土地出让收入', 'value': half_value,
             'unit': '亿元', 'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current_source,
             'warning': '6月累计值，不是全年值。'},
            {'label': '上半年官方同比', 'value': current.get('half_year_yoy_official'),
             'unit': '%', 'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current_source},
            {'label': '历史H1/全年中位比例', 'value': current.get('historical_share_median_pct'),
             'unit': '%', 'period': f"{current.get('historical_sample_start')}—{current.get('historical_sample_end')}",
             'data_status': 'derived', 'formula': current['formula'],
             'source_name': SOURCE_NAME, 'source_url': current_source},
            {'label': f'{current_year}全年机械推演（中位比例）',
             'value': current.get('implied_full_year_median'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'derived',
             'formula': current['formula'], 'source_name': SOURCE_NAME, 'source_url': current_source},
            {'label': '历史中间50%机械区间',
             'value': (
                 f"{current['implied_full_year_low']:,.0f}—{current['implied_full_year_high']:,.0f}"
                 if current.get('implied_full_year_low') is not None and
                 current.get('implied_full_year_high') is not None else None),
             'unit': '亿元', 'period': current['period'],
             'data_status': 'derived' if current.get('implied_full_year_low') is not None else 'missing',
             'formula': current['formula'], 'source_name': SOURCE_NAME, 'source_url': current_source,
             'warning': '不是置信区间；只是历史季节性比例的中间50%区间。'},
        ]

    return {
        'rows': rows,
        'cards': cards,
        'current': current,
        'predictive_power': predictive_power,
        'method': '匹配同一自然年的6月累计值与12月累计值；比例、相关和回测均只用官方YTD观测，机械推演不写回官方表。',
        'sample_start': str(matched[0]['year']) if matched else None,
        'sample_end': str(matched[-1]['year']) if matched else None,
        'n_obs': len(matched),
        'data_status': 'derived' if matched else 'missing',
        'caveats': [
            '缺少6月或12月观测的年份不进入H1/全年比例回测；不把缺月当作0，也不跨缺月填补。',
            'H1同比与全年同比的方向比较采用两期官方累计值直算的 derived 同比；存在统计口径和土地结算节奏变化，不能解释为因果或精确预测。',
        ],
    }


def _cutoff_label(month):
    month = int(month)
    return '上半年' if month == 6 else f'1—{month}月'


def build_land_transfer_latest_ytd_analysis(series, start_year=LAND_TRANSFER_ANNUAL_START_YEAR,
                                            min_history=3):
    """Re-estimate the current land-transfer total using the newest YTD cutoff.

    The older H1 analysis remains available for a stable backtest.  This layer
    uses the latest available cutoff (for example 1—7月) and only compares it
    with the same calendar cutoff in prior years.  It never treats a missing
    month as zero or bridges a missing report.
    """
    source_by_period = {
        str(row.get('period')): dict(row) for row in series or []
        if _period_year_month(row.get('period'))
    }
    partials = [
        row for row in source_by_period.values()
        if _period_year_month(row.get('period'))[1] != 12
        and _is_number(row.get('govfund_land_transfer_revenue_ytd'))
        and _period_year_month(row.get('period'))[0] >= int(start_year)
    ]
    if not partials:
        return {
            'rows': [], 'cards': [], 'current': None,
            'predictive_power': {'data_status': 'missing', 'n_obs': 0},
            'method': '仅匹配同一自然年的最新累计截止月与12月完整年度值；无可用观测。',
            'sample_start': None, 'sample_end': None, 'n_obs': 0,
            'data_status': 'missing',
            'caveats': ['尚无财政部土地出让收入的非12月官方累计观测。'],
        }

    latest_partial = max(
        partials, key=lambda row: str(row.get('period')))
    current_year, cutoff_month = _period_year_month(latest_partial['period'])
    cutoff_label = _cutoff_label(cutoff_month)
    full_by_year = {
        year: row for period, row in source_by_period.items()
        if (year := _period_year_month(period)[0]) >= int(start_year)
        and _period_year_month(period)[1] == 12
    }
    years = sorted({year for period in source_by_period
                    if (year := _period_year_month(period)[0]) >= int(start_year)}
                   | {current_year})
    rows = []
    for year in range(min(years), current_year + 1):
        ytd = source_by_period.get(f'{year}-{cutoff_month:02d}', {})
        full = full_by_year.get(year, {})
        previous_ytd = source_by_period.get(f'{year - 1}-{cutoff_month:02d}', {})
        previous_full = full_by_year.get(year - 1, {})
        ytd_value = ytd.get('govfund_land_transfer_revenue_ytd')
        full_value = full.get('govfund_land_transfer_revenue_ytd')
        ytd_available = _is_number(ytd_value)
        full_available = _is_number(full_value)
        share = round(ytd_value / full_value * 100, 6) if (
            ytd_available and full_available and full_value) else None
        ytd_yoy_derived = (
            round((ytd_value / previous_ytd.get('govfund_land_transfer_revenue_ytd') - 1) * 100, 2)
            if ytd_available and _is_number(previous_ytd.get('govfund_land_transfer_revenue_ytd'))
            and previous_ytd.get('govfund_land_transfer_revenue_ytd') else None)
        full_yoy_derived = (
            round((full_value / previous_full.get('govfund_land_transfer_revenue_ytd') - 1) * 100, 2)
            if full_available and _is_number(previous_full.get('govfund_land_transfer_revenue_ytd'))
            and previous_full.get('govfund_land_transfer_revenue_ytd') else None)
        reasons = []
        if not ytd_available:
            reasons.append(f'缺少该年度{cutoff_label}官方累计观测')
        if not full_available:
            reasons.append('缺少该年度12月累计官方观测')
        rows.append({
            'period': str(year), 'year': year,
            'cutoff_period': f'{year}-{cutoff_month:02d}',
            'full_year_period': f'{year}-12',
            'cutoff_month': cutoff_month, 'cutoff_label': cutoff_label,
            'ytd_revenue': ytd_value if ytd_available else None,
            'full_year_revenue': full_value if full_available else None,
            'ytd_share_of_full_year_pct': share,
            'ytd_yoy_official': ytd.get('govfund_land_transfer_revenue_ytd_yoy_official'),
            'full_year_yoy_official': full.get('govfund_land_transfer_revenue_ytd_yoy_official'),
            'ytd_yoy_derived': ytd_yoy_derived,
            'full_year_yoy_derived': full_yoy_derived,
            'full_year_estimate_by_prior_median': None,
            'estimate_error_pct': None,
            'analysis_status': 'matched' if ytd_available and full_available
            else 'ytd_only' if ytd_available else 'full_year_only' if full_available else 'missing',
            'data_status': 'official' if ytd_available or full_available else 'missing',
            'source_url': ytd.get('source_url') or full.get('source_url'),
            'source_urls': _dedupe([ytd.get('source_url'), full.get('source_url')]),
            'source_title': ytd.get('source_title') or full.get('source_title'),
            'formula': (
                'ytd_share_of_full_year_pct = same-year YTD cumulative revenue / '
                'same-year December cumulative revenue × 100; '
                'full-year estimate = current YTD revenue / historical same-cutoff share'
            ),
            'missing_reason': '；'.join(reasons) or None,
        })

    matched = [row for row in rows
               if row['analysis_status'] == 'matched' and row['year'] < current_year]
    shares = [row['ytd_share_of_full_year_pct'] for row in matched]
    prior_shares = []
    errors = []
    for row in matched:
        if len(prior_shares) >= int(min_history) and prior_shares:
            reference = median(prior_shares)
            estimate = row['ytd_revenue'] / (reference / 100)
            row['full_year_estimate_by_prior_median'] = round(estimate, 2)
            row['estimate_error_pct'] = round(
                (estimate / row['full_year_revenue'] - 1) * 100, 2)
            errors.append(row['estimate_error_pct'])
        prior_shares.append(row['ytd_share_of_full_year_pct'])
    backtest = {
        'n_obs': len(errors),
        'error_unit': 'relative_pct_of_actual_full_year',
        'mae_relative_pct': round(sum(abs(value) for value in errors) / len(errors), 2)
        if errors else None,
        'median_abs_relative_pct': round(median(abs(value) for value in errors), 2)
        if errors else None,
        'within_10pct_relative_error_pct': round(
            sum(abs(value) <= 10 for value in errors) / len(errors) * 100, 2)
        if errors else None,
        'data_status': 'derived' if errors else 'insufficient_sample',
    }
    predictive_power = {
        'data_status': 'derived' if len(matched) >= 2 else 'insufficient_sample',
        'n_obs': len(matched),
        'sample_start': str(matched[0]['year']) if matched else None,
        'sample_end': str(matched[-1]['year']) if matched else None,
        'level_correlation_ytd_vs_full_year': _pearson_correlation(
            [row['ytd_revenue'] for row in matched],
            [row['full_year_revenue'] for row in matched]),
        'backtest': backtest,
        'interpretation': (
            f'{cutoff_label}累计值对全年有季节性参考价值，但比例随结算节奏和政策变化；'
            '不能把累计同比直接当作全年同比，也不能把机械推演解释为官方预测。'
        ),
    }
    current_row = next((row for row in rows if row['period'] == str(current_year)), None)
    if current_row is None or not _is_number(current_row.get('ytd_revenue')):
        return {
            'rows': rows, 'cards': [], 'current': None,
            'predictive_power': predictive_power, 'sample_start': predictive_power['sample_start'],
            'sample_end': predictive_power['sample_end'], 'n_obs': len(matched),
            'data_status': 'insufficient_sample' if matched else 'missing',
            'method': f'仅匹配同一自然年的{cutoff_label}累计值与12月完整年度值。',
            'caveats': ['最新累计月没有可用官方土地出让收入值。'],
        }
    q25 = _land_transfer_quantile(shares, 0.25) if len(shares) >= int(min_history) else None
    q75 = _land_transfer_quantile(shares, 0.75) if len(shares) >= int(min_history) else None
    share_median = median(shares) if len(shares) >= int(min_history) else None
    share_mean = sum(shares) / len(shares) if shares else None
    previous_full = next((row for row in reversed(rows)
                          if row['year'] < current_year and _is_number(row.get('full_year_revenue'))), None)
    estimate_low = current_row['ytd_revenue'] / (q75 / 100) if q75 else None
    estimate_median = current_row['ytd_revenue'] / (share_median / 100) if share_median else None
    estimate_high = current_row['ytd_revenue'] / (q25 / 100) if q25 else None
    def _estimate_yoy(value):
        return ((value / previous_full['full_year_revenue']) - 1) * 100 \
            if value is not None and previous_full else None
    current = {
        'year': current_year, 'period': current_row['cutoff_period'],
        'cutoff_period': current_row['cutoff_period'], 'cutoff_month': cutoff_month,
        'cutoff_label': cutoff_label, 'ytd_revenue': current_row['ytd_revenue'],
        'ytd_yoy_official': current_row.get('ytd_yoy_official'),
        'data_status': 'official', 'source_url': current_row.get('source_url'),
        'source_urls': current_row.get('source_urls', []),
        'historical_sample_n': len(matched),
        'historical_sample_start': str(matched[0]['year']) if matched else None,
        'historical_sample_end': str(matched[-1]['year']) if matched else None,
        'historical_share_mean_pct': round(share_mean, 4) if share_mean is not None else None,
        'historical_share_median_pct': round(share_median, 4) if share_median is not None else None,
        'historical_share_q25_pct': round(q25, 4) if q25 is not None else None,
        'historical_share_q75_pct': round(q75, 4) if q75 is not None else None,
        'implied_full_year_low': round(estimate_low, 2) if estimate_low is not None else None,
        'implied_full_year_median': round(estimate_median, 2) if estimate_median is not None else None,
        'implied_full_year_high': round(estimate_high, 2) if estimate_high is not None else None,
        'implied_full_year_yoy_low_pct': round(_estimate_yoy(estimate_low), 2)
        if _estimate_yoy(estimate_low) is not None else None,
        'implied_full_year_yoy_median_pct': round(_estimate_yoy(estimate_median), 2)
        if _estimate_yoy(estimate_median) is not None else None,
        'implied_full_year_yoy_high_pct': round(_estimate_yoy(estimate_high), 2)
        if _estimate_yoy(estimate_high) is not None else None,
        'comparison_full_year': previous_full['year'] if previous_full else None,
        'formula': (
            f'全年机械推演 = 当前{cutoff_label}累计值 / 历史同截止月YTD/全年比例；'
            '区间使用历史比例第25—75百分位。'
        ),
        'caveats': [
            '这是基于历史季节性的derived机械推演，不是官方预测；未纳入土地市场政策、供地节奏和一次性结算变化。',
            f'当前年只有{cutoff_label}累计值，12月官方值尚未公布；不能与完整年度官方值混列。',
        ],
    }
    if current['implied_full_year_median'] is not None:
        current_row['full_year_estimate_by_prior_median'] = current['implied_full_year_median']
    cards = [
        {'label': f'{current_year}年{cutoff_label}土地出让收入', 'value': current['ytd_revenue'],
         'unit': '亿元', 'period': current['period'], 'data_status': 'official',
         'source_name': SOURCE_NAME, 'source_url': current['source_url'],
         'warning': f'{cutoff_label}累计值，不是全年值。'},
        {'label': f'{cutoff_label}官方同比', 'value': current.get('ytd_yoy_official'),
         'unit': '%', 'period': current['period'], 'data_status': 'official',
         'source_name': SOURCE_NAME, 'source_url': current['source_url']},
        {'label': '历史同截止月/全年中位比例', 'value': current.get('historical_share_median_pct'),
         'unit': '%', 'period': f"{current.get('historical_sample_start')}—{current.get('historical_sample_end')}",
         'data_status': 'derived' if current.get('historical_share_median_pct') is not None else 'insufficient_sample',
         'formula': current['formula'], 'source_name': SOURCE_NAME, 'source_url': current['source_url']},
        {'label': f'{current_year}全年机械推演（中位比例）',
         'value': current.get('implied_full_year_median'), 'unit': '亿元',
         'period': current['period'],
         'data_status': 'derived' if current.get('implied_full_year_median') is not None else 'insufficient_sample',
         'formula': current['formula'], 'source_name': SOURCE_NAME, 'source_url': current['source_url']},
        {'label': '历史中间50%机械区间',
         'value': (f"{current['implied_full_year_low']:,.0f}—{current['implied_full_year_high']:,.0f}"
                   if current.get('implied_full_year_low') is not None and
                   current.get('implied_full_year_high') is not None else None),
         'unit': '亿元', 'period': current['period'],
         'data_status': 'derived' if current.get('implied_full_year_low') is not None else 'insufficient_sample',
         'formula': current['formula'], 'source_name': SOURCE_NAME, 'source_url': current['source_url'],
         'warning': '不是置信区间；只是历史同截止月比例的中间50%区间。'},
    ]
    return {
        'rows': rows, 'cards': cards, 'current': current,
        'predictive_power': predictive_power,
        'method': f'匹配同一自然年的{cutoff_label}累计值与12月累计值；比例、相关和回测均只用官方YTD观测，机械推演不写回官方表。',
        'sample_start': str(matched[0]['year']) if matched else None,
        'sample_end': str(matched[-1]['year']) if matched else None,
        'n_obs': len(matched),
        'data_status': 'derived' if len(matched) >= int(min_history) else 'insufficient_sample',
        'caveats': [
            '缺少同一截止月或12月观测的年份不进入比例回测；不把缺月当作0，也不跨缺月填补。',
            'YTD同比与全年同比的方向比较采用官方同比优先、直除同比为补充；不能解释为因果或精确预测。',
        ],
    }


def _budget_short_code(code):
    return code[:-4] if code.endswith('_ytd') else code


def build_budget_latest_ytd_analysis(annual, series, min_history=3):
    """Build the same-account latest-YTD-to-full-year conversion.

    Unlike the legacy H1 layer, the cutoff is inferred from the newest
    available non-December report.  The comparison sample uses that exact
    calendar cutoff in earlier years, so a July cumulative value is never
    compared with a June value or an annual point.
    """
    annual_by_year = {}
    for row in annual or []:
        period = str(row.get('period') or '')
        year = row.get('year')
        if year is None and period.isdigit():
            year = int(period)
        if year is not None:
            annual_by_year[int(year)] = dict(row)
    source_by_period = {
        str(row.get('period')): dict(row) for row in series or []
        if _period_year_month(row.get('period'))
    }
    partials = []
    for row in source_by_period.values():
        year_month = _period_year_month(row.get('period'))
        if year_month and year_month[1] != 12 and any(
                _is_number(row.get(code)) for code in CORE_OFFICIAL_INDICATORS):
            partials.append(row)
    if not partials:
        return {
            'rows': [], 'current': None, 'cards': [], 'simulation': {
                'data_status': 'missing', 'records': [], 'simulations': 0,
            }, 'share_stats': {}, 'predictive_power': {}, 'n_obs': 0,
            'data_status': 'missing',
            'method': '仅匹配同一自然年的最新累计截止月与12月完整年度官方值；无可用观测。',
            'caveats': ['尚无财政部非12月财政收支累计观测。'],
        }

    latest_partial = max(partials, key=lambda row: str(row.get('period')))
    current_year, cutoff_month = _period_year_month(latest_partial['period'])
    cutoff_label = _cutoff_label(cutoff_month)
    years = sorted({int(period[:4]) for period in source_by_period}
                   | set(annual_by_year) | {current_year})
    rows = []
    for year in range(min(years), current_year + 1):
        ytd = source_by_period.get(f'{year}-{cutoff_month:02d}', {})
        full = annual_by_year.get(year, source_by_period.get(f'{year}-12', {}))
        previous_ytd = source_by_period.get(f'{year - 1}-{cutoff_month:02d}', {})
        previous_full = annual_by_year.get(year - 1,
                                           source_by_period.get(f'{year - 1}-12', {}))
        matched_indicators = []
        ytd_indicators = []
        full_indicators = []
        reasons = []
        row = {
            'period': str(year), 'year': year,
            'cutoff_period': f'{year}-{cutoff_month:02d}',
            'full_year_period': f'{year}-12', 'cutoff_month': cutoff_month,
            'cutoff_label': cutoff_label,
            'source_url': ytd.get('source_url') or full.get('source_url'),
            'source_urls': _dedupe([ytd.get('source_url'), full.get('source_url')]),
            'source_title': ytd.get('source_title') or full.get('source_title'),
            'missing_reason': None,
        }
        for code in CORE_OFFICIAL_INDICATORS:
            short = _budget_short_code(code)
            ytd_key = f'{short}_ytd'
            full_key = f'{short}_full_year'
            share_key = f'{short}_ytd_full_year_share_pct'
            ytd_value = ytd.get(code)
            full_value = full.get(code)
            row[ytd_key] = ytd_value if _is_number(ytd_value) else None
            row[full_key] = full_value if _is_number(full_value) else None
            ytd_official_key = f'{short}_ytd_yoy_official'
            full_official_key = f'{short}_full_year_yoy_official'
            row[ytd_official_key] = ytd.get(f'{code}_yoy_official')
            row[full_official_key] = full.get(f'{code}_yoy_official')
            previous_ytd_value = previous_ytd.get(code)
            previous_full_value = previous_full.get(code)
            row[f'{short}_ytd_yoy_derived'] = (
                round((ytd_value / previous_ytd_value - 1) * 100, 2)
                if _is_number(ytd_value) and _is_number(previous_ytd_value)
                and previous_ytd_value else None)
            row[f'{short}_full_year_yoy_derived'] = (
                round((full_value / previous_full_value - 1) * 100, 2)
                if _is_number(full_value) and _is_number(previous_full_value)
                and previous_full_value else None)
            if _is_number(ytd_value):
                ytd_indicators.append(code)
            else:
                reasons.append(f'{year}缺少{short}{cutoff_label}累计值')
            if _is_number(full_value):
                full_indicators.append(code)
            else:
                reasons.append(f'{year}缺少{short}全年累计值')
            if _is_number(ytd_value) and _is_number(full_value) and full_value:
                row[share_key] = round(ytd_value / full_value * 100, 6)
                matched_indicators.append(code)
            else:
                row[share_key] = None
            row[f'{short}_full_year_estimate_by_prior_median'] = None
            row[f'{short}_estimate_error_pct'] = None
        row['matched_indicator_count'] = len(matched_indicators)
        row['matched_indicators'] = matched_indicators
        row['ytd_indicator_count'] = len(ytd_indicators)
        row['full_year_indicator_count'] = len(full_indicators)
        row['analysis_status'] = (
            'matched_all' if len(matched_indicators) == len(CORE_OFFICIAL_INDICATORS)
            else 'partial' if matched_indicators
            else 'ytd_only' if ytd_indicators and not full_indicators
            else 'full_year_only' if full_indicators and not ytd_indicators
            else 'missing')
        row['data_status'] = 'official' if ytd_indicators or full_indicators else 'missing'
        row['missing_reason'] = '；'.join(_dedupe(reasons)) or None
        row['formula'] = (
            f'{cutoff_label}/全年比例 = 同年{cutoff_label}累计值 / 同年12月累计值；'
            f'全年机械推演 = 当前年{cutoff_label}累计值 / 历史同截止月比例'
        )
        rows.append(row)

    share_stats = {}
    backtest = {}
    for code in CORE_OFFICIAL_INDICATORS:
        short = _budget_short_code(code)
        share_key = f'{short}_ytd_full_year_share_pct'
        matched = [row for row in rows if row['year'] < current_year
                   and _is_number(row.get(share_key))]
        shares = [row[share_key] for row in matched]
        share_stats[short] = {
            'indicator_code': code, 'label': INDICATORS[code], 'n_obs': len(shares),
            'sample_start': str(matched[0]['year']) if matched else None,
            'sample_end': str(matched[-1]['year']) if matched else None,
            'mean_pct': round(sum(shares) / len(shares), 4) if shares else None,
            'median_pct': round(median(shares), 4) if shares else None,
            'q25_pct': round(_land_transfer_quantile(shares, 0.25), 4) if shares else None,
            'q75_pct': round(_land_transfer_quantile(shares, 0.75), 4) if shares else None,
            'min_pct': round(min(shares), 4) if shares else None,
            'max_pct': round(max(shares), 4) if shares else None,
        }
        prior_shares = []
        errors = []
        for row in matched:
            share = row.get(share_key)
            ytd_value = row.get(f'{short}_ytd')
            full_value = row.get(f'{short}_full_year')
            if len(prior_shares) >= int(min_history) and _is_number(ytd_value) \
                    and _is_number(full_value):
                reference = median(prior_shares)
                estimate = ytd_value / (reference / 100)
                row[f'{short}_full_year_estimate_by_prior_median'] = round(estimate, 2)
                row[f'{short}_estimate_error_pct'] = round(
                    (estimate / full_value - 1) * 100, 2)
                errors.append(row[f'{short}_estimate_error_pct'])
            prior_shares.append(share)
        backtest[short] = {
            'n_obs': len(errors),
            'mae_relative_pct': round(sum(abs(value) for value in errors) / len(errors), 2)
            if errors else None,
            'median_abs_relative_pct': round(median(abs(value) for value in errors), 2)
            if errors else None,
            'within_10pct_relative_error_pct': round(
                sum(abs(value) <= 10 for value in errors) / len(errors) * 100, 2)
            if errors else None,
            'error_unit': 'relative_pct_of_actual_full_year',
            'data_status': 'derived' if errors else 'insufficient_sample',
        }

    matched_all = [row for row in rows if row['year'] < current_year
                   and row.get('matched_indicator_count') == len(CORE_OFFICIAL_INDICATORS)]
    current_row = next((row for row in rows if row['year'] == current_year), None)
    current = None
    if current_row and current_row.get('ytd_indicator_count', 0):
        ytd_values = {
            code: current_row.get(f'{_budget_short_code(code)}_ytd')
            for code in CORE_OFFICIAL_INDICATORS
        }
        current = {
            'year': current_year, 'period': current_row['cutoff_period'],
            'cutoff_period': current_row['cutoff_period'], 'cutoff_month': cutoff_month,
            'cutoff_label': cutoff_label, 'ytd_values': ytd_values,
            'ytd_yoy_official': {
                _budget_short_code(code): current_row.get(
                    f'{_budget_short_code(code)}_ytd_yoy_official')
                for code in CORE_OFFICIAL_INDICATORS
            },
            'ytd_yoy_derived': {
                _budget_short_code(code): current_row.get(
                    f'{_budget_short_code(code)}_ytd_yoy_derived')
                for code in CORE_OFFICIAL_INDICATORS
            },
            'share_stats': share_stats, 'data_status': 'official',
            'source_url': current_row.get('source_url'),
            'source_urls': current_row.get('source_urls', []),
            'formula': (
                f'当前全年值 = 当前{cutoff_label}官方累计值 / 历史同科目{cutoff_label}/全年比例；'
                '基准使用中位数，较好/较坏使用方向一致的第25/75百分位。'
            ),
            'scenarios': {},
        }
        scenario_share_rules = {
            'baseline': {'label': '最可能（季节性中位）', 'revenue': 'median', 'expenditure': 'median'},
            'improvement': {'label': '较好（累计月后修复）', 'revenue': 'q25', 'expenditure': 'q75'},
            'pressure': {'label': '较坏（累计月后走弱）', 'revenue': 'q75', 'expenditure': 'q25'},
        }
        revenue_codes = {'general_budget_revenue', 'gov_fund_revenue'}
        enough_history = all(share_stats[_budget_short_code(code)].get('n_obs', 0)
                             >= int(min_history) for code in CORE_OFFICIAL_INDICATORS)
        for scenario_code, rule in scenario_share_rules.items():
            raw_values = {}
            assumptions = {}
            for code in CORE_OFFICIAL_INDICATORS:
                short = _budget_short_code(code)
                stat = share_stats[short]
                statistic = rule['revenue'] if short in revenue_codes else rule['expenditure']
                share = stat.get(f'{statistic}_pct') if enough_history else None
                assumptions[short] = share
                if _is_number(ytd_values.get(code)) and _is_number(share) and share > 0:
                    raw_values[code] = round(ytd_values[code] / (share / 100), 1)
            current['scenarios'][scenario_code] = {
                'label': rule['label'], 'values': derive_budget_values(raw_values),
                'share_assumptions_pct': assumptions,
                'data_status': 'derived' if len(raw_values) == len(CORE_OFFICIAL_INDICATORS)
                else 'insufficient_sample', 'formula': current['formula'],
            }
        current['simulation'] = simulate_budget_latest_ytd_uncertainty(
            rows, current, cutoff_month=cutoff_month, simulations=5000, seed=20260823)
        baseline = current['scenarios'].get('baseline', {}).get('values', {})
        simulation_record = (current['simulation'].get('records') or [{}])[0]
        current['cards'] = [
            {'label': f'{current_year}年{cutoff_label}一般公共预算收入',
             'value': ytd_values.get('general_budget_revenue_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年{cutoff_label}一般公共预算支出',
             'value': ytd_values.get('general_budget_expenditure_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年{cutoff_label}政府性基金收入',
             'value': ytd_values.get('gov_fund_revenue_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年{cutoff_label}政府性基金支出',
             'value': ytd_values.get('gov_fund_expenditure_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{cutoff_label}一般预算收入官方同比',
             'value': current['ytd_yoy_official'].get('general_budget_revenue'), 'unit': '%',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{cutoff_label}政府性基金收入官方同比',
             'value': current['ytd_yoy_official'].get('gov_fund_revenue'), 'unit': '%',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}全年两本账差额（季节性中位）',
             'value': baseline.get('combined_budget_balance_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'derived' if baseline else 'insufficient_sample',
             'formula': current['formula'], 'source_name': SOURCE_NAME,
             'source_url': current['source_url']},
            {'label': f'{current_year}全年两本账差额（模拟P50）',
             'value': simulation_record.get('combined_budget_balance_ytd_p50'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'scenario' if simulation_record else 'insufficient_sample',
             'formula': current['simulation'].get('formula'), 'source_name': SOURCE_NAME,
             'source_url': current['source_url']},
        ]
    predictive_power = {
        'data_status': 'derived' if matched_all else 'insufficient_sample',
        'n_obs': len(matched_all),
        'sample_start': str(matched_all[0]['year']) if matched_all else None,
        'sample_end': str(matched_all[-1]['year']) if matched_all else None,
        'backtest': backtest,
        'interpretation': (
            f'最新{cutoff_label}累计值与全年之间仅做同截止月季节性转换；不能把累计同比直接当成全年同比。'
        ),
    }
    return {
        'rows': rows, 'current': current, 'share_stats': share_stats,
        'backtest': backtest,
        'simulation': current.get('simulation', {}) if current else {},
        'n_obs': len(matched_all),
        'sample_start': str(matched_all[0]['year']) if matched_all else None,
        'sample_end': str(matched_all[-1]['year']) if matched_all else None,
        'data_status': 'derived' if len(matched_all) >= int(min_history) else 'insufficient_sample',
        'method': (
            f'分别匹配同一自然年的{cutoff_label}累计值与12月完整年度值；当前年度使用同科目历史'
            f'{cutoff_label}/全年比例转换，模拟使用同一年四科目比例联合抽样。'
        ),
        'predictive_power': predictive_power,
        'caveats': [
            '官方同比优先用于增长判断，YTD/全年比例只用于透明的derived机械转换。',
            'P10/P50/P90是历史同截止月比例的敏感性区间，不是概率预测或官方置信区间。',
            '财政收支口径、土地结算节奏和政策调整会改变同截止月/全年比例；历史样本不代表结构稳定。',
        ],
    }


def build_budget_half_year_analysis(annual, series, min_history=3):
    """Build an auditable H1-to-full-year conversion for all four accounts.

    The existing annual forecast used the latest H1 year-on-year rate as if it
    were a full-year rate. That is only valid when the H1/full-year seasonal
    share is unchanged. This layer estimates each current full-year account as
    ``current H1 / historical same-year H1/full-year share`` and keeps the
    three current-year cases tied to observed share quantiles. It never writes
    the estimate back as an official observation.
    """
    annual_by_year = {
        int(row.get('year', str(row.get('period', '0'))[:4])): row
        for row in annual or []
        if row.get('year') is not None or str(row.get('period', '')).isdigit()
    }
    source_by_period = {
        str(row.get('period')): row for row in series or []
        if _period_year_month(row.get('period'))
    }
    years = sorted({int(period[:4]) for period in source_by_period}
                   | set(annual_by_year))
    if not years:
        return {
            'rows': [], 'current': None, 'cards': [], 'simulation': {
                'data_status': 'missing', 'records': [], 'simulations': 0,
            }, 'share_stats': {}, 'predictive_power': {}, 'n_obs': 0,
            'data_status': 'missing',
            'method': '仅匹配同一自然年的6月累计值与12月完整年度官方值；无可用观测。',
            'caveats': ['尚无财政部一般预算/政府性基金上半年与全年配对官方值。'],
        }

    rows = []
    for year in range(min(years), max(years) + 1):
        half = source_by_period.get(f'{year}-06', {})
        full = annual_by_year.get(year, source_by_period.get(f'{year}-12', {}))
        previous_half = source_by_period.get(f'{year - 1}-06', {})
        previous_full = annual_by_year.get(
            year - 1, source_by_period.get(f'{year - 1}-12', {}))
        matched_indicators = []
        half_indicators = []
        full_indicators = []
        row = {
            'period': str(year), 'year': year,
            'half_year_period': f'{year}-06', 'full_year_period': f'{year}-12',
            'source_url': half.get('source_url') or full.get('source_url'),
            'source_urls': _dedupe([half.get('source_url'), full.get('source_url')]),
            'source_title': half.get('source_title') or full.get('source_title'),
            'missing_reason': None,
        }
        reasons = []
        for code in CORE_OFFICIAL_INDICATORS:
            short = _budget_short_code(code)
            half_key = f'{short}_h1'
            full_key = f'{short}_full_year'
            share_key = f'{short}_h1_full_year_share_pct'
            half_value = half.get(code)
            full_value = full.get(code)
            row[half_key] = half_value if _is_number(half_value) else None
            row[full_key] = full_value if _is_number(full_value) else None
            row[f'{short}_h1_yoy_official'] = half.get(f'{code}_yoy_official')
            row[f'{short}_full_year_yoy_official'] = full.get(
                f'{code}_yoy_official')
            previous_half_value = previous_half.get(code)
            previous_full_value = previous_full.get(code)
            row[f'{short}_h1_yoy_derived'] = (
                round((half_value / previous_half_value - 1) * 100, 2)
                if _is_number(half_value) and _is_number(previous_half_value)
                and previous_half_value else None)
            row[f'{short}_full_year_yoy_derived'] = (
                round((full_value / previous_full_value - 1) * 100, 2)
                if _is_number(full_value) and _is_number(previous_full_value)
                and previous_full_value else None)
            if _is_number(half_value):
                half_indicators.append(code)
            else:
                reasons.append(f'{year}缺少{short}上半年累计值')
            if _is_number(full_value):
                full_indicators.append(code)
            else:
                reasons.append(f'{year}缺少{short}全年累计值')
            if _is_number(half_value) and _is_number(full_value) and full_value:
                row[share_key] = round(half_value / full_value * 100, 6)
                matched_indicators.append(code)
            else:
                row[share_key] = None
            row[f'{short}_full_year_estimate_prior_median'] = None
            row[f'{short}_estimate_error_pct'] = None
        row['matched_indicator_count'] = len(matched_indicators)
        row['matched_indicators'] = matched_indicators
        row['half_year_indicator_count'] = len(half_indicators)
        row['full_year_indicator_count'] = len(full_indicators)
        row['analysis_status'] = (
            'matched_all' if len(matched_indicators) == len(CORE_OFFICIAL_INDICATORS)
            else 'partial' if matched_indicators
            else 'half_year_only' if half_indicators and not full_indicators
            else 'full_year_only' if full_indicators and not half_indicators
            else 'missing')
        row['data_status'] = 'official' if half_indicators or full_indicators else 'missing'
        row['missing_reason'] = '；'.join(_dedupe(reasons)) or None
        row['formula'] = (
            'H1/全年比例 = 同年6月累计 / 同年12月累计；'
            '全年机械推演 = 当前年6月累计 / 历史H1/全年比例')
        rows.append(row)

    share_stats = {}
    backtest = {}
    for code in CORE_OFFICIAL_INDICATORS:
        short = _budget_short_code(code)
        share_key = f'{short}_h1_full_year_share_pct'
        shares = [row[share_key] for row in rows if _is_number(row.get(share_key))]
        stats = {
            'indicator_code': code, 'label': INDICATORS[code],
            'n_obs': len(shares),
            'sample_start': str(next((row['year'] for row in rows
                                      if _is_number(row.get(share_key))), '')) or None,
            'sample_end': str(next((row['year'] for row in reversed(rows)
                                    if _is_number(row.get(share_key))), '')) or None,
            'mean_pct': round(sum(shares) / len(shares), 4) if shares else None,
            'median_pct': round(median(shares), 4) if shares else None,
            'q25_pct': round(_land_transfer_quantile(shares, 0.25), 4) if shares else None,
            'q75_pct': round(_land_transfer_quantile(shares, 0.75), 4) if shares else None,
            'min_pct': round(min(shares), 4) if shares else None,
            'max_pct': round(max(shares), 4) if shares else None,
        }
        share_stats[short] = stats
        prior_shares = []
        errors = []
        for row in rows:
            share = row.get(share_key)
            h1_value = row.get(f'{short}_h1')
            full_value = row.get(f'{short}_full_year')
            if _is_number(share) and _is_number(h1_value) and _is_number(full_value):
                if len(prior_shares) >= int(min_history):
                    reference = median(prior_shares)
                    estimate = h1_value / (reference / 100)
                    error = (estimate / full_value - 1) * 100
                    row[f'{short}_full_year_estimate_prior_median'] = round(estimate, 2)
                    row[f'{short}_estimate_error_pct'] = round(error, 2)
                    errors.append(error)
                prior_shares.append(share)
        backtest[short] = {
            'n_obs': len(errors),
            'mae_relative_pct': round(sum(abs(v) for v in errors) / len(errors), 2)
            if errors else None,
            'median_abs_relative_pct': round(median(abs(v) for v in errors), 2)
            if errors else None,
            'within_10pct_relative_error_pct': round(
                sum(abs(v) <= 10 for v in errors) / len(errors) * 100, 2)
            if errors else None,
            'error_unit': 'relative_pct_of_actual_full_year',
            'data_status': 'derived' if errors else 'insufficient_sample',
        }

    latest_full_year = max((row['year'] for row in rows
                            if row['full_year_indicator_count']), default=None)
    current_candidates = [row for row in rows
                          if row['half_year_indicator_count'] and
                          (latest_full_year is None or row['year'] > latest_full_year)]
    if not current_candidates:
        current_candidates = [row for row in rows if row['half_year_indicator_count']]
    current_row = current_candidates[-1] if current_candidates else None
    current = None
    if current_row:
        current_year = current_row['year']
        h1_values = {code: current_row.get(f'{_budget_short_code(code)}_h1')
                     for code in CORE_OFFICIAL_INDICATORS}
        current = {
            'year': current_year, 'period': current_row['half_year_period'],
            'h1_values': h1_values,
            'h1_yoy_official': {
                _budget_short_code(code): current_row.get(
                    f'{_budget_short_code(code)}_h1_yoy_official')
                for code in CORE_OFFICIAL_INDICATORS
            },
            'h1_yoy_derived': {
                _budget_short_code(code): current_row.get(
                    f'{_budget_short_code(code)}_h1_yoy_derived')
                for code in CORE_OFFICIAL_INDICATORS
            },
            'share_stats': share_stats,
            'data_status': 'official',
            'source_url': current_row.get('source_url'),
            'source_urls': current_row.get('source_urls', []),
            'formula': (
                '当前全年值 = 当前上半年官方累计值 / 历史同科目H1/全年比例；'
                '基准使用中位数，较好/较坏使用方向一致的第25/75百分位。'),
            'scenarios': {},
        }
        scenario_share_rules = {
            'baseline': {'label': '最可能（季节性中位）', 'revenue': 'median', 'expenditure': 'median'},
            'improvement': {'label': '较好（上半年后修复）', 'revenue': 'q25', 'expenditure': 'q75'},
            'pressure': {'label': '较坏（上半年后走弱）', 'revenue': 'q75', 'expenditure': 'q25'},
        }
        revenue_codes = {'general_budget_revenue', 'gov_fund_revenue'}
        for scenario_code, rule in scenario_share_rules.items():
            raw_values = {}
            assumptions = {}
            for code in CORE_OFFICIAL_INDICATORS:
                short = _budget_short_code(code)
                stat = share_stats[short]
                statistic = rule['revenue'] if short in revenue_codes else rule['expenditure']
                share = stat.get(f'{statistic}_pct')
                assumptions[short] = share
                if _is_number(h1_values.get(code)) and _is_number(share) and share > 0:
                    raw_values[code] = round(h1_values[code] / (share / 100), 1)
            current['scenarios'][scenario_code] = {
                'label': rule['label'], 'values': derive_budget_values(raw_values),
                'share_assumptions_pct': assumptions,
                'data_status': 'derived' if len(raw_values) == len(CORE_OFFICIAL_INDICATORS)
                else 'insufficient_sample',
                'formula': current['formula'],
            }

        current['simulation'] = simulate_budget_half_year_uncertainty(
            rows, current, simulations=5000, seed=20260808)
        baseline = current['scenarios'].get('baseline', {}).get('values', {})
        current['cards'] = [
            {'label': f'{current_year}年上半年一般公共预算收入',
             'value': h1_values.get('general_budget_revenue_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年一般公共预算支出',
             'value': h1_values.get('general_budget_expenditure_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年政府性基金收入',
             'value': h1_values.get('gov_fund_revenue_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年政府性基金支出',
             'value': h1_values.get('gov_fund_expenditure_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年一般公共预算收入同比',
             'value': current['h1_yoy_official'].get('general_budget_revenue'), 'unit': '%',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年一般公共预算支出同比',
             'value': current['h1_yoy_official'].get('general_budget_expenditure'), 'unit': '%',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年政府性基金收入同比',
             'value': current['h1_yoy_official'].get('gov_fund_revenue'), 'unit': '%',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}年上半年政府性基金支出同比',
             'value': current['h1_yoy_official'].get('gov_fund_expenditure'), 'unit': '%',
             'period': current['period'], 'data_status': 'official',
             'source_name': SOURCE_NAME, 'source_url': current['source_url']},
            {'label': f'{current_year}全年两本账差额（季节性中位）',
             'value': baseline.get('combined_budget_balance_ytd'), 'unit': '亿元',
             'period': current['period'], 'data_status': 'derived',
             'formula': current['formula'], 'source_name': SOURCE_NAME,
             'source_url': current['source_url']},
            {'label': f'{current_year}全年两本账差额（模拟P50）',
             'value': (current['simulation'].get('records') or [{}])[0].get(
                 'combined_budget_balance_ytd_p50'),
             'unit': '亿元', 'period': current['period'], 'data_status': 'scenario',
             'formula': current['simulation'].get('formula'), 'source_name': SOURCE_NAME,
             'source_url': current['source_url']},
        ]
    else:
        current = {'data_status': 'missing', 'scenarios': {}, 'simulation': {
            'data_status': 'missing', 'records': [], 'simulations': 0,
        }}

    matched_all = [row for row in rows
                   if row.get('matched_indicator_count') == len(CORE_OFFICIAL_INDICATORS)]
    return {
        'rows': rows, 'current': current, 'share_stats': share_stats,
        'backtest': backtest, 'simulation': current.get('simulation', {}) if current else {},
        'n_obs': len(matched_all),
        'sample_start': str(matched_all[0]['year']) if matched_all else None,
        'sample_end': str(matched_all[-1]['year']) if matched_all else None,
        'data_status': 'derived' if matched_all else 'insufficient_sample',
        'method': (
            '分别匹配同一自然年的6月累计值与12月完整年度值；当前年度使用同科目历史'
            'H1/全年比例转换，模拟使用同一年四科目比例联合抽样。'),
        'caveats': [
            '上半年同比不能直接当作全年同比；当前年度先按历史季节性比例转换，再进入情景路径。',
            'P10/P50/P90是历史季节性比例的敏感性区间，不是概率预测或官方置信区间。',
            '财政收支口径、土地出让节奏和政策调整会改变H1/全年比例；历史样本不代表结构稳定。',
        ],
    }


def simulate_budget_half_year_uncertainty(rows, current, simulations=5000, seed=20260808):
    """Bootstrap current-year full-year values from paired H1/FY shares."""
    joint_rows = [row for row in rows if all(
        _is_number(row.get(f'{_budget_short_code(code)}_h1_full_year_share_pct'))
        for code in CORE_OFFICIAL_INDICATORS)]
    h1_values = current.get('h1_values') if current else {}
    if not current or not all(_is_number(h1_values.get(code)) for code in CORE_OFFICIAL_INDICATORS):
        return {'data_status': 'missing', 'records': [], 'simulations': 0,
                'n_share_vectors': len(joint_rows),
                'warnings': ['当前上半年四项财政累计值不完整，未生成全年模拟。']}
    if len(joint_rows) < 5:
        return {'data_status': 'insufficient_sample', 'records': [], 'simulations': 0,
                'n_share_vectors': len(joint_rows),
                'warnings': ['四项财政H1/全年联合比例少于5个年度，不生成全年模拟区间。']}
    simulations = max(100, min(int(simulations), 50000))
    rng = random.Random(int(seed))
    distribution_codes = CORE_OFFICIAL_INDICATORS + (
        'general_budget_balance_ytd', 'gov_fund_balance_ytd',
        'combined_budget_revenue_ytd', 'combined_budget_expenditure_ytd',
        'combined_budget_balance_ytd')
    distributions = {code: [] for code in distribution_codes}
    for _ in range(simulations):
        sampled = rng.choice(joint_rows)
        raw_values = {}
        for code in CORE_OFFICIAL_INDICATORS:
            short = _budget_short_code(code)
            share = sampled[f'{short}_h1_full_year_share_pct']
            raw_values[code] = h1_values[code] / (share / 100)
        values = derive_budget_values(raw_values)
        for code in distribution_codes:
            if _is_number(values.get(code)):
                distributions[code].append(values[code])
    record = {'period': str(current['year']), 'year': current['year'],
              'data_status': 'scenario'}
    for code, values in distributions.items():
        record[f'{code}_p10'] = round(_land_transfer_quantile(values, 0.10), 1)
        record[f'{code}_p50'] = round(_land_transfer_quantile(values, 0.50), 1)
        record[f'{code}_p90'] = round(_land_transfer_quantile(values, 0.90), 1)
    return {
        'data_status': 'scenario', 'records': [record], 'simulations': simulations,
        'seed': int(seed), 'n_share_vectors': len(joint_rows),
        'sample_start': str(joint_rows[0]['year']), 'sample_end': str(joint_rows[-1]['year']),
        'percentiles': [10, 50, 90],
        'method': '固定当前年上半年官方累计值，按历史同一年四科目H1/全年比例联合bootstrap；不使用当前年全年信息。',
        'formula': 'full_year_value[code] = current_h1_value[code] / sampled_same_year_h1_full_year_share[code]',
        'warnings': [
            'P10/P50/P90是历史季节性比例的敏感性区间，不是财政结果发生概率或官方置信区间。',
            '模拟次数增加不会增加历史比例样本的信息；当前联合比例样本仍然有限。',
        ],
    }


def simulate_budget_latest_ytd_uncertainty(rows, current, cutoff_month,
                                           simulations=5000, seed=20260823):
    """Bootstrap full-year values from same-cutoff YTD/full-year share vectors."""
    joint_rows = [row for row in rows if all(
        _is_number(row.get(f'{_budget_short_code(code)}_ytd_full_year_share_pct'))
        for code in CORE_OFFICIAL_INDICATORS)]
    ytd_values = current.get('ytd_values') if current else {}
    cutoff_label = _cutoff_label(cutoff_month)
    if not current or not all(_is_number(ytd_values.get(code))
                              for code in CORE_OFFICIAL_INDICATORS):
        return {
            'data_status': 'missing', 'records': [], 'simulations': 0,
            'n_share_vectors': len(joint_rows),
            'warnings': [f'当前{cutoff_label}四项财政累计值不完整，未生成全年模拟。'],
        }
    if len(joint_rows) < 5:
        return {
            'data_status': 'insufficient_sample', 'records': [], 'simulations': 0,
            'n_share_vectors': len(joint_rows),
            'warnings': [f'四项财政同{cutoff_label}/全年联合比例少于5个年度，不生成全年模拟区间。'],
        }
    simulations = max(100, min(int(simulations), 50000))
    rng = random.Random(int(seed))
    distribution_codes = CORE_OFFICIAL_INDICATORS + (
        'general_budget_balance_ytd', 'gov_fund_balance_ytd',
        'combined_budget_revenue_ytd', 'combined_budget_expenditure_ytd',
        'combined_budget_balance_ytd')
    distributions = {code: [] for code in distribution_codes}
    for _ in range(simulations):
        sampled = rng.choice(joint_rows)
        raw_values = {}
        for code in CORE_OFFICIAL_INDICATORS:
            short = _budget_short_code(code)
            share = sampled[f'{short}_ytd_full_year_share_pct']
            raw_values[code] = ytd_values[code] / (share / 100)
        values = derive_budget_values(raw_values)
        for code in distribution_codes:
            if _is_number(values.get(code)):
                distributions[code].append(values[code])
    record = {'period': str(current['year']), 'year': current['year'],
              'cutoff_period': current.get('cutoff_period'),
              'cutoff_label': cutoff_label, 'data_status': 'scenario'}
    for code, values in distributions.items():
        record[f'{code}_p10'] = round(_land_transfer_quantile(values, 0.10), 1)
        record[f'{code}_p50'] = round(_land_transfer_quantile(values, 0.50), 1)
        record[f'{code}_p90'] = round(_land_transfer_quantile(values, 0.90), 1)
    return {
        'data_status': 'scenario', 'records': [record], 'simulations': simulations,
        'seed': int(seed), 'n_share_vectors': len(joint_rows),
        'sample_start': str(joint_rows[0]['year']), 'sample_end': str(joint_rows[-1]['year']),
        'percentiles': [10, 50, 90],
        'method': f'固定当前年{cutoff_label}官方累计值，按历史同一年四科目{cutoff_label}/全年比例联合bootstrap；不使用当前年全年信息。',
        'formula': 'full_year_value[code] = current_ytd_value[code] / sampled_same_cutoff_ytd_full_year_share[code]',
        'warnings': [
            'P10/P50/P90是历史季节性比例的敏感性区间，不是财政结果发生概率或官方置信区间。',
            '模拟次数增加不会增加历史比例样本的信息；当前联合比例样本仍然有限。',
        ],
    }


def derive_monthly_budget_series(series):
    """Convert official YTD observations into transparent period flows.

    ``YYYY-02`` is kept as a Jan-Feb combined window because the Ministry does
    not publish a separate January report.  For March onward a value is only
    derived when the immediately preceding YTD cutoff exists in the same year;
    a missing month is never bridged.  Missing calendar rows are retained so a
    chart/table can show the break instead of silently connecting the lines.
    """
    source_rows = {
        row['period']: row for row in series
        if _period_year_month(row.get('period'))
    }
    if not source_rows:
        return []

    periods_by_year = {}
    for period in source_rows:
        year, month = _period_year_month(period)
        periods_by_year.setdefault(year, []).append(month)

    monthly = []
    for year in sorted(periods_by_year):
        actual_months = sorted(set(periods_by_year[year]))
        # Audit the observed span only. Before the first observed report we do
        # not claim that a report should exist; the coverage summary records the
        # historical start separately.
        for month in range(actual_months[0], actual_months[-1] + 1):
            period = f'{year}-{month:02d}'
            current = source_rows.get(period)
            row = {
                'period': period,
                'source_period': period,
                'flow_window': '1-2月' if month == 2 else f'{month}月',
                'months_covered': 2 if month == 2 else 1,
                'data_status': 'missing',
                'source_url': current.get('source_url') if current else None,
                'source_urls': [],
                'source_title': current.get('source_title') if current else None,
                'missing_reason': None,
            }
            reasons = []
            formulas = []
            if current and current.get('source_url'):
                row['source_urls'].append(current['source_url'])

            for ytd_code, monthly_code in MONTHLY_FLOW_FROM_YTD.items():
                current_value = current.get(ytd_code) if current else None
                value = None
                if not _is_number(current_value):
                    reasons.append(f'{period}缺少{ytd_code}官方累计值')
                elif month == 2:
                    value = round(float(current_value), 2)
                    formulas.append(f'{monthly_code} = {ytd_code}[{period}]（1-2月合并）')
                else:
                    previous_period = f'{year}-{month - 1:02d}'
                    previous = source_rows.get(previous_period)
                    previous_value = previous.get(ytd_code) if previous else None
                    if _is_number(previous_value):
                        value = round(float(current_value) - float(previous_value), 2)
                        formulas.append(
                            f'{monthly_code} = {ytd_code}[{period}] - '
                            f'{ytd_code}[{previous_period}]')
                        if previous.get('source_url'):
                            row['source_urls'].append(previous['source_url'])
                    else:
                        reasons.append(
                            f'{period}未计算{monthly_code}：缺少相邻{previous_period}累计值，未跨缺月差分')
                row[monthly_code] = value

            if _is_number(row.get('general_budget_revenue_monthly')) and _is_number(
                    row.get('general_budget_expenditure_monthly')):
                row['general_budget_balance_monthly'] = round(
                    row['general_budget_revenue_monthly'] - row['general_budget_expenditure_monthly'], 2)
                formulas.append(
                    'general_budget_balance_monthly = general_budget_revenue_monthly - '
                    'general_budget_expenditure_monthly')
            if _is_number(row.get('gov_fund_revenue_monthly')) and _is_number(
                    row.get('gov_fund_expenditure_monthly')):
                row['gov_fund_balance_monthly'] = round(
                    row['gov_fund_revenue_monthly'] - row['gov_fund_expenditure_monthly'], 2)
                formulas.append(
                    'gov_fund_balance_monthly = gov_fund_revenue_monthly - '
                    'gov_fund_expenditure_monthly')
            if _is_number(row.get('general_budget_revenue_monthly')) and _is_number(
                    row.get('gov_fund_revenue_monthly')):
                row['combined_budget_revenue_monthly'] = round(
                    row['general_budget_revenue_monthly'] + row['gov_fund_revenue_monthly'], 2)
                formulas.append(
                    'combined_budget_revenue_monthly = general_budget_revenue_monthly + '
                    'gov_fund_revenue_monthly')
            if _is_number(row.get('general_budget_expenditure_monthly')) and _is_number(
                    row.get('gov_fund_expenditure_monthly')):
                row['combined_budget_expenditure_monthly'] = round(
                    row['general_budget_expenditure_monthly'] + row['gov_fund_expenditure_monthly'], 2)
                formulas.append(
                    'combined_budget_expenditure_monthly = general_budget_expenditure_monthly + '
                    'gov_fund_expenditure_monthly')
            if _is_number(row.get('combined_budget_revenue_monthly')) and _is_number(
                    row.get('combined_budget_expenditure_monthly')):
                row['combined_budget_balance_monthly'] = round(
                    row['combined_budget_revenue_monthly'] - row['combined_budget_expenditure_monthly'], 2)
                formulas.append(
                    'combined_budget_balance_monthly = combined_budget_revenue_monthly - '
                    'combined_budget_expenditure_monthly')

            row['source_urls'] = _dedupe(row['source_urls'])
            row['formula'] = '; '.join(formulas) if formulas else None
            row['data_status'] = (
                'derived' if any(_is_number(row.get(code)) for code in MONTHLY_FLOW_INDICATORS)
                else 'missing')
            row['missing_reason'] = '；'.join(_dedupe(reasons)) or None
            monthly.append(row)

    # The screenshot's second series is a same-month comparison of the
    # already-derived full-caliber expenditure flow.  Build it only after all
    # monthly flows exist so a missing month cannot be bridged implicitly.
    monthly_by_period = {row['period']: row for row in monthly}
    for row in monthly:
        row['combined_budget_expenditure_monthly_yoy'] = None
        row['combined_budget_expenditure_monthly_yoy_formula'] = None
        row['combined_budget_expenditure_monthly_yoy_missing_reason'] = None
        year, month = _period_year_month(row['period'])
        previous_period = f'{year - 1}-{month:02d}'
        previous = monthly_by_period.get(previous_period)
        current_value = row.get('combined_budget_expenditure_monthly')
        previous_value = previous.get('combined_budget_expenditure_monthly') if previous else None
        if _is_number(current_value) and _is_number(previous_value) and previous_value:
            row['combined_budget_expenditure_monthly_yoy'] = round(
                (float(current_value) / float(previous_value) - 1) * 100, 2)
            row['combined_budget_expenditure_monthly_yoy_formula'] = (
                f'combined_budget_expenditure_monthly[{row["period"]}] / '
                f'combined_budget_expenditure_monthly[{previous_period}] - 1')
            row['source_urls'] = _dedupe(
                row.get('source_urls', []) + (previous.get('source_urls', []) if previous else [])
                + ([previous.get('source_url')] if previous and previous.get('source_url') else []))
            row['formula'] = '; '.join(filter(None, [
                row.get('formula'), row['combined_budget_expenditure_monthly_yoy_formula']]))
        elif _is_number(current_value):
            row['combined_budget_expenditure_monthly_yoy_missing_reason'] = (
                f'缺少上一年同月({previous_period})的全口径支出流量，未计算同比')
    return monthly


def build_budget_monthly_coverage(series, monthly):
    """Return an auditable completeness summary for the derived flow layer."""
    ytd_periods = sorted({row['period'] for row in series if _period_year_month(row.get('period'))})
    monthly_periods = [row['period'] for row in monthly]
    coverage_by_indicator = {}
    for ytd_code, monthly_code in MONTHLY_FLOW_FROM_YTD.items():
        ytd_available = [row['period'] for row in series if _is_number(row.get(ytd_code))]
        flow_available = [row['period'] for row in monthly if _is_number(row.get(monthly_code))]
        expected = [row['period'] for row in monthly]
        missing = [period for period in expected if period not in flow_available]
        coverage_by_indicator[monthly_code] = {
            'ytd_first': ytd_available[0] if ytd_available else None,
            'ytd_latest': ytd_available[-1] if ytd_available else None,
            'ytd_records': len(ytd_available),
            'observed_span_periods': len(expected),
            'derived_flow_records': len(flow_available),
            'coverage_pct': round(100 * len(flow_available) / len(expected), 2) if expected else 0.0,
            'missing_flow_periods': missing,
        }
    joint_total = [row['period'] for row in monthly if
                   _is_number(row.get('combined_budget_revenue_monthly')) and
                   _is_number(row.get('combined_budget_expenditure_monthly'))]
    full_caliber_expenditure = [row['period'] for row in monthly
                                if _is_number(row.get('combined_budget_expenditure_monthly'))]
    full_caliber_expenditure_yoy = [row['period'] for row in monthly
                                    if _is_number(row.get('combined_budget_expenditure_monthly_yoy'))]
    coverage_by_indicator['combined_budget_expenditure_monthly_yoy'] = {
        'base_flow_indicator': 'combined_budget_expenditure_monthly',
        'observed_span_periods': len(monthly_periods),
        'base_flow_records': len(full_caliber_expenditure),
        'derived_yoy_records': len(full_caliber_expenditure_yoy),
        'coverage_pct': (round(100 * len(full_caliber_expenditure_yoy) /
                               len(full_caliber_expenditure), 2)
                         if full_caliber_expenditure else 0.0),
        'missing_yoy_periods': [row['period'] for row in monthly
                                if _is_number(row.get('combined_budget_expenditure_monthly'))
                                and not _is_number(row.get('combined_budget_expenditure_monthly_yoy'))],
    }
    return {
        'basis': '按现有官方YTD报告的观测跨度审计；不把未披露的1月拆出，也不跨缺月差分。',
        'ytd_report_periods': len(ytd_periods),
        'ytd_first': ytd_periods[0] if ytd_periods else None,
        'ytd_latest': ytd_periods[-1] if ytd_periods else None,
        'monthly_rows_in_observed_spans': len(monthly_periods),
        'joint_total_flow_periods': len(joint_total),
        'joint_total_first': joint_total[0] if joint_total else None,
        'joint_total_latest': joint_total[-1] if joint_total else None,
        'full_caliber_expenditure_flow_periods': len(full_caliber_expenditure),
        'full_caliber_expenditure_first': full_caliber_expenditure[0] if full_caliber_expenditure else None,
        'full_caliber_expenditure_latest': full_caliber_expenditure[-1] if full_caliber_expenditure else None,
        'full_caliber_expenditure_yoy_periods': len(full_caliber_expenditure_yoy),
        'full_caliber_expenditure_yoy_first': full_caliber_expenditure_yoy[0] if full_caliber_expenditure_yoy else None,
        'full_caliber_expenditure_yoy_latest': full_caliber_expenditure_yoy[-1] if full_caliber_expenditure_yoy else None,
        'coverage_by_indicator': coverage_by_indicator,
        'warnings': [
            '官方报告是年初至今累计值；月度流量是相邻YTD差分，不是财政部直接公布的单月字段。',
            '1-2月作为一个合并窗口保留；1月没有单独官方观测。',
            '缺少相邻YTD截止期时保持 missing，不用前值、插值或跨缺月差分。',
            '两本账总收入/总支出是一般公共预算与政府性基金的简单相加，不等于财政部另行公布的法定综合财力。',
        ],
    }


def build_full_caliber_expenditure_series(monthly):
    """Expose the screenshot-compatible monthly full-caliber expenditure view.

    The value is the derived sum of the two official YTD-derived monthly flows.
    The year-on-year field compares the same reporting window in the prior year;
    it is intentionally separate from the official YTD同比 fields.
    """
    records = []
    for row in monthly:
        value = row.get('combined_budget_expenditure_monthly')
        yoy = row.get('combined_budget_expenditure_monthly_yoy')
        records.append({
            'period': row.get('period'),
            'flow_window': row.get('flow_window'),
            'months_covered': row.get('months_covered'),
            'full_caliber_expenditure_monthly': value,
            'full_caliber_expenditure_yoy_pct': yoy,
            'data_status': 'derived' if _is_number(value) else 'missing',
            'source_url': row.get('source_url'),
            'source_urls': row.get('source_urls', []),
            'source_title': row.get('source_title'),
            'value_formula': (
                'full_caliber_expenditure_monthly = '
                'general_budget_expenditure_monthly + gov_fund_expenditure_monthly'
                if _is_number(value) else None),
            'yoy_formula': row.get('combined_budget_expenditure_monthly_yoy_formula'),
            'formula': row.get('formula'),
            'missing_reason': row.get('missing_reason'),
            'yoy_missing_reason': row.get(
                'combined_budget_expenditure_monthly_yoy_missing_reason'),
        })
    latest = next((row for row in reversed(records)
                   if _is_number(row.get('full_caliber_expenditure_monthly'))), None)
    latest_yoy = next((row for row in reversed(records)
                       if _is_number(row.get('full_caliber_expenditure_yoy_pct'))), None)
    base_records = [row for row in records
                    if _is_number(row.get('full_caliber_expenditure_monthly'))]
    yoy_records = [row for row in records
                   if _is_number(row.get('full_caliber_expenditure_yoy_pct'))]

    def card(label, row, value_key, unit, formula, warning):
        value = row.get(value_key) if row else None
        return {
            'indicator_code': value_key,
            'label': label,
            'value': value,
            'unit': unit,
            'period': row.get('period') if row else None,
            'flow_window': row.get('flow_window') if row else None,
            'data_status': 'derived' if _is_number(value) else 'missing',
            'source_name': SOURCE_NAME if row and _is_number(value) else None,
            'source_url': row.get('source_url') if row and _is_number(value) else None,
            'source_urls': row.get('source_urls', []) if row and _is_number(value) else [],
            'source_title': row.get('source_title') if row and _is_number(value) else None,
            'parser_notes': (
                '由财政部一般公共预算与政府性基金官方YTD相邻差分后相加；'
                '同比比较同一报告窗口，不把1—2月拆成单月。'
                if row and _is_number(value) else None),
            'formula': formula if row and _is_number(value) else None,
            'warning': None if row and _is_number(value) else warning,
        }

    return {
        'data_status': 'derived' if latest else 'missing',
        'unit': '亿元',
        'records': records,
        'latest': latest,
        'coverage': {
            'flow_records': len(base_records),
            'flow_first': base_records[0]['period'] if base_records else None,
            'flow_latest': base_records[-1]['period'] if base_records else None,
            'yoy_records': len(yoy_records),
            'yoy_first': yoy_records[0]['period'] if yoy_records else None,
            'yoy_latest': yoy_records[-1]['period'] if yoy_records else None,
            'yoy_coverage_pct': (round(100 * len(yoy_records) / len(base_records), 2)
                                 if base_records else 0.0),
            'missing_yoy_periods': [row['period'] for row in base_records
                                    if not _is_number(row.get('full_caliber_expenditure_yoy_pct'))],
        },
        'cards': [
            card(
                '财政全口径支出（当期流量，derived）', latest,
                'full_caliber_expenditure_monthly', '亿元',
                'full_caliber_expenditure_monthly = '
                'general_budget_expenditure_monthly + gov_fund_expenditure_monthly',
                '尚无一般公共预算与政府性基金均可差分的共同月份。'),
            card(
                '财政全口径支出同比（同月，derived）', latest_yoy,
                'full_caliber_expenditure_yoy_pct', '%',
                'full_caliber_expenditure_monthly[当期] / '
                'full_caliber_expenditure_monthly[上一年同月] - 1',
                '尚无可与当前流量严格匹配的上一年同月。'),
        ],
        'formula': 'general_budget_expenditure_monthly + gov_fund_expenditure_monthly',
        'yoy_formula': 'same reporting window current year / prior year - 1',
        'notes': [
            '截图中的“全口径支出”按一般公共预算支出与政府性基金支出当期流量简单相加实现。',
            '底层官方报告是YTD累计值；当期流量由相邻YTD差分得到，1—2月保留合并窗口。',
            '同比是同一报告窗口的derived比较，不等同于财政部单列的官方YTD同比字段。',
        ],
    }


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


def _quantile(values, probability):
    """Linear-interpolated quantile for a non-empty numeric sequence."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError('quantile requires at least one value')
    position = (len(ordered) - 1) * float(probability)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _joint_historical_growth_vectors(annual):
    """Keep each year's four-account growth rates together for resampling."""
    complete = [row for row in annual if all(
        isinstance(row.get(code), (int, float)) and row.get(code) != 0
        for code in CORE_OFFICIAL_INDICATORS)]
    vectors = []
    for previous, current in zip(complete, complete[1:]):
        if current['year'] != previous['year'] + 1:
            continue
        vector = {
            code: _bounded_growth(current[code] / previous[code] - 1)
            for code in CORE_OFFICIAL_INDICATORS
        }
        vectors.append({'period': str(current['year']), 'rates': vector})
    return vectors


def simulate_budget_uncertainty(annual, anchor, first_year_rates, historical_rates,
                                horizon=3, simulations=5000, seed=20260726):
    """Paired historical-shock bootstrap around the transparent baseline path.

    This is a sensitivity distribution, not a calibrated probability forecast.
    The four growth rates from one historical year are sampled as a joint vector
    so revenue/expenditure and general/fund co-movement are not broken apart.
    """
    vectors = _joint_historical_growth_vectors(annual)
    if len(vectors) < 5:
        return {
            'data_status': 'insufficient_sample', 'records': [],
            'simulations': 0, 'n_growth_vectors': len(vectors),
            'warnings': ['完整年度同比向量少于5个，不生成模拟区间。'],
        }
    simulations = max(100, min(int(simulations), 50000))
    rng = random.Random(int(seed))
    balance_codes = (
        'general_budget_balance_ytd',
        'gov_fund_balance_ytd',
        'combined_budget_balance_ytd',
    )
    distributions = {
        anchor['year'] + offset: {code: [] for code in balance_codes}
        for offset in range(1, horizon + 1)
    }
    for _ in range(simulations):
        previous_values = {code: float(anchor[code]) for code in CORE_OFFICIAL_INDICATORS}
        for offset in range(1, horizon + 1):
            year = anchor['year'] + offset
            sampled = rng.choice(vectors)['rates']
            raw_values = {}
            for code in CORE_OFFICIAL_INDICATORS:
                baseline_rate = first_year_rates[code] if offset == 1 else historical_rates[code]
                centred_shock = sampled[code] - historical_rates[code]
                applied_rate = _bounded_growth(baseline_rate + centred_shock)
                raw_values[code] = previous_values[code] * (1 + applied_rate)
            values = derive_budget_values(raw_values)
            for code in balance_codes:
                distributions[year][code].append(values[code])
            previous_values = raw_values

    records = []
    for year, by_code in sorted(distributions.items()):
        row = {'period': str(year), 'year': year, 'data_status': 'scenario'}
        for code, values in by_code.items():
            row[f'{code}_p10'] = round(_quantile(values, 0.10), 1)
            row[f'{code}_p50'] = round(_quantile(values, 0.50), 1)
            row[f'{code}_p90'] = round(_quantile(values, 0.90), 1)
        records.append(row)

    return {
        'data_status': 'scenario', 'records': records,
        'simulations': simulations, 'seed': int(seed),
        'sample_start': str(annual[0]['year']), 'sample_end': str(anchor['year']),
        'n_growth_vectors': len(vectors), 'percentiles': [10, 50, 90],
        'method': ('paired bootstrap of contiguous annual four-indicator growth vectors; '
                   'historical shocks centred on baseline rates; growth bounded to +/-20%; '
                   'fixed random seed for reproducibility'),
        'formula': ('value[t] = value[t-1] * (1 + bound(baseline_rate[t] + '
                    'sampled_joint_growth - historical_median_growth)); '
                    'balance = revenue - expenditure'),
        'warnings': [
            'P10/P50/P90是基于历史联合波动的模型敏感性区间，不是财政结果发生概率或官方置信区间。',
            '历史样本较短且存在制度、土地市场与口径变化；增加模拟次数不会增加原始信息。',
        ],
    }


def build_budget_forecast(annual, series, horizon=3, half_year_analysis=None,
                          latest_ytd_analysis=None):
    """Build three transparent scenarios without writing them as official data."""
    if half_year_analysis is None:
        half_year_analysis = build_budget_half_year_analysis(annual, series)
    if latest_ytd_analysis is None:
        latest_ytd_analysis = build_budget_latest_ytd_analysis(annual, series)
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
    first_year_raw_rates = dict(historical_rates)
    first_year_rate_sources = {code: 'five_year_annual_median' for code in CORE_OFFICIAL_INDICATORS}
    ytd_rate_codes = []
    if latest_ytd and prior_ytd:
        for code in CORE_OFFICIAL_INDICATORS:
            current = latest_ytd.get(code)
            previous = prior_ytd.get(code)
            official_yoy_code = f'{code}_yoy_official'
            official_yoy = latest_ytd.get(official_yoy_code)
            if isinstance(official_yoy, (int, float)):
                raw_rate = float(official_yoy) / 100.0
                first_year_raw_rates[code] = raw_rate
                first_year_rates[code] = _bounded_growth(raw_rate)
                first_year_rate_sources[code] = 'official_comparable_yoy'
                ytd_rate_codes.append(code)
            elif isinstance(current, (int, float)) and isinstance(previous, (int, float)) and previous:
                raw_rate = current / previous - 1
                first_year_raw_rates[code] = raw_rate
                first_year_rates[code] = _bounded_growth(raw_rate)
                first_year_rate_sources[code] = 'derived_same_period_ytd'
                ytd_rate_codes.append(code)

    scenario_specs = {
        'baseline': {'label': '最可能（基准）', 'revenue_adjustment': 0.0,
                     'expenditure_adjustment': 0.0,
                     'interpretation': '当前YTD与近期历史中位增速的点估计'},
        'improvement': {'label': '较好（改善）', 'revenue_adjustment': 0.02,
                        'expenditure_adjustment': -0.02,
                        'interpretation': '收入增速+2pp、支出增速-2pp的改善压力测试'},
        'pressure': {'label': '较坏（承压）', 'revenue_adjustment': -0.02,
                     'expenditure_adjustment': 0.02,
                     'interpretation': '收入增速-2pp、支出增速+2pp的承压压力测试'},
    }
    half_current = (half_year_analysis or {}).get('current') or {}
    half_scenarios = half_current.get('scenarios') or {}
    latest_current = (latest_ytd_analysis or {}).get('current') or {}
    latest_scenarios = latest_current.get('scenarios') or {}
    latest_cutoff_month = latest_current.get('cutoff_month')
    seasonal_ready = bool(
        latest_current.get('year') and
        all((latest_ytd_analysis.get('share_stats', {}).get(_budget_short_code(code), {}).get('n_obs', 0)
             >= 3) for code in CORE_OFFICIAL_INDICATORS) and
        all((latest_scenarios.get('baseline', {}).get('values', {}).get(code) is not None)
            for code in CORE_OFFICIAL_INDICATORS))
    if seasonal_ready:
        scenario_specs['baseline']['interpretation'] = (
            f"当前年按同科目历史{latest_current.get('cutoff_label', '最新累计月')}/全年比例中位数转换；后续按近期年度增速中位数")
        scenario_specs['improvement']['interpretation'] = (
            f"当前年收入使用{latest_current.get('cutoff_label', '最新累计月')}/全年比例第25百分位、支出使用第75百分位；后续收入+2pp、支出-2pp")
        scenario_specs['pressure']['interpretation'] = (
            f"当前年收入使用{latest_current.get('cutoff_label', '最新累计月')}/全年比例第75百分位、支出使用第25百分位；后续收入-2pp、支出+2pp")
    scenarios = {}
    revenue_codes = {'general_budget_revenue_ytd', 'gov_fund_revenue_ytd'}
    for scenario_code, spec in scenario_specs.items():
        previous_values = {code: anchor[code] for code in CORE_OFFICIAL_INDICATORS}
        rows = []
        for offset in range(1, horizon + 1):
            year = anchor['year'] + offset
            values = {}
            if offset == 1 and seasonal_ready and scenario_code in latest_scenarios:
                values = {code: latest_scenarios[scenario_code]['values'][code]
                          for code in CORE_OFFICIAL_INDICATORS}
                method = (
                    f"current-year {latest_current.get('cutoff_label', 'latest YTD')} official values "
                    'converted by same-account historical same-cutoff/full-year seasonal share; '
                    'scenario uses empirical share quantile; no direct YTD-yoy-to-full-year extrapolation')
            else:
                for code in CORE_OFFICIAL_INDICATORS:
                    base_rate = historical_rates[code]
                    adjustment = (spec['revenue_adjustment'] if code in revenue_codes
                                  else spec['expenditure_adjustment'])
                    applied_rate = _bounded_growth(base_rate + adjustment)
                    values[code] = round(previous_values[code] * (1 + applied_rate), 1)
                method = 'five-change median annual growth with scenario adjustment; growth bounded to ±20%'
            rows.append(_forecast_row(year, values, scenario_code, method))
            previous_values = values
        scenarios[scenario_code] = {'label': spec['label'], 'records': rows}

    if seasonal_ready:
        baseline_values = latest_scenarios['baseline']['values']
        current_simulation = latest_current.get('simulation') or {
            'data_status': 'insufficient_sample', 'records': [], 'simulations': 0,
        }
        seasonal_anchor = {'year': latest_current['year'], **baseline_values}
        future_uncertainty = simulate_budget_uncertainty(
            complete, seasonal_anchor, historical_rates, historical_rates,
            horizon=max(int(horizon) - 1, 0))
        uncertainty = dict(future_uncertainty)
        uncertainty['records'] = (current_simulation.get('records') or []) + \
            (future_uncertainty.get('records') or [])
        uncertainty['current_year'] = current_simulation
        uncertainty['method'] = (
            f"当前年固定官方{latest_current.get('cutoff_label', '最新累计月')}累计值并对历史同截止月/全年比例做联合bootstrap；"
            '后续年度再从历史年度联合增速向量抽样。')
        uncertainty['warnings'] = _dedupe(
            (current_simulation.get('warnings') or []) +
            (future_uncertainty.get('warnings') or []))
    else:
        uncertainty = simulate_budget_uncertainty(
            complete, anchor, first_year_rates, historical_rates, horizon=horizon)

    return {
        'data_status': 'scenario', 'anchor_year': anchor['year'], 'horizon_years': horizon,
        'latest_ytd_period': latest_ytd['period'] if latest_ytd else None,
        'comparison_ytd_period': prior_ytd['period'] if prior_ytd else None,
        'latest_ytd_cutoff_month': latest_cutoff_month,
        'latest_ytd_cutoff_label': latest_current.get('cutoff_label') if latest_current else None,
        'historical_growth_rates': historical_rates,
        'first_year_growth_rates_raw': first_year_raw_rates,
        'first_year_growth_rates': first_year_rates,
        'first_year_growth_rate_sources': first_year_rate_sources,
        'current_year_forecast_mode': (
            ('h1_seasonality' if latest_cutoff_month == 6 else 'latest_ytd_seasonality')
            if seasonal_ready else
            ('h1_yoy_fallback' if latest_cutoff_month == 6 else 'latest_ytd_yoy_fallback')),
        'current_year_h1_growth_rates_raw': first_year_raw_rates,
        'current_year_h1_growth_rate_sources': first_year_rate_sources,
        'current_year_ytd_growth_rates_raw': first_year_raw_rates,
        'current_year_ytd_growth_rate_sources': first_year_rate_sources,
        'half_year_analysis': half_year_analysis,
        'latest_ytd_analysis': latest_ytd_analysis,
        'scenario_definitions': scenario_specs,
        'scenarios': scenarios,
        'uncertainty': uncertainty,
        'warnings': [
            '情景估计不是财政部预测，不写入 official observation。',
            (f"当前年度使用同科目历史{latest_current.get('cutoff_label', '最新累计月')}/全年比例转换；"
             '累计同比只作为背景信息，不直接当作全年同比。' if seasonal_ready else
             '历史同截止月/全年比例样本不足，当前年度回退为同月累计同比/近期年度中位数方法。'),
            '较好/较坏情景分别在收入与支出增速上作 ±2 个百分点调整；它们是压力测试，不是理论最好/最坏值。',
            (f"当前年模拟使用历史四项{latest_current.get('cutoff_label', '最新累计月')}/全年比例联合抽样；后续年度模拟使用同一年四项收支增速联合抽样，"
             '固定种子运行5000次。' if seasonal_ready else
             '模拟区间使用同一年四项收支增速联合抽样，固定种子运行5000次；所有增速限制在 ±20%。'),
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
    deficit_rows = [r for r in rows if r['indicator_code'] ==
                    OFFICIAL_NATIONAL_FISCAL_DEFICIT_INDICATOR]
    annual = attach_official_national_fiscal_deficit(_annual_series(series), deficit_rows)
    historical_summary = build_historical_fiscal_summary(annual, deficit_rows)
    current_year_summary = build_current_year_fiscal_summary(
        series, annual, OFFICIAL_NATIONAL_FISCAL_DEFICIT_PLAN)
    land_transfer_annual = build_land_transfer_annual_series(series)
    land_transfer_half_year = build_land_transfer_half_year_analysis(series)
    land_transfer_latest_ytd = build_land_transfer_latest_ytd_analysis(series)
    budget_half_year = build_budget_half_year_analysis(annual, series)
    budget_latest_ytd = build_budget_latest_ytd_analysis(annual, series)
    monthly = derive_monthly_budget_series(series)
    monthly_coverage = build_budget_monthly_coverage(series, monthly)
    full_caliber_expenditure = build_full_caliber_expenditure_series(monthly)
    forecast = build_budget_forecast(
        annual, series, half_year_analysis=budget_half_year,
        latest_ytd_analysis=budget_latest_ytd)
    latest = series[-1] if series else None
    latest_rows = {r['indicator_code']: r for r in rows if latest and r['period'] == latest['period']}
    cards = []
    for code in INDICATORS:
        r = latest_rows.get(code)
        cards.append({
            'indicator_code': code,
            'label': INDICATORS[code], 'value': r['value'] if r else None,
            'unit': r['unit'] if r else ('%' if code.endswith('_yoy_official') else '亿元'),
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
    latest_monthly = next((row for row in reversed(monthly)
                           if _is_number(row.get('combined_budget_revenue_monthly')) and
                           _is_number(row.get('combined_budget_expenditure_monthly'))), None)
    monthly_cards = []
    for code, label in (
            ('combined_budget_revenue_monthly', '两本账总收入（当期流量，简单相加）'),
            ('combined_budget_expenditure_monthly', '两本账总支出（当期流量，简单相加）')):
        monthly_cards.append({
            'indicator_code': code,
            'label': label,
            'value': latest_monthly.get(code) if latest_monthly else None,
            'unit': '亿元',
            'period': latest_monthly.get('period') if latest_monthly else None,
            'flow_window': latest_monthly.get('flow_window') if latest_monthly else None,
            'data_status': 'derived' if latest_monthly else 'missing',
            'source_name': SOURCE_NAME if latest_monthly else None,
            'source_url': latest_monthly.get('source_url') if latest_monthly else None,
            'source_urls': latest_monthly.get('source_urls', []) if latest_monthly else [],
            'source_title': latest_monthly.get('source_title') if latest_monthly else None,
            'parser_notes': (
                '由一般公共预算与政府性基金相邻YTD差分后简单相加；'
                '当前期窗口见 flow_window，不跨缺月。'
                if latest_monthly else None),
            'formula': (
                'combined_budget_revenue_monthly = general_budget_revenue_monthly + '
                'gov_fund_revenue_monthly'
                if code == 'combined_budget_revenue_monthly' else
                'combined_budget_expenditure_monthly = general_budget_expenditure_monthly + '
                'gov_fund_expenditure_monthly') if latest_monthly else None,
            'warning': None if latest_monthly else '尚无一般公共预算与政府性基金均可差分的共同月份。',
        })
    monthly_cards.extend(full_caliber_expenditure.get('cards', [])[1:])
    coverage = {
        'periods': len(series),
        'earliest': series[0]['period'] if series else None,
        'latest': series[-1]['period'] if series else None,
        'annual_periods': len(annual),
        'annual_earliest': annual[0]['period'] if annual else None,
        'annual_latest': annual[-1]['period'] if annual else None,
        'historical_fiscal_summary': historical_summary.get('coverage', {}),
        'current_year_fiscal_summary': {
            'period': current_year_summary.get('period'),
            'year': current_year_summary.get('year'),
            'data_status': current_year_summary.get('data_status'),
        },
        'land_transfer_annual_periods': len(land_transfer_annual),
        'land_transfer_annual_start': (
            land_transfer_annual[0]['period'] if land_transfer_annual else None),
        'land_transfer_annual_end': (
            land_transfer_annual[-1]['period'] if land_transfer_annual else None),
        'land_transfer_observed_years': sum(
            row.get('data_status') == 'official' for row in land_transfer_annual),
        'land_transfer_missing_years': [
            row['period'] for row in land_transfer_annual
            if row.get('data_status') == 'missing'
        ],
        'land_transfer_half_year_matched_years': land_transfer_half_year.get('n_obs', 0),
        'land_transfer_half_year_sample_start': land_transfer_half_year.get('sample_start'),
        'land_transfer_half_year_sample_end': land_transfer_half_year.get('sample_end'),
        'land_transfer_latest_ytd_period': land_transfer_latest_ytd.get('current', {}).get('period')
        if land_transfer_latest_ytd.get('current') else None,
        'land_transfer_latest_ytd_cutoff_month': land_transfer_latest_ytd.get('current', {}).get('cutoff_month')
        if land_transfer_latest_ytd.get('current') else None,
        'land_transfer_latest_ytd_matched_years': land_transfer_latest_ytd.get('n_obs', 0),
        'budget_latest_ytd_period': budget_latest_ytd.get('current', {}).get('period')
        if budget_latest_ytd.get('current') else None,
        'budget_latest_ytd_cutoff_month': budget_latest_ytd.get('current', {}).get('cutoff_month')
        if budget_latest_ytd.get('current') else None,
        'budget_latest_ytd_matched_years': budget_latest_ytd.get('n_obs', 0),
        'monthly_flow': monthly_coverage,
        'full_caliber_expenditure': full_caliber_expenditure.get('coverage', {}),
    }
    return {
        'data_status': 'official' if rows else 'missing',
        'coverage': coverage,
        'cards': cards, 'annual_cards': annual_cards, 'monthly_cards': monthly_cards,
        'series': series, 'annual_series': annual,
        'historical_fiscal_summary': historical_summary,
        'current_year_fiscal_summary': current_year_summary,
        'land_transfer_annual_series': land_transfer_annual,
        'land_transfer_half_year_analysis': land_transfer_half_year,
        'land_transfer_latest_ytd_analysis': land_transfer_latest_ytd,
        'budget_half_year_analysis': budget_half_year,
        'budget_latest_ytd_analysis': budget_latest_ytd,
        'monthly_series': monthly,
        'full_caliber_expenditure': full_caliber_expenditure,
        'monthly_coverage': monthly_coverage, 'forecast': forecast,
        'warnings': [] if rows else ['财政收支尚未抓取；未生成 mock。'],
        'notes': [
            '官方报告为年初至今累计(YTD)；收支差额为 derived，不等于官方预算口径赤字。',
            '历年财政汇总单独保留财政部年度报告的法定赤字；账面缺口按支出减收入另列，禁止相互替代。',
            '当前年度汇总只显示最新YTD实际、YTD账面缺口和官方预算计划；全年法定赤字待年度报告。',
            '一般公共预算与政府性基金的合计仅为简单相加分析视图，未抵销调入调出或跨账本转移。',
            '2010—2011 年国库司年度财政收支稿未同时披露全国政府性基金收支，基金年度序列从直接可核验的 2012 年开始。',
            '全国土地出让收入年度表从2007年制度化口径开始；表中缺年保留为空，不把2007年前预算外/扣除成本口径与2007年后全额入库口径直接拼接。',
            '土地出让收入年度值取财政部12月YTD官方观测；年度表不是将月度观测相加，也不对缺失年份插值。',
            '土地出让收入半年度分析只匹配同一年6月YTD与12月YTD；历史比例和回测为derived，当前年机械推演不等于官方预测。',
            '全年推演锚点自动使用最新非12月官方累计月；与同截止月历史/12月配对，保留上半年分析作为回测对照。',
            '财政收支全年推演优先使用同科目历史H1/全年比例；上半年同比不直接当作全年同比，模拟区间仅为历史季节性敏感性。',
            '月度流量由相邻YTD差分得到；1-2月为合并窗口，缺少相邻YTD时不跨缺月计算。',
        ],
    }
