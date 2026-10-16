#!/usr/bin/env python3
"""Bounded official-source repair/backfill with immutable raw-response receipts."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from bs4 import BeautifulSoup
from services.china_macro_service import (
    INDICATORS, PARSERS, connect, ensure_china_macro_tables, discover_releases,
    ANNUAL_SUPPLEMENT_PATH, SOURCE_NAME, SOURCE_TYPE,
    econ_period_from_article,
)
from services.china_macro_extended_service import annual_period
from services.macro_data_quality_service import build_macro_data_quality
from services.us_macro_service import SERIES, update_us_macro

PBOC_LATEST = 'https://www.pbc.gov.cn/diaochatongjisi/attachDir/2026/09/2026091418164535833.xlsx'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--start-year', type=int, default=2018)
    parser.add_argument('--annual-start-year', type=int, default=2010)
    parser.add_argument('--max-requests', type=int, default=400)
    parser.add_argument('--sleep', type=float, default=0.35)
    parser.add_argument('--replay-audit', type=Path)
    parser.add_argument('--verify-us-extensions', action='store_true')
    parser.add_argument('--extend-econ', action='store_true')
    parser.add_argument('--only-kinds')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_completeness')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Database must already exist.')
    run = args.output_dir / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    raw_dir = run / 'raw'
    raw_dir.mkdir(parents=True, exist_ok=False)
    before = {country: build_macro_data_quality(str(args.db), country) for country in ('china', 'us')}
    (run / 'coverage-before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
    manifest, errors, parsed_counts, annual_rows = [], [], {}, []
    request_count = 0
    session = requests.Session()
    cached = {}
    if args.replay_audit:
        previous = json.loads(args.replay_audit.read_text(encoding='utf-8'))
        cached = {row['source_url']: row for row in previous['source_manifest']}

    def get(url):
        nonlocal request_count
        if url in cached:
            prior = cached[url]
            content = (args.replay_audit.parent / prior['raw_path']).read_bytes()
            if hashlib.sha256(content).hexdigest() != prior['raw_sha256']:
                raise ValueError('Cached official response hash changed; replay refused.')
            response = requests.Response()
            response.status_code = 200; response._content = content
            response.url = prior['resolved_url']; response.encoding = 'utf-8'
            suffix = '.xlsx' if '.xlsx' in url.lower() else '.html'
            target = raw_dir / f'{len(manifest)+1:04d}-{prior["raw_sha256"][:12]}{suffix}'
            target.write_bytes(content)
            record = {**prior, 'raw_path': str(target.relative_to(run)),
                      'replayed_at': datetime.now().astimezone().isoformat()}
            manifest.append(record)
            return response, record
        if request_count >= args.max_requests:
            raise RuntimeError('Configured official request budget exhausted; remaining fields stay missing.')
        request_count += 1
        time.sleep(max(0, args.sleep))
        response = session.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        suffix = '.xlsx' if '.xlsx' in url.lower() else '.html'
        target = raw_dir / f'{request_count:04d}-{digest[:12]}{suffix}'
        target.write_bytes(response.content)
        record = {'source_url': url, 'resolved_url': response.url,
                  'retrieved_at': datetime.now().astimezone().isoformat(),
                  'raw_sha256': digest, 'raw_path': str(target.relative_to(run)), 'bytes': len(response.content)}
        manifest.append(record)
        response.encoding = 'utf-8'
        return response, record

    conn = connect(str(args.db))
    ensure_china_macro_tables(conn)
    damaged = [dict(row) for row in conn.execute(
        "SELECT * FROM china_macro_observations WHERE indicator_code='CN_FAI_PRIVATE_YTD_YOY' AND abs(value)>1000")]
    (run / 'fai-before-repair.json').write_text(json.dumps(damaged, ensure_ascii=False, indent=2), encoding='utf-8')
    # Preserve the source value even when a page is unavailable. A known amount-as-rate
    # parser error must not remain an official percentage in a live chart/model.
    for row in damaged:
        conn.execute("UPDATE china_macro_observations SET original_value=COALESCE(original_value,value), "
                     "value=NULL,data_status='invalidated_source_value',missing_reason=? WHERE id=?",
                     ('Historical parser selected investment amount instead of the growth column; awaiting official reparse.', row['id']))
    conn.commit()

    def upsert(kind, period, url, title, response, receipt):
        nonlocal annual_rows
        if kind == 'econ':
            actual = econ_period_from_article(response.text, title, url)
            if not actual:
                raise ValueError('Reporting year/month not verifiable from the article; no upsert.')
            if actual != period:
                original = [dict(row) for row in conn.execute(
                    'SELECT * FROM china_macro_observations WHERE period=? AND source_url=?', (period, url))]
                correction_path = run / 'period-corrections.jsonl'
                with correction_path.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps({'old_period':period,'actual_period':actual,
                                             'source_url':url,'original_rows':original},ensure_ascii=False)+'\n')
                conn.execute("UPDATE china_macro_observations SET original_value=COALESCE(original_value,value), "
                             "value=NULL,data_status='invalidated_source_period',missing_reason=? "
                             "WHERE period=? AND source_url=?",
                             (f'Migrated archive path was mistaken for reporting period; actual={actual}',period,url))
                period = actual
        values = PARSERS[kind](response.text,period=period) if kind == 'econ' else PARSERS[kind](response.text)
        receipt.update(kind=kind, validated_period=period, title=title)
        soup = BeautifulSoup(response.text, 'html.parser')
        release_date = None
        for meta in soup.find_all('meta'):
            if (meta.get('name') or '').lower() in ('pubdate', 'publishdate', 'date'):
                found = re.search(r'20\d{2}[-/]\d{2}[-/]\d{2}', meta.get('content') or '')
                if found:
                    release_date = found[0].replace('/', '-')
                    break
        for code, value in values.items():
            if code not in INDICATORS:
                continue
            name, unit, frequency = INDICATORS[code]
            status = 'official_preliminary' if kind == 'annual' else 'official'
            note = ('官方累计同比按可比口径公布；累计金额与月末存量分别保存。' if kind == 'profit' else
                    '官方年度公报初步值；不替代其他序列的年鉴修订值。' if kind == 'annual' else
                    '官方新闻稿及表格解析；历史缺失不插值。')
            conn.execute('''INSERT INTO china_macro_observations (
                indicator_code,indicator_name,period,value,unit,frequency,data_status,
                source_name,source_type,source_url,source_title,parser_notes,updated_at,
                release_date,retrieved_at,raw_sha256,parser_version,missing_reason)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(indicator_code,period) DO UPDATE SET
                value=excluded.value,indicator_name=excluded.indicator_name,unit=excluded.unit,
                frequency=excluded.frequency,data_status=excluded.data_status,
                source_name=excluded.source_name,source_type=excluded.source_type,
                source_url=excluded.source_url,source_title=excluded.source_title,
                parser_notes=excluded.parser_notes,updated_at=excluded.updated_at,
                release_date=excluded.release_date,retrieved_at=excluded.retrieved_at,
                raw_sha256=excluded.raw_sha256,parser_version=excluded.parser_version,missing_reason=NULL''',
                (code, name, period, value, unit, frequency, status, SOURCE_NAME, SOURCE_TYPE,
                 url, title, note, datetime.now().isoformat(), release_date, receipt['retrieved_at'],
                 receipt['raw_sha256'], 'macro-completeness-20261002', None))
            if kind == 'annual':
                annual_rows.append({'indicator_code': code, 'period': period, 'value': value, 'unit': unit,
                                    'data_status': status, 'source_name': SOURCE_NAME, 'source_url': url,
                                    'source_title': title, 'parser_notes': note})
        conn.commit()
        parsed_counts[kind] = parsed_counts.get(kind, 0) + len(values)

    tasks = {}
    for kind, anchor in (('cpi', 'CN_CPI_YOY'), ('pmi', 'CN_PMI_MFG'), ('econ', 'CN_UNEMP_SURVEY')):
        for row in conn.execute('SELECT period,source_url,source_title FROM china_macro_observations '
                                'WHERE indicator_code=? AND period>=? ORDER BY period', (anchor, str(args.start_year))):
            tasks[(kind, row['period'])] = (row['source_url'], row['source_title'] or '')
    for row in damaged:
        tasks[('fai', row['period'])] = (row['source_url'], row['source_title'] or '')
    if args.replay_audit:
        # Reuse the governing URLs already linked to successful observations.
        for url in cached:
            row = conn.execute('SELECT period,source_title,indicator_code,frequency '
                               'FROM china_macro_observations WHERE source_url=? LIMIT 1',(url,)).fetchone()
            if not row:
                continue
            title=row['source_title'] or ''
            kind=('annual' if '统计公报' in title else 'econ' if '国民经济' in title else
                  'profit' if '工业企业利润' in title else 'capacity' if '产能利用率' in title else
                  'cpi' if '居民消费价格' in title else 'pmi' if '采购经理' in title else
                  'fai' if '固定资产投资' in title else None)
            if kind:
                tasks[(kind,row['period'])]=(url,title)
    discover_kinds = (() if args.replay_audit else ('profit', 'capacity')) + (('econ',) if args.extend_econ else ())
    for kind in discover_kinds:
        print(f'Discovering official {kind} releases from {args.start_year}...', flush=True)
        try:
            releases = discover_releases(kind, args.start_year, max_pages=2, workers=1)
            for period, (url, title) in releases.items():
                tasks[(kind, period)] = (url, title)
            print(f'{kind}: {len(releases)} validated release periods.', flush=True)
        except Exception as exc:
            errors.append({'kind': kind, 'phase': 'discovery', 'error': str(exc)})
    # A public, governed release directory; no EasyQuery refusal bypass.
    for page in range(6):
        url = 'https://www.stats.gov.cn/xxgk/sjfb/tjgb2020/' + (f'index_{page}.html' if page else '')
        try:
            response, _ = get(url)
            for link in BeautifulSoup(response.text, 'html.parser').find_all('a', href=True):
                title = link.get_text(' ', strip=True)
                period = annual_period(title)
                if period and int(period) >= args.annual_start_year:
                    target = urljoin(url, link['href'])
                    if target.lower().endswith('.html'):
                        tasks[('annual', period)] = (target, title)
        except Exception as exc:
            errors.append({'source_url': url, 'phase': 'annual_discovery', 'error': str(exc)})
    if args.only_kinds:
        allowed = set(args.only_kinds.split(','))
        if allowed - set(PARSERS):
            raise ValueError('Unknown source kinds requested.')
        tasks = {key:value for key,value in tasks.items() if key[0] in allowed}
    print(f'Fetching {len(tasks)} source releases; raw responses archived under {run}.', flush=True)
    for index, ((kind, period), (url, title)) in enumerate(sorted(tasks.items()), start=1):
        try:
            response, receipt = get(url)
            upsert(kind, period, url, title, response, receipt)
        except Exception as exc:
            errors.append({'kind': kind, 'period': period, 'source_url': url, 'error': str(exc)})
        if index % 20 == 0 or index == len(tasks):
            print(f'Progress {index}/{len(tasks)}; parsed observations {sum(parsed_counts.values())}; source failures {len(errors)}.', flush=True)
    if annual_rows:
        # This supplemental snapshot is generated from archived official releases,
        # not a hand-edited replacement of the historical source CSVs.
        merged = {}
        if ANNUAL_SUPPLEMENT_PATH.exists():
            with ANNUAL_SUPPLEMENT_PATH.open(encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle): merged[(row['indicator_code'], row['period'])] = row
        for row in annual_rows: merged[(row['indicator_code'], row['period'])] = row
        with ANNUAL_SUPPLEMENT_PATH.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(annual_rows[0]))
            writer.writeheader(); writer.writerows(merged[key] for key in sorted(merged))
    conn.close()

    pboc = None
    try:
        from services.pboc_balance_sheet_service import (
            connect as pboc_connect, ensure_pboc_balance_sheet_tables,
            parse_balance_sheet_xlsx, source_date_from_url,
        )
        response, receipt = get(PBOC_LATEST)
        meta = {'source_name': '中国人民银行', 'source_type': 'pboc_balance_sheet',
                'source_url': PBOC_LATEST, 'source_title': '货币当局资产负债表',
                'published_date': source_date_from_url(PBOC_LATEST),
                'parser_notes': '官方xlsx；空单元格按实际列位置处理；来源上传日与资料月分开。'}
        rows = parse_balance_sheet_xlsx(response.content, meta)
        with pboc_connect(str(args.db)) as c:
            ensure_pboc_balance_sheet_tables(c)
            for row in rows:
                columns = ('indicator_code','indicator_name','period','frequency','value','unit','data_status',
                           'source_name','source_type','source_url','source_title','published_date','parser_notes','formula')
                c.execute('INSERT INTO pboc_balance_sheet_observations (' + ','.join(columns) + ',updated_at) '
                          'VALUES (' + ','.join('?' for _ in range(len(columns)+1)) + ') '
                          'ON CONFLICT(indicator_code,period,source_url) DO UPDATE SET '
                          'value=excluded.value,updated_at=excluded.updated_at',
                          tuple(row.get(key) for key in columns) + (datetime.now().isoformat(),))
            c.commit()
        pboc = {'observations': len(rows), 'latest_period': max(row['period'] for row in rows),
                'raw_sha256': receipt['raw_sha256']}
    except Exception as exc:
        errors.append({'source_url': PBOC_LATEST, 'phase': 'pboc', 'error': str(exc)})
    with sqlite3.connect(args.db) as c:
        existing = {row[0] for row in c.execute('SELECT DISTINCT indicator_code FROM us_macro_observations')}
    new_fred = [row[0] for row in SERIES if row[0] not in existing]
    if args.verify_us_extensions:
        new_fred = ['PCEPI','PCEC96','DSPIC96','PSAVERT','GPDIC1','CCSA','AWHAETP','HOUST',
                    'PERMIT','HSN1F','MSPUS','TOTBKCR','EXPGS','IMPGS','BOPGSTB','DCOILWTICO','DCOILBRENTEU']
    print(f'Fetching {len(new_fred)} new FRED series with full source history.', flush=True)
    us_result = update_us_macro(str(args.db), codes=new_fred, archive_dir=raw_dir / 'fred')
    after = {country: build_macro_data_quality(str(args.db), country) for country in ('china', 'us')}
    audit = {'generated_at': datetime.now().astimezone().isoformat(), 'parameters': vars(args) | {'db': str(args.db), 'output_dir': str(args.output_dir)},
             'parsed_observations': parsed_counts, 'known_invalid_rates_preserved': len(damaged),
             'pboc': pboc, 'us_result': us_result, 'errors': errors,
             'source_manifest': manifest, 'coverage_before': before, 'coverage_after': after}
    (run / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'output_dir': str(run), 'parsed_observations': parsed_counts, 'pboc': pboc,
                      'us_result': us_result, 'errors': errors,
                      'coverage': {key: {field: value for field, value in item.items() if field != 'indicators'}
                                   for key,item in after.items()}}, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
