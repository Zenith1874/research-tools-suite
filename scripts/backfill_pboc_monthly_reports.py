# -*- coding: utf-8 -*-
"""回填缺失的央行《金融统计数据报告》月度页面,补齐 dashboard 数据洞。

背景:2016-2021 年 monthly_data 的月度行多来自信贷收支表 Excel(只有 M2/贷款等),
未抓当月报告页,导致 ibor/repo(银行间利率)等整段缺失;部分月份整行缺失。

做法:对 2015-01 起每个 ibor 为 NULL 的月份,用央行站内搜索(wzdig)按
"X年X月金融统计数据报告"精确发现,parse_report 解析,只填 NULL 列、
绝不覆盖已有值;行不存在则新建。失败如实跳过。

用法: python scripts/backfill_pboc_monthly_reports.py [--start 2015-01] [--dry-run]
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
sys.path.insert(0, str(ROOT))

from server import parse_report, DB_PATH  # noqa: E402  (server 有 __main__ 守卫,导入安全)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
SEARCH = ('https://wzdig.pbc.gov.cn/search/pcRender'
          '?pageId=c177a85bd02b4114bebebd210809f691&sr=score%20desc&q=')
# 可回填列:parse_report 产出的键(全部只在 NULL 时写入)
FILLABLE = ('M2', 'M2y', 'M1', 'M1y', 'M0y', 'loan', 'loany', 'dep', 'depy',
            'SF', 'SFy', 'ibor', 'repo')


def search_report(year, month):
    q = f'{year}年{month}月金融统计数据报告'
    try:
        req = urllib.request.Request(SEARCH + urllib.parse.quote(q), headers=HEADERS)
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', 'ignore')
    except Exception as exc:  # noqa: BLE001
        print(f'  {year}-{month:02d} 搜索失败: {exc}')
        return None
    best = None
    for m in re.finditer(r'href="(https://www\.pbc\.gov\.cn/[^"]+/index\.html)"[^>]*>(.*?)</a>',
                         html, re.S):
        title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if title == q or title.replace('份', '') == q:
            url = m.group(1)
            if best is None or '/goutongjiaoliu/' in url:
                best = url
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2015-01')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA busy_timeout=30000')
    now = datetime.now()
    months = []
    y, m = int(args.start[:4]), int(args.start[5:7])
    while (y, m) <= (now.year, now.month):
        months.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    todo = []
    for y, m in months:
        key = f'{y}-{m:02d}'
        row = conn.execute('SELECT ibor, repo FROM monthly_data WHERE month=?', (key,)).fetchone()
        if row is None or row[0] is None:
            todo.append((y, m, key, row is not None))
    print(f'待补月份: {len(todo)}')

    filled = failed = 0
    for y, m, key, exists in todo:
        url = search_report(y, m)
        if not url:
            print(f'  {key}: 未发现报告页')
            failed += 1
            time.sleep(0.4)
            continue
        month, data, raw = parse_report(url)
        data = {k: v for k, v in data.items() if k in FILLABLE and v is not None}
        if month != key or not data:
            print(f'  {key}: 解析失败/月份不符({month}, {len(data)}键)')
            failed += 1
            time.sleep(0.4)
            continue
        print(f'  {key}: {sorted(data)} ← {url[:70]}')
        if not args.dry_run:
            ts = datetime.now().isoformat()
            if not exists:
                conn.execute('INSERT INTO monthly_data (month, scraped_at, source_url) VALUES (?,?,?)',
                             (key, ts, url))
            sets = ', '.join(f'{k}=COALESCE({k},?)' for k in data)
            conn.execute(f'UPDATE monthly_data SET {sets}, '
                         'raw_html=COALESCE(raw_html,?), source_url=COALESCE(source_url,?) '
                         'WHERE month=?', (*data.values(), raw, url, key))
            conn.commit()
        filled += 1
        time.sleep(0.5)
    conn.close()
    print(f'完成: 补{filled} 失败{failed}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
