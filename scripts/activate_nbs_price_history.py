#!/usr/bin/env python3
"""Review archived prices with explicit append, value-repair or metadata-only modes."""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.china_macro_service import INDICATORS, SOURCE_NAME, SOURCE_TYPE, parse_ppi_article, parse_cpi_article
from services.nbs_release_evidence import nbs_release_dates
from scripts.activate_bank_history_year import protected_digest

FIELDS = ('CN_PPI_YOY', 'CN_PPI_MOM', 'CN_PPIRM_YOY', 'CN_PPIRM_MOM',
          'CN_PPI_PRODUCTION_YOY', 'CN_PPI_LIVING_YOY')


def compact(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or ''))


def price_source_timing(soup):
    """Keep explicit publication dates separate from creation-only disclosure metadata."""
    return nbs_release_dates(soup,require_original=True)


def validated_price_document(html, period, title, kind):
    """Bind an exact official heading, reporting month and truthful timing roles."""
    prefixes={'ppi':r'工业生产者(?:出厂)?价格','cpi':r'居民消费价格'}
    if kind not in prefixes:
        raise ValueError('Only reviewed CPI/PPI source families are supported.')
    match = re.match(r'(20\d{2})年(\d{1,2})月份'+prefixes[kind], compact(title))
    if not match or period != f'{match[1]}-{int(match[2]):02d}' or not 1 <= int(match[2]) <= 12:
        raise ValueError('The fully dated source title must establish the observation month.')
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('.detail-title h1, .xxgkNbXqTitle')
    heading_text=compact(heading.get_text()) if heading else ''
    if heading is not None and not heading_text:
        # Recent official pages render the visible heading from script data;
        # bind the exact provided ArticleTitle metadata without executing JS.
        metadata=[compact(x.get('content')) for x in soup.find_all('meta')
                  if str(x.get('name') or '').lower()=='articletitle']
        heading_text=metadata[0] if len(metadata)==1 else ''
    if heading is None or heading_text != compact(title):
        raise ValueError('The archived official article heading differs from the reviewed title.')
    timing=price_source_timing(soup)
    original=datetime.strptime(timing['release_date'] or timing['source_page_created_date'],'%Y-%m-%d')
    year, month = int(match[1]), int(match[2])
    if (original.year, original.month) != (year + (month == 12), month % 12 + 1):
        raise ValueError('Original source timing metadata is inconsistent with the reported monthly release.')
    table_name='工业生产者价格' if kind=='ppi' else '居民消费价格'
    if not re.search(fr'{year}年{month}月份?{table_name}主要数据', compact(soup.get_text())):
        raise ValueError('The original monthly table must independently state the observation period.')
    return soup,timing


def validated_ppi_article(html, period, title):
    """Independently reconcile the existing prose parser with original table cells."""
    soup,timing=validated_price_document(html,period,title,'ppi')
    table_values = {}
    labels = {'工业生产者出厂价格':('CN_PPI_MOM','CN_PPI_YOY'),
              '工业生产者购进价格':('CN_PPIRM_MOM','CN_PPIRM_YOY'),
              '生产资料':(None,'CN_PPI_PRODUCTION_YOY'),
              '生活资料':(None,'CN_PPI_LIVING_YOY')}
    for table in soup.find_all('table'):
        table_rows = [[compact(c.get_text(' ', strip=True)) for c in tr.find_all(['td','th'])]
                      for tr in table.find_all('tr')]
        header_candidates = [[c for c in r if c] for r in table_rows]
        if not any(len(r)>=2 and '环比' in r[0] and '同比' in r[1] for r in header_candidates):
            continue
        for cells in table_rows:
            if len(cells)<3:
                continue
            label = re.sub(r'^[一二三四五六七八九十]+、', '', cells[0])
            if label not in labels:
                continue
            for code, cell in zip(labels[label], cells[1:3]):
                if code is None:
                    continue
                if not re.fullmatch(r'-?\d+(?:\.\d+)?', cell):
                    raise ValueError('A directly reported numeric table cell is required; no missing-to-zero conversion.')
                value = float(cell)
                if code in table_values and value != table_values[code]:
                    raise ValueError('Conflicting repeated table cells must be reviewed, not overwritten.')
                table_values[code] = value
    prose = parse_ppi_article(html)
    if set(table_values) != set(FIELDS) or set(prose) != set(FIELDS):
        raise ValueError('All six independently checked monthly price fields are required.')
    if any(not math.isclose(prose[k], table_values[k], abs_tol=1e-9, rel_tol=0) for k in FIELDS):
        raise ValueError('Existing prose parser differs from the original monthly table.')
    return table_values, timing['release_date']


def validated_cpi_article(html, period, title):
    """Check current CPI monthly columns and the separately labelled core YTD average."""
    soup,timing=validated_price_document(html,period,title,'cpi')
    labels={'居民消费价格':('CN_CPI_MOM','CN_CPI_YOY')}
    for label,code in (('食品','FOOD'),('非食品','NONFOOD'),('消费品','GOODS'),
                       ('服务','SERVICES'),('不包括食品和能源','CORE')):
        labels[label]=(f'CN_CPI_{code}_MOM',f'CN_CPI_{code}_YOY')
    values={}
    for table in soup.find_all('table'):
        rows=[[compact(c.get_text(' ',strip=True)) for c in tr.find_all(['td','th'])]
              for tr in table.find_all('tr')]
        headers=[r for r in rows if len(r)>=4 and '环比' in r[1] and '同比' in r[2] and '同比' in r[3]]
        if not headers:
            continue
        for cells in rows:
            if len(cells)<3:
                continue
            label=re.sub(r'^其中:', '', cells[0])
            if label not in labels:
                continue
            targets=list(zip(labels[label],cells[1:3]))
            if label=='不包括食品和能源':
                if len(cells)<4:
                    raise ValueError('Core CPI YTD average must be explicitly reported in its own column.')
                targets.append(('CN_CPI_CORE_YTD_AVG_YOY',cells[3]))
            for code,cell in targets:
                if not re.fullmatch(r'-?\d+(?:\.\d+)?',cell):
                    raise ValueError('CPI table blanks/ellipsis are not zero.')
                value=float(cell)
                if code in values and values[code]!=value:
                    raise ValueError('Conflicting repeated CPI table cells.')
                values[code]=value
    prose=parse_cpi_article(html)
    if len(values)!=13 or values!=prose:
        raise ValueError('All13 CPI fields must agree with the original explicitly labelled columns.')
    return values,timing['release_date']


def observation_value_digest(conn):
    """Hash all semantic values, original values and classifications, excluding provenance."""
    digest=hashlib.sha256();count=0
    for row in conn.execute('''SELECT id,indicator_code,indicator_name,period,value,unit,frequency,
                            data_status,formula,original_value FROM china_macro_observations ORDER BY id'''):
        digest.update((json.dumps(dict(row),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'))
        count+=1
    return count,digest.hexdigest()


def plan_existing_metadata(conn, rows):
    """Preflight exact observed values and return only compatible metadata additions."""
    pending=[];seen=set()
    for row in rows:
        key=(row['indicator_code'],row['period'])
        if key in seen:
            raise ValueError('Duplicate annotation identity.')
        seen.add(key)
        old=conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',key).fetchone()
        if (old is None or old['value']!=row['value'] or old['unit']!=row['unit'] or old['frequency']!='monthly'
                or not str(old['data_status']).startswith('official')):
            raise ValueError('Metadata annotation requires an existing exact monthly value.')
        old=dict(old);changes={}
        for field in ('raw_sha256','release_date','source_page_created_date'):
            current=old[field];verified=row.get(field)
            if current not in (None,'') and verified not in (None,'') and current!=verified:
                raise ValueError('Conflicting known source metadata requires separate review.')
            if current in (None,'') and verified not in (None,''):
                changes[field]=verified
        if old['release_date'] and row.get('release_date') is None:
            raise ValueError('Do not relabel an existing known release date using a creation-only source.')
        if old['source_url']!=row['source_url']:
            if not (old['source_url'].startswith('http://www.stats.gov.cn/') and
                    'https://'+old['source_url'][7:]==row['source_url']):
                raise ValueError('An archive hash must refer to the exact source pointer, not an unfetched alias.')
            changes['source_url']=row['source_url']
        if not old['retrieved_at'] and row.get('retrieved_at'):
            changes['retrieved_at']=row['retrieved_at']
        for field in ('release_date_not_provided','release_date_reason'):
            if old[field]!=row.get(field,0 if field=='release_date_not_provided' else None):
                changes[field]=row.get(field,0 if field=='release_date_not_provided' else None)
        if changes:
            changes['parser_notes']=(old['parser_notes'] or '')+'；source_metadata_v1：经归档原文补齐来源元数据，数值未改。'
            changes['updated_at']=datetime.now().isoformat()
            pending.append((old['id'],changes))
    return pending


def annotate_existing_rows(conn, rows):
    """Fill verified provenance only; never change a value, original or parser version."""
    pending=plan_existing_metadata(conn,rows)
    # Preflight the entire cohort before changing any metadata.
    for identifier,changes in pending:
        conn.execute('UPDATE china_macro_observations SET '+','.join(k+'=?' for k in changes)+' WHERE id=?',
                     (*changes.values(),identifier))
    return {'inserted':0,'updated_values':0,'updated_metadata':len(pending),'unchanged':len(rows)-len(pending)}


def append_missing_rows(conn, rows):
    """Insert only absent keys; exact existing values retain all original metadata."""
    keys = [(r['indicator_code'],r['period']) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate price identities in the reviewed snapshot.')
    columns = ('indicator_code','indicator_name','period','value','unit','frequency',
               'data_status','source_name','source_type','source_url','source_title',
               'parser_notes','updated_at','release_date','retrieved_at','raw_sha256','parser_version',
               'source_page_created_date','release_date_not_provided','release_date_reason')
    existing = {}
    for row in rows:
        old = conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',
                           (row['indicator_code'],row['period'])).fetchone()
        if old is not None:
            if old['value'] != row['value'] or old['unit'] != row['unit'] or old['frequency'] != 'monthly':
                raise ValueError('Existing observation conflicts; keep both source claims pending, never silently revise.')
            existing[(row['indicator_code'],row['period'])] = dict(old)
    inserted = 0
    for row in rows:
        if (row['indicator_code'],row['period']) in existing:
            continue
        conn.execute('INSERT INTO china_macro_observations ('+','.join(columns)+') VALUES ('+
                     ','.join('?' for _ in columns)+')', tuple(row.get(c,0 if c=='release_date_not_provided' else None) for c in columns))
        inserted += 1
    return {'inserted':inserted, 'updated':0, 'unchanged':len(existing)}


def row_fingerprint(row):
    return hashlib.sha256(json.dumps(dict(row),ensure_ascii=False,sort_keys=True,
                                    separators=(',',':')).encode('utf-8')).hexdigest()


def reconcile_existing_rows(conn, rows, corrections):
    """Apply explicitly reviewed value repairs after checking every original row."""
    expected={(r['indicator_code'],r['period']):r for r in corrections}
    source={(r['indicator_code'],r['period']):r for r in rows}
    if len(expected)!=len(corrections) or len(source)!=len(rows) or not set(expected)<=set(source):
        raise ValueError('Correction identities must be unique and belong to the reviewed source rows.')
    pending=[]
    for key,row in source.items():
        original=conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',key).fetchone()
        if original is None or original['unit']!='%' or original['frequency']!='monthly':
            raise ValueError('Reconciliation requires existing monthly percentage observations.')
        original=dict(original)
        if original['value']==row['value']:
            continue
        review=expected.get(key)
        if review is None or original['value']!=review['expected_old_value'] or row_fingerprint(original)!=review['expected_old_row_sha256']:
            raise ValueError('An unreviewed/stale original differs; no repair is permitted.')
        if not str(original['data_status']).startswith('official'):
            raise ValueError('Do not silently replace a derived or invalidated observation.')
        pending.append((original,row))
    # All originals are checked before the first write. The caller owns the
    # transaction and freezes full originals in target_rows_before.json.
    for original,row in pending:
        initial=original['original_value'] if original['original_value'] is not None else original['value']
        conn.execute('''UPDATE china_macro_observations SET value=?,original_value=?,
                     source_url=?,source_title=?,source_name=?,source_type=?,
                     parser_notes=?,parser_version=?,release_date=?,retrieved_at=?,raw_sha256=?,updated_at=?,
                     source_page_created_date=?,release_date_not_provided=?,release_date_reason=?
                     WHERE id=?''',
                     (row['value'],initial,row['source_url'],row['source_title'],row['source_name'],row['source_type'],
                      (original['parser_notes'] or '')+'；经官方当月表格与正文核对，更正旧解析错读；首次旧值保留在original_value，本轮完整旧记录已冻结。',
                      'nbs-price-reconciled-20261015',row['release_date'],row['retrieved_at'],row['raw_sha256'],
                      datetime.now().isoformat(),row.get('source_page_created_date'),row.get('release_date_not_provided',0),
                      row.get('release_date_reason'),original['id']))
    return {'inserted':0,'updated':len(pending),'unchanged':len(rows)-len(pending)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, action='append', required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--database', type=Path, default=ROOT/'pboc_data.db')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--reconcile-existing', action='store_true',
                        help='Require an explicit reviewed correction list; preserve full originals and original_value.')
    parser.add_argument('--metadata-only', action='store_true',
                        help='Fill verified provenance while preserving every semantic value and original.')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'outputs/macro_refresh_20261015')
    args = parser.parse_args()
    if args.metadata_only and args.reconcile_existing:
        parser.error('Select one explicit operation, not value repair and metadata annotation together.')
    if not args.database.is_file():
        raise ValueError('The existing database is required; do not create a replacement.')
    review = json.loads(args.review.read_text(encoding='utf-8'))
    if review.get('schema_version')!=1 or review.get('review_status')!='source_values_reviewed':
        raise ValueError('An explicitly reviewed source-value configuration is required.')
    if args.reconcile_existing and review.get('operation')!='reconcile_existing_source_errors':
        raise ValueError('Value repair needs the explicitly reviewed reconciliation operation.')
    if not args.reconcile_existing and review.get('operation')=='reconcile_existing_source_errors':
        raise ValueError('Do not run a repair review through the append-only path.')
    if args.metadata_only and review.get('operation')!='annotate_existing_source_metadata':
        raise ValueError('Metadata-only changes require an explicit annotation review.')
    if not args.metadata_only and review.get('operation')=='annotate_existing_source_metadata':
        raise ValueError('A metadata review cannot be used to append or revise values.')
    records = {}
    for directory in args.source_dir:
        for record in json.loads((directory/'audit.json').read_text(encoding='utf-8'))['source_manifest']:
            if record['id'] in records:
                raise ValueError('Duplicate archive identities; select one exact original.')
            records[record['id']] = (directory, record)
    rows, sources = [], []
    for source in review['documents']:
        directory, record = records[source['id']]
        path = (directory/record['raw_path']).resolve()
        url = urlsplit(record['source_url'])
        if (not path.is_relative_to(directory.resolve()) or record['format']!='html' or
                url.scheme!='https' or url.hostname!='www.stats.gov.cn' or url.query or
                record['source_url']!=source['source_url']):
            raise ValueError('Reviewed archive identity, path or official article URL changed.')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=record['raw_sha256'] or record['raw_sha256']!=source['raw_sha256']:
            raise ValueError('Reviewed original source bytes changed.')
        kind=source.get('kind','ppi')
        if kind not in ('ppi','cpi'):
            raise ValueError('Unknown reviewed price family.')
        values, released = (validated_ppi_article if kind=='ppi' else validated_cpi_article)(
            content.decode('utf-8'), source['period'], source['source_title'])
        timing=price_source_timing(BeautifulSoup(content.decode('utf-8'),'html.parser'))
        if values != source['expected_values']:
            raise ValueError('Original table differs from the inspected source-value review.')
        for code, value in values.items():
            name, unit, frequency = INDICATORS[code]
            rows.append({'indicator_code':code,'indicator_name':name,'period':source['period'],'value':value,
                         'unit':unit,'frequency':frequency,'data_status':'official','source_name':SOURCE_NAME,
                         'source_type':SOURCE_TYPE,'source_url':record['source_url'],'source_title':source['source_title'],
                         'parser_notes':'官方月报正文与原表逐字段核对；环比/同比/累计同比分列，不拆年度；2011年起工业生产者价格统计新制度；原始发布时间不由迁移地址日期推断。',
                         'updated_at':datetime.now().isoformat(),'release_date':released,
                         'retrieved_at':record['retrieved_at'],'raw_sha256':record['raw_sha256'],
                         'parser_version':'nbs-price-history-reviewed-20261015',**timing})
        sources.append({'period':source['period'],'source_url':record['source_url'],'raw_sha256':record['raw_sha256'],
                        'release_date':released,'table_values':values,'raw_path':str(path.relative_to(ROOT))})
    output = args.output_dir/('price-history-activation-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    (output/'reviewed_rows.json').write_bytes((json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    audit = {'captured_at':datetime.now(timezone.utc).isoformat(),'phase':'reviewed_not_applied',
             'network_requests':0,'source_count':len(sources),'target_count':len(rows),'sources':sources,
             'apply_requested':args.apply,'reconcile_existing':args.reconcile_existing,'metadata_only':args.metadata_only}
    keys = {(r['indicator_code'],r['period']) for r in rows}
    correction_keys={(r['indicator_code'],r['period']) for r in review.get('corrections',[])}
    protected_keys=correction_keys if args.reconcile_existing else keys
    with closing(sqlite3.connect(args.database,timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        before = [dict(r) for r in conn.execute('SELECT * FROM china_macro_observations ORDER BY id')
                  if (r['indicator_code'],r['period']) in keys]
        if args.metadata_only:
            pending_metadata=plan_existing_metadata(conn,rows)
            pending_ids={identifier for identifier,_ in pending_metadata}
            protected_keys={(r['indicator_code'],r['period']) for r in before if r['id'] in pending_ids}
            audit['metadata_plan_count']=len(pending_metadata)
            audit['already_complete_rows']=len(rows)-len(pending_metadata)
        audit['protected_before'] = protected_digest(conn, protected_keys)
        audit['all_values_before']=observation_value_digest(conn)
        (output/'target_rows_before.json').write_bytes((json.dumps(before,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        if args.apply:
            session=requests.Session();session.trust_env=False
            response=session.get('http://127.0.0.1:5001/api/jobs',timeout=15);response.raise_for_status()
            jobs=response.json();jobs=jobs.get('jobs',[]) if isinstance(jobs,dict) else jobs
            if isinstance(jobs,dict):jobs=list(jobs.values())
            if any(isinstance(j,dict) and j.get('status') in ('running','pending','queued') for j in jobs):
                raise RuntimeError('A live update job is active; do not overlap this activation.')
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                audit['import'] = (annotate_existing_rows(conn,rows) if args.metadata_only else
                                   reconcile_existing_rows(conn,rows,review['corrections'])
                                   if args.reconcile_existing else append_missing_rows(conn,rows))
                after = {(r['indicator_code'],r['period']):dict(r) for r in conn.execute('SELECT * FROM china_macro_observations ORDER BY id')
                         if (r['indicator_code'],r['period']) in keys}
                audit['protected_after'] = protected_digest(conn, protected_keys)
                audit['all_values_after']=observation_value_digest(conn)
                audit['all_semantic_values_preserved']=audit['all_values_before']==audit['all_values_after']
                audit['existing_target_rows_unchanged'] = all(after[(r['indicator_code'],r['period'])]==r for r in before)
                audit['unchanged_target_rows_preserved'] = all(after[(r['indicator_code'],r['period'])]==r for r in before
                                                              if (r['indicator_code'],r['period']) not in correction_keys)
                audit['exact_value_readback'] = all(after[(r['indicator_code'],r['period'])]['value']==r['value'] for r in rows)
                preserved=(audit['all_semantic_values_preserved'] if args.metadata_only else
                           audit['unchanged_target_rows_preserved'] if args.reconcile_existing else audit['existing_target_rows_unchanged'])
                if (audit['protected_before']!=audit['protected_after'] or not preserved
                        or not audit['exact_value_readback']):
                    raise ValueError('Scoped preservation/readback verification failed; transaction rolled back.')
            audit['phase']='applied_readback_verified'
    (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),'phase':audit['phase'],'source_count':len(sources),
                      'target_count':len(rows),'import':audit.get('import')},ensure_ascii=False))


if __name__ == '__main__':
    main()
