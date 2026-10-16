#!/usr/bin/env python3
"""Fill missing annual livelihood observations from hash-verified official source archives."""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
PARSER_SOURCE = ROOT / 'services/china_macro_extended_service.py'
sys.path.insert(0, str(ROOT))
from scripts.activate_bank_history_year import protected_digest
from services.china_macro_service import INDICATORS, econ_period_from_article
from services.china_macro_extended_service import (
    parse_annual_livelihood_article, parse_compiled_annual_pdf,
    parse_urbanization_retrospective, COMPILED_ANNUAL_TABLES,
)
from services.nbs_release_evidence import nbs_https_url, nbs_release_dates

VERSION = 'nbs-reviewed-annual-history-20261015-v3'
COMPILED_BOOK_URL = 'https://www.stats.gov.cn/zt_18555/ztsj/jzgj/jzsc2023/202404/P020240417553133577139.pdf'


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def validate_livelihood_source(content, review):
    """Verify the national annual scope, original date and every approved field."""
    for code, value in review['values'].items():
        if (code not in INDICATORS or INDICATORS[code][2] != 'annual'
                or type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError('Use finite actual values in a registered annual indicator.')
    if review['kind'] == 'official_compilation_pdf':
        if review['source_url'] != COMPILED_BOOK_URL or not content.startswith(b'%PDF-'):
            raise ValueError('Only the explicitly reviewed public official compilation is accepted.')
        profile = review['table_profile']
        if profile not in COMPILED_ANNUAL_TABLES:
            raise ValueError('Unknown reviewed table/country profile.')
        parsed = parse_compiled_annual_pdf(content, profile, int(review['year']))
        # The edition is dated February2024, but no exact online publication day
        # is given. PDF creation and URL upload dates are not publication dates.
        timing = {'release_date': None, 'source_page_created_date': None, 'release_date_not_provided': 1,
                  'release_date_reason': '原书标2024年2月版次，未给出具体网络发布日期；不以PDF创建时间或URL上传目录冒充发布日。'}
        for code, value in review['values'].items():
            if code not in INDICATORS or INDICATORS[code][2] != 'annual' or parsed.get(code) != value:
                raise ValueError('A compiled-table field differs from its explicit row/year cell: ' + code)
        return timing
    if nbs_https_url(review['source_url']) != review['source_url']:
        raise ValueError('An exact verified public HTTPS NBS source is required.')
    soup = BeautifulSoup(content, 'html.parser')
    heading = soup.select_one('.xxgkNbXqTitle') or soup.title
    if not heading or compact(heading.get_text().strip().removesuffix(' - 国家统计局')) != compact(review['source_title']):
        raise ValueError('The archived national source title differs from the reviewed title.')
    year = int(review['year']); text = compact(soup.get_text('', strip=True))
    timing = nbs_release_dates(soup, require_original=True)
    if review['kind'] == 'urbanization_measure_repair':
        original = timing['release_date'] or timing['source_page_created_date']
        hukou = {float(value) for value in re.findall(r'户籍人口城镇化率(?:为|达到|达)?([\d.]+)%', text)}
        resident = {float(value) for value in re.findall(r'常住人口城镇化率[）)]?(?:为|达到|达)?([\d.]+)%', text)}
        parsed = parse_annual_livelihood_article(str(soup))
        expected = review['values'].get('CN_URBANIZATION_RATE')
        if (set(review['values']) != {'CN_URBANIZATION_RATE'}
                or f'{year}年年末人口数及其构成' not in text
                or not original or not original.startswith(str(year + 1) + '-')
                or hukou != {review['expected_wrong_hukou_value']} or resident != {expected}
                or parsed.get('CN_URBANIZATION_RATE') != expected):
            raise ValueError('The same original must independently distinguish resident and hukou rates.')
        return timing
    if review['kind'] == 'urbanization_retrospective':
        if review['source_url'] != 'https://www.stats.gov.cn/sj/sjjd/202606/t20260603_1963868.html':
            raise ValueError('Use the explicitly reviewed national urbanization report.')
        parsed_rates = parse_urbanization_retrospective(str(soup))
        if (not timing['release_date'] or timing['release_date'] != '2026-06-03'
                or set(review['values']) != {'CN_URBANIZATION_RATE'}
                or parsed_rates.get(str(year)) != review['values']['CN_URBANIZATION_RATE']):
            raise ValueError('The national retrospective must explicitly state this year and rate.')
        return timing
    if not timing['release_date'] or not timing['release_date'].startswith(str(year + 1) + '-'):
        raise ValueError('An original next-year release date must establish the annual vintage.')
    if review['kind'] == 'statistical_bulletin':
        if (compact(review['source_title']) != f'{year}年国民经济和社会发展统计公报'
                or f'{year}年年末人口数及其构成' not in text):
            raise ValueError('The annual title and statistical table must independently agree.')
    elif review['kind'] == 'yearend_economy':
        if econ_period_from_article(str(soup)) != f'{year}-12':
            raise ValueError('A year-end source must explicitly report December/full year, not a partial year.')
    else:
        raise ValueError('Unknown reviewed annual source family.')
    parsed = parse_annual_livelihood_article(str(soup))
    for code, value in review['values'].items():
        if (code not in INDICATORS or INDICATORS[code][2] != 'annual'
                or type(value) not in (int, float) or not math.isfinite(value)
                or parsed.get(code) != value):
            raise ValueError('A reviewed annual field differs from explicit original parsing: ' + code)
    return timing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-base', type=Path, default=ROOT / 'outputs/macro_refresh_20261015')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--repair-urbanization-scope', action='store_true',
                        help='Explicitly repair only a verified resident/hukou measure mix-up, preserving full old records.')
    args = parser.parse_args()
    if not args.database.is_file():
        raise ValueError('Do not create a substitute production database.')
    config = json.loads(args.review.read_text(encoding='utf-8'))
    if config.get('schema_version') != 1:
        raise ValueError('Unknown reviewed source schema.')
    if any(row['kind'] == 'urbanization_measure_repair' for row in config['sources']) != args.repair_urbanization_scope:
        raise ValueError('Resident/hukou corrections require their explicit, separate repair mode.')
    if args.repair_urbanization_scope and any(row['kind'] != 'urbanization_measure_repair' for row in config['sources']):
        raise ValueError('Do not mix source-measure repairs with a fill-missing batch.')
    rows, sources, seen, repair_wrong_values = [], [], set(), {}
    parser_hash = hashlib.sha256(PARSER_SOURCE.read_bytes()).hexdigest()
    for review in config['sources']:
        archive = (ROOT / review['archive']).resolve()
        if not archive.is_relative_to(ROOT):
            raise ValueError('The archive must stay in this workspace.')
        source_audit = json.loads((archive / 'audit.json').read_text(encoding='utf-8'))
        matches = [row for row in source_audit['source_manifest'] if row['source_url'] == review['source_url']]
        if len(matches) != 1:
            raise ValueError('An unambiguous original capture is required.')
        source = matches[0]; raw = (archive / source['raw_path']).resolve()
        if not raw.is_relative_to(archive):
            raise ValueError('An original file cannot escape its source run.')
        content = raw.read_bytes()
        if hashlib.sha256(content).hexdigest() != source['raw_sha256']:
            raise ValueError('The original source hash changed.')
        timing = validate_livelihood_source(content, review)
        reference = raw.relative_to(ROOT).as_posix()
        sources.append({'source_url': review['source_url'], 'raw_path': reference, 'raw_sha256': source['raw_sha256'],
                        'year': review['year'], 'kind': review['kind'], 'table_profile': review.get('table_profile'),
                        'reviewed_fields': review['values'], 'retrieved_at': source['retrieved_at'], **timing})
        for code, value in review['values'].items():
            period = str(review['year']); key = (code, period)
            if key in seen:
                raise ValueError('Resolve duplicate source vintages before importing.')
            seen.add(key)
            name, unit, frequency = INDICATORS[code]
            status, source_name, link = 'official_preliminary', '国家统计局', review['source_url']
            notes = '官方年度公报/年末首次发布值；不替代既有年鉴修订值；仅取明确全国年度指标；城乡/全国中位数与纯收入不互代；金额不推算'
            if review['kind'] == 'official_compilation_pdf':
                status, source_name = 'official_reprinted', '国家统计局等·金砖国家联合统计手册2023'
                page = COMPILED_ANNUAL_TABLES[review['table_profile']]['page']
                link += '#page=' + str(page)
                notes = '国家统计局官网公开统计表重刊原值；2024年2月版；第' + str(page) + '页的明确年度列；不推算未列年份或其他年龄段'
                if review['table_profile'] == 'population_china':
                    notes += '；人口年末数及其年龄构成，2020为普查推算年末统计口径，不以普查标准时点数代替'
                elif review['year'] < 2013:
                    notes += '；2000为旧住户调查历史代表点，2001—2012本表未列，不补齐或跨缺年连线；2013起为全国住户调查'
                else:
                    notes += '；2013起全国住户调查口径；不以旧农村纯收入或旧城镇调查值替代'
            elif review['kind'] == 'urbanization_retrospective':
                status = 'official'
                notes = '国家统计局官方回顾明确列示该年度常住人口城镇化率；2020普查校准基准与早期公报初步估计不同；未由人口数反算，不与普查时点/年末总人口机械拼接为官方城镇人数'
            elif review['kind'] == 'urbanization_measure_repair':
                repair_wrong_values[key] = review['expected_wrong_hukou_value']
                notes = '修复指标含义错误：原常住城镇化率误取同稿户籍率；正确值经常住率正文与年末人口表城镇比重列双重核对；不是年鉴修订或跨版本替换；完整旧行另存审核收据'
            notes += ';source_archive_ref=' + reference + ';parser_sha256=' + parser_hash
            if review['kind'] in ('statistical_bulletin', 'yearend_economy') and code in ('CN_INCOME_URBAN', 'CN_INCOME_RURAL'):
                notes += ';城乡一体化住户调查口径；2013旧城镇口径另保留并断线'
            rows.append({'indicator_code': code, 'indicator_name': name, 'period': period, 'value': value,
                         'unit': unit, 'frequency': frequency, 'data_status': status,
                         'source_name': source_name, 'source_type': 'china_macro_annual',
                         'source_url': link, 'source_title': review['source_title'],
                         'parser_notes': notes, 'formula': None, 'parser_version': VERSION,
                         'retrieved_at': source['retrieved_at'], 'raw_sha256': source['raw_sha256'],
                         'source_page_last_updated_date': None, 'missing_reason': None, **timing})
    output = args.output_base / ('livelihood-activation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    audit = {'phase': 'reviewed_not_applied', 'apply_requested': args.apply, 'expected_rows': rows, 'sources': sources,
             'network_source_requests': 0, 'parser_version': VERSION, 'parser_sha256': parser_hash}

    def save():
        (output / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    target = str(args.database) if args.apply else args.database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(target, uri=not args.apply, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        if args.apply:
            with closing(requests.Session()) as session:
                session.trust_env = False
                response = session.get('http://127.0.0.1:5001/api/jobs', timeout=15, allow_redirects=False)
                if response.status_code != 200:
                    raise RuntimeError('The actual local job guard is unavailable.')
                jobs = response.json()
            active = jobs.get('jobs', {}); active = active.values() if isinstance(active, dict) else active
            if jobs.get('update_lock_busy') or any(row.get('status') in ('running', 'queued', 'pending') for row in active):
                audit.update(phase='deferred_active_update_job', committed_rows=0); save()
                raise RuntimeError('An update job is active; no production import.')
            conn.execute('BEGIN IMMEDIATE')
        else:
            conn.execute('BEGIN')
        pending, preserved, old_missing, old_repaired = [], [], [], []
        for row in rows:
            old = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?', (row['indicator_code'], row['period'])).fetchone()
            if old and old['value'] is not None:
                key = (row['indicator_code'], row['period'])
                if args.repair_urbanization_scope and old['value'] != row['value']:
                    if (old['value'] != repair_wrong_values[key] or old['source_url'] != row['source_url']
                            or old['raw_sha256'] != row['raw_sha256']):
                        audit.update(phase='repair_baseline_mismatch_preserved', conflict=dict(old)); save()
                        raise ValueError('The live value/source/hash differs from the verified measure mix-up.')
                    old_repaired.append(dict(old))
                    row['original_value'] = old['original_value'] if old['original_value'] is not None else old['value']
                    pending.append(row)
                    continue
                preserved.append(dict(old))
                if old['value'] != row['value']:
                    audit.update(phase='conflict_preserved_not_applied', conflict=dict(old)); save()
                    raise ValueError('Preserve a different existing annual value for separate vintage review.')
            else:
                pending.append(row)
                if old:
                    old_missing.append(dict(old))
        changed_keys = {(row['indicator_code'], row['period']) for row in pending}
        before = protected_digest(conn, changed_keys)
        audit.update(pending=len(pending), preserved_existing=len(preserved), old_missing=old_missing,
                     old_repaired=old_repaired, corrected_existing_rows=len(old_repaired),
                     inserted_keys=len(pending)-len(old_missing)-len(old_repaired), filled_null_values=len(old_missing), protected_before=before)
        save()
        if args.apply:
            try:
                for row in pending:
                    record = {**row, 'updated_at': datetime.now().isoformat()}; fields = tuple(record)
                    conn.execute('INSERT INTO china_macro_observations (' + ','.join(fields) + ') VALUES (' +
                                 ','.join('?' for _ in fields) + ') ON CONFLICT(indicator_code,period) DO UPDATE SET ' +
                                 ','.join(field + '=excluded.' + field for field in fields if field not in ('indicator_code', 'period')),
                                 tuple(record.values()))
                for row in rows:
                    actual = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?', (row['indicator_code'], row['period'])).fetchone()
                    if actual['value'] != row['value'] or row in pending and any(actual[key] != value for key, value in row.items()):
                        raise ValueError('An annual value or provenance field failed exact readback.')
                after = protected_digest(conn, changed_keys)
                if after != before:
                    raise ValueError('An old non-target macro record changed.')
                conn.commit(); audit.update(phase='applied_readback_verified', committed_rows=len(pending),
                                            exact_readback=True, protected_after=after, protected_unchanged=True)
            except Exception as error:
                conn.rollback(); audit.update(phase='failed_rolled_back', committed_rows=0, error=str(error)); save(); raise
            save()
    print(json.dumps({'output_dir': str(output), 'phase': audit['phase'], 'pending': len(pending),
                      'preserved': len(preserved), 'committed_rows': audit.get('committed_rows'),
                      'inserted_keys': audit['inserted_keys'], 'filled_null_values': audit['filled_null_values']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
