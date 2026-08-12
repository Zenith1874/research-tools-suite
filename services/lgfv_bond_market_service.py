# -*- coding: utf-8 -*-
"""Private bond-terms, cash-flow and notice enrichment for the LGFV candidate set.

This module deliberately does not create an official ``lgfv_debt`` series.  The
ChinaMoney/AKShare universe is a bond-market candidate inventory; it has no
official LGFV classification.  All calculated balances and cash flows therefore
carry an explicit ``market_estimate`` or ``derived_schedule`` status.

The public bond list supplies identifiers only.  ``BondDetailInfo`` supplies
issuance amounts and static terms.  The separate ``clinrAnNotice`` endpoint
supplies official notice metadata for interest/redemption announcements.  A
notice is not treated as a paid amount unless its attachment can be parsed.
"""

import calendar
import json
import re
import sqlite3
import time
from datetime import date, datetime
from urllib.parse import quote

import requests

from services.lgfv_bond_service import (
    CANDIDATE_BOND_TYPES,
    DETAIL_URL,
    PUBLIC_QUERY_URL,
    REQUEST_HEADERS,
    SOURCE_TYPE,
    ensure_lgfv_inventory_tables,
)


NOTICE_URL = (
    'https://www.chinamoney.com.cn/ags/ms/'
    'cm-u-notice-issue/clinrAnNotice'
)
NOTICE_CHANNEL_ID = '2562'  # 中国货币网 fxdf: 付息兑付
NOTICE_SECOND_TYPES = '2001,2002'
NOTICE_MIN_DATE = '2023-08-07'
NOTICE_PAGE_SIZE = 30
NOTICE_PAGE_SOURCE = 'https://www.chinamoney.com.cn/chinese/fxdflm/'
NOTICE_FILE_BASE = (
    'https://www.chinamoney.com.cn/dqs/cm-s-notice-query/'
    'fileDownLoad.do'
)

DETAIL_SOURCE_TYPE = 'chinamoney_bond_terms'
NOTICE_SOURCE_TYPE = 'chinamoney_interest_redemption_notice'
DEFAULT_DETAIL_RETRIES = 4

_AMOUNT_RE = re.compile(r'^[\s,，]*([+-]?(?:\d+(?:\.\d*)?|\.\d+))[\s,，]*$')
_DATE_RE = re.compile(r'^(\d{4})[-/]?(\d{1,2})[-/]?(\d{1,2})$')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text not in {'---', '—', 'null', 'None'} else None


def parse_amount(value):
    """Parse a ChinaMoney amount in 亿元 without silently coercing junk to 0."""
    text = _clean(value)
    if text is None:
        return None
    text = text.replace(',', '').replace('，', '')
    match = _AMOUNT_RE.match(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def parse_date(value):
    text = _clean(value)
    if not text:
        return None
    match = _DATE_RE.match(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _iso(value):
    parsed = parse_date(value) if not isinstance(value, date) else value
    return parsed.isoformat() if parsed else None


def frequency_months(value):
    """Map common public Chinese frequency labels to months per payment."""
    text = _clean(value) or ''
    if any(token in text for token in ('每月', '月度', '月')):
        return 1
    if any(token in text for token in ('每季', '季度', '季')):
        return 3
    if any(token in text for token in ('每半年', '半年', '半年度')):
        return 6
    if any(token in text for token in ('每年', '年度', '年')):
        return 12
    return None


def add_months(value, months):
    """Add whole months while keeping end-of-month dates valid."""
    if not isinstance(value, date):
        value = parse_date(value)
    if value is None or not months:
        return None
    total = value.year * 12 + value.month - 1 + int(months)
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def fetch_bond_detail(bond_defined_code, session=None, timeout=30,
                      retries=DEFAULT_DETAIL_RETRIES, retry_backoff=1.0):
    """Fetch and validate one official ChinaMoney detail response.

    The endpoint occasionally returns an empty body or raises a low-level
    ``OSError`` after a long sequence of requests.  Those are retryable
    transport/response failures, not evidence that the bond has no terms.
    """
    client = session or requests
    last_error = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            response = client.post(
                DETAIL_URL,
                data={'bondDefinedCode': bond_defined_code},
                headers=REQUEST_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            base = (payload.get('data') or {}).get('bondBaseInfo')
            if not isinstance(base, dict) or not base.get('bondDefinedCode'):
                raise ValueError('BondDetailInfo 缺少 bondBaseInfo/bondDefinedCode')
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < int(retries):
                # A longer backoff is intentional: the observed failures were
                # clustered after many sequential requests and succeeded when
                # retried later against the same official endpoint.
                delay = min(20.0, float(retry_backoff) * (2 ** attempt))
                time.sleep(max(0.0, delay))
    raise last_error


def parse_bond_terms(snapshot_date, inventory_row, payload):
    """Normalize detail JSON into a stable terms record."""
    base = payload['data']['bondBaseInfo']
    defined = _clean(base.get('bondDefinedCode')) or inventory_row['bond_defined_code']
    source_url = (
        f'{PUBLIC_QUERY_URL}?bondDefinedCode={quote(defined)}'
    )
    return {
        'snapshot_date': snapshot_date,
        'source_type': DETAIL_SOURCE_TYPE,
        'bond_defined_code': defined,
        'bond_code': _clean(base.get('bondCode')),
        'bond_name': _clean(base.get('bondName')) or inventory_row['bond_name'],
        'bond_full_name': _clean(base.get('bondFullName')),
        'bond_type_code': _clean(base.get('bondTypeCode')) or inventory_row['bond_type_code'],
        'bond_type': _clean(base.get('bondType')) or inventory_row['bond_type'],
        'issuer': _clean(base.get('entyFullName')) or inventory_row['issuer'],
        'issue_date': _iso(base.get('issueDate')),
        'maturity_date': _iso(base.get('mrtyDate')),
        'first_value_date': _iso(base.get('frstValueDate')),
        'first_coupon_date': _iso(base.get('frstCpnDt')),
        'first_payment_date': _iso(base.get('frstPayDt')),
        'planned_issue_amount': parse_amount(base.get('plndIssueAmnt')),
        'actual_issue_amount': parse_amount(base.get('issueAmnt')),
        'par_value': parse_amount(base.get('parValue')),
        'issue_price': parse_amount(base.get('issuePrice')),
        'coupon_rate': parse_amount(base.get('parCouponRate')),
        'coupon_type': _clean(base.get('couponType')),
        'coupon_frequency': _clean(base.get('couponFrqncy')),
        'bond_period': _clean(base.get('bondPeriod')),
        'principal_amount_field': parse_amount(base.get('ntnlPrncplAmnt')),
        'exercise_info_json': json.dumps(
            base.get('exerciseInfoList') or [], ensure_ascii=False, sort_keys=True
        ),
        'additional_issue_json': json.dumps(
            base.get('bondRisInfoList') or [], ensure_ascii=False, sort_keys=True
        ),
        'source_url': source_url,
        'raw_json': json.dumps(payload, ensure_ascii=False, sort_keys=True),
        'data_status': 'official_terms',
        'detail_status': 'success',
        'detail_error': None,
        'updated_at': _now(),
    }


def scheduled_cashflows(terms, as_of=None):
    """Generate transparent payment dates from static terms.

    Amounts are populated only when actual issuance, coupon rate and frequency
    are all known.  These rows are scheduled/derived, never labelled as paid.
    """
    as_of = parse_date(as_of) if as_of else date.today()
    first = parse_date(terms.get('first_coupon_date'))
    if first is None:
        first = parse_date(terms.get('first_payment_date'))
    if first is None:
        first = parse_date(terms.get('first_value_date'))
    maturity = parse_date(terms.get('maturity_date'))
    months = frequency_months(terms.get('coupon_frequency'))
    if first is None or maturity is None or months is None or first > maturity:
        return []

    principal = terms.get('actual_issue_amount')
    coupon_rate = terms.get('coupon_rate')
    interest_amount = None
    if principal is not None and coupon_rate is not None:
        interest_amount = principal * coupon_rate / 100.0 * months / 12.0

    rows = []
    previous = parse_date(terms.get('first_value_date')) or add_months(first, -months)
    current = first
    guard = 0
    while current <= maturity and guard < 240:
        rows.append({
            'bond_defined_code': terms['bond_defined_code'],
            'event_type': 'scheduled_interest',
            'period_start': _iso(previous),
            'period_end': _iso(current),
            'event_date': _iso(current),
            'interest_amount': round(interest_amount, 10) if interest_amount is not None else None,
            'principal_amount': None,
            'amount': round(interest_amount, 10) if interest_amount is not None else None,
            'amount_unit': '亿元',
            'data_status': 'derived_schedule',
            'method': 'actual_issue_amount × coupon_rate × months_per_payment / 12 / 100',
            'source_url': terms['source_url'],
            'notice_content_id': None,
            'notice_title': None,
            'raw_json': json.dumps({'scheduled_as_of': _iso(as_of)}, ensure_ascii=False),
        })
        if current == maturity:
            rows.append({
                'bond_defined_code': terms['bond_defined_code'],
                'event_type': 'scheduled_principal',
                'period_start': None,
                'period_end': None,
                'event_date': _iso(current),
                'interest_amount': None,
                'principal_amount': principal,
                'amount': principal,
                'amount_unit': '亿元',
                'data_status': 'derived_schedule',
                'method': 'actual_issue_amount at stated maturity; no partial-redemption data',
                'source_url': terms['source_url'],
                'notice_content_id': None,
                'notice_title': None,
                'raw_json': json.dumps({'scheduled_as_of': _iso(as_of)}, ensure_ascii=False),
            })
            break
        previous = current
        current = add_months(current, months)
        guard += 1
    return rows


def ensure_lgfv_market_tables(conn):
    """Create enrichment tables in the private database only."""
    ensure_lgfv_inventory_tables(conn)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_terms (
            id INTEGER PRIMARY KEY,
            snapshot_date TEXT NOT NULL,
            source_type TEXT NOT NULL,
            bond_defined_code TEXT NOT NULL,
            bond_code TEXT,
            bond_name TEXT,
            bond_full_name TEXT,
            bond_type_code TEXT,
            bond_type TEXT,
            issuer TEXT,
            issue_date TEXT,
            maturity_date TEXT,
            first_value_date TEXT,
            first_coupon_date TEXT,
            first_payment_date TEXT,
            planned_issue_amount REAL,
            actual_issue_amount REAL,
            par_value REAL,
            issue_price REAL,
            coupon_rate REAL,
            coupon_type TEXT,
            coupon_frequency TEXT,
            bond_period TEXT,
            principal_amount_field REAL,
            exercise_info_json TEXT NOT NULL,
            additional_issue_json TEXT NOT NULL,
            source_url TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            data_status TEXT NOT NULL,
            detail_status TEXT NOT NULL,
            detail_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(snapshot_date, source_type, bond_defined_code)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_cashflows (
            id INTEGER PRIMARY KEY,
            snapshot_date TEXT NOT NULL,
            bond_defined_code TEXT NOT NULL,
            event_type TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            event_date TEXT,
            interest_amount REAL,
            principal_amount REAL,
            amount REAL,
            amount_unit TEXT NOT NULL,
            data_status TEXT NOT NULL,
            method TEXT NOT NULL,
            source_url TEXT NOT NULL,
            notice_content_id TEXT,
            notice_title TEXT,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(snapshot_date, bond_defined_code, event_type, event_date,
                   data_status, notice_content_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_notices (
            id INTEGER PRIMARY KEY,
            snapshot_date TEXT NOT NULL,
            notice_content_id TEXT NOT NULL,
            bond_type_code TEXT,
            release_date TEXT,
            title TEXT NOT NULL,
            event_type TEXT NOT NULL,
            draft_path TEXT,
            source_url TEXT NOT NULL,
            attachment_url TEXT,
            matched_bond_defined_code TEXT,
            amount REAL,
            interest_amount REAL,
            principal_amount REAL,
            parse_status TEXT NOT NULL,
            data_status TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(snapshot_date, notice_content_id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_detail_progress (
            snapshot_date TEXT PRIMARY KEY,
            attempted INTEGER NOT NULL DEFAULT 0,
            succeeded INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT,
            updated_at TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_notice_progress (
            snapshot_date TEXT NOT NULL,
            bond_type_code TEXT NOT NULL,
            bond_type TEXT NOT NULL,
            total_count INTEGER,
            page_total INTEGER,
            next_page INTEGER NOT NULL DEFAULT 1,
            fetched_rows INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(snapshot_date, bond_type_code)
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_lgfv_terms_snapshot_status
        ON lgfv_bond_terms(snapshot_date, detail_status)
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_lgfv_terms_snapshot_code
        ON lgfv_bond_terms(snapshot_date, bond_defined_code)
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_lgfv_inventory_snapshot_code
        ON lgfv_bond_inventory(snapshot_date, bond_defined_code)
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_lgfv_cashflows_snapshot_event
        ON lgfv_bond_cashflows(snapshot_date, event_type, event_date)
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_lgfv_notices_snapshot_match
        ON lgfv_bond_notices(snapshot_date, matched_bond_defined_code)
    ''')


def _upsert_terms(conn, row):
    fields = [
        'snapshot_date', 'source_type', 'bond_defined_code', 'bond_code',
        'bond_name', 'bond_full_name', 'bond_type_code', 'bond_type', 'issuer',
        'issue_date', 'maturity_date', 'first_value_date', 'first_coupon_date',
        'first_payment_date', 'planned_issue_amount', 'actual_issue_amount',
        'par_value', 'issue_price', 'coupon_rate', 'coupon_type',
        'coupon_frequency', 'bond_period', 'principal_amount_field',
        'exercise_info_json', 'additional_issue_json', 'source_url', 'raw_json',
        'data_status', 'detail_status', 'detail_error', 'updated_at',
    ]
    values = [row.get(field) for field in fields]
    placeholders = ','.join('?' for _ in fields)
    conn.execute(f'''
        INSERT INTO lgfv_bond_terms ({','.join(fields)},created_at)
        VALUES ({placeholders},?)
        ON CONFLICT(snapshot_date, source_type, bond_defined_code) DO UPDATE SET
            bond_code=excluded.bond_code,
            bond_name=excluded.bond_name,
            bond_full_name=excluded.bond_full_name,
            bond_type_code=excluded.bond_type_code,
            bond_type=excluded.bond_type,
            issuer=COALESCE(excluded.issuer, lgfv_bond_terms.issuer),
            issue_date=COALESCE(excluded.issue_date, lgfv_bond_terms.issue_date),
            maturity_date=COALESCE(excluded.maturity_date, lgfv_bond_terms.maturity_date),
            first_value_date=COALESCE(excluded.first_value_date, lgfv_bond_terms.first_value_date),
            first_coupon_date=COALESCE(excluded.first_coupon_date, lgfv_bond_terms.first_coupon_date),
            first_payment_date=COALESCE(excluded.first_payment_date, lgfv_bond_terms.first_payment_date),
            planned_issue_amount=COALESCE(excluded.planned_issue_amount, lgfv_bond_terms.planned_issue_amount),
            actual_issue_amount=COALESCE(excluded.actual_issue_amount, lgfv_bond_terms.actual_issue_amount),
            par_value=COALESCE(excluded.par_value, lgfv_bond_terms.par_value),
            issue_price=COALESCE(excluded.issue_price, lgfv_bond_terms.issue_price),
            coupon_rate=COALESCE(excluded.coupon_rate, lgfv_bond_terms.coupon_rate),
            coupon_type=COALESCE(excluded.coupon_type, lgfv_bond_terms.coupon_type),
            coupon_frequency=COALESCE(excluded.coupon_frequency, lgfv_bond_terms.coupon_frequency),
            bond_period=COALESCE(excluded.bond_period, lgfv_bond_terms.bond_period),
            principal_amount_field=COALESCE(excluded.principal_amount_field, lgfv_bond_terms.principal_amount_field),
            exercise_info_json=excluded.exercise_info_json,
            additional_issue_json=excluded.additional_issue_json,
            source_url=excluded.source_url,
            raw_json=excluded.raw_json,
            data_status=excluded.data_status,
            detail_status=excluded.detail_status,
            detail_error=excluded.detail_error,
            updated_at=excluded.updated_at
    ''', values + [_now()])


def _replace_scheduled_cashflows(conn, snapshot_date, terms):
    conn.execute('''
        DELETE FROM lgfv_bond_cashflows
        WHERE snapshot_date=? AND bond_defined_code=? AND data_status='derived_schedule'
    ''', (snapshot_date, terms['bond_defined_code']))
    now = _now()
    for row in scheduled_cashflows(terms, as_of=snapshot_date):
        conn.execute('''
            INSERT OR IGNORE INTO lgfv_bond_cashflows (
                snapshot_date,bond_defined_code,event_type,period_start,period_end,
                event_date,interest_amount,principal_amount,amount,amount_unit,
                data_status,method,source_url,notice_content_id,notice_title,
                raw_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            snapshot_date, row['bond_defined_code'], row['event_type'],
            row['period_start'], row['period_end'], row['event_date'],
            row['interest_amount'], row['principal_amount'], row['amount'],
            row['amount_unit'], row['data_status'], row['method'],
            row['source_url'], row['notice_content_id'], row['notice_title'],
            row['raw_json'], now, now,
        ))


def update_lgfv_bond_details(db_path, max_rows=None, request_pause=0.15,
                             timeout=30, retries=DEFAULT_DETAIL_RETRIES,
                             snapshot_date=None, verbose=False):
    """Resume detail enrichment for every inventory row in the private DB."""
    snapshot = snapshot_date or date.today().isoformat()
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=60000')
    ensure_lgfv_market_tables(conn)
    progress = conn.execute(
        'SELECT attempted,succeeded,failed FROM lgfv_bond_detail_progress WHERE snapshot_date=?',
        (snapshot,),
    ).fetchone()
    attempted = int(progress['attempted']) if progress else 0
    succeeded = int(progress['succeeded']) if progress else 0
    failed = int(progress['failed']) if progress else 0
    conn.execute('''
        INSERT INTO lgfv_bond_detail_progress
            (snapshot_date,attempted,succeeded,failed,status,updated_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(snapshot_date) DO UPDATE SET status='running',updated_at=excluded.updated_at
    ''', (snapshot, attempted, succeeded, failed, 'running', _now()))
    conn.commit()
    result = {
        'success': True, 'snapshot_date': snapshot, 'attempted': 0,
        'succeeded': 0, 'failed': 0, 'warnings': [],
        'source_type': DETAIL_SOURCE_TYPE,
    }
    try:
        query = '''
            SELECT i.* FROM lgfv_bond_inventory i
            LEFT JOIN lgfv_bond_terms t
              ON t.snapshot_date=i.snapshot_date
             AND t.bond_defined_code=i.bond_defined_code
            WHERE i.snapshot_date=? AND (t.id IS NULL OR t.detail_status!='success')
            ORDER BY i.id
        '''
        rows = conn.execute(query, (snapshot,)).fetchall()
        for inventory in rows:
            if max_rows is not None and result['attempted'] >= max_rows:
                break
            code = inventory['bond_defined_code']
            result['attempted'] += 1
            attempted += 1
            try:
                if verbose:
                    print(f'[lgfv-detail] {code} {inventory["bond_name"]}', flush=True)
                payload = fetch_bond_detail(
                    code, timeout=timeout, retries=retries)
                terms = parse_bond_terms(snapshot, inventory, payload)
                _upsert_terms(conn, terms)
                _replace_scheduled_cashflows(conn, snapshot, terms)
                succeeded += 1
                result['succeeded'] += 1
            except Exception as exc:
                failed += 1
                result['failed'] += 1
                result['success'] = False
                warning = f'{code} 详情失败：{type(exc).__name__}: {exc}'
                result['warnings'].append(warning)
                error_row = {
                    'snapshot_date': snapshot,
                    'source_type': DETAIL_SOURCE_TYPE,
                    'bond_defined_code': code,
                    'bond_code': inventory['bond_code'],
                    'bond_name': inventory['bond_name'],
                    'bond_full_name': None,
                    'bond_type_code': inventory['bond_type_code'],
                    'bond_type': inventory['bond_type'],
                    'issuer': inventory['issuer'],
                    'issue_date': None, 'maturity_date': None,
                    'first_value_date': None, 'first_coupon_date': None,
                    'first_payment_date': None,
                    'planned_issue_amount': None, 'actual_issue_amount': None,
                    'par_value': None, 'issue_price': None, 'coupon_rate': None,
                    'coupon_type': None, 'coupon_frequency': None,
                    'bond_period': None, 'principal_amount_field': None,
                    'exercise_info_json': '[]', 'additional_issue_json': '[]',
                    'source_url': f'{PUBLIC_QUERY_URL}?bondDefinedCode={quote(code)}',
                    'raw_json': '{}', 'data_status': 'missing',
                    'detail_status': 'error', 'detail_error': warning,
                    'updated_at': _now(),
                }
                _upsert_terms(conn, error_row)
            conn.execute('''
                UPDATE lgfv_bond_detail_progress SET attempted=?,succeeded=?,failed=?,
                    last_error=?,updated_at=? WHERE snapshot_date=?
            ''', (attempted, succeeded, failed,
                  result['warnings'][-1] if result['warnings'] else None,
                  _now(), snapshot))
            conn.commit()
            if request_pause:
                time.sleep(float(request_pause))
        remaining = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_inventory i
            LEFT JOIN lgfv_bond_terms t ON t.snapshot_date=i.snapshot_date
             AND t.bond_defined_code=i.bond_defined_code
            WHERE i.snapshot_date=? AND (t.id IS NULL OR t.detail_status!='success')
        ''', (snapshot,)).fetchone()[0]
        status = 'done' if remaining == 0 else 'partial'
        conn.execute('''
            UPDATE lgfv_bond_detail_progress SET attempted=?,succeeded=?,failed=?,
                status=?,updated_at=? WHERE snapshot_date=?
        ''', (attempted, succeeded, failed, status, _now(), snapshot))
        conn.commit()
        result['remaining'] = int(remaining)
        result['status'] = status
        return result
    except BaseException as exc:
        # A process kill/interrupt can otherwise leave the progress row stuck
        # at ``running`` forever.  Preserve the already committed per-bond
        # rows and make the next invocation explicitly resumable.
        try:
            conn.execute('''
                UPDATE lgfv_bond_detail_progress
                SET attempted=?,succeeded=?,failed=?,status='partial',
                    last_error=?,updated_at=? WHERE snapshot_date=?
            ''', (
                attempted, succeeded, failed,
                f'{type(exc).__name__}: {exc}', _now(), snapshot,
            ))
            conn.commit()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def infer_notice_event_type(title):
    text = _clean(title) or ''
    has_interest = '付息' in text
    has_principal = any(token in text for token in ('兑付', '偿还本金', '还本'))
    if has_interest and has_principal:
        return 'interest_and_principal_notice'
    if has_principal:
        return 'principal_notice'
    if has_interest:
        return 'interest_notice'
    return 'other_cashflow_notice'


def fetch_notice_page(bond_type_code, page_no, start_date=NOTICE_MIN_DATE,
                      end_date=None, session=None, timeout=30, retries=2):
    client = session or requests
    end_date = end_date or date.today().isoformat()
    last_error = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            response = client.post(
                NOTICE_URL,
                data={
                    'channelId': NOTICE_CHANNEL_ID,
                    'bondSrno': str(bond_type_code),
                    'drftClAngl': '20',
                    'scnd': NOTICE_SECOND_TYPES,
                    'pageSize': str(NOTICE_PAGE_SIZE),
                    'pageNo': str(page_no),
                    'startDate': start_date,
                    'endDate': end_date,
                    'limit': '1',
                    'timeln': '0',
                },
                headers=REQUEST_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get('data') or {}
            records = payload.get('records') or []
            return {
                'total_count': int(data.get('total') or 0),
                'page_total': int(data.get('pageTotalSize') or 0),
                'page_no': int(page_no),
                'records': records,
            }
        except Exception as exc:
            last_error = exc
            if attempt < int(retries):
                time.sleep(min(5.0, 0.5 * (2 ** attempt)))
    raise last_error


def _notice_row(snapshot, bond_type_code, item):
    content_id = _clean(item.get('contentId'))
    if not content_id:
        return None
    draft_path = _clean(item.get('draftPath'))
    source_url = (
        'https://www.chinamoney.com.cn' + draft_path
        if draft_path and draft_path.startswith('/') else NOTICE_PAGE_SOURCE
    )
    attachment_url = (
        f'{NOTICE_FILE_BASE}?contentId={quote(content_id)}&priority=0&mode=open'
    )
    title = _clean(item.get('title')) or ''
    return {
        'snapshot_date': snapshot,
        'notice_content_id': content_id,
        'bond_type_code': str(bond_type_code),
        'release_date': _clean(item.get('releaseDate')),
        'title': title,
        'event_type': infer_notice_event_type(title),
        'draft_path': draft_path,
        'source_url': source_url,
        'attachment_url': attachment_url,
        'matched_bond_defined_code': None,
        'amount': None,
        'interest_amount': None,
        'principal_amount': None,
        'parse_status': 'metadata_only_attachment_not_parsed',
        'data_status': 'official_notice_metadata',
        'raw_json': json.dumps(item, ensure_ascii=False, sort_keys=True),
    }


def _upsert_notice(conn, row):
    conn.execute('''
        INSERT INTO lgfv_bond_notices (
            snapshot_date,notice_content_id,bond_type_code,release_date,title,
            event_type,draft_path,source_url,attachment_url,
            matched_bond_defined_code,amount,interest_amount,principal_amount,
            parse_status,data_status,raw_json,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(snapshot_date,notice_content_id) DO UPDATE SET
            bond_type_code=excluded.bond_type_code,
            release_date=excluded.release_date,
            title=excluded.title,
            event_type=excluded.event_type,
            draft_path=excluded.draft_path,
            source_url=excluded.source_url,
            attachment_url=excluded.attachment_url,
            raw_json=excluded.raw_json,
            updated_at=excluded.updated_at
    ''', (
        row['snapshot_date'], row['notice_content_id'], row['bond_type_code'],
        row['release_date'], row['title'], row['event_type'], row['draft_path'],
        row['source_url'], row['attachment_url'], row['matched_bond_defined_code'],
        row['amount'], row['interest_amount'], row['principal_amount'],
        row['parse_status'], row['data_status'], row['raw_json'], _now(), _now(),
    ))


def link_notice_records(conn, snapshot_date):
    """Conservatively link notice titles to a single inventory bond.

    The public notice feed does not expose ``bondDefinedCode``.  We only link
    when the issuer is unique in the snapshot, or when the exact bond name/full
    name appears in the title.  Ambiguous notices remain unlinked rather than
    being assigned by fuzzy guesses.
    """
    terms = conn.execute('''
        SELECT bond_defined_code,bond_name,bond_full_name,issuer
        FROM lgfv_bond_terms WHERE snapshot_date=? AND detail_status='success'
    ''', (snapshot_date,)).fetchall()
    inventory = conn.execute('''
        SELECT bond_defined_code,bond_name,issuer
        FROM lgfv_bond_inventory WHERE snapshot_date=?
    ''', (snapshot_date,)).fetchall()
    candidates = list(terms) if terms else list(inventory)
    by_issuer = {}
    for row in candidates:
        issuer = _clean(row['issuer'])
        if issuer:
            by_issuer.setdefault(issuer, []).append(row)
    linked = 0
    for notice in conn.execute('''
        SELECT id,title FROM lgfv_bond_notices
        WHERE snapshot_date=? AND matched_bond_defined_code IS NULL
    ''', (snapshot_date,)).fetchall():
        title = notice['title'] or ''
        matches = []
        for issuer, rows in by_issuer.items():
            if issuer in title:
                matches.extend(rows)
        unique = {row['bond_defined_code']: row for row in matches}
        if len(unique) > 1:
            named = []
            for row in unique.values():
                for name_field in ('bond_full_name', 'bond_name'):
                    name = _clean(row[name_field]) if name_field in row.keys() else None
                    if name and name in title:
                        named.append(row)
                        break
            unique = {row['bond_defined_code']: row for row in named}
        if len(unique) == 1:
            code = next(iter(unique))
            conn.execute('''
                UPDATE lgfv_bond_notices
                SET matched_bond_defined_code=?,updated_at=? WHERE id=?
            ''', (code, _now(), notice['id']))
            linked += 1
    conn.commit()
    return linked


def update_lgfv_bond_notices(db_path, bond_types=None, max_pages=None,
                             request_pause=0.15, timeout=30,
                             snapshot_date=None, start_date=NOTICE_MIN_DATE,
                             end_date=None, verbose=False):
    """Resume official interest/redemption notice metadata collection."""
    selected = tuple(bond_types or CANDIDATE_BOND_TYPES)
    snapshot = snapshot_date or date.today().isoformat()
    conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=60000')
    ensure_lgfv_market_tables(conn)
    result = {
        'success': True, 'snapshot_date': snapshot, 'rows_upserted': 0,
        'warnings': [], 'types': [], 'source_type': NOTICE_SOURCE_TYPE,
    }
    try:
        for type_code, type_name in selected:
            progress = conn.execute('''
                SELECT total_count,page_total,next_page,fetched_rows,status
                FROM lgfv_bond_notice_progress
                WHERE snapshot_date=? AND bond_type_code=?
            ''', (snapshot, str(type_code))).fetchone()
            next_page = int(progress[2]) if progress else 1
            fetched = int(progress[3]) if progress else 0
            page_total = int(progress[1]) if progress and progress[1] else None
            total = int(progress[0]) if progress and progress[0] else None
            if progress and progress[4] == 'done' and max_pages is None:
                result['types'].append({
                    'bond_type_code': str(type_code), 'bond_type': type_name,
                    'status': 'already_done', 'fetched_rows': fetched,
                    'page_total': page_total,
                })
                continue
            conn.execute('''
                INSERT INTO lgfv_bond_notice_progress
                    (snapshot_date,bond_type_code,bond_type,total_count,page_total,
                     next_page,fetched_rows,status,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(snapshot_date,bond_type_code) DO UPDATE SET
                    status='running',last_error=NULL,updated_at=excluded.updated_at
            ''', (snapshot, str(type_code), type_name, total, page_total,
                  next_page, fetched, 'running', _now()))
            conn.commit()
            pages_this_run = 0
            status = 'partial'
            last_error = None
            while True:
                if max_pages is not None and pages_this_run >= max_pages:
                    break
                try:
                    if verbose:
                        print(f'[lgfv-notice] {type_name} page {next_page}', flush=True)
                    page = fetch_notice_page(
                        type_code, next_page, start_date=start_date,
                        end_date=end_date, timeout=timeout,
                    )
                    total = (
                        page['total_count']
                        if page['total_count'] is not None else total
                    )
                    page_total = (
                        page['page_total']
                        if page['page_total'] is not None else page_total
                    )
                    for item in page['records']:
                        row = _notice_row(snapshot, type_code, item)
                        if row:
                            _upsert_notice(conn, row)
                            result['rows_upserted'] += 1
                            fetched += 1
                    pages_this_run += 1
                    # A type with no matching notices returns pageTotalSize=0;
                    # treat it as complete instead of paging forever.
                    is_done = bool(
                        page_total == 0 or
                        (page_total and next_page >= page_total)
                    )
                    next_page += 1
                    status = 'done' if is_done else 'partial'
                    conn.execute('''
                        UPDATE lgfv_bond_notice_progress SET total_count=?,page_total=?,
                            next_page=?,fetched_rows=?,status=?,last_error=NULL,updated_at=?
                        WHERE snapshot_date=? AND bond_type_code=?
                    ''', (total, page_total, next_page, fetched, status, _now(),
                          snapshot, str(type_code)))
                    conn.commit()
                    if is_done:
                        break
                    if request_pause:
                        time.sleep(float(request_pause))
                except Exception as exc:
                    last_error = f'{type(exc).__name__}: {exc}'
                    status = 'error'
                    result['success'] = False
                    result['warnings'].append(
                        f'{type_name} 第{next_page}页失败：{last_error}'
                    )
                    conn.execute('''
                        UPDATE lgfv_bond_notice_progress SET total_count=?,page_total=?,
                            next_page=?,fetched_rows=?,status=?,last_error=?,updated_at=?
                        WHERE snapshot_date=? AND bond_type_code=?
                    ''', (total, page_total, next_page, fetched, status, last_error,
                          _now(), snapshot, str(type_code)))
                    conn.commit()
                    break
            result['types'].append({
                'bond_type_code': str(type_code), 'bond_type': type_name,
                'status': status, 'fetched_rows': fetched,
                'page_total': page_total, 'next_page': next_page,
                'pages_this_run': pages_this_run,
                **({'error': last_error} if last_error else {}),
            })
            if status == 'error':
                break
        result['linked_rows'] = link_notice_records(conn, snapshot)
        return result
    finally:
        conn.close()


def _safe_sum(conn, query, params=()):
    value = conn.execute(query, params).fetchone()[0]
    return round(float(value), 6) if value is not None else 0.0


def build_lgfv_market_payload(db_path, as_of=None):
    """Build a private candidate-universe estimate with explicit coverage fields."""
    as_of_date = parse_date(as_of) if as_of else date.today()
    as_of_text = as_of_date.isoformat()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_lgfv_market_tables(conn)
        snapshot = conn.execute(
            'SELECT MAX(snapshot_date) FROM lgfv_bond_inventory'
        ).fetchone()[0]
        if not snapshot:
            return {
                'data_status': 'missing', 'snapshot_date': None,
                'as_of': as_of_text, 'source_type': SOURCE_TYPE,
                'scope_note': '尚未抓取候选债券清单。',
            }
        inv_n = conn.execute(
            'SELECT COUNT(*) FROM lgfv_bond_inventory WHERE snapshot_date=?',
            (snapshot,),
        ).fetchone()[0]
        term_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
        ''', (snapshot,)).fetchone()[0]
        amount_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND actual_issue_amount IS NOT NULL
        ''', (snapshot,)).fetchone()[0]
        planned_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND planned_issue_amount IS NOT NULL
        ''', (snapshot,)).fetchone()[0]
        active_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND maturity_date>? AND actual_issue_amount IS NOT NULL
        ''', (snapshot, as_of_text)).fetchone()[0]
        active_amount = _safe_sum(conn, '''
            SELECT SUM(actual_issue_amount) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND maturity_date>? AND actual_issue_amount IS NOT NULL
        ''', (snapshot, as_of_text))
        all_issued_amount = _safe_sum(conn, '''
            SELECT SUM(actual_issue_amount) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND actual_issue_amount IS NOT NULL
        ''', (snapshot,))
        all_planned_amount = _safe_sum(conn, '''
            SELECT SUM(planned_issue_amount) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND planned_issue_amount IS NOT NULL
        ''', (snapshot,))
        rate_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND maturity_date>? AND actual_issue_amount IS NOT NULL
              AND coupon_rate IS NOT NULL
        ''', (snapshot, as_of_text)).fetchone()[0]
        annual_interest = _safe_sum(conn, '''
            SELECT SUM(actual_issue_amount * coupon_rate / 100.0)
            FROM lgfv_bond_terms
            WHERE snapshot_date=? AND detail_status='success'
              AND maturity_date>? AND actual_issue_amount IS NOT NULL
              AND coupon_rate IS NOT NULL
        ''', (snapshot, as_of_text))
        scheduled_interest = _safe_sum(conn, '''
            SELECT SUM(amount) FROM lgfv_bond_cashflows
            WHERE snapshot_date=? AND event_type='scheduled_interest'
              AND event_date>? AND amount IS NOT NULL
        ''', (snapshot, as_of_text))
        scheduled_principal = _safe_sum(conn, '''
            SELECT SUM(amount) FROM lgfv_bond_cashflows
            WHERE snapshot_date=? AND event_type='scheduled_principal'
              AND event_date>? AND amount IS NOT NULL
        ''', (snapshot, as_of_text))
        notice_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_notices WHERE snapshot_date=?
        ''', (snapshot,)).fetchone()[0]
        linked_notice_n = conn.execute('''
            SELECT COUNT(*) FROM lgfv_bond_notices
            WHERE snapshot_date=? AND matched_bond_defined_code IS NOT NULL
        ''', (snapshot,)).fetchone()[0]
        return {
            'data_status': 'market_estimate' if term_n else 'metadata_only',
            'snapshot_date': snapshot,
            'as_of': as_of_text,
            'source_name': '中国货币网公开债券查询（底层与AKShare bond_info_cm一致）',
            'source_type': SOURCE_TYPE,
            'candidate_record_count': int(inv_n),
            'terms_record_count': int(term_n),
            'actual_issue_amount_record_count': int(amount_n),
            'planned_issue_amount_record_count': int(planned_n),
            'active_bond_count': int(active_n),
            'coupon_rate_record_count_active': int(rate_n),
            'historical_actual_issue_amount_total': all_issued_amount,
            'historical_planned_issue_amount_total': all_planned_amount,
            'actual_to_planned_issue_ratio': (
                round(all_issued_amount / all_planned_amount, 6)
                if all_planned_amount else None
            ),
            'active_issue_amount_total': active_amount,
            'estimated_current_balance_upper_bound': active_amount,
            'estimated_annual_interest_known_rate': annual_interest,
            'future_scheduled_interest_known_rate': scheduled_interest,
            'future_scheduled_principal': scheduled_principal,
            'notice_record_count': int(notice_n),
            'linked_notice_record_count': int(linked_notice_n),
            'balance_formula': (
                'active bond actual_issue_amount minus verified principal repayments; '
                'current implementation has no complete cross-market repayment snapshot, '
                'so active_issue_amount_total is an upper-bound estimate'
            ),
            'scope_note': (
                '这不是官方“城投债”分类，也不是财政部政府债务余额。候选集合覆盖中国货币网'
                '银行间若干债券类型；未补交易所市场、发行人分类、跨市场去重和完整存续余额。'
            ),
            'cashflow_note': (
                '付息计划由发行额、票面利率、付息频率和到期日推导；官方公告仅作为事件记录。'
                '扫描型PDF未提取到金额时保持金额缺失，不把应付计划写成已付。'
            ),
            'source_url': PUBLIC_QUERY_URL,
            'notice_source_url': NOTICE_PAGE_SOURCE,
        }
    finally:
        conn.close()
