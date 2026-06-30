import calendar
import json
import re
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


PBOC_SOURCE_NAME = '中国人民银行'
SOURCE_TYPE = 'pboc_buyout_reverse_repo'
ENTRY_URL = 'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5492845/b0da893b-1.html'
PAGE_URLS = [
    ENTRY_URL,
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5492845/b0da893b-2.html',
]
DETAIL_PATH_RE = re.compile(r'/zhengcehuobisi/125207/125213/125431/5492845/[^/]+/index\.html$')


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table):
    return {row['name'] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_column(conn, table, name, ddl):
    if name not in _columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


def ensure_pboc_buyout_reverse_repo_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pboc_buyout_reverse_repo_announcements (
        id INTEGER PRIMARY KEY,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT UNIQUE,
        source_title TEXT,
        announcement_kind TEXT,
        notice_no TEXT,
        list_page_url TEXT,
        list_page_no INTEGER,
        list_order INTEGER,
        listed_date TEXT,
        published_date TEXT,
        raw_text TEXT,
        parser_notes TEXT,
        parsed_operation_count INTEGER,
        data_status TEXT,
        parse_status TEXT,
        error TEXT,
        updated_at TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pboc_buyout_reverse_repo_operations (
        id INTEGER PRIMARY KEY,
        operation_id TEXT UNIQUE,
        operation_date TEXT,
        buy_date TEXT,
        buy_time TEXT,
        maturity_date TEXT,
        maturity_date_status TEXT,
        amount REAL,
        term_months INTEGER,
        term_days INTEGER,
        unit TEXT,
        announcement_kind TEXT,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT,
        source_title TEXT,
        published_date TEXT,
        raw_text TEXT,
        parser_notes TEXT,
        data_status TEXT,
        updated_at TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pboc_buyout_reverse_repo_monthly_stock (
        id INTEGER PRIMARY KEY,
        period TEXT UNIQUE,
        month_end_date TEXT,
        outstanding_amount REAL,
        operation_count INTEGER,
        matured_operation_count INTEGER,
        derived_maturity_count INTEGER,
        active_operation_dates TEXT,
        active_operations_json TEXT,
        unit TEXT,
        data_status TEXT,
        formula TEXT,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT,
        parser_notes TEXT,
        updated_at TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS fiscal_debt_sources (
        id INTEGER PRIMARY KEY,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT UNIQUE,
        source_title TEXT,
        published_date TEXT,
        parser_notes TEXT,
        raw_text TEXT,
        parsed_indicators TEXT,
        status TEXT,
        error TEXT,
        updated_at TEXT
    )''')
    for name, ddl in [
        ('buy_date', 'TEXT'),
        ('buy_time', 'TEXT'),
        ('announcement_kind', 'TEXT'),
    ]:
        _add_column(conn, 'pboc_buyout_reverse_repo_operations', name, ddl)
    for name, ddl in [
        ('active_operation_dates', 'TEXT'),
        ('active_operations_json', 'TEXT'),
    ]:
        _add_column(conn, 'pboc_buyout_reverse_repo_monthly_stock', name, ddl)


def fetch_html(url):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    return r.content.decode('utf-8', errors='replace'), r.url


def text_from_html(html):
    return BeautifulSoup(html, 'html.parser').get_text('\n', strip=True)


def clean_title(title):
    return re.sub(r'\s+', ' ', (title or '').replace('_中国人民银行', '')).strip()


def classify_announcement(title):
    if '招标公告' in title:
        return 'tender'
    if '业务公告' in title:
        return 'business'
    return 'other'


def parse_notice_no(title):
    m = re.search(r'\[(\d{4})\]\s*第\s*(\d+)\s*号', title or '')
    return f'{m.group(1)}-{int(m.group(2)):02d}' if m else None


def discover_announcements():
    out = []
    seen = set()
    for page_no, page in enumerate(PAGE_URLS, start=1):
        html, final_url = fetch_html(page)
        soup = BeautifulSoup(html, 'html.parser')
        order = 0
        for a in soup.find_all('a'):
            href = a.get('href') or ''
            full = urljoin(final_url, href)
            if not DETAIL_PATH_RE.search(href) and not DETAIL_PATH_RE.search(full):
                continue
            if full in seen:
                continue
            title = clean_title(a.get_text(' ', strip=True))
            if '买断式逆回购' not in title:
                continue
            order += 1
            seen.add(full)
            parent_text = ''
            node = a
            for _ in range(4):
                if not node:
                    break
                node = node.parent
                text_for_date = node.get_text(' ', strip=True) if node else ''
                if re.search(r'20\d{2}-\d{2}-\d{2}', text_for_date):
                    parent_text = text_for_date
                    break
            date_match = re.search(r'(20\d{2}-\d{2}-\d{2})', parent_text)
            out.append({
                'source_name': PBOC_SOURCE_NAME,
                'source_type': SOURCE_TYPE,
                'source_url': full,
                'source_title': title,
                'announcement_kind': classify_announcement(title),
                'notice_no': parse_notice_no(title),
                'list_page_url': final_url,
                'list_page_no': page_no,
                'list_order': order,
                'listed_date': date_match.group(1) if date_match else None,
            })
    return out


def parse_date_cn(text):
    m = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', text or '')
    if not m:
        return None
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'


def parse_published(text, listed_date=None):
    m = re.search(r'(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}', text or '')
    return m.group(1) if m else listed_date


def add_months(date_obj, months):
    month = date_obj.month - 1 + months
    year = date_obj.year + month // 12
    month = month % 12 + 1
    day = min(date_obj.day, calendar.monthrange(year, month)[1])
    return date_obj.replace(year=year, month=month, day=day)


def parse_time(text):
    m = re.search(r'(\d{1,2}:\d{2})', text or '')
    return m.group(1) if m else None


def parse_operation_page(item):
    html, final_url = fetch_html(item['source_url'])
    soup = BeautifulSoup(html, 'html.parser')
    title = clean_title(soup.find('title').get_text(' ', strip=True) if soup.find('title') else item['source_title'])
    text = text_from_html(html)
    compact = re.sub(r'\s+', '', text)
    published_date = parse_published(text, item.get('listed_date'))
    if '招标公告' not in title:
        return [], {
            'published_date': published_date,
            'raw_text': text[-1500:],
            'parser_notes': '公告已归档；非招标公告，不参与逐笔操作和月末存量测算。',
        }
    operation_date = parse_date_cn(compact)
    if not operation_date:
        raise RuntimeError('未解析出操作日期')
    body_match = re.search(r'(为保持.*?中国人民银行公开市场业务操作室)', text, re.S)
    raw_text = body_match.group(1).strip() if body_match else text[-1500:]
    tranches = []
    for m in re.finditer(r'(\d+)个月（\s*(\d+)\s*天）\s*(\d+(?:\.\d+)?)亿元', compact):
        tranches.append({'term_months': int(m.group(1)), 'term_days': int(m.group(2)), 'amount': float(m.group(3))})
    if not tranches:
        amount_match = re.search(r'开展(\d+(?:\.\d+)?)亿元买断式逆回购操作', compact)
        if not amount_match:
            raise RuntimeError('未解析出操作金额')
        term_months = None
        term_days = None
        m = re.search(r'期限为(\d+)个月（\s*(\d+)\s*天）', compact)
        if m:
            term_months = int(m.group(1))
            term_days = int(m.group(2))
        else:
            m = re.search(r'期限为(\d+)天', compact)
            if m:
                term_days = int(m.group(1))
        if not term_days and term_months is None:
            raise RuntimeError('未解析出期限')
        tranches.append({'term_months': term_months, 'term_days': term_days, 'amount': float(amount_match.group(1))})

    operations = []
    explicit_maturity = re.search(r'到期日为(20\d{2}年\d{1,2}月\d{1,2}日)', compact)
    operation_time = parse_time(text)
    for idx, tranche in enumerate(tranches, start=1):
        maturity_status = 'official'
        if explicit_maturity and len(tranches) == 1:
            maturity_date = parse_date_cn(explicit_maturity.group(1))
        else:
            start = datetime.strptime(operation_date, '%Y-%m-%d')
            if tranche['term_months']:
                maturity = add_months(start, tranche['term_months'])
            else:
                maturity = start + timedelta(days=tranche['term_days'])
            maturity_date = maturity.strftime('%Y-%m-%d')
            maturity_status = 'derived'
        suffix = '' if len(tranches) == 1 else f"-{tranche['term_months']}m-{idx}"
        operations.append({
            'operation_id': re.sub(r'\s+', '', title) + suffix,
            'operation_date': operation_date,
            'buy_date': operation_date,
            'buy_time': operation_time,
            'maturity_date': maturity_date,
            'maturity_date_status': maturity_status,
            'amount': tranche['amount'],
            'term_months': tranche['term_months'],
            'term_days': tranche['term_days'],
            'unit': '亿元',
            'announcement_kind': 'tender',
            'source_name': PBOC_SOURCE_NAME,
            'source_type': SOURCE_TYPE,
            'source_url': final_url,
            'source_title': title,
            'published_date': published_date,
            'raw_text': raw_text,
            'parser_notes': '解析自中国人民银行公开市场买断式逆回购招标公告；买入/操作日、金额、期限来自公告，未明示到期日时按操作日加期限推算。',
            'data_status': 'official',
        })
    return operations, {
        'published_date': published_date,
        'raw_text': raw_text,
        'parser_notes': '招标公告已解析为逐笔买断式逆回购操作，并用于月末未到期本金存量测算。',
    }


def month_end(date_str):
    d = datetime.strptime(date_str, '%Y-%m-%d')
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def build_monthly_stock(operations):
    if not operations:
        return []
    start = month_end(min(datetime.strptime(o['operation_date'], '%Y-%m-%d') for o in operations).strftime('%Y-%m-%d'))
    end = month_end(max(datetime.strptime(o['maturity_date'], '%Y-%m-%d') for o in operations).strftime('%Y-%m-%d'))
    rows = []
    current = start
    while current <= end:
        outstanding = 0.0
        active_ops = []
        matured = 0
        for op in operations:
            op_date = datetime.strptime(op['operation_date'], '%Y-%m-%d')
            mat_date = datetime.strptime(op['maturity_date'], '%Y-%m-%d')
            if op_date <= current < mat_date:
                outstanding += op['amount']
                active_ops.append({
                    'operation_id': op['operation_id'],
                    'buy_date': op['buy_date'],
                    'buy_time': op.get('buy_time'),
                    'maturity_date': op['maturity_date'],
                    'maturity_date_status': op['maturity_date_status'],
                    'amount': op['amount'],
                    'term_months': op['term_months'],
                    'term_days': op['term_days'],
                    'source_title': op['source_title'],
                    'source_url': op['source_url'],
                })
            elif mat_date <= current:
                matured += 1
        active_ops.sort(key=lambda x: (x['buy_date'], x['maturity_date'], x['amount']))
        rows.append({
            'period': f'{current.year}-{current.month:02d}',
            'month_end_date': current.strftime('%Y-%m-%d'),
            'outstanding_amount': outstanding,
            'operation_count': len(active_ops),
            'matured_operation_count': matured,
            'derived_maturity_count': sum(1 for op in active_ops if op['maturity_date_status'] == 'derived'),
            'active_operation_dates': ', '.join(sorted({op['buy_date'] for op in active_ops})),
            'active_operations_json': json.dumps(active_ops, ensure_ascii=False),
            'unit': '亿元',
            'data_status': 'derived',
            'formula': 'sum(amount for operation_date <= month_end_date < maturity_date)',
        })
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=31)
        else:
            nxt = current.replace(month=current.month + 1, day=1)
            current = nxt.replace(day=calendar.monthrange(nxt.year, nxt.month)[1])
    return rows


def calculate_outstanding_at(operations, as_of_date):
    as_of = datetime.strptime(as_of_date, '%Y-%m-%d')
    active = []
    for op in operations:
        operation_date = datetime.strptime(op['operation_date'], '%Y-%m-%d')
        maturity_date = datetime.strptime(op['maturity_date'], '%Y-%m-%d')
        if operation_date <= as_of < maturity_date:
            active.append(op)
    active.sort(key=lambda row: (row['operation_date'], row['maturity_date'], row['operation_id']))
    return {
        'as_of_date': as_of_date,
        'outstanding_amount': sum(float(op['amount']) for op in active),
        'operation_count': len(active),
        'derived_maturity_count': sum(1 for op in active if op['maturity_date_status'] == 'derived'),
        'data_status': 'derived',
        'formula': 'sum(amount for operation_date <= as_of_date < maturity_date)',
        'active_operations': active,
    }


def _insert_announcement(conn, ann, now, parsed_count, detail, status='success', error=None):
    conn.execute('''INSERT INTO pboc_buyout_reverse_repo_announcements (
        source_name,source_type,source_url,source_title,announcement_kind,notice_no,list_page_url,
        list_page_no,list_order,listed_date,published_date,raw_text,parser_notes,parsed_operation_count,
        data_status,parse_status,error,updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(source_url) DO UPDATE SET
        source_title=excluded.source_title,announcement_kind=excluded.announcement_kind,notice_no=excluded.notice_no,
        list_page_url=excluded.list_page_url,list_page_no=excluded.list_page_no,list_order=excluded.list_order,
        listed_date=excluded.listed_date,published_date=excluded.published_date,raw_text=excluded.raw_text,
        parser_notes=excluded.parser_notes,parsed_operation_count=excluded.parsed_operation_count,
        data_status=excluded.data_status,parse_status=excluded.parse_status,error=excluded.error,updated_at=excluded.updated_at
    ''', (
        ann['source_name'], ann['source_type'], ann['source_url'], ann['source_title'],
        ann['announcement_kind'], ann['notice_no'], ann['list_page_url'], ann['list_page_no'],
        ann['list_order'], ann.get('listed_date'), detail.get('published_date'), detail.get('raw_text'),
        detail.get('parser_notes'), parsed_count, 'official' if status == 'success' else 'missing',
        status, error, now,
    ))
    conn.execute('''INSERT INTO fiscal_debt_sources (
        source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
        parsed_indicators,status,error,updated_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(source_url) DO UPDATE SET
        source_title=excluded.source_title,published_date=excluded.published_date,parser_notes=excluded.parser_notes,
        raw_text=excluded.raw_text,parsed_indicators=excluded.parsed_indicators,status=excluded.status,
        error=excluded.error,updated_at=excluded.updated_at
    ''', (
        PBOC_SOURCE_NAME, SOURCE_TYPE, ann['source_url'], ann['source_title'], detail.get('published_date'),
        detail.get('parser_notes'), detail.get('raw_text'),
        json.dumps(['announcement_archive'] + (['amount', 'buy_date', 'maturity_date'] if parsed_count else []), ensure_ascii=False),
        status, error, now,
    ))


def update_pboc_buyout_reverse_repo(db_path):
    parser_errors = []
    parsed = []
    announcements = []
    with connect(db_path) as conn:
        ensure_pboc_buyout_reverse_repo_tables(conn)
        now = datetime.now().isoformat()
        try:
            announcements = discover_announcements()
        except Exception as exc:
            parser_errors.append({'source_url': ENTRY_URL, 'error': str(exc)})
        for ann in announcements:
            try:
                ops, detail = parse_operation_page(ann)
                parsed.extend(ops)
                _insert_announcement(conn, ann, now, len(ops), detail)
            except Exception as exc:
                parser_errors.append({'source_url': ann['source_url'], 'error': str(exc)})
                _insert_announcement(conn, ann, now, 0, {
                    'published_date': ann.get('listed_date'),
                    'raw_text': '',
                    'parser_notes': '公告归档或解析失败。',
                }, status='error', error=str(exc))
        if not announcements or not parsed:
            conn.rollback()
            return {
                'success': False,
                'announcement_records': len(announcements),
                'operation_records': 0,
                'parser_errors': parser_errors,
                'error': '本次未解析出完整买断式逆回购操作；已保留旧数据。',
            }
        for op in parsed:
            conn.execute('''INSERT INTO pboc_buyout_reverse_repo_operations (
                operation_id,operation_date,buy_date,buy_time,maturity_date,maturity_date_status,amount,
                term_months,term_days,unit,announcement_kind,source_name,source_type,source_url,source_title,
                published_date,raw_text,parser_notes,data_status,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(operation_id) DO UPDATE SET
                operation_date=excluded.operation_date,buy_date=excluded.buy_date,buy_time=excluded.buy_time,
                maturity_date=excluded.maturity_date,maturity_date_status=excluded.maturity_date_status,
                amount=excluded.amount,term_months=excluded.term_months,term_days=excluded.term_days,
                unit=excluded.unit,announcement_kind=excluded.announcement_kind,source_url=excluded.source_url,
                source_title=excluded.source_title,published_date=excluded.published_date,raw_text=excluded.raw_text,
                parser_notes=excluded.parser_notes,data_status=excluded.data_status,updated_at=excluded.updated_at
            ''', (
                op['operation_id'], op['operation_date'], op['buy_date'], op.get('buy_time'), op['maturity_date'],
                op['maturity_date_status'], op['amount'], op['term_months'], op['term_days'], op['unit'],
                op['announcement_kind'], op['source_name'], op['source_type'], op['source_url'], op['source_title'],
                op['published_date'], op['raw_text'], op['parser_notes'], op['data_status'], now,
            ))
        stock_rows = build_monthly_stock(parsed)
        source_urls = json.dumps([op['source_url'] for op in parsed], ensure_ascii=False)
        for row in stock_rows:
            conn.execute('''INSERT INTO pboc_buyout_reverse_repo_monthly_stock (
                period,month_end_date,outstanding_amount,operation_count,matured_operation_count,
                derived_maturity_count,active_operation_dates,active_operations_json,unit,data_status,formula,
                source_name,source_type,source_url,parser_notes,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(period) DO UPDATE SET
                month_end_date=excluded.month_end_date,outstanding_amount=excluded.outstanding_amount,
                operation_count=excluded.operation_count,matured_operation_count=excluded.matured_operation_count,
                derived_maturity_count=excluded.derived_maturity_count,
                active_operation_dates=excluded.active_operation_dates,
                active_operations_json=excluded.active_operations_json,data_status=excluded.data_status,
                formula=excluded.formula,source_url=excluded.source_url,parser_notes=excluded.parser_notes,
                updated_at=excluded.updated_at
            ''', (
                row['period'], row['month_end_date'], row['outstanding_amount'], row['operation_count'],
                row['matured_operation_count'], row['derived_maturity_count'], row['active_operation_dates'],
                row['active_operations_json'], row['unit'], row['data_status'], row['formula'],
                PBOC_SOURCE_NAME, SOURCE_TYPE, source_urls,
                '月末存量由逐笔买断式逆回购招标公告按未到期本金合计测算；不是单篇公告原始值。',
                now,
            ))
        conn.commit()
    today = datetime.now().date()
    completed_stock_rows = [
        row for row in stock_rows
        if datetime.strptime(row['month_end_date'], '%Y-%m-%d').date() <= today
    ] if parsed else []
    return {
        'success': True,
        'entry_url': ENTRY_URL,
        'announcement_records': len(announcements),
        'tender_announcement_records': sum(1 for ann in announcements if ann['announcement_kind'] == 'tender'),
        'business_announcement_records': sum(1 for ann in announcements if ann['announcement_kind'] == 'business'),
        'operation_records': len(parsed),
        'monthly_stock_records': len(stock_rows) if parsed else 0,
        'latest_operation_date': max([o['operation_date'] for o in parsed], default=None),
        'latest_stock_period': completed_stock_rows[-1]['period'] if completed_stock_rows else None,
        'projection_latest_stock_period': max([r['period'] for r in stock_rows], default=None) if parsed else None,
        'parser_errors': parser_errors,
    }


def _coverage(conn, table):
    if table == 'pboc_buyout_reverse_repo_announcements':
        row = conn.execute('''SELECT count(*) records,min(listed_date) earliest_period,max(listed_date) latest_period,
            sum(case when source_url is null or source_url='' then 1 else 0 end) missing_source_url
            FROM pboc_buyout_reverse_repo_announcements''').fetchone()
    elif table == 'pboc_buyout_reverse_repo_operations':
        row = conn.execute('''SELECT count(*) records,min(operation_date) earliest_period,max(operation_date) latest_period,
            sum(case when source_url is null or source_url='' then 1 else 0 end) missing_source_url
            FROM pboc_buyout_reverse_repo_operations''').fetchone()
    else:
        row = conn.execute('''SELECT count(*) records,min(period) earliest_period,max(period) latest_period,0 missing_source_url
            FROM pboc_buyout_reverse_repo_monthly_stock''').fetchone()
    return dict(row)


def build_pboc_buyout_reverse_repo_payload(db_path):
    with connect(db_path) as conn:
        ensure_pboc_buyout_reverse_repo_tables(conn)
        announcements = [dict(r) for r in conn.execute(
            'SELECT * FROM pboc_buyout_reverse_repo_announcements ORDER BY list_page_no,list_order'
        ).fetchall()]
        ops = [dict(r) for r in conn.execute(
            'SELECT * FROM pboc_buyout_reverse_repo_operations ORDER BY operation_date,amount'
        ).fetchall()]
        stocks = [dict(r) for r in conn.execute(
            'SELECT * FROM pboc_buyout_reverse_repo_monthly_stock ORDER BY period'
        ).fetchall()]
        sources = [dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_debt_sources WHERE source_type=? ORDER BY published_date DESC, source_title DESC',
            (SOURCE_TYPE,)
        ).fetchall()]
        cov = {
            'announcements': _coverage(conn, 'pboc_buyout_reverse_repo_announcements'),
            'operations': _coverage(conn, 'pboc_buyout_reverse_repo_operations'),
            'monthly_stock': _coverage(conn, 'pboc_buyout_reverse_repo_monthly_stock'),
        }
    for row in stocks:
        raw_urls = row.get('source_url')
        try:
            parsed_urls = json.loads(raw_urls) if raw_urls else []
        except (TypeError, json.JSONDecodeError):
            parsed_urls = [raw_urls] if raw_urls else []
        if isinstance(parsed_urls, str):
            parsed_urls = [parsed_urls]
        source_urls = list(dict.fromkeys(
            url for url in parsed_urls if isinstance(url, str) and url.startswith('http')
        ))
        row['source_urls'] = source_urls
        row['source_url'] = source_urls[0] if source_urls else None
    today = datetime.now().date()
    as_of_stock = calculate_outstanding_at(ops, today.isoformat()) if ops else None
    if as_of_stock:
        as_of_urls = list(dict.fromkeys(
            op['source_url'] for op in as_of_stock['active_operations'] if op.get('source_url')
        ))
        as_of_stock['source_urls'] = as_of_urls
        as_of_stock['source_url'] = as_of_urls[0] if as_of_urls else None
    current_period = datetime.now().strftime('%Y-%m')
    completed_stocks = [
        row for row in stocks
        if datetime.strptime(row['month_end_date'], '%Y-%m-%d').date() <= today
    ]
    latest_current = completed_stocks[-1] if completed_stocks else (stocks[-1] if stocks else None)
    current_month_projection = next((row for row in stocks if row.get('period') == current_period), None)
    return {
        'data_status': 'derived' if stocks else 'missing',
        'operation_data_status': 'official' if ops else 'missing',
        'announcement_data_status': 'official' if announcements else 'missing',
        'latest_period': latest_current['period'] if latest_current else None,
        'latest': latest_current,
        'as_of_stock': as_of_stock,
        'current_month_projection': current_month_projection,
        'projection_latest_period': stocks[-1]['period'] if stocks else None,
        'projection_latest': stocks[-1] if stocks else None,
        'announcements': announcements,
        'operations': ops,
        'records': stocks,
        'completed_records': completed_stocks,
        'projection_records': [
            row for row in stocks
            if datetime.strptime(row['month_end_date'], '%Y-%m-%d').date() > today
        ],
        'coverage': cov,
        'source_records': sources,
        'warnings': [] if ops else ['买断式逆回购公告尚未成功接入；未生成 mock 数据。'],
        'notes': [
            '公告全集保存 33 条，包括业务公告和招标公告；只有招标公告进入逐笔操作测算。',
            '逐笔买入/操作金额来自官方招标公告，为 official。',
            '月末存量按 operation_date <= 月末 < maturity_date 的未到期本金合计，为 derived。',
            '公告未明示到期日时，使用操作日期 + 期限推算到期日，并在 maturity_date_status 标记为 derived。',
        ],
    }


def build_pboc_buyout_reverse_repo_debug(conn):
    ensure_pboc_buyout_reverse_repo_tables(conn)
    return {
        'coverage': {
            'announcements': _coverage(conn, 'pboc_buyout_reverse_repo_announcements'),
            'operations': _coverage(conn, 'pboc_buyout_reverse_repo_operations'),
            'monthly_stock': _coverage(conn, 'pboc_buyout_reverse_repo_monthly_stock'),
        },
        'announcement_kind_distribution': [dict(r) for r in conn.execute('''
            SELECT announcement_kind,parse_status,count(*) count
            FROM pboc_buyout_reverse_repo_announcements GROUP BY announcement_kind,parse_status
            ORDER BY announcement_kind,parse_status
        ''').fetchall()],
        'latest_announcements': [dict(r) for r in conn.execute(
            'SELECT * FROM pboc_buyout_reverse_repo_announcements ORDER BY list_page_no,list_order LIMIT 40'
        ).fetchall()],
        'latest_operations': [dict(r) for r in conn.execute(
            'SELECT * FROM pboc_buyout_reverse_repo_operations ORDER BY operation_date DESC,amount DESC LIMIT 40'
        ).fetchall()],
        'latest_monthly_stock': [dict(r) for r in conn.execute(
            'SELECT * FROM pboc_buyout_reverse_repo_monthly_stock ORDER BY period DESC LIMIT 30'
        ).fetchall()],
        'status_distribution': [dict(r) for r in conn.execute('''
            SELECT data_status,maturity_date_status,count(*) count
            FROM pboc_buyout_reverse_repo_operations GROUP BY data_status,maturity_date_status
            ORDER BY data_status,maturity_date_status
        ''').fetchall()],
    }
