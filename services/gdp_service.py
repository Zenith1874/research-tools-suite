# -*- coding: utf-8 -*-
"""中美 GDP：全国可比序列与官方地区 GDP。

全国现价美元来自 World Bank 经 FRED 免 key CSV；美国州级来自 BEA SAGDP。
中国省级只接受国家统计局官方年鉴值：优先 XLS，只有官方 JPG 时使用
整表严格校验的本地 OCR 回退；不使用第三方或插值。
"""
import csv
import io
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime

import requests
import xlrd
from services.regional_fiscal_service import (
    ensure_regional_fiscal_table, update_regional_fiscal, build_regional_fiscal_payload,
    CN_PROVINCES,
)
from services.nbs_yearbook_ocr import extract_nbs_yearbook_image_values

UA = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'),
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}
FRED_SERIES = {'CN': 'MKTGDPCNA646NWDB', 'US': 'MKTGDPUSA646NWDB'}
BEA_ZIP = 'https://apps.bea.gov/regional/zip/SAGDP.zip'
# SIC 口径历史(1963-1997,仅名义值);与 NAICS 行业分类不同,1997 年有轻微断点,
# 不与 1997 起的 NAICS 序列直接拼接,入库用独立 indicator_code。
BEA_SIC_ZIP = 'https://apps.bea.gov/regional/zip/SAGDP_SIC.zip'
NBS_API = 'https://data.stats.gov.cn/easyquery.htm'
NBS_YEARBOOK_GDP_XLS = {
    '2010': 'https://www.stats.gov.cn/sj/ndsj/2011/html/C0215C.xls',
    '2011': 'https://www.stats.gov.cn/sj/ndsj/2012/html/C0215C.xls',
    '2012': 'https://www.stats.gov.cn/sj/ndsj/2013/html/Z0216C.xls',
    '2013': 'https://www.stats.gov.cn/sj/ndsj/2014/zk/html/Z0316C.xls',
    '2020': 'https://www.stats.gov.cn/sj/ndsj/2021/html/C03-09.xls',
}
NBS_YEARBOOK_GDP_IMAGES = {
    '2014': 'https://www.stats.gov.cn/sj/ndsj/2015/html/CH0309.jpg',
    '2015': 'https://www.stats.gov.cn/sj/ndsj/2016/html/0309CH.jpg',
    '2016': 'https://www.stats.gov.cn/sj/ndsj/2017/html/CH0309.jpg',
    '2017': 'https://www.stats.gov.cn/sj/ndsj/2018/html/CH0309.jpg',
    '2018': 'https://www.stats.gov.cn/sj/ndsj/2019/html/C0309.jpg',
    '2019': 'https://www.stats.gov.cn/sj/ndsj/2020/html/C0309.jpg',
    '2020': 'https://www.stats.gov.cn/sj/ndsj/2021/html/C03-09.jpg',
    '2021': 'https://www.stats.gov.cn/sj/ndsj/2022/html/C03-09.jpg',
    '2022': 'https://www.stats.gov.cn/sj/ndsj/2023/html/C03-09.jpg',
    '2023': 'https://www.stats.gov.cn/sj/ndsj/2024/html/C03-09.jpg',
    '2024': 'https://www.stats.gov.cn/sj/ndsj/2025/html/C03-09.jpg',
}
# The 2015 and 2016 yearbooks show a five-year history; the current year is
# the fifth numeric column.  Later images are single-year industry tables.
NBS_YEARBOOK_GDP_IMAGE_COLUMNS = {'2014': 4, '2015': 4}


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_gdp_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS gdp_national_observations (
      id INTEGER PRIMARY KEY, country_code TEXT, indicator_code TEXT, period TEXT,
      value REAL, unit TEXT, data_status TEXT, source_name TEXT, source_url TEXT,
      parser_notes TEXT, updated_at TEXT,
      UNIQUE(country_code, indicator_code, period))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS gdp_region_observations (
      id INTEGER PRIMARY KEY, country_code TEXT, region_code TEXT, region_name TEXT,
      indicator_code TEXT, period TEXT, value REAL, unit TEXT, data_status TEXT,
      source_name TEXT, source_url TEXT, parser_notes TEXT, updated_at TEXT,
      UNIQUE(country_code, region_code, indicator_code, period))''')
    conn.commit()


def parse_fred_csv(text):
    reader = csv.reader(io.StringIO(text)); next(reader, None)
    out = []
    for row in reader:
        if len(row) >= 2 and row[1] not in ('', '.'):
            out.append((row[0][:4], float(row[1])))
    return out


def parse_bea_sagdp_csv(text, line_map=None):
    """读取 BEA ALL_AREAS 文件，只保留 50 州与 DC。
    NAICS 表(SAGDP1)默认 LineCode 1=实际/3=名义;SIC 表(SAGDP2S)传
    {'1':'nominal_gdp_sic'}(SIC 只有现价名义值)。"""
    line_map = line_map or {'1': 'real_gdp', '3': 'nominal_gdp'}
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        fips = (row.get('GeoFIPS') or '').strip().strip('"')
        if len(fips) != 5 or not fips.endswith('000') or fips == '00000':
            continue
        state_fips = fips[:2]
        if state_fips in {'00', '91', '92', '93', '94', '95', '96', '97', '98'}:
            continue
        line = (row.get('LineCode') or '').strip()
        code = line_map.get(line)
        if not code:
            continue
        name = (row.get('GeoName') or '').strip().rstrip(' *')
        for year, raw in row.items():
            if not year.isdigit() or len(year) != 4 or raw in (None, '', '(NA)'):
                continue
            try: value = float(raw.replace(',', ''))
            except ValueError: continue
            out.append({'region_code': state_fips, 'region_name': name,
                        'indicator_code': code, 'period': year, 'value': value})
    return out


def parse_nbs_province_gdp_sheet(sheet, period):
    rows = []
    for row_index in range(sheet.nrows):
        raw_name = str(sheet.cell_value(row_index, 0) or '')
        compact = ''.join(raw_name.split())
        identity = next(((code, short) for short, code in CN_PROVINCES.items()
                         if compact.startswith(short)), None)
        if not identity or sheet.ncols < 2:
            continue
        raw_value = sheet.cell_value(row_index, 1)
        if not isinstance(raw_value, (int, float)) or raw_value <= 0:
            continue
        code, name = identity
        rows.append({'region_code': code, 'region_name': name,
                     'indicator_code': 'nominal_gdp', 'period': str(period),
                     'value': round(float(raw_value), 4)})
    if len({row['region_code'] for row in rows}) != 31:
        raise ValueError(f'NBS yearbook {period}: expected 31 provinces, got {len(rows)}')
    return rows


def parse_nbs_province_gdp_xls(content, period):
    """Parse the NBS China Statistical Yearbook province GDP column (亿元)."""
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    return parse_nbs_province_gdp_sheet(sheet, period)


def parse_nbs_province_gdp_image(content, period, value_column=0):
    """Extract the configured GDP column from an official yearbook JPEG."""
    if value_column < 0:
        raise ValueError('value_column must be non-negative')
    extracted = extract_nbs_yearbook_image_values(
        content, needed_columns=value_column + 1)
    provinces = [(code, name) for name, code in CN_PROVINCES.items()]
    rows = []
    for (code, name), item in zip(provinces, extracted):
        value = item['values'][value_column]
        if value <= 0:
            raise ValueError(f'NBS yearbook {period} {name}: GDP must be positive')
        rows.append({'region_code': code, 'region_name': name,
                     'indicator_code': 'nominal_gdp', 'period': str(period),
                     'value': round(float(value), 4),
                     'ocr_confidence': item['confidence']})
    if len(rows) != 31:
        raise ValueError(f'NBS yearbook {period}: expected 31 provinces, got {len(rows)}')
    return rows


def derive_yoy(rows):
    by_year = {int(r['period']): r['value'] for r in rows}
    return [{'period': str(y), 'value': round((v / by_year[y-1] - 1) * 100, 4)}
            for y, v in sorted(by_year.items()) if y-1 in by_year and by_year[y-1]]


def update_gdp(db_path):
    errors, counts = [], {'national': 0, 'us_regions': 0, 'cn_regions': 0}
    now = datetime.now().isoformat()
    with closing(connect(db_path)) as conn:
        ensure_gdp_tables(conn)
        ensure_regional_fiscal_table(conn)
        for country, code in FRED_SERIES.items():
            try:
                url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}'
                response = requests.get(url, headers=UA, timeout=30); response.raise_for_status()
                for period, value in parse_fred_csv(response.text):
                    conn.execute('''INSERT INTO gdp_national_observations VALUES
                      (NULL,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(country_code,indicator_code,period)
                      DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at''',
                      (country, 'nominal_usd', period, value, 'current US$', 'official',
                       'World Bank via FRED', f'https://fred.stlouisfed.org/series/{code}',
                       'World Bank national accounts; FRED official mirror', now))
                    counts['national'] += 1
            except Exception as exc: errors.append(f'{country} national: {exc}')
        try:
            response = requests.get(BEA_ZIP, headers=UA, timeout=60); response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                name = next(n for n in zf.namelist() if 'SAGDP1__ALL_AREAS' in n)
                rows = parse_bea_sagdp_csv(zf.read(name).decode('utf-8-sig'))
            for row in rows:
                conn.execute('''INSERT INTO gdp_region_observations VALUES
                  (NULL,'US',?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(country_code,region_code,indicator_code,period)
                  DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at''',
                  (row['region_code'], row['region_name'], row['indicator_code'], row['period'],
                   row['value'], 'million chained 2017 US$' if row['indicator_code']=='real_gdp' else 'million current US$',
                   'official', 'U.S. Bureau of Economic Analysis',
                   'https://www.bea.gov/data/gdp/gdp-state', 'BEA SAGDP annual table', now))
                counts['us_regions'] += 1
        except Exception as exc: errors.append(f'US regions: {exc}')
        # SIC 历史(1963-1997)是冻结数据集:库里已有就不再重复下载 7MB
        have_sic = conn.execute("""SELECT COUNT(*) FROM gdp_region_observations
            WHERE country_code='US' AND indicator_code='nominal_gdp_sic'""").fetchone()[0]
        if have_sic < 1700:   # 51 地区 × 35 年 = 1785,留余量判断完整性
            try:
                response = requests.get(BEA_SIC_ZIP, headers=UA, timeout=90); response.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                    name = next(n for n in zf.namelist() if 'SAGDP2S__ALL_AREAS' in n)
                    rows = parse_bea_sagdp_csv(zf.read(name).decode('utf-8-sig'),
                                               line_map={'1': 'nominal_gdp_sic'})
                for row in rows:
                    conn.execute('''INSERT INTO gdp_region_observations VALUES
                      (NULL,'US',?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(country_code,region_code,indicator_code,period)
                      DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at''',
                      (row['region_code'], row['region_name'], row['indicator_code'], row['period'],
                       row['value'], 'million current US$', 'official',
                       'U.S. Bureau of Economic Analysis',
                       'https://apps.bea.gov/regional/zip/SAGDP_SIC.zip',
                       'BEA SAGDP2S,SIC 行业分类口径 1963-1997;与 1997 起 NAICS 序列存在口径断点,不直接拼接', now))
                    counts['us_regions'] += 1
            except Exception as exc: errors.append(f'US SIC regions: {exc}')
        for period, url in NBS_YEARBOOK_GDP_XLS.items():
            have = conn.execute("""SELECT COUNT(*) FROM gdp_region_observations
                WHERE country_code='CN' AND indicator_code='nominal_gdp' AND period=?""",
                (period,)).fetchone()[0]
            if have >= 31:
                continue
            try:
                response = requests.get(url, headers=UA, timeout=60); response.raise_for_status()
                if not response.content.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
                    raise ValueError('response is not an Excel BIFF file')
                for row in parse_nbs_province_gdp_xls(response.content, period):
                    conn.execute('''INSERT INTO gdp_region_observations VALUES
                      (NULL,'CN',?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(country_code,region_code,indicator_code,period)
                      DO UPDATE SET value=excluded.value,source_url=excluded.source_url,
                                    parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
                      (row['region_code'], row['region_name'], row['indicator_code'], row['period'],
                       row['value'], '亿元', 'official', '国家统计局《中国统计年鉴》', url,
                       '年鉴官方XLS“地区生产总值”列；当年价格。缺失年份不插值。', now))
                    counts['cn_regions'] += 1
            except Exception as exc:
                errors.append(f'CN regions {period}: {exc}')
        for period, url in NBS_YEARBOOK_GDP_IMAGES.items():
            have = conn.execute("""SELECT COUNT(*) FROM gdp_region_observations
                WHERE country_code='CN' AND indicator_code='nominal_gdp' AND period=?""",
                (period,)).fetchone()[0]
            value_column = NBS_YEARBOOK_GDP_IMAGE_COLUMNS.get(period, 0)
            parser_tag = f'第{value_column + 1}数值列'
            tagged = conn.execute("""SELECT COUNT(*) FROM gdp_region_observations
                WHERE country_code='CN' AND indicator_code='nominal_gdp' AND period=?
                AND parser_notes LIKE ?""", (period, f'%{parser_tag}%')).fetchone()[0]
            if have >= 31 and (value_column == 0 or tagged >= 31):
                continue
            try:
                response = requests.get(url, headers=UA, timeout=60); response.raise_for_status()
                for row in parse_nbs_province_gdp_image(
                        response.content, period, value_column=value_column):
                    conn.execute('''INSERT INTO gdp_region_observations VALUES
                      (NULL,'CN',?,?,?,?,?,?,?,?,?,?,?)
                      ON CONFLICT(country_code,region_code,indicator_code,period)
                      DO UPDATE SET value=excluded.value,source_url=excluded.source_url,
                                    parser_notes=excluded.parser_notes,updated_at=excluded.updated_at''',
                      (row['region_code'], row['region_name'], row['indicator_code'], row['period'],
                       row['value'], '亿元', 'official', '国家统计局《中国统计年鉴》', url,
                       f'年鉴官方JPG{parser_tag}；本地OCR最低置信度{row["ocr_confidence"]:.3f}；'
                       '固定31省顺序，整表校验通过；缺失年份不插值。', now))
                    counts['cn_regions'] += 1
            except Exception as exc:
                errors.append(f'CN regions image {period}: {exc}')
        conn.commit()
        regional_fiscal = update_regional_fiscal(conn)
        stored_cn_regions = conn.execute("""SELECT COUNT(DISTINCT region_code)
          FROM gdp_region_observations WHERE country_code='CN'
          AND indicator_code='nominal_gdp'""").fetchone()[0]
        stored_cn_years = conn.execute("""SELECT COUNT(*) FROM (
          SELECT period FROM gdp_region_observations WHERE country_code='CN'
          AND indicator_code='nominal_gdp' GROUP BY period
          HAVING COUNT(DISTINCT region_code)=31)""").fetchone()[0]
    return {'success': counts['national'] > 0 or counts['us_regions'] > 0 or counts['cn_regions'] > 0,
            'records_upserted': counts, 'errors': errors + regional_fiscal['errors'],
            'regional_fiscal': regional_fiscal,
            'china_regions': {'status': 'official' if stored_cn_regions == 31 else 'source_blocked',
              'reason': ('国家数据 API 当前海外 IP 返回 403；改用官方《中国统计年鉴》XLS与JPG。'
                         f'当前完整覆盖{stored_cn_years}个年份；JPG仅在31省整表与置信度校验通过后入库，不使用第三方或插值。'),
              'source_url': NBS_API}}


def _rows(conn, sql, args=()): return [dict(r) for r in conn.execute(sql, args)]


def build_gdp_payload(db_path):
    with closing(connect(db_path)) as conn:
        ensure_gdp_tables(conn)
        national = {}
        for country in ('CN', 'US'):
            rs = _rows(conn, '''SELECT period,value FROM gdp_national_observations
                                WHERE country_code=? AND indicator_code='nominal_usd' ORDER BY period''', (country,))
            national[country] = {'series': rs, 'growth': derive_yoy(rs), 'latest': rs[-1] if rs else None}
        regions = {}
        for country in ('CN', 'US'):
            data = _rows(conn, '''SELECT region_code,region_name,indicator_code,period,value,unit
                                 FROM gdp_region_observations WHERE country_code=? ORDER BY period,region_name''', (country,))
            if country == 'CN':
                # 本表同时存省级行政区与地级市（城市经济模块用）。省级视图只要
                # 省级码，否则上海/北京会各出现两次、深圳广州等城市混进省级排行。
                data = [row for row in data if row['region_code'].endswith('0000')]
            regions[country] = data
        us_years = sorted({r['period'] for r in regions['US']}, reverse=True)
        cn_years = sorted({r['period'] for r in regions['CN']}, reverse=True)
        return {'generated_at': datetime.now().isoformat(), 'national': national,
                'regions': regions, 'coverage': {'national_start': '1960', 'national_end': national['US']['latest']['period'] if national['US']['latest'] else None,
                'US': {'years': us_years, 'regions': len({r['region_code'] for r in regions['US']})},
                'CN': {'years': cn_years, 'regions': len({r['region_code'] for r in regions['CN']})}},
                'china_region_source': {'status': 'source_blocked' if not regions['CN'] else 'official',
                  'message': ('统计局国家数据接口在当前海外网络返回 403；已接入官方年鉴 XLS，'
                              '仅对官方高清 JPG 使用本地严格 OCR 回退。每张表必须通过31省行数、'
                              '目标列置信度与异常检查；不用第三方或插值。'),
                  'source_url': 'https://data.stats.gov.cn/'},
                'regional_fiscal': build_regional_fiscal_payload(conn),
                'methods': {'national': 'World Bank 现价美元年度 GDP，经 FRED 镜像；用于规模比较。',
                  'CN': ('国家统计局《中国统计年鉴》官方 XLS/JPG，地区生产总值按当年价格、单位亿元；'
                         'JPG 使用固定版式列映射与本地 OCR，整表不通过即拒绝，缺值不插值。'),
                  'US': 'BEA SAGDP：1997 起为 NAICS 口径（实际值 2017 年链式美元、名义值当年美元）；1963–1997 为 SIC 口径历史（仅名义值），两套行业分类在 1997 年存在口径断点，图中以虚线区分、不做拼接。'}}
