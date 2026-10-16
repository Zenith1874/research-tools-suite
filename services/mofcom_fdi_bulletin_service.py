"""Reviewed MOFCOM annual bulletin facts, kept separate from monthly FDI releases."""
import hashlib
import json
import math
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REVIEWED_DIR = ROOT / 'data' / 'mofcom_fdi_bulletin_reviewed'
FDI_ANNUAL_INDICATORS = {
    'CN_MOFCOM_FDI_USD_ANNUAL': ('商务部公报实际使用外资（全年，USD）', '亿美元', 'annual'),
    'CN_MOFCOM_FDI_NEW_FIRMS_ANNUAL': ('商务部公报新设外商投资企业（全年）', '家', 'annual'),
}


def parse_fdi_annual_appendix(text):
    """Read Appendix 1's explicit years; preserve the combined early block separately."""
    compact = re.sub(r'\s+', '', text)
    heading = re.search(r'附表1截至(20\d{2})年外商直接投资情况', compact)
    if not heading or '金额单位：亿美元' not in compact:
        raise ValueError('Appendix 1 heading and USD units must be explicit.')
    final_year = int(heading[1])
    rows = {}
    for match in re.finditer(r'^\s*((?:19|20)\d{2})\s+([\d,]+)\s+([\d,.]+)\s*$', text, re.MULTILINE):
        year = int(match[1])
        companies = int(match[2].replace(',', ''))
        amount = float(match[3].replace(',', ''))
        if year in rows or not 1983 <= year <= final_year or not math.isfinite(amount) or amount < 0:
            raise ValueError('Duplicate year, invalid value or unsupported annual period.')
        rows[year] = {'year': year, 'new_firms': companies, 'amount_usd': amount}
    if sorted(rows) != list(range(1983, final_year + 1)):
        raise ValueError('The supplied Appendix 1 pages do not cover every explicit annual row.')
    total = re.search(r'^\s*总计\s+([\d,]+)\s+([\d,.]+)\s*$', text, re.MULTILINE)
    block = re.search(r'^\s*1979[—–-]1982\s+([\d,]+)\s+([\d,.]+)\s*$', text, re.MULTILINE)
    if not total or not block:
        raise ValueError('The total and combined 1979-1982 block must be preserved.')
    total_firms = int(total[1].replace(',', ''))
    block_firms = int(block[1].replace(',', ''))
    if sum(row['new_firms'] for row in rows.values()) + block_firms != total_firms:
        raise ValueError('Company counts do not reconcile to the published total.')
    total_amount = Decimal(total[2].replace(',', ''))
    block_amount = Decimal(block[2].replace(',', ''))
    amount_sum = sum((Decimal(str(row['amount_usd'])) for row in rows.values()), block_amount)
    # Published amounts have one decimal; independent annual rounding may accumulate.
    if abs(amount_sum - total_amount) > Decimal('0.05') * (len(rows) + 1):
        raise ValueError('Annual amounts do not reconcile within source rounding precision.')
    return {'statistical_year': final_year, 'annual_rows': [rows[year] for year in sorted(rows)],
            'combined_early_block': {'period': '1979-1982', 'new_firms': block_firms,
                                     'amount_usd': float(block_amount)},
            'published_total': {'period': f'1979-{final_year}', 'new_firms': total_firms,
                                'amount_usd': float(total_amount)}}


def annual_snapshot_observations(snapshot):
    """Expand an explicitly reviewed annual snapshot without rewriting monthly series."""
    if snapshot.get('schema_version') != 1 or not snapshot.get('reviewed_at'):
        raise ValueError('A reviewed annual snapshot is required.')
    source = urlsplit(snapshot.get('source_url', ''))
    if source.scheme != 'https' or source.username or source.password or not (
            source.hostname == 'mofcom.gov.cn' or (source.hostname or '').endswith('.mofcom.gov.cn')):
        raise ValueError('A public official MOFCOM source is required.')
    if not re.fullmatch(r'[a-f0-9]{64}', snapshot.get('raw_sha256', '')):
        raise ValueError('The reviewed source PDF checksum is required.')
    rows = []
    seen = set()
    for annual in snapshot['annual_rows']:
        year = int(annual['year'])
        if year in seen or not 1983 <= year <= int(snapshot['statistical_year']):
            raise ValueError('Invalid or duplicate snapshot annual period.')
        seen.add(year)
        for code, key in (('CN_MOFCOM_FDI_USD_ANNUAL', 'amount_usd'),
                          ('CN_MOFCOM_FDI_NEW_FIRMS_ANNUAL', 'new_firms')):
            value = annual[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Finite nonnegative annual source values are required.')
            if key == 'new_firms' and int(value) != value:
                raise ValueError('Company counts must be integers.')
            name, unit, frequency = FDI_ANNUAL_INDICATORS[code]
            rows.append({'indicator_code': code, 'indicator_name': name, 'period': str(year),
                         'value': value, 'unit': unit, 'frequency': frequency,
                         'source_url': snapshot['source_url'], 'source_title': snapshot['source_title'],
                         'release_date': snapshot.get('release_date'), 'retrieved_at': snapshot['retrieved_at'],
                         'raw_sha256': snapshot['raw_sha256'], 'parser_notes': snapshot['parser_notes']})
    if sorted(seen) != list(range(1983, int(snapshot['statistical_year']) + 1)):
        raise ValueError('The reviewed annual snapshot is incomplete.')
    return rows


def sync_mofcom_fdi_annual(conn, reviewed_dir=REVIEWED_DIR):
    """Idempotent reviewed-source sync with prior observations retained on vintage changes."""
    paths = sorted(Path(reviewed_dir).glob('*.json'))
    if not paths:
        return {'records_changed': 0, 'rows_reviewed': 0, 'source_status': 'reviewed_snapshot_missing'}
    snapshots = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
    snapshot = max(snapshots, key=lambda item: (item['statistical_year'], item.get('release_date') or '', item['reviewed_at']))
    rows = annual_snapshot_observations(snapshot)
    conn.execute('''CREATE TABLE IF NOT EXISTS mofcom_fdi_annual_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, indicator_code TEXT NOT NULL, period TEXT NOT NULL,
        previous_row_json TEXT NOT NULL, next_raw_sha256 TEXT NOT NULL, revised_at TEXT NOT NULL)''')
    now = datetime.now().astimezone().isoformat()
    changed = 0
    try:
        for row in rows:
            old = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                               (row['indicator_code'], row['period'])).fetchone()
            if old and all(old[key] == row[key] for key in ('value', 'source_url', 'raw_sha256', 'parser_notes', 'release_date')):
                continue
            if old:
                conn.execute('INSERT INTO mofcom_fdi_annual_revisions '
                             '(indicator_code,period,previous_row_json,next_raw_sha256,revised_at) VALUES (?,?,?,?,?)',
                             (row['indicator_code'], row['period'], json.dumps(dict(old), ensure_ascii=False),
                              row['raw_sha256'], now))
            conn.execute('''INSERT INTO china_macro_observations
                (indicator_code,indicator_name,period,value,unit,frequency,data_status,source_name,source_type,
                 source_url,source_title,parser_notes,updated_at,release_date,retrieved_at,raw_sha256,parser_version)
                VALUES (?,?,?,?,?,?,?,'商务部','mofcom_fdi_bulletin_annual',?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET value=excluded.value,
                source_url=excluded.source_url,source_title=excluded.source_title,parser_notes=excluded.parser_notes,
                release_date=excluded.release_date,retrieved_at=excluded.retrieved_at,
                raw_sha256=excluded.raw_sha256,updated_at=excluded.updated_at,parser_version=excluded.parser_version''',
                (row['indicator_code'], row['indicator_name'], row['period'], row['value'], row['unit'],
                 row['frequency'], 'official', row['source_url'], row['source_title'], row['parser_notes'],
                 now, row['release_date'], row['retrieved_at'], row['raw_sha256'], 'mofcom_fdi_annual_20261013'))
            changed += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {'records_changed': changed, 'rows_reviewed': len(rows),
            'first_year': rows[0]['period'], 'last_year': rows[-1]['period']}
