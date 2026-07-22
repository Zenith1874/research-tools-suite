# -*- coding: utf-8 -*-
"""中美 GDP：全国可比序列与官方地区 GDP。

全国现价美元来自 World Bank 经 FRED 免 key CSV；美国州级来自 BEA SAGDP。
中国省级只接受国家统计局结构化官方值，当前海外 IP 403 时保留明确缺口。
"""
import csv
import io
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime

import requests

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
FRED_SERIES = {'CN': 'MKTGDPCNA646NWDB', 'US': 'MKTGDPUSA646NWDB'}
BEA_ZIP = 'https://apps.bea.gov/regional/zip/SAGDP.zip'
# SIC 口径历史(1963-1997,仅名义值);与 NAICS 行业分类不同,1997 年有轻微断点,
# 不与 1997 起的 NAICS 序列直接拼接,入库用独立 indicator_code。
BEA_SIC_ZIP = 'https://apps.bea.gov/regional/zip/SAGDP_SIC.zip'
NBS_API = 'https://data.stats.gov.cn/easyquery.htm'


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


def derive_yoy(rows):
    by_year = {int(r['period']): r['value'] for r in rows}
    return [{'period': str(y), 'value': round((v / by_year[y-1] - 1) * 100, 4)}
            for y, v in sorted(by_year.items()) if y-1 in by_year and by_year[y-1]]


def update_gdp(db_path):
    errors, counts = [], {'national': 0, 'us_regions': 0, 'cn_regions': 0}
    now = datetime.now().isoformat()
    with closing(connect(db_path)) as conn:
        ensure_gdp_tables(conn)
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
        conn.commit()
    return {'success': counts['national'] > 0 or counts['us_regions'] > 0,
            'records_upserted': counts, 'errors': errors,
            'china_regions': {'status': 'source_blocked', 'reason': '统计局国家数据 API 当前海外 IP 返回 403；年鉴表为图片，未以 OCR 值冒充结构化官方数据。', 'source_url': NBS_API}}


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
            regions[country] = data
        us_years = sorted({r['period'] for r in regions['US']}, reverse=True)
        cn_years = sorted({r['period'] for r in regions['CN']}, reverse=True)
        return {'generated_at': datetime.now().isoformat(), 'national': national,
                'regions': regions, 'coverage': {'national_start': '1960', 'national_end': national['US']['latest']['period'] if national['US']['latest'] else None,
                'US': {'years': us_years, 'regions': len({r['region_code'] for r in regions['US']})},
                'CN': {'years': cn_years, 'regions': len({r['region_code'] for r in regions['CN']})}},
                'china_region_source': {'status': 'source_blocked' if not regions['CN'] else 'official',
                  'message': '统计局国家数据接口在当前海外网络返回 403；官方年鉴地区表为图片。缺失不以第三方或 OCR 猜测补齐。',
                  'source_url': 'https://data.stats.gov.cn/'},
                'methods': {'national': 'World Bank 现价美元年度 GDP，经 FRED 镜像；用于规模比较。',
                  'US': 'BEA SAGDP：1997 起为 NAICS 口径（实际值 2017 年链式美元、名义值当年美元）；1963–1997 为 SIC 口径历史（仅名义值），两套行业分类在 1997 年存在口径断点，图中以虚线区分、不做拼接。'}}
