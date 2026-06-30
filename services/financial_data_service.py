import json
import re
import sqlite3
from datetime import datetime

from .financial_dictionary import INDICATORS, FIELD_TO_INDICATOR, SOURCE_REGISTRY, SOURCE_BY_INDICATOR
from .market_fetcher import get_market_data

PBOC_FIELDS = [
    'M2', 'M2y', 'M1', 'M1y', 'M0y', 'SF', 'SFy', 'loan', 'loany', 'dep', 'depy', 'ibor', 'repo',
    'loan_ytd', 'loan_hh_ytd', 'loan_hh_st_ytd', 'loan_hh_lt_ytd',
    'loan_corp_ytd', 'loan_corp_st_ytd', 'loan_corp_lt_ytd', 'loan_bill_ytd', 'loan_nbfi_ytd',
    'loan_hh_bal', 'loan_hh_st_bal', 'loan_hh_lt_bal', 'loan_hh_lt_cons_bal',
    'loan_corp_bal', 'loan_corp_st_bal', 'loan_corp_lt_bal', 'loan_bill_bal', 'loan_nbfi_bal',
    'fx_dep', 'fx_dep_y', 'fx_dep_ytd',
]

API_FIELD_MAP = {
    'M2': 'M2_BALANCE', 'M2y': 'M2_YOY', 'M1': 'M1_BALANCE', 'M1y': 'M1_YOY', 'M0y': 'M0_YOY',
    'SF': 'TSF_STOCK', 'SFy': 'TSF_YOY', 'loan': 'RMB_LOAN_BALANCE', 'loany': 'RMB_LOAN_YOY',
    'dep': 'RMB_DEPOSIT_BALANCE', 'depy': 'RMB_DEPOSIT_YOY', 'ibor': 'IBOR_WEIGHTED_AVG',
    'repo': 'PLEDGED_REPO_WEIGHTED_AVG',
}

STRUCTURE_FIELD_MAP = {
    'loan_hh_bal': 'HOUSEHOLD_LOAN_BALANCE',
    'loan_hh_st_bal': 'HOUSEHOLD_SHORT_LOAN_BALANCE',
    'loan_hh_lt_bal': 'HOUSEHOLD_LONG_LOAN_BALANCE',
    'loan_hh_lt_cons_bal': 'HOUSEHOLD_LONG_CONSUMPTION_LOAN_BALANCE',
    'loan_corp_bal': 'CORPORATE_LOAN_BALANCE',
    'loan_corp_st_bal': 'CORPORATE_SHORT_LOAN_BALANCE',
    'loan_corp_lt_bal': 'CORPORATE_LONG_LOAN_BALANCE',
    'loan_bill_bal': 'BILL_FINANCING_BALANCE',
    'loan_nbfi_bal': 'NBFI_LOAN_BALANCE',
    'loan_ytd': 'RMB_LOAN_YTD',
    'loan_hh_ytd': 'HOUSEHOLD_LOAN_YTD',
    'loan_hh_st_ytd': 'HOUSEHOLD_SHORT_LOAN_YTD',
    'loan_hh_lt_ytd': 'HOUSEHOLD_LONG_LOAN_YTD',
    'loan_corp_ytd': 'CORPORATE_LOAN_YTD',
    'loan_corp_st_ytd': 'CORPORATE_SHORT_LOAN_YTD',
    'loan_corp_lt_ytd': 'CORPORATE_LONG_LOAN_YTD',
    'loan_bill_ytd': 'BILL_FINANCING_YTD',
    'loan_nbfi_ytd': 'NBFI_LOAN_YTD',
}

def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_financial_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS financial_observations (
        id INTEGER PRIMARY KEY,
        indicator_code TEXT,
        indicator_name TEXT,
        value REAL,
        unit_raw TEXT,
        unit_display TEXT,
        scale_factor REAL,
        period TEXT,
        date TEXT,
        frequency TEXT,
        source_type TEXT,
        source_name TEXT,
        source_url TEXT,
        source_title TEXT,
        published_date TEXT,
        parser_notes TEXT,
        data_status TEXT,
        is_mock INTEGER,
        is_seed INTEGER,
        is_cache INTEGER,
        is_ytd INTEGER,
        is_monthly_increment INTEGER,
        is_stock INTEGER,
        yoy REAL,
        mom REAL,
        notes TEXT,
        created_at TEXT,
        updated_at TEXT,
        UNIQUE(indicator_code, period, source_type)
    )''')
    for col, typ in [
        ('source_title', 'TEXT'),
        ('published_date', 'TEXT'),
        ('parser_notes', 'TEXT'),
    ]:
        try:
            conn.execute(f'ALTER TABLE financial_observations ADD COLUMN {col} {typ}')
        except sqlite3.OperationalError:
            pass
    conn.execute('''CREATE TABLE IF NOT EXISTS financial_source_registry (
        source_key TEXT PRIMARY KEY,
        source_name TEXT,
        source_type TEXT,
        source_label TEXT,
        entry_url TEXT,
        candidate_paths TEXT,
        parser_notes TEXT,
        updated_at TEXT
    )''')
    now = datetime.now().isoformat()
    for key, src in SOURCE_REGISTRY.items():
        conn.execute('''INSERT INTO financial_source_registry (
            source_key,source_name,source_type,source_label,entry_url,candidate_paths,parser_notes,updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(source_key) DO UPDATE SET
            source_name=excluded.source_name,
            source_type=excluded.source_type,
            source_label=excluded.source_label,
            entry_url=excluded.entry_url,
            candidate_paths=excluded.candidate_paths,
            parser_notes=excluded.parser_notes,
            updated_at=excluded.updated_at
        ''', (
            key, src.get('source_name'), src.get('source_type'), src.get('source_label'),
            src.get('entry_url'), json.dumps(src.get('candidate_paths', []), ensure_ascii=False),
            src.get('parser_notes'), now
        ))
    conn.execute('''CREATE TABLE IF NOT EXISTS financial_update_logs (
        id INTEGER PRIMARY KEY,
        source_name TEXT,
        source_type TEXT,
        started_at TEXT,
        finished_at TEXT,
        success INTEGER,
        new_records INTEGER,
        updated_records INTEGER,
        error_message TEXT,
        warnings TEXT
    )''')
    conn.commit()

def source_status(row):
    src = row['source_url']
    if src == 'manual':
        return 'seed', 'manual', 1
    if src == 'seed':
        return 'seed', 'seed', 1
    if src and str(src).startswith('http'):
        return 'cache', 'pboc_monthly', 0
    return 'missing', 'manual', 0

def extract_source_meta(row):
    html = row['raw_html'] if 'raw_html' in row.keys() else None
    text = ''
    if html:
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.I | re.S)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
    title = None
    if text:
        m = re.search(r'((?:19|20)\d{2}年(?:\d{1,2}月|一季度|上半年|前三季度)?(?:金融统计数据报告|社会融资规模存量统计数据报告|社会融资规模增量统计数据报告))', text)
        if m:
            title = m.group(1)
    if not title:
        title = f"{row['month']} 中国人民银行金融统计数据报告"
    published_date = None
    if text:
        m = re.search(r'((?:19|20)\d{2}-\d{2}-\d{2})\s+\d{1,2}:\d{2}', text)
        if m:
            published_date = m.group(1)
    return title, published_date

def source_meta_for_indicator(code, row):
    source_key = SOURCE_BY_INDICATOR.get(code, 'pboc_financial_statistics_report')
    registry = SOURCE_REGISTRY.get(source_key, SOURCE_REGISTRY['pboc_financial_statistics_report'])
    title, published_date = extract_source_meta(row)
    notes = registry.get('parser_notes', '')
    if code in {'TSF_STOCK', 'TSF_YOY'} and '社会融资规模存量统计数据报告' not in (title or ''):
        notes += ' 当前缓存原文不是独立社融存量报告时，保留实际解析公告 URL，并在 registry 中标记专用候选入口。'
    return {
        'source_name': registry.get('source_name', '中国人民银行'),
        'source_type': registry.get('source_type', 'pboc_monthly'),
        'source_url': row['source_url'],
        'source_title': title,
        'published_date': published_date,
        'parser_notes': notes,
    }

def legacy_row(row):
    d = {'m': row['month']}
    for field in PBOC_FIELDS:
        if field in row.keys() and row[field] is not None:
            d[field] = row[field]
    return d

def structured_pboc_record(row):
    data_status, source_type, is_seed = source_status(row)
    rec = {
        'period': row['month'],
        'source_name': '中国人民银行',
        'source_url': row['source_url'],
        'data_status': data_status,
        'source_type': source_type,
        'is_seed': bool(is_seed),
        'is_mock': False,
        'is_cache': data_status == 'cache',
    }
    for old, new in API_FIELD_MAP.items():
        rec[new] = row[old]
    rec['source_title'], rec['published_date'] = extract_source_meta(row)
    rec['parser_notes'] = '行级来源为该月公告原文；字段级来源详见 indicator_sources。'
    rec['indicator_sources'] = {}
    for old, code in API_FIELD_MAP.items():
        if row[old] is not None:
            rec['indicator_sources'][code] = source_meta_for_indicator(code, row)
    return rec

def structure_record(row):
    data_status, source_type, is_seed = source_status(row)
    rec = {
        'period': row['month'],
        'source_name': '中国人民银行',
        'source_url': row['source_url'],
        'data_status': data_status,
        'source_type': source_type,
        'is_seed': bool(is_seed),
        'is_mock': False,
        'is_cache': data_status == 'cache',
    }
    for old, new in STRUCTURE_FIELD_MAP.items():
        if old in row.keys():
            rec[new] = row[old]
    rec['source_title'], rec['published_date'] = extract_source_meta(row)
    rec['parser_notes'] = '贷款结构字段来自央行公告正文或信贷收支统计表缓存；空值不补 0。'
    rec['is_balance'] = any(rec.get(code) is not None for code in [
        'HOUSEHOLD_LOAN_BALANCE', 'CORPORATE_LOAN_BALANCE', 'BILL_FINANCING_BALANCE'
    ])
    rec['is_ytd'] = any(rec.get(code) is not None for code in [
        'RMB_LOAN_YTD', 'HOUSEHOLD_LOAN_YTD', 'CORPORATE_LOAN_YTD'
    ])
    return rec

def latest_period(records):
    return records[-1]['period'] if records else None

def build_api_payload(db_path):
    with connect(db_path) as conn:
        ensure_financial_tables(conn)
        cols = ','.join(['month'] + PBOC_FIELDS + ['scraped_at', 'source_url', 'raw_html'])
        rows = conn.execute(f'SELECT {cols} FROM monthly_data ORDER BY month').fetchall()
        last = conn.execute(
            "SELECT scraped_at FROM scrape_log WHERE status='ok' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    legacy = [legacy_row(r) for r in rows]
    pboc_records = [structured_pboc_record(r) for r in rows if any(r[f] is not None for f in API_FIELD_MAP)]
    loan_records = [structure_record(r) for r in rows if any(r[f] is not None for f in STRUCTURE_FIELD_MAP if f in r.keys())]
    market = get_market_data()
    statuses = {r['data_status'] for r in pboc_records}
    data_mode = 'cache' if 'cache' in statuses else ('seed' if 'seed' in statuses else 'missing')
    warnings = []
    if data_mode == 'seed':
        warnings.append('当前主要数据来自人工种子/离线核实记录，不应标记为实时。')
    if market['data_status'] == 'missing':
        warnings.extend(market.get('warnings', []))

    return {
        'success': True,
        'data_mode': data_mode,
        'pboc_monthly': {
            'latest_period': latest_period(pboc_records),
            'last_sync': last['scraped_at'] if last else None,
            'source_name': '中国人民银行',
            'data_status': data_mode,
            'warnings': warnings,
            'records': pboc_records,
        },
        'loan_structure': {
            'latest_period': latest_period(loan_records),
            'data_status': data_mode,
            'records': loan_records,
        },
        'deposit_structure': {
            'latest_period': None,
            'data_status': 'missing',
            'records': [],
            'warnings': ['尚未接入结构化存款分部门数据源。'],
        },
        'tsf_structure': {
            'latest_period': None,
            'data_status': 'missing',
            'records': [],
            'warnings': ['尚未接入结构化社融分项数据源。'],
        },
        'market_data': market,
        'metadata': {
            'last_sync': last['scraped_at'] if last else None,
            'record_count': len(pboc_records),
            'source_summary': sorted(statuses),
            'source_registry': SOURCE_REGISTRY,
            'indicator_dictionary': INDICATORS,
            'warnings': warnings,
            'errors': [],
        },
        'data': legacy,
        'count': len(legacy),
        'last_sync': last['scraped_at'] if last else None,
    }

def sync_observations(db_path):
    started = datetime.now().isoformat()
    new_records = 0
    updated_records = 0
    warnings = []
    with connect(db_path) as conn:
        ensure_financial_tables(conn)
        conn.execute('''
            DELETE FROM financial_observations
            WHERE data_status='seed'
              AND period IN (
                  SELECT month FROM monthly_data
                  WHERE source_url LIKE 'http%'
              )
        ''')
        rows = conn.execute('SELECT * FROM monthly_data ORDER BY month').fetchall()
        now = datetime.now().isoformat()
        for row in rows:
            data_status, source_type, is_seed = source_status(row)
            for field, code in FIELD_TO_INDICATOR.items():
                if field not in row.keys() or row[field] is None:
                    continue
                meta = INDICATORS.get(code, {'display_name': code, 'unit_raw': '', 'unit_display': '', 'scale_factor': 1, 'frequency': 'monthly', 'is_ytd': False, 'is_stock': False, 'notes': ''})
                src_meta = source_meta_for_indicator(code, row)
                existing = conn.execute(
                    'SELECT id FROM financial_observations WHERE indicator_code=? AND period=? AND source_type=?',
                    (code, row['month'], source_type)
                ).fetchone()
                params = (
                    code, meta.get('display_name', code), row[field], meta.get('unit_raw', ''),
                    meta.get('unit_display', ''), meta.get('scale_factor', 1), row['month'], row['month'] + '-01',
                    meta.get('frequency', 'monthly'), source_type, src_meta['source_name'], src_meta['source_url'],
                    src_meta['source_title'], src_meta['published_date'], src_meta['parser_notes'],
                    data_status, 0, is_seed, data_status == 'cache', int(meta.get('is_ytd', False)),
                    0, int(meta.get('is_stock', False)), row[field] if code.endswith('_YOY') else None,
                    None, meta.get('notes', ''), now, now
                )
                conn.execute('''INSERT INTO financial_observations (
                    indicator_code,indicator_name,value,unit_raw,unit_display,scale_factor,period,date,frequency,
                    source_type,source_name,source_url,source_title,published_date,parser_notes,
                    data_status,is_mock,is_seed,is_cache,is_ytd,
                    is_monthly_increment,is_stock,yoy,mom,notes,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period,source_type) DO UPDATE SET
                    value=excluded.value, source_url=excluded.source_url,
                    source_title=excluded.source_title, published_date=excluded.published_date,
                    parser_notes=excluded.parser_notes, data_status=excluded.data_status,
                    is_seed=excluded.is_seed, is_cache=excluded.is_cache, updated_at=excluded.updated_at
                ''', params)
                if existing:
                    updated_records += 1
                else:
                    new_records += 1
        conn.execute('''INSERT INTO financial_update_logs
            (source_name,source_type,started_at,finished_at,success,new_records,updated_records,error_message,warnings)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            ('中国人民银行', 'pboc_monthly', started, datetime.now().isoformat(), 1,
             new_records, updated_records, None, json.dumps(warnings, ensure_ascii=False)))
        conn.commit()
    return {'new_records': new_records, 'updated_records': updated_records, 'warnings': warnings}

def build_debug_payload(db_path):
    with connect(db_path) as conn:
        ensure_financial_tables(conn)
        tables = {}
        for name in ['monthly_data', 'raw_pages', 'scrape_log', 'financial_observations', 'financial_update_logs']:
            tables[name] = conn.execute(f'SELECT COUNT(*) AS c FROM {name}').fetchone()['c']
        latest_by_indicator = [dict(r) for r in conn.execute('''
            SELECT indicator_code, indicator_name, value, unit_display, period, source_name,
                   source_type, source_url, source_title, published_date, parser_notes,
                   data_status, is_mock, is_seed, is_cache, updated_at
            FROM financial_observations fo
            WHERE period = (SELECT MAX(period) FROM financial_observations WHERE indicator_code=fo.indicator_code)
            ORDER BY indicator_code
        ''').fetchall()]
        indicators_by_source = [dict(r) for r in conn.execute('''
            SELECT COALESCE(source_url, '') AS source_url,
                   MAX(source_title) AS source_title,
                   MAX(published_date) AS published_date,
                   COUNT(DISTINCT indicator_code) AS indicator_count,
                   GROUP_CONCAT(DISTINCT indicator_code) AS indicators
            FROM financial_observations
            GROUP BY COALESCE(source_url, '')
            ORDER BY MAX(period) DESC, indicator_count DESC
        ''').fetchall()]
        missing_source_url = [dict(r) for r in conn.execute('''
            SELECT indicator_code, COUNT(*) AS records
            FROM financial_observations
            WHERE source_url IS NULL OR source_url='' OR source_url IN ('seed','manual')
            GROUP BY indicator_code
            ORDER BY indicator_code
        ''').fetchall()]
        status_counts = [dict(r) for r in conn.execute('''
            SELECT data_status, source_type, is_mock, is_seed, is_cache, COUNT(*) AS records
            FROM financial_observations
            GROUP BY data_status, source_type, is_mock, is_seed, is_cache
            ORDER BY records DESC
        ''').fetchall()]
        field_coverage = {}
        for field in PBOC_FIELDS:
            try:
                field_coverage[field] = conn.execute(f'SELECT COUNT(*) AS c FROM monthly_data WHERE {field} IS NOT NULL').fetchone()['c']
            except sqlite3.OperationalError:
                pass
        latest_period = conn.execute('SELECT MAX(month) AS m FROM monthly_data').fetchone()['m']
        logs = [dict(r) for r in conn.execute('SELECT * FROM financial_update_logs ORDER BY id DESC LIMIT 10').fetchall()]
        registry = [dict(r) for r in conn.execute('SELECT * FROM financial_source_registry ORDER BY source_key').fetchall()]
    return {
        'database_path': db_path,
        'tables': tables,
        'latest_by_indicator': latest_by_indicator,
        'indicators_by_source': indicators_by_source,
        'missing_source_url': missing_source_url,
        'status_counts': status_counts,
        'source_registry': registry,
        'field_coverage': field_coverage,
        'latest_period': latest_period,
        'latest_date': None,
        'last_update_logs': logs,
        'warnings': [],
        'errors': [],
    }
