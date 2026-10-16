#!/usr/bin/env python3
"""Apply reviewed province fiscal snapshots with streamed protected-row verification."""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from contextlib import closing

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.regional_fiscal_service import sync_reviewed_regional_fiscal,validate_reviewed_regional_fiscal_snapshot


def protected_digest(conn,keys):
    digest=hashlib.sha256();count=0
    for row in conn.execute('SELECT * FROM regional_fiscal_observations ORDER BY id'):
        key=(row['country_code'],row['government_scope'],row['region_code'],row['indicator_code'],row['period'])
        if key in keys:continue
        digest.update((json.dumps(dict(row),ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8'))
        count+=1
    return count,digest.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'pboc_data.db')
    parser.add_argument('--snapshot-dir',type=Path,default=ROOT/'data/regional_fiscal_reviewed')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261013')
    args=parser.parse_args()
    if not args.database.is_file():raise ValueError('Refuse to create a replacement database.')
    snapshots=[]
    for path in args.snapshot_dir.glob('*.json'):
        value=json.loads(path.read_text(encoding='utf-8'));validate_reviewed_regional_fiscal_snapshot(value);snapshots.append(value)
    if not snapshots:raise ValueError('No reviewed fiscal snapshot.')
    expected={(r['country_code'],r['government_scope'],r['region_code'],r['indicator_code'],r['period']):r['value']
              for s in sorted(snapshots,key=lambda s:s['generated_at']) for r in s['observations']}
    out=args.output_dir/('province-fiscal-activation-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    path=out/'audit.json'
    with closing(sqlite3.connect(args.database,timeout=30)) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA busy_timeout=30000')
        if args.apply:
            s=requests.Session();s.trust_env=False;r=s.get('http://127.0.0.1:5001/api/jobs',timeout=15);r.raise_for_status()
            data=r.json();jobs=data.get('jobs',[]) if isinstance(data,dict) else data
            if isinstance(jobs,dict):jobs=list(jobs.values())
            if data.get('update_lock_busy') or any(j.get('status') in ('running','pending','queued') for j in jobs if isinstance(j,dict)):
                path.write_bytes((json.dumps({'phase':'blocked_active_job','apply_requested':True,'committed_rows':0},indent=2)+'\n').encode('utf-8'))
                raise RuntimeError('An update job is active; keep this activation separate.')
            # Acquire one bounded write transaction before read/freeze. This avoids
            # upgrading a stale WAL read snapshot and makes all year groups atomic.
            conn.execute('BEGIN IMMEDIATE')
        count,before=protected_digest(conn,set(expected))
        prior=[dict(row) for row in conn.execute('SELECT * FROM regional_fiscal_observations')
               if (row['country_code'],row['government_scope'],row['region_code'],row['indicator_code'],row['period']) in expected]
        audit={'phase':'reviewed_ready_not_applied','target_keys':len(expected),'target_rows_before':prior,
               'protected_rows':count,'protected_sha256_before':before,'apply_requested':args.apply}
        path.write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        if args.apply:
            try:
                audit['import']=sync_reviewed_regional_fiscal(conn,args.snapshot_dir)
                if audit['import']['errors']:
                    raise ValueError('Fiscal import errors: '+json.dumps(audit['import']['errors'],ensure_ascii=False))
                after={};rows_after=[]
                for row in conn.execute('SELECT * FROM regional_fiscal_observations'):
                    key=(row['country_code'],row['government_scope'],row['region_code'],row['indicator_code'],row['period'])
                    if key in expected:after[key]=row['value'];rows_after.append(dict(row))
                after_count,after_hash=protected_digest(conn,set(expected))
                audit.update(target_rows_after=rows_after,exact_value_readback=after==expected,
                             protected_sha256_after=after_hash,protected_rows_unchanged=(after_count==count and after_hash==before))
                if not audit['exact_value_readback'] or not audit['protected_rows_unchanged']:
                    raise ValueError('Readback verification failed; no year group will be committed.')
                conn.commit();audit.update(phase='applied_readback_verified',committed_rows=audit['import']['inserted']+audit['import']['updated'])
            except Exception as exc:
                conn.rollback();audit.update(phase='failed_rolled_back',committed_rows=0,error=str(exc))
                path.write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
                raise
            path.write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(out),'phase':audit['phase'],'target_keys':len(expected),
                      'import':audit.get('import'),'protected_rows_unchanged':audit.get('protected_rows_unchanged')},ensure_ascii=False))


if __name__=='__main__':main()
