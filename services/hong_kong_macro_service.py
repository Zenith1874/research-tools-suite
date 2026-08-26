# -*- coding: utf-8 -*-
"""香港宏观独立模块：官方源发现、解析、审计入库和描述性联动分析。

数据边界：
* 香港住宅/交易数据来自差饷物业估价署（RVD）和土地注册处；
* 经济、货币和储备资产数据来自香港金融管理局（HKMA）开放 API；
* 货物再出口来自香港政府统计处贸易统计 API（Trade-IDDS）；
* 年度宏观补充指标来自政府统计处 CSD-IDDS。

该模块不把香港数据写入中国城市经济表，也不把香港金融管理局的外汇
储备资产当作中国国家外汇储备。每个来源独立记录成功/失败状态；来源失败
时保留旧观测，不删除历史数据。
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import subprocess
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from services.china_macro_service import connect, ensure_china_macro_tables


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / 'data' / 'hong_kong_macro_raw'
UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 Chrome/124 Safari/537.36')}
TIMEOUT = 45
HK_MACRO_SCHEMA_VERSION = 6

RVD_INDEX_PAGE = 'https://www.rvd.gov.hk/en/publications/property_market_statistics.html'
RVD_BASE = 'https://www.rvd.gov.hk/'
RVD_FILES = {
    'HK_RVD_PRIVATE_AVG_RENT': 'doc/en/statistics/his_data_1.xls',
    'HK_RVD_PRIVATE_AVG_PRICE': 'doc/en/statistics/his_data_2.xls',
    'HK_RVD_RENT_INDEX': 'doc/en/statistics/his_data_3.xls',
    'HK_RVD_PRICE_INDEX': 'doc/en/statistics/his_data_4.xls',
    'HK_RVD_DOMESTIC_SALES': 'doc/en/statistics/his_data_16.xls',
    'HK_RVD_PRIVATE_STOCK_FLOW': 'doc/en/statistics/private_domestic.xls',
}
LANDREG_BASE = 'https://www.landreg.gov.hk'
LANDREG_PRIMARY_PATHS = {
    'agt-primary': '2022-2026', 'agt-pri-5': '2021-2025',
    'agt-pri-4': '2016-2020', 'agt-pri-3': '2011-2015',
    'agt-pri-2': '2006-2010', 'agt-pri-1': '2002-2005',
}
HKMA_BASE = 'https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin'
HKMA_URLS = {
    'HK_HKMA_FC_RESERVE_ASSETS': f'{HKMA_BASE}/ef-fc-resv-assets/fc-resv-assests',
    'HK_HKMA_ECONOMIC': f'{HKMA_BASE}/financial/economic-statistics',
    'HK_HKMA_MONETARY': f'{HKMA_BASE}/financial/monetary-statistics',
    'HK_HKMA_BANKING_STATS': f'{HKMA_BASE}/financial/banking-statistics',
    'HK_HKMA_CUSTOMER_DEPOSITS': f'{HKMA_BASE}/banking/customer-deposits-by-type-hkd-fc',
    'HK_HKMA_RMB_DEPOSITS': f'{HKMA_BASE}/banking/customer-deposits-by-type-cny',
    'HK_HKMA_LOANS_BY_TYPE': f'{HKMA_BASE}/banking/loans-by-type-lb',
    'HK_HKMA_MORTGAGE_SURVEY': f'{HKMA_BASE}/banking/residential-mortgage-survey',
    'HK_HKMA_NEGATIVE_EQUITY': f'{HKMA_BASE}/banking/residential-mortgage-loans-neg-equity',
}
HKMA_REQUEST_PARAMS = {
    'HK_HKMA_MORTGAGE_SURVEY': {'segment': 'new'},
}
TRADE_API_SPEC = 'https://tradeidds.censtatd.gov.hk/MetadataLink/ApiSpec/API_eng.pdf'
TRADE_API_URL = 'https://tradeidds.censtatd.gov.hk/api/get'
CSD_CTT_URL = 'https://idds.censtatd.gov.hk/api/Cidds/GetCTT/{table_id}'
CSD_WEB_TABLE_API = 'https://www.censtatd.gov.hk/api/get.php'

# The API accepts at most 30 country/territory codes and at most 20
# commodity codes. Keep these requests explicit so a classification change
# cannot silently turn a dimension chart into an opaque aggregate. T210's
# current ``Principal SITC 2-digit (Division)`` universe has 68 defined codes;
# the omitted values are not valid commodity codes in the live official API.
# It is fetched in chunks because the UI's Top N must be selected from the
# complete defined division universe, not from an arbitrary first page.
SITC2_UNDEFINED_CODES = frozenset({
    10, 13, 14, 15, 16, 17, 18, 19, 20, 30, 31, 36, 37, 38, 39, 40,
    44, 45, 46, 47, 48, 49, 50, 60, 70, 80, 86, 90, 92, 94, 95, 99,
})
SITC2_CODES = tuple(f'{index:02d}' for index in range(100)
                    if index not in SITC2_UNDEFINED_CODES)
TRADE_DIMENSION_MAX_CODES = 20
TRADE_DIMENSION_REQUESTS = {
    'mainland_origin': {
        'source_id': 'HK_TRADE_IDDS_MAINLAND_ORIGIN',
        'title': 'Imports from Chinese Mainland by origin',
        'dimension_type': 'origin', 'dimension_key': 'CN',
        'entry_url': 'https://tradeidds.censtatd.gov.hk/CommonTable/T057',
        'params': {'ttype': '1', 'coclass': 'C', 'co': 'CN'},
        'note': 'ttype=1 imports；co=CN 为原产地，不等于进口报关地/供应地。',
    },
    'mainland_consignment': {
        'source_id': 'HK_TRADE_IDDS_MAINLAND_CONSIGNMENT',
        'title': 'Imports from Chinese Mainland by consignment',
        'dimension_type': 'consignment', 'dimension_key': 'CN',
        'entry_url': 'https://tradeidds.censtatd.gov.hk/CommonTable/T057',
        'params': {'ttype': '1', 'ccclass': 'C', 'cc': 'CN'},
        'note': 'ttype=1 imports；cc=CN 为货物寄运/供应地，不等于原产地。',
    },
    'mainland_destination': {
        'source_id': 'HK_TRADE_IDDS_MAINLAND_DESTINATION',
        'title': 'Total exports to Chinese Mainland by destination',
        'dimension_type': 'destination', 'dimension_key': 'CN',
        'entry_url': 'https://tradeidds.censtatd.gov.hk/CommonTable/ETR08a03',
        'params': {'ttype': '4', 'ccclass': 'C', 'cc': 'CN'},
        'note': 'ttype=4 total exports；cc=CN 为出口寄运目的地/目的地统计。',
    },
    'top_origins': {
        'source_id': 'HK_TRADE_IDDS_TOP_ORIGINS',
        'title': 'Imports by all origin countries/territories',
        'dimension_type': 'origin_top', 'dimension_key': 'ALL',
        'entry_url': 'https://tradeidds.censtatd.gov.hk/CommonTable/T057',
        'params': {'ttype': '1', 'coclass': 'C', 'co': 'ALL'},
        'note': 'ttype=1 imports；co=ALL 返回全部有记录的原产地，页面按最新月份货值取 Top 10。',
    },
    'top_destinations': {
        'source_id': 'HK_TRADE_IDDS_TOP_DESTINATIONS',
        'title': 'Total exports by all destination countries/territories',
        'dimension_type': 'destination_top', 'dimension_key': 'ALL',
        'entry_url': 'https://tradeidds.censtatd.gov.hk/CommonTable/ETR08a03',
        'params': {'ttype': '4', 'ccclass': 'C', 'cc': 'ALL'},
        'note': 'ttype=4 total exports；cc=ALL 返回全部有记录的出口目的地，页面按最新月份货值取 Top 10。',
    },
    'top_sitc2_exports': {
        'source_id': 'HK_TRADE_IDDS_TOP_SITC2_EXPORTS',
        'title': 'Total exports by SITC 2-digit commodity division',
        'dimension_type': 'commodity_sitc2', 'dimension_key': 'SITC2',
        'entry_url': 'https://tradeidds.censtatd.gov.hk/CommonTable/T210',
        'params': {'ttype': '4', 'codeclass': 'SITC2'},
        'dimension_values': SITC2_CODES,
        'note': 'ttype=4 total exports；T210 当前定义的 68 个 SITC2 两位商品分类，页面按最新月份货值排序为 Top N。',
    },
}

# CSD Web Table is the finer-grained official table API. The response format
# is intentionally kept in a separate table because a single table contains
# many series with different units and dimensions. ``full_series=1`` is the
# public data.gov-compatible shortcut; a future opaque ``param`` can be added
# per table without changing the parser or database contract.
CSD_WEB_TABLES = {
    '310-31002': {'title': 'GDP by expenditure at current market prices', 'frequency': 'quarterly'},
    '310-31003': {'title': 'GDP by expenditure in chained 2024 dollars', 'frequency': 'quarterly'},
    '310-31007': {'title': 'Seasonally adjusted GDP by expenditure', 'frequency': 'quarterly'},
    '310-33041': {'title': 'Trade in services by major service component', 'frequency': 'quarterly'},
    '310-33042': {'title': 'Trade in services by service component', 'frequency': 'quarterly'},
    '620-67001': {'title': 'Value of total retail sales', 'frequency': 'monthly'},
    '620-67002': {'title': 'Retail sales by selected types of outlet', 'frequency': 'monthly'},
    '620-67003': {'title': 'Volume of retail sales', 'frequency': 'monthly'},
    '620-67021': {'title': 'Seasonally adjusted retail sales', 'frequency': 'monthly'},
    '650-80001': {'title': 'Visitor arrivals by country/territory', 'frequency': 'monthly'},
    '650-80005': {'title': 'Visitor arrivals and length of stay', 'frequency': 'monthly'},
    '110-01003': {'title': 'Population growth by component', 'frequency': 'semiannual'},
    '315-37001': {'title': 'Balance of payments summary', 'frequency': 'quarterly'},
    '315-37003': {'title': 'Balance of payments current account', 'frequency': 'quarterly'},
    '315-37004': {'title': 'Balance of payments financial account', 'frequency': 'quarterly'},
    '315-37021': {'title': 'International investment position', 'frequency': 'quarterly'},
    '315-37031': {'title': 'External debt statistics', 'frequency': 'quarterly'},
}
CSD_WEB_UPDATE_TABLES = tuple(CSD_WEB_TABLES)

# Verified from the retained official 110-01003 payload and its table notes.
# Other sv codes are not guessed: the parser emits an explicit unknown label
# plus a structured missing_reason until a table-specific dictionary is
# verified from source documentation.
CSD_VERIFIED_CONSTRUCT_LABELS = {
    ('110-01003', 'PG'): 'Population growth',
    ('110-01003', 'PGR'): 'Population growth rate',
    ('110-01003', 'NC'): 'Natural change (births less deaths)',
    ('110-01003', 'NM'): 'Net movement (inflow less outflow)',
    ('110-01003', 'BIRTHS_PRO'): 'Births',
    ('110-01003', 'DEATHS_PRO'): 'Deaths',
}


# name, unit, frequency, category, source_id
INDICATORS = {
    'HK_RVD_PRIVATE_AVG_RENT': ('私人住宅平均租金', 'HK$ / m²', 'monthly', 'housing', 'HK_RVD_AVG_RENT'),
    'HK_RVD_PRIVATE_AVG_PRICE': ('私人住宅平均售价', 'HK$ / m²', 'monthly', 'housing', 'HK_RVD_AVG_PRICE'),
    'HK_RVD_RENT_INDEX': ('私人住宅租金指数', 'index', 'monthly', 'housing', 'HK_RVD_RENT_INDEX'),
    'HK_RVD_PRICE_INDEX': ('私人住宅价格指数', 'index', 'monthly', 'housing', 'HK_RVD_PRICE_INDEX'),
    'HK_RVD_RENT_INDEX_QUARTERLY': ('私人住宅租金指数（季度历史）', 'index', 'quarterly', 'housing', 'HK_RVD_RENT_INDEX'),
    'HK_RVD_RENT_INDEX_ANNUAL': ('私人住宅租金指数（年度历史）', 'index', 'annual', 'housing', 'HK_RVD_RENT_INDEX'),
    'HK_RVD_PRICE_INDEX_QUARTERLY': ('私人住宅价格指数（季度历史）', 'index', 'quarterly', 'housing', 'HK_RVD_PRICE_INDEX'),
    'HK_RVD_PRICE_INDEX_ANNUAL': ('私人住宅价格指数（年度历史）', 'index', 'annual', 'housing', 'HK_RVD_PRICE_INDEX'),
    'HK_RVD_PRIMARY_SALES_COUNT': ('私人住宅一手销售宗数', 'agreements', 'monthly', 'housing', 'HK_RVD_DOMESTIC_SALES'),
    'HK_RVD_PRIMARY_SALES_VALUE': ('私人住宅一手销售金额', '$ million', 'monthly', 'housing', 'HK_RVD_DOMESTIC_SALES'),
    'HK_RVD_SECONDARY_SALES_COUNT': ('私人住宅二手销售宗数', 'agreements', 'monthly', 'housing', 'HK_RVD_DOMESTIC_SALES'),
    'HK_RVD_SECONDARY_SALES_VALUE': ('私人住宅二手销售金额', '$ million', 'monthly', 'housing', 'HK_RVD_DOMESTIC_SALES'),
    'HK_RVD_TOTAL_SALES_COUNT': ('私人住宅一二手销售宗数合计', 'agreements', 'monthly', 'housing', 'HK_RVD_DOMESTIC_SALES'),
    'HK_RVD_TOTAL_SALES_VALUE': ('私人住宅一二手销售金额合计', '$ million', 'monthly', 'housing', 'HK_RVD_DOMESTIC_SALES'),
    'HK_RVD_COMPLETIONS': ('私人住宅落成量', 'units', 'annual', 'housing', 'HK_RVD_PRIVATE_STOCK_FLOW'),
    'HK_RVD_COMPLETIONS_YTD': ('私人住宅落成量（截至期暂定累计）', 'units', 'semiannual', 'housing', 'HK_RVD_PRIVATE_STOCK_FLOW'),
    'HK_RVD_STOCK': ('私人住宅总存量', 'units', 'annual', 'housing', 'HK_RVD_PRIVATE_STOCK_FLOW'),
    'HK_RVD_VACANCY_UNITS': ('私人住宅空置量', 'units', 'annual', 'housing', 'HK_RVD_PRIVATE_STOCK_FLOW'),
    'HK_RVD_VACANCY_RATE': ('私人住宅空置率', '%', 'annual', 'housing', 'HK_RVD_PRIVATE_STOCK_FLOW'),
    'HK_RVD_TAKE_UP': ('私人住宅入伙量', 'units', 'annual', 'housing', 'HK_RVD_PRIVATE_STOCK_FLOW'),

    'HK_LR_PRIMARY_SALES_COUNT': ('土地注册处住宅一手注册买卖合约宗数', 'agreements', 'monthly', 'housing', 'HK_LANDREG_PRIMARY'),
    'HK_LR_SECONDARY_SALES_COUNT': ('土地注册处住宅二手注册买卖合约宗数', 'agreements', 'monthly', 'housing', 'HK_LANDREG_PRIMARY'),
    'HK_LR_TOTAL_SALES_COUNT': ('土地注册处住宅一二手注册买卖合约宗数合计', 'agreements', 'monthly', 'housing', 'HK_LANDREG_PRIMARY'),
    'HK_LR_PRIMARY_SALES_VALUE': ('土地注册处住宅一手注册买卖合约金额', 'HK$ million', 'monthly', 'housing', 'HK_LANDREG_PRIMARY'),
    'HK_LR_SECONDARY_SALES_VALUE': ('土地注册处住宅二手注册买卖合约金额', 'HK$ million', 'monthly', 'housing', 'HK_LANDREG_PRIMARY'),
    'HK_LR_TOTAL_SALES_VALUE': ('土地注册处住宅一二手注册买卖合约金额合计', 'HK$ million', 'monthly', 'housing', 'HK_LANDREG_PRIMARY'),

    'HK_HKMA_FC_RESERVE_ASSETS_EF': ('外汇基金外币储备资产', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_FC_RESERVE_ASSETS_LF': ('土地基金外币储备资产', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_FC_RESERVE_ASSETS_TOTAL': ('香港外币储备资产合计', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_FC_RESERVE_ASSETS_CONTRACTS_TOTAL': ('香港含未交收外汇合约的储备资产', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_UNSETTLED_FX_CONTRACTS_EF': ('外汇基金未交收外汇合约', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_UNSETTLED_FX_CONTRACTS_LF': ('土地基金未交收外汇合约', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_UNSETTLED_FX_CONTRACTS_TOTAL': ('未交收外汇合约合计', 'US$ million', 'monthly', 'reserves_finance', 'HK_HKMA_FC_RESERVE_ASSETS'),
    'HK_HKMA_NOMINAL_GDP': ('香港名义本地生产总值', 'HK$ million', 'quarterly', 'economy', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_REAL_GDP': ('香港实质本地生产总值', 'HK$ million', 'quarterly', 'economy', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_GOV_CONSOLIDATED_BALANCE': ('香港政府综合结余', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_CPI_INDEX': ('香港综合消费物价指数', 'index', 'monthly', 'economy', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_UNEMPLOYMENT_RATE': ('香港失业率', '%', 'monthly', 'economy', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_CURRENT_ACCOUNT_BALANCE': ('香港经常帐结余', 'HK$ million', 'quarterly', 'economy', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_FC_RESERVE_USD_BN': ('香港外汇储备（经济统计口径）', 'US$ billion', 'monthly', 'reserves_finance', 'HK_HKMA_ECONOMIC'),
    'HK_HKMA_MONETARY_BASE': ('香港货币基础', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_AGGREGATE_BALANCE': ('香港总结余', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_EF_BILLS_NOTES': ('外汇基金票据及债券', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_NOTES_COINS_CIRCULATION': ('流通纸币及硬币', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_M1_TOTAL': ('香港货币供应 M1', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_M1_HKD': ('香港货币供应 M1（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_M2_TOTAL': ('香港货币供应 M2', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_M2_HKD': ('香港货币供应 M2（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_M3_TOTAL': ('香港货币供应 M3', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_M3_HKD': ('香港货币供应 M3（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_HIBOR_OVERNIGHT': ('隔夜 HIBOR', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_HIBOR_3M': ('3 个月 HIBOR', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_BEST_LENDING_RATE': ('最优惠贷款利率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_DISCOUNT_WINDOW_BASE_RATE': ('贴现窗基本利率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_DEPOSIT_RATE_3M': ('3 个月存款利率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_DEPOSIT_RATE_SAVING': ('储蓄存款利率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_EXRATE_HKD_USD': ('港元兑美元汇率', 'HKD per USD', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_NEER_INDEX': ('港元名义有效汇率指数', 'index', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_EFPAPER_YIELD_3M': ('外汇基金票据 3 个月收益率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),
    'HK_HKMA_GOVBOND_YIELD_10Y': ('香港政府债券 10 年收益率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MONETARY'),

    'HK_HKMA_BANKING_NO_AIS': ('香港银行体系认可机构数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_TOTAL_ASSETS': ('香港银行体系总资产', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_TOTAL_EXTERNAL_CLAIMS': ('香港银行体系对外总债权', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_TOTAL_EXTERNAL_LIABILITIES': ('香港银行体系对外总负债', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_HKD': ('香港银行客户存款（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_FC': ('香港银行客户存款（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_TOTAL': ('香港银行客户存款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_LOANS_IN_HK': ('香港银行在港使用贷款', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_LOANS_OUTSIDE_HK': ('香港银行在港外使用贷款', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_LOANS_TOTAL': ('香港银行贷款总额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_RESIDENTIAL_MORTGAGE_LOANS': ('香港银行住宅按揭贷款', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_CLASSIFIED_LOANS': ('香港银行分类贷款', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_MORTGAGE_DELINQUENCY_RATIO': ('住宅按揭贷款拖欠比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),
    'HK_HKMA_BANKING_CREDIT_CARD_CHARGE_OFF_RATIO': ('信用卡撇账比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_BANKING_STATS'),

    'HK_HKMA_MORTGAGE_OUTSTANDING_AMT': ('住宅按揭未偿还贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_3M': ('住宅按揭三个月以上拖欠比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_6M': ('住宅按揭六个月以上拖欠比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_RESCHEDULED_RATIO': ('住宅按揭经重组贷款比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_APPLICATIONS': ('住宅按揭新申请宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_DRAWN_AMT': ('住宅按揭新取用贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_DRAWN_COUNT': ('住宅按揭新取用贷款宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_APPROVED_AMT': ('住宅按揭新批贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_APPROVED_COUNT': ('住宅按揭新批贷款宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_APPROVED_AVG_SIZE': ('住宅按揭新批平均贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_APPROVED_LTV': ('住宅按揭新批平均贷款价值比', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_NEW_APPROVED_LIFE': ('住宅按揭新批平均合约期', 'month', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_PRIMARY_AMT': ('住宅按揭新批一手贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_SECONDARY_AMT': ('住宅按揭新批二手贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_REFIN_AMT': ('住宅按揭新批转按贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_PRIMARY_COUNT': ('住宅按揭新批一手贷款宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_SECONDARY_COUNT': ('住宅按揭新批二手贷款宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_REFIN_COUNT': ('住宅按揭新批转按宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_UNDRAWN_AMT': ('住宅按揭已批未取用贷款额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_APPROVED_UNDRAWN_COUNT': ('住宅按揭已批未取用贷款宗数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_RATE_HIBOR': ('新批住宅按揭参考 HIBOR 比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_RATE_BLR': ('新批住宅按揭参考最优惠贷款利率比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_RATE_FIXED': ('新批住宅按揭固定利率比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),
    'HK_HKMA_MORTGAGE_RATE_OTHER': ('新批住宅按揭其他利率比率', '%', 'monthly', 'reserves_finance', 'HK_HKMA_MORTGAGE_SURVEY'),

    'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT': ('负资产住宅按揭贷款宗数', 'count', 'quarterly', 'reserves_finance', 'HK_HKMA_NEGATIVE_EQUITY'),
    'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT_RATIO': ('负资产住宅按揭贷款宗数占比', '%', 'quarterly', 'reserves_finance', 'HK_HKMA_NEGATIVE_EQUITY'),
    'HK_HKMA_NEGATIVE_EQUITY_LOANS_AMT': ('负资产住宅按揭未偿还贷款额', 'HK$ million', 'quarterly', 'reserves_finance', 'HK_HKMA_NEGATIVE_EQUITY'),
    'HK_HKMA_NEGATIVE_EQUITY_LOANS_AMT_RATIO': ('负资产住宅按揭贷款额占比', '%', 'quarterly', 'reserves_finance', 'HK_HKMA_NEGATIVE_EQUITY'),
    'HK_HKMA_NEGATIVE_EQUITY_UNSECURED_AMT': ('负资产住宅按揭无抵押部分金额', 'HK$ million', 'quarterly', 'reserves_finance', 'HK_HKMA_NEGATIVE_EQUITY'),
    'HK_HKMA_NEGATIVE_EQUITY_LTV': ('负资产住宅按揭贷款价值比', '%', 'quarterly', 'reserves_finance', 'HK_HKMA_NEGATIVE_EQUITY'),

    'HK_HKMA_DEPOSITS_LB_DEMAND_HKD': ('认可机构活期存款（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_DEMAND_FC': ('认可机构活期存款（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_DEMAND_TOTAL': ('认可机构活期存款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_SAVINGS_HKD': ('认可机构储蓄存款（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_SAVINGS_FC': ('认可机构储蓄存款（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_SAVINGS_TOTAL': ('认可机构储蓄存款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_TIME_HKD': ('认可机构定期存款（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_TIME_FC': ('认可机构定期存款（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_TIME_TOTAL': ('认可机构定期存款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_TOTAL_HKD': ('认可机构客户存款（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_TOTAL_FC': ('认可机构客户存款（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_LB_TOTAL': ('认可机构客户存款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_ALL_AIS_HKD': ('所有认可机构客户存款（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_ALL_AIS_FC': ('所有认可机构客户存款（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),
    'HK_HKMA_DEPOSITS_ALL_AIS_TOTAL': ('所有认可机构客户存款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_CUSTOMER_DEPOSITS'),

    'HK_HKMA_RMB_DEPOSITS_DEMAND_SAVINGS': ('香港人民币活期及储蓄存款', 'RMB million yuan', 'monthly', 'reserves_finance', 'HK_HKMA_RMB_DEPOSITS'),
    'HK_HKMA_RMB_DEPOSITS_TIME': ('香港人民币定期存款', 'RMB million yuan', 'monthly', 'reserves_finance', 'HK_HKMA_RMB_DEPOSITS'),
    'HK_HKMA_RMB_DEPOSITS_TOTAL': ('香港人民币存款合计', 'RMB million yuan', 'monthly', 'reserves_finance', 'HK_HKMA_RMB_DEPOSITS'),
    'HK_HKMA_RMB_DEPOSITS_AIS_COUNT': ('经营人民币业务认可机构数', 'count', 'monthly', 'reserves_finance', 'HK_HKMA_RMB_DEPOSITS'),

    'HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_HKD': ('香港银行贸易融资（港元）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_FC': ('香港银行贸易融资（外币）', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_TOTAL': ('香港银行贸易融资合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_MERCH_TRADE_NON_HK_TOTAL': ('非香港商品贸易融资合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_IN_HK_TOTAL': ('按用途分类的在港使用贷款', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_OUTSIDE_HK_TOTAL': ('按用途分类的港外使用贷款', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_UNKNOWN_USE_TOTAL': ('用途不详贷款合计', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),
    'HK_HKMA_LOANS_TOTAL_BY_TYPE': ('按用途分类贷款总额', 'HK$ million', 'monthly', 'reserves_finance', 'HK_HKMA_LOANS_BY_TYPE'),

    'HK_TRADE_IMPORTS': ('香港商品进口', "$'000", 'monthly', 're_export', 'HK_TRADE_IDDS'),
    'HK_TRADE_DOMESTIC_EXPORTS': ('香港本地产品出口', "$'000", 'monthly', 're_export', 'HK_TRADE_IDDS'),
    'HK_TRADE_RE_EXPORTS': ('香港转口', "$'000", 'monthly', 're_export', 'HK_TRADE_IDDS'),
    'HK_TRADE_TOTAL_EXPORTS': ('香港出口总额', "$'000", 'monthly', 're_export', 'HK_TRADE_IDDS'),
    'HK_TRADE_TOTAL_TRADE': ('香港商品贸易总额', "$'000", 'monthly', 're_export', 'HK_TRADE_IDDS'),
    'HK_TRADE_BALANCE': ('香港商品贸易差额', "$'000", 'monthly', 're_export', 'HK_TRADE_IDDS'),
    'HK_TRADE_RE_EXPORT_SHARE': ('香港转口占整体出口比重', '%', 'monthly', 're_export', 'HK_TRADE_IDDS'),

    'HK_CSD_COMPOSITE_CPI_INDEX': ('香港综合消费物价指数（CSD年度）', 'index', 'annual', 'economy', 'HK_CSD_CTT_6'),
    'HK_CSD_GDP_REAL_ANNUAL': ('香港实质本地生产总值（CSD年度）', 'HK$ million', 'annual', 'economy', 'HK_CSD_CTT_6'),
    'HK_CSD_UNEMPLOYMENT_RATE_ANNUAL': ('香港失业率（CSD年度）', '%', 'annual', 'economy', 'HK_CSD_CTT_6'),
    'HK_CSD_TOTAL_EXPORTS_YOY_ANNUAL': ('香港出口总额同比（CSD年度）', '%', 'annual', 're_export', 'HK_CSD_CTT_6'),
    'HK_CSD_COMPOSITE_CPI_YOY_ANNUAL': ('香港综合消费物价同比（CSD年度）', '%', 'annual', 'economy', 'HK_CSD_CTT_8'),
    'HK_CSD_GDP_REAL_YOY_ANNUAL': ('香港实质本地生产总值同比（CSD年度）', '%', 'annual', 'economy', 'HK_CSD_CTT_8'),
}

# These series are intentionally kept in the catalog so a failed or
# unavailable official field remains visible in diagnostics, but they are not
# eligible for charts, default API output, or lead-lag calculations.  A zero
# row is not evidence that the official source published a zero.
CSD_CURATED_MAPPINGS = {
    'HK_CSD_WEB_GDP_CURRENT_QUARTERLY': {
        'table_id': '310-31002',
        'series_code': 'freq=Q|sv=CUR|stat=HK_million',
        'name': 'CSD 按当时市价计算的 GDP（季度）', 'unit': 'HK$ million',
        'frequency': 'quarterly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选映射；保留官方季度频率和原始系列码。',
        'price_basis': 'current_market_prices', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_GDP_REAL_QUARTERLY': {
        'table_id': '310-31003',
        'series_code': 'freq=Q|sv=CON|stat=HK_million',
        'name': 'CSD 实质 GDP（季度，链式 2024 年价格）', 'unit': 'HK$ million',
        'frequency': 'quarterly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选映射；保留官方链式价格基础和季度频率。',
        'price_basis': 'chained_2024_dollars', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_GDP_REAL_YOY_QUARTERLY': {
        'table_id': '310-31003',
        'series_code': 'freq=Q|sv=CON|stat=Year-on-year_change',
        'name': 'CSD 实质 GDP 同比（季度）', 'unit': '%',
        'frequency': 'quarterly', 'category': 'economy', 'statistic': 'yoy',
        'note': 'CSD Web Table 官方同比字段；不对官方同比再次变换。',
        'price_basis': 'chained_2024_dollars', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_PRIVATE_CONSUMPTION_QUARTERLY': {
        'table_id': '310-31003',
        'series_code': 'GDP_COMPONENT=PCE|freq=Q|sv=CON|stat=HK_million',
        'name': 'CSD 私人消费开支（季度，实质）', 'unit': 'HK$ million',
        'frequency': 'quarterly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选映射；GDP_COMPONENT=PCE。',
        'price_basis': 'chained_2024_dollars', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_FIXED_CAPITAL_FORMATION_QUARTERLY': {
        'table_id': '310-31003',
        'series_code': 'GDP_COMPONENT=GDFCF|freq=Q|sv=CON|stat=HK_million',
        'name': 'CSD 固定资本形成总额（季度，实质）', 'unit': 'HK$ million',
        'frequency': 'quarterly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选映射；GDP_COMPONENT=GDFCF。',
        'price_basis': 'chained_2024_dollars', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_BOP_CURRENT_ACCOUNT_QUARTERLY': {
        'table_id': '315-37001',
        'series_code': 'BOP_COMPONENT=CRA|freq=Q|sv=BOP|stat=HK_million',
        'name': 'CSD 国际收支经常账户（季度）', 'unit': 'HK$ million',
        'frequency': 'quarterly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选映射；BOP_COMPONENT=CRA。',
        'price_basis': None, 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_RETAIL_TOTAL_VALUE': {
        'table_id': '620-67001',
        'series_code': 'freq=M|sv=VAL_RS|stat=HK_million',
        'name': 'CSD 零售销售总额', 'unit': 'HK$ million',
        'frequency': 'monthly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选映射；不与 RVD 物业交易金额混合。',
        'price_basis': 'current_prices', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_RETAIL_VALUE_INDEX_YOY': {
        'table_id': '620-67001',
        'series_code': 'freq=M|sv=VAL_IDX_RS|stat=Year-on-year_change',
        'name': 'CSD 零售销售价值指数同比', 'unit': '%',
        'frequency': 'monthly', 'category': 'economy', 'statistic': 'yoy',
        'note': 'CSD Web Table 官方同比字段；不对官方同比再次变换。',
        'price_basis': 'current_prices', 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_VISITOR_ARRIVALS_MAINLAND': {
        'table_id': '650-80001',
        'series_code': 'REGION=CN|freq=M|sv=VIS_ARR|stat=Number',
        'name': 'CSD 中国内地访港旅客人次', 'unit': 'count',
        'frequency': 'monthly', 'category': 'economy', 'statistic': 'level',
        'note': 'CSD Web Table 精选维度映射；REGION=CN 是统计维度，不是来源替换。',
        'price_basis': None, 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v1',
    },
    'HK_CSD_WEB_POPULATION_GROWTH_SEMIANNUAL': {
        'table_id': '110-01003',
        'series_code': 'freq=H|sv=PG|stat=000',
        'name': 'CSD 香港人口增长（半年参考点同比变动）', 'unit': "('000)",
        'frequency': 'semiannual', 'category': 'economy', 'statistic': 'level',
        'note': ('CSD Table 110-01003 Population growth by component；PG 是相对上年同一'
                 '参考时点的人口增长量（千人），不是人口存量；半年期保留为 H1/H2。'),
        'price_basis': None, 'seasonal_adjustment': None,
        'mapping_version': 'csd_curated_v2_population_growth',
    },
}

# Compatibility catalog entry only.  The former code incorrectly described
# PG as a population stock.  It returns no active observations and points
# callers to the semantically correct replacement instead of silently
# repurposing the old identifier.
DEPRECATED_CSD_CURATED_MAPPINGS = {
    'HK_CSD_WEB_POPULATION_SEMIANNUAL': {
        'name': '已弃用：原“香港人口（半年）”错误映射',
        'unit': "('000)", 'frequency': 'semiannual', 'category': 'economy',
        'source_id': 'HK_CSD_WEB_110-01003',
        'replacement_code': 'HK_CSD_WEB_POPULATION_GROWTH_SEMIANNUAL',
        'note': ('deprecated：旧代码曾把 110-01003 的 PG 人口增长量误标为人口存量；'
                 '不再返回活动序列。人口存量尚未接入。'),
    },
}

INDICATOR_STATUS_OVERRIDES = {
    'HK_RVD_PRIMARY_SALES_VALUE': ('unavailable_at_source', 'RVD current workbook does not publish a stable primary amount field'),
    'HK_RVD_SECONDARY_SALES_VALUE': ('unavailable_at_source', 'RVD current workbook does not publish a stable secondary amount field'),
    'HK_RVD_TOTAL_SALES_VALUE': ('unavailable_at_source', 'RVD amount total is unavailable when component amounts are not published'),
    'HK_HKMA_FC_RESERVE_ASSETS_LF': ('unsupported_field', 'HKMA endpoint does not expose a separate Land Fund reserve field in the current response'),
    'HK_HKMA_UNSETTLED_FX_CONTRACTS_LF': ('unsupported_field', 'HKMA endpoint does not expose a separate Land Fund unsettled-contract field in the current response'),
}

INDICATOR_TRANSFORMS = {
    'monthly': ('level', 'difference', 'mom', 'yoy', 'rolling_12m', 'index100'),
    'quarterly': ('level', 'qoq', 'yoy', 'rolling_12m', 'index100'),
    'annual': ('level', 'difference', 'yoy', 'index100'),
    'semiannual': ('level', 'difference', 'yoy', 'index100'),
}

# Transform permissions are series-semantic, not merely frequency-semantic.
# In particular, an official YoY field must not receive a second YoY, rates
# and shares should not be treated as stock/flow levels, and stock series do
# not receive a rolling flow operation.  The frequency map above remains a
# conservative fallback for small fixtures and unknown future catalog items.
_FLOW_CODE_HINTS = (
    'SALES_', 'TRADE_', 'EXPORT', 'IMPORT', 'RE_EXPORT', 'COMPLETION',
    'TAKE_UP', 'NEW_APPLICATION', 'NEW_APPROVED', 'NEW_DRAWN',
)
_STOCK_CODE_HINTS = (
    'RESERVE_ASSETS', 'DEPOSITS', 'LOANS_', 'STOCK', 'VACANCY_UNITS',
    'POPULATION', 'GDP', 'BALANCE', 'HIBOR',
)


def _is_official_change_series(code):
    text = str(code or '').upper()
    return ('_YOY' in text or text.endswith('YOY') or
            code in CSD_CURATED_MAPPINGS and
            CSD_CURATED_MAPPINGS[code].get('statistic') == 'yoy')


def _is_rate_or_share_series(code, unit=None):
    text = str(code or '').upper()
    unit_text = str(unit or '').lower()
    return (unit_text in {'%', '‰'} or any(token in text for token in
            ('RATE', 'RATIO', 'SHARE', 'PERCENT', 'HIBOR')))


def _allowed_transforms(code):
    """Return transforms valid for one catalog series."""
    if code in CSD_CURATED_MAPPINGS:
        meta = CSD_CURATED_MAPPINGS[code]
        frequency = meta.get('frequency')
        if _is_official_change_series(code) or _is_rate_or_share_series(code, meta.get('unit')):
            return ('level',)
        base = {
            'monthly': ('level', 'difference', 'mom', 'yoy', 'index100'),
            'quarterly': ('level', 'qoq', 'yoy', 'index100'),
            'semiannual': ('level', 'difference', 'yoy', 'index100'),
            'annual': ('level', 'yoy', 'index100'),
        }
        return base.get(frequency, ('level',))
    if code not in INDICATORS:
        return ('level',)
    name, unit, frequency, _category, _source_id = INDICATORS[code]
    if _is_official_change_series(code) or _is_rate_or_share_series(code, unit):
        return ('level', 'difference')
    if any(token in str(code).upper() for token in _STOCK_CODE_HINTS):
        base = {
            'monthly': ('level', 'difference', 'mom', 'yoy', 'index100'),
            'quarterly': ('level', 'qoq', 'yoy', 'index100'),
            'semiannual': ('level', 'difference', 'yoy', 'index100'),
            'annual': ('level', 'yoy', 'index100'),
        }
        return base.get(frequency, ('level',))
    base = {
        'monthly': ('level', 'difference', 'mom', 'yoy', 'index100'),
        'quarterly': ('level', 'qoq', 'yoy', 'index100'),
        'annual': ('level', 'difference', 'yoy', 'index100'),
        'semiannual': ('level', 'difference', 'yoy', 'index100'),
    }.get(frequency, ('level',))
    if any(token in str(code).upper() for token in _FLOW_CODE_HINTS):
        position = {'monthly': 5, 'quarterly': 4}.get(frequency)
        if position is not None:
            base = base[:position] + ('rolling_12m',) + base[position:]
    return base

FIRST_TIER_CITIES = ('北京', '上海', '广州', '深圳')
MAINLAND_HOUSING_CODES = {
    'CN_FIRST_TIER_NEW_HOME_INDEX': ('new_home_mom_idx', '一线城市新建商品住宅价格指数（等权链式）'),
    'CN_FIRST_TIER_SECOND_HOME_INDEX': ('second_home_mom_idx', '一线城市二手住宅价格指数（等权链式）'),
}
MAINLAND_NATIONAL_TRANSACTION_CODES = {
    'CN_NATIONAL_SALES_AREA_YTD_YOY': (
        'sales_area_ytd_yoy_official', '中国全国新建商品房销售面积累计同比（国家统计局）',
        '%', 'housing_national_observations'),
    'CN_NATIONAL_SALES_VALUE_YTD_YOY': (
        'sales_value_ytd_yoy_official', '中国全国新建商品房销售额累计同比（国家统计局）',
        '%', 'housing_national_observations'),
}
MAINLAND_DERIVED_MONTHLY_CODES = {
    'CN_NATIONAL_SALES_AREA_MONTHLY_DERIVED': (
        'sales_area_monthly_derived', '中国全国新建商品房销售面积月度流量（由官方累计值差分）',
        '万平方米', 'housing_national_observations'),
    'CN_NATIONAL_SALES_VALUE_MONTHLY_DERIVED': (
        'sales_value_monthly_derived', '中国全国新建商品房销售额月度流量（由官方累计值差分）',
        '亿元', 'housing_national_observations'),
}
MAINLAND_PRETRANSFORMED_CODES = {
    'CN_CPI_YOY', 'CN_PPI_YOY', 'CN_GACC_EXPORT_CNY_MONTH_YOY',
    'CN_NATIONAL_SALES_AREA_YTD_YOY', 'CN_NATIONAL_SALES_VALUE_YTD_YOY',
}

MAINLAND_LEAD_LAG_HINTS = (
    'CN_CPI_YOY', 'CN_PPI_YOY', 'CN_GACC_EXPORT_CNY_MONTH_YOY',
    'CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD',
    'CN_FIRST_TIER_NEW_HOME_INDEX', 'CN_FIRST_TIER_SECOND_HOME_INDEX',
    'CN_NATIONAL_SALES_AREA_YTD_YOY', 'CN_NATIONAL_SALES_VALUE_YTD_YOY',
    'CN_NATIONAL_SALES_AREA_MONTHLY_DERIVED',
    'CN_NATIONAL_SALES_VALUE_MONTHLY_DERIVED',
)

SOURCE_CATALOG = {
    'HK_RVD_AVG_RENT': ('差饷物业估价署', 'Private Domestic - Average Rents by Class', 'official_xls', RVD_INDEX_PAGE, 'monthly'),
    'HK_RVD_AVG_PRICE': ('差饷物业估价署', 'Private Domestic - Average Prices by Class', 'official_xls', RVD_INDEX_PAGE, 'monthly'),
    'HK_RVD_RENT_INDEX': ('差饷物业估价署', 'Private Domestic - Rental Indices by Class', 'official_xls', RVD_INDEX_PAGE, 'monthly'),
    'HK_RVD_PRICE_INDEX': ('差饷物业估价署', 'Private Domestic - Price Indices by Class', 'official_xls', RVD_INDEX_PAGE, 'monthly'),
    'HK_RVD_DOMESTIC_SALES': ('差饷物业估价署', 'Domestic Sales', 'official_xls', RVD_INDEX_PAGE, 'monthly'),
    'HK_RVD_PRIVATE_STOCK_FLOW': ('差饷物业估价署', 'Private Domestic - Completions, Stock, Vacancy and Take-up', 'official_xls', RVD_INDEX_PAGE, 'annual'),
    'HK_LANDREG_PRIMARY': ('土地注册处', 'Monthly Statistics on Agreements for Sale and Purchase', 'official_json', 'https://www.landreg.gov.hk/en/monthly/monthly.htm', 'monthly'),
    'HK_HKMA_FC_RESERVE_ASSETS': ('香港金融管理局', 'Foreign currency reserve assets', 'official_api', HKMA_URLS['HK_HKMA_FC_RESERVE_ASSETS'], 'monthly'),
    'HK_HKMA_ECONOMIC': ('香港金融管理局', 'Economic statistics', 'official_api', HKMA_URLS['HK_HKMA_ECONOMIC'], 'monthly'),
    'HK_HKMA_MONETARY': ('香港金融管理局', 'Monetary statistics', 'official_api', HKMA_URLS['HK_HKMA_MONETARY'], 'monthly'),
    'HK_HKMA_BANKING_STATS': ('香港金融管理局', 'Banking statistics', 'official_api', HKMA_URLS['HK_HKMA_BANKING_STATS'], 'monthly'),
    'HK_HKMA_CUSTOMER_DEPOSITS': ('香港金融管理局', 'Customer deposits by type (HKD/foreign currencies)', 'official_api', HKMA_URLS['HK_HKMA_CUSTOMER_DEPOSITS'], 'monthly'),
    'HK_HKMA_RMB_DEPOSITS': ('香港金融管理局', 'Customer deposits by type (RMB)', 'official_api', HKMA_URLS['HK_HKMA_RMB_DEPOSITS'], 'monthly'),
    'HK_HKMA_LOANS_BY_TYPE': ('香港金融管理局', 'Loans by type of licensed banks', 'official_api', HKMA_URLS['HK_HKMA_LOANS_BY_TYPE'], 'monthly'),
    'HK_HKMA_MORTGAGE_SURVEY': ('香港金融管理局', 'Residential mortgage survey results', 'official_api', HKMA_URLS['HK_HKMA_MORTGAGE_SURVEY'], 'monthly'),
    'HK_HKMA_NEGATIVE_EQUITY': ('香港金融管理局', 'Residential mortgage loans in negative equity', 'official_api', HKMA_URLS['HK_HKMA_NEGATIVE_EQUITY'], 'quarterly'),
    'HK_TRADE_IDDS': ('香港政府统计处', 'Trade-IDDS merchandise trade data', 'official_api', TRADE_API_SPEC, 'monthly'),
    **{item['source_id']: ('香港政府统计处', item['title'], 'official_api', item['entry_url'], 'monthly')
       for item in TRADE_DIMENSION_REQUESTS.values()},
    'HK_CSD_CTT_6': ('香港政府统计处', 'CSD IDDS common table 6', 'official_api', 'https://idds.censtatd.gov.hk/', 'annual'),
    'HK_CSD_CTT_8': ('香港政府统计处', 'CSD IDDS common table 8', 'official_api', 'https://idds.censtatd.gov.hk/', 'annual'),
    **{f'HK_CSD_WEB_{table_id}': ('香港政府统计处', table['title'], 'official_web_table',
                                  f'https://www.censtatd.gov.hk/en/web_table.html?id={table_id}',
                                  table['frequency'])
       for table_id, table in CSD_WEB_TABLES.items()},
}


def _new_session():
    session = requests.Session()
    retry = Retry(total=3, connect=3, read=2, status=2, backoff_factor=0.4,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(('GET',)))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    text = str(value).strip().replace(',', '').replace('，', '')
    if text in ('', '-', '—', '–', '…', '...', 'NA', 'N/A', 'null'):
        return None
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


def _period(value, annual=False):
    text = str(value or '').strip()
    match = re.search(r'(20\d{2})[-/.年]?(?:(\d{1,2})月?)?', text)
    if not match:
        return None
    year, month = int(match.group(1)), match.group(2)
    if annual or not month:
        return f'{year:04d}-12' if annual else f'{year:04d}'
    month = int(month)
    return f'{year:04d}-{month:02d}' if 1 <= month <= 12 else None


def _month_period(year, month):
    try:
        year, month = int(year), int(month)
    except (TypeError, ValueError):
        return None
    return f'{year:04d}-{month:02d}' if 1 <= month <= 12 and 1900 <= year <= 2100 else None


def _text(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _norm(value):
    return re.sub(r'[^a-z0-9]+', '', str(value or '').lower())


def _currency_for_unit(unit):
    text = str(unit or '')
    if 'HK$' in text or 'HKD' in text or text == '$ million':
        return 'HKD'
    if 'US$' in text or 'USD' in text:
        return 'USD'
    if 'RMB' in text or 'CNY' in text:
        return 'CNY'
    return None


def _meta(code):
    if code in DEPRECATED_CSD_CURATED_MAPPINGS:
        mapping = DEPRECATED_CSD_CURATED_MAPPINGS[code]
        source_url = SOURCE_CATALOG.get(mapping['source_id'], ('', '', '', '', ''))[3]
        return {
            'code': code, 'name': mapping['name'], 'unit': mapping['unit'],
            'frequency': mapping['frequency'], 'category': mapping['category'],
            'source_id': mapping['source_id'], 'source_url': source_url,
            'currency': None, 'price_basis': None, 'seasonal_adjustment': None,
            'status': 'deprecated', 'status_note': mapping['note'],
            'eligible_for_api': False, 'eligible_for_lead_lag': False,
            'allowed_transforms': ['level'],
            'deprecated': True,
            'deprecated_alias_for': mapping['replacement_code'],
        }
    if code in CSD_CURATED_MAPPINGS:
        mapping = CSD_CURATED_MAPPINGS[code]
        source_id = f"HK_CSD_WEB_{mapping['table_id']}"
        source_url = SOURCE_CATALOG.get(source_id, ('', '', '', '', ''))[3]
        return {'code': code, 'name': mapping['name'], 'unit': mapping['unit'],
                'frequency': mapping['frequency'], 'category': mapping['category'],
                'source_id': source_id, 'source_url': source_url,
                'currency': _currency_for_unit(mapping['unit']),
                'price_basis': mapping.get('price_basis'),
                'seasonal_adjustment': mapping.get('seasonal_adjustment'),
                'mapping_version': mapping.get('mapping_version', 'csd_curated_v1'),
                'status': 'available', 'status_note': mapping['note'],
                'eligible_for_api': True, 'eligible_for_lead_lag': False,
                'allowed_transforms': list(_allowed_transforms(code)),
                'curated_mapping': dict(mapping)}
    name, unit, frequency, category, source_id = INDICATORS[code]
    status, status_note = INDICATOR_STATUS_OVERRIDES.get(code, ('available', ''))
    source_url = SOURCE_CATALOG.get(source_id, ('', '', '', '', ''))[3]
    return {'code': code, 'name': name, 'unit': unit, 'frequency': frequency,
            'category': category, 'source_id': source_id,
            'source_url': source_url,
            'currency': _currency_for_unit(unit),
            'price_basis': None, 'seasonal_adjustment': None,
            'status': status, 'status_note': status_note,
            'eligible_for_api': status == 'available',
            'eligible_for_lead_lag': status == 'available' and frequency == 'monthly',
            'allowed_transforms': list(_allowed_transforms(code))}


def _period_sort_key(period, frequency=None):
    """Return a comparable calendar key without coercing frequencies."""
    text = str(period or '').strip().upper()
    match = re.fullmatch(r'((?:19|20)\d{2})-(\d{2})', text)
    if match:
        return int(match.group(1)) * 12 + int(match.group(2)) - 1
    match = re.fullmatch(r'((?:19|20)\d{2})-Q([1-4])', text)
    if match:
        return int(match.group(1)) * 12 + (int(match.group(2)) - 1) * 3
    match = re.fullmatch(r'((?:19|20)\d{2})-H([1-2])', text)
    if match:
        return int(match.group(1)) * 12 + (int(match.group(2)) - 1) * 6
    match = re.fullmatch(r'((?:19|20)\d{2})(?:-12)?', text)
    if match:
        return int(match.group(1)) * 12
    return -1


def _period_step_months(frequency):
    """Return the calendar distance between adjacent observations."""
    return {'monthly': 1, 'quarterly': 3, 'semiannual': 6, 'annual': 12}.get(
        str(frequency or '').lower(), 1)


def _period_bounds(period, frequency=None):
    """Expose explicit calendar bounds while preserving the source frequency."""
    text = str(period or '').strip().upper()
    match = re.fullmatch(r'((?:19|20)\d{2})-(\d{2})', text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        return {'period_start': f'{year:04d}-{month:02d}',
                'period_end': f'{year:04d}-{month:02d}'}
    match = re.fullmatch(r'((?:19|20)\d{2})-Q([1-4])', text)
    if match:
        year, quarter = int(match.group(1)), int(match.group(2))
        start = (quarter - 1) * 3 + 1
        return {'period_start': f'{year:04d}-{start:02d}',
                'period_end': f'{year:04d}-{start + 2:02d}'}
    match = re.fullmatch(r'((?:19|20)\d{2})-H([1-2])', text)
    if match:
        year, half = int(match.group(1)), int(match.group(2))
        start = 1 if half == 1 else 7
        return {'period_start': f'{year:04d}-{start:02d}',
                'period_end': f'{year:04d}-{start + 5:02d}'}
    match = re.fullmatch(r'((?:19|20)\d{2})(?:-12)?', text)
    if match:
        year = int(match.group(1))
        return {'period_start': f'{year:04d}-01',
                'period_end': f'{year:04d}-12'}
    return {'period_start': None, 'period_end': None}


def _current_code_revision():
    """Return a reproducible code identifier without requiring a clean tree."""
    try:
        commit = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
            check=True, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(
            ['git', 'diff', '--quiet'], cwd=str(ROOT), check=False).returncode != 0
        return f'git:{commit}{"-dirty" if dirty else ""}'
    except (OSError, subprocess.SubprocessError):
        return 'worktree'


def parse_period_bound(value):
    """Validate an API period bound while preserving M/Q/H/Y semantics."""
    text = str(value or '').strip().upper()
    if not text:
        return None
    if re.fullmatch(r'(?:19|20)\d{2}(?:-\d{2}|-Q[1-4]|-H[1-2])?', text):
        if re.search(r'-\d{2}$', text) and not 1 <= int(text[-2:]) <= 12:
            raise ValueError(f'非法 period: {value}')
        return text
    raise ValueError(f'非法 period: {value}')


def _row(code, period, value, source_id, source_url=None, source_table=None,
         data_status='official', note='', release_date=None, raw_sha256=None,
         transformation=None, dimension_key='', dimension_value='', dimension_json=None,
         source_period_end=None, missing_reason=None):
    if code not in INDICATORS or not period or value is None:
        return None
    value = _number(value)
    if value is None:
        return None
    meta = _meta(code)
    return {
        'indicator_code': code, 'jurisdiction': 'HK', 'category': meta['category'],
        'subcategory': meta['source_id'], 'period': period,
        'period_label': period, 'frequency': meta['frequency'], 'value': value,
        'unit': meta['unit'], 'currency': meta.get('currency'),
        'seasonal_adjustment': None, 'price_basis': None,
        'transformation': transformation, 'dimension_key': dimension_key,
        'dimension_value': dimension_value, 'dimension_json': dimension_json,
        'data_status': data_status, 'source_id': source_id,
        'source_url': source_url or SOURCE_CATALOG.get(source_id, ('', '', '', '', ''))[3],
        'source_table': source_table, 'release_date': release_date,
        'vintage_date': '', 'raw_sha256': raw_sha256, 'parser_version': 'hk_macro_v1',
        'source_period_end': source_period_end,
        'missing_reason': missing_reason, 'note': note, 'formula': None,
    }


def _connect_readonly(db_path):
    """Open an existing SQLite database without allowing GET-side writes."""
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f'hong_kong_macro database not found: {path}')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _require_hong_kong_macro_schema(conn):
    required = {
        'hong_kong_macro_observations', 'hong_kong_macro_sources',
        'hong_kong_macro_trade_dimensions',
        'hong_kong_macro_web_table_observations',
        'hong_kong_macro_lead_lag_results',
        'hong_kong_macro_lead_lag_snapshots',
    }
    existing = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(required - existing)
    if missing:
        raise RuntimeError('hong_kong_macro_not_initialized: missing tables=' +
                           ','.join(missing))


def ensure_hong_kong_macro_tables(conn, refresh_metadata=False):
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        indicator_code TEXT NOT NULL, jurisdiction TEXT NOT NULL DEFAULT 'HK',
        category TEXT NOT NULL, subcategory TEXT, period TEXT NOT NULL,
        period_label TEXT, frequency TEXT NOT NULL, value REAL, unit TEXT NOT NULL,
        currency TEXT, seasonal_adjustment TEXT, price_basis TEXT,
        transformation TEXT, dimension_key TEXT NOT NULL DEFAULT '',
        dimension_value TEXT NOT NULL DEFAULT '', dimension_json TEXT,
        data_status TEXT NOT NULL, source_id TEXT, source_url TEXT,
        source_table TEXT, release_date TEXT, vintage_date TEXT NOT NULL DEFAULT '',
        retrieved_at TEXT NOT NULL, raw_sha256 TEXT, parser_version TEXT,
        source_period_end TEXT, missing_reason TEXT, note TEXT, formula TEXT,
        UNIQUE(indicator_code, period, dimension_key, dimension_value, vintage_date)
    )''')
    observation_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(hong_kong_macro_observations)')}
    for name, definition in (
            ('missing_reason', 'TEXT'),
            ('source_period_end', 'TEXT')):
        if name not in observation_columns:
            conn.execute(f'ALTER TABLE hong_kong_macro_observations ADD COLUMN {name} {definition}')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_hk_macro_code_period
                    ON hong_kong_macro_observations(indicator_code, period)''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_hk_macro_category_period
                    ON hong_kong_macro_observations(category, period)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_sources (
        source_id TEXT PRIMARY KEY, institution TEXT, dataset_name TEXT,
        source_type TEXT, entry_url TEXT, download_url TEXT, request_params TEXT,
        file_format TEXT, frequency TEXT, history_start TEXT, unit TEXT,
        seasonal_adjustment TEXT, latest_reference_period TEXT,
        latest_release_date TEXT, last_success_at TEXT, last_attempt_at TEXT,
        raw_sha256 TEXT, parser_version TEXT, terms_note TEXT, status TEXT,
        error_type TEXT, error_message TEXT, raw_path TEXT, record_count INTEGER,
        updated_at TEXT, expected_frequency TEXT,
        expected_release_lag_days INTEGER, latest_reference_period_end TEXT,
        freshness_status TEXT, freshness_reason TEXT,
        release_date_not_provided INTEGER NOT NULL DEFAULT 0,
        frequency_summary_json TEXT, page_last_updated_date TEXT,
        release_metadata_status TEXT, release_metadata_reason TEXT,
        expected_release_lag_status TEXT, expected_release_lag_reason TEXT
    )''')
    source_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(hong_kong_macro_sources)')}
    for name, definition in (
            ('expected_frequency', 'TEXT'),
            ('expected_release_lag_days', 'INTEGER'),
            ('latest_reference_period_end', 'TEXT'),
            ('freshness_status', 'TEXT'),
            ('freshness_reason', 'TEXT'),
            ('release_date_not_provided', 'INTEGER NOT NULL DEFAULT 0'),
            ('frequency_summary_json', 'TEXT'),
            ('page_last_updated_date', 'TEXT'),
            ('release_metadata_status', 'TEXT'),
            ('release_metadata_reason', 'TEXT'),
            ('expected_release_lag_status', 'TEXT'),
            ('expected_release_lag_reason', 'TEXT')):
        if name not in source_columns:
            conn.execute(f'ALTER TABLE hong_kong_macro_sources ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_update_runs (
        run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT,
        full_history INTEGER, source_status_json TEXT, records_parsed INTEGER,
        records_written INTEGER, error_count INTEGER, error_message TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_lead_lag_results (
        result_id TEXT PRIMARY KEY, pair_code TEXT, hk_indicator_code TEXT,
        mainland_indicator_code TEXT, transform TEXT, lag_months INTEGER,
        corr REAL, n_obs INTEGER, window_start TEXT, window_end TEXT,
        window_type TEXT, computed_at TEXT, status TEXT, note TEXT,
        snapshot_id TEXT
    )''')
    lead_lag_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(hong_kong_macro_lead_lag_results)')}
    if 'snapshot_id' not in lead_lag_columns:
        conn.execute('ALTER TABLE hong_kong_macro_lead_lag_results ADD COLUMN snapshot_id TEXT')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_hk_lead_lag_snapshot
                    ON hong_kong_macro_lead_lag_results(snapshot_id, pair_code, computed_at)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_lead_lag_snapshots (
        snapshot_id TEXT PRIMARY KEY, pair_code TEXT, hk_indicator_code TEXT,
        mainland_indicator_code TEXT, transform TEXT, hk_transform TEXT,
        mainland_transform TEXT, min_overlap INTEGER, lag_min INTEGER,
        lag_max INTEGER, input_start TEXT, input_end TEXT, hk_n_obs INTEGER,
        mainland_n_obs INTEGER, input_hash TEXT, source_vintages_json TEXT,
        parameters_json TEXT, computation_version TEXT, code_revision TEXT,
        computed_at TEXT NOT NULL, status TEXT NOT NULL, note TEXT,
        hk_input_hash TEXT, mainland_input_hash TEXT,
        hk_start TEXT, hk_end TEXT, mainland_start TEXT, mainland_end TEXT,
        rolling_windows_json TEXT, parser_versions_json TEXT
    )''')
    snapshot_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(hong_kong_macro_lead_lag_snapshots)')}
    for name, definition in (
            ('hk_input_hash', 'TEXT'),
            ('mainland_input_hash', 'TEXT'),
            ('hk_start', 'TEXT'),
            ('hk_end', 'TEXT'),
            ('mainland_start', 'TEXT'),
            ('mainland_end', 'TEXT'),
            ('rolling_windows_json', 'TEXT'),
            ('parser_versions_json', 'TEXT')):
        if name not in snapshot_columns:
            conn.execute(f'ALTER TABLE hong_kong_macro_lead_lag_snapshots ADD COLUMN {name} {definition}')
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_trade_dimensions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL, dimension_type TEXT NOT NULL,
        trade_type TEXT, period TEXT NOT NULL, dimension_code TEXT NOT NULL,
        dimension_label TEXT, statistic TEXT NOT NULL, value REAL,
        unit TEXT, data_status TEXT NOT NULL DEFAULT 'official',
        source_url TEXT, source_table TEXT, raw_sha256 TEXT,
        dimension_json TEXT, note TEXT, retrieved_at TEXT NOT NULL,
        UNIQUE(source_id,dimension_type,trade_type,period,dimension_code,statistic)
    )''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_hk_trade_dimensions_period
                    ON hong_kong_macro_trade_dimensions(dimension_type,period)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS hong_kong_macro_web_table_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL, table_id TEXT NOT NULL, period TEXT NOT NULL,
        series_code TEXT NOT NULL, series_label TEXT, value REAL, unit TEXT,
        frequency TEXT, data_status TEXT NOT NULL DEFAULT 'official',
        source_url TEXT, source_table TEXT, raw_sha256 TEXT,
        dimension_json TEXT, retrieved_at TEXT NOT NULL,
        UNIQUE(table_id,period,series_code)
    )''')
    web_columns = {row[1] for row in conn.execute(
        'PRAGMA table_info(hong_kong_macro_web_table_observations)')}
    for name, definition in (
            ('period_raw', 'TEXT'),
            ('statistic', 'TEXT'),
            ('construct_label', 'TEXT'),
            ('parser_version', 'TEXT'),
            ('missing_reason', 'TEXT')):
        if name not in web_columns:
            conn.execute(f'ALTER TABLE hong_kong_macro_web_table_observations ADD COLUMN {name} {definition}')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_hk_web_tables_period
                    ON hong_kong_macro_web_table_observations(table_id,period)''')
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_hk_web_tables_series
                    ON hong_kong_macro_web_table_observations(table_id,series_code,frequency)''')
    # The first implementation stored annual periods as ``YYYY-12``. Keep
    # those rows for audit, but move unambiguous active rows to canonical Y
    # periods required by the API. A conflicting target is never deleted; the
    # legacy row is explicitly superseded instead.
    user_version = int(conn.execute('PRAGMA user_version').fetchone()[0] or 0)
    initial_user_version = user_version
    if user_version < HK_MACRO_SCHEMA_VERSION:
        annual_rows = conn.execute('''SELECT id,indicator_code,period,
                dimension_key,dimension_value,vintage_date
            FROM hong_kong_macro_observations
            WHERE frequency='annual' AND period GLOB '[0-9][0-9][0-9][0-9]-12' ''').fetchall()
        for row in annual_rows:
            target = row['period'][:4]
            conflict = conn.execute('''SELECT id FROM hong_kong_macro_observations
                WHERE indicator_code=? AND period=? AND dimension_key=?
                  AND dimension_value=? AND vintage_date=? AND id<>? LIMIT 1''',
                                    (row['indicator_code'], target, row['dimension_key'],
                                     row['dimension_value'], row['vintage_date'], row['id'])).fetchone()
            if conflict:
                conn.execute('''UPDATE hong_kong_macro_observations
                    SET data_status='superseded',missing_reason='period_canonicalization_conflict',
                        note=TRIM(COALESCE(note,'') || ' [superseded: annual period canonicalization]')
                    WHERE id=?''', (row['id'],))
            else:
                conn.execute('''UPDATE hong_kong_macro_observations
                    SET period=?,period_label=? WHERE id=?''', (target, target, row['id']))
        web_annual_rows = conn.execute('''SELECT id,table_id,period,series_code
            FROM hong_kong_macro_web_table_observations
            WHERE period GLOB '[0-9][0-9][0-9][0-9]-12'
              AND COALESCE(frequency,'')='annual' ''').fetchall()
        for row in web_annual_rows:
            target = row['period'][:4]
            conflict = conn.execute('''SELECT id FROM hong_kong_macro_web_table_observations
                WHERE table_id=? AND period=? AND series_code=? AND id<>? LIMIT 1''',
                                    (row['table_id'], target, row['series_code'], row['id'])).fetchone()
            if conflict:
                conn.execute('''UPDATE hong_kong_macro_web_table_observations
                    SET data_status='superseded',missing_reason='period_canonicalization_conflict'
                    WHERE id=?''', (row['id'],))
            else:
                conn.execute('''UPDATE hong_kong_macro_web_table_observations
                    SET period=? WHERE id=?''', (target, row['id']))
        conn.execute(f'PRAGMA user_version={HK_MACRO_SCHEMA_VERSION}')
    # Metadata coverage is expensive on the ~1 GB production database. The
    # schema/migration path runs it once per database version; ordinary API
    # reads only need the already materialized source rows. Explicit debug or
    # update paths can request a refresh.
    if not refresh_metadata and initial_user_version >= HK_MACRO_SCHEMA_VERSION:
        conn.commit()
        return
    for source_id, (institution, dataset, source_type, entry, frequency) in SOURCE_CATALOG.items():
        conn.execute('''INSERT INTO hong_kong_macro_sources
            (source_id,institution,dataset_name,source_type,entry_url,frequency,
             parser_version,status,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO NOTHING''',
                     (source_id, institution, dataset, source_type, entry, frequency,
                      'hk_macro_v1', 'not_attempted', datetime.now().isoformat()))
        source_format = ('json' if 'api' in source_type or source_type == 'official_json'
                         else ('html/json' if source_type == 'official_web_table' else 'xls/xlsx/html'))
        params = ({'id': source_id.replace('HK_CSD_WEB_', ''), 'lang': 'en', 'full_series': 1}
                  if source_type == 'official_web_table' else {})
        conn.execute('''UPDATE hong_kong_macro_sources SET
            download_url=COALESCE(NULLIF(download_url,''),?),
            request_params=COALESCE(NULLIF(request_params,''),?),
            file_format=COALESCE(NULLIF(file_format,''),?),
            terms_note=COALESCE(NULLIF(terms_note,''),?),
            parser_version=COALESCE(NULLIF(parser_version,''),'hk_macro_v1'),
            expected_frequency=COALESCE(NULLIF(expected_frequency,''),?),
            release_date_not_provided=CASE WHEN latest_release_date IS NULL OR latest_release_date=''
                                           THEN 1 ELSE 0 END,
            release_metadata_status=CASE
                WHEN latest_release_date IS NULL OR latest_release_date='' THEN 'not_provided'
                ELSE 'provided' END,
            release_metadata_reason=CASE
                WHEN latest_release_date IS NULL OR latest_release_date=''
                THEN 'Official source does not expose a consistently verified observation release date.'
                ELSE 'Official release date retained from source metadata.' END,
            expected_release_lag_status=CASE
                WHEN expected_release_lag_days IS NULL THEN 'not_yet_verified'
                ELSE 'provided' END,
            expected_release_lag_reason=CASE
                WHEN expected_release_lag_days IS NULL
                THEN 'No official release calendar evidence verified; value remains NULL.'
                ELSE 'Verified official release-calendar lag.' END
            WHERE source_id=?''',
                     (entry, json.dumps(params, ensure_ascii=False, sort_keys=True),
                      source_format,
                      'Release date is not exposed consistently; retrieved_at is ingestion time. '
                      'Frequency and unit remain source-native; no cross-frequency interpolation.',
                      frequency,
                      source_id))
        # Keep source-level coverage auditable even when a source has no rows.
        main = conn.execute('''SELECT MIN(period),MAX(period),COUNT(*)
            FROM hong_kong_macro_observations WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ''',
                            (source_id,)).fetchone()
        trade = conn.execute('''SELECT MIN(period),MAX(period),COUNT(*)
            FROM hong_kong_macro_trade_dimensions WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ''',
                             (source_id,)).fetchone()
        web = conn.execute('''SELECT MIN(period),MAX(period),COUNT(*)
            FROM hong_kong_macro_web_table_observations WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ''', (source_id,)).fetchone()
        observed_units = [row[0] for row in conn.execute('''SELECT DISTINCT unit
            FROM hong_kong_macro_observations WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded'
              AND unit IS NOT NULL AND unit<>'' ''', (source_id,))]
        observed_frequencies = [row[0] for row in conn.execute('''SELECT DISTINCT frequency
            FROM hong_kong_macro_observations WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded'
              AND frequency IS NOT NULL AND frequency<>'' ''', (source_id,))]
        observed_units.extend(row[0] for row in conn.execute('''SELECT DISTINCT unit
            FROM hong_kong_macro_web_table_observations WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded'
              AND unit IS NOT NULL AND unit<>'' ''', (source_id,)))
        observed_units.extend(row[0] for row in conn.execute('''SELECT DISTINCT unit
            FROM hong_kong_macro_trade_dimensions WHERE source_id=? AND value IS NOT NULL
              AND unit IS NOT NULL AND unit<>'' ''', (source_id,)))
        observed_frequencies.extend(row[0] for row in conn.execute('''SELECT DISTINCT frequency
            FROM hong_kong_macro_web_table_observations WHERE source_id=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded'
              AND frequency IS NOT NULL AND frequency<>'' ''', (source_id,)))
        # Trade-IDDS dimensions are monthly by source contract, even though
        # the dimension table intentionally does not duplicate a frequency
        # column on every row.
        if conn.execute('''SELECT 1 FROM hong_kong_macro_trade_dimensions
                           WHERE source_id=? AND value IS NOT NULL LIMIT 1''', (source_id,)).fetchone():
            observed_frequencies.append('monthly')
        catalog_units = [meta[1] for meta in INDICATORS.values() if meta[4] == source_id]
        catalog_units.extend(meta['unit'] for meta in CSD_CURATED_MAPPINGS.values()
                             if f"HK_CSD_WEB_{meta['table_id']}" == source_id)
        unit_values = sorted(set(str(item) for item in observed_units + catalog_units if item))
        source_unit = unit_values[0] if len(unit_values) == 1 else ('mixed' if unit_values else 'unknown')
        frequency_values = sorted(set(str(item) for item in observed_frequencies if item))
        source_frequency = (frequency_values[0] if len(frequency_values) == 1 else
                            ('mixed' if frequency_values else frequency))
        coverage_rows = []
        for table_name, frequency_sql in (
                ('hong_kong_macro_observations', 'frequency'),
                ('hong_kong_macro_trade_dimensions', "'monthly'"),
                ('hong_kong_macro_web_table_observations', 'frequency')):
            coverage_rows.extend(conn.execute(
                f'''SELECT period,{frequency_sql} AS frequency FROM {table_name}
                    WHERE source_id=? AND value IS NOT NULL
                      AND COALESCE(data_status,'') <> 'superseded' ''', (source_id,)).fetchall())
        starts = [row['period'] for row in coverage_rows if row['period']]
        ends = [row['period'] for row in coverage_rows if row['period']]
        frequency_summary = {}
        for row in coverage_rows:
            freq = row['frequency'] or 'unknown'
            item = frequency_summary.setdefault(freq, {'n_obs': 0, 'start_period': None,
                                                        'end_period': None})
            item['n_obs'] += 1
            if item['start_period'] is None or _period_sort_key(row['period'], freq) < _period_sort_key(item['start_period'], freq):
                item['start_period'] = row['period']
            if item['end_period'] is None or _period_sort_key(row['period'], freq) > _period_sort_key(item['end_period'], freq):
                item['end_period'] = row['period']
        count = sum(int(row[2] or 0) for row in (main, trade, web))
        if starts or ends or count:
            conn.execute('''UPDATE hong_kong_macro_sources SET history_start=?,
                latest_reference_period=?,latest_reference_period_end=?,record_count=?,unit=?,frequency=?,
                frequency_summary_json=?,freshness_status=?,freshness_reason=?,
                seasonal_adjustment=COALESCE(NULLIF(seasonal_adjustment,''),'not_provided')
                WHERE source_id=?''',
                         (min(starts, key=lambda item: _period_sort_key(item)) if starts else None,
                          max(ends, key=lambda item: _period_sort_key(item)) if ends else None,
                          max(ends, key=lambda item: _period_sort_key(item)) if ends else None,
                          count, source_unit, source_frequency,
                          json.dumps(frequency_summary, ensure_ascii=False, sort_keys=True),
                          _source_freshness({'status': 'success',
                                             'latest_reference_period': max(ends, key=lambda item: _period_sort_key(item)) if ends else None,
                                             'frequency': source_frequency}) if ends else 'no_observation',
                          'Release date not provided by source; freshness is based on reference period.' if ends else 'No active observation',
                          source_id))
        else:
            conn.execute('''UPDATE hong_kong_macro_sources SET unit=?,frequency=?,
                frequency_summary_json=?,freshness_status='no_observation',
                freshness_reason='No active observation',
                seasonal_adjustment=COALESCE(NULLIF(seasonal_adjustment,''),'not_provided')
                WHERE source_id=?''', (source_unit, source_frequency,
                                       json.dumps(frequency_summary, ensure_ascii=False, sort_keys=True), source_id))
    # Backfill provenance from source-level snapshots for older observation
    # rows; do not invent release dates or replace existing hashes.
    conn.execute('''UPDATE hong_kong_macro_observations SET
        source_url=COALESCE(NULLIF(source_url,''),(SELECT entry_url FROM hong_kong_macro_sources s WHERE s.source_id=hong_kong_macro_observations.source_id)),
        raw_sha256=COALESCE(NULLIF(raw_sha256,''),(SELECT raw_sha256 FROM hong_kong_macro_sources s WHERE s.source_id=hong_kong_macro_observations.source_id)),
        parser_version=COALESCE(NULLIF(parser_version,''),(SELECT parser_version FROM hong_kong_macro_sources s WHERE s.source_id=hong_kong_macro_observations.source_id),'hk_macro_v1')
        WHERE value IS NOT NULL''')
    conn.execute(f'PRAGMA user_version={HK_MACRO_SCHEMA_VERSION}')
    conn.commit()


def upsert_hong_kong_observations(conn, rows):
    now = datetime.now().isoformat()
    count = 0
    for row in rows or []:
        if not row:
            continue
        cur = conn.execute('''INSERT INTO hong_kong_macro_observations (
            indicator_code,jurisdiction,category,subcategory,period,period_label,
            frequency,value,unit,currency,seasonal_adjustment,price_basis,
            transformation,dimension_key,dimension_value,dimension_json,data_status,
            source_id,source_url,source_table,release_date,vintage_date,retrieved_at,
            raw_sha256,parser_version,source_period_end,missing_reason,note,formula
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(indicator_code,period,dimension_key,dimension_value,vintage_date)
        DO UPDATE SET jurisdiction=excluded.jurisdiction,category=excluded.category,
          subcategory=excluded.subcategory,period_label=excluded.period_label,
          frequency=excluded.frequency,value=excluded.value,unit=excluded.unit,
          currency=excluded.currency,seasonal_adjustment=excluded.seasonal_adjustment,
          price_basis=excluded.price_basis,transformation=excluded.transformation,
          dimension_json=excluded.dimension_json,data_status=excluded.data_status,
          source_id=excluded.source_id,source_url=excluded.source_url,
          source_table=excluded.source_table,release_date=excluded.release_date,
          retrieved_at=excluded.retrieved_at,raw_sha256=excluded.raw_sha256,
          parser_version=excluded.parser_version,
          source_period_end=excluded.source_period_end,
          missing_reason=excluded.missing_reason,
          note=excluded.note,
          formula=excluded.formula''', (
            row['indicator_code'], row.get('jurisdiction', 'HK'), row['category'],
            row.get('subcategory'), row['period'], row.get('period_label'),
            row['frequency'], row['value'], row['unit'], row.get('currency'),
            row.get('seasonal_adjustment'), row.get('price_basis'),
            row.get('transformation'), row.get('dimension_key', ''),
            row.get('dimension_value', ''), row.get('dimension_json'),
            row.get('data_status', 'official'), row.get('source_id'),
            row.get('source_url'), row.get('source_table'), row.get('release_date'),
            row.get('vintage_date', ''), row.get('retrieved_at') or now,
            row.get('raw_sha256'), row.get('parser_version', 'hk_macro_v1'),
            row.get('source_period_end'), row.get('missing_reason'),
            row.get('note'), row.get('formula')))
        count += max(0, cur.rowcount)
    conn.commit()
    return count


def upsert_trade_dimensions(conn, rows):
    now = datetime.now().isoformat()
    count = 0
    for row in rows or []:
        if not row or not row.get('period') or not row.get('dimension_code'):
            continue
        cur = conn.execute('''INSERT INTO hong_kong_macro_trade_dimensions (
            source_id,dimension_type,trade_type,period,dimension_code,
            dimension_label,statistic,value,unit,data_status,source_url,
            source_table,raw_sha256,dimension_json,note,retrieved_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id,dimension_type,trade_type,period,dimension_code,statistic)
        DO UPDATE SET dimension_label=excluded.dimension_label,value=excluded.value,
          unit=excluded.unit,data_status=excluded.data_status,source_url=excluded.source_url,
          source_table=excluded.source_table,raw_sha256=excluded.raw_sha256,
          dimension_json=excluded.dimension_json,note=excluded.note,
          retrieved_at=excluded.retrieved_at''', (
            row.get('source_id'), row.get('dimension_type'), row.get('trade_type'),
            row.get('period'), row.get('dimension_code'), row.get('dimension_label'),
            row.get('statistic', 'value_monthly'), _number(row.get('value')),
            row.get('unit'), row.get('data_status', 'official'), row.get('source_url'),
            row.get('source_table'), row.get('raw_sha256'), row.get('dimension_json'),
            row.get('note'), now))
        count += max(0, cur.rowcount)
    conn.commit()
    return count


def upsert_csd_web_table_rows(conn, rows):
    now = datetime.now().isoformat()
    count = 0
    for row in rows or []:
        if not row or not row.get('table_id') or not row.get('period') or not row.get('series_code'):
            continue
        cur = conn.execute('''INSERT INTO hong_kong_macro_web_table_observations (
            source_id,table_id,period,series_code,series_label,value,unit,frequency,
            data_status,source_url,source_table,raw_sha256,dimension_json,retrieved_at,
            period_raw,statistic,construct_label,parser_version,missing_reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(table_id,period,series_code)
        DO UPDATE SET series_label=excluded.series_label,value=excluded.value,
          unit=excluded.unit,frequency=excluded.frequency,data_status=excluded.data_status,
          source_url=excluded.source_url,source_table=excluded.source_table,
          raw_sha256=excluded.raw_sha256,dimension_json=excluded.dimension_json,
          retrieved_at=excluded.retrieved_at,period_raw=excluded.period_raw,
          statistic=excluded.statistic,construct_label=excluded.construct_label,
          parser_version=excluded.parser_version,missing_reason=excluded.missing_reason''', (
            row.get('source_id'), row.get('table_id'), row.get('period'), row.get('series_code'),
            row.get('series_label'), _number(row.get('value')), row.get('unit'), row.get('frequency'),
            row.get('data_status', 'official'), row.get('source_url'), row.get('source_table'),
            row.get('raw_sha256'), row.get('dimension_json'), now,
            row.get('period_raw'), row.get('statistic'), row.get('construct_label'),
            row.get('parser_version', 'csd_web_v2'), row.get('missing_reason')))
        count += max(0, cur.rowcount)
    conn.commit()
    return count


def reingest_csd_web_tables_from_raw(db_path):
    """Re-key already downloaded CSD Web Table raw files without refetching.

    The live CSD payload can contain annual, quarterly, and monthly rows with
    the same normalized period, and can reuse ``sv`` for multiple statistics.
    This maintenance path preserves the old derived rows as ``superseded``
    and inserts rows using the current frequency/statistic-aware key.
    """
    with closing(connect(db_path)) as conn:
        ensure_hong_kong_macro_tables(conn)
        summary = []
        for source_id in sorted(source for source in SOURCE_CATALOG
                                 if source.startswith('HK_CSD_WEB_')):
            table_id = source_id.replace('HK_CSD_WEB_', '', 1)
            source = conn.execute(
                'SELECT raw_path,raw_sha256 FROM hong_kong_macro_sources WHERE source_id=?',
                (source_id,)).fetchone()
            if not source or not source['raw_path']:
                summary.append({'table_id': table_id, 'status': 'skipped',
                                'reason': 'raw_path_missing'})
                continue
            raw_path = ROOT / source['raw_path']
            if not raw_path.exists():
                summary.append({'table_id': table_id, 'status': 'skipped',
                                'reason': 'raw_file_missing', 'raw_path': source['raw_path']})
                continue
            payload = json.loads(raw_path.read_text(encoding='utf-8'))
            actual_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            if source['raw_sha256'] and actual_digest != source['raw_sha256']:
                raise ValueError(
                    f'CSD Web Table {table_id} raw SHA-256 mismatch: '
                    f'{actual_digest} != {source["raw_sha256"]}')
            source_url = f'{CSD_WEB_TABLE_API}?id={table_id}&lang=en&full_series=1'
            rows = parse_csd_web_table_payload(
                payload, table_id, source_url=source_url,
                raw_sha256=source['raw_sha256'])
            if not rows:
                raise ValueError(f'CSD Web Table {table_id} raw parser returned no observations')
            # The prior parser could assign a calendar month to H/Q rows,
            # use the statistic description as the unit, and leave construct
            # labels blank.  Preserve every such active row as an audit record
            # with a unique legacy key; otherwise the table's natural unique
            # key would simply reactivate the old row during the upsert and
            # erase evidence that a semantic repair happened.
            legacy_rows = conn.execute('''SELECT id,series_code
                FROM hong_kong_macro_web_table_observations
                WHERE source_id=? AND COALESCE(data_status, '') <> 'superseded'
                  AND COALESCE(parser_version,'') <> 'csd_web_v3_constructs' ''',
                                         (source_id,)).fetchall()
            for legacy in legacy_rows:
                conn.execute('''UPDATE hong_kong_macro_web_table_observations
                    SET series_code=series_code || ?, data_status='superseded',
                        missing_reason='superseded_csd_construct_repair',
                        parser_version='legacy_csd_pre_v3'
                    WHERE id=?''',
                             (f'|legacy=20260812-{legacy["id"]}', legacy['id']))
            superseded = len(legacy_rows)
            conn.commit()
            written = upsert_csd_web_table_rows(conn, rows)
            _update_source_state(conn, source_id, record_count=len(rows),
                                 parser_version='csd_web_v3_constructs')
            summary.append({'table_id': table_id, 'status': 'success',
                            'observations_parsed': len(rows),
                            'records_written': written, 'superseded': superseded,
                            'raw_path': source['raw_path']})
        return summary


def parse_rvd_index_matrix(matrix, code, source_id, source_url, frequency='monthly'):
    """Parse one RVD index sheet while preserving its official frequency."""
    header = next((row for row in matrix if any(_norm(c) == 'allclasses' for c in row)), None)
    if not header:
        raise ValueError('RVD index sheet lacks All Classes header')
    frequency = str(frequency or 'monthly').lower()
    if frequency not in ('monthly', 'quarterly', 'annual'):
        raise ValueError(f'unsupported RVD index frequency: {frequency}')
    header_index = next(i for i, row in enumerate(matrix) if row is header)
    header_col = next(i for i, cell in enumerate(header) if _norm(cell) == 'allclasses')
    # RVD places the label in a merged cell and the value one column to the
    # right in the data rows. Prefer the candidate with the most numeric rows;
    # this also keeps small parser fixtures with no spacer column valid.
    candidates = [header_col]
    if header_col + 1 < len(header):
        candidates.append(header_col + 1)
    value_col = max(candidates, key=lambda candidate: sum(
        1 for raw in matrix[header_index + 1:]
        if len(raw) > candidate and _number(raw[candidate]) is not None))
    rows = []
    current_year = None
    year_col = 2 if frequency == 'annual' else 1
    period_col = 3 if frequency == 'quarterly' else 5
    for raw in matrix[header_index + 1:]:
        year = _number(raw[year_col] if len(raw) > year_col else None)
        if year is not None:
            current_year = year
        if frequency == 'monthly':
            period = _month_period(current_year, _number(raw[period_col] if len(raw) > period_col else None))
        elif frequency == 'quarterly':
            month = _number(raw[period_col] if len(raw) > period_col else None)
            period = (f'{int(current_year):04d}-Q{int((month - 1) // 3) + 1}'
                      if current_year is not None and month is not None and 1 <= month <= 12 else None)
        else:
            period = f'{int(current_year):04d}' if current_year is not None else None
        value = _number(raw[value_col] if len(raw) > value_col else None)
        if not period or value is None:
            continue
        status = 'official_revised' if '*' in ' '.join(str(c) for c in raw) else 'official'
        rows.append(_row(code, period, value, source_id, source_url,
                         source_table=frequency, data_status=status,
                         note=f'RVD 官方{frequency}表 All Classes；* 表示临时/修订标记'))
    return [row for row in rows if row]


def parse_rvd_average_matrix(matrix, code, source_id, source_url):
    """Parse RVD average rent/price workbooks with class and district dimensions.

    These workbooks do not publish a single territory-wide ``All Classes``
    average.  We therefore retain each official class x district cell instead
    of manufacturing an unweighted average.
    """
    header_index = next((i for i, row in enumerate(matrix)
                         if any(_norm(cell) == 'year' for cell in row)), None)
    if header_index is None:
        raise ValueError('RVD average sheet lacks Year header')
    district_cols = []
    for index, cell in enumerate(matrix[header_index]):
        label = _norm(cell)
        if label in ('hongkong', 'kong', 'kowloon', 'territories'):
            district_cols.append((index, 'Hong Kong' if label == 'kong' else str(cell).strip()))
    if not district_cols:
        raise ValueError('RVD average sheet lacks district columns')
    class_by_value_col = {}
    # The two class header rows immediately precede the Hong Kong/Kowloon/
    # Territories rows; do not accidentally treat those district labels as a
    # class when a workbook has an extra bilingual header row.
    class_rows = matrix[max(0, header_index - 4):max(0, header_index - 2)]
    for group_index in range((len(district_cols) + 2) // 3):
        group_header_col = district_cols[group_index * 3][0]
        label = None
        for class_row in class_rows:
            candidate = str(class_row[group_header_col]).strip() if group_header_col < len(class_row) else ''
            if candidate and _norm(candidate) not in ('year', 'month'):
                label = candidate
        label = label or f'class_{group_index + 1}'
        for value_col, _district in district_cols[group_index * 3:(group_index + 1) * 3]:
            class_by_value_col[value_col + 1] = label
    rows = []
    current_year = None
    for raw in matrix[header_index + 1:]:
        year = _number(raw[1] if len(raw) > 1 else None)
        if year is not None:
            current_year = year
        period = _month_period(current_year,
                               _number(raw[5] if len(raw) > 5 else None))
        if not period:
            continue
        for header_col, district in district_cols:
            value_col = header_col + 1 if header_col + 1 < len(raw) else header_col
            value = _number(raw[value_col] if value_col < len(raw) else None)
            dimension = f"{class_by_value_col.get(value_col, 'unknown')}|{district}"
            item = _row(code, period, value, source_id, source_url,
                        source_table='Monthly',
                        data_status='official_revised' if '*' in ' '.join(str(c) for c in raw) else 'official',
                        note='RVD 官方平均租金/售价；保留 class × district 维度，不计算无权重总平均',
                        dimension_key='class_district', dimension_value=dimension)
            if item:
                rows.append(item)
    return rows


def parse_rvd_sales_matrix(matrix, source_id, source_url):
    header_index = next((i for i, row in enumerate(matrix)
                         if any(_norm(cell) == 'year' for cell in row)), None)
    if header_index is None:
        raise ValueError('RVD sales sheet lacks Year header')
    header = matrix[header_index]
    no_cols = [i for i, cell in enumerate(header) if _norm(cell) == 'no']
    consideration_cols = [i for i, cell in enumerate(header) if 'consideration' in _norm(cell)]
    if len(no_cols) < 2 or len(consideration_cols) < 2:
        raise ValueError('RVD sales sheet lacks primary/secondary columns')
    rows = []
    current_year = None
    for raw in matrix[header_index + 1:]:
        year = _number(raw[1] if len(raw) > 1 else None)
        if year is not None:
            current_year = year
        period = _month_period(current_year,
                               _number(raw[5] if len(raw) > 5 else None))
        if not period:
            continue
        p_count = _number(raw[no_cols[0]] if len(raw) > no_cols[0] else None)
        s_count = _number(raw[no_cols[1]] if len(raw) > no_cols[1] else None)
        p_value = _number(raw[consideration_cols[0]] if len(raw) > consideration_cols[0] else None)
        s_value = _number(raw[consideration_cols[1]] if len(raw) > consideration_cols[1] else None)
        values = {
            'HK_RVD_PRIMARY_SALES_COUNT': p_count,
            'HK_RVD_PRIMARY_SALES_VALUE': p_value,
            'HK_RVD_SECONDARY_SALES_COUNT': s_count,
            'HK_RVD_SECONDARY_SALES_VALUE': s_value,
            'HK_RVD_TOTAL_SALES_COUNT': (p_count + s_count) if p_count is not None and s_count is not None else None,
            'HK_RVD_TOTAL_SALES_VALUE': (p_value + s_value) if p_value is not None and s_value is not None else None,
        }
        for code, value in values.items():
            item = _row(code, period, value, source_id, source_url,
                        source_table='Monthly', note='RVD 官方 Domestic Sales 月度表；金额单位为 $ million')
            if item:
                rows.append(item)
    return rows


def parse_rvd_private_annual_matrix(matrix, code, source_id, source_url, value_kind='units'):
    """Parse RVD annual stock-flow sheets; totals are the last numeric cell."""
    rows = []
    matrix_text = ' '.join(str(cell) for raw in matrix for cell in raw if cell not in (None, ''))
    provisional_end = re.search(
        r'Provisional\s+figures\s*\(up\s+to\s+(\d{2})\.(\d{2})\.(\d{4})\)',
        matrix_text, re.I)
    source_period_end = None
    partial_year = None
    if provisional_end:
        day, month, end_year = map(int, provisional_end.groups())
        source_period_end = f'{end_year:04d}-{month:02d}-{day:02d}'
        partial_year = end_year
    for raw in matrix:
        # The workbook's footnotes contain years in prose (for example
        # ``Since 2003 ...``).  A year is an observation only when the
        # dedicated Year column is itself a four-digit cell; searching every
        # cell turns footnotes into fake annual observations.
        year_cell = raw[2] if len(raw) > 2 else None
        year_text = str(year_cell or '').strip()
        year = None
        if isinstance(year_cell, (int, float)) and not isinstance(year_cell, bool):
            candidate = int(year_cell)
            if float(year_cell) == candidate and 1980 <= candidate <= 2100:
                year = candidate
        elif re.fullmatch(r'(?:19|20)\d{2}', year_text):
            year = int(year_text)
        if year is None:
            continue
        numbers = [_number(cell) for cell in raw]
        numbers = [value for value in numbers if value is not None]
        if not numbers:
            continue
        value = numbers[-2] if value_kind == 'vacancy_units' and len(numbers) >= 2 else numbers[-1]
        if value_kind == 'rate':
            if value > 1.5:
                # Already percentage in a future workbook revision.
                pass
            else:
                value *= 100.0
        marker = '#' in ' '.join(str(c) for c in raw)
        target_code = code
        target_period = f'{int(year):04d}'
        status = 'official_revised' if marker else 'official'
        note = ('RVD 官方私人住宅年度存量/流量表；空置率由小数转为百分比'
                if value_kind == 'rate' else 'RVD 官方私人住宅年度表')
        target_period_end = None
        # The workbook has appeared in two equivalent layouts: some releases
        # put ``#`` on the 2026 value cell, while others put the provisional
        # footnote in a separate row.  Once the matrix-wide footnote identifies
        # the covered year, that year must never be re-exposed as a full annual
        # observation even if the marker is not repeated on the data row.
        if (code == 'HK_RVD_COMPLETIONS' and
                partial_year == int(year) and source_period_end):
            if source_period_end[5:7] != '06':
                raise ValueError(
                    'RVD provisional completions end outside verified H1 contract: ' +
                    source_period_end)
            target_code = 'HK_RVD_COMPLETIONS_YTD'
            target_period = f'{int(year):04d}-H1'
            target_period_end = source_period_end
            status = 'provisional'
            note = ('RVD official provisional completions cumulative through '
                    f'{source_period_end}; footnote: # Provisional figures '
                    f'(up to {source_period_end[8:10]}.{source_period_end[5:7]}.'
                    f'{source_period_end[:4]}). Not a full-year annual value.')
        item = _row(target_code, target_period, value, source_id, source_url,
                    source_table='annual', data_status=status,
                    source_period_end=target_period_end, note=note)
        if item:
            rows.append(item)
    return rows


def parse_landreg_primary_rows(records, source_id='HK_LANDREG_PRIMARY', source_url=''):
    rows = []
    field_map = {
        'HK_LR_PRIMARY_SALES_COUNT': 'Number of Primary Sales for ASP Residential Building Units',
        'HK_LR_SECONDARY_SALES_COUNT': 'Number of Secondary Sales for ASP Residential Building Units',
        'HK_LR_TOTAL_SALES_COUNT': 'Number of ASP for Residential Building Units',
        'HK_LR_PRIMARY_SALES_VALUE': 'Consideration of Primary Sales for ASP Residential Building Units',
        'HK_LR_SECONDARY_SALES_VALUE': 'Consideration of Secondary Sales for ASP Residential Building Units',
        'HK_LR_TOTAL_SALES_VALUE': 'Consideration of ASP for Residential Building Units',
    }
    for raw in records or []:
        period = _month_period(raw.get('Year'), raw.get('Month'))
        for code, field in field_map.items():
            item = _row(code, period, raw.get(field), source_id, source_url,
                        source_table='monthly_agt-pri',
                        note=('土地注册处官方注册买卖合约统计；注册月份不等于成交签约月份；'
                              '金额字段按官方 $ million 保存' if 'VALUE' in code else
                              '土地注册处官方注册买卖合约统计；注册月份不等于成交签约月份'))
            if item:
                rows.append(item)
    return rows


HKMA_QUARTER_END_INDICATORS = frozenset({
    'HK_HKMA_NOMINAL_GDP',
    'HK_HKMA_REAL_GDP',
    'HK_HKMA_CURRENT_ACCOUNT_BALANCE',
})


def normalize_hkma_period(indicator_code, source_period):
    """Normalize HKMA end-of-period fields using indicator frequency.

    GDP and current-account values are quarter totals reported only in
    March/June/September/December.  Non-quarter-end months and ``YYYY-00``
    annual rows are excluded rather than coerced into another frequency.
    """
    match = re.fullmatch(r'((?:19|20)\d{2})[-/.](\d{2})',
                         str(source_period or '').strip())
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if month == 0:
        return None
    if indicator_code in HKMA_QUARTER_END_INDICATORS:
        quarter = {3: 1, 6: 2, 9: 3, 12: 4}.get(month)
        return f'{year:04d}-Q{quarter}' if quarter else None
    meta = _meta(indicator_code)
    if meta.get('frequency') == 'monthly' and 1 <= month <= 12:
        return f'{year:04d}-{month:02d}'
    if meta.get('frequency') == 'quarterly':
        quarter = {3: 1, 6: 2, 9: 3, 12: 4}.get(month)
        return f'{year:04d}-Q{quarter}' if quarter else None
    return None


def parse_hkma_records(records, source_id):
    rows = []
    mappings = {
        'HK_HKMA_FC_RESERVE_ASSETS': (
            ('fc_resv_assets_ef', 'HK_HKMA_FC_RESERVE_ASSETS_EF'),
            ('fc_resv_assets_lf', 'HK_HKMA_FC_RESERVE_ASSETS_LF'),
            ('fc_resv_assets_total', 'HK_HKMA_FC_RESERVE_ASSETS_TOTAL'),
            ('fc_assets_fx_contracts_total', 'HK_HKMA_FC_RESERVE_ASSETS_CONTRACTS_TOTAL'),
            ('unsettle_fx_contracts_ef', 'HK_HKMA_UNSETTLED_FX_CONTRACTS_EF'),
            ('unsettle_fx_contracts_lf', 'HK_HKMA_UNSETTLED_FX_CONTRACTS_LF'),
            ('unsettle_fx_contracts_total', 'HK_HKMA_UNSETTLED_FX_CONTRACTS_TOTAL'),
        ),
        'HK_HKMA_ECONOMIC': (
            ('nominal_gdp', 'HK_HKMA_NOMINAL_GDP'),
            ('real_gdp', 'HK_HKMA_REAL_GDP'),
            ('gov_consol_bal', 'HK_HKMA_GOV_CONSOLIDATED_BALANCE'),
            ('composite_cpi', 'HK_HKMA_CPI_INDEX'),
            ('unemploy_rate', 'HK_HKMA_UNEMPLOYMENT_RATE'),
            ('curr_acc_bal', 'HK_HKMA_CURRENT_ACCOUNT_BALANCE'),
            ('fc_reserve', 'HK_HKMA_FC_RESERVE_USD_BN'),
        ),
        'HK_HKMA_MONETARY': (
            ('monetary_base_total', 'HK_HKMA_MONETARY_BASE'),
            ('aggr_balance', 'HK_HKMA_AGGREGATE_BALANCE'),
            ('ef_bills_notes', 'HK_HKMA_EF_BILLS_NOTES'),
            ('notes_coins_circulation', 'HK_HKMA_NOTES_COINS_CIRCULATION'),
            ('m1_total', 'HK_HKMA_M1_TOTAL'),
            ('m1_hkd', 'HK_HKMA_M1_HKD'),
            ('m2_total', 'HK_HKMA_M2_TOTAL'),
            ('m2_hkd', 'HK_HKMA_M2_HKD'),
            ('m3_total', 'HK_HKMA_M3_TOTAL'),
            ('m3_hkd', 'HK_HKMA_M3_HKD'),
            ('hibor_fixing_overnight', 'HK_HKMA_HIBOR_OVERNIGHT'),
            ('hibor_fixing_3m', 'HK_HKMA_HIBOR_3M'),
            ('best_lending_rate', 'HK_HKMA_BEST_LENDING_RATE'),
            ('discount_window_base_rate', 'HK_HKMA_DISCOUNT_WINDOW_BASE_RATE'),
            ('deposit_rate_3m', 'HK_HKMA_DEPOSIT_RATE_3M'),
            ('deposit_rate_saving', 'HK_HKMA_DEPOSIT_RATE_SAVING'),
            ('exrate_hkd_usd', 'HK_HKMA_EXRATE_HKD_USD'),
            ('nominal_eff_exrate_index', 'HK_HKMA_NEER_INDEX'),
            ('yield_efpaper_3m', 'HK_HKMA_EFPAPER_YIELD_3M'),
            ('yield_govbond_10y', 'HK_HKMA_GOVBOND_YIELD_10Y'),
        ),
        'HK_HKMA_BANKING_STATS': (
            ('no_of_ais', 'HK_HKMA_BANKING_NO_AIS'),
            ('total_assets', 'HK_HKMA_BANKING_TOTAL_ASSETS'),
            ('total_ext_claims', 'HK_HKMA_BANKING_TOTAL_EXTERNAL_CLAIMS'),
            ('total_ext_liab', 'HK_HKMA_BANKING_TOTAL_EXTERNAL_LIABILITIES'),
            ('cust_deposites_hkd', 'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_HKD'),
            ('cust_deposits_fc', 'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_FC'),
            ('cust_deposits_total', 'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_TOTAL'),
            ('loans_in_hk', 'HK_HKMA_BANKING_LOANS_IN_HK'),
            ('loans_outside_hk', 'HK_HKMA_BANKING_LOANS_OUTSIDE_HK'),
            ('loans_total', 'HK_HKMA_BANKING_LOANS_TOTAL'),
            ('loans_resid_mort_lending', 'HK_HKMA_BANKING_RESIDENTIAL_MORTGAGE_LOANS'),
            ('classif_loans', 'HK_HKMA_BANKING_CLASSIFIED_LOANS'),
            ('deli_ratio_resid_mort_lend', 'HK_HKMA_BANKING_MORTGAGE_DELINQUENCY_RATIO'),
            ('chroff_ratio_of_crcard_rece', 'HK_HKMA_BANKING_CREDIT_CARD_CHARGE_OFF_RATIO'),
        ),
        'HK_HKMA_CUSTOMER_DEPOSITS': (
            ('lb_demand_hkd', 'HK_HKMA_DEPOSITS_LB_DEMAND_HKD'),
            ('lb_demand_fc', 'HK_HKMA_DEPOSITS_LB_DEMAND_FC'),
            ('lb_demand_total', 'HK_HKMA_DEPOSITS_LB_DEMAND_TOTAL'),
            ('lb_savings_hkd', 'HK_HKMA_DEPOSITS_LB_SAVINGS_HKD'),
            ('lb_savings_fc', 'HK_HKMA_DEPOSITS_LB_SAVINGS_FC'),
            ('lb_savings_total', 'HK_HKMA_DEPOSITS_LB_SAVINGS_TOTAL'),
            ('lb_time_hkd', 'HK_HKMA_DEPOSITS_LB_TIME_HKD'),
            ('lb_time_fc', 'HK_HKMA_DEPOSITS_LB_TIME_FC'),
            ('lb_time_total', 'HK_HKMA_DEPOSITS_LB_TIME_TOTAL'),
            ('lb_total_hkd', 'HK_HKMA_DEPOSITS_LB_TOTAL_HKD'),
            ('lb_total_fc', 'HK_HKMA_DEPOSITS_LB_TOTAL_FC'),
            ('lb_total', 'HK_HKMA_DEPOSITS_LB_TOTAL'),
            ('all_ais_hkd', 'HK_HKMA_DEPOSITS_ALL_AIS_HKD'),
            ('all_ais_fc', 'HK_HKMA_DEPOSITS_ALL_AIS_FC'),
            ('all_ais_total', 'HK_HKMA_DEPOSITS_ALL_AIS_TOTAL'),
        ),
        'HK_HKMA_RMB_DEPOSITS': (
            ('demand_savings_deposits', 'HK_HKMA_RMB_DEPOSITS_DEMAND_SAVINGS'),
            ('time_deposits', 'HK_HKMA_RMB_DEPOSITS_TIME'),
            ('total_deposits', 'HK_HKMA_RMB_DEPOSITS_TOTAL'),
            ('no_of_ais_engaged', 'HK_HKMA_RMB_DEPOSITS_AIS_COUNT'),
        ),
        'HK_HKMA_LOANS_BY_TYPE': (
            ('imp_exp_reexp_fromhk_hkd', 'HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_HKD'),
            ('imp_exp_reexp_fromhk_fc', 'HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_FC'),
            ('imp_exp_reexp_fromhk_total', 'HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_TOTAL'),
            ('merch_trade_nonhk_total', 'HK_HKMA_LOANS_MERCH_TRADE_NON_HK_TOTAL'),
            ('loans_inhk_total', 'HK_HKMA_LOANS_IN_HK_TOTAL'),
            ('other_loans_outhk_total', 'HK_HKMA_LOANS_OUTSIDE_HK_TOTAL'),
            ('other_loans_unkplace_total', 'HK_HKMA_LOANS_UNKNOWN_USE_TOTAL'),
            ('total_loans', 'HK_HKMA_LOANS_TOTAL_BY_TYPE'),
        ),
        'HK_HKMA_MORTGAGE_SURVEY': (
            ('outstanding_loans_amt', 'HK_HKMA_MORTGAGE_OUTSTANDING_AMT'),
            ('delinquency_ratio', 'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_3M'),
            ('delinquency_ratio_6mth', 'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_6M'),
            ('resch_loan_ratio', 'HK_HKMA_MORTGAGE_RESCHEDULED_RATIO'),
            ('new_loans_app_received', 'HK_HKMA_MORTGAGE_NEW_APPLICATIONS'),
            ('new_loans_drawn_amt', 'HK_HKMA_MORTGAGE_NEW_DRAWN_AMT'),
            ('new_loans_drawn', 'HK_HKMA_MORTGAGE_NEW_DRAWN_COUNT'),
            ('new_loans_approved_amt', 'HK_HKMA_MORTGAGE_NEW_APPROVED_AMT'),
            ('new_loans_approved', 'HK_HKMA_MORTGAGE_NEW_APPROVED_COUNT'),
            ('new_loans_approved_avg_size', 'HK_HKMA_MORTGAGE_NEW_APPROVED_AVG_SIZE'),
            ('new_loans_approved_lv_ratio', 'HK_HKMA_MORTGAGE_NEW_APPROVED_LTV'),
            ('new_loans_approved_contra_life', 'HK_HKMA_MORTGAGE_NEW_APPROVED_LIFE'),
            ('new_loans_approved_pt_amt_pri', 'HK_HKMA_MORTGAGE_APPROVED_PRIMARY_AMT'),
            ('new_loans_approved_pt_amt_sec', 'HK_HKMA_MORTGAGE_APPROVED_SECONDARY_AMT'),
            ('new_loans_approved_pt_amt_refin', 'HK_HKMA_MORTGAGE_APPROVED_REFIN_AMT'),
            ('new_loans_approved_pt_primkt', 'HK_HKMA_MORTGAGE_APPROVED_PRIMARY_COUNT'),
            ('new_loans_approved_pt_secmkt', 'HK_HKMA_MORTGAGE_APPROVED_SECONDARY_COUNT'),
            ('new_loans_approved_pt_refin', 'HK_HKMA_MORTGAGE_APPROVED_REFIN_COUNT'),
            ('new_loans_approved_undrawn_amt', 'HK_HKMA_MORTGAGE_APPROVED_UNDRAWN_AMT'),
            ('new_loans_approved_undrawn', 'HK_HKMA_MORTGAGE_APPROVED_UNDRAWN_COUNT'),
            ('ir_new_loans_approved_hibor', 'HK_HKMA_MORTGAGE_RATE_HIBOR'),
            ('ir_new_loans_approved_blr', 'HK_HKMA_MORTGAGE_RATE_BLR'),
            ('ir_new_loans_approved_fixed', 'HK_HKMA_MORTGAGE_RATE_FIXED'),
            ('ir_new_loans_approved_other', 'HK_HKMA_MORTGAGE_RATE_OTHER'),
        ),
        'HK_HKMA_NEGATIVE_EQUITY': (
            ('outstanding_loans', 'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT'),
            ('outstanding_loans_ratio', 'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT_RATIO'),
            ('outstanding_loans_amt', 'HK_HKMA_NEGATIVE_EQUITY_LOANS_AMT'),
            ('outstanding_loans_amt_ratio', 'HK_HKMA_NEGATIVE_EQUITY_LOANS_AMT_RATIO'),
            ('unsecured_portion_amt', 'HK_HKMA_NEGATIVE_EQUITY_UNSECURED_AMT'),
            ('lv_ratio', 'HK_HKMA_NEGATIVE_EQUITY_LTV'),
        ),
    }
    unit_overrides = {'HK_HKMA_FC_RESERVE_USD_BN': 'US$ billion',
                      'HK_HKMA_CPI_INDEX': 'index',
                      'HK_HKMA_UNEMPLOYMENT_RATE': '%',
                      'HK_HKMA_HIBOR_OVERNIGHT': '%', 'HK_HKMA_HIBOR_3M': '%',
                      'HK_HKMA_BEST_LENDING_RATE': '%',
                      'HK_HKMA_DISCOUNT_WINDOW_BASE_RATE': '%',
                      'HK_HKMA_DEPOSIT_RATE_3M': '%',
                      'HK_HKMA_DEPOSIT_RATE_SAVING': '%',
                      'HK_HKMA_NEER_INDEX': 'index',
                      'HK_HKMA_EFPAPER_YIELD_3M': '%',
                      'HK_HKMA_GOVBOND_YIELD_10Y': '%',
                      'HK_HKMA_BANKING_MORTGAGE_DELINQUENCY_RATIO': '%',
                      'HK_HKMA_BANKING_CREDIT_CARD_CHARGE_OFF_RATIO': '%',
                      'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_3M': '%',
                      'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_6M': '%',
                      'HK_HKMA_MORTGAGE_RESCHEDULED_RATIO': '%',
                      'HK_HKMA_MORTGAGE_NEW_APPROVED_LTV': '%',
                      'HK_HKMA_MORTGAGE_RATE_HIBOR': '%',
                      'HK_HKMA_MORTGAGE_RATE_BLR': '%',
                      'HK_HKMA_MORTGAGE_RATE_FIXED': '%',
                      'HK_HKMA_MORTGAGE_RATE_OTHER': '%',
                      'HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT_RATIO': '%',
                      'HK_HKMA_NEGATIVE_EQUITY_LOANS_AMT_RATIO': '%',
                      'HK_HKMA_NEGATIVE_EQUITY_LTV': '%'}
    for raw in records or []:
        if source_id == 'HK_HKMA_NEGATIVE_EQUITY':
            quarter = re.search(r'(20\d{2})[-/. ]*Q([1-4])', str(raw.get('end_of_quarter') or ''), re.I)
            quarter_period = (f'{int(quarter.group(1)):04d}-Q{int(quarter.group(2))}'
                              if quarter else None)
        for field, code in mappings.get(source_id, ()):
            period = (quarter_period if source_id == 'HK_HKMA_NEGATIVE_EQUITY'
                      else normalize_hkma_period(code, raw.get('end_of_month')))
            item = _row(code, period, raw.get(field), source_id,
                        source_url=SOURCE_CATALOG[source_id][3], source_table='records',
                        note=('HKMA 官方开放 API；period 按字段官方月度/季度语义规范化；'
                              'YYYY-00 年度行不混入月/季序列；单位按 API 文档保存'))
            if item:
                if code in unit_overrides:
                    item['unit'] = unit_overrides[code]
                rows.append(item)
    return rows


def parse_trade_idds_payload(payload, source_id='HK_TRADE_IDDS', source_url=TRADE_API_URL):
    data = payload.get('dataSet') or payload.get('dataset') or payload.get('data') or []
    if isinstance(data, dict):
        data = data.get('records') or data.get('data') or []
    type_map = {
        '1': 'HK_TRADE_IMPORTS', '2': 'HK_TRADE_DOMESTIC_EXPORTS',
        '3': 'HK_TRADE_RE_EXPORTS', '4': 'HK_TRADE_TOTAL_EXPORTS',
        '5': 'HK_TRADE_TOTAL_TRADE', 'IMPORTS': 'HK_TRADE_IMPORTS',
        'DOMESTIC EXPORTS': 'HK_TRADE_DOMESTIC_EXPORTS',
        'RE-EXPORTS': 'HK_TRADE_RE_EXPORTS', 'REEXPORTS': 'HK_TRADE_RE_EXPORTS',
        'TOTAL EXPORTS': 'HK_TRADE_TOTAL_EXPORTS', 'TOTAL TRADE': 'HK_TRADE_TOTAL_TRADE',
    }
    rows = []
    for raw in data:
        raw_type = str(raw.get('ttype') or raw.get('tradeType') or raw.get('trade_type') or '').strip().upper()
        code = type_map.get(raw_type)
        if not code:
            continue
        period = _period(raw.get('period') or raw.get('time') or raw.get('refPeriod'))
        value = raw.get('figure') if 'figure' in raw else raw.get('value')
        item = _row(code, period, value, source_id, source_url,
                    source_table='api/get', note='Trade-IDDS 官方 API；ttype=ALL；不与 RVD 金额混合')
        if item:
            item['unit'] = str(raw.get('unit') or raw.get('unitEN') or item['unit'])
            rows.append(item)
    return rows


def parse_trade_dimension_payload(payload, request_key, source_url=TRADE_API_URL,
                                  raw_sha256=None):
    """Parse country/territory or commodity dimensions from Trade-IDDS.

    The same official API response shape is used for origin, consignment,
    destination and commodity requests. Dimensions are kept out of the five
    aggregate indicator series so origin and destination can never be
    accidentally compared as if they were the same concept.
    """
    request = TRADE_DIMENSION_REQUESTS[request_key]
    data = payload.get('dataSet') or payload.get('dataset') or payload.get('data') or []
    if isinstance(data, dict):
        data = data.get('records') or data.get('data') or []
    rows = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        period = _period(raw.get('period') or raw.get('time') or raw.get('refPeriod'))
        code = (raw.get('co') or raw.get('cc') or raw.get('code') or
                raw.get('dimensionCode') or raw.get('dimension_code'))
        label = (raw.get('coDescEN') or raw.get('ccDescEN') or raw.get('codeDescEN') or
                 raw.get('dimensionLabel') or raw.get('dimension_label') or code)
        value = raw.get('figure') if 'figure' in raw else raw.get('value')
        if not period or not code or _number(value) is None:
            continue
        statistic = {
            'VCm': 'value_monthly', 'VCy': 'value_ytd',
            'QCm': 'quantity_monthly', 'QCy': 'quantity_ytd',
        }.get(str(raw.get('sv') or '').replace(' ', ''), 'value')
        rows.append({
            'source_id': request['source_id'],
            'dimension_type': request['dimension_type'],
            'trade_type': str(raw.get('ttype') or raw.get('ttypeDescEN') or ''),
            'period': period, 'dimension_code': str(code),
            'dimension_label': str(label), 'statistic': statistic,
            'value': _number(value),
            'unit': str(raw.get('unitEN') or raw.get('unit') or ''),
            'data_status': 'official', 'source_url': source_url,
            'source_table': 'api/get', 'raw_sha256': raw_sha256,
            'dimension_json': json.dumps(raw, ensure_ascii=False, sort_keys=True),
            'note': request['note'],
        })
    return rows


def derive_trade_rows(rows, source_id='HK_TRADE_IDDS', source_url=TRADE_API_URL,
                      raw_sha256=None):
    """Create transparent monthly trade identities from the five raw series."""
    by_period = {}
    for row in rows or []:
        if row.get('period') and row.get('value') is not None:
            by_period.setdefault(row['period'], {})[row['indicator_code']] = float(row['value'])
    derived = []
    for period, values in sorted(by_period.items()):
        total_exports = values.get('HK_TRADE_TOTAL_EXPORTS')
        imports = values.get('HK_TRADE_IMPORTS')
        re_exports = values.get('HK_TRADE_RE_EXPORTS')
        if total_exports is not None and imports is not None:
            item = _row('HK_TRADE_BALANCE', period, total_exports - imports, source_id,
                        source_url, source_table='derived:api/get',
                        transformation='derived',
                        note='派生恒等式：trade_balance = total_exports - imports')
            if item:
                item['data_status'] = 'derived'
                item['formula'] = 'HK_TRADE_TOTAL_EXPORTS - HK_TRADE_IMPORTS'
                item['raw_sha256'] = raw_sha256
                derived.append(item)
        if total_exports not in (None, 0) and re_exports is not None:
            item = _row('HK_TRADE_RE_EXPORT_SHARE', period,
                        re_exports / total_exports * 100.0, source_id,
                        source_url, source_table='derived:api/get',
                        transformation='derived',
                        note='派生恒等式：re_export_share = re_exports / total_exports * 100')
            if item:
                item['data_status'] = 'derived'
                item['formula'] = 'HK_TRADE_RE_EXPORTS / HK_TRADE_TOTAL_EXPORTS * 100'
                item['raw_sha256'] = raw_sha256
                derived.append(item)
    return derived


def parse_csd_ctt_payload(payload, source_id, sp_codes):
    rows = []
    metadata = payload.get('SPs') or payload.get('Selection', {}).get('SPs') or []
    # The CTT response exposes selected values as SV01, SV02...; the common
    # tables used here have stable selected-series order, but prefer response
    # metadata if the endpoint supplies it.
    if metadata and isinstance(metadata, list):
        ids = []
        for item in metadata:
            if isinstance(item, dict):
                ids.append(item.get('SpId') or item.get('spId'))
            else:
                ids.append(item)
        if ids:
            sp_codes = list(sp_codes[:len(ids)])
    for raw in payload.get('MDT') or []:
        year = _number(raw.get('TV01'))
        if year is None:
            continue
        for index, code in enumerate(sp_codes, 1):
            value = raw.get(f'SV{index:02d}')
            item = _row(code, f'{int(year):04d}', value, source_id,
                        source_url='https://idds.censtatd.gov.hk/', source_table='MDT',
                        note='CSD-IDDS 官方 common table；年度值按官方表格选定序列入库')
            if item:
                rows.append(item)
    return rows


def _normalize_csd_frequency(value, fallback=None):
    mapping = {'M': 'monthly', 'MONTHLY': 'monthly',
               'Q': 'quarterly', 'QUARTERLY': 'quarterly',
               'H': 'semiannual', 'HALF-YEARLY': 'semiannual',
               'Y': 'annual', 'A': 'annual', 'ANNUAL': 'annual'}
    text = str(value or '').strip().upper()
    if not text:
        fallback_text = str(fallback or '').strip().upper()
        return mapping.get(fallback_text, 'unknown')
    return mapping.get(text, 'unknown')


def _csd_period(value, frequency=None):
    """Canonicalize CSD M/Q/H/Y periods without converting frequencies."""
    text = _text(value).replace('年', '-').replace('月', '').upper()
    freq = _normalize_csd_frequency(frequency)
    year_match = re.search(r'(20\d{2})', text)
    if not year_match:
        return None
    year = int(year_match.group(1))
    quarter = re.search(r'Q\s*([1-4])$', text)
    half = re.search(r'H\s*([1-2])$', text)
    numeric = re.search(r'(20\d{2})[-/. ]?(\d{1,2})$', text)
    if freq == 'unknown':
        # An unsupported source frequency must remain visibly unsupported;
        # do not silently coerce an ambiguous six-digit period to annual.
        if quarter:
            return f'{year:04d}-Q{int(quarter.group(1))}'
        if half:
            return f'{year:04d}-H{int(half.group(1))}'
        if re.fullmatch(r'20\d{2}-\d{2}', text):
            return text
        return text
    if freq == 'quarterly':
        if quarter:
            return f'{year:04d}-Q{int(quarter.group(1))}'
        if numeric and 1 <= int(numeric.group(2)) <= 12:
            month = int(numeric.group(2))
            return f'{year:04d}-Q{((month - 1) // 3) + 1}'
    elif freq == 'semiannual':
        if half:
            return f'{year:04d}-H{int(half.group(1))}'
        if numeric and 1 <= int(numeric.group(2)) <= 12:
            return f'{year:04d}-H{1 if int(numeric.group(2)) <= 6 else 2}'
    elif freq == 'monthly':
        if numeric and 1 <= int(numeric.group(2)) <= 12:
            return f'{year:04d}-{int(numeric.group(2)):02d}'
    elif freq == 'annual':
        return f'{year:04d}'
    if quarter:
        return f'{year:04d}-Q{int(quarter.group(1))}'
    if half:
        return f'{year:04d}-H{int(half.group(1))}'
    if numeric and 1 <= int(numeric.group(2)) <= 12:
        return f'{year:04d}-{int(numeric.group(2)):02d}'
    return f'{year:04d}'


def _csd_unit_and_statistic(description, explicit_unit=None):
    text = _text(description)
    lowered = text.lower()
    if 'year-on-year' in lowered or 'year on year' in lowered or '同比' in text:
        return '%', 'yoy'
    if 'index' in lowered or '指数' in text:
        return 'index', 'index'
    if text in ('Number', '人数', '宗数', 'Count') or lowered in ('number', 'count'):
        return 'count', 'level'
    if '%' in text or 'percent' in lowered or 'percentage' in lowered:
        return '%', 'level'
    return str(explicit_unit or text or ''), 'level'


def _csd_series_token(value):
    """Make a readable, stable token for a CSD statistic description."""
    text = _text(value).strip()
    if not text:
        return 'unknown'
    token = re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('_') or 'unknown'
    if len(token) <= 80:
        return token
    digest = hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]
    return f'{token[:60]}_{digest}'


def _csd_web_records(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ('dataset', 'dataSet', 'records', 'observations', 'data', 'Dataset', 'Data'):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _csd_web_records(value)
            if nested:
                return nested
    return []


def parse_csd_web_table_payload(payload, table_id, source_url=None, raw_sha256=None):
    """Parse the public CSD Web Table JSON without inventing dimensions.

    CSD has used more than one JSON envelope over time. This parser accepts
    the documented dataset/data/records envelopes and preserves the original
    row as ``dimension_json``. Unsupported wide-table shapes return no rows,
    which keeps the source status auditable instead of coercing labels into
    values.
    """
    table = CSD_WEB_TABLES.get(str(table_id), {})
    source_id = f'HK_CSD_WEB_{table_id}'
    source_url = source_url or f'{CSD_WEB_TABLE_API}?id={table_id}&lang=en&full_series=1'
    rows = []
    period_keys = ('period', 'Period', 'time', 'Time', 'refPeriod', 'date', 'Date',
                   'TIME_PERIOD', 'time_period', 'year', 'Year')
    value_keys = ('value', 'Value', 'figure', 'Figure', 'obs_value', 'OBS_VALUE',
                  'observation', 'Observation')
    code_keys = ('series_code', 'seriesCode', 'indicator_code', 'indicatorCode',
                 'series', 'code', 'id', 'ID', 'key')
    label_keys = ('series_label', 'seriesLabel', 'indicator_name', 'indicatorName',
                  'label', 'Label', 'name', 'Name', 'title', 'Title', 'description')
    unit_keys = ('unit', 'Unit', 'unit_name', 'unitName')
    for raw in _csd_web_records(payload):
        if not isinstance(raw, dict):
            continue
        source = dict(raw)
        nested_series = source.pop('series', None)
        if isinstance(nested_series, dict):
            source = {**nested_series, **source}
        period_value = next((source.get(key) for key in period_keys if source.get(key) not in (None, '')), None)
        value = next((source.get(key) for key in value_keys if source.get(key) not in (None, '')), None)
        code = next((source.get(key) for key in code_keys if source.get(key) not in (None, '')), None)
        label = next((source.get(key) for key in label_keys if source.get(key) not in (None, '')), None)
        unit = next((source.get(key) for key in unit_keys if source.get(key) not in (None, '')), None)
        # The live CSD Web Table API uses ``sv``/``svDesc`` for the selected
        # statistic and dynamic dimension fields such as REGION/REGIONDesc or
        # GDP_COMPONENT/GDP_COMPONENTDesc. Build an explicit series key from
        # those fields rather than treating a dimension label as a value.
        if value is None and 'figure' in source:
            value = source.get('figure')
        statistic = 'level'
        construct_label = ''
        construct_missing_reason = None
        raw_frequency = source.get('freq') or table.get('frequency')
        if code is None and source.get('sv') not in (None, ''):
            dimension_parts = []
            label_parts = []
            for key, item in source.items():
                if key in ('period', 'freq', 'sv', 'svDesc', 'figure', 'sd_value') or key.endswith('Desc'):
                    continue
                if item not in (None, ''):
                    dimension_parts.append(f'{key}={item}')
                    desc = source.get(f'{key}Desc')
                    label_parts.append(str(desc or item))
            code_parts = dimension_parts + [
                f"freq={source.get('freq') or table.get('frequency') or 'unknown'}",
                f"sv={source.get('sv')}",
                f"stat={_csd_series_token(source.get('svDesc') or source.get('sv'))}",
            ]
            code = '|'.join(code_parts) or str(source.get('sv'))
            construct_label = ' · '.join(label_parts)
            if not label_parts:
                verified = CSD_VERIFIED_CONSTRUCT_LABELS.get(
                    (str(table_id), str(source.get('sv'))))
                if verified:
                    construct_label = verified
                    label_parts.append(verified)
                else:
                    construct_label = f"unknown:sv={source.get('sv')}"
                    construct_missing_reason = 'construct_label_not_yet_verified'
                    label_parts.append(construct_label)
            label_parts.append(str(source.get('svDesc') or source.get('sv')))
            label = ' · '.join(label_parts)
        table_frequency = _normalize_csd_frequency(raw_frequency, table.get('frequency'))
        parsed_unit, statistic = _csd_unit_and_statistic(
            source.get('svDesc') or label or code, unit)
        if unit in (None, '') or str(unit) == str(source.get('svDesc') or ''):
            unit = parsed_unit
        elif statistic == 'yoy':
            unit = '%'
        period = _csd_period(period_value, raw_frequency)
        if not period or code in (None, '') or _number(value) is None:
            continue
        if not construct_label:
            construct_label = f'unknown:series_code={code}'
            construct_missing_reason = (construct_missing_reason or
                                        'construct_label_not_yet_verified')
        provisional = str(source.get('sd_value') or '').strip().lower() in {
            'p', 'provisional', '暂定', '臨時'}
        row_status = ('metadata_unknown' if table_frequency == 'unknown' else
                      'provisional' if provisional else 'official')
        rows.append({
            'source_id': source_id, 'table_id': str(table_id), 'period': period,
            'series_code': str(code), 'series_label': str(label or code),
            'value': _number(value), 'unit': str(unit or ''),
            'frequency': table_frequency, 'data_status': row_status,
            'source_url': source_url, 'source_table': 'dataset',
            'raw_sha256': raw_sha256,
            'dimension_json': json.dumps(raw, ensure_ascii=False, sort_keys=True),
            'period_raw': str(period_value or ''), 'statistic': statistic,
            'construct_label': construct_label,
            'parser_version': 'csd_web_v3_constructs',
            'missing_reason': ('unknown_frequency' if table_frequency == 'unknown'
                               else construct_missing_reason),
        })
    return rows


def _save_raw(source_id, content, suffix):
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest()
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S%f')
    path = RAW_ROOT / f'{source_id}_{stamp}.{suffix.lstrip(".")}'
    part = path.with_suffix(path.suffix + '.part')
    part.write_bytes(content)
    os.replace(part, path)
    return str(path.relative_to(ROOT)).replace(os.sep, '/'), digest


def _update_source_state(conn, source_id, **values):
    fields = []
    params = []
    for key, value in values.items():
        fields.append(f'{key}=?')
        params.append(value)
    fields.append('updated_at=?')
    params.append(datetime.now().isoformat())
    params.append(source_id)
    conn.execute(f'UPDATE hong_kong_macro_sources SET {", ".join(fields)} WHERE source_id=?', params)
    conn.commit()


def _fetch_json(session, url, params=None):
    response = session.get(url, params=params, headers=UA, timeout=TIMEOUT)
    response.raise_for_status()
    return response.content, response.json()


def _fetch_hkma_all(session, url, extra_params=None):
    records, offset, seen = [], 0, set()
    while offset <= 10000:
        params = {'offset': offset, 'pagesize': 1000}
        params.update(extra_params or {})
        content, payload = _fetch_json(session, url, params)
        result = payload.get('result') or {}
        page = result.get('records') or result.get('data') or []
        if not page:
            break
        marker = json.dumps(page[:1], sort_keys=True, ensure_ascii=False)
        if marker in seen:
            break
        seen.add(marker)
        records.extend(page)
        offset += len(page)
        if len(page) < 1000 or offset >= int(result.get('datasize') or offset):
            break
    return records


def _fetch_rvd(session):
    page_response = session.get(RVD_INDEX_PAGE, headers=UA, timeout=TIMEOUT)
    page_response.raise_for_status()
    soup = BeautifulSoup(page_response.text, 'html.parser')
    discovered = {}
    for anchor in soup.find_all('a', href=True):
        href = urljoin(RVD_INDEX_PAGE, anchor['href'])
        if href.lower().endswith(('.xls', '.xlsx')):
            discovered[Path(href).name] = href
    direct = {Path(path).name: urljoin(RVD_BASE, path) for path in RVD_FILES.values()}
    discovered.update({key: discovered.get(key, value) for key, value in direct.items()})
    jobs = []
    for code, path in RVD_FILES.items():
        url = discovered.get(Path(path).name) or urljoin(RVD_BASE, path)
        response = session.get(url, headers=UA, timeout=TIMEOUT)
        response.raise_for_status()
        content = response.content
        raw_path, digest = _save_raw('HK_RVD_' + code.replace('HK_RVD_', ''), content, 'xls')
        jobs.append((code, url, content, digest, raw_path))
    return page_response.content, jobs


def _parse_rvd_workbook(code, content, url):
    import xlrd
    workbook = xlrd.open_workbook(file_contents=content)
    if code == 'HK_RVD_DOMESTIC_SALES':
        sheet = workbook.sheet_by_index(0)
        return parse_rvd_sales_matrix([sheet.row_values(i) for i in range(sheet.nrows)],
                                      'HK_RVD_DOMESTIC_SALES', url)
    if code == 'HK_RVD_PRIVATE_STOCK_FLOW':
        mapping = {
            'Completions': ('HK_RVD_COMPLETIONS', 'units'),
            'Stock': ('HK_RVD_STOCK', 'units'),
            'Vacancy': ('HK_RVD_VACANCY_UNITS', 'units'),
            'Take-up': ('HK_RVD_TAKE_UP', 'units'),
        }
        rows = []
        for index in range(workbook.nsheets):
            sheet = workbook.sheet_by_index(index)
            title = sheet.name
            matrix = [sheet.row_values(i) for i in range(sheet.nrows)]
            if title.startswith('Vacancy'):
                # The same row reports total vacant units and total vacancy rate.
                rows.extend(parse_rvd_private_annual_matrix(
                    matrix, 'HK_RVD_VACANCY_UNITS', 'HK_RVD_PRIVATE_STOCK_FLOW', url, 'vacancy_units'))
                for row in parse_rvd_private_annual_matrix(
                        matrix, 'HK_RVD_VACANCY_RATE', 'HK_RVD_PRIVATE_STOCK_FLOW', url, 'rate'):
                    rows.append(row)
            else:
                key = next((key for key in mapping if title.startswith(key)), None)
                if key:
                    target, kind = mapping[key]
                    rows.extend(parse_rvd_private_annual_matrix(
                        matrix, target, 'HK_RVD_PRIVATE_STOCK_FLOW', url, kind))
        return rows
    target = code
    source_for_code = {
        'HK_RVD_PRIVATE_AVG_RENT': 'HK_RVD_AVG_RENT',
        'HK_RVD_PRIVATE_AVG_PRICE': 'HK_RVD_AVG_PRICE',
        'HK_RVD_RENT_INDEX': 'HK_RVD_RENT_INDEX',
        'HK_RVD_PRICE_INDEX': 'HK_RVD_PRICE_INDEX',
    }[code]
    sheets_by_frequency = {
        'monthly': next((sheet for sheet in workbook.sheets()
                         if str(sheet.name).lower().startswith('monthly')), None),
        'quarterly': next((sheet for sheet in workbook.sheets()
                           if str(sheet.name).lower().startswith('quarterly')), None),
        'annual': next((sheet for sheet in workbook.sheets()
                        if str(sheet.name).lower().startswith('annual')), None),
    }
    if code in ('HK_RVD_PRIVATE_AVG_RENT', 'HK_RVD_PRIVATE_AVG_PRICE'):
        sheet = sheets_by_frequency['monthly'] or workbook.sheet_by_index(0)
        return parse_rvd_average_matrix([sheet.row_values(i) for i in range(sheet.nrows)],
                                        target, source_for_code, url)
    rows = []
    low_frequency_codes = {
        'HK_RVD_RENT_INDEX': {
            'quarterly': 'HK_RVD_RENT_INDEX_QUARTERLY',
            'annual': 'HK_RVD_RENT_INDEX_ANNUAL'},
        'HK_RVD_PRICE_INDEX': {
            'quarterly': 'HK_RVD_PRICE_INDEX_QUARTERLY',
            'annual': 'HK_RVD_PRICE_INDEX_ANNUAL'},
    }
    for frequency, sheet in sheets_by_frequency.items():
        if sheet is None:
            continue
        target_code = low_frequency_codes.get(code, {}).get(frequency, code)
        rows.extend(parse_rvd_index_matrix(
            [sheet.row_values(i) for i in range(sheet.nrows)],
            target_code, source_for_code, url, frequency=frequency))
    return rows


def reingest_rvd_private_annual_from_raw(db_path):
    """Repair RVD annual observations from the retained raw workbook.

    This is deliberately a local maintenance path: it never fetches the
    source again. Existing annual observations remain in the database as
    ``superseded`` audit history, while the corrected parser reuses the same
    source hash and canonical ``YYYY`` periods for the active rows.
    """
    source_id = 'HK_RVD_PRIVATE_STOCK_FLOW'
    with closing(connect(db_path)) as conn:
        ensure_hong_kong_macro_tables(conn)
        source = conn.execute('''SELECT raw_path,raw_sha256,entry_url
            FROM hong_kong_macro_sources WHERE source_id=?''', (source_id,)).fetchone()
        if not source or not source['raw_path']:
            return {'status': 'skipped', 'reason': 'raw_path_missing', 'source_id': source_id}
        raw_path = ROOT / source['raw_path']
        if not raw_path.exists():
            return {'status': 'skipped', 'reason': 'raw_file_missing',
                    'source_id': source_id, 'raw_path': source['raw_path']}
        content = raw_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        rows = _parse_rvd_workbook(source_id, content, source['entry_url'] or RVD_INDEX_PAGE)
        rows = [row for row in rows if row and (
            row.get('frequency') == 'annual' or
            row.get('indicator_code') == 'HK_RVD_COMPLETIONS_YTD')]
        for row in rows:
            row['raw_sha256'] = digest
            row['parser_version'] = 'hk_macro_v3_rvd_partial_year'
            row['vintage_date'] = ''
        before = conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
            WHERE source_id=? AND frequency='annual' AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ''', (source_id,)).fetchone()[0]
        conn.execute('''UPDATE hong_kong_macro_observations SET data_status='superseded',
            missing_reason='superseded_rvd_annual_parser_repair',
            note=TRIM(COALESCE(note,'') || ' [superseded: RVD full-year/partial-year repair 2026-08-12]')
            WHERE source_id=? AND frequency='annual' AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ''', (source_id,))
        conn.commit()
        written = upsert_hong_kong_observations(conn, rows)
        conn.execute('''UPDATE hong_kong_macro_sources SET parser_version=?,raw_sha256=?,
            raw_path=?,record_count=?,last_success_at=?,status='success',updated_at=?
            WHERE source_id=?''', ('hk_macro_v3_rvd_partial_year', digest, source['raw_path'],
                                   len(rows), datetime.now().isoformat(),
                                   datetime.now().isoformat(), source_id))
        conn.commit()
    return {'status': 'success', 'source_id': source_id, 'raw_path': source['raw_path'],
            'raw_sha256': digest, 'rows_parsed': len(rows), 'rows_written': written,
            'active_rows_before': before}


SAFE_RESERVE_CODES = (
    'CN_SAFE_FX_RESERVES_USD', 'CN_SAFE_IMF_RESERVE_POSITION_USD',
    'CN_SAFE_SDR_HOLDINGS_USD', 'CN_SAFE_MONETARY_GOLD_USD',
    'CN_SAFE_MONETARY_GOLD_QUANTITY', 'CN_SAFE_OTHER_RESERVE_ASSETS_USD',
    'CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD',
)


def migrate_safe_reserve_release_metadata(conn,
                                          page_last_updated_by_year=None):
    """Clear URL-inferred SAFE release dates without changing observations."""
    page_last_updated_by_year = page_last_updated_by_year or {
        2026: '2026-08-07',
    }
    ensure_china_macro_tables(conn)
    rows = conn.execute('''SELECT * FROM china_macro_observations
        WHERE indicator_code IN ({})
          AND source_type='safe_official_reserve_assets' '''.format(
              ','.join('?' for _ in SAFE_RESERVE_CODES)), SAFE_RESERVE_CODES).fetchall()
    reason = ('SAFE annual reserve-assets page does not provide a distinct '
              'per-observation release date; URL path date is page creation '
              'metadata and retrieved_at is ingestion time.')
    changed = 0
    values_before = {(row['indicator_code'], row['period']): row['value'] for row in rows}
    for row in rows:
        source_url = str(row['source_url'] or '')
        match = re.search(r'/safe/(20\d{2})/(\d{2})(\d{2})/', source_url)
        page_created = (f'{match.group(1)}-{match.group(2)}-{match.group(3)}'
                        if match else row['source_page_created_date'])
        period_year = int(str(row['period'])[:4]) if str(row['period'])[:4].isdigit() else None
        last_updated = (page_last_updated_by_year.get(period_year) or
                        row['source_page_last_updated_date'])
        inferred_release = bool(page_created and row['release_date'] == page_created)
        desired_release = None if inferred_release else row['release_date']
        desired_not_provided = int(desired_release in (None, ''))
        note = str(row['parser_notes'] or '')
        marker = 'SAFE release metadata remediation 2026-08-12'
        desired_note = note if marker in note else (note + '; ' + marker).strip('; ')
        desired_reason = reason if desired_not_provided else row['release_date_reason']
        current = (
            row['release_date'], row['source_page_created_date'],
            row['source_page_last_updated_date'], row['release_date_not_provided'],
            row['release_date_reason'], row['parser_notes'])
        desired = (
            desired_release, page_created, last_updated, desired_not_provided,
            desired_reason, desired_note)
        if current == desired:
            continue
        conn.execute('''UPDATE china_macro_observations SET
            release_date=?,source_page_created_date=?,
            source_page_last_updated_date=?,release_date_not_provided=?,
            release_date_reason=?,parser_notes=?,parser_version='safe_reserve_v3'
            WHERE id=?''', (*desired, row['id']))
        changed += 1
    conn.commit()
    values_after = {(row['indicator_code'], row['period']): row['value']
                    for row in conn.execute('''SELECT indicator_code,period,value
                        FROM china_macro_observations WHERE indicator_code IN ({})
                        AND source_type='safe_official_reserve_assets' '''.format(
                            ','.join('?' for _ in SAFE_RESERVE_CODES)),
                        SAFE_RESERVE_CODES)}
    if values_before != values_after:
        raise RuntimeError('SAFE release metadata migration changed observation values')
    return {'rows_examined': len(rows), 'rows_changed': changed,
            'values_unchanged': True,
            'page_last_updated_by_year': page_last_updated_by_year}


def migrate_hkma_period_frequency_rows(conn):
    """Supersede legacy HKMA period keys and activate canonical replacements."""
    target_codes = tuple(HKMA_QUARTER_END_INDICATORS) + (
        'HK_HKMA_GOV_CONSOLIDATED_BALANCE',)
    active_rows = [dict(row) for row in conn.execute('''SELECT *
        FROM hong_kong_macro_observations
        WHERE indicator_code IN ({})
          AND COALESCE(data_status,'') <> 'superseded' '''.format(
              ','.join('?' for _ in target_codes)), target_codes)]
    corrected = []
    superseded_ids = []
    for row in active_rows:
        expected_frequency = _meta(row['indicator_code'])['frequency']
        canonical = normalize_hkma_period(row['indicator_code'], row['period'])
        if row['indicator_code'] in HKMA_QUARTER_END_INDICATORS:
            already_canonical = bool(re.fullmatch(
                r'(?:19|20)\d{2}-Q[1-4]', str(row['period'] or '')))
            canonical = row['period'] if already_canonical else canonical
        else:
            already_canonical = bool(re.fullmatch(
                r'(?:19|20)\d{2}-(?:0[1-9]|1[0-2])', str(row['period'] or '')))
            canonical = row['period'] if already_canonical else canonical
        if already_canonical and row['frequency'] == expected_frequency:
            continue
        original_status = row['data_status']
        legacy_vintage = f'legacy_hkma_period_frequency_20260812_{row["id"]}'
        conn.execute('''UPDATE hong_kong_macro_observations SET
            data_status='superseded',vintage_date=?,
            missing_reason='superseded_hkma_period_frequency_repair',
            note=TRIM(COALESCE(note,'') ||
                ' [superseded: HKMA period/frequency repair 2026-08-12]')
            WHERE id=?''', (legacy_vintage, row['id']))
        superseded_ids.append(row['id'])
        if canonical:
            replacement = dict(row)
            replacement.update({
                'period': canonical, 'period_label': canonical,
                'frequency': expected_frequency, 'data_status': original_status,
                'vintage_date': '', 'missing_reason': None,
                'parser_version': 'hk_macro_v3_hkma_period',
                'note': (str(row.get('note') or '') +
                         ' [canonical HKMA period/frequency repair 2026-08-12]').strip(),
            })
            corrected.append(replacement)
    conn.commit()
    written = upsert_hong_kong_observations(conn, corrected) if corrected else 0
    return {'rows_examined': len(active_rows),
            'legacy_rows_superseded': len(superseded_ids),
            'canonical_rows_written': written,
            'excluded_without_canonical_period': len(superseded_ids) - len(corrected)}


def apply_hong_kong_macro_final_remediation_migration(db_path):
    """Apply the 2026-08-12 P0/P1/P2 migration from retained raw data."""
    with closing(connect(db_path)) as conn:
        ensure_china_macro_tables(conn)
        ensure_hong_kong_macro_tables(conn)
        before = {
            'active_hk': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
                WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone()[0],
            'superseded_hk': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
                WHERE data_status='superseded' ''').fetchone()[0],
            'active_csd': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_web_table_observations
                WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone()[0],
            'superseded_csd': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_web_table_observations
                WHERE data_status='superseded' ''').fetchone()[0],
        }
        safe = migrate_safe_reserve_release_metadata(conn)
        hkma = migrate_hkma_period_frequency_rows(conn)
    rvd = reingest_rvd_private_annual_from_raw(db_path)
    csd = reingest_csd_web_tables_from_raw(db_path)
    with closing(connect(db_path)) as conn:
        ensure_hong_kong_macro_tables(conn, refresh_metadata=True)
        conn.execute('''UPDATE hong_kong_macro_sources SET
            entry_url='https://tradeidds.censtatd.gov.hk/CommonTable/ETR08a03'
            WHERE source_id='HK_TRADE_IDDS_TOP_DESTINATIONS' ''')
        conn.execute('''UPDATE hong_kong_macro_sources SET
            dataset_name='Population growth by component',
            release_metadata_status=COALESCE(release_metadata_status,'not_provided'),
            release_metadata_reason=COALESCE(release_metadata_reason,
                'Official observation release date not consistently exposed.')
            WHERE source_id='HK_CSD_WEB_110-01003' ''')
        conn.execute(f'PRAGMA user_version={HK_MACRO_SCHEMA_VERSION}')
        conn.commit()
        after = {
            'active_hk': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
                WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone()[0],
            'superseded_hk': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
                WHERE data_status='superseded' ''').fetchone()[0],
            'active_csd': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_web_table_observations
                WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone()[0],
            'superseded_csd': conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_web_table_observations
                WHERE data_status='superseded' ''').fetchone()[0],
            'user_version': conn.execute('PRAGMA user_version').fetchone()[0],
            'quick_check': conn.execute('PRAGMA quick_check').fetchone()[0],
        }
    return {'success': after['quick_check'] == 'ok', 'before': before,
            'after': after, 'safe': safe, 'hkma': hkma,
            'rvd': rvd, 'csd': csd}


def _fetch_landreg(session, full_history=False):
    names = list(LANDREG_PRIMARY_PATHS)
    if not full_history:
        names = ['agt-primary']
    by_period, raw_parts = {}, []
    for name in names:
        for table in ('t1', 't2'):
            url = f'{LANDREG_BASE}/json/monthly_agt-pri/{name}/{table}.json'
            content, payload = _fetch_json(session, url)
            records = payload if isinstance(payload, list) else payload.get('data') or []
            raw_parts.append({'endpoint': url, 'records': records})
            for record in records:
                key = (str(record.get('Year')), str(record.get('Month')))
                by_period.setdefault(key, {}).update(record)
    encoded = json.dumps(raw_parts, ensure_ascii=False, sort_keys=True).encode('utf-8')
    raw_path, digest = _save_raw('HK_LANDREG_PRIMARY', encoded, 'json')
    return list(by_period.values()), raw_path, digest


def _fetch_trade(session, full_history=False, start_year=None):
    # Trade-IDDS requires its own session/cookie flow. A direct API call that
    # receives the site's access-denied response is recorded as blocked; no
    # CAPTCHA, cookie replay, or verification bypass is attempted.
    spec = session.get(TRADE_API_SPEC, headers=UA, timeout=TIMEOUT)
    spec.raise_for_status()
    start = int(start_year or (2012 if full_history else max(2012, datetime.now().year - 5)))
    end = datetime.now().strftime('%Y%m')
    time.sleep(0.8)
    payload = None
    attempted_ends = []
    for step in range(0, 7):
        end_year = int(end[:4]); end_month = int(end[4:])
        for _ in range(step):
            end_month -= 1
            if end_month == 0:
                end_year -= 1; end_month = 12
        candidate = f'{end_year:04d}{end_month:02d}'
        attempted_ends.append(candidate)
        response = session.get(TRADE_API_URL, params={
            'lang': 'EN', 'sv': 'VCm', 'freq': 'M',
            'period': f'{start:04d}01,{candidate}', 'ttype': 'ALL',
        }, headers=UA, timeout=TIMEOUT)
        response.raise_for_status()
        candidate_payload = response.json()
        header = candidate_payload.get('header') or {}
        status = header.get('status') or {}
        code = status.get('code', candidate_payload.get('code'))
        message = ' '.join(str(item) for item in (status.get('message') or []))
        if code in (None, 0, '0'):
            payload = candidate_payload
            break
        # Trade-IDDS rejects a future/current month before the monthly release;
        # move back one month based on the official validation response.
        if code in (1, '1') and 'Period code' in message and 'not defined' in message:
            continue
        raise RuntimeError(f'Trade-IDDS API code={code}: {message or candidate_payload}')
    if payload is None:
        raise RuntimeError(f'Trade-IDDS latest period unavailable; tried {attempted_ends}')
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    raw_path, digest = _save_raw('HK_TRADE_IDDS', encoded, 'json')
    return payload, raw_path, digest


def _trade_end_candidates():
    end_year, end_month = datetime.now().year, datetime.now().month
    for step in range(0, 7):
        year, month = end_year, end_month
        for _ in range(step):
            month -= 1
            if month == 0:
                year -= 1
                month = 12
        yield f'{year:04d}{month:02d}'


def _trade_dataset_records(payload):
    data = payload.get('dataSet') or payload.get('dataset') or payload.get('data') or []
    if isinstance(data, dict):
        data = data.get('records') or data.get('data') or []
    return data if isinstance(data, list) else []


def _trade_dimension_code_chunks(request):
    values = tuple(request.get('dimension_values') or ())
    if not values:
        return [None]
    return [values[index:index + TRADE_DIMENSION_MAX_CODES]
            for index in range(0, len(values), TRADE_DIMENSION_MAX_CODES)]


def _fetch_trade_dimension(session, request_key, full_history=False, start_year=None):
    request = TRADE_DIMENSION_REQUESTS[request_key]
    start = int(start_year or (2012 if full_history else max(2012, datetime.now().year - 5)))
    payload = None
    combined_records = []
    attempted_ends = []
    for code_chunk in _trade_dimension_code_chunks(request):
        chunk_payload = None
        for end in _trade_end_candidates():
            attempted_ends.append(f'{end}:{",".join(code_chunk) if code_chunk else "default"}')
            params = {'lang': 'EN', 'sv': 'VCm', 'freq': 'M',
                      'period': f'{start:04d}01,{end}'}
            params.update(request['params'])
            if code_chunk:
                params['code'] = ','.join(code_chunk)
            response = session.get(TRADE_API_URL, params=params, headers=UA, timeout=TIMEOUT)
            response.raise_for_status()
            candidate = response.json()
            status = (candidate.get('header') or {}).get('status') or {}
            code = status.get('code', candidate.get('code'))
            message = ' '.join(str(item) for item in (status.get('message') or []))
            if code in (None, 0, '0'):
                chunk_payload = candidate
                break
            if code in (1, '1') and 'Period code' in message and 'not defined' in message:
                continue
            raise RuntimeError(f'Trade-IDDS {request_key} API code={code}: {message or candidate}')
        if chunk_payload is None:
            raise RuntimeError(f'Trade-IDDS {request_key} latest period unavailable; tried {attempted_ends}')
        if payload is None:
            payload = chunk_payload
        combined_records.extend(_trade_dataset_records(chunk_payload))
    if payload is None:
        raise RuntimeError(f'Trade-IDDS {request_key} returned no payload; tried {attempted_ends}')
    if len(_trade_dimension_code_chunks(request)) > 1:
        payload = dict(payload)
        payload['dataSet'] = combined_records
        payload['_dimension_chunk_count'] = len(_trade_dimension_code_chunks(request))
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')
    raw_path, digest = _save_raw(request['source_id'], encoded, 'json')
    return payload, raw_path, digest


def _fetch_csd(session, table_id):
    url = CSD_CTT_URL.format(table_id=table_id)
    content, payload = _fetch_json(session, url)
    raw_path, digest = _save_raw(f'HK_CSD_CTT_{table_id}', content, 'json')
    return payload, url, raw_path, digest


def _fetch_csd_web_table(session, table_id):
    params = {'id': table_id, 'lang': 'en', 'full_series': '1'}
    content, payload = _fetch_json(session, CSD_WEB_TABLE_API, params)
    raw_path, digest = _save_raw(f'HK_CSD_WEB_{table_id}', content, 'json')
    url = requests.Request('GET', CSD_WEB_TABLE_API, params=params).prepare().url
    return payload, url, raw_path, digest


def _filter_start(rows, start_year):
    if not start_year:
        return rows
    try:
        year = int(start_year)
    except (TypeError, ValueError):
        return rows
    return [row for row in rows if str(row.get('period') or '')[:4].isdigit()
            and int(str(row['period'])[:4]) >= year]


def _load_hk_series(conn, code):
    if code not in INDICATORS:
        raise ValueError(f'未知香港指标: {code}')
    if not _meta(code)['eligible_for_lead_lag']:
        return []
    return [dict(row) for row in conn.execute('''SELECT period,value,source_id,raw_sha256,retrieved_at,
            parser_version,data_status FROM hong_kong_macro_observations
        WHERE indicator_code=? AND value IS NOT NULL
          AND COALESCE(data_status, '') <> 'superseded'
          AND COALESCE(dimension_key, '')='' ORDER BY period''', (code,))]


def _month_index(period):
    match = re.match(r'^(\d{4})-(\d{2})$', str(period or ''))
    if not match:
        return None
    return int(match.group(1)) * 12 + int(match.group(2))


def _period_from_month_index(index):
    index = int(index)
    year, month0 = divmod(index - 1, 12)
    return f'{year:04d}-{month0 + 1:02d}'


def _load_first_tier_housing_index(conn, indicator_code):
    """Build a transparent four-city equal-weighted chain-linked index.

    The source observations are the official NBS city-level month-on-month
    indices. We average the available first-tier cities each month and chain
    the average from 100; a missing month breaks the chain instead of being
    bridged. This is a derived comparison series, not an official national
    index and not a price-level estimate.
    """
    source_code = MAINLAND_HOUSING_CODES.get(indicator_code, (None,))[0]
    if not source_code:
        return []
    placeholders = ','.join('?' for _ in FIRST_TIER_CITIES)
    try:
        rows = [dict(row) for row in conn.execute(
            f'''SELECT city,period,value FROM housing_city_observations
                WHERE indicator_code=? AND city IN ({placeholders}) AND value IS NOT NULL
                ORDER BY period,city''', (source_code, *FIRST_TIER_CITIES))]
    except sqlite3.OperationalError:
        return []
    buckets = {}
    for row in rows:
        key = _month_index(row.get('period'))
        if key is not None:
            buckets.setdefault(key, []).append(float(row['value']))
    if not buckets:
        return []
    output = []
    previous = None
    current = None
    for key in range(min(buckets), max(buckets) + 1):
        values = buckets.get(key)
        if not values:
            current = None
            previous = key
            continue
        average_mom = sum(values) / len(values)
        if previous is None or key != previous + 1 or current is None:
            current = 100.0
        else:
            current *= average_mom / 100.0
        output.append({'period': _period_from_month_index(key), 'value': round(current, 8),
                       'city_count': len(values)})
        previous = key
    return output


def _load_mainland_series(conn, code):
    if code in MAINLAND_HOUSING_CODES:
        return _load_first_tier_housing_index(conn, code)
    if code in MAINLAND_NATIONAL_TRANSACTION_CODES or code in MAINLAND_DERIVED_MONTHLY_CODES:
        source_code = (MAINLAND_NATIONAL_TRANSACTION_CODES.get(code) or
                       MAINLAND_DERIVED_MONTHLY_CODES[code])[0]
        try:
            rows = conn.execute('''SELECT period,value,data_status,raw_sha256,retrieved_at,
                    parser_version FROM housing_national_observations
                WHERE indicator_code=? AND value IS NOT NULL ORDER BY period''',
                                (source_code,)).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute('''SELECT period,value FROM housing_national_observations
                WHERE indicator_code=? AND value IS NOT NULL ORDER BY period''',
                                (source_code,)).fetchall()
        output = []
        for row in rows:
            row = dict(row)
            period = _period(row['period'])
            if period and _number(row['value']) is not None:
                output.append({'period': period, 'value': float(row['value']),
                               'data_status': row.get('data_status'),
                               'raw_sha256': row.get('raw_sha256'),
                               'retrieved_at': row.get('retrieved_at'),
                               'parser_version': row.get('parser_version')})
        return output
    try:
        source_rows = conn.execute('''SELECT period,value,source_name AS source_id,
                raw_sha256,retrieved_at FROM china_macro_observations
            WHERE indicator_code=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ORDER BY period''', (code,))
    except sqlite3.OperationalError:
        source_rows = conn.execute('''SELECT period,value,source_name AS source_id
            FROM china_macro_observations
            WHERE indicator_code=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded' ORDER BY period''', (code,))
    return [dict(row) for row in source_rows]


def _known_mainland_lead_lag_codes(conn):
    """Return requestable Mainland codes without accepting arbitrary strings."""
    known = set(MAINLAND_LEAD_LAG_HINTS) | set(MAINLAND_HOUSING_CODES)
    known.update(MAINLAND_NATIONAL_TRANSACTION_CODES)
    known.update(MAINLAND_DERIVED_MONTHLY_CODES)
    for table_name in ('china_macro_observations', 'housing_city_observations',
                       'housing_national_observations'):
        try:
            known.update(row[0] for row in conn.execute(
                f'SELECT DISTINCT indicator_code FROM {table_name} WHERE indicator_code IS NOT NULL'))
        except sqlite3.OperationalError:
            continue
    return known


def _available_hk_lead_lag_indicators(conn):
    available = []
    for code in sorted(INDICATORS):
        meta = _meta(code)
        if meta.get('frequency') != 'monthly' or meta.get('status') != 'available':
            continue
        count = conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
            WHERE indicator_code=? AND value IS NOT NULL
              AND COALESCE(data_status,'') <> 'superseded'
              AND COALESCE(dimension_key,'')='' ''', (code,)).fetchone()[0]
        if count >= 60:
            available.append(code)
    return available


def _series_input_hash(series):
    stable = [{key: row.get(key) for key in (
        'period', 'value', 'source_id', 'raw_sha256', 'retrieved_at',
        'parser_version', 'data_status')} for row in series]
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False,
                                     sort_keys=True, default=str).encode('utf-8')).hexdigest()


def _series_bounds(series):
    periods = [row.get('period') for row in series if row.get('period')]
    if not periods:
        return None, None
    return (min(periods, key=lambda item: _period_sort_key(item)),
            max(periods, key=lambda item: _period_sort_key(item)))


def _transform_values(series, transform):
    rows = sorted((item for item in series if _month_index(item.get('period')) is not None),
                  key=lambda item: item['period'])
    if transform in (None, '', 'level'):
        return {_month_index(item['period']): float(item['value']) for item in rows}
    if transform in ('diff', 'difference'):
        values = {_month_index(item['period']): float(item['value']) for item in rows}
        return {key: values[key] - values[key - 1] for key in values if key - 1 in values}
    if transform in ('mom', 'qoq'):
        values = {_month_index(item['period']): float(item['value']) for item in rows}
        step = 1 if transform == 'mom' else 3
        output = {}
        for key, value in values.items():
            previous = values.get(key - step)
            if previous not in (None, 0):
                output[key] = (value / previous - 1.0) * 100.0
        return output
    if transform in ('yoy', 'pct_change_12'):
        values = {_month_index(item['period']): float(item['value']) for item in rows}
        output = {}
        for key, value in values.items():
            previous = values.get(key - 12)
            if previous not in (None, 0):
                output[key] = (value / previous - 1.0) * 100.0
        return output
    if transform == 'rolling_12m':
        values = {_month_index(item['period']): float(item['value']) for item in rows}
        return {key: sum(values[key - offset] for offset in range(12)) / 12.0
                for key in values if all(key - offset in values for offset in range(12))}
    if transform == 'index100':
        values = {_month_index(item['period']): float(item['value']) for item in rows}
        first = next(iter(values.values()), None)
        return {key: value / first * 100.0 for key, value in values.items()
                if first not in (None, 0)}
    raise ValueError(f'不支持的 lead-lag transform: {transform}')


def _pearson(left, right):
    if len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    den_left = sum((a - mean_left) ** 2 for a in left)
    den_right = sum((b - mean_right) ** 2 for b in right)
    denominator = math.sqrt(den_left * den_right)
    return numerator / denominator if denominator else None


def compute_lead_lag(hk_series, mainland_series, lags=range(-24, 25),
                     min_overlap=60, transform='level', window_type='full',
                     window_start=None, window_end=None, hk_transform=None,
                     mainland_transform=None):
    """Compute descriptive correlations with the fixed convention:

    ``corr_at_lag(k) = corr(HK_t, Mainland_(t+k))``. Thus k > 0 means the
    Hong Kong observation is earlier and leads the mainland series. This is
    alignment only; it is not a causal estimator.
    """
    hk_transform = hk_transform or transform
    mainland_transform = mainland_transform or transform
    hk = _transform_values(hk_series, hk_transform)
    mainland = _transform_values(mainland_series, mainland_transform)
    start_key = _month_index(window_start) if window_start else None
    end_key = _month_index(window_end) if window_end else None
    result = []
    for lag in lags:
        pairs = [(hk[key], mainland[key + int(lag)]) for key in sorted(hk)
                 if (start_key is None or key >= start_key)
                 and (end_key is None or key <= end_key)
                 if key + int(lag) in mainland]
        left, right = zip(*pairs) if pairs else ([], [])
        n_obs = len(pairs)
        status = 'ok' if n_obs >= int(min_overlap) and _pearson(left, right) is not None else 'insufficient_sample'
        result.append({'lag_months': int(lag), 'corr': _pearson(left, right) if status == 'ok' else None,
                       'n_obs': n_obs, 'status': status, 'window_type': window_type})
    return {
        'sign_convention': 'corr_at_lag(k)=corr(HK_t, Mainland_(t+k)); k>0 means Hong Kong leads',
        'transform': transform, 'hk_transform': hk_transform,
        'mainland_transform': mainland_transform, 'min_overlap': int(min_overlap),
        'window_type': window_type,
        'window_start': window_start, 'window_end': window_end,
        'results': result, 'note': '描述性同步/领先滞后相关，不作因果识别或预测结论。',
    }


def _rolling_lead_lag(hk_series, mainland_series, transform, min_overlap,
                      window_months=(60, 120), step_months=12, hk_transform=None,
                      mainland_transform=None):
    """Return annual-anchor rolling curves for the requested window lengths."""
    hk_keys = [_month_index(row.get('period')) for row in hk_series
               if _month_index(row.get('period')) is not None]
    mainland_keys = [_month_index(row.get('period')) for row in mainland_series
                     if _month_index(row.get('period')) is not None]
    if not hk_keys or not mainland_keys:
        return []
    first = max(min(hk_keys), min(mainland_keys))
    last = min(max(hk_keys), max(mainland_keys))
    output = []
    for months in window_months:
        anchor = first + months - 1
        while anchor <= last:
            start = anchor - months + 1
            start_period = _period_from_month_index(start)
            end_period = _period_from_month_index(anchor)
            # The display curve itself is the full -24..+24 lag sequence for
            # this rolling sample, so a reader can compare curves without
            # silently switching lag definitions.
            result = compute_lead_lag(
                hk_series, mainland_series, min_overlap=min_overlap,
                transform=transform, window_type=f'rolling_{months}m',
                window_start=start_period, window_end=end_period,
                hk_transform=hk_transform, mainland_transform=mainland_transform)
            result.update({'window_months': months, 'window_start': start_period,
                           'window_end': end_period})
            output.append(result)
            anchor += step_months
    return output


def _standardized_comparison_series(hk_series, mainland_series, hk_transform,
                                    mainland_transform):
    hk = _transform_values(hk_series, hk_transform)
    mainland = _transform_values(mainland_series, mainland_transform)
    keys = sorted(set(hk) & set(mainland))
    if not keys:
        return []
    left = [hk[key] for key in keys]
    right = [mainland[key] for key in keys]
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    sd_left = math.sqrt(sum((value - mean_left) ** 2 for value in left) / len(left)) or 1.0
    sd_right = math.sqrt(sum((value - mean_right) ** 2 for value in right) / len(right)) or 1.0
    return [{'period': _period_from_month_index(key),
             'hk': (hk[key] - mean_left) / sd_left,
             'mainland': (mainland[key] - mean_right) / sd_right}
            for key in keys]


def _best_lag(result_rows, absolute=False, minimum_lag=None):
    rows = [row for row in result_rows if row.get('status') == 'ok'
            and row.get('corr') is not None
            and (minimum_lag is None or row['lag_months'] >= minimum_lag)]
    if not rows:
        return None
    row = max(rows, key=(lambda item: abs(item['corr'])) if absolute
              else (lambda item: item['corr']))
    return {'lag_months': row['lag_months'], 'corr': row['corr'], 'n_obs': row['n_obs']}


def _build_lead_lag_payload(db_path, hk_indicator=None, mainland_indicator=None,
                            transform='yoy', min_overlap=60):
    hk_indicator = hk_indicator or 'HK_RVD_PRICE_INDEX'
    mainland_indicator = mainland_indicator or 'CN_FIRST_TIER_NEW_HOME_INDEX'
    transform = (transform or 'yoy').lower()
    if hk_indicator not in INDICATORS:
        return {'success': False, 'status': 'invalid_request',
                'error': f'未知香港指标: {hk_indicator}',
                'available_hk_indicators': sorted(INDICATORS)}
    hk_meta = _meta(hk_indicator)
    if hk_meta.get('frequency') != 'monthly':
        return {'success': False, 'status': 'invalid_request',
                'error': 'lead-lag 香港序列必须是月度频率',
                'hk_indicator_code': hk_indicator,
                'frequency': hk_meta.get('frequency')}
    if hk_meta.get('status') != 'available':
        return {'success': False, 'status': 'hk_no_data',
                'error': hk_meta.get('status_note') or '香港指标在官方来源不可用',
                'upstream_status': hk_meta.get('status'),
                'hk_indicator_code': hk_indicator}
    if transform not in hk_meta['allowed_transforms']:
        return {'success': False, 'status': 'unsupported_transform',
                'error': f'{hk_indicator} 不支持 transform={transform}',
                'allowed_transforms': hk_meta['allowed_transforms']}
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        known_mainland = _known_mainland_lead_lag_codes(conn)
        if mainland_indicator not in known_mainland:
            return {'success': False, 'status': 'invalid_request',
                    'error': f'未知大陆指标: {mainland_indicator}',
                    'mainland_indicator_code': mainland_indicator,
                    'available_mainland_hint': list(MAINLAND_LEAD_LAG_HINTS)}
        hk = _load_hk_series(conn, hk_indicator)
        mainland = _load_mainland_series(conn, mainland_indicator)
        available_hk = _available_hk_lead_lag_indicators(conn)
    if not hk:
        return {'success': False, 'status': 'hk_no_data',
                'error': '香港序列没有可用于 lead-lag 的月度有效观测；未保存结果。',
                'hk_indicator_code': hk_indicator,
                'mainland_indicator_code': mainland_indicator,
                'transform': transform, 'hk_n_obs': len(hk),
                'mainland_n_obs': len(mainland),
                'available_hk_indicators': available_hk}
    if not mainland:
        return {'success': False, 'status': 'mainland_no_data',
                'error': '内地序列没有可用于 lead-lag 的月度有效观测；未保存结果。',
                'hk_indicator_code': hk_indicator,
                'mainland_indicator_code': mainland_indicator,
                'transform': transform, 'hk_n_obs': len(hk),
                'mainland_n_obs': len(mainland),
                'available_hk_indicators': available_hk}
    mainland_transform = ('level' if mainland_indicator in MAINLAND_PRETRANSFORMED_CODES
                          else transform)
    base = compute_lead_lag(hk, mainland, min_overlap=min_overlap, transform=transform,
                            hk_transform=transform, mainland_transform=mainland_transform)
    base['rolling_windows'] = _rolling_lead_lag(
        hk, mainland, transform=transform, min_overlap=min_overlap,
        hk_transform=transform, mainland_transform=mainland_transform)
    base['comparison_series'] = _standardized_comparison_series(
        hk, mainland, transform, mainland_transform)
    base['best_absolute'] = _best_lag(base['results'], absolute=True)
    base['best_positive'] = _best_lag(base['results'])
    # lag=0 is contemporaneous, not a Hong-Kong-leading result.
    base['best_hong_kong_lead'] = _best_lag(base['results'], absolute=True, minimum_lag=1)
    base['rolling_summary'] = []
    for window in base['rolling_windows']:
        best = _best_lag(window.get('results') or [], absolute=True)
        base['rolling_summary'].append({
            'window_months': window.get('window_months'),
            'window_start': window.get('window_start'),
            'window_end': window.get('window_end'),
            'best_absolute': best,
        })
    if mainland_indicator in MAINLAND_HOUSING_CODES:
        mainland_definition = {
            'code': mainland_indicator,
            'label': MAINLAND_HOUSING_CODES[mainland_indicator][1],
            'cities': list(FIRST_TIER_CITIES),
            'aggregation': '每月对有值的一线城市等权平均月环比指数，再链式累计；缺月不桥接',
            'source_table': 'housing_city_observations',
            'source_indicator': MAINLAND_HOUSING_CODES[mainland_indicator][0],
        }
    elif mainland_indicator in MAINLAND_DERIVED_MONTHLY_CODES:
        source_code, label, unit, source_table = MAINLAND_DERIVED_MONTHLY_CODES[mainland_indicator]
        mainland_definition = {
            'code': mainland_indicator, 'label': label, 'unit': unit,
            'source_table': source_table, 'source_indicator': source_code,
            'aggregation': '由同一年度相邻月份国家统计局官方累计销售面积/销售额差分得到月度流量；缺少上月时不推断。',
            'warning': '这是项目内 derived 序列，不是国家统计局单独发布的月度流量；1—2月合并发布期不拆分。',
        }
    elif mainland_indicator in MAINLAND_NATIONAL_TRANSACTION_CODES:
        source_code, label, unit, source_table = MAINLAND_NATIONAL_TRANSACTION_CODES[mainland_indicator]
        mainland_definition = {
            'code': mainland_indicator, 'label': label, 'unit': unit,
            'source_table': source_table, 'source_indicator': source_code,
            'aggregation': '国家统计局新建商品房销售面积/销售额累计同比；这是 YTD 同比，不是月度流量。',
            'warning': '不能把累计同比直接解释为单月成交量；仅用于香港交易序列的敏感性配对。',
        }
    else:
        mainland_definition = {
            'code': mainland_indicator, 'label': '中国宏观观察层原始序列',
            'aggregation': '项目中国宏观观察层；未跨口径改造',
        }
    valid_results = [row for row in base['results'] if row.get('status') == 'ok'
                     and row.get('corr') is not None]
    source_vintages = {}
    for row in list(hk) + list(mainland):
        source_id = row.get('source_id') or 'mainland_input'
        source_vintages.setdefault(source_id, {
            'raw_sha256': row.get('raw_sha256'),
            'retrieved_at': row.get('retrieved_at'),
        })
    hk_input_hash = _series_input_hash(hk)
    mainland_input_hash = _series_input_hash(mainland)
    hk_start, hk_end = _series_bounds(hk)
    mainland_start, mainland_end = _series_bounds(mainland)
    parser_versions = {
        'hk': sorted({row.get('parser_version') for row in hk if row.get('parser_version')}),
        'mainland': sorted({row.get('parser_version') for row in mainland if row.get('parser_version')}),
    }
    input_hash = hashlib.sha256(json.dumps(
        {'hk_indicator': hk_indicator, 'mainland_indicator': mainland_indicator,
         'transform': transform, 'hk': hk, 'mainland': mainland,
                 'source_vintages': source_vintages,
                 'hk_input_hash': hk_input_hash,
                 'mainland_input_hash': mainland_input_hash},
        ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    base.update({'success': bool(valid_results),
                 'status': 'ok' if valid_results else 'insufficient_overlap',
                 'error': None if valid_results else '没有任何 lag 达到 min_overlap 且相关系数可计算；未保存结果。',
                 'hk_indicator_code': hk_indicator,
                 'mainland_indicator_code': mainland_indicator,
                 'hk_n_obs': len(hk), 'mainland_n_obs': len(mainland),
                 'comparison_mode': 'normalized_zscore',
                 'mainland_definition': mainland_definition,
                 'source_vintages': source_vintages,
                 'input_hash': input_hash,
                 'hk_input_hash': hk_input_hash,
                 'mainland_input_hash': mainland_input_hash,
                 'hk_start': hk_start, 'hk_end': hk_end,
                 'mainland_start': mainland_start, 'mainland_end': mainland_end,
                 'rolling_window_specs': {'window_months': [60, 120], 'step_months': 12,
                                          'lag_min': -24, 'lag_max': 24},
                 'parser_versions': parser_versions,
                 'calculation_version': 'hk_lead_lag_v2',
                 'code_revision': _current_code_revision(),
                 'available_hk_indicators': [code for code in available_hk
                                              if not code.startswith('HK_RVD_PRIVATE_AVG_')],
                 'available_mainland_hint': list(MAINLAND_LEAD_LAG_HINTS),
                 'status_vocabulary': ['ok', 'hk_no_data', 'mainland_no_data',
                                       'unsupported_transform', 'insufficient_overlap',
                                       'invalid_request', 'failed']})
    return base


def build_lead_lag_payload(db_path, hk_indicator=None, mainland_indicator=None,
                           transform='yoy', min_overlap=60):
    """Build lead-lag output with a closed, auditable top-level status set."""
    try:
        min_overlap = int(min_overlap)
    except (TypeError, ValueError):
        return {'success': False, 'status': 'invalid_request',
                'error': 'min_overlap 必须是整数'}
    if min_overlap < 2:
        return {'success': False, 'status': 'invalid_request',
                'error': 'min_overlap 必须至少为 2'}
    try:
        return _build_lead_lag_payload(
            db_path, hk_indicator=hk_indicator,
            mainland_indicator=mainland_indicator,
            transform=transform, min_overlap=min_overlap)
    except Exception as exc:  # keep API status explicit without fabricating a result
        return {'success': False, 'status': 'failed',
                'error': f'lead-lag 计算失败：{type(exc).__name__}: {exc}'}


def persist_lead_lag_payload(db_path, payload, pair_code=None):
    """Persist an explicitly requested lead-lag snapshot for vintage audits.

    GET requests remain read-only.  Callers must invoke this function through
    the protected save route or a local script, so a descriptive calculation is
    never silently written just because somebody viewed the page.
    """
    if not isinstance(payload, dict) or not payload.get('success') or payload.get('status') != 'ok':
        raise ValueError('不能保存空的或失败的 lead-lag 结果')
    primary_results = payload.get('results') or []
    if not any(isinstance(result, dict) and result.get('status') == 'ok'
               and result.get('corr') is not None for result in primary_results):
        raise ValueError('lead-lag 没有有效的全样本相关曲线，不能保存')
    if payload.get('hk_n_obs') is not None and payload.get('hk_n_obs') <= 0:
        raise ValueError('香港序列没有有效观察，不能保存')
    if payload.get('mainland_n_obs') is not None and payload.get('mainland_n_obs') <= 0:
        raise ValueError('内地序列没有有效观察，不能保存')
    required_snapshot_fields = (
        'input_hash', 'hk_input_hash', 'mainland_input_hash',
        'hk_start', 'hk_end', 'mainland_start', 'mainland_end',
        'hk_n_obs', 'mainland_n_obs', 'min_overlap',
        'source_vintages', 'parser_versions', 'calculation_version',
        'code_revision', 'rolling_window_specs',
    )
    incomplete = [field for field in required_snapshot_fields
                  if payload.get(field) in (None, '', {}, [])]
    if incomplete:
        raise ValueError('snapshot metadata 不完整，拒绝保存: ' + ', '.join(incomplete))
    computed_at = datetime.now().isoformat()
    snapshot_id = uuid.uuid4().hex
    pair_code = pair_code or '{}__{}__{}'.format(
        payload.get('hk_indicator_code') or '',
        payload.get('mainland_indicator_code') or '',
        payload.get('transform') or '')
    note = payload.get('note') or '描述性同步/领先滞后结果；不作因果识别或预测。'
    rows = []

    def add_result(result, window_type, window_start, window_end):
        if not isinstance(result, dict):
            return
        rows.append((uuid.uuid4().hex, pair_code,
                     payload.get('hk_indicator_code'), payload.get('mainland_indicator_code'),
                     payload.get('transform'), result.get('lag_months'), result.get('corr'),
                     result.get('n_obs'), window_start, window_end, window_type,
                     computed_at, result.get('status'), note, snapshot_id))

    for result in payload.get('results') or []:
        add_result(result, payload.get('window_type') or 'full',
                   payload.get('window_start'), payload.get('window_end'))
    for window in payload.get('rolling_windows') or []:
        for result in window.get('results') or []:
            add_result(result, window.get('window_type') or
                       f"rolling_{window.get('window_months')}m",
                       window.get('window_start'), window.get('window_end'))
    if not rows:
        raise ValueError('lead-lag 结果没有可保存的相关曲线')
    with closing(connect(db_path)) as conn:
        ensure_hong_kong_macro_tables(conn)
        source_vintages = payload.get('source_vintages') or {}
        parameters = {
            'lag_min': payload.get('rolling_window_specs', {}).get('lag_min',
                         min((row[5] for row in rows if row[5] is not None), default=None)),
            'lag_max': payload.get('rolling_window_specs', {}).get('lag_max',
                         max((row[5] for row in rows if row[5] is not None), default=None)),
            'min_overlap': payload.get('min_overlap'),
            'window_type': payload.get('window_type'),
            'window_start': payload.get('window_start'),
            'window_end': payload.get('window_end'),
            'rolling_window_specs': payload.get('rolling_window_specs') or {},
        }
        input_hash = payload.get('input_hash') or hashlib.sha256(
            json.dumps({'hk': payload.get('hk_indicator_code'),
                        'mainland': payload.get('mainland_indicator_code'),
                        'transform': payload.get('transform'),
                        'comparison': payload.get('comparison_series') or [],
                        'vintages': source_vintages},
                       ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        conn.execute('BEGIN')
        conn.execute('''INSERT INTO hong_kong_macro_lead_lag_snapshots (
            snapshot_id,pair_code,hk_indicator_code,mainland_indicator_code,transform,
            hk_transform,mainland_transform,min_overlap,lag_min,lag_max,input_start,input_end,
            hk_n_obs,mainland_n_obs,input_hash,source_vintages_json,parameters_json,
            computation_version,code_revision,computed_at,status,note,
            hk_input_hash,mainland_input_hash,hk_start,hk_end,mainland_start,mainland_end,
            rolling_windows_json,parser_versions_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                snapshot_id, pair_code, payload.get('hk_indicator_code'),
                payload.get('mainland_indicator_code'), payload.get('transform'),
                payload.get('hk_transform'), payload.get('mainland_transform'),
                payload.get('min_overlap'), parameters['lag_min'], parameters['lag_max'],
                payload.get('window_start'), payload.get('window_end'),
                payload.get('hk_n_obs'), payload.get('mainland_n_obs'), input_hash,
                json.dumps(source_vintages, ensure_ascii=False, sort_keys=True),
                json.dumps(parameters, ensure_ascii=False, sort_keys=True),
                payload.get('calculation_version', 'hk_lead_lag_v2'),
                payload.get('code_revision', 'worktree'), computed_at, 'ok', note,
                payload.get('hk_input_hash'), payload.get('mainland_input_hash'),
                payload.get('hk_start'), payload.get('hk_end'),
                payload.get('mainland_start'), payload.get('mainland_end'),
                json.dumps(payload.get('rolling_window_specs') or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(payload.get('parser_versions') or {}, ensure_ascii=False, sort_keys=True)))
        conn.executemany('''INSERT INTO hong_kong_macro_lead_lag_results
            (result_id,pair_code,hk_indicator_code,mainland_indicator_code,transform,
             lag_months,corr,n_obs,window_start,window_end,window_type,computed_at,
             status,note,snapshot_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows)
        conn.commit()
    return {'success': True, 'snapshot_id': snapshot_id, 'pair_code': pair_code,
            'computed_at': computed_at, 'rows_written': len(rows),
            'input_hash': input_hash, 'calculation_version': 'hk_lead_lag_v2'}


def _snapshot_reproducibility(metadata):
    required = (
        'input_hash', 'hk_input_hash', 'mainland_input_hash',
        'hk_start', 'hk_end', 'mainland_start', 'mainland_end',
        'hk_n_obs', 'mainland_n_obs', 'min_overlap',
        'source_vintages_json', 'parameters_json', 'parser_versions_json',
        'computation_version', 'code_revision',
    )
    if not metadata or ('metadata_snapshot_id' in metadata and
                        not metadata.get('metadata_snapshot_id')):
        return {
            'reproducibility_status': 'legacy_unreproducible',
            'metadata_complete': False,
            'missing_metadata_fields': list(required),
            'result_group_type': 'legacy_result_group',
        }
    missing = [field for field in required
               if metadata.get(field) in (None, '', '{}', '[]')]
    return {
        'reproducibility_status': ('reproducible_snapshot' if not missing
                                   else 'metadata_incomplete'),
        'metadata_complete': not missing,
        'missing_metadata_fields': missing,
        'result_group_type': ('snapshot' if not missing else 'incomplete_snapshot'),
    }


def build_saved_lead_lag_payload(db_path, snapshot_id=None, pair_code=None, limit=20):
    """Return saved lead-lag snapshots, or rows for one selected snapshot."""
    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit = 20
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        if snapshot_id:
            rows = [dict(row) for row in conn.execute('''SELECT *
                FROM hong_kong_macro_lead_lag_results WHERE snapshot_id=?
                ORDER BY window_type,lag_months''', (snapshot_id,))]
            metadata = conn.execute('''SELECT * FROM hong_kong_macro_lead_lag_snapshots
                                      WHERE snapshot_id=?''', (snapshot_id,)).fetchone()
            metadata = dict(metadata) if metadata else None
            assessment = _snapshot_reproducibility(metadata)
            return {'success': True, 'snapshot_id': snapshot_id, 'rows': rows,
                    'n_rows': len(rows), 'metadata': metadata,
                    'metadata_status': ('available' if metadata else 'missing'),
                    **assessment}
        clauses, params = [], []
        if pair_code:
            clauses.append('pair_code=?')
            params.append(pair_code)
        where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
        snapshots = [dict(row) for row in conn.execute(f'''SELECT r.snapshot_id,
            r.pair_code,r.hk_indicator_code,r.mainland_indicator_code,r.transform,
            MIN(r.computed_at) AS computed_at,COUNT(*) AS n_rows,
            s.snapshot_id AS metadata_snapshot_id,
            s.hk_n_obs,s.mainland_n_obs,s.min_overlap,
            s.input_hash,s.hk_input_hash,s.mainland_input_hash,
            s.hk_start,s.hk_end,s.mainland_start,s.mainland_end,
            s.source_vintages_json,s.parameters_json,s.rolling_windows_json,
            s.parser_versions_json,s.computation_version,s.code_revision
            FROM hong_kong_macro_lead_lag_results r
            LEFT JOIN hong_kong_macro_lead_lag_snapshots s ON s.snapshot_id=r.snapshot_id
            {where.replace('pair_code=', 'r.pair_code=')}
            GROUP BY r.snapshot_id,r.pair_code,r.hk_indicator_code,r.mainland_indicator_code,r.transform,
                     s.snapshot_id,
                     s.hk_n_obs,s.mainland_n_obs,s.min_overlap,
                     s.input_hash,s.hk_input_hash,s.mainland_input_hash,
                     s.hk_start,s.hk_end,s.mainland_start,s.mainland_end,
                     s.source_vintages_json,s.parameters_json,s.rolling_windows_json,
                     s.parser_versions_json,s.computation_version,s.code_revision
            ORDER BY computed_at DESC LIMIT ?''', (*params, limit))]
    for snapshot in snapshots:
        snapshot.update(_snapshot_reproducibility(snapshot))
    return {
        'success': True, 'snapshots': snapshots, 'n_snapshots': len(snapshots),
        'reproducible_snapshot_count': sum(
            1 for item in snapshots
            if item['reproducibility_status'] == 'reproducible_snapshot'),
        'legacy_result_group_count': sum(
            1 for item in snapshots
            if item['reproducibility_status'] == 'legacy_unreproducible'),
        'metadata_incomplete_count': sum(
            1 for item in snapshots
            if item['reproducibility_status'] == 'metadata_incomplete'),
    }


GROUPS = [
    {'code': 'housing', 'title': '住房与交易',
     'description': 'RVD 价格/租金与销售，加上土地注册处登记的住宅买卖合约。',
     'charts': [
        {'code': 'housing_indices', 'title': '私人住宅价格与租金指数',
          'series': ['HK_RVD_PRICE_INDEX', 'HK_RVD_RENT_INDEX'], 'unit': 'index'},
         {'code': 'housing_indices_quarterly_history', 'title': 'RVD 价格/租金指数季度历史（1979 起）',
          'series': ['HK_RVD_PRICE_INDEX_QUARTERLY', 'HK_RVD_RENT_INDEX_QUARTERLY'], 'unit': 'index'},
         {'code': 'housing_indices_annual_history', 'title': 'RVD 价格/租金指数年度历史（1980 起）',
          'series': ['HK_RVD_PRICE_INDEX_ANNUAL', 'HK_RVD_RENT_INDEX_ANNUAL'], 'unit': 'index'},
         {'code': 'housing_sales', 'title': 'RVD 私人住宅一手/二手销售宗数',
          'series': ['HK_RVD_PRIMARY_SALES_COUNT', 'HK_RVD_SECONDARY_SALES_COUNT'], 'unit': 'agreements'},
         {'code': 'housing_registry', 'title': '土地注册处住宅注册买卖合约',
          'series': ['HK_LR_PRIMARY_SALES_COUNT', 'HK_LR_SECONDARY_SALES_COUNT'], 'unit': 'agreements'},
         {'code': 'housing_registry_value', 'title': '土地注册处住宅注册买卖合约金额',
          'series': ['HK_LR_PRIMARY_SALES_VALUE', 'HK_LR_SECONDARY_SALES_VALUE'], 'unit': 'HK$ million'},
         {'code': 'housing_stock', 'title': '私人住宅存量、完整年度落成与空置',
          'series': ['HK_RVD_STOCK', 'HK_RVD_COMPLETIONS', 'HK_RVD_VACANCY_UNITS'], 'unit': 'units'},
         {'code': 'housing_completions_ytd',
          'title': '私人住宅落成量（截至期暂定累计，不是全年）',
          'series': ['HK_RVD_COMPLETIONS_YTD'], 'unit': 'units'},
         {'code': 'housing_vacancy', 'title': '私人住宅空置率',
          'series': ['HK_RVD_VACANCY_RATE'], 'unit': '%'},
     ]},
    {'code': 'economy', 'title': '经济与就业',
     'description': 'HKMA 月度/季度统计与 CSD 年度汇总；季度数值只在官方季度月出现。',
     'charts': [
         {'code': 'economy_gdp', 'title': '名义与实质 GDP',
          'series': ['HK_HKMA_NOMINAL_GDP', 'HK_HKMA_REAL_GDP',
                     'HK_CSD_WEB_GDP_REAL_QUARTERLY'], 'unit': 'HK$ million'},
         {'code': 'economy_prices', 'title': '综合 CPI',
          'series': ['HK_HKMA_CPI_INDEX', 'HK_CSD_COMPOSITE_CPI_INDEX'], 'unit': 'index'},
         {'code': 'economy_labor', 'title': '失业率',
          'series': ['HK_HKMA_UNEMPLOYMENT_RATE', 'HK_CSD_UNEMPLOYMENT_RATE_ANNUAL'], 'unit': '%'},
         {'code': 'economy_annual_growth', 'title': '年度 GDP/CPI 同比',
          'series': ['HK_CSD_GDP_REAL_YOY_ANNUAL', 'HK_CSD_COMPOSITE_CPI_YOY_ANNUAL'], 'unit': '%'},
         {'code': 'economy_csd_retail', 'title': 'CSD 精选：零售销售总额',
          'series': ['HK_CSD_WEB_RETAIL_TOTAL_VALUE'], 'unit': 'HK$ million'},
         {'code': 'economy_csd_gdp', 'title': 'CSD 精选：按当时市价计算的 GDP',
          'series': ['HK_CSD_WEB_GDP_CURRENT_QUARTERLY'], 'unit': 'HK$ million'},
         {'code': 'economy_csd_consumption', 'title': 'CSD 精选：实质消费与固定资本形成',
          'series': ['HK_CSD_WEB_PRIVATE_CONSUMPTION_QUARTERLY',
                     'HK_CSD_WEB_FIXED_CAPITAL_FORMATION_QUARTERLY'], 'unit': 'HK$ million'},
         {'code': 'economy_csd_external', 'title': 'CSD 精选：经常账户',
          'series': ['HK_CSD_WEB_BOP_CURRENT_ACCOUNT_QUARTERLY'], 'unit': 'HK$ million'},
     ]},
    {'code': 're_export', 'title': '再出口贸易',
     'description': 'Trade-IDDS 月度货值；ttype=3 为 re-exports，未把 RVD 交易金额混入货物贸易。',
     'charts': [
         {'code': 'trade_composition', 'title': '进口、本地出口与转口',
          'series': ['HK_TRADE_IMPORTS', 'HK_TRADE_DOMESTIC_EXPORTS', 'HK_TRADE_RE_EXPORTS'], 'unit': "$'000"},
         {'code': 'trade_totals', 'title': '出口总额与商品贸易总额',
          'series': ['HK_TRADE_TOTAL_EXPORTS', 'HK_TRADE_TOTAL_TRADE'], 'unit': "$'000"},
         {'code': 'trade_balance', 'title': '商品贸易差额（派生）',
          'series': ['HK_TRADE_BALANCE'], 'unit': "$'000"},
         {'code': 'trade_reexport_share', 'title': '转口占整体出口比重（派生）',
          'series': ['HK_TRADE_RE_EXPORT_SHARE'], 'unit': '%'},
         {'code': 'trade_annual_yoy', 'title': 'CSD 出口总额年度同比',
          'series': ['HK_CSD_TOTAL_EXPORTS_YOY_ANNUAL'], 'unit': '%'},
     ]},
    {'code': 'reserves_finance', 'title': '储备与金融',
     'description': 'HKMA 外币储备资产、货币基础与货币供应；和中国 SAFE 储备资产完全分开。',
     'charts': [
         {'code': 'reserve_assets', 'title': '香港外币储备资产',
          'series': ['HK_HKMA_FC_RESERVE_ASSETS_EF', 'HK_HKMA_FC_RESERVE_ASSETS_LF',
                     'HK_HKMA_FC_RESERVE_ASSETS_TOTAL'], 'unit': 'US$ million'},
         {'code': 'unsettled_contracts', 'title': '未交收外汇合约',
          'series': ['HK_HKMA_UNSETTLED_FX_CONTRACTS_EF', 'HK_HKMA_UNSETTLED_FX_CONTRACTS_LF',
                     'HK_HKMA_UNSETTLED_FX_CONTRACTS_TOTAL'], 'unit': 'US$ million'},
         {'code': 'monetary', 'title': '货币基础、总结余与货币供应',
          'series': ['HK_HKMA_MONETARY_BASE', 'HK_HKMA_AGGREGATE_BALANCE',
                     'HK_HKMA_M1_TOTAL', 'HK_HKMA_M2_TOTAL', 'HK_HKMA_M3_TOTAL'],
          'unit': 'HK$ million'},
         {'code': 'market_rates', 'title': 'HIBOR 与政策利率',
          'series': ['HK_HKMA_HIBOR_OVERNIGHT', 'HK_HKMA_HIBOR_3M',
                     'HK_HKMA_BEST_LENDING_RATE', 'HK_HKMA_DISCOUNT_WINDOW_BASE_RATE'], 'unit': '%'},
         {'code': 'exchange_rate', 'title': '港元汇率与名义有效汇率',
          'series': ['HK_HKMA_EXRATE_HKD_USD', 'HK_HKMA_NEER_INDEX'], 'unit': 'index / HKD per USD'},
         {'code': 'banking_deposits', 'title': '银行客户存款（港元、外币与合计）',
          'series': ['HK_HKMA_BANKING_CUSTOMER_DEPOSITS_HKD',
                     'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_FC',
                     'HK_HKMA_BANKING_CUSTOMER_DEPOSITS_TOTAL'], 'unit': 'HK$ million'},
         {'code': 'rmb_deposits', 'title': '香港人民币存款',
          'series': ['HK_HKMA_RMB_DEPOSITS_DEMAND_SAVINGS',
                     'HK_HKMA_RMB_DEPOSITS_TIME', 'HK_HKMA_RMB_DEPOSITS_TOTAL'],
          'unit': 'RMB million yuan'},
         {'code': 'banking_loans', 'title': '贷款、贸易融资与按揭',
          'series': ['HK_HKMA_LOANS_TRADE_FINANCE_FROM_HK_TOTAL',
                     'HK_HKMA_LOANS_IN_HK_TOTAL', 'HK_HKMA_BANKING_RESIDENTIAL_MORTGAGE_LOANS',
                     'HK_HKMA_BANKING_LOANS_TOTAL'], 'unit': 'HK$ million'},
         {'code': 'banking_quality', 'title': '银行资产与贷款质量',
          'series': ['HK_HKMA_BANKING_TOTAL_ASSETS', 'HK_HKMA_BANKING_CLASSIFIED_LOANS',
                     'HK_HKMA_BANKING_MORTGAGE_DELINQUENCY_RATIO'], 'unit': 'HK$ million / %'},
         {'code': 'mortgage_flow', 'title': '住宅按揭申请、批出与取用',
          'series': ['HK_HKMA_MORTGAGE_NEW_APPLICATIONS',
                     'HK_HKMA_MORTGAGE_NEW_APPROVED_AMT',
                     'HK_HKMA_MORTGAGE_NEW_DRAWN_AMT'], 'unit': 'count / HK$ million'},
         {'code': 'mortgage_quality', 'title': '住宅按揭质量与新批利率',
          'series': ['HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_3M',
                     'HK_HKMA_MORTGAGE_DELINQUENCY_RATIO_6M',
                     'HK_HKMA_MORTGAGE_RESCHEDULED_RATIO',
                     'HK_HKMA_MORTGAGE_RATE_HIBOR',
                     'HK_HKMA_MORTGAGE_RATE_BLR'], 'unit': '%'},
         {'code': 'negative_equity', 'title': '负资产住宅按揭（季度）',
          'series': ['HK_HKMA_NEGATIVE_EQUITY_LOANS_COUNT',
                     'HK_HKMA_NEGATIVE_EQUITY_LOANS_AMT',
                     'HK_HKMA_NEGATIVE_EQUITY_UNSECURED_AMT'], 'unit': 'count / HK$ million'},
     ]},
    {'code': 'china_linkage', 'title': '中国联动（描述性）',
     'description': '统一月份后的相关曲线；正滞后表示香港领先，不代表因果关系。',
     'charts': []},
]

CARD_INDICATOR_CODES = (
    'HK_RVD_PRICE_INDEX', 'HK_HKMA_CPI_INDEX', 'HK_TRADE_RE_EXPORTS',
    'HK_HKMA_FC_RESERVE_ASSETS_TOTAL', 'HK_HKMA_UNEMPLOYMENT_RATE',
    'HK_LR_TOTAL_SALES_COUNT',
)


def _overview_indicator_codes():
    codes = set(CARD_INDICATOR_CODES)
    for group in GROUPS:
        if group['code'] == 'china_linkage' or not group.get('charts'):
            continue
        codes.update(group['charts'][0].get('series') or ())
    return codes


def _coverage(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row['indicator_code'], []).append(row)
    output = []
    for code, values in grouped.items():
        values = sorted(values, key=lambda row: _period_sort_key(row.get('period'), row.get('frequency')))
        meta = _meta(code)
        output.append({'code': code, 'name': meta['name'], 'unit': meta['unit'],
                       'frequency': meta['frequency'], 'category': meta['category'],
                       'status': meta['status'],
                       'n_obs': len(values), 'start_period': values[0]['period'],
                       'end_period': values[-1]['period'],
                       'latest_status': values[-1].get('data_status'),
                       'source_id': values[-1].get('source_id'),
                       'source_url': values[-1].get('source_url')})
    return sorted(output, key=lambda item: item['code'])


def _source_freshness_detail(source):
    """Classify freshness and retain the reason used for the classification."""
    if source.get('status') not in ('success', 'partial'):
        freshness = ('source_failed_using_cached_data'
                     if source.get('latest_reference_period') else 'no_observation')
        return {'freshness': freshness,
                'freshness_status': freshness,
                'freshness_reason': ('Source failed/blocked; cached observations retained.'
                                     if freshness != 'no_observation' else 'No successful observation.')}
    period = source.get('latest_reference_period')
    if not period:
        return {'freshness': 'no_observation', 'freshness_status': 'no_observation',
                'freshness_reason': 'No active observation.'}
    current_key = datetime.now().year * 12 + datetime.now().month - 1
    source_key = _period_sort_key(period, source.get('frequency') or 'unknown')
    frequency = source.get('frequency') or 'unknown'
    period_text = str(period).upper()
    if frequency == 'annual':
        threshold = 24
    elif frequency == 'semiannual':
        threshold = 15
    elif frequency == 'monthly':
        threshold = 2
    elif frequency == 'quarterly':
        threshold = 9
    elif '-Q' in period_text:
        threshold = 9
    elif '-H' in period_text:
        threshold = 15
    elif re.fullmatch(r'(?:19|20)\d{2}-\d{2}', period_text):
        threshold = 2
    else:
        threshold = 24
    freshness = 'stale' if current_key - source_key > threshold else 'current'
    release_note = ('Release date was not provided by the official source; '
                    'classification uses the latest reference period.')
    reason = release_note + f' Latest reference period={period}; threshold={threshold} months.'
    return {'freshness': freshness, 'freshness_status': freshness,
            'freshness_reason': reason,
            'release_date_not_provided': bool(source.get('release_date_not_provided', 1))}


def _source_freshness(source):
    return _source_freshness_detail(source).get('freshness', 'unknown')


def _query_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _query_values(query, *names):
    values = []
    for name in names:
        value = query.get(name) if isinstance(query, dict) else None
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            parts = value
        else:
            parts = str(value).split(',')
        values.extend(str(item).strip() for item in parts if str(item).strip())
    return list(dict.fromkeys(values))


def _parse_dimension_filters(query):
    """Parse explicit CSD dimension filters without inventing dimensions.

    Accepted forms are ``dimension=KEY:VALUE``, ``dimension=KEY=VALUE``,
    ``dimension_key=KEY&dimension_value=VALUE`` and a JSON object supplied as
    ``dimensions``.  Values are compared against both the official code and
    its ``Desc`` label after the stored JSON is parsed.
    """
    raw_values = []
    for name in ('dimension', 'dimensions'):
        value = query.get(name) if isinstance(query, dict) else None
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            raw_values.extend(str(item).strip() for item in value if str(item).strip())
        else:
            text = str(value).strip()
            if text.startswith('{') and text.endswith('}'):
                raw_values.append(text)
            else:
                raw_values.extend(item.strip() for item in text.split(',') if item.strip())
    key_values = []
    explicit_key = str(query.get('dimension_key') or '').strip() if isinstance(query, dict) else ''
    explicit_value = str(query.get('dimension_value') or '').strip() if isinstance(query, dict) else ''
    if explicit_key:
        key_values.append((explicit_key, explicit_value))
    for raw in raw_values:
        if raw.startswith('{') and raw.endswith('}'):
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                key_values.extend((str(key), str(value)) for key, value in parsed.items())
                continue
        separator = ':' if ':' in raw else '=' if '=' in raw else None
        if separator:
            key, value = raw.split(separator, 1)
            if key.strip():
                key_values.append((key.strip(), value.strip()))
    return list(dict.fromkeys(key_values))


def _matches_dimension_filters(row, filters):
    if not filters:
        return True
    try:
        dimensions = json.loads(row.get('dimension_json') or '{}')
    except (TypeError, ValueError):
        return False
    if not isinstance(dimensions, dict):
        return False
    for key, expected in filters:
        actual = dimensions.get(key)
        described = dimensions.get(f'{key}Desc')
        if str(actual).strip() != str(expected).strip() and str(described).strip() != str(expected).strip():
            return False
    return True


def _group_indicator_codes(group):
    all_codes = set(INDICATORS) | set(CSD_CURATED_MAPPINGS)
    if not group:
        return all_codes
    if group not in {item['code'] for item in GROUPS}:
        raise ValueError(f'未知香港宏观 group: {group}')
    codes = set()
    for item in GROUPS:
        if item['code'] != group:
            continue
        for chart in item.get('charts', []):
            codes.update(chart.get('series', []))
    if group == 'china_linkage':
        return set()
    return codes or {code for code, meta in INDICATORS.items()
                     if meta[3] == group} | {
                         code for code, meta in CSD_CURATED_MAPPINGS.items()
                         if meta['category'] == group}


def _transform_rows(rows, transform, base_period=None):
    """Apply a declared within-frequency transform without filling gaps."""
    transform = (transform or 'level').lower()
    if transform in ('none', ''):
        transform = 'level'
    if not rows:
        return []
    frequency = rows[0].get('frequency') or 'monthly'
    code = rows[0].get('indicator_code')
    allowed = _allowed_transforms(code) if code else INDICATOR_TRANSFORMS.get(
        frequency, ('level',))
    if transform not in allowed:
        raise ValueError(f'{code or frequency} 序列不支持 transform={transform}; allowed={allowed}')
    periods_per_year = {'monthly': 12, 'quarterly': 4,
                        'semiannual': 2, 'annual': 1}.get(frequency, 1)
    step_months = _period_step_months(frequency)
    sorted_rows = sorted(rows, key=lambda row: _period_sort_key(row.get('period'), frequency))
    values = {_period_sort_key(row.get('period'), frequency): row.get('value')
              for row in sorted_rows if row.get('value') is not None}
    if transform == 'index100' and base_period:
        base_key = _period_sort_key(base_period, frequency)
        if base_key not in values:
            raise ValueError(f'base_period={base_period} 不在序列覆盖范围内')
        first_value = values[base_key]
    else:
        first_value = next(iter(values.values()), None)
    output = []
    for row in sorted_rows:
        current_key = _period_sort_key(row.get('period'), frequency)
        raw_value = row.get('value')
        value = raw_value
        formula = 'level: official/source-native value'
        if raw_value is not None and transform != 'level':
            if transform in ('difference', 'diff'):
                previous_key = current_key - step_months
                previous = values.get(previous_key)
                value = raw_value - previous if previous is not None else None
                formula = (f'difference: x[t]-x[t-{step_months} calendar months]; '
                           'missing adjacent source period remains null')
            elif transform in ('mom', 'qoq'):
                previous_key = current_key - step_months
                previous = values.get(previous_key)
                value = (((raw_value / previous) - 1.0) * 100.0
                         if previous not in (None, 0) else None)
                formula = (f'{transform}: (x[t]/x[t-{step_months} calendar months]-1)*100; '
                           'adjacent source period only; zero denominator remains null')
            elif transform in ('yoy', 'pct_change_12'):
                previous = values.get(current_key - 12)
                value = ((raw_value / previous) - 1.0) * 100.0 \
                    if previous not in (None, 0) else None
                formula = 'yoy: (x[t]/x[t-12 calendar months]-1)*100; no interpolation'
            elif transform == 'rolling_12m':
                offsets = [step_months * offset for offset in range(periods_per_year)]
                window = [values.get(current_key - offset) for offset in offsets]
                if len(window) == periods_per_year and all(item is not None for item in window):
                    if any(token in str(code or '').upper() for token in _FLOW_CODE_HINTS):
                        value = sum(window)
                        formula = f'rolling_12m: sum of {periods_per_year} source periods; incomplete window remains missing'
                    else:
                        value = sum(window) / periods_per_year
                        formula = f'rolling_12m: mean of {periods_per_year} source periods; incomplete window remains missing'
                else:
                    value = None
            elif transform == 'index100':
                value = (raw_value / first_value * 100.0
                         if first_value not in (None, 0) else None)
                formula = 'index100: x[t]/first non-missing x*100'
        item = dict(row)
        item['raw_value'] = raw_value
        item['value'] = value
        item['transformation'] = transform
        item['formula'] = formula
        if transform in ('mom', 'qoq', 'yoy', 'pct_change_12'):
            item['unit'] = '%'
        if raw_value is not None and transform != 'level' and value is None:
            if transform in ('mom', 'qoq', 'yoy', 'pct_change_12'):
                lag = 12 if transform in ('yoy', 'pct_change_12') else step_months
                predecessor = values.get(current_key - lag)
                item['missing_reason'] = ('zero_denominator' if predecessor == 0
                                          else 'adjacent_period_missing')
            elif transform in ('difference', 'diff'):
                item['missing_reason'] = 'adjacent_period_missing'
        output.append(item)
    return output


def _load_hk_query_rows(conn, query=None):
    query = query or {}
    group = str(query.get('group') or '').strip()
    start = parse_period_bound(query.get('start')) if query.get('start') else None
    end = parse_period_bound(query.get('end')) if query.get('end') else None
    if start and end and _period_sort_key(start) > _period_sort_key(end):
        raise ValueError('start 不能晚于 end')
    requested = _query_values(query, 'indicator', 'indicators')
    known_codes = (set(INDICATORS) | set(CSD_CURATED_MAPPINGS) |
                   set(DEPRECATED_CSD_CURATED_MAPPINGS))
    unknown = sorted(set(requested) - known_codes)
    if unknown:
        raise ValueError(f'未知香港宏观 indicator: {", ".join(unknown)}')
    if len(requested) > 50:
        raise ValueError('indicator 一次最多请求 50 个序列')
    codes = set(requested) if requested else _group_indicator_codes(group)
    if not requested and not group:
        codes = (_overview_indicator_codes()
                 if _query_bool(query.get('dashboard')) else known_codes)
    if group == 'china_linkage' and not requested:
        # The linkage tab needs the eligible Hong Kong candidates to populate
        # its selector and to report n_obs.  Mainland inputs stay in the
        # separate lead-lag endpoint; this branch only narrows the HK side.
        codes = {code for code in INDICATORS
                 if _meta(code).get('eligible_for_lead_lag')}
    source_ids = _query_values(query, 'source', 'source_id')
    unknown_sources = sorted(set(source_ids) - set(SOURCE_CATALOG))
    if unknown_sources:
        raise ValueError(f'未知香港宏观 source: {", ".join(unknown_sources)}')
    frequencies = _query_values(query, 'frequency', 'freq')
    statuses = _query_values(query, 'status', 'data_status')
    include_superseded = _query_bool(query.get('include_superseded'))
    include_missing = _query_bool(query.get('include_missing'))
    base = str(query.get('base') or 'all').strip().lower()
    base_period = parse_period_bound(query.get('base_period')) if query.get('base_period') else None
    transform = str(query.get('transform') or 'level').strip().lower()
    if transform in ('none', ''):
        transform = 'level'
    if base not in ('all', 'official', 'derived', 'raw'):
        raise ValueError('base must be all, official, derived, or raw')
    if base == 'official':
        statuses = statuses or ['official', 'official_revised']
    elif base == 'derived':
        statuses = statuses or ['derived']
    unsupported = []
    for code in codes:
        frequency = _meta(code).get('frequency')
        if transform not in _allowed_transforms(code):
            unsupported.append(f'{code} ({frequency})')
    if unsupported:
        raise ValueError(f'transform={transform} 不适用于: {", ".join(sorted(unsupported))}')
    # SQL narrows the candidate set first. Calendar-aware mixed-frequency
    # bounds are applied below with _period_sort_key so Q/H/Y are not coerced.
    clauses, params = [], []
    main_codes = set(codes) & set(INDICATORS)
    if main_codes:
        placeholders = ','.join('?' for _ in main_codes)
        clauses.append(f'indicator_code IN ({placeholders})')
        params.extend(sorted(main_codes))
    if source_ids:
        placeholders = ','.join('?' for _ in source_ids)
        clauses.append(f'source_id IN ({placeholders})')
        params.extend(source_ids)
    if frequencies:
        placeholders = ','.join('?' for _ in frequencies)
        clauses.append(f'frequency IN ({placeholders})')
        params.extend(frequencies)
    if statuses:
        placeholders = ','.join('?' for _ in statuses)
        clauses.append(f'data_status IN ({placeholders})')
        params.extend(statuses)
    elif not include_superseded:
        clauses.append("COALESCE(data_status,'') <> 'superseded'")
    if not include_missing:
        clauses.append('value IS NOT NULL')
    where = ' AND '.join(clauses) if clauses else '1=1'
    rows = [dict(row) for row in conn.execute(
        'SELECT * FROM hong_kong_macro_observations WHERE ' + where,
        params)] if main_codes else []
    # CSD Web Table curated mappings are real source observations exposed in
    # the main API through a stable project code.  They stay in their own
    # storage table and are joined only when requested by this query.
    for code in sorted(set(codes) & set(CSD_CURATED_MAPPINGS)):
        mapping = CSD_CURATED_MAPPINGS[code]
        csd_clauses = ['table_id=?', 'series_code=?']
        csd_params = [mapping['table_id'], mapping['series_code']]
        if source_ids:
            if f"HK_CSD_WEB_{mapping['table_id']}" not in source_ids:
                continue
        if frequencies:
            if mapping['frequency'] not in frequencies:
                continue
            csd_clauses.append('frequency IN (' + ','.join('?' for _ in frequencies) + ')')
            csd_params.extend(frequencies)
        if statuses:
            csd_clauses.append('data_status IN (' + ','.join('?' for _ in statuses) + ')')
            csd_params.extend(statuses)
        elif not include_superseded:
            csd_clauses.append("COALESCE(data_status,'') <> 'superseded'")
        if not include_missing:
            csd_clauses.append('value IS NOT NULL')
        csd_rows = [dict(item) for item in conn.execute(
            'SELECT * FROM hong_kong_macro_web_table_observations WHERE ' +
            ' AND '.join(csd_clauses) + ' ORDER BY period', csd_params)]
        meta = _meta(code)
        source = conn.execute('''SELECT latest_release_date FROM hong_kong_macro_sources
                                 WHERE source_id=?''', (meta['source_id'],)).fetchone()
        release_date = source['latest_release_date'] if source else None
        for item in csd_rows:
            item['indicator_code'] = code
            item['jurisdiction'] = 'HK'
            item['category'] = meta['category']
            item['subcategory'] = meta['source_id']
            item['period_label'] = item.get('period')
            item['currency'] = 'HKD' if 'HK$' in (item.get('unit') or meta['unit']) else None
            item['seasonal_adjustment'] = None
            item['price_basis'] = None
            item['transformation'] = None
            item['dimension_key'] = ''
            item['dimension_value'] = ''
            item['data_status'] = item.get('data_status') or 'official'
            item['source_id'] = meta['source_id']
            item['source_url'] = item.get('source_url') or meta['source_url']
            item['source_table'] = item.get('source_table') or 'dataset'
            item['release_date'] = release_date
            item['vintage_date'] = ''
            item['note'] = mapping['note']
            item['formula'] = None
        rows.extend(csd_rows)
    start_key = _period_sort_key(start) if start else None
    end_key = _period_sort_key(end) if end else None
    if start_key is not None or end_key is not None:
        rows = [row for row in rows
                if (start_key is None or _period_sort_key(row.get('period'), row.get('frequency')) >= start_key)
                and (end_key is None or _period_sort_key(row.get('period'), row.get('frequency')) <= end_key)]
    return rows, {'group': group or None, 'start': start, 'end': end,
                  'indicators': sorted(codes), 'source': source_ids,
                  'frequency': frequencies,
                  'status': statuses or (['active'] if not include_superseded else ['all']),
                  'base': base, 'include_superseded': include_superseded,
                  'include_missing': include_missing, 'transform': transform,
                  'base_period': base_period,
                  'dashboard': _query_bool(query.get('dashboard'))}


def build_hong_kong_macro_payload(db_path, query=None):
    query = query or {}
    group = str(query.get('group') or '').strip()
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        raw_rows, filters = _load_hk_query_rows(conn, query)
        requested = _query_values(query, 'indicator', 'indicators')
        overview = bool(filters.get('dashboard') and not group and not requested)
        include_trade_catalog = overview or group == 're_export'
        include_csd_catalog = overview or group == 'economy'
        relevant_source_ids = sorted({
            _meta(code).get('source_id') for code in filters.get('indicators') or ()
            if _meta(code).get('source_id')
        })
        if overview or not relevant_source_ids:
            source_rows = conn.execute(
                'SELECT * FROM hong_kong_macro_sources ORDER BY source_id')
        else:
            source_rows = conn.execute(
                'SELECT * FROM hong_kong_macro_sources WHERE source_id IN ({}) '
                'ORDER BY source_id'.format(','.join('?' for _ in relevant_source_ids)),
                relevant_source_ids)
        sources = [dict(row) for row in source_rows]
        for source in sources:
            source.update(_source_freshness_detail(source))
        trade_dimensions = []
        if include_trade_catalog:
            latest_trade_rows = [dict(row) for row in conn.execute('''SELECT d.source_id,
                d.dimension_type,d.trade_type,d.period,d.dimension_code,d.dimension_label,
                d.statistic,d.value,d.unit,d.data_status,d.source_url,d.source_table,d.note
                FROM hong_kong_macro_trade_dimensions d
                JOIN (SELECT dimension_type,MAX(period) AS period
                      FROM hong_kong_macro_trade_dimensions
                      WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded'
                      GROUP BY dimension_type) latest
                  ON latest.dimension_type=d.dimension_type AND latest.period=d.period
                WHERE d.value IS NOT NULL AND COALESCE(d.data_status,'') <> 'superseded'
                ORDER BY d.dimension_type,d.value DESC,d.dimension_code''')]
            by_dimension_type = {}
            for row in latest_trade_rows:
                by_dimension_type.setdefault(row['dimension_type'], []).append(row)
            for dimension_type, values in sorted(by_dimension_type.items()):
                limit = 20 if dimension_type in {
                    'origin_top', 'destination_top', 'commodity_sitc2'} else None
                trade_dimensions.extend(values[:limit] if limit else values)
        trade_dimension_summary = ([dict(row) for row in conn.execute('''SELECT dimension_type,
            COUNT(*) AS n_obs,MIN(period) AS start_period,MAX(period) AS end_period,
            COUNT(DISTINCT dimension_code) AS n_dimensions
            FROM hong_kong_macro_trade_dimensions WHERE value IS NOT NULL
            GROUP BY dimension_type ORDER BY dimension_type''')]
                                   if include_trade_catalog else [])
        web_table_summary = ([dict(row) for row in conn.execute('''SELECT table_id,
            COUNT(*) AS n_obs,COUNT(DISTINCT series_code) AS n_series,
            MIN(period) AS start_period,MAX(period) AS end_period
            FROM hong_kong_macro_web_table_observations
            WHERE value IS NOT NULL AND COALESCE(data_status, '') <> 'superseded'
            GROUP BY table_id ORDER BY table_id''')]
                             if include_csd_catalog else [])
        database_active_observation_count = sum(
            conn.execute(f'''SELECT COUNT(*) FROM {table_name}
                WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone()[0]
            for table_name in (
                'hong_kong_macro_observations',
                'hong_kong_macro_web_table_observations',
                'hong_kong_macro_trade_dimensions'))
        # Full CSD history is intentionally not embedded in the main payload;
        # the dedicated endpoint below applies the same bounded-query rule.
    series = {}
    for row in raw_rows:
        series.setdefault(row['indicator_code'], []).append(row)
    for code in series:
        series[code].sort(key=lambda row: _period_sort_key(row.get('period'), row.get('frequency')))
    metric_codes = set(filters.get('indicators') or ())
    metrics = {code: _meta(code) for code in metric_codes}
    transform = str(query.get('transform') or 'level').lower()
    transformed_series = {}
    for code, values in series.items():
        transformed_series[code] = _transform_rows(values, transform, filters.get('base_period'))
    filtered_series_counts = {code: len(values)
                              for code, values in transformed_series.items()}
    # The browser dashboard must not serialize the entire research history on
    # its first paint. Explicit API/CSV filters remain lossless; dashboard=1
    # is only a bounded presentation view and never changes stored data.
    dashboard_preview = bool(filters.get('dashboard'))
    series_limit_per_indicator = 60 if dashboard_preview else None
    if dashboard_preview:
        # Six years is enough for a first visual orientation; explicit
        # indicator/date requests remain the lossless research path.
        transformed_series = {code: values[-60:]
                              for code, values in transformed_series.items()}
    plotted_observation_count = sum(len(values) for values in transformed_series.values())
    truncated_series = sorted(
        code for code, count in filtered_series_counts.items()
        if series_limit_per_indicator is not None and count > series_limit_per_indicator)
    source_by_id = {row['source_id']: row for row in sources}
    for code, meta in metrics.items():
        values = [row for row in raw_rows
                  if row.get('indicator_code') == code and row.get('value') is not None]
        latest = max(values, key=lambda row: _period_sort_key(
            row.get('period'), row.get('frequency')), default={})
        source = source_by_id.get(meta.get('source_id'), {})
        meta.update({
            'name_zh': meta.get('name'), 'name_en': None,
            'description': meta.get('status_note') or meta.get('name'),
            'n_obs': len(values),
            'first_period': min((row.get('period') for row in values),
                                key=lambda item: _period_sort_key(item), default=None),
            'last_period': max((row.get('period') for row in values),
                               key=lambda item: _period_sort_key(item), default=None),
            'latest_status': latest.get('data_status'),
            'source_name': source.get('institution'),
            'source_table': latest.get('source_table') or source.get('dataset_name'),
            'latest_release_date': source.get('latest_release_date'),
            'page_last_updated_date': source.get('page_last_updated_date'),
            'release_metadata_status': source.get('release_metadata_status'),
            'release_metadata_reason': source.get('release_metadata_reason'),
            'expected_release_lag_days': source.get('expected_release_lag_days'),
            'expected_release_lag_status': source.get('expected_release_lag_status'),
            'expected_release_lag_reason': source.get('expected_release_lag_reason'),
            'retrieved_at': latest.get('retrieved_at') or source.get('last_success_at'),
            'source_status': source.get('status'),
            'freshness': source.get('freshness'),
            'freshness_status': source.get('freshness_status'),
            'freshness_reason': source.get('freshness_reason'),
            'expected_frequency': source.get('expected_frequency') or meta.get('frequency'),
            'release_date_not_provided': bool(source.get('release_date_not_provided', 1)),
            'original_or_derived': 'derived' if any(
                row.get('data_status') == 'derived' for row in values) else 'original',
            'derived': any(row.get('data_status') == 'derived' for row in values),
            'formula': latest.get('formula'),
            'currency': ('HKD' if 'HK$' in str(meta.get('unit')) else
                         'USD' if 'US$' in str(meta.get('unit')) else None),
        })
        meta['supported_transforms'] = list(meta.get('allowed_transforms') or ('level',))
        if meta.get('eligible_for_lead_lag'):
            if meta.get('frequency') != 'monthly':
                meta['eligible_for_lead_lag'] = False
                meta['ineligible_reason'] = 'lead-lag 只接受月度香港序列'
            elif len(values) < 60:
                meta['eligible_for_lead_lag'] = False
                meta['ineligible_reason'] = '有效观测少于最低 60 个月样本门槛'
        elif meta.get('status') != 'available':
            meta['ineligible_reason'] = meta.get('status_note') or '来源字段不可用'
        elif meta.get('frequency') != 'monthly':
            meta['ineligible_reason'] = 'lead-lag 只接受月度香港序列'
        else:
            meta['ineligible_reason'] = '有效观测不足最低 60 个月样本门槛'
    public_series = {code: [
        {'period': row['period'], **_period_bounds(row.get('period'), row.get('frequency')),
         'value': row['value'], 'raw_value': row.get('raw_value'),
         'unit': row.get('unit'), 'frequency': row.get('frequency'),
         'name_zh': metrics[code].get('name_zh'), 'name_en': metrics[code].get('name_en'),
         'transformation': row.get('transformation') or 'level',
         'formula': row.get('formula'), 'data_status': row['data_status'],
         'source_id': row['source_id'], 'source_url': row['source_url'],
         'source_table': row.get('source_table'),
         'currency': row.get('currency') or metrics[code].get('currency'),
         'seasonal_adjustment': row.get('seasonal_adjustment') or 'not_provided',
         'price_basis': row.get('price_basis') or metrics[code].get('price_basis'),
         'derived': row.get('data_status') == 'derived',
         'original_or_derived': ('derived' if row.get('data_status') == 'derived' else 'original'),
         'release_date': row.get('release_date'), 'retrieved_at': row.get('retrieved_at'),
         'vintage_date': row.get('vintage_date'), 'missing_reason': row.get('missing_reason'),
         'source_period_end': row.get('source_period_end'),
         'raw_sha256': row.get('raw_sha256'), 'parser_version': row.get('parser_version'),
         'period_raw': row.get('period_raw'), 'statistic': row.get('statistic'),
         'construct_label': row.get('construct_label'),
         'dimension_key': row.get('dimension_key') or '',
         'dimension_value': row.get('dimension_value') or ''}
        for row in values] for code, values in transformed_series.items()}
    if dashboard_preview:
        # Keep the dashboard's repeated row metadata compact while retaining
        # the fields needed for tooltips and audit hand-off. Lossless history
        # stays available through explicit indicator/date API or CSV queries.
        dashboard_fields = ('period', 'period_start', 'period_end', 'value',
                            'raw_value', 'unit', 'frequency', 'data_status',
                            'source_id', 'source_url', 'release_date',
                            'retrieved_at', 'source_period_end')
        public_series = {
            code: [{field: row.get(field) for field in dashboard_fields}
                   for row in values]
            for code, values in public_series.items()
        }
    cards = []
    for code in CARD_INDICATOR_CODES:
        if code not in metrics:
            continue
        values = series.get(code) or []
        meta = metrics[code]
        latest = max(values, key=lambda row: _period_sort_key(row.get('period'), row.get('frequency')), default={})
        cards.append({'code': code, 'label': meta['name'], 'value': latest.get('value'),
                      'period': latest.get('period'), 'unit': meta['unit'],
                      'frequency': meta['frequency'], 'data_status': latest.get('data_status', 'missing'),
                      'source_id': latest.get('source_id'), 'source_url': latest.get('source_url'),
                      'source_period_end': latest.get('source_period_end'),
                      'release_date': latest.get('release_date'),
                      'release_date_not_provided': meta.get('release_date_not_provided'),
                      'source_page_last_updated_date': meta.get('page_last_updated_date'),
                      'retrieved_at': latest.get('retrieved_at'),
                      'status': meta['status']})
    # SAFE remains a China-level series in china_macro_observations. Expose a
    # clearly labelled reference card only; do not merge it into HK metrics or
    # the HK source registry.
    requested_hk = _query_values(query, 'indicator', 'indicators')
    has_hk_scope = bool(requested_hk or group or
                        any(str(query.get(key) or '').strip()
                            for key in ('start', 'end', 'frequency', 'freq',
                                        'source', 'source_id')))
    try:
        with closing(_connect_readonly(db_path)) as safe_conn:
            safe_row = safe_conn.execute('''SELECT indicator_code,indicator_name,period,value,unit,
                data_status,source_name,source_url,release_date,retrieved_at,raw_sha256,
                parser_version,missing_reason,source_page_created_date,
                source_page_last_updated_date,release_date_not_provided,
                release_date_reason
                FROM china_macro_observations
                WHERE indicator_code='CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD'
                  AND value IS NOT NULL
                ORDER BY period DESC LIMIT 1''').fetchone()
    except sqlite3.OperationalError:
        safe_row = None
    if safe_row and not has_hk_scope:
        safe_row = dict(safe_row)
        cards.append({'code': safe_row['indicator_code'],
                      'label': '中国 SAFE 官方储备资产合计（联动参考）',
                      'value': safe_row['value'], 'period': safe_row['period'],
                      'unit': safe_row['unit'], 'frequency': 'monthly',
                      'data_status': safe_row['data_status'],
                      'source_id': safe_row['indicator_code'],
                      'source_name': safe_row['source_name'],
                      'source_url': safe_row['source_url'],
                      'release_date': safe_row['release_date'],
                      'source_page_created_date': safe_row['source_page_created_date'],
                      'source_page_last_updated_date': safe_row['source_page_last_updated_date'],
                      'release_date_not_provided': bool(safe_row['release_date_not_provided']),
                      'release_date_reason': safe_row['release_date_reason'],
                      'retrieved_at': safe_row['retrieved_at'],
                      'raw_sha256': safe_row['raw_sha256'],
                      'parser_version': safe_row['parser_version'],
                      'missing_reason': safe_row['missing_reason'],
                      'derived': False,
                      'freshness': 'release_date_not_provided' if not safe_row['release_date'] else 'reference'})
    updated = [row.get('retrieved_at') for row in raw_rows if row.get('retrieved_at')]
    failed_sources = [row for row in sources if row.get('status') in ('blocked', 'failed', 'partial')]
    missing_sources = [row for row in sources if row.get('status') == 'not_attempted']
    stale_sources = [row for row in sources if row.get('freshness') == 'stale']
    status = 'empty' if not raw_rows else (
        'partial' if failed_sources or missing_sources else
        ('stale' if stale_sources else 'ok'))
    latest_reference_period_by_frequency = {}
    for row in raw_rows:
        freq = row.get('frequency') or 'unknown'
        if row.get('period') and (freq not in latest_reference_period_by_frequency or
                                  _period_sort_key(row['period'], freq) > _period_sort_key(
                                      latest_reference_period_by_frequency[freq], freq)):
            latest_reference_period_by_frequency[freq] = row['period']
    latest_reference_period = max((row['period'] for row in raw_rows if row.get('period')),
                                  key=lambda item: _period_sort_key(item), default=None)
    eligible_catalog = []
    for code in sorted(metrics):
        meta = metrics[code]
        values = [row for row in raw_rows if row.get('indicator_code') == code and row.get('value') is not None]
        eligible_catalog.append(dict(meta, n_obs=len(values),
                                     start_period=min((row['period'] for row in values),
                                                       key=lambda item: _period_sort_key(item), default=None),
                                     end_period=max((row['period'] for row in values),
                                                     key=lambda item: _period_sort_key(item), default=None)))
    return {
        'success': True, 'generated_at': datetime.now().isoformat(),
        'updated_at': max(updated) if updated else None, 'groups': GROUPS,
        'metrics': metrics, 'series': public_series, 'cards': cards,
        'coverage': _coverage(raw_rows), 'sources': sources,
        'filters': filters, 'indicator_catalog': eligible_catalog,
        'trade_dimensions': trade_dimensions,
        'trade_dimension_catalog': ([dict(item, request_key=key)
                                     for key, item in TRADE_DIMENSION_REQUESTS.items()]
                                    if include_trade_catalog else []),
        'trade_dimension_summary': trade_dimension_summary,
        'csd_web_table_catalog': ([dict(item, table_id=table_id,
                                        source_id=f'HK_CSD_WEB_{table_id}')
                                  for table_id, item in CSD_WEB_TABLES.items()]
                                 if include_csd_catalog else []),
        'csd_web_table_summary': web_table_summary,
        'csd_web_table_preview': [],
        'csd_web_table_endpoint': '/api/hong-kong-macro/csd-web-table',
        'dashboard_preview': dashboard_preview,
        'meta': {
            'module': 'hong_kong_macro', 'jurisdiction': 'HK', 'title': '香港宏观',
            'positioning': '中国的对外窗口', 'generated_at': datetime.now().isoformat(),
            'latest_reference_period': latest_reference_period, 'status': status,
            'latest_reference_period_by_frequency': latest_reference_period_by_frequency,
            'latest_monthly_period': latest_reference_period_by_frequency.get('monthly'),
            'latest_quarterly_period': latest_reference_period_by_frequency.get('quarterly'),
            'latest_semiannual_period': latest_reference_period_by_frequency.get('semiannual'),
            'latest_annual_period': latest_reference_period_by_frequency.get('annual'),
            'series_count': len(public_series),
            'observation_count': len(raw_rows),
            'database_active_observation_count': database_active_observation_count,
            'filtered_observation_count': len(raw_rows),
            'plotted_observation_count': plotted_observation_count,
            'series_limit_per_indicator': series_limit_per_indicator,
            'truncated': bool(truncated_series),
            'truncated_series': truncated_series,
            'active_indicator_count': sum(1 for item in metrics.values()
                                          if item.get('n_obs', 0) > 0 and item.get('eligible_for_api')),
            'source_success_count': sum(1 for row in sources if row.get('status') == 'success'),
            'source_count': len(sources),
            'last_success_at': max((row.get('last_success_at') for row in sources
                                    if row.get('last_success_at')), default=None),
            'failed_sources': [row['source_id'] for row in failed_sources],
            'missing_sources': [row['source_id'] for row in missing_sources],
            'stale_sources': [row['source_id'] for row in stale_sources],
            'dashboard_preview': dashboard_preview,
        },
        'quality': {
            'warnings': [], 'missing': [row['source_id'] for row in missing_sources],
            'failed_sources': [row['source_id'] for row in failed_sources],
            'stale_sources': [row['source_id'] for row in stale_sources],
            'derived_trade_series': ['HK_TRADE_BALANCE', 'HK_TRADE_RE_EXPORT_SHARE'],
            'curated_csd_series': sorted(CSD_CURATED_MAPPINGS),
            'deprecated_csd_series': sorted(DEPRECATED_CSD_CURATED_MAPPINGS),
        },
        'warnings': [
            '香港是独立 jurisdiction；本页数据不写入中国城市经济模块。',
            'RVD/Land Registry 是物业交易/登记统计，不把注册月份直接解释为签约月份。',
            'HKMA 外币储备资产与中国 SAFE 官方储备资产是不同经济体、不同统计机构和不同口径。',
            'Trade-IDDS 的转口是货物贸易口径，不等于跨境资金流或房地产交易金额。',
            'CSD 110-01003 的 PG 是人口增长量（千人），不是香港人口存量；人口存量尚未接入。',
            'RVD 2026-H1 落成量是截至 2026-06-30 的暂定累计，不是 2026 全年值。',
            'lead-lag 只做月份对齐和描述性相关，不作因果、预测或结构模型结论。',
        ],
        'methodology': {
            'status_vocabulary': ['not_attempted', 'success', 'blocked', 'failed', 'partial',
                                  'ok', 'empty', 'stale', 'current',
                                  'official', 'official_revised', 'provisional',
                                  'derived', 'superseded', 'deprecated',
                                  'not_released', 'metadata_unknown', 'unavailable_at_source',
                                  'unsupported_field', 'source_failed_using_cached_data'],
            'missingness': '来源失败保留旧观测；缺失不插值、不跨频率补值、不以其他来源换算。',
            'sources': ['差饷物业估价署', '土地注册处', '香港金融管理局',
                        '香港政府统计处 Trade-IDDS', '香港政府统计处 CSD-IDDS'],
            'curated_csd_series': sorted(CSD_CURATED_MAPPINGS),
            'deprecated_csd_series': sorted(DEPRECATED_CSD_CURATED_MAPPINGS),
            'transform_semantics': {
                'difference': 'x[t]-x[t-1] in the source unit',
                'mom': '(x[t]/x[t-1]-1)*100 for adjacent monthly periods',
                'qoq': '(x[t]/x[t-1]-1)*100 for adjacent canonical quarters',
            },
        },
    }


def _build_indicator_catalog(conn):
    """Build the same complete catalog used by the API for debug audits."""
    catalog = []
    for code in sorted(set(INDICATORS) | set(CSD_CURATED_MAPPINGS) |
                       set(DEPRECATED_CSD_CURATED_MAPPINGS)):
        meta = dict(_meta(code))
        if code in INDICATORS:
            rows = [dict(row) for row in conn.execute('''SELECT period,value,data_status,
                    retrieved_at,source_table FROM hong_kong_macro_observations
                WHERE indicator_code=? AND value IS NOT NULL
                  AND COALESCE(data_status,'') <> 'superseded'
                  AND COALESCE(dimension_key,'')='' ''', (code,))]
        elif code in CSD_CURATED_MAPPINGS:
            mapping = CSD_CURATED_MAPPINGS[code]
            rows = [dict(row) for row in conn.execute('''SELECT period,value,data_status,
                    retrieved_at,source_table FROM hong_kong_macro_web_table_observations
                WHERE table_id=? AND series_code=? AND value IS NOT NULL
                  AND COALESCE(data_status,'') <> 'superseded' ''',
                                   (mapping['table_id'], mapping['series_code']))]
        else:
            rows = []
        rows.sort(key=lambda row: _period_sort_key(row.get('period'), meta.get('frequency')))
        source = conn.execute('SELECT * FROM hong_kong_macro_sources WHERE source_id=?',
                              (meta.get('source_id'),)).fetchone()
        source = dict(source) if source else {}
        meta.update({
            'n_obs': len(rows),
            'start_period': rows[0].get('period') if rows else None,
            'end_period': rows[-1].get('period') if rows else None,
            'first_period': rows[0].get('period') if rows else None,
            'last_period': rows[-1].get('period') if rows else None,
            'latest_status': rows[-1].get('data_status') if rows else None,
            'source_name': source.get('institution'),
            'source_table': (rows[-1].get('source_table') if rows else None) or source.get('dataset_name'),
            'latest_release_date': source.get('latest_release_date'),
            'retrieved_at': (rows[-1].get('retrieved_at') if rows else None) or source.get('last_success_at'),
            'source_status': source.get('status'),
            'source_freshness': source.get('freshness_status') or _source_freshness(source),
            'supported_transforms': list(_allowed_transforms(code)),
        })
        if code in INDICATORS:
            meta['eligible_for_lead_lag'] = bool(
                meta.get('frequency') == 'monthly' and meta.get('status') == 'available'
                and len(rows) >= 60)
        else:
            meta['eligible_for_lead_lag'] = False
        if not meta['eligible_for_lead_lag']:
            meta['ineligible_reason'] = (
                'CSD curated series is not a lead-lag input' if code in CSD_CURATED_MAPPINGS
                else ('source catalog status is not available' if meta.get('status') != 'available'
                      else ('frequency is not monthly' if meta.get('frequency') != 'monthly'
                            else '有效观测不足最低 60 个月样本门槛')))
        catalog.append(meta)
    return catalog


def _identity_check(conn, name, table, code_map, expression, *,
                    absolute_tolerance, warning_tolerance=None,
                    relative_tolerance=None, unit='', rounding_note='',
                    source_or_derived='mixed'):
    """Check an accounting identity with declared, source-specific tolerances."""
    warning_tolerance = (absolute_tolerance if warning_tolerance is None
                         else warning_tolerance)
    tolerance = {
        'absolute_pass': float(absolute_tolerance),
        'absolute_warning_max': float(warning_tolerance),
        'relative_pass': relative_tolerance,
        'unit': unit,
        'rounding_note': rounding_note,
    }
    try:
        rows = conn.execute(
            f'''SELECT period,indicator_code,value FROM {table}
                WHERE indicator_code IN ({','.join('?' for _ in code_map.values())})
                  AND value IS NOT NULL
                  AND COALESCE(data_status,'') <> 'superseded' ''',
            tuple(code_map.values())).fetchall()
    except sqlite3.OperationalError:
        return {'name': name, 'status': 'table_unavailable', 'checked_periods': 0,
                'missing_periods': 0, 'max_abs_residual': None,
                'max_relative_residual': None, 'tolerance': tolerance,
                'offending_periods': [], 'source_or_derived': source_or_derived}
    by_period = {}
    aliases = {actual: alias for alias, actual in code_map.items()}
    for row in rows:
        alias = aliases.get(row['indicator_code'])
        if alias:
            by_period.setdefault(row['period'], {})[alias] = float(row['value'])
    residuals = []
    missing_periods = []
    offending = []
    for period, values in sorted(by_period.items()):
        if not all(alias in values for alias in code_map):
            missing_periods.append({
                'period': period,
                'missing_components': sorted(set(code_map) - set(values)),
            })
            continue
        signed = float(expression(values))
        absolute = abs(signed)
        scale = max([abs(value) for value in values.values()] + [1.0])
        relative = absolute / scale
        pass_absolute = absolute <= float(absolute_tolerance)
        pass_relative = (relative_tolerance is None or
                         relative <= float(relative_tolerance))
        if pass_absolute and pass_relative:
            classification = 'pass'
        elif absolute <= float(warning_tolerance):
            classification = 'warning'
        else:
            classification = 'fail'
        detail = {
            'period': period, 'residual': signed,
            'abs_residual': absolute, 'relative_residual': relative,
            'classification': classification,
        }
        residuals.append(detail)
        if classification != 'pass':
            offending.append(detail)
    if not residuals:
        status = 'insufficient_overlap'
    elif any(item['classification'] == 'fail' for item in residuals):
        status = 'fail'
    elif any(item['classification'] == 'warning' for item in residuals):
        status = 'warning'
    else:
        status = 'pass'
    return {
        'name': name, 'status': status, 'checked_periods': len(residuals),
        'missing_periods': len(missing_periods),
        'missing_period_details': missing_periods[:50],
        'max_abs_residual': (max(item['abs_residual'] for item in residuals)
                             if residuals else None),
        'max_relative_residual': (
            max(item['relative_residual'] for item in residuals)
            if residuals else None),
        'tolerance': tolerance, 'offending_periods': offending[:50],
        'source_or_derived': source_or_derived,
    }


def _build_identity_checks(conn):
    safe = _identity_check(
        conn, 'SAFE total reserve assets = components', 'china_macro_observations',
        {'total': 'CN_SAFE_OFFICIAL_RESERVE_ASSETS_TOTAL_USD',
         'fx': 'CN_SAFE_FX_RESERVES_USD', 'gold': 'CN_SAFE_MONETARY_GOLD_USD',
         'sdr': 'CN_SAFE_SDR_HOLDINGS_USD', 'imf': 'CN_SAFE_IMF_RESERVE_POSITION_USD',
         'other': 'CN_SAFE_OTHER_RESERVE_ASSETS_USD'},
        lambda v: v['total'] - v['fx'] - v['gold'] - v['sdr'] - v['imf'] - v['other'],
        absolute_tolerance=0.05, warning_tolerance=2.0, unit='亿美元',
        rounding_note=('SAFE publishes total and components independently to two decimals; '
                       'residuals above 0.05 and at most 2.0 are retained as rounding warnings.'),
        source_or_derived='official_total_and_components')
    trade_export = _identity_check(
        conn, 'HK total exports = domestic exports + re-exports',
        'hong_kong_macro_observations',
        {'total': 'HK_TRADE_TOTAL_EXPORTS', 'domestic': 'HK_TRADE_DOMESTIC_EXPORTS',
         'reexport': 'HK_TRADE_RE_EXPORTS'},
        lambda v: v['total'] - v['domestic'] - v['reexport'],
        absolute_tolerance=0.001, warning_tolerance=1.0, unit="HK$ '000",
        rounding_note='Trade-IDDS values are reported in HK$ thousand; up to one unit is a rounding warning.',
        source_or_derived='official_components')
    trade_total = _identity_check(
        conn, 'HK total trade = imports + total exports',
        'hong_kong_macro_observations',
        {'total_trade': 'HK_TRADE_TOTAL_TRADE', 'imports': 'HK_TRADE_IMPORTS',
         'exports': 'HK_TRADE_TOTAL_EXPORTS'},
        lambda v: v['total_trade'] - v['imports'] - v['exports'],
        absolute_tolerance=0.001, warning_tolerance=1.0, unit="HK$ '000",
        rounding_note='Trade-IDDS values are reported in HK$ thousand; up to one unit is a rounding warning.',
        source_or_derived='official_components')
    trade_balance = _identity_check(
        conn, 'HK trade balance = exports - imports',
        'hong_kong_macro_observations',
        {'balance': 'HK_TRADE_BALANCE', 'exports': 'HK_TRADE_TOTAL_EXPORTS',
         'imports': 'HK_TRADE_IMPORTS'},
        lambda v: v['balance'] - v['exports'] + v['imports'],
        absolute_tolerance=0.001, warning_tolerance=0.01, unit="HK$ '000",
        rounding_note='Trade balance is derived from the stored official exports and imports.',
        source_or_derived='derived_balance_vs_official_inputs')
    trade_share = _identity_check(
        conn, 'HK re-export share = re-exports / total exports',
        'hong_kong_macro_observations',
        {'share': 'HK_TRADE_RE_EXPORT_SHARE', 'reexport': 'HK_TRADE_RE_EXPORTS',
         'exports': 'HK_TRADE_TOTAL_EXPORTS'},
        lambda v: v['share'] - (v['reexport'] / v['exports'] * 100.0
                                if v['exports'] else 0.0),
        absolute_tolerance=1e-9, warning_tolerance=1e-6, unit='percentage points',
        rounding_note='Derived share uses unrounded stored inputs; floating-point epsilon only.',
        source_or_derived='derived_share_vs_official_inputs')
    rvd = _identity_check(
        conn, 'RVD total sales count = primary + secondary',
        'hong_kong_macro_observations',
        {'total': 'HK_RVD_TOTAL_SALES_COUNT', 'primary': 'HK_RVD_PRIMARY_SALES_COUNT',
         'secondary': 'HK_RVD_SECONDARY_SALES_COUNT'},
        lambda v: v['total'] - v['primary'] - v['secondary'],
        absolute_tolerance=0.0, warning_tolerance=0.0, unit='agreements',
        rounding_note='Agreement counts must add exactly.',
        source_or_derived='derived_total_vs_official_components')
    land = _identity_check(
        conn, 'Land Registry total sales count = primary + secondary',
        'hong_kong_macro_observations',
        {'total': 'HK_LR_TOTAL_SALES_COUNT', 'primary': 'HK_LR_PRIMARY_SALES_COUNT',
         'secondary': 'HK_LR_SECONDARY_SALES_COUNT'},
        lambda v: v['total'] - v['primary'] - v['secondary'],
        absolute_tolerance=0.0, warning_tolerance=0.0, unit='agreements',
        rounding_note='Agreement counts must add exactly.',
        source_or_derived='official_total_and_components')
    land_value = _identity_check(
        conn, 'Land Registry total sales value = primary + secondary',
        'hong_kong_macro_observations',
        {'total': 'HK_LR_TOTAL_SALES_VALUE', 'primary': 'HK_LR_PRIMARY_SALES_VALUE',
         'secondary': 'HK_LR_SECONDARY_SALES_VALUE'},
        lambda v: v['total'] - v['primary'] - v['secondary'],
        absolute_tolerance=0.001, warning_tolerance=1.0, unit='HK$ million',
        rounding_note='Published component values are rounded to HK$ million; one million is a warning band.',
        source_or_derived='official_total_and_components')
    return [safe, trade_export, trade_total, trade_balance, trade_share,
            rvd, land, land_value]


def _build_source_metadata_gaps(conn, sources):
    fields = ('entry_url', 'download_url', 'request_params', 'file_format',
              'expected_frequency', 'history_start', 'latest_reference_period',
              'latest_reference_period_end', 'unit', 'parser_version', 'status',
              'raw_sha256', 'freshness_status', 'freshness_reason')
    gaps = {'source_count': len(sources),
            'release_date_not_provided_count': sum(
                1 for source in sources if source.get('release_date_not_provided')),
            'release_lag_not_provided_count': sum(
                1 for source in sources
                if source.get('expected_release_lag_days') in (None, '')),
            'trade_sources_with_unknown_unit': [],
            'fields': {field: sum(1 for source in sources
                                  if source.get(field) in (None, '')) for field in fields}}
    for field in ('release_metadata_status', 'expected_release_lag_status'):
        counts = {}
        for source in sources:
            value = source.get(field) or 'missing'
            counts[value] = counts.get(value, 0) + 1
        gaps[field + '_counts'] = counts
    gaps['trade_sources_with_unknown_unit'] = [source['source_id'] for source in sources
                                               if source.get('source_id', '').startswith('HK_TRADE_')
                                               and source.get('unit') in (None, '', 'unknown')]
    return gaps


def build_hong_kong_macro_debug(db_path):
    try:
        conn = _connect_readonly(db_path)
        _require_hong_kong_macro_schema(conn)
    except (FileNotFoundError, RuntimeError, sqlite3.OperationalError) as exc:
        return {'success': False, 'status': 'not_initialized', 'error': str(exc)}
    with closing(conn):
        counts = [dict(row) for row in conn.execute('''SELECT indicator_code,COUNT(*) AS n_obs,
            MIN(period) AS start_period,MAX(period) AS end_period
            FROM hong_kong_macro_observations
            WHERE value IS NOT NULL AND COALESCE(data_status, '') <> 'superseded'
            GROUP BY indicator_code ORDER BY indicator_code''')]
        superseded_count = conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
                                           WHERE data_status='superseded' ''').fetchone()[0]
        null_count = conn.execute('''SELECT COUNT(*) FROM hong_kong_macro_observations
                                     WHERE value IS NULL''').fetchone()[0]
        sources = [dict(row) for row in conn.execute('SELECT * FROM hong_kong_macro_sources ORDER BY source_id')]
        runs = [dict(row) for row in conn.execute('''SELECT * FROM hong_kong_macro_update_runs
            ORDER BY started_at DESC LIMIT 10''')]
        trade_dimension_counts = [dict(row) for row in conn.execute('''SELECT dimension_type,
            COUNT(*) AS n_obs,COUNT(DISTINCT dimension_code) AS n_dimensions,
            MIN(period) AS start_period,MAX(period) AS end_period
            FROM hong_kong_macro_trade_dimensions WHERE value IS NOT NULL
            GROUP BY dimension_type ORDER BY dimension_type''')]
        web_table_counts = [dict(row) for row in conn.execute('''SELECT table_id,
            COUNT(*) AS n_obs,COUNT(DISTINCT series_code) AS n_series,
            MIN(period) AS start_period,MAX(period) AS end_period
            FROM hong_kong_macro_web_table_observations
            WHERE value IS NOT NULL AND COALESCE(data_status, '') <> 'superseded'
            GROUP BY table_id ORDER BY table_id''')]
        superseded_web_table_count = conn.execute('''SELECT COUNT(*)
            FROM hong_kong_macro_web_table_observations
            WHERE data_status='superseded' ''').fetchone()[0]
        metadata_gaps = dict(conn.execute('''SELECT
            SUM(CASE WHEN source_url IS NULL OR source_url='' THEN 1 ELSE 0 END) AS no_source_url,
            SUM(CASE WHEN retrieved_at IS NULL OR retrieved_at='' THEN 1 ELSE 0 END) AS no_retrieved_at,
            SUM(CASE WHEN raw_sha256 IS NULL OR raw_sha256='' THEN 1 ELSE 0 END) AS no_raw_sha256,
            SUM(CASE WHEN parser_version IS NULL OR parser_version='' THEN 1 ELSE 0 END) AS no_parser_version,
            SUM(CASE WHEN release_date IS NULL OR release_date='' THEN 1 ELSE 0 END) AS no_release_date
            FROM hong_kong_macro_observations
            WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone())
        web_metadata_gaps = dict(conn.execute('''SELECT
            SUM(CASE WHEN source_url IS NULL OR source_url='' THEN 1 ELSE 0 END) AS no_source_url,
            SUM(CASE WHEN retrieved_at IS NULL OR retrieved_at='' THEN 1 ELSE 0 END) AS no_retrieved_at,
            SUM(CASE WHEN raw_sha256 IS NULL OR raw_sha256='' THEN 1 ELSE 0 END) AS no_raw_sha256,
            SUM(CASE WHEN parser_version IS NULL OR parser_version='' THEN 1 ELSE 0 END) AS no_parser_version,
            SUM(CASE WHEN period_raw IS NULL OR period_raw='' THEN 1 ELSE 0 END) AS no_period_raw,
            SUM(CASE WHEN statistic IS NULL OR statistic='' THEN 1 ELSE 0 END) AS no_statistic
            ,SUM(CASE WHEN construct_label IS NULL OR construct_label='' THEN 1 ELSE 0 END) AS no_construct_label
            ,SUM(CASE WHEN (construct_label IS NULL OR construct_label='')
                           AND (missing_reason IS NULL OR missing_reason='')
                      THEN 1 ELSE 0 END) AS unlabeled_without_reason
            FROM hong_kong_macro_web_table_observations
            WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded' ''').fetchone())
        duplicate_active = [dict(row) for row in conn.execute('''SELECT indicator_code,period,
            dimension_key,dimension_value,vintage_date,COUNT(*) AS n
            FROM hong_kong_macro_observations
            WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded'
            GROUP BY indicator_code,period,dimension_key,dimension_value,vintage_date
            HAVING COUNT(*) > 1 LIMIT 100''')]
        web_duplicate_active = [dict(row) for row in conn.execute('''SELECT table_id,period,
            series_code,COUNT(*) AS n
            FROM hong_kong_macro_web_table_observations
            WHERE value IS NOT NULL AND COALESCE(data_status,'') <> 'superseded'
            GROUP BY table_id,period,series_code HAVING COUNT(*) > 1 LIMIT 100''')]
        quick_check = conn.execute('PRAGMA quick_check').fetchone()[0]
        observed_codes = {row['indicator_code'] for row in counts}
        for code, mapping in CSD_CURATED_MAPPINGS.items():
            exists = conn.execute('''SELECT 1 FROM hong_kong_macro_web_table_observations
                WHERE table_id=? AND series_code=? AND value IS NOT NULL
                  AND COALESCE(data_status,'') <> 'superseded' LIMIT 1''',
                                  (mapping['table_id'], mapping['series_code'])).fetchone()
            if exists:
                observed_codes.add(code)
        all_codes = (set(INDICATORS) | set(CSD_CURATED_MAPPINGS) |
                     set(DEPRECATED_CSD_CURATED_MAPPINGS))
        zero_indicators = [_meta(code) for code in sorted(all_codes - observed_codes)]
        short_indicators = [dict(_meta(code), n_obs=row['n_obs'], start_period=row['start_period'],
                                 end_period=row['end_period'])
                            for row in counts if row['n_obs'] < 60]
        indicator_catalog = _build_indicator_catalog(conn)
        identity_checks = _build_identity_checks(conn)
        source_metadata_gaps = _build_source_metadata_gaps(conn, sources)
        mixed_frequency_anomalies = []
        for source in sources:
            if source.get('frequency') == 'mixed':
                try:
                    summary = json.loads(source.get('frequency_summary_json') or '{}')
                except (TypeError, ValueError):
                    summary = None
                mixed_frequency_anomalies.append({
                    'source_id': source['source_id'],
                    'expected_frequency': source.get('expected_frequency'),
                    'observed_frequency_summary': summary,
                    'latest_reference_period': source.get('latest_reference_period'),
                    'reason': 'Source contains more than one official frequency; latest period is calendar-keyed.',
                })
        latest_run = runs[0] if runs else None
        recent_failed_run = next((run for run in runs
                                  if run.get('status') in ('failed', 'partial')), None)
        schema_info = {
            'module_schema_version': HK_MACRO_SCHEMA_VERSION,
            'database_user_version': conn.execute('PRAGMA user_version').fetchone()[0],
            'database_identifier': 'pboc_data.db',
        }
    source_hash_checks = []
    for source in sources:
        raw_path = source.get('raw_path')
        if not raw_path:
            source_hash_checks.append({'source_id': source['source_id'], 'status': 'no_raw_path'})
            continue
        path = ROOT / raw_path
        if not path.exists():
            source_hash_checks.append({'source_id': source['source_id'], 'status': 'raw_file_missing',
                                       'raw_path': raw_path})
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        source_hash_checks.append({'source_id': source['source_id'], 'status': 'match' if digest == source.get('raw_sha256') else 'mismatch',
                                   'raw_path': raw_path, 'stored_sha256': source.get('raw_sha256'),
                                   'actual_sha256': digest})
    freshness = []
    for source in sources:
        period = source.get('latest_reference_period')
        freq = source.get('frequency') or 'unknown'
        if not period:
            freshness.append({'source_id': source['source_id'], 'freshness': 'no_observation'})
            continue
        detail = _source_freshness_detail(source)
        freshness.append({'source_id': source['source_id'], 'frequency': freq,
                          'latest_reference_period': period,
                          'latest_reference_period_end': source.get('latest_reference_period_end'),
                          **detail})
    return {'success': True, 'database_quick_check': quick_check,
            'observation_counts': counts, 'null_observation_count': null_count,
            'superseded_observation_count': superseded_count,
            'sources': sources, 'runs': runs,
            'trade_dimension_counts': trade_dimension_counts,
            'csd_web_table_counts': web_table_counts,
            'superseded_web_table_count': superseded_web_table_count,
            'metadata_gaps': metadata_gaps,
            'csd_metadata_gaps': web_metadata_gaps,
            'duplicate_active_observations': duplicate_active,
            'duplicate_active_csd_observations': web_duplicate_active,
            'source_hash_checks': source_hash_checks,
            'source_freshness': freshness,
            'indicator_catalog': indicator_catalog,
            'identity_checks': identity_checks,
            'source_metadata_gaps': source_metadata_gaps,
            'mixed_frequency_anomalies': mixed_frequency_anomalies,
            'schema': schema_info,
            'current_update_job': latest_run,
            'recent_failed_run': recent_failed_run,
            'zero_indicators': zero_indicators,
            'short_indicators_below_60': short_indicators,
            'status_vocabulary': ['not_attempted', 'success', 'blocked', 'failed', 'partial',
                                  'official', 'official_revised', 'provisional',
                                  'derived', 'superseded', 'deprecated',
                                  'not_released', 'metadata_unknown', 'unavailable_at_source',
                                  'unsupported_field', 'current', 'delayed_but_expected',
                                  'stale', 'source_failed_using_cached_data', 'unknown'],
            'lead_lag_status_vocabulary': ['ok', 'hk_no_data', 'mainland_no_data',
                                           'unsupported_transform', 'insufficient_overlap',
                                           'invalid_request', 'failed'],
            'identity_status_vocabulary': ['pass', 'warning', 'fail',
                                           'insufficient_overlap', 'table_unavailable'],
            'table': 'hong_kong_macro_observations',
            'raw_root': 'data/hong_kong_macro_raw/',
            'notes': ['原始文件只写入 data/hong_kong_macro_raw 并由 .gitignore 排除。',
                      '中国 SAFE 储备资产位于 china_macro_observations，不在本表。']}


def build_hong_kong_macro_csd_web_table_payload(db_path, table_id, query=None):
    """Return one bounded, independently queryable CSD Web Table slice."""
    table_id = str(table_id or '').strip()
    if table_id not in CSD_WEB_TABLES:
        raise ValueError(f'未知 CSD Web Table: {table_id}')
    query = query or {}
    start = parse_period_bound(query.get('start')) if query.get('start') else None
    end = parse_period_bound(query.get('end')) if query.get('end') else None
    if start and end and _period_sort_key(start) > _period_sort_key(end):
        raise ValueError('start 不能晚于 end')
    include_superseded = _query_bool(query.get('include_superseded'))
    include_missing = _query_bool(query.get('include_missing'))
    series = _query_values(query, 'series_code', 'series')
    frequencies = _query_values(query, 'frequency', 'freq')
    statistics = _query_values(query, 'statistic', 'stat')
    dimension_filters = _parse_dimension_filters(query)
    latest = _query_bool(query.get('latest'))
    clauses = ['table_id=?']
    params = [table_id]
    if series:
        placeholders = ','.join('?' for _ in series)
        clauses.append(f'series_code IN ({placeholders})')
        params.extend(series)
    if frequencies:
        clauses.append('frequency IN (' + ','.join('?' for _ in frequencies) + ')')
        params.extend(frequencies)
    if statistics:
        clauses.append('statistic IN (' + ','.join('?' for _ in statistics) + ')')
        params.extend(statistics)
    if not include_superseded:
        clauses.append("COALESCE(data_status,'') <> 'superseded'")
    if not include_missing:
        clauses.append('value IS NOT NULL')
    if _query_bool(query.get('_export_all')):
        limit = None
    else:
        try:
            limit = max(1, min(5000, int(query.get('limit', 1000))))
        except (TypeError, ValueError):
            limit = 1000
    try:
        offset = max(0, int(query.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    where_sql = ' AND '.join(clauses)
    start_key = _period_sort_key(start) if start else None
    end_key = _period_sort_key(end) if end else None
    # Without mixed-frequency bounds, dimension filters, or latest=1, let
    # SQLite count and page the table so a large official table is never
    # materialized for the first page. The explicit latest/dimension paths
    # materialize only the selected table, then apply canonical semantics in
    # Python so Q/H/Y do not get coerced by lexical ordering.
    has_period_bound = start_key is not None or end_key is not None
    materialize_candidates = has_period_bound or latest or bool(dimension_filters)
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        if materialize_candidates:
            bounded_clauses = list(clauses)
            bounded_params = list(params)
            if start:
                bounded_clauses.append('period >= ?')
                bounded_params.append(str(start)[:4])
            if end:
                bounded_clauses.append('period <= ?')
                bounded_params.append(str(end)[:4] + '-99')
            candidates = [dict(row) for row in conn.execute(
                'SELECT * FROM hong_kong_macro_web_table_observations WHERE ' +
                ' AND '.join(bounded_clauses) + ' ORDER BY period,series_code',
                bounded_params)]
            rows = [row for row in candidates
                    if (start_key is None or _period_sort_key(row.get('period'), row.get('frequency')) >= start_key)
                    and (end_key is None or _period_sort_key(row.get('period'), row.get('frequency')) <= end_key)
                    and _matches_dimension_filters(row, dimension_filters)]
            if latest:
                latest_rows = {}
                for row in rows:
                    key = (row.get('frequency'), row.get('series_code'),
                           row.get('statistic'))
                    old = latest_rows.get(key)
                    if old is None or _period_sort_key(row.get('period'), row.get('frequency')) > _period_sort_key(old.get('period'), old.get('frequency')):
                        latest_rows[key] = row
                rows = list(latest_rows.values())
            total = len(rows)
            page_rows = rows[offset:] if limit is None else rows[offset:offset + limit]
            frequency_summary = {}
            for row in rows:
                key = (row.get('frequency') or 'unknown', row.get('statistic') or 'unknown')
                frequency_summary[key] = frequency_summary.get(key, 0) + 1
        else:
            total = conn.execute(
                'SELECT COUNT(*) FROM hong_kong_macro_web_table_observations WHERE ' +
                where_sql, params).fetchone()[0]
            if limit is None:
                page_rows = [dict(row) for row in conn.execute(
                    'SELECT * FROM hong_kong_macro_web_table_observations WHERE ' +
                    where_sql + ' ORDER BY period,series_code', params)]
            else:
                page_rows = [dict(row) for row in conn.execute(
                    'SELECT * FROM hong_kong_macro_web_table_observations WHERE ' +
                    where_sql + ' ORDER BY period,series_code LIMIT ? OFFSET ?',
                    (*params, limit, offset))]
            frequency_summary = {(row['frequency'] or 'unknown', row['statistic'] or 'unknown'): row['n_obs']
                                 for row in conn.execute(
                                     'SELECT frequency,statistic,COUNT(*) AS n_obs '
                                     'FROM hong_kong_macro_web_table_observations WHERE ' +
                                     where_sql + ' GROUP BY frequency,statistic', params)}
    for row in page_rows:
        row.update(_period_bounds(row.get('period'), row.get('frequency')))
        if row.get('dimension_json'):
            try:
                row['dimensions'] = json.loads(row['dimension_json'])
            except (TypeError, ValueError):
                row['dimensions'] = None
    with closing(_connect_readonly(db_path)) as conn:
        source = conn.execute('SELECT * FROM hong_kong_macro_sources WHERE source_id=?',
                              (f'HK_CSD_WEB_{table_id}',)).fetchone()
    return {'success': True, 'table_id': table_id, 'table': CSD_WEB_TABLES[table_id],
            'filters': {'start': start, 'end': end, 'series_code': series,
                        'frequency': frequencies, 'statistic': statistics,
                        'dimensions': dimension_filters, 'latest': latest,
                        'include_superseded': include_superseded,
                        'include_missing': include_missing,
                        'limit': limit, 'offset': offset},
            'source': dict(source) if source else None,
            'rows': page_rows, 'n_rows': len(page_rows), 'total_rows': total,
            'has_more': limit is not None and offset + len(page_rows) < total,
            'frequency_summary': [
                {'frequency': key[0], 'statistic': key[1], 'n_obs': count}
                for key, count in sorted(frequency_summary.items())]}


def build_hong_kong_macro_csd_web_table_csv(db_path, table_id, query=None):
    export_query = dict(query or {})
    export_query['_export_all'] = '1'
    payload = build_hong_kong_macro_csd_web_table_payload(db_path, table_id,
                                                           export_query)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['table_id', 'period', 'period_start', 'period_end', 'period_raw', 'frequency', 'series_code',
                     'series_label', 'construct_label', 'statistic', 'value', 'unit',
                     'dimension_json', 'data_status', 'source_url', 'raw_sha256', 'parser_version'])
    for row in payload['rows']:
        writer.writerow([row.get('table_id'), row.get('period'), row.get('period_start'),
                         row.get('period_end'), row.get('period_raw'),
                         row.get('frequency'), row.get('series_code'), row.get('series_label'),
                         row.get('construct_label'), row.get('statistic'), row.get('value'),
                         row.get('unit'), row.get('dimension_json'), row.get('data_status'), row.get('source_url'),
                         row.get('raw_sha256'), row.get('parser_version')])
    return output.getvalue()


def build_hong_kong_macro_csv(db_path, query=None):
    query = query or {}
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        rows, _filters = _load_hk_query_rows(conn, query)
    by_code = {}
    for row in rows:
        by_code.setdefault(row['indicator_code'], []).append(row)
    transformed = []
    transform = str(query.get('transform') or 'level').lower()
    for code, values in by_code.items():
        transformed.extend(_transform_rows(values, transform, _filters.get('base_period')))
    transformed.sort(key=lambda row: (row.get('indicator_code') or '',
                                      _period_sort_key(row.get('period'), row.get('frequency'))))
    rows = transformed
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['indicator_code', 'indicator_name', 'name_zh', 'name_en', 'category',
                     'period', 'period_start', 'period_end', 'frequency', 'value',
                     'source_period_end',
                     'raw_value', 'transformed_value',
                     'transformation', 'formula', 'unit', 'currency',
                     'seasonal_adjustment', 'price_basis', 'dimension_key',
                     'dimension_value', 'data_status', 'derived', 'original_or_derived',
                     'source_id', 'source_url', 'source_table', 'release_date',
                     'retrieved_at', 'vintage_date', 'raw_sha256', 'parser_version',
                     'missing_reason', 'note'])
    writer.writerows([
        [row.get('indicator_code'), _meta(row['indicator_code'])['name'],
         _meta(row['indicator_code']).get('name_zh', _meta(row['indicator_code'])['name']),
         _meta(row['indicator_code']).get('name_en'), row.get('category'),
         row.get('period'), _period_bounds(row.get('period'), row.get('frequency'))['period_start'],
         _period_bounds(row.get('period'), row.get('frequency'))['period_end'],
         row.get('frequency'), row.get('value'), row.get('source_period_end'),
         row.get('raw_value'),
         row.get('value'), row.get('transformation') or 'level', row.get('formula'),
         row.get('unit'), row.get('currency') or _meta(row['indicator_code']).get('currency'),
         row.get('seasonal_adjustment') or 'not_provided',
         row.get('price_basis') or _meta(row['indicator_code']).get('price_basis'),
         row.get('dimension_key') or '', row.get('dimension_value') or '',
         row.get('data_status'),
         row.get('data_status') == 'derived',
         'derived' if row.get('data_status') == 'derived' else 'original',
         row.get('source_id'), row.get('source_url'), row.get('source_table'),
         row.get('release_date'), row.get('retrieved_at'), row.get('vintage_date'),
         row.get('raw_sha256'), row.get('parser_version'), row.get('missing_reason'),
         row.get('note')]
        for row in rows])
    return output.getvalue()


def build_hong_kong_macro_trade_dimensions_csv(db_path):
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        rows = conn.execute('''SELECT source_id,dimension_type,trade_type,period,
            dimension_code,dimension_label,statistic,value,unit,data_status,
            source_url,source_table,raw_sha256,note
            FROM hong_kong_macro_trade_dimensions
            ORDER BY dimension_type,period,dimension_code''')
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['source_id', 'dimension_type', 'trade_type', 'period',
                         'dimension_code', 'dimension_label', 'statistic', 'value',
                         'unit', 'data_status', 'source_url', 'source_table',
                         'raw_sha256', 'note'])
        writer.writerows(rows)
    return output.getvalue()


def build_hong_kong_macro_trade_dimensions_payload(db_path, dimension_type=None,
                                                   start_period=None, end_period=None,
                                                   latest_only=True, top_n=10):
    """Return an explicit, bounded or full Trade-IDDS dimension response.

    The dashboard deliberately uses latest Top 10 rows for partner/product
    cross-sections. Researchers can request the complete stored dimension
    history with ``latest_only=False`` and ``top_n=None``; the CSV endpoint
    remains the lossless export path.
    """
    start_period = parse_period_bound(start_period) if start_period else None
    end_period = parse_period_bound(end_period) if end_period else None
    valid_types = {item['dimension_type'] for item in TRADE_DIMENSION_REQUESTS.values()}
    if dimension_type and dimension_type not in valid_types:
        raise ValueError(f'未知 trade dimension_type: {dimension_type}')
    if start_period and end_period and _period_sort_key(start_period) > _period_sort_key(end_period):
        raise ValueError('start_period 不能晚于 end_period')
    with closing(_connect_readonly(db_path)) as conn:
        _require_hong_kong_macro_schema(conn)
        clauses = ["value IS NOT NULL", "COALESCE(data_status,'') <> 'superseded'"]
        params = []
        if dimension_type:
            clauses.append('dimension_type=?')
            params.append(str(dimension_type))
        if start_period:
            # Mixed-frequency support is not needed for Trade-IDDS, but the
            # same canonical bound validator is used by every endpoint.
            clauses.append('period>=?')
            params.append(start_period)
        if end_period:
            clauses.append('period<=?')
            params.append(end_period)
        rows = [dict(row) for row in conn.execute('''SELECT source_id,dimension_type,
            trade_type,period,dimension_code,dimension_label,statistic,value,unit,data_status,
            source_url,source_table,raw_sha256,note
            FROM hong_kong_macro_trade_dimensions WHERE ''' + ' AND '.join(clauses) + '''
            ORDER BY dimension_type,period,dimension_code''', tuple(params))]
    if latest_only:
        latest_by_type = {}
        for row in rows:
            latest_by_type[row['dimension_type']] = max(
                latest_by_type.get(row['dimension_type'], ''), row['period'])
        rows = [row for row in rows
                if row['period'] == latest_by_type.get(row['dimension_type'])]
    if top_n is not None:
        try:
            limit = max(1, int(top_n))
        except (TypeError, ValueError):
            limit = 10
        grouped = {}
        for row in rows:
            grouped.setdefault((row['dimension_type'], row['period']), []).append(row)
        rows = []
        for key in sorted(grouped):
            rows.extend(sorted(grouped[key],
                               key=lambda item: (-float(item['value']), item['dimension_code']))[:limit])
    return {'success': True, 'rows': rows, 'n_rows': len(rows),
            'filters': {'dimension_type': dimension_type, 'start_period': start_period,
                        'end_period': end_period, 'latest_only': bool(latest_only),
                        'top_n': top_n}}


def _run_source(conn, source_id, fetch_and_parse):
    _update_source_state(conn, source_id, last_attempt_at=datetime.now().isoformat(),
                          status='running', error_type=None, error_message=None)
    try:
        rows, raw_path, digest = fetch_and_parse()
        for row in rows or []:
            if row and not row.get('raw_sha256'):
                row['raw_sha256'] = digest
        written = upsert_hong_kong_observations(conn, rows)
        periods = [row['period'] for row in rows if row.get('period')]
        breakdown = {}
        for row in rows:
            item_source = row.get('source_id') or source_id
            detail = breakdown.setdefault(item_source, {'record_count': 0, 'periods': [],
                                                       'raw_sha256_values': set(),
                                                       'raw_path_values': set()})
            detail['record_count'] += 1
            if row.get('period'):
                detail['periods'].append(row['period'])
            if row.get('raw_sha256'):
                detail['raw_sha256_values'].add(row['raw_sha256'])
            if row.get('_raw_path'):
                detail['raw_path_values'].add(row['_raw_path'])
        for detail in breakdown.values():
            detail['latest_reference_period'] = max(detail['periods']) if detail['periods'] else None
            detail.pop('periods', None)
            hashes = detail.pop('raw_sha256_values')
            paths = detail.pop('raw_path_values')
            detail['raw_sha256'] = next(iter(hashes), None) if len(hashes) == 1 else None
            detail['raw_path'] = next(iter(paths), None) if len(paths) == 1 else None
        _update_source_state(conn, source_id, status='success', last_success_at=datetime.now().isoformat(),
                             raw_sha256=digest, raw_path=raw_path,
                             latest_reference_period=max(periods) if periods else None,
                             record_count=len(rows), error_type=None, error_message=None)
        return {'status': 'success', 'observations_parsed': len(rows),
                'records_written': written, 'raw_path': raw_path,
                'raw_sha256': digest,
                'source_breakdown': breakdown}
    except Exception as exc:
        blocked = isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
        status = 'blocked' if blocked else 'failed'
        _update_source_state(conn, source_id, status=status, error_type=type(exc).__name__,
                             error_message=str(exc))
        return {'status': status, 'observations_parsed': 0, 'records_written': 0,
                'error': str(exc), 'error_type': type(exc).__name__}


def retry_hkma_sources(db_path, source_ids=None, start_year=None):
    """Retry only failed/blocked HKMA sources without refetching other domains."""
    started = datetime.now().isoformat()
    run_id = uuid.uuid4().hex
    records_parsed = records_written = 0
    source_status = {}
    with closing(connect(db_path)) as conn:
        ensure_hong_kong_macro_tables(conn)
        if source_ids is None:
            source_ids = [row[0] for row in conn.execute('''SELECT source_id
                FROM hong_kong_macro_sources
                WHERE source_id IN ({}) AND status IN ('blocked','failed')
                ORDER BY source_id'''.format(','.join('?' * len(HKMA_URLS))),
                tuple(HKMA_URLS))]
        source_ids = list(dict.fromkeys(source_ids or []))
        invalid = [source_id for source_id in source_ids if source_id not in HKMA_URLS]
        if invalid:
            raise ValueError('未知 HKMA source: ' + ', '.join(invalid))
        conn.execute('''INSERT INTO hong_kong_macro_update_runs
            (run_id,started_at,status,full_history,source_status_json,records_parsed,records_written,error_count)
            VALUES (?,?,?,?,?,?,?,?)''',
                     (run_id, started, 'running', 0, '{}', 0, 0, 0))
        conn.commit()
        session = _new_session()
        for source_id in source_ids:
            def hkma_job(source_id=source_id):
                records = _fetch_hkma_all(session, HKMA_URLS[source_id],
                                          HKMA_REQUEST_PARAMS.get(source_id))
                raw = json.dumps(records, ensure_ascii=False, sort_keys=True).encode('utf-8')
                raw_path, digest = _save_raw(source_id, raw, 'json')
                return _filter_start(parse_hkma_records(records, source_id), start_year), raw_path, digest
            result = _run_source(conn, source_id, hkma_job)
            source_status[source_id] = result
            records_parsed += result['observations_parsed']
            records_written += result['records_written']
        errors = [item.get('error') for item in source_status.values()
                  if item.get('status') in ('failed', 'blocked')]
        if records_written and errors:
            status = 'partial'
        elif records_written or not errors:
            status = 'completed'
        else:
            status = 'failed'
        finished = datetime.now().isoformat()
        conn.execute('''UPDATE hong_kong_macro_update_runs SET finished_at=?,status=?,source_status_json=?,
            records_parsed=?,records_written=?,error_count=?,error_message=? WHERE run_id=?''',
                     (finished, status, json.dumps(source_status, ensure_ascii=False),
                      records_parsed, records_written, len(errors), '; '.join(errors)[:4000], run_id))
        ensure_hong_kong_macro_tables(conn, refresh_metadata=True)
        conn.commit()
    return {'success': status in ('completed', 'partial'), 'run_id': run_id,
            'started_at': started, 'finished_at': finished, 'status': status,
            'source_ids': source_ids, 'records_parsed': records_parsed,
            'records_written': records_written, 'source_status': source_status,
            'errors': errors}


def _run_trade_dimension_source(conn, source_id, fetch_and_parse):
    _update_source_state(conn, source_id, last_attempt_at=datetime.now().isoformat(),
                          status='running', error_type=None, error_message=None)
    try:
        rows, raw_path, digest = fetch_and_parse()
        for row in rows or []:
            if row:
                row['raw_sha256'] = row.get('raw_sha256') or digest
        written = upsert_trade_dimensions(conn, rows)
        periods = [row['period'] for row in rows if row.get('period')]
        _update_source_state(
            conn, source_id, status='success', last_success_at=datetime.now().isoformat(),
            raw_sha256=digest, raw_path=raw_path,
            latest_reference_period=max(periods) if periods else None,
            record_count=len(rows), error_type=None, error_message=None)
        return {'status': 'success', 'observations_parsed': len(rows),
                'records_written': written, 'raw_path': raw_path, 'raw_sha256': digest}
    except Exception as exc:
        blocked = isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
        status = 'blocked' if blocked else 'failed'
        _update_source_state(conn, source_id, status=status, error_type=type(exc).__name__,
                             error_message=str(exc))
        return {'status': status, 'observations_parsed': 0, 'records_written': 0,
                'error': str(exc), 'error_type': type(exc).__name__}


def _run_csd_web_table_source(conn, source_id, table_id, fetch_and_parse):
    _update_source_state(conn, source_id, last_attempt_at=datetime.now().isoformat(),
                          status='running', error_type=None, error_message=None)
    try:
        rows, raw_path, digest = fetch_and_parse()
        if not rows:
            raise ValueError(f'CSD Web Table {table_id} downloaded but parser returned no observations')
        canonical_keyed = all(
            'freq=' in str(row.get('series_code') or '') and
            '|sv=' in str(row.get('series_code') or '') and
            '|stat=' in str(row.get('series_code') or '')
            for row in rows)
        if canonical_keyed:
            conn.execute('''UPDATE hong_kong_macro_web_table_observations
                SET data_status='superseded'
                WHERE source_id=? AND COALESCE(data_status, '') <> 'superseded'
                  AND NOT (series_code LIKE '%freq=%'
                           AND series_code LIKE '%|sv=%'
                           AND series_code LIKE '%|stat=%') ''', (source_id,))
            conn.commit()
        for row in rows or []:
            if row:
                row['raw_sha256'] = row.get('raw_sha256') or digest
        written = upsert_csd_web_table_rows(conn, rows)
        periods = [row['period'] for row in rows if row.get('period')]
        _update_source_state(
            conn, source_id, status='success', last_success_at=datetime.now().isoformat(),
            raw_sha256=digest, raw_path=raw_path,
            latest_reference_period=max(periods) if periods else None,
            record_count=len(rows), error_type=None, error_message=None)
        return {'status': 'success', 'observations_parsed': len(rows),
                'records_written': written, 'raw_path': raw_path, 'raw_sha256': digest,
                'table_id': table_id}
    except Exception as exc:
        blocked = isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError))
        status = 'blocked' if blocked else 'failed'
        _update_source_state(conn, source_id, status=status, error_type=type(exc).__name__,
                             error_message=str(exc))
        return {'status': status, 'observations_parsed': 0, 'records_written': 0,
                'error': str(exc), 'error_type': type(exc).__name__, 'table_id': table_id}


def update_hong_kong_macro(db_path, full_history=False, start_year=None):
    started = datetime.now().isoformat()
    run_id = uuid.uuid4().hex
    source_status = {}
    records_parsed = records_written = 0
    with closing(connect(db_path)) as conn:
        ensure_hong_kong_macro_tables(conn)
        conn.execute('''INSERT INTO hong_kong_macro_update_runs
            (run_id,started_at,status,full_history,source_status_json,records_parsed,records_written,error_count)
            VALUES (?,?,?,?,?,?,?,?)''',
                     (run_id, started, 'running', int(bool(full_history)), '{}', 0, 0, 0))
        conn.commit()
        session = _new_session()

        # RVD: discover the page first, then fetch only the six listed official files.
        try:
            def rvd_job():
                page_content, jobs = _fetch_rvd(session)
                rows = []
                digest = hashlib.sha256(page_content).hexdigest()
                raw_path, _ = _save_raw('HK_RVD_INDEX', page_content, 'html')
                for code, url, content, file_digest, _file_path in jobs:
                    parsed = _parse_rvd_workbook(code, content, url)
                    for row in parsed:
                        row['raw_sha256'] = file_digest
                        row['_raw_path'] = _file_path
                    rows.extend(parsed)
                rows = _filter_start(rows, start_year)
                return rows, raw_path, digest
            result = _run_source(conn, 'HK_RVD_PRICE_INDEX', rvd_job)
            # The RVD workbook includes several datasets, so reflect the same fetch
            # under source records for coverage even though observations carry their
            # precise source id from the parser.
            for source_id in ('HK_RVD_AVG_RENT', 'HK_RVD_AVG_PRICE', 'HK_RVD_RENT_INDEX',
                              'HK_RVD_PRICE_INDEX',
                              'HK_RVD_DOMESTIC_SALES', 'HK_RVD_PRIVATE_STOCK_FLOW'):
                detail = (result.get('source_breakdown') or {}).get(source_id, {})
                _update_source_state(conn, source_id, status=result['status'],
                                     last_success_at=datetime.now().isoformat() if result['status'] == 'success' else None,
                                     raw_path=detail.get('raw_path') or result.get('raw_path'),
                                     raw_sha256=detail.get('raw_sha256') or result.get('raw_sha256'),
                                     record_count=detail.get('record_count', 0),
                                     latest_reference_period=detail.get('latest_reference_period'),
                                     error_message=result.get('error'))
            source_status['HK_RVD_PRICE_INDEX'] = result
            records_parsed += result['observations_parsed']; records_written += result['records_written']
        except Exception as exc:
            source_status['HK_RVD_PRICE_INDEX'] = {'status': 'failed', 'error': str(exc)}

        def land_job():
            records, raw_path, digest = _fetch_landreg(session, full_history)
            return _filter_start(parse_landreg_primary_rows(records, source_url=LANDREG_BASE), start_year), raw_path, digest
        result = _run_source(conn, 'HK_LANDREG_PRIMARY', land_job)
        source_status['HK_LANDREG_PRIMARY'] = result
        records_parsed += result['observations_parsed']; records_written += result['records_written']

        for source_id in ('HK_HKMA_FC_RESERVE_ASSETS', 'HK_HKMA_ECONOMIC', 'HK_HKMA_MONETARY',
                          'HK_HKMA_BANKING_STATS', 'HK_HKMA_CUSTOMER_DEPOSITS',
                          'HK_HKMA_RMB_DEPOSITS', 'HK_HKMA_LOANS_BY_TYPE',
                          'HK_HKMA_MORTGAGE_SURVEY', 'HK_HKMA_NEGATIVE_EQUITY'):
            def hkma_job(source_id=source_id):
                records = _fetch_hkma_all(session, HKMA_URLS[source_id],
                                          HKMA_REQUEST_PARAMS.get(source_id))
                raw = json.dumps(records, ensure_ascii=False, sort_keys=True).encode('utf-8')
                raw_path, digest = _save_raw(source_id, raw, 'json')
                return _filter_start(parse_hkma_records(records, source_id), start_year), raw_path, digest
            result = _run_source(conn, source_id, hkma_job)
            source_status[source_id] = result
            records_parsed += result['observations_parsed']; records_written += result['records_written']

        def trade_job():
            payload, raw_path, digest = _fetch_trade(session, full_history, start_year)
            rows = parse_trade_idds_payload(payload)
            rows.extend(derive_trade_rows(rows, raw_sha256=digest))
            return _filter_start(rows, start_year), raw_path, digest
        result = _run_source(conn, 'HK_TRADE_IDDS', trade_job)
        source_status['HK_TRADE_IDDS'] = result
        records_parsed += result['observations_parsed']; records_written += result['records_written']

        for request_key, request in TRADE_DIMENSION_REQUESTS.items():
            def trade_dimension_job(request_key=request_key):
                payload, raw_path, digest = _fetch_trade_dimension(
                    session, request_key, full_history, start_year)
                rows = parse_trade_dimension_payload(payload, request_key,
                                                     raw_sha256=digest)
                return rows, raw_path, digest
            result = _run_trade_dimension_source(conn, request['source_id'], trade_dimension_job)
            source_status[request['source_id']] = result
            records_parsed += result['observations_parsed']; records_written += result['records_written']

        for table_id, source_id, codes in (
            (6, 'HK_CSD_CTT_6', ['HK_CSD_COMPOSITE_CPI_INDEX', 'HK_CSD_GDP_REAL_ANNUAL',
                                 'HK_CSD_TOTAL_EXPORTS_YOY_ANNUAL', 'HK_CSD_UNEMPLOYMENT_RATE_ANNUAL']),
            (8, 'HK_CSD_CTT_8', ['HK_CSD_COMPOSITE_CPI_YOY_ANNUAL', 'HK_CSD_GDP_REAL_YOY_ANNUAL']),
        ):
            def csd_job(table_id=table_id, source_id=source_id, codes=codes):
                payload, url, raw_path, digest = _fetch_csd(session, table_id)
                return _filter_start(parse_csd_ctt_payload(payload, source_id, codes), start_year), raw_path, digest
            result = _run_source(conn, source_id, csd_job)
            source_status[source_id] = result
            records_parsed += result['observations_parsed']; records_written += result['records_written']

        for table_id in CSD_WEB_UPDATE_TABLES:
            source_id = f'HK_CSD_WEB_{table_id}'
            def csd_web_job(table_id=table_id):
                payload, url, raw_path, digest = _fetch_csd_web_table(session, table_id)
                rows = parse_csd_web_table_payload(payload, table_id, url, digest)
                return _filter_start(rows, start_year), raw_path, digest
            result = _run_csd_web_table_source(conn, source_id, table_id, csd_web_job)
            source_status[source_id] = result
            records_parsed += result['observations_parsed']; records_written += result['records_written']

        errors = [item.get('error') for item in source_status.values()
                  if item.get('status') in ('failed', 'blocked')]
        if records_written and errors:
            status = 'partial'
        elif records_written or not errors:
            status = 'completed'
        else:
            status = 'failed'
        conn.execute('''UPDATE hong_kong_macro_update_runs SET finished_at=?,status=?,source_status_json=?,
            records_parsed=?,records_written=?,error_count=?,error_message=? WHERE run_id=?''',
                     (datetime.now().isoformat(), status, json.dumps(source_status, ensure_ascii=False),
                      records_parsed, records_written, len(errors), '; '.join(errors)[:4000], run_id))
        ensure_hong_kong_macro_tables(conn, refresh_metadata=True)
        conn.commit()
    return {'success': status in ('completed', 'partial'), 'run_id': run_id,
            'started_at': started, 'finished_at': datetime.now().isoformat(),
            'status': status, 'full_history': bool(full_history), 'start_year': start_year,
            'records_parsed': records_parsed, 'records_written': records_written,
            'source_status': source_status, 'errors': errors}
