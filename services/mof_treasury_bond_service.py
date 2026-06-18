import calendar
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


SOURCE_NAME = '财政部债务管理司'
SOURCE_TYPE = 'mof_treasury_bond'
ENTRY_URL = 'https://zwgls.mof.gov.cn/ywgg/'


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_mof_treasury_bond_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS mof_treasury_bond_issuances (
        id INTEGER PRIMARY KEY,
        bond_code TEXT,
        bond_name TEXT,
        bond_type TEXT,
        issue_kind TEXT,
        is_reissue INTEGER DEFAULT 0,
        is_special INTEGER DEFAULT 0,
        is_savings INTEGER DEFAULT 0,
        issue_date TEXT,
        auction_date TEXT,
        value_date TEXT,
        listing_date TEXT,
        maturity_date TEXT,
        maturity_year INTEGER,
        term_years REAL,
        term_days INTEGER,
        planned_issue_amount REAL,
        actual_issue_amount REAL,
        coupon_rate REAL,
        yield_rate REAL,
        issue_price REAL,
        payment_frequency TEXT,
        source_name TEXT,
        source_type TEXT,
        source_url TEXT UNIQUE,
        source_title TEXT,
        published_date TEXT,
        raw_text TEXT,
        parser_notes TEXT,
        data_status TEXT,
        updated_at TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS mof_treasury_bond_update_logs (
        id INTEGER PRIMARY KEY,
        started_at TEXT,
        finished_at TEXT,
        success INTEGER,
        discovered_links INTEGER,
        parsed_records INTEGER,
        parser_errors TEXT
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


def fetch_html(url, retries=4, timeout=18):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
            if r.status_code >= 500:
                last = RuntimeError(f'HTTP {r.status_code}')
                time.sleep(0.8 * (i + 1))
                continue
            r.raise_for_status()
            return r.content.decode('utf-8', errors='replace'), r.url
        except Exception as exc:
            last = exc
            time.sleep(0.8 * (i + 1))
    raise last


def clean_text(html):
    return BeautifulSoup(html, 'html.parser').get_text('\n', strip=True)


def compact_text(text):
    return re.sub(r'\s+', '', text or '')


def parse_date_cn(s, default_year=None):
    if not s:
        return None
    m = re.search(r'(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日', s)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    if default_year:
        m = re.search(r'(\d{1,2})月\s*(\d{1,2})日', s)
        if m:
            return f'{default_year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}'
    return None


def parse_published(text, fallback=None):
    m = re.search(r'发布日期[:：]?\s*(20\d{2})年(\d{2})月(\d{2})日', text or '')
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    m = re.search(r'(20\d{2}-\d{2}-\d{2})', text or '')
    return m.group(1) if m else fallback


def page_url(n):
    return ENTRY_URL if n == 0 else urljoin(ENTRY_URL, f'index_{n}.htm')


def discover_treasury_links(start_year=2024, max_pages=80):
    out = []
    seen = set()
    stop_old_pages = 0
    page_results = {}

    def fetch_page(n):
        try:
            html, final_url = fetch_html(page_url(n), retries=2, timeout=8)
        except Exception:
            return n, None, None
        return n, html, final_url

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(fetch_page, n) for n in range(max_pages)]
        for fut in as_completed(futures):
            n, html, final_url = fut.result()
            page_results[n] = (html, final_url)
    for n in range(max_pages):
        html, final_url = page_results.get(n, (None, None))
        if html:
            continue
        try:
            html, final_url = fetch_html(page_url(n), retries=1, timeout=10)
            page_results[n] = (html, final_url)
        except Exception:
            page_results[n] = (None, None)

    for n in range(max_pages):
        html, final_url = page_results.get(n, (None, None))
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        page_links = []
        page_years = []
        for a in soup.find_all('a'):
            title = re.sub(r'\s+', ' ', a.get_text(' ', strip=True)).strip()
            href = a.get('href') or ''
            if not href.endswith('.htm'):
                continue
            if '国债' not in title:
                continue
            if '做市支持' in title:
                continue
            if not ('国债业务公告' in title or '发行工作有关事宜' in title):
                continue
            full = urljoin(final_url, href)
            if full in seen:
                continue
            parent_text = ''
            node = a
            for _ in range(4):
                node = node.parent if node else None
                if not node:
                    break
                t = node.get_text(' ', strip=True)
                if re.search(r'20\d{2}-\d{2}-\d{2}', t):
                    parent_text = t
                    break
            date_match = re.search(r'(20\d{2})-\d{2}-\d{2}', parent_text)
            listed_year = int(date_match.group(1)) if date_match else None
            if listed_year:
                page_years.append(listed_year)
            if listed_year and listed_year < start_year:
                continue
            seen.add(full)
            page_links.append({
                'source_url': full,
                'source_title': title,
                'listed_date': date_match.group(0) if date_match else None,
                'list_page_url': final_url,
                'list_page_no': n + 1,
            })
        out.extend(page_links)
        if page_years and max(page_years) < start_year:
            stop_old_pages += 1
        else:
            stop_old_pages = 0
        if stop_old_pages >= 2:
            break
    return out


def _num(pattern, text):
    m = re.search(pattern, text or '')
    return float(m.group(1)) if m else None


def classify_bond_type(title, body):
    s = f'{title} {body}'
    if '储蓄国债' in s:
        return 'savings_bond'
    if '贴现' in s:
        return 'discount_bond'
    if '特别国债' in s:
        return 'special_treasury_bond'
    if '附息' in s:
        return 'book_entry_interest_bearing'
    return 'treasury_bond'


def parse_bond_name(title, compact):
    patterns = [
        r'(20\d{2}年记账式[^（）]*（[^）]+）国债)',
        r'(20\d{2}年超长期特别国债（[^）]+）)',
        r'(20\d{2}年储蓄国债（[^）]+）)',
        r'(20\d{2}年[^，。；:：]*?国债)(?:第[一二三四五六七八九十0-9]+次续发行)?已完成招标工作',
        r'财政部拟发行(20\d{2}年[^。；:：]*?国债)',
        r'关于(20\d{2}年[^。；:：]*?国债)(?:第[一二三四五六七八九十0-9]+次续发行)?工作',
        r'(20\d{2}年[^。；:：]*?国债)',
    ]
    for p in patterns:
        m = re.search(p, compact)
        if m:
            return m.group(1)
    m = re.search(r'(20\d{2}年.*?国债)', title or '')
    return m.group(1) if m else title


def parse_term(title, compact):
    m = re.search(r'为(\d+(?:\.\d+)?)年期', compact)
    if m:
        return float(m.group(1)), None
    m = re.search(r'期限(?:为)?(\d+(?:\.\d+)?)年', compact)
    if m:
        return float(m.group(1)), None
    m = re.search(r'期限(?:为)?(\d+)天', compact)
    if m:
        return None, int(m.group(1))
    m = re.search(r'记账式贴现（[^）]+）国债', title or compact)
    return None, None


def parse_payment_frequency(compact):
    if '按半年付息' in compact:
        return 'semiannual'
    if '每年支付利息' in compact or '按年付息' in compact:
        return 'annual'
    if '到期一次还本付息' in compact:
        return 'at_maturity'
    return None


def parse_detail_page(item):
    html, final_url = fetch_html(item['source_url'])
    soup = BeautifulSoup(html, 'html.parser')
    title = re.sub(r'\s+', ' ', (soup.title.get_text(' ', strip=True) if soup.title else item['source_title'])).strip()
    text = clean_text(html)
    compact = compact_text(text)
    published = parse_published(text, item.get('listed_date'))
    is_result = '国债业务公告' in title and '已完成招标工作' in compact
    is_plan = not is_result and '发行工作有关事宜' in title
    if not (is_result or is_plan):
        raise RuntimeError('不是国债发行/续发行计划或结果公告')

    planned = _num(r'计划(?:续)?发行(?:面值总额)?(\d+(?:\.\d+)?)亿元', compact)
    if planned is None:
        planned = _num(r'竞争性招标面值总额(\d+(?:\.\d+)?)亿元', compact)
    actual = _num(r'实际(?:续)?发行面值金额(\d+(?:\.\d+)?)亿元', compact)

    bond_name = parse_bond_name(title, compact)
    bond_type = classify_bond_type(title, compact)
    is_reissue = 1 if '续发行' in title or '续发行' in compact[:300] else 0
    term_years, term_days = parse_term(title, compact)
    value_date = parse_date_cn(re.search(r'起息日为(20\d{2}年\d{1,2}月\d{1,2}日)', compact).group(1), None) if re.search(r'起息日为(20\d{2}年\d{1,2}月\d{1,2}日)', compact) else None
    if not value_date:
        m = re.search(r'自(20\d{2}年\d{1,2}月\d{1,2}日)开始计息', compact)
        value_date = parse_date_cn(m.group(1)) if m else None
    maturity = None
    m = re.search(r'((?:20\d{2}年\d{1,2}月\d{1,2}日)[^。；]*偿还本金)', compact)
    if m:
        dates = re.findall(r'20\d{2}年\d{1,2}月\d{1,2}日', m.group(1))
        if dates:
            maturity = parse_date_cn(dates[-1])
    if not maturity:
        m = re.search(r'((?:20\d{2}年\d{1,2}月\d{1,2}日)[^。；]*按面值偿还)', compact)
        if m:
            dates = re.findall(r'20\d{2}年\d{1,2}月\d{1,2}日', m.group(1))
            if dates:
                maturity = parse_date_cn(dates[-1])
    auction = None
    m = re.search(r'招标时间。?(20\d{2}年\d{1,2}月\d{1,2}日)', compact)
    if m:
        auction = parse_date_cn(m.group(1))
    listing = None
    default_year = int((published or value_date or '1900')[:4])
    m = re.search(r'(\d{1,2}月\d{1,2}日)起上市交易', compact)
    if m:
        listing = parse_date_cn(m.group(1), default_year)

    issue_price = _num(r'(?:发行价格|续发行价格)为(\d+(?:\.\d+)?)元', compact)
    yield_rate = _num(r'收益率为(\d+(?:\.\d+)?)%', compact)
    coupon = _num(r'票面利率为(\d+(?:\.\d+)?)%', compact)
    bond_code = None
    m = re.search(r'(?:证券代码|债券代码)[:：]?(\d+)', compact)
    if m:
        bond_code = m.group(1)
    data_status = 'official' if actual is not None else 'planned_only'
    if is_reissue:
        issue_date = auction or published or value_date
    else:
        issue_date = value_date or auction or published
    if not term_years and not term_days and value_date and maturity:
        try:
            start = datetime.strptime(value_date, '%Y-%m-%d')
            end = datetime.strptime(maturity, '%Y-%m-%d')
            days = (end - start).days
            if days <= 366:
                term_days = days
            else:
                term_years = round(days / 365.25, 1)
        except Exception:
            pass
    return {
        'bond_code': bond_code,
        'bond_name': bond_name,
        'bond_type': bond_type,
        'issue_kind': 'reissue' if is_reissue else 'initial',
        'is_reissue': is_reissue,
        'is_special': 1 if bond_type == 'special_treasury_bond' else 0,
        'is_savings': 1 if bond_type == 'savings_bond' else 0,
        'issue_date': issue_date,
        'auction_date': auction,
        'value_date': value_date,
        'listing_date': listing,
        'maturity_date': maturity,
        'maturity_year': int(maturity[:4]) if maturity else None,
        'term_years': term_years,
        'term_days': term_days,
        'planned_issue_amount': planned,
        'actual_issue_amount': actual,
        'coupon_rate': coupon,
        'yield_rate': yield_rate,
        'issue_price': issue_price,
        'payment_frequency': parse_payment_frequency(compact),
        'source_name': SOURCE_NAME,
        'source_type': SOURCE_TYPE,
        'source_url': final_url,
        'source_title': title,
        'published_date': published,
        'raw_text': text[-2500:],
        'parser_notes': '解析自财政部债务管理司业务公告；实际发行额优先使用国债业务公告结果公告，计划公告仅标记 planned_only。',
        'data_status': data_status,
    }


def update_mof_treasury_bonds(db_path, start_year=2024, max_pages=80):
    started = datetime.now().isoformat()
    errors = []
    records = []
    skipped = []
    links = discover_treasury_links(start_year=start_year, max_pages=max_pages)
    parsed_items = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(parse_detail_page, item): item for item in links}
        for fut in as_completed(futures):
            item = futures[fut]
            try:
                parsed_items.append((item, fut.result(), None))
            except Exception as exc:
                parsed_items.append((item, None, str(exc)))
    retried_items = []
    for item, rec, error in parsed_items:
        if error and 'HTTP 502' in error:
            try:
                time.sleep(0.3)
                retried_items.append((item, parse_detail_page(item), None))
                continue
            except Exception as exc:
                retried_items.append((item, None, str(exc)))
                continue
        retried_items.append((item, rec, error))
    parsed_items = retried_items
    with connect(db_path) as conn:
        ensure_mof_treasury_bond_tables(conn)
        now = datetime.now().isoformat()
        conn.execute('DELETE FROM mof_treasury_bond_issuances')
        conn.execute('DELETE FROM fiscal_debt_sources WHERE source_type=?', (SOURCE_TYPE,))
        for item, rec, error in parsed_items:
            try:
                if error:
                    raise RuntimeError(error)
                records.append(rec)
                conn.execute('''INSERT INTO mof_treasury_bond_issuances (
                    bond_code,bond_name,bond_type,issue_kind,is_reissue,is_special,is_savings,issue_date,
                    auction_date,value_date,listing_date,maturity_date,maturity_year,term_years,term_days,
                    planned_issue_amount,actual_issue_amount,coupon_rate,yield_rate,issue_price,payment_frequency,
                    source_name,source_type,source_url,source_title,published_date,raw_text,parser_notes,data_status,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_url) DO UPDATE SET
                    bond_code=excluded.bond_code,bond_name=excluded.bond_name,bond_type=excluded.bond_type,
                    issue_kind=excluded.issue_kind,is_reissue=excluded.is_reissue,is_special=excluded.is_special,
                    is_savings=excluded.is_savings,issue_date=excluded.issue_date,auction_date=excluded.auction_date,
                    value_date=excluded.value_date,listing_date=excluded.listing_date,maturity_date=excluded.maturity_date,
                    maturity_year=excluded.maturity_year,term_years=excluded.term_years,term_days=excluded.term_days,
                    planned_issue_amount=excluded.planned_issue_amount,actual_issue_amount=excluded.actual_issue_amount,
                    coupon_rate=excluded.coupon_rate,yield_rate=excluded.yield_rate,issue_price=excluded.issue_price,
                    payment_frequency=excluded.payment_frequency,source_title=excluded.source_title,
                    published_date=excluded.published_date,raw_text=excluded.raw_text,parser_notes=excluded.parser_notes,
                    data_status=excluded.data_status,updated_at=excluded.updated_at
                ''', tuple(rec[k] for k in [
                    'bond_code','bond_name','bond_type','issue_kind','is_reissue','is_special','is_savings','issue_date',
                    'auction_date','value_date','listing_date','maturity_date','maturity_year','term_years','term_days',
                    'planned_issue_amount','actual_issue_amount','coupon_rate','yield_rate','issue_price','payment_frequency',
                    'source_name','source_type','source_url','source_title','published_date','raw_text','parser_notes','data_status'
                ]) + (now,))
                conn.execute('''INSERT INTO fiscal_debt_sources (
                    source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                    parsed_indicators,status,error,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_url) DO UPDATE SET
                    source_title=excluded.source_title,published_date=excluded.published_date,parser_notes=excluded.parser_notes,
                    raw_text=excluded.raw_text,parsed_indicators=excluded.parsed_indicators,status=excluded.status,
                    error=excluded.error,updated_at=excluded.updated_at
                ''', (
                    SOURCE_NAME, SOURCE_TYPE, rec['source_url'], rec['source_title'], rec['published_date'],
                    rec['parser_notes'], rec['raw_text'],
                    json.dumps(['planned_issue_amount','actual_issue_amount','maturity_date','coupon_rate'], ensure_ascii=False),
                    'success', None, now,
                ))
            except Exception as exc:
                if str(exc).startswith('不是国债发行/续发行计划或结果公告'):
                    skipped.append({'source_url': item['source_url'], 'source_title': item['source_title']})
                    conn.execute('''INSERT INTO fiscal_debt_sources (
                        source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                        parsed_indicators,status,error,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_url) DO UPDATE SET status=excluded.status,error=excluded.error,updated_at=excluded.updated_at
                    ''', (SOURCE_NAME, SOURCE_TYPE, item['source_url'], item['source_title'], item.get('listed_date'),
                          '财政部国债公告已发现，但不是发行/续发行计划或招标结果公告，未写入发行明细表。', '',
                          '[]', 'skipped', str(exc), now))
                    continue
                errors.append({'source_url': item['source_url'], 'source_title': item['source_title'], 'error': str(exc)})
                conn.execute('''INSERT INTO fiscal_debt_sources (
                    source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                    parsed_indicators,status,error,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_url) DO UPDATE SET status=excluded.status,error=excluded.error,updated_at=excluded.updated_at
                ''', (SOURCE_NAME, SOURCE_TYPE, item['source_url'], item['source_title'], item.get('listed_date'),
                      '解析财政部国债发行公告失败。', '', '[]', 'error', str(exc), now))
        conn.execute('''INSERT INTO mof_treasury_bond_update_logs (
            started_at,finished_at,success,discovered_links,parsed_records,parser_errors
        ) VALUES (?,?,?,?,?,?)''', (started, datetime.now().isoformat(), 1 if not errors else 0, len(links), len(records), json.dumps(errors, ensure_ascii=False)))
        conn.commit()
    return {
        'success': not errors,
        'discovered_links': len(links),
        'parsed_records': len(records),
        'actual_records': sum(1 for r in records if r['actual_issue_amount'] is not None),
        'planned_only_records': sum(1 for r in records if r['actual_issue_amount'] is None),
        'skipped_records': len(skipped),
        'parser_errors': errors[:20],
    }


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def build_mof_treasury_bond_payload(db_path):
    with connect(db_path) as conn:
        ensure_mof_treasury_bond_tables(conn)
        records = _rows(conn, 'SELECT * FROM mof_treasury_bond_issuances ORDER BY issue_date DESC, published_date DESC')
        yearly = _rows(conn, '''
            SELECT substr(issue_date,1,4) year, sum(actual_issue_amount) actual_issue_amount, count(*) records
            FROM mof_treasury_bond_issuances
            WHERE actual_issue_amount IS NOT NULL AND issue_date IS NOT NULL
            GROUP BY substr(issue_date,1,4) ORDER BY year
        ''')
        monthly = _rows(conn, '''
            SELECT substr(issue_date,1,7) period, sum(actual_issue_amount) actual_issue_amount, count(*) records
            FROM mof_treasury_bond_issuances
            WHERE actual_issue_amount IS NOT NULL AND issue_date IS NOT NULL
            GROUP BY substr(issue_date,1,7) ORDER BY period
        ''')
        by_type = _rows(conn, '''
            SELECT substr(issue_date,1,4) year,bond_type,issue_kind,sum(actual_issue_amount) actual_issue_amount,count(*) records
            FROM mof_treasury_bond_issuances
            WHERE actual_issue_amount IS NOT NULL AND issue_date IS NOT NULL
            GROUP BY substr(issue_date,1,4),bond_type,issue_kind ORDER BY year,bond_type,issue_kind
        ''')
        by_term = _rows(conn, '''
            SELECT coalesce(cast(term_days as text) || '天', cast(term_years as text) || '年') term,
                   sum(actual_issue_amount) actual_issue_amount,count(*) records
            FROM mof_treasury_bond_issuances
            WHERE actual_issue_amount IS NOT NULL
            GROUP BY term ORDER BY term
        ''')
        by_maturity = _rows(conn, '''
            SELECT maturity_year, sum(actual_issue_amount) actual_issue_amount, count(*) records
            FROM mof_treasury_bond_issuances
            WHERE actual_issue_amount IS NOT NULL AND maturity_year IS NOT NULL
            GROUP BY maturity_year ORDER BY maturity_year
        ''')
        coverage = dict(conn.execute('''
            SELECT count(*) records,min(issue_date) earliest_period,max(issue_date) latest_period,
                   sum(case when source_url is null or source_url='' then 1 else 0 end) missing_source_url,
                   sum(case when data_status='official' then 1 else 0 end) official_records,
                   sum(case when data_status='planned_only' then 1 else 0 end) planned_only_records
            FROM mof_treasury_bond_issuances
        ''').fetchone())
        sources = _rows(conn, 'SELECT * FROM fiscal_debt_sources WHERE source_type=? ORDER BY updated_at DESC LIMIT 40', (SOURCE_TYPE,))
    current_year = datetime.now().year
    ytd = next((r for r in yearly if str(r['year']) == str(current_year)), None)
    return {
        'data_status': 'official' if coverage.get('official_records') else 'missing',
        'source_name': SOURCE_NAME,
        'source_type': SOURCE_TYPE,
        'entry_url': ENTRY_URL,
        'coverage': coverage,
        'records': records,
        'yearly': yearly,
        'monthly': monthly,
        'by_type': by_type,
        'by_term': by_term,
        'by_maturity_year': by_maturity,
        'current_year_ytd': ytd,
        'source_records': sources,
        'warnings': [] if records else ['财政部国债发行明细尚未接入；未生成 mock 数据。'],
        'notes': [
            '主口径使用 actual_issue_amount；只有计划发行额且没有结果公告时 data_status=planned_only，不计入实际发行汇总。',
            '逐条来源为财政部债务管理司业务公告具体原文页。',
        ],
    }


def build_mof_treasury_bond_debug(conn):
    ensure_mof_treasury_bond_tables(conn)
    return {
        'coverage': dict(conn.execute('''
            SELECT count(*) records,min(issue_date) earliest_period,max(issue_date) latest_period,
                   sum(case when source_url is null or source_url='' then 1 else 0 end) missing_source_url,
                   sum(case when data_status='official' then 1 else 0 end) official_records,
                   sum(case when data_status='planned_only' then 1 else 0 end) planned_only_records
            FROM mof_treasury_bond_issuances
        ''').fetchone()),
        'status_distribution': _rows(conn, '''
            SELECT data_status,bond_type,issue_kind,count(*) count,sum(actual_issue_amount) actual_issue_amount
            FROM mof_treasury_bond_issuances GROUP BY data_status,bond_type,issue_kind
            ORDER BY data_status,bond_type,issue_kind
        '''),
        'latest_records': _rows(conn, 'SELECT * FROM mof_treasury_bond_issuances ORDER BY issue_date DESC,published_date DESC LIMIT 50'),
    }
