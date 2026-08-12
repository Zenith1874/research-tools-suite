# -*- coding: utf-8 -*-
"""中国货币网债券清单侦察管线（AKShare ``bond_info_cm`` 的底层来源）。

这条管线只保存债券级元数据，暂不把发行金额当作当前余额，也不把结果并入
财政部官方政府债务。中国货币网的查询接口按债券类型分页，且单页最多返回
15 条；因此这里设计成逐页提交、可中断恢复的本地库存扫描。

城投分类不是中国货币网的官方字段。本模块的候选清单覆盖可能承载城投债的
银行间债券类型，后续还需要发行人分类、交易所债券补充、跨市场去重和存续
余额核验，才能形成 ``market_estimate``，当前 payload 明确标记为
``metadata_only``。
"""

import json
import sqlite3
import time
from datetime import date, datetime
from urllib.parse import quote

import requests


SOURCE_NAME = '中国货币网（AKShare bond_info_cm 底层接口）'
SOURCE_TYPE = 'chinamoney_lgfv_inventory'
LIST_URL = 'https://www.chinamoney.com.cn/ags/ms/cm-u-bond-md/BondMarketInfoList2'
CONDITION_URL = (
    'https://www.chinamoney.com.cn/ags/ms/cm-u-bond-md/'
    'BondBaseInfoSearchCondition'
)
DETAIL_URL = 'https://www.chinamoney.com.cn/ags/ms/cm-u-bond-md/BondDetailInfo'
PUBLIC_QUERY_URL = 'https://www.chinamoney.com.cn/chinese/scsjzqxx/'

REQUEST_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Origin': 'https://www.chinamoney.com.cn',
    'Referer': PUBLIC_QUERY_URL,
    'X-Requested-With': 'XMLHttpRequest',
    # The public endpoint intermittently leaves keep-alive connections open;
    # one request per page is more reliable for a resumable crawler.
    'Connection': 'close',
}

# 这些类型可能包含城投企业发行的债券；它们不是“城投债”官方分类。
CANDIDATE_BOND_TYPES = (
    ('100004', '企业债'),
    ('100006', '短期融资券'),
    ('100010', '中期票据'),
    ('100025', '集合票据'),
    ('100029', '超短期融资券'),
    ('100055', '项目收益票据'),
    ('100057', '项目收益债券'),
    ('100072', '资产支持票据'),
    ('100073', '绿色债务融资工具'),
)

LIST_PAGE_SIZE = 15  # 接口实际返回上限；AKShare 也使用这个值


def ensure_lgfv_inventory_tables(conn):
    """Create private inventory/progress tables without touching official rows."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_inventory (
            id INTEGER PRIMARY KEY,
            snapshot_date TEXT NOT NULL,
            source_type TEXT NOT NULL,
            bond_defined_code TEXT NOT NULL,
            bond_code TEXT,
            bond_name TEXT,
            bond_type_code TEXT,
            bond_type TEXT,
            issuer TEXT,
            rating TEXT,
            issue_start_date TEXT,
            issue_end_date TEXT,
            source_url TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            data_status TEXT NOT NULL,
            current_balance REAL,
            current_balance_status TEXT NOT NULL DEFAULT 'not_disclosed',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(snapshot_date, source_type, bond_defined_code)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS lgfv_bond_inventory_progress (
            snapshot_date TEXT NOT NULL,
            source_type TEXT NOT NULL,
            bond_type_code TEXT NOT NULL,
            bond_type TEXT NOT NULL,
            total_count INTEGER,
            page_total INTEGER,
            next_page INTEGER NOT NULL DEFAULT 1,
            fetched_rows INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(snapshot_date, source_type, bond_type_code)
        )
    ''')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text != '---' else None


def _list_payload(bond_type_code, page_no):
    return {
        'pageNo': str(page_no),
        'pageSize': str(LIST_PAGE_SIZE),
        'bondName': '',
        'bondCode': '',
        'issueEnty': '',
        'bondType': bond_type_code,
        'bondSpclPrjctVrty': '',
        'couponType': '',
        'issueYear': '',
        'entyDefinedCode': '',
        'rtngShrt': '',
    }


def fetch_bond_type_page(session, bond_type_code, page_no, timeout=30,
                         retries=0):
    """Fetch one official page; callers control pacing and retries.

    The public endpoint is more stable when each page uses a fresh HTTP
    request. ``session`` remains injectable for unit tests and callers that
    explicitly need cookies, but the default updater passes ``None``.
    """
    client = session or requests
    last_error = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            response = client.post(
                LIST_URL,
                data=_list_payload(bond_type_code, page_no),
                headers=REQUEST_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get('data') or {}
            error = _clean(data.get('errorMsg'))
            if error:
                raise RuntimeError(f'中国货币网返回错误：{error}')
            rows = data.get('resultList') or []
            if not isinstance(rows, list):
                raise ValueError('resultList 不是列表')
            return {
                'total_count': int(data.get('total') or 0),
                'page_total': int(data.get('pageTotal') or 0),
                'page_no': int(data.get('pageNo') or page_no),
                'rows': rows,
            }
        except Exception as exc:
            last_error = exc
            if attempt < int(retries):
                time.sleep(min(5.0, 0.5 * (2 ** attempt)))
    raise last_error


def _row_from_api(snapshot_date, bond_type_code, page_no, row):
    defined = _clean(row.get('bondDefinedCode'))
    if not defined:
        return None
    source_url = (
        f'{PUBLIC_QUERY_URL}?bondType={quote(str(bond_type_code))}'
        f'&pageNo={page_no}&bondDefinedCode={quote(defined)}'
    )
    return {
        'snapshot_date': snapshot_date,
        'source_type': SOURCE_TYPE,
        'bond_defined_code': defined,
        'bond_code': _clean(row.get('bondCode')),
        'bond_name': _clean(row.get('bondName')),
        'bond_type_code': _clean(row.get('bondTypeCode')) or str(bond_type_code),
        'bond_type': _clean(row.get('bondType')),
        'issuer': _clean(row.get('entyFullName')),
        'rating': _clean(row.get('debtRtng')),
        'issue_start_date': _clean(row.get('issueStartDate')),
        'issue_end_date': _clean(row.get('issueEndDate')),
        'source_url': source_url,
        'raw_json': json.dumps(row, ensure_ascii=False, sort_keys=True),
        'data_status': 'official_metadata',
        'current_balance': None,
        'current_balance_status': 'not_disclosed_in_list',
        'updated_at': _now(),
    }


def _upsert_inventory_rows(conn, rows):
    inserted_or_updated = 0
    for row in rows:
        conn.execute('''
            INSERT INTO lgfv_bond_inventory (
                snapshot_date, source_type, bond_defined_code, bond_code,
                bond_name, bond_type_code, bond_type, issuer, rating,
                issue_start_date, issue_end_date, source_url, raw_json,
                data_status, current_balance, current_balance_status,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(snapshot_date, source_type, bond_defined_code) DO UPDATE SET
                bond_code=excluded.bond_code,
                bond_name=excluded.bond_name,
                bond_type_code=excluded.bond_type_code,
                bond_type=excluded.bond_type,
                issuer=COALESCE(excluded.issuer, lgfv_bond_inventory.issuer),
                rating=COALESCE(excluded.rating, lgfv_bond_inventory.rating),
                issue_start_date=COALESCE(excluded.issue_start_date, lgfv_bond_inventory.issue_start_date),
                issue_end_date=COALESCE(excluded.issue_end_date, lgfv_bond_inventory.issue_end_date),
                source_url=excluded.source_url,
                raw_json=excluded.raw_json,
                data_status=excluded.data_status,
                updated_at=excluded.updated_at
        ''', (
            row['snapshot_date'], row['source_type'], row['bond_defined_code'],
            row['bond_code'], row['bond_name'], row['bond_type_code'],
            row['bond_type'], row['issuer'], row['rating'],
            row['issue_start_date'], row['issue_end_date'], row['source_url'],
            row['raw_json'], row['data_status'], row['current_balance'],
            row['current_balance_status'], row['updated_at'], row['updated_at'],
        ))
        inserted_or_updated += 1
    return inserted_or_updated


def update_lgfv_bond_inventory(db_path, bond_types=None, max_pages=None,
                               request_pause=0.15, timeout=30,
                               snapshot_date=None, verbose=False):
    """Resume a candidate inventory scan using official ChinaMoney pages.

    ``max_pages`` is intended for a smoke test. With ``None`` the selected
    candidate types are scanned to their reported page totals. Existing rows
    are upserted; a failed page never deletes a prior snapshot.
    """
    selected = tuple(bond_types or CANDIDATE_BOND_TYPES)
    snapshot = snapshot_date or date.today().isoformat()
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute('PRAGMA busy_timeout=60000')
    ensure_lgfv_inventory_tables(conn)
    # Do not reuse a persistent connection: the public endpoint intermittently
    # stalls on the second paginated request even though a fresh request works.
    session = None
    summary = {
        'success': True,
        'snapshot_date': snapshot,
        'source_name': SOURCE_NAME,
        'source_type': SOURCE_TYPE,
        'types': [],
        'rows_upserted': 0,
        'warnings': [],
    }
    try:
        for type_code, type_name in selected:
            progress = conn.execute('''
                SELECT total_count,page_total,next_page,fetched_rows,status
                FROM lgfv_bond_inventory_progress
                WHERE snapshot_date=? AND source_type=? AND bond_type_code=?
            ''', (snapshot, SOURCE_TYPE, type_code)).fetchone()
            if progress and progress[4] == 'done' and max_pages is None:
                summary['types'].append({
                    'bond_type_code': type_code, 'bond_type': type_name,
                    'status': 'already_done', 'fetched_rows': progress[3],
                    'page_total': progress[1],
                })
                continue
            next_page = int(progress[2]) if progress else 1
            fetched_rows = int(progress[3]) if progress else 0
            total_count = int(progress[0]) if progress and progress[0] else None
            page_total = int(progress[1]) if progress and progress[1] else None
            started = _now()
            conn.execute('''
                INSERT INTO lgfv_bond_inventory_progress (
                    snapshot_date,source_type,bond_type_code,bond_type,
                    total_count,page_total,next_page,fetched_rows,status,
                    started_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(snapshot_date,source_type,bond_type_code) DO UPDATE SET
                    bond_type=excluded.bond_type, status='running',
                    last_error=NULL, updated_at=excluded.updated_at
            ''', (snapshot, SOURCE_TYPE, type_code, type_name,
                  total_count, page_total, next_page, fetched_rows,
                  'running', started, started))
            conn.commit()
            pages_this_run = 0
            status = 'partial'
            last_error = None
            while True:
                if max_pages is not None and pages_this_run >= max_pages:
                    break
                try:
                    if verbose:
                        print(f'[lgfv] {type_name} page {next_page} request',
                              flush=True)
                    page = fetch_bond_type_page(
                        session, type_code, next_page, timeout=timeout,
                        retries=3,
                    )
                    if verbose:
                        print(f'[lgfv] {type_name} page {next_page} response '
                              f"rows={len(page['rows'])}", flush=True)
                    total_count = page['total_count'] or total_count
                    page_total = page['page_total'] or page_total
                    rows = [
                        parsed for raw in page['rows']
                        if (parsed := _row_from_api(snapshot, type_code,
                                                    next_page, raw))
                    ]
                    if not rows and next_page <= (page_total or next_page):
                        raise RuntimeError(
                            f'第{next_page}页没有可用债券记录，接口页数={page_total}'
                        )
                    page_rows = _upsert_inventory_rows(conn, rows)
                    fetched_rows += page_rows
                    summary['rows_upserted'] += page_rows
                    pages_this_run += 1
                    is_done = bool(page_total and next_page >= page_total)
                    next_page += 1
                    status = 'done' if is_done else 'partial'
                    conn.execute('''
                        UPDATE lgfv_bond_inventory_progress SET
                            total_count=?,page_total=?,next_page=?,fetched_rows=?,
                            status=?,last_error=NULL,updated_at=?
                        WHERE snapshot_date=? AND source_type=? AND bond_type_code=?
                    ''', (total_count, page_total, next_page, fetched_rows, status,
                          _now(), snapshot, SOURCE_TYPE, type_code))
                    conn.commit()
                    if verbose:
                        print(f'[lgfv] {type_name} page {next_page - 1} committed '
                              f'next={next_page}', flush=True)
                    if is_done:
                        break
                    if request_pause:
                        time.sleep(float(request_pause))
                except Exception as exc:
                    last_error = f'{type(exc).__name__}: {exc}'
                    status = 'error'
                    conn.execute('''
                        UPDATE lgfv_bond_inventory_progress SET
                            total_count=?,page_total=?,next_page=?,fetched_rows=?,
                            status=?,last_error=?,updated_at=?
                        WHERE snapshot_date=? AND source_type=? AND bond_type_code=?
                    ''', (total_count, page_total, next_page, fetched_rows, status,
                          last_error, _now(), snapshot, SOURCE_TYPE, type_code))
                    conn.commit()
                    summary['success'] = False
                    summary['warnings'].append(
                        f'{type_name} 第{next_page}页失败：{last_error}'
                    )
                    break
            item = {
                'bond_type_code': type_code, 'bond_type': type_name,
                'status': status, 'fetched_rows': fetched_rows,
                'page_total': page_total, 'next_page': next_page,
                'pages_this_run': pages_this_run,
            }
            if last_error:
                item['error'] = last_error
            summary['types'].append(item)
            if status == 'error':
                # Do not hammer the next type after an upstream block.
                break
        return summary
    finally:
        conn.close()


def build_lgfv_bond_inventory_payload(db_path):
    """Return inventory coverage and explicitly separate it from balances."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        ensure_lgfv_inventory_tables(conn)
        snapshot = conn.execute(
            'SELECT MAX(snapshot_date) FROM lgfv_bond_inventory'
        ).fetchone()[0]
        if not snapshot:
            return {
                'data_status': 'missing', 'snapshot_date': None,
                'record_count': 0, 'current_balance_record_count': 0,
                'source_name': SOURCE_NAME, 'source_type': SOURCE_TYPE,
                'scope_note': '尚未抓取候选债券清单。',
            }
        row = conn.execute('''
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN issuer IS NOT NULL AND TRIM(issuer)!='' THEN 1 ELSE 0 END) AS issuer_n,
                   SUM(CASE WHEN current_balance IS NOT NULL THEN 1 ELSE 0 END) AS balance_n,
                   COUNT(DISTINCT bond_defined_code) AS distinct_defined_n
            FROM lgfv_bond_inventory WHERE snapshot_date=?
        ''', (snapshot,)).fetchone()
        counts = conn.execute('''
            SELECT bond_type_code,bond_type,COUNT(*) AS n
            FROM lgfv_bond_inventory WHERE snapshot_date=?
            GROUP BY bond_type_code,bond_type ORDER BY bond_type_code
        ''', (snapshot,)).fetchall()
        n = int(row['n'] or 0)
        issuer_n = int(row['issuer_n'] or 0)
        return {
            'data_status': 'metadata_only' if n else 'missing',
            'snapshot_date': snapshot,
            'record_count': n,
            'distinct_bond_count': int(row['distinct_defined_n'] or 0),
            'issuer_record_count': issuer_n,
            'issuer_coverage_pct': round(issuer_n / n * 100, 2) if n else None,
            'current_balance_record_count': int(row['balance_n'] or 0),
            'by_bond_type': [dict(item) for item in counts],
            'source_name': SOURCE_NAME,
            'source_type': SOURCE_TYPE,
            'source_url': PUBLIC_QUERY_URL,
            'scope_note': (
                '这是中国货币网银行间债券元数据候选库存，不是城投债官方分类；'
                '清单接口没有当前存续余额字段，不能把发行金额或清单行数当作城投债余额。'
            ),
            'next_steps': [
                '补充发行人分类规则并逐只核验发行人',
                '补充交易所公司债/企业债并跨市场去重',
                '从存续期公告或授权债券快照获取当前余额',
            ],
        }
    finally:
        conn.close()
