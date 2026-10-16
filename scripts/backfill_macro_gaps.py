#!/usr/bin/env python3
"""Fill verified NBS history gaps using archived public search and article responses."""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
from bs4 import BeautifulSoup
from services.china_macro_service import (
    NBS_SEARCH_API, NBS_SEARCH_SITE_CODE, UA, connect, ensure_china_macro_tables,
    econ_period_from_article, parse_econ_article, parse_econ_unemployment_observations, INDICATORS,
)
from services.china_macro_extended_service import profit_period, parse_industrial_profit_article, parse_annual_unemployment_commentary


def official_article_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme in ('http', 'https') and parsed.hostname == 'www.stats.gov.cn'
            and parsed.path.endswith('.html') and not parsed.query)


def nbs_article_release_date(html):
    """Read publication metadata or the dated NBS release heading, never the URL."""
    dates=set()
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup.find_all('meta'):
        if str(tag.get('name') or '').lower()!='pubdate':
            continue
        match=re.match(r'(20\d{2})[-/](\d{2})[-/](\d{2})',tag.get('content') or '')
        if match:
            value='-'.join(match.groups())
            try:
                datetime.strptime(value,'%Y-%m-%d')
                dates.add(value)
            except ValueError:
                continue
    # Older migrated releases retain an original dated heading followed by the
    # issuing agency. Ordinary reporting-period dates and Info document dates are
    # not publication evidence. Conflicting explicit dates remain unavailable.
    text = re.sub(r'\s+', '', soup.get_text(' ', strip=True))
    for match in re.finditer(r'[（(](20\d{2})年(\d{1,2})月(\d{1,2})日[）)]中华人民共和国国家统计局', text):
        year, month, day = (int(value) for value in match.groups())
        try:
            value = datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            continue
        dates.add(value)
    return next(iter(dates)) if len(dates)==1 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--start-year', type=int, default=2018)
    parser.add_argument('--end-year', type=int, default=datetime.now().year)
    parser.add_argument('--max-requests', type=int, default=130)
    parser.add_argument('--search-pages', type=int, default=2)
    parser.add_argument('--broad-econ-pages', type=int, default=0,
                        help='Scan public national-economy search pages without trusting migrated URL dates.')
    parser.add_argument('--replay-audit', type=Path)
    parser.add_argument('--replay-raw-only', action='store_true',
                        help='Reuse cached responses without re-queueing unrelated earlier profit articles.')
    parser.add_argument('--resume-journal-dir', type=Path,
                        help='Reuse hash-verified raw responses from an interrupted run without inventing its completion audit.')
    parser.add_argument('--extra-releases', type=Path,
                        help='Verified public source links; an explicit period hint requires literal year and month evidence.')
    parser.add_argument('--date-filtered', action='store_true',
                        help='Use the public search UI timeOption/startDateStr/endDateStr fields.')
    parser.add_argument('--target-unemployment-gaps', action='store_true',
                        help='Search only the publication windows for still-missing monthly survey rates.')
    parser.add_argument('--sleep', type=float, default=0.35)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261010')
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('The existing observation database is required.')
    out = args.output_dir / ('nbs-gaps-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    raw = out / 'raw'
    raw.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    manifest, failures, reviewed, changes, skipped, deferred = [], [], [], [], [], []
    metadata_changes=[]
    request_count = 0
    cached = {}
    if args.replay_audit:
        previous = json.loads(args.replay_audit.read_text(encoding='utf-8'))
        cached_base = args.replay_audit.parent
    elif args.resume_journal_dir:
        previous = {'source_manifest': [json.loads(line) for line in
            (args.resume_journal_dir/'manifest.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]}
        cached_base = args.resume_journal_dir
    else:
        previous = None
        cached_base = None
    if previous:
        cached = {(row['source_url'], json.dumps(row.get('request_form'), sort_keys=True)): row
                  for row in previous['source_manifest']}
    pending = {}
    conn = connect(str(args.db))
    ensure_china_macro_tables(conn)
    before = {code: {row['period'] for row in conn.execute(
        'SELECT period FROM china_macro_observations WHERE indicator_code=? AND value IS NOT NULL', (code,))}
        for code in ('CN_UNEMP_SURVEY', 'CN_UNEMP_31_CITIES', 'CN_IND_PROFIT_YTD_YOY')}
    # A previously reviewed profit release may still lack ancillary stock fields
    # even after its headline official growth rate has been filled.
    if args.replay_audit and not args.replay_raw_only:
        for row in previous.get('reviewed', []):
            hint = profit_period(row['title'], row['url'])
            if hint:
                pending[('profit', row['url'])] = {'title': row['title'],
                    'expected_year': int(hint[:4]), 'period_hint': hint}
    if args.extra_releases:
        extra=json.loads(args.extra_releases.read_text(encoding='utf-8'))
        if extra.get('schema_version')!=1:
            raise ValueError('Unsupported extra release schema.')
        for row in extra['releases']:
            if row['kind'] not in ('econ','employment_commentary') or not official_article_url(row['source_url']):
                raise ValueError('Only verified public NBS economic article links are accepted.')
            if row.get('period_hint') and not all(row.get(key) for key in
                ('reporting_year_evidence','month_evidence')):
                raise ValueError('A curated period hint needs literal source evidence, not a guessed date.')
            allowed=row.get('allowed_codes') or ['CN_UNEMP_SURVEY','CN_UNEMP_31_CITIES']
            if not set(allowed)<=set(('CN_UNEMP_SURVEY','CN_UNEMP_31_CITIES')):
                raise ValueError('Unknown code in reviewed employment source scope.')
            status=row.get('data_status') or ('official_relayed' if row['kind']=='employment_commentary' else 'official')
            if status not in ('official','official_relayed'):
                raise ValueError('Unsupported reviewed source evidence status.')
            pending[(row['kind'],row['source_url'])]={'title':row['source_title'],
                'expected_year':row.get('reporting_year'),'period_hint':row.get('period_hint'),
                'year_evidence':row.get('reporting_year_evidence'),
                'month_evidence':row.get('month_evidence'),'allowed_codes':allowed,'data_status':status,
                'reporting_year_basis':row.get('reporting_year_basis')}

    def save_receipt():
        receipt = {'captured_at': datetime.now().astimezone().isoformat(),
                   'parameters': {key: str(value) if isinstance(value, Path) else value
                                  for key, value in vars(args).items()},
                   'requests': request_count, 'source_manifest': manifest,
                   'reviewed': reviewed, 'changes': changes, 'metadata_changes':metadata_changes,'skipped': skipped,
                   'deferred_candidates': deferred, 'errors': failures}
        # Append-only journal is the durable checkpoint; the final JSON is written once.
        return receipt

    def request(url, method='GET', form=None):
        nonlocal request_count
        prior = cached.get((url, json.dumps(form, sort_keys=True)))
        if prior:
            path = (cached_base / prior['raw_path']).resolve()
            if not path.is_relative_to(cached_base.resolve()):
                raise ValueError('Cached response path escaped the source run.')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != prior['raw_sha256']:
                raise ValueError('Cached response hash mismatch.')
            target = raw / f'cached-{len(manifest):04d}-{prior["raw_sha256"][:12]}.response'
            target.write_bytes(content)
            record = {**prior, 'raw_path': target.relative_to(out).as_posix(),
                      'replayed_at': datetime.now().astimezone().isoformat()}
            manifest.append(record)
            with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + '\n')
            response = requests.Response()
            response._content = content
            response.encoding = 'utf-8'
            return response, record
        if request_count >= args.max_requests:
            raise RuntimeError('Configured request budget exhausted; unvisited sources stay missing.')
        request_count += 1
        time.sleep(args.sleep)
        response = session.request(method, url, data=form, headers=UA, timeout=18)
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        path = raw / f'{request_count:04d}-{digest[:12]}.response'
        path.write_bytes(response.content)
        record = {'source_url': url, 'resolved_url': response.url, 'request_method': method,
                  'request_form': form, 'retrieved_at': datetime.now().astimezone().isoformat(),
                  'raw_path': path.relative_to(out).as_posix(), 'raw_sha256': digest}
        manifest.append(record)
        with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        response.encoding = 'utf-8'
        return response, record

    queries = []
    if args.date_filtered:
        # The parameters are taken from the site's own public search client.
        request('https://www.stats.gov.cn/search/s')
        request('https://p.so-gov.cn/web/api/util.js')
    windows = {}
    if args.target_unemployment_gaps:
        observed = sorted(before['CN_UNEMP_SURVEY'])
        first = int(observed[0][:4])*12 + int(observed[0][5:])-1
        last = int(observed[-1][:4])*12 + int(observed[-1][5:])-1
        for key in range(first,last+1):
            year,month=key//12,key%12+1
            target=f'{year}-{month:02d}'
            if target in before['CN_UNEMP_SURVEY']:
                continue
            start_key=key+1
            end_key=key+(3 if month==1 else 2)
            start=f'{start_key//12}-{start_key%12+1:02d}-01'
            end=f'{end_key//12}-{end_key%12+1:02d}-01'
            query_id=target
            windows[query_id]=(start,end)
            queries.append(('econ',query_id,'国民经济','1'))
    for year in (() if args.target_unemployment_gaps else range(args.start_year, args.end_year + 1)):
        queries.append(('econ', year, '国民经济' if args.date_filtered else f'{year}年 城镇调查失业率', '1'))
        # The longer legacy keyword missed the entire 2021 profit cohort.
        if any(f'{year}-{month:02d}' not in before['CN_IND_PROFIT_YTD_YOY']
               for month in range(2, 13) if f'{year}-{month:02d}' <= datetime.now().strftime('%Y-%m')):
            queries.append(('profit', year, '规模以上工业企业利润' if args.date_filtered else f'{year}年 规模以上工业企业 利润', '1'))
    if args.broad_econ_pages:
        queries.append(('econ', None, '国民经济', '1'))
    for kind, year, query, key_place in queries:
        pages = args.broad_econ_pages if year is None else args.search_pages
        for page in range(1, pages + 1):
            try:
                form = {
                    'siteCode': NBS_SEARCH_SITE_CODE, 'qt': query, 'page': page,
                    'pageSize': 20, 'keyPlace': key_place,
                    'sort': 'dateDesc' if year is None else 'relevance'}
                if year in windows:
                    start,end=windows[year]
                    form.update(timeOption=2,startDateStr=start,endDateStr=end)
                elif args.date_filtered and year is not None:
                    form.update(timeOption=2, startDateStr=f'{year}-01-01', endDateStr=f'{year+1}-02-28')
                response, record = request(NBS_SEARCH_API, 'POST', form)
                payload = response.json()
                if not payload.get('ok'):
                    raise ValueError('Public NBS search did not return an accepted response.')
                for doc in payload.get('resultDocs') or []:
                    data = doc.get('data', doc)
                    title = BeautifulSoup(str(data.get('title') or ''), 'html.parser').get_text('', strip=True)
                    url = data.get('url') or ''
                    if not official_article_url(url):
                        continue
                    if kind == 'econ' and ('国民经济' not in title or '统计公报' in title or '答' in title or '解读' in title):
                        continue
                    period = profit_period(title, url) if kind == 'profit' else None
                    if kind == 'profit' and (not period or int(period[:4]) != year or period in before['CN_IND_PROFIT_YTD_YOY']):
                        continue
                    pending[(kind, url)] = {'title': title, 'expected_year': year, 'period_hint': period}
                if page * 20 >= int(payload.get('totalHits') or 0):
                    break
            except Exception as exc:
                failures.append({'phase': 'search', 'kind': kind, 'year': year, 'error': str(exc)})
                break
    print(f'{len(pending)} official history candidates; source archives: {out}', flush=True)
    for index, ((kind, url), candidate) in enumerate(pending.items(), 1):
        try:
            response, record = request(url)
            release_date=nbs_article_release_date(response.text)
            if candidate.get('year_evidence'):
                source_text=re.sub(r'\s+','',BeautifulSoup(response.text,'html.parser').get_text('',strip=True))
                if not all(re.sub(r'\s+','',candidate[key]) in source_text for key in ('year_evidence','month_evidence')):
                    raise ValueError('The archived source does not contain the curated year/month evidence.')
            period = (candidate['period_hint'] if kind == 'profit' else
                      f"{candidate['expected_year']}-12" if kind=='employment_commentary' else
                      candidate.get('period_hint') or econ_period_from_article(response.text, candidate['title'], url))
            if not period or not args.start_year <= int(period[:4]) <= args.end_year:
                skipped.append({'url': url, 'reason': 'Actual source period not verified in requested range.'})
                continue
            values = (parse_industrial_profit_article(response.text) if kind == 'profit' else {} if kind=='employment_commentary' else
                      parse_econ_article(response.text, period=period))
            codes = tuple(code for code in INDICATORS if code.startswith('CN_IND_')) if kind == 'profit' else (
                         'CN_UNEMP_SURVEY', 'CN_UNEMP_31_CITIES')
            approved = {code: values[code] for code in codes if code in values}
            reviewed.append({'url': url, 'period': period, 'title': candidate['title'], 'values': approved,
                             'reporting_year_basis':candidate.get('reporting_year_basis')})
            observations = ([(period, code, value) for code, value in approved.items()] if kind == 'profit' else
                            parse_annual_unemployment_commentary(response.text,candidate['expected_year']) if kind=='employment_commentary'
                            else parse_econ_unemployment_observations(response.text, period))
            for observed_period, code, value in observations:
                if candidate.get('allowed_codes') and code not in candidate['allowed_codes']:
                    continue
                # An explicit January unemployment rate is not a split YTD flow.
                observation_period = observed_period
                old = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?', (code, observation_period)).fetchone()
                if old and old['value'] is not None:
                    if abs(old['value'] - value) > 1e-8:
                        skipped.append({'code': code, 'period': observation_period, 'old': old['value'], 'source_value': value,
                                        'url': url, 'reason': 'Conflict preserved for independent review; not overwritten.'})
                    elif old['source_url']==url and ((release_date and not old['release_date']) or not old['raw_sha256']):
                        conn.execute('''UPDATE china_macro_observations SET
                            release_date=COALESCE(release_date,?),raw_sha256=COALESCE(raw_sha256,?)
                            WHERE indicator_code=? AND period=? AND source_url=? AND value=?''',
                            (release_date,record['raw_sha256'],code,observation_period,url,value))
                        metadata_change={'code':code,'period':observation_period,'source_url':url,
                            'release_date':release_date,'raw_sha256':record['raw_sha256'],'original_row':dict(old)}
                        metadata_changes.append(metadata_change)
                        with (out/'metadata_changes.jsonl').open('a',encoding='utf-8') as handle:
                            handle.write(json.dumps(metadata_change,ensure_ascii=False)+'\n')
                    continue
                name, unit, frequency = INDICATORS[code]
                now = record['retrieved_at']
                observation_status=candidate.get('data_status') or ('official_relayed' if kind=='employment_commentary' else 'official')
                notes=('Official employment commentary explicitly states each monthly rate; reporting year validated from the source text or heading; no average allocation or interpolation.'
                       if kind=='employment_commentary' else 'Verified historical source period; source-comparable official values; migration URL date not used.')
                if candidate.get('reporting_year_basis'):
                    notes+=' Reporting-year basis: '+candidate['reporting_year_basis']
                conn.execute('''INSERT INTO china_macro_observations
                    (indicator_code,indicator_name,period,value,unit,frequency,data_status,source_name,
                     source_type,source_url,source_title,parser_notes,updated_at,retrieved_at,parser_version,release_date,raw_sha256)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(indicator_code,period) DO UPDATE SET value=excluded.value,
                    data_status=excluded.data_status,source_url=excluded.source_url,source_title=excluded.source_title,
                    parser_notes=excluded.parser_notes,updated_at=excluded.updated_at,retrieved_at=excluded.retrieved_at,
                    parser_version=excluded.parser_version,release_date=excluded.release_date,raw_sha256=excluded.raw_sha256''',
                    (code, name, observation_period, value, unit, frequency,
                     observation_status, '国家统计局',
                     'nbs_reviewed_commentary' if observation_status=='official_relayed' else 'nbs_official_release', url, candidate['title'],
                     notes,now,now,'nbs-gaps-20261012',release_date,record['raw_sha256']))
                change = {'code': code, 'period': observation_period, 'value': value, 'source_url': url,
                          'original_row': dict(old) if old else None}
                changes.append(change)
                with (out / 'changes.jsonl').open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(change, ensure_ascii=False) + '\n')
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, RuntimeError) and str(exc).startswith('Configured request budget exhausted'):
                deferred.extend({'kind': next_kind, 'url': next_url, **details}
                    for (next_kind, next_url), details in list(pending.items())[index-1:])
                break
            failures.append({'phase': 'article', 'kind': kind, 'url': url, 'error': str(exc)})
        if index % 10 == 0:
            print(f'Articles {index}/{len(pending)}, gap fills {len(changes)}, errors {len(failures)}', flush=True)
    conn.close()
    (out / 'audit.json').write_text(json.dumps(save_receipt(), ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), 'changes': len(changes), 'reviewed_articles': len(reviewed),
                      'metadata_changes':len(metadata_changes),
                      'requests': request_count, 'deferred_candidates': len(deferred),
                      'errors': len(failures)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
