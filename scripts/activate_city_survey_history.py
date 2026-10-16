#!/usr/bin/env python3
"""Review archived NBS 31-city observations; fill only missing values with guarded --apply."""
import argparse
import hashlib
import json
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
from services.china_macro_service import INDICATORS, econ_period_from_article, parse_econ_unemployment_observations
from services.nbs_release_evidence import nbs_https_url, nbs_release_dates

CODE = 'CN_UNEMP_31_CITIES'
VERSION = 'nbs-city-survey-20261015'


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def validated_city_release(content, review):
    """Require matching title, statistical table month, original date and explicit values."""
    if nbs_https_url(review['source_url']) != review['source_url']:
        raise ValueError('Use the exact verified HTTPS source, not a downgraded transport.')
    soup = BeautifulSoup(content, 'html.parser')
    if not soup.title or compact(review['source_title']) != compact(soup.title.get_text().removesuffix(' - 国家统计局')):
        raise ValueError('The archived title differs from the reviewed NBS release.')
    html = str(soup)
    period = econ_period_from_article(html)
    if period != review['release_period']:
        raise ValueError('The statistical table does not independently verify this release month.')
    timing = nbs_release_dates(soup, require_original=True)
    year, month = map(int, period.split('-'))
    expected_publication = f'{year + (month == 12)}-{month % 12 + 1:02d}'
    if not timing['release_date'] or not timing['release_date'].startswith(expected_publication):
        raise ValueError('The original publication date must be the following month, not the migration URL.')
    rows = {observed: value for observed, code, value in parse_econ_unemployment_observations(html, period) if code == CODE}
    if rows != review['observations']:
        raise ValueError('Independently parsed explicit city rates differ from the reviewed values: ' + repr(rows))
    text = compact(soup.get_text('', strip=True))
    position = text.find('31个大城市')
    excerpt = text[max(0, position-150):position+180]
    return rows, timing, excerpt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--output-base', type=Path, default=ROOT / 'outputs/macro_refresh_20261015')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--repair-own-missing-flags', action='store_true',
                        help='Clear only a stale missing flag on this importer version and identical reviewed source/value.')
    args = parser.parse_args()
    config = json.loads(args.review.read_text(encoding='utf-8'))
    if config.get('schema_version') != 1 or config.get('indicator_code') != CODE or not args.database.is_file():
        raise ValueError('An existing database and the reviewed city-only scope are required.')
    rows, sources, keys = [], [], set()
    parser_hash = hashlib.sha256(PARSER_SOURCE.read_bytes()).hexdigest()
    for reviewed in config['sources']:
        archive = (ROOT / reviewed['archive']).resolve()
        if not archive.is_relative_to(ROOT):
            raise ValueError('A source archive cannot escape the workspace.')
        audit = json.loads((archive / 'audit.json').read_text(encoding='utf-8'))
        matches = [row for row in audit['source_manifest'] if row['source_url'] == reviewed['source_url']]
        if len(matches) != 1:
            raise ValueError('The original source manifest is absent or ambiguous.')
        source = matches[0]
        raw = (archive / source['raw_path']).resolve()
        if not raw.is_relative_to(archive):
            raise ValueError('A raw source cannot escape its archive.')
        content = raw.read_bytes()
        if hashlib.sha256(content).hexdigest() != source['raw_sha256']:
            raise ValueError('The original source bytes changed.')
        values, timing, excerpt = validated_city_release(content, reviewed)
        reference = raw.relative_to(ROOT).as_posix()
        sources.append({'source_url': reviewed['source_url'], 'raw_path': reference, 'raw_sha256': source['raw_sha256'],
                        'retrieved_at': source['retrieved_at'], 'reviewed_excerpt': excerpt, 'values': values, **timing})
        for period, value in values.items():
            if period in keys:
                raise ValueError('Review duplicate source vintages explicitly before activation.')
            keys.add(period)
            rows.append({'period': period, 'value': value, 'source_url': reviewed['source_url'],
                         'source_title': reviewed['source_title'], 'retrieved_at': source['retrieved_at'],
                         'raw_sha256': source['raw_sha256'], 'parser_notes':
                         'NBS explicit monthly 31-city rate; no national substitution, average allocation or interpolation; '
                         'original statistical table and publication month verified; source_archive_ref=' + reference +
                         ';city_parser_sha256=' + parser_hash, **timing})
    output = args.output_base / ('city-survey-activation-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    audit = {'phase': 'reviewed_not_applied', 'apply_requested': args.apply, 'sources': sources, 'expected_rows': rows,
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
                response.raise_for_status()
                jobs = response.json()
            job_rows = jobs.get('jobs', {})
            job_rows = job_rows.values() if isinstance(job_rows, dict) else job_rows
            if jobs.get('update_lock_busy') or any(row.get('status') in ('running', 'queued', 'pending') for row in job_rows):
                audit.update(phase='deferred_active_update_job', committed_rows=0)
                save()
                raise RuntimeError('An update job is active; archived source review remains separate.')
            conn.execute('BEGIN IMMEDIATE')
        else:
            conn.execute('BEGIN')
        pending, preserved, old_missing, own_repairs = [], [], [], []
        for row in rows:
            previous = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?', (CODE, row['period'])).fetchone()
            if previous and previous['value'] is not None:
                preserved.append(dict(previous))
                if previous['value'] != row['value']:
                    audit.update(phase='conflict_preserved_not_applied', conflict=dict(previous)); save()
                    raise ValueError('An existing nonmissing value conflicts; preserve it for separate review.')
                if (args.repair_own_missing_flags and previous['parser_version'] == VERSION
                        and previous['data_status'] == 'official' and previous['missing_reason']
                        and previous['source_url'] == row['source_url'] and previous['raw_sha256'] == row['raw_sha256']):
                    own_repairs.append(dict(previous))
            else:
                pending.append(row)
                if previous:
                    old_missing.append(dict(previous))
        changed_keys = {(CODE, row['period']) for row in pending + own_repairs}
        before = protected_digest(conn, changed_keys)
        audit.update(pending=len(pending), preserved_existing=len(preserved), old_missing=old_missing,
                     inserted_keys=len(pending)-len(old_missing), filled_null_values=len(old_missing),
                     own_flag_repairs_before=own_repairs, protected_before=before)
        save()
        if args.apply:
            try:
                name, unit, frequency = INDICATORS[CODE]
                for row in pending:
                    record = {'indicator_code': CODE, 'indicator_name': name, 'unit': unit, 'frequency': frequency,
                              'data_status': 'official', 'source_name': '国家统计局', 'source_type': 'china_macro',
                              'parser_version': VERSION, 'updated_at': datetime.now().isoformat(), 'formula': None,
                              'missing_reason': None, 'source_page_last_updated_date': None, **row}
                    fields = tuple(record)
                    conn.execute('INSERT INTO china_macro_observations (' + ','.join(fields) + ') VALUES (' +
                                 ','.join('?' for _ in fields) + ') ON CONFLICT(indicator_code,period) DO UPDATE SET ' +
                                 ','.join(field + '=excluded.' + field for field in fields if field not in ('indicator_code', 'period')),
                                 tuple(record.values()))
                for previous in own_repairs:
                    conn.execute('UPDATE china_macro_observations SET missing_reason=NULL WHERE indicator_code=? AND period=?',
                                 (CODE, previous['period']))
                for row in rows:
                    actual = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?', (CODE, row['period'])).fetchone()
                    if actual['value'] != row['value']:
                        raise ValueError('A city observation failed exact value readback.')
                    if row in pending and any(actual[field] != row[field] for field in ('source_url', 'raw_sha256', 'retrieved_at', 'release_date')):
                        raise ValueError('New observation provenance failed readback.')
                    if row in pending and actual['missing_reason'] is not None:
                        raise ValueError('A filled observation still carries an invalidation flag.')
                for previous in own_repairs:
                    actual = dict(conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                                               (CODE, previous['period'])).fetchone())
                    if actual != {**previous, 'missing_reason': None}:
                        raise ValueError('Own flag repair changed an unrelated field.')
                after = protected_digest(conn, changed_keys)
                if before != after:
                    raise ValueError('An old non-target macro row changed.')
                conn.commit()
                audit.update(phase='applied_readback_verified', committed_rows=len(pending), protected_after=after,
                             metadata_flags_cleared=len(own_repairs), protected_unchanged=True, exact_readback=True)
            except Exception as error:
                conn.rollback(); audit.update(phase='failed_rolled_back', committed_rows=0, error=str(error)); save(); raise
            save()
    print(json.dumps({'output_dir': str(output), 'phase': audit['phase'], 'pending': len(pending),
                      'preserved': len(preserved), 'committed_rows': audit.get('committed_rows')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
