"""Reviewed official bank-table observations; no unreviewed OCR or extrapolation."""
import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path

BANK_INDICATORS = {
    'CN_BANK_NPL_BALANCE': ('商业银行不良贷款余额', '亿元', 'quarterly'),
    'CN_BANK_NPL_RATIO': ('商业银行不良贷款率', '%', 'quarterly'),
    'CN_BANK_NIM_YTD': ('商业银行净息差（监管披露）', '%', 'quarterly'),
    'CN_BANK_PROVISION_COVERAGE': ('商业银行拨备覆盖率', '%', 'quarterly'),
    'CN_BANK_CAPITAL_ADEQUACY': ('商业银行资本充足率', '%', 'quarterly'),
    'CN_BANK_TIER1_CAPITAL_ADEQUACY': ('商业银行一级资本充足率', '%', 'quarterly'),
    'CN_BANK_CORE_TIER1_CAPITAL_ADEQUACY': ('商业银行核心一级资本充足率', '%', 'quarterly'),
    'CN_BANK_NET_PROFIT_YTD': ('商业银行净利润（本年累计）', '亿元', 'quarterly'),
    'CN_BANK_ROA_YTD': ('商业银行资产利润率', '%', 'quarterly'),
    'CN_BANK_ROE_YTD': ('商业银行资本利润率', '%', 'quarterly'),
    'CN_BANK_LCR': ('商业银行流动性覆盖率', '%', 'quarterly'),
    'CN_BANK_NSFR': ('商业银行净稳定资金比例', '%', 'quarterly'),
    'CN_BANK_LIQUIDITY_RATIO': ('商业银行流动性比例', '%', 'quarterly'),
    'CN_BANK_LOAN_DEPOSIT_RATIO': ('商业银行存贷款比例（人民币境内）', '%', 'quarterly'),
}
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / 'data' / 'bank_supervision_reviewed_official.csv'
HISTORY_PATH = SNAPSHOT_PATH.with_name('bank_supervision_history_reviewed.json')
SOURCE_IMAGE = 'https://www.nfra.gov.cn/chinese/OFFICE/HTML/1258121.files/12581210.png'
SOURCE_NOTE = ('金融监管总局2026年商业银行主要监管指标表，逐格人工核对官方图片；'
               '截至2026-10-02只核验2026Q1/Q2，空白季度不补；净利润为本年累计，'
               '净息差等比率按官方监管定义原样保存，不自行季度差分或年化；'
               '不良贷款余额为季末；2024起资本新规，跨口径不机械拼接。'
               '发布日期为所核验表格版本日期，不代表每个季度首次发布日。')


def reviewed_history_rows(path):
    """Expand independently reviewed quarter cells; blank cells remain absent."""
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema_version') != 1:
        raise ValueError('Unsupported reviewed bank-history schema.')
    rows = []
    for table in payload['tables']:
        if not table.get('reviewed_at') or not table.get('source_url', '').startswith('https://www.nfra.gov.cn/'):
            raise ValueError('A reviewed official table and provenance are required.')
        year = int(table['year'])
        if not 2000 <= year <= datetime.now().year:
            raise ValueError('Invalid reviewed bank-table year.')
        for code, values in table['values'].items():
            if code not in BANK_INDICATORS or len(values) != 4:
                raise ValueError('Unknown indicator or invalid quarter columns.')
            for quarter, value in enumerate(values, 1):
                if value is not None:
                    rows.append({**{key: table[key] for key in
                        ('source_url', 'source_title', 'release_date', 'retrieved_at', 'parser_notes')},
                        'indicator_code': code, 'period': f'{year}-{quarter * 3:02d}', 'value': value})
    return rows


def sync_bank_supervision_snapshot(conn, path=SNAPSHOT_PATH, history_path=None):
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    # Custom test/user snapshots stay isolated from the production supplement.
    if history_path is None and Path(path).resolve() == SNAPSHOT_PATH.resolve():
        history_path = HISTORY_PATH if HISTORY_PATH.is_file() else None
    if history_path:
        rows.extend(reviewed_history_rows(history_path))
    seen = set()
    for row in rows:
        code, period = row['indicator_code'], row['period']
        if code not in BANK_INDICATORS or not re.fullmatch(r'(?:19|20)\d{2}-(03|06|09|12)',period):
            raise ValueError('Unknown bank indicator or invalid quarter-end period.')
        key=(code,period)
        if key in seen or not math.isfinite(float(row['value'])):
            raise ValueError('Duplicate or nonfinite bank snapshot observation.')
        seen.add(key)
    changed = 0
    now = datetime.now().isoformat()
    for row in rows:
        code, period, value = row['indicator_code'], row['period'], float(row['value'])
        name, unit, frequency = BANK_INDICATORS[code]
        source_url = row.get('source_url') or SOURCE_IMAGE
        source_title = row.get('source_title') or '2026年商业银行主要监管指标情况表'
        source_note = row.get('parser_notes') or SOURCE_NOTE
        release_date = row.get('release_date') or '2026-08-14'
        retrieved_at = row.get('retrieved_at') or '2026-10-02'
        previous = conn.execute('SELECT value,source_url,parser_notes FROM china_macro_observations '
                                'WHERE indicator_code=? AND period=?',(code,period)).fetchone()
        if previous and tuple(previous) == (value,source_url,source_note):
            continue
        conn.execute('''INSERT INTO china_macro_observations (
            indicator_code,indicator_name,period,value,unit,frequency,data_status,source_name,
            source_type,source_url,source_title,parser_notes,updated_at,release_date,retrieved_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period) DO UPDATE SET value=excluded.value,
            indicator_name=excluded.indicator_name,unit=excluded.unit,frequency=excluded.frequency,
            data_status=excluded.data_status,source_name=excluded.source_name,
            source_type=excluded.source_type,source_url=excluded.source_url,
            source_title=excluded.source_title,parser_notes=excluded.parser_notes,
            updated_at=excluded.updated_at,release_date=excluded.release_date,retrieved_at=excluded.retrieved_at''',
            (code,name,period,value,unit,frequency,'official','国家金融监督管理总局',
             'nfra_reviewed_table',source_url,source_title,source_note,
             now,release_date,retrieved_at))
        changed+=1
    conn.commit()
    sources = sorted({row.get('source_url') or SOURCE_IMAGE for row in rows})
    return {'success':True,'records_changed':changed,'records_upserted':changed,
            'rows_reviewed':len(rows),'data_status':'official',
            'source_url':sources[0] if len(sources) == 1 else None, 'source_urls':sources,
            'start_period':min((row['period'] for row in rows), default=None),
            'end_period':max((row['period'] for row in rows), default=None),
            'method':'Reviewed official image snapshot; future image versions need independent cell review.'}
