#!/usr/bin/env python3
"""Review68 archived official FRED snapshots; optionally atomically apply actual differences."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.fred_native_review import load_fred_native_archive,METADATA
from services.us_macro_service import upsert_fred_observations


def protected_us_digest(conn,keys):
    digest=hashlib.sha256();count=0
    for r in conn.execute('SELECT * FROM us_macro_observations ORDER BY id'):
        if (r['indicator_code'],r['period']) in keys:continue
        digest.update((json.dumps(dict(r),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'));count+=1
    return count,digest.hexdigest()


def compare_sources(conn,sources):
    planned=[];keys=set();old_changed=[]
    for code,source in sorted(sources.items()):
        old={r['period']:dict(r) for r in conn.execute('SELECT * FROM us_macro_observations WHERE indicator_code=?',(code,))}
        m=METADATA[code];counts={'inserted':0,'updated':0,'unchanged':0};changed=[]
        for r in source['rows']:
            previous=old.get(r['period'])
            same=previous and previous['value']==r['value'] and previous['unit']==m['unit'] and previous['frequency']==m['frequency'] and previous['data_status'] in ('official','official_final')
            if same:counts['unchanged']+=1;continue
            keys.add((code,r['period']));counts['updated' if previous else 'inserted']+=1
            if previous:old_changed.append(previous);changed.append({'period':r['period'],'old':previous['value'],'new':r['value']})
        source_periods={r['period'] for r in source['rows']};omitted=sorted(set(old)-source_periods)
        planned.append({'code':code,**counts,'source_observations':len(source['rows']),
                        'source_start':min(source_periods),'source_end':max(source_periods),
                        'local_end_before':max(old) if old else None,'existing_not_in_snapshot':len(omitted),
                        'existing_not_in_snapshot_sample':omitted[:5],'revision_sample':changed[-5:],
                        'raw_sha256':source['receipt']['raw_sha256'],'receipt_ref':source['receipt']['receipt_ref']})
    return planned,keys,old_changed


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-dir',type=Path,required=True)
    p.add_argument('--database',type=Path,default=ROOT/'pboc_data.db');p.add_argument('--apply',action='store_true')
    p.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261015');args=p.parse_args()
    if not args.database.is_file():raise ValueError('Do not create a substitute production database.')
    sources=load_fred_native_archive(args.source_dir)
    output=args.output_dir/('fred-native-review-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir(parents=True,exist_ok=False)
    audit={'phase':'reviewed_not_applied','apply_requested':args.apply,'sources':68,'source_dir':str(args.source_dir),'network_requests':0,'full_repository_test_claim':False}
    target=str(args.database) if args.apply else args.database.resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(target,timeout=30,uri=not args.apply)) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA busy_timeout=30000')
        if args.apply:
            s=requests.Session();s.trust_env=False;r=s.get('http://127.0.0.1:5001/api/jobs',timeout=15);r.raise_for_status();data=r.json();jobs=data.get('jobs',{});jobs=jobs.values() if isinstance(jobs,dict) else jobs
            if data.get('update_lock_busy') or any(j.get('status') in ('running','queued','pending') for j in jobs):raise RuntimeError('An update job is active; keep source review separate.')
            conn.execute('BEGIN IMMEDIATE')
        else:conn.execute('BEGIN')  # One consistent read-only WAL snapshot.
        plan,keys,old=compare_sources(conn,sources);before=protected_us_digest(conn,keys)
        totals={k:sum(x[k] for x in plan) for k in ('inserted','updated','unchanged')}
        audit.update(plan=plan,planned_totals=totals,protected_before=before,old_changed_records=len(old),
                     omitted_existing_rows_preserved=sum(x['existing_not_in_snapshot'] for x in plan))
        if not args.apply and totals['inserted']==0 and totals['updated']==0 and audit['omitted_existing_rows_preserved']==0:
            audit.update(phase='verified_current_no_changes',all_source_values_and_native_units_match=True,production_writes=0)
        (output/'before_changed_rows.json').write_bytes((json.dumps(old,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        if args.apply:
            try:
                actual={k:0 for k in totals}
                for code,source in sorted(sources.items()):
                    receipt=dict(source['receipt']);receipt['receipt_ref']=str(source['receipt_path'].relative_to(ROOT))
                    counts=upsert_fred_observations(conn,code,source['rows'],receipt)
                    for k in actual:actual[k]+=counts[k]
                if actual!=totals:raise ValueError('Actual changes do not match the frozen plan.')
                for code,source in sources.items():
                    values={r['period']:r['value'] for r in conn.execute('SELECT period,value FROM us_macro_observations WHERE indicator_code=?',(code,))}
                    if any(values.get(r['period'])!=r['value'] for r in source['rows']):raise ValueError('Source-value readback failed: '+code)
                after=protected_us_digest(conn,keys)
                if after!=before:raise ValueError('An untouched U.S. row changed.')
                conn.commit();audit.update(phase='applied_readback_verified',actual=actual,protected_after=after,protected_unchanged=True,all_source_values_readback=True)
            except Exception as exc:
                conn.rollback();audit.update(phase='failed_rolled_back',committed_rows=0,error=str(exc));(output/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');raise
            (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),'phase':audit['phase'],'totals':totals,'source_observations':sum(len(s['rows']) for s in sources.values()),'omitted_existing_rows_preserved':audit['omitted_existing_rows_preserved'],'protected_unchanged':audit.get('protected_unchanged')},ensure_ascii=False))


if __name__=='__main__':main()
