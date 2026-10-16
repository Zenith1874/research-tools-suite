#!/usr/bin/env python3
"""Archive verified FDI releases and repair exact misdated rows without deleting originals."""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.china_macro_service import connect, ensure_china_macro_tables
from services.china_external_service import (
    MOFCOM_FDI_API, MOFCOM_DATA_URL, _number, _observation, _period_yyyymm,
    parse_mofcom_fdi_text, quarantine_mofcom_period_mismatches,
)

RELEASES = (
    ('2023年全国吸收外资1.1万亿元人民币',
     'https://www.mofcom.gov.cn/xwfb/rcxwfb/art/2024/art_9df7a4a551f94067b9b81d73b1c30d7f.html',
     '2023-12', '2023年，全国新设立外商投资企业53766家', '2024-01-19'),
    ('2022年全国实际使用外资稳定增长',
     'https://www.mofcom.gov.cn/syxwfb/art/2023/art_083e241e45c14215a153b7111b6bd60f.html',
     '2022-12', '2022年，全国实际使用外资金额12326.8亿元人民币', '2023-01-18'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261013')
    parser.add_argument('--apply', action='store_true', help='Apply only after exact original reporting-period evidence is present.')
    parser.add_argument('--replay-source-dir', type=Path, help='Reuse checksum-verified sources from an earlier bounded attempt.')
    args = parser.parse_args()
    out = args.output_dir / ('mofcom-period-repair-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    manifest, observations, errors = [], [], []
    cached = {}
    if args.replay_source_dir:
        previous = json.loads((args.replay_source_dir / 'audit.json').read_text(encoding='utf-8'))
        cached = {item['source_url']: item for item in previous['source_manifest']}
    audit = {'started_at': datetime.now().astimezone().isoformat(), 'source_manifest': manifest,
             'errors': errors, 'changes': [], 'applied': False}

    def archive(url, name, post=False):
        if url in cached:
            prior = cached[url]
            path = (args.replay_source_dir / prior['raw_path']).resolve()
            if not path.is_relative_to(args.replay_source_dir.resolve()):
                raise ValueError('Cached source escaped its archived run directory.')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != prior['raw_sha256']:
                raise ValueError('Archived source checksum mismatch.')
            (out / name).write_bytes(content)
            record = {**prior, 'raw_path': name, 'replayed_at': datetime.now().astimezone().isoformat()}
            manifest.append(record)
            with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            response = requests.Response()
            response._content = content
            response.encoding = 'utf-8'
            return response, record
        kwargs = {'timeout': 20, 'headers': {'User-Agent': 'Mozilla/5.0'}}
        response = session.post(url, json={}, **kwargs) if post else session.get(url, **kwargs)
        response.raise_for_status()
        host = urlsplit(response.url).hostname or ''
        if not host.endswith('.mofcom.gov.cn'):
            raise ValueError('Official source redirected outside MOFCOM.')
        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError('Source exceeds bounded small-release scope.')
        response.encoding = 'utf-8'
        (out / name).write_bytes(response.content)
        record = {'source_url': url, 'resolved_url': response.url, 'raw_path': name,
                  'request_method': 'POST' if post else 'GET', 'request_json': {} if post else None,
                  'retrieved_at': datetime.now().astimezone().isoformat(),
                  'raw_sha256': hashlib.sha256(response.content).hexdigest()}
        manifest.append(record)
        with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        return response, record

    for index, (title, url, period, exact_sentence, release_date) in enumerate(RELEASES, 1):
        try:
            response, record = archive(url, f'release-{index}.html')
            text = BeautifulSoup(response.text, 'html.parser').get_text(' ', strip=True)
            if re.sub(r'\s+', '', exact_sentence) not in re.sub(r'\s+', '', text):
                raise ValueError('The source does not contain the independently checked reporting-year sentence.')
            rows = parse_mofcom_fdi_text(title, text, url)
            if not rows or any(row['period'] != period for row in rows):
                raise ValueError('Parsed reporting period disagrees with the original source.')
            for row in rows:
                row.update(retrieved_at=record['retrieved_at'], raw_sha256=record['raw_sha256'],
                           parser_version='mofcom_headline_period_20261013', release_date=release_date)
            observations.extend(rows)
        except Exception as exc:
            errors.append({'source_url': url, 'error': str(exc)})
    # An original API company count can restore a year-end total without using
    # annual-bulletin counts to synthesize monthly company observations.
    try:
        response, record = archive(MOFCOM_FDI_API, 'fdi-api.json', post=True)
        payload = response.json()
        for raw in payload[0] if payload and isinstance(payload[0], list) else []:
            if _period_yyyymm(raw.get('data_time')) != '2022-12':
                continue
            for code, key in (('CN_MOFCOM_FDI_NEW_FIRMS_YTD', 'project_number'),
                              ('CN_MOFCOM_FDI_NEW_FIRMS_YTD_YOY', 'project_per')):
                value = _number(raw.get(key))
                row = _observation(code, '2022-12', value, '商务部', 'mofcom_data_api',
                                   MOFCOM_DATA_URL, '吸收外商直接投资月报图表',
                                   '官方API原始2022-12企业数；不由公报年度数拆分。',
                                   raw_sha256=record['raw_sha256'], retrieved_at=record['retrieved_at'])
                if row:
                    observations.append(row)
    except Exception as exc:
        errors.append({'source_url': MOFCOM_FDI_API, 'error': str(exc)})
    audit['observations'] = observations
    if args.apply and all(any(row['period'] == period and row['source_type'] == 'mofcom_fdi'
                              for row in observations) for period in ('2022-12', '2023-12')):
        conn = connect(args.db)
        ensure_china_macro_tables(conn)
        before = [dict(row) for row in conn.execute("SELECT * FROM china_macro_observations WHERE "
                  "indicator_code LIKE 'CN_MOFCOM_FDI_%' AND period IN ('2022-12','2023-12')")]
        (out / 'original_rows.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            audit['quarantined_rows'] = quarantine_mofcom_period_mismatches(conn, observations)
            for row in observations:
                old = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                   (row['indicator_code'], row['period'])).fetchone()
                if old and old['value'] is not None:
                    if abs(old['value'] - row['value']) > 1e-8:
                        raise ValueError('Unexpected valid-target conflict; no unreviewed overwrite is allowed.')
                    continue
                keys = [key for key in row if key in {col[1] for col in conn.execute('PRAGMA table_info(china_macro_observations)')}]
                if old:
                    assignments = ','.join(f'{key}=?' for key in keys if key not in ('indicator_code', 'period'))
                    values = [row[key] for key in keys if key not in ('indicator_code', 'period')]
                    conn.execute(f'UPDATE china_macro_observations SET {assignments},updated_at=? WHERE id=?',
                                 (*values, datetime.now().astimezone().isoformat(), old['id']))
                else:
                    conn.execute('INSERT INTO china_macro_observations (' + ','.join(keys) + ',updated_at) VALUES (' +
                                 ','.join('?' for _ in range(len(keys) + 1)) + ')',
                                 (*[row[key] for key in keys], datetime.now().astimezone().isoformat()))
                audit['changes'].append({'indicator_code': row['indicator_code'], 'period': row['period'],
                                         'value': row['value'], 'original_row': dict(old) if old else None})
            conn.commit()
            audit['applied'] = True
            audit['readback'] = [dict(row) for row in conn.execute("SELECT indicator_code,period,value,original_value,"
                                "data_status,source_url FROM china_macro_observations WHERE indicator_code LIKE "
                                "'CN_MOFCOM_FDI_%' AND period IN ('2022-12','2023-12') ORDER BY indicator_code,period")]
        except Exception as exc:
            conn.rollback()
            audit['changes'] = []
            audit['apply_error'] = str(exc)
        finally:
            conn.close()
    audit['finished_at'] = datetime.now().astimezone().isoformat()
    (out / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), 'observations': len(observations), 'errors': errors,
                      'applied': audit['applied'], 'apply_error': audit.get('apply_error'),
                      'changes': len(audit['changes'])}, ensure_ascii=False))
    raise SystemExit(0 if audit['applied'] or (not args.apply and observations) else 1)


if __name__ == '__main__':
    main()
