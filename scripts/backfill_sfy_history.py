# -*- coding: utf-8 -*-
"""回填社融存量(SF)与存量同比(SFy)历史。

来源:央行《社会融资规模存量统计数据报告》(月度,2016-01 起;此前仅年度)。
发现:央行站内搜索 wzdig.pbc.gov.cn(与金融统计报告回填同机制)。
解析:正文"社会融资规模存量为X万亿元,同比增长Y%"(增长/下降定号)。

数据纪律:
- 只填 monthly_data 中该月 SF/SFy 为 NULL 的格子,绝不覆盖现有值;
- 每个回填值的 source_url/标题记入独立溯源表 sf_stock_sources(可审计);
- 解析失败/字段缺失如实跳过,不估算。

用法: python scripts/backfill_sfy_history.py [--start-year 2016] [--dry-run]
"""
import argparse
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / 'pboc_data.db'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
SEARCH_URL = ('https://wzdig.pbc.gov.cn/search/pcRender'
              '?pageId=c177a85bd02b4114bebebd210809f691&sr=score%20desc&q=')
PHRASE = '社会融资规模存量统计数据报告'


def fetch(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        for enc in ('utf-8', 'gb18030'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', 'ignore')
    except Exception as exc:  # noqa: BLE001 - 网络失败只跳过该页
        print(f'  fetch失败 {url[:80]}: {exc}')
        return None


def clean(text):
    return re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', text or ''))


def month_from_title(title):
    """'2025年6月社会融资规模存量统计数据报告'→2025-06;年度→12月;
    一季度→03;上半年→06;前三季度→09。"""
    m = re.search(r'(20\d{2})年(\d{1,2})月', title)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}'
    m = re.search(r'(20\d{2})年(一季度|上半年|前三季度)?', title)
    if not m:
        return None
    suffix = {'一季度': '03', '上半年': '06', '前三季度': '09', None: '12'}
    return f"{m.group(1)}-{suffix[m.group(2)]}"


def discover(start_year, end_year):
    found = {}
    for year in range(start_year, end_year + 1):
        url = SEARCH_URL + urllib.parse.quote(f'{year}年{PHRASE}')
        html = fetch(url)
        if not html:
            continue
        for m in re.finditer(
                r'href="(https://www\.pbc\.gov\.cn/[^"]+/index\.html)"[^>]*>(.*?)</a>',
                html, re.I | re.S):
            title = clean(m.group(2))
            if PHRASE not in title or '增量' in title:
                continue
            month = month_from_title(title)
            if month and month not in found:
                found[month] = (m.group(1), title)
        time.sleep(0.15)
    return found


SF_RE = re.compile(r'社会融资规模存量为([\d.]+)万亿元')
SFY_RE = re.compile(r'社会融资规模存量为[\d.]+万亿元[^。]{0,30}?同比(增长|下降)([\d.]+)%')


def parse_article(html):
    text = clean(html)
    sf = sfy = None
    m = SF_RE.search(text)
    if m:
        sf = float(m.group(1))
    m = SFY_RE.search(text)
    if m:
        sfy = float(m.group(2)) * (1 if m.group(1) == '增长' else -1)
    return sf, sfy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-year', type=int, default=2016)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS sf_stock_sources (
        month TEXT PRIMARY KEY, sf REAL, sfy REAL,
        source_url TEXT, source_title TEXT, updated_at TEXT)''')

    links = discover(args.start_year, datetime.now().year)
    print(f'发现 {len(links)} 篇社融存量报告')
    filled = skipped = failed = 0
    for month in sorted(links):
        url, title = links[month]
        row = conn.execute('SELECT SF, SFy FROM monthly_data WHERE month=?', (month,)).fetchone()
        if row and row[0] is not None and row[1] is not None:
            skipped += 1
            continue
        html = fetch(url)
        if not html:
            failed += 1
            continue
        sf, sfy = parse_article(html)
        if sf is None and sfy is None:
            print(f'  {month} 解析失败({title[:30]})')
            failed += 1
            continue
        print(f'  {month}: SF={sf} SFy={sfy}  ← {title[:34]}')
        if not args.dry_run:
            now = datetime.now().isoformat()
            if row is None:
                conn.execute('INSERT INTO monthly_data (month, SF, SFy, scraped_at, source_url) '
                             'VALUES (?,?,?,?,?)', (month, sf, sfy, now, url))
            else:
                # 只填空格,不覆盖现有值
                conn.execute('UPDATE monthly_data SET SF=COALESCE(SF,?), SFy=COALESCE(SFy,?) '
                             'WHERE month=?', (sf, sfy, month))
            conn.execute('INSERT OR REPLACE INTO sf_stock_sources VALUES (?,?,?,?,?,?)',
                         (month, sf, sfy, url, title, now))
            conn.commit()
        filled += 1
        time.sleep(0.35)
    conn.close()
    print(f'完成: 回填{filled} 跳过(已有){skipped} 失败{failed}')
    return 0 if filled or skipped else 1


if __name__ == '__main__':
    sys.exit(main())
