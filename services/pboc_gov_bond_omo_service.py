import json
import re
import sqlite3
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


PBOC_SOURCE_NAME = '中国人民银行'
PBOC_OMO_SOURCE_TYPE = 'pboc_gov_bond_omo'
PBOC_OMO_ENTRY = 'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/index.html'
PBOC_OMO_COLUMN = 'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/index.html'

KNOWN_OMO_URLS = [
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5730072/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5697721/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5646965/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5604395/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5578971/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5550612/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5522522/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5493317/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5472598/index.html',
    'https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125431/5442785/5445617/index.html',
]


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_pboc_gov_bond_omo_tables(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS pboc_gov_bond_omo_observations (
        id INTEGER PRIMARY KEY,
        period TEXT UNIQUE,
        operation_status TEXT,
        net_purchase_amount REAL,
        cumulative_net_purchase_amount REAL,
        unit TEXT,
        buy_description TEXT,
        sell_description TEXT,
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


def fetch_html(url):
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    return r.content.decode('utf-8', errors='replace'), r.url


def clean_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text('\n', strip=True)


def discover_omo_links():
    links = []
    try:
        html, final_url = fetch_html(PBOC_OMO_COLUMN)
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a'):
            text = a.get_text(' ', strip=True)
            href = a.get('href') or ''
            if '/5442785/' in href and href.endswith('/index.html') and '[' in text:
                links.append({'title': text, 'url': urljoin(final_url, href)})
    except Exception:
        pass
    try:
        html, final_url = fetch_html(PBOC_OMO_ENTRY)
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a'):
            text = a.get_text(' ', strip=True)
            href = a.get('href') or ''
            full = urljoin(final_url, href)
            if '/5442785/' in href and href.endswith('/index.html') and '[' in text and full not in {x['url'] for x in links}:
                links.append({'title': text, 'url': full})
    except Exception:
        pass
    seen = {x['url'] for x in links}
    for url in KNOWN_OMO_URLS:
        if url not in seen:
            links.append({'title': '国债买卖业务公告', 'url': url})
    return links


def parse_period(text):
    m = re.search(r'(20\d{2})年\s*(\d{1,2})月', text)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}'
    return None


def parse_published_date(text):
    m = re.search(r'(20\d{2}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}', text)
    return m.group(1) if m else None


def parse_omo_page(url):
    html, final_url = fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.find('title').get_text(' ', strip=True) if soup.find('title') else '国债买卖业务公告'
    text = clean_text(html)
    compact = re.sub(r'\s+', '', text)
    if '国债买卖业务公告' not in text:
        raise RuntimeError('页面标题不属于国债买卖业务公告')
    period = parse_period(text)
    if not period:
        raise RuntimeError('未解析出公告月份')
    published = parse_published_date(text)

    not_conducted = bool(re.search(r'未开展公开市场国债买卖(?:操作|业务)?', compact))
    amount = None
    status = 'conducted'
    if not_conducted:
        status = 'not_conducted'
        amount = 0.0
    else:
        m = re.search(r'净买入(?:债券)?(?:面值)?(?:为|人民币)?(\d+(?:\.\d+)?)亿元', compact)
        if m:
            amount = float(m.group(1))
        else:
            m = re.search(r'净卖出(?:债券)?(?:面值)?(?:为|人民币)?(\d+(?:\.\d+)?)亿元', compact)
            if m:
                amount = -float(m.group(1))
        if amount is None:
            raise RuntimeError('公告已识别为开展操作，但未解析出净买入/净卖出金额')

    buy_description = None
    sell_description = None
    m = re.search(r'买入([^，。；;]*?国债)', text)
    if m:
        buy_description = '买入' + m.group(1)
    m = re.search(r'卖出([^，。；;]*?国债)', text)
    if m:
        sell_description = '卖出' + m.group(1)

    body_match = re.search(r'(为贯彻.*?中国人民银行公开市场业务操作室|为维护.*?中国人民银行公开市场业务操作室|202\d年.*?中国人民银行公开市场业务操作室)', text, re.S)
    raw_text = body_match.group(1).strip() if body_match else text[-1000:]
    return {
        'period': period,
        'operation_status': status,
        'net_purchase_amount': amount,
        'unit': '亿元',
        'buy_description': buy_description,
        'sell_description': sell_description,
        'source_name': PBOC_SOURCE_NAME,
        'source_type': PBOC_OMO_SOURCE_TYPE,
        'source_url': final_url,
        'source_title': title,
        'published_date': published,
        'raw_text': raw_text,
        'parser_notes': '仅解析中国人民银行“公开市场国债买卖业务公告”栏目；不解析逆回购、买断式逆回购、MLF 或普通公开市场业务交易公告。',
        'data_status': 'official',
    }


def update_pboc_gov_bond_omo(db_path):
    links = discover_omo_links()
    parser_errors = []
    parsed = []
    with connect(db_path) as conn:
        ensure_pboc_gov_bond_omo_tables(conn)
        now = datetime.now().isoformat()
        for item in links:
            try:
                rec = parse_omo_page(item['url'])
                parsed.append(rec)
            except Exception as exc:
                parser_errors.append({'source_url': item['url'], 'error': str(exc)})
                conn.execute('''INSERT INTO fiscal_debt_sources (
                    source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                    parsed_indicators,status,error,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_url) DO UPDATE SET
                    status=excluded.status, error=excluded.error, updated_at=excluded.updated_at
                ''', (
                    PBOC_SOURCE_NAME, PBOC_OMO_SOURCE_TYPE, item['url'], item.get('title'),
                    None, '解析公开市场国债买卖业务公告失败。', '', '[]', 'error', str(exc), now
                ))

        if not parsed:
            conn.rollback()
            return {
                'success': False,
                'records': 0,
                'latest_period': None,
                'parser_errors': parser_errors,
                'error': '本次未解析出任何公开市场国债买卖公告；已保留旧数据。',
            }

        parsed_periods = {rec['period'] for rec in parsed}
        for row in conn.execute('SELECT * FROM pboc_gov_bond_omo_observations ORDER BY period').fetchall():
            if row['period'] not in parsed_periods:
                parsed.append(dict(row))

        cumulative = 0.0
        for rec in sorted(parsed, key=lambda r: r['period']):
            cumulative += rec['net_purchase_amount'] or 0.0
            rec['cumulative_net_purchase_amount'] = cumulative
            conn.execute('''INSERT INTO pboc_gov_bond_omo_observations (
                period,operation_status,net_purchase_amount,cumulative_net_purchase_amount,unit,
                buy_description,sell_description,source_name,source_type,source_url,source_title,
                published_date,raw_text,parser_notes,data_status,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(period) DO UPDATE SET
                operation_status=excluded.operation_status,
                net_purchase_amount=excluded.net_purchase_amount,
                cumulative_net_purchase_amount=excluded.cumulative_net_purchase_amount,
                unit=excluded.unit,
                buy_description=excluded.buy_description,
                sell_description=excluded.sell_description,
                source_url=excluded.source_url,
                source_title=excluded.source_title,
                published_date=excluded.published_date,
                raw_text=excluded.raw_text,
                parser_notes=excluded.parser_notes,
                data_status=excluded.data_status,
                updated_at=excluded.updated_at
            ''', (
                rec['period'], rec['operation_status'], rec['net_purchase_amount'], rec['cumulative_net_purchase_amount'],
                rec['unit'], rec['buy_description'], rec['sell_description'], rec['source_name'], rec['source_type'],
                rec['source_url'], rec['source_title'], rec['published_date'], rec['raw_text'], rec['parser_notes'],
                rec['data_status'], now
            ))
            conn.execute('''INSERT INTO fiscal_debt_sources (
                source_name,source_type,source_url,source_title,published_date,parser_notes,raw_text,
                parsed_indicators,status,error,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_url) DO UPDATE SET
                source_title=excluded.source_title, published_date=excluded.published_date,
                parser_notes=excluded.parser_notes, raw_text=excluded.raw_text,
                parsed_indicators=excluded.parsed_indicators, status=excluded.status,
                error=excluded.error, updated_at=excluded.updated_at
            ''', (
                PBOC_SOURCE_NAME, PBOC_OMO_SOURCE_TYPE, rec['source_url'], rec['source_title'],
                rec['published_date'], rec['parser_notes'], rec['raw_text'],
                json.dumps(['operation_status', 'net_purchase_amount', 'cumulative_net_purchase_amount'], ensure_ascii=False),
                'success', None, now
            ))
        conn.commit()
    return {
        'success': True,
        'records': len(parsed),
        'latest_period': max([r['period'] for r in parsed], default=None),
        'parser_errors': parser_errors,
    }


def _coverage(conn):
    row = conn.execute('''SELECT count(*) records, min(period) earliest_period, max(period) latest_period,
        count(distinct period) months,
        sum(case when source_url is null or source_url='' then 1 else 0 end) missing_source_url
        FROM pboc_gov_bond_omo_observations''').fetchone()
    return dict(row)


def build_pboc_gov_bond_omo_payload(db_path):
    with connect(db_path) as conn:
        ensure_pboc_gov_bond_omo_tables(conn)
        rows = [dict(r) for r in conn.execute('SELECT * FROM pboc_gov_bond_omo_observations ORDER BY period').fetchall()]
        coverage = _coverage(conn)
        sources = [dict(r) for r in conn.execute(
            'SELECT * FROM fiscal_debt_sources WHERE source_type=? ORDER BY updated_at DESC LIMIT 20',
            (PBOC_OMO_SOURCE_TYPE,)
        ).fetchall()]
    return {
        'data_status': 'official' if rows else 'missing',
        'latest_period': rows[-1]['period'] if rows else None,
        'latest': rows[-1] if rows else None,
        'records': rows,
        'coverage': coverage,
        'source_records': sources,
        'warnings': [] if rows else ['公开市场国债买卖业务公告尚未成功接入；未生成 mock 数据。'],
        'notes': ['累计净买入只基于已抓取并解析成功的 official 公告月份，不外推未来月份。'],
    }


def build_pboc_gov_bond_omo_debug(conn):
    ensure_pboc_gov_bond_omo_tables(conn)
    latest = [dict(r) for r in conn.execute(
        'SELECT * FROM pboc_gov_bond_omo_observations ORDER BY period DESC LIMIT 20'
    ).fetchall()]
    status_dist = [dict(r) for r in conn.execute('''
        SELECT operation_status, data_status, count(*) count
        FROM pboc_gov_bond_omo_observations GROUP BY operation_status, data_status
        ORDER BY operation_status, data_status
    ''').fetchall()]
    return {
        'coverage': _coverage(conn),
        'latest_observations': latest,
        'status_distribution': status_dist,
        'missing_source_url': conn.execute(
            "SELECT count(*) FROM pboc_gov_bond_omo_observations WHERE source_url IS NULL OR source_url=''"
        ).fetchone()[0],
    }
