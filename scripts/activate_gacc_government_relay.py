#!/usr/bin/env python3
"""Review one archived official relay and fill only missing September CNY observations."""
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
from services.china_external_service import parse_gacc_q3_government_relay,upsert_external_observations
from scripts.activate_bank_history_year import protected_digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--database',type=Path,default=ROOT/'pboc_data.db')
    p.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261015');p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    if not args.database.is_file():raise ValueError('Never create a substitute production database.')
    receipt=json.loads((args.source_dir/'receipt.json').read_text(encoding='utf-8'))
    path=(args.source_dir/receipt['raw_path']).resolve()
    if not path.is_relative_to(args.source_dir.resolve()):raise ValueError('Original escaped source archive.')
    content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=receipt['raw_sha256'] or receipt['http_status']!=200 or receipt['certificate_or_proxy_override']:
        raise ValueError('Complete verified original bytes are required.')
    rows=parse_gacc_q3_government_relay(content,'2026-09',receipt['source_url'])
    for row in rows:
        row.update(retrieved_at=receipt['retrieved_at'],raw_sha256=receipt['raw_sha256'])
        row['parser_notes']+='; access_mode='+receipt['access_mode']+'; raw_sha256='+receipt['raw_sha256']
    output=args.output_dir/('gacc-relay-activation-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));output.mkdir(parents=True,exist_ok=False)
    audit={'phase':'reviewed_not_applied','source_receipt':str(args.source_dir/'receipt.json'),'expected_rows':rows,'apply_requested':args.apply}
    with closing(sqlite3.connect(args.database,timeout=30)) as conn:
        conn.row_factory=sqlite3.Row;conn.execute('PRAGMA busy_timeout=30000')
        if args.apply:
            s=requests.Session();s.trust_env=False;data=s.get('http://127.0.0.1:5001/api/jobs',timeout=15).json()
            jobs=data.get('jobs',{});jobs=jobs.values() if isinstance(jobs,dict) else jobs
            if data.get('update_lock_busy') or any(j.get('status') in ('running','queued','pending') for j in jobs):raise RuntimeError('An update job is active; no production import.')
            conn.execute('BEGIN IMMEDIATE')
        pending=[];preserved=[];before=[]
        for row in rows:
            old=conn.execute('SELECT * FROM china_macro_observations WHERE indicator_code=? AND period=?',(row['indicator_code'],row['period'])).fetchone()
            if old is None or old['value'] is None:
                pending.append(row)
                if old:before.append(dict(old))
            else:preserved.append({'indicator_code':row['indicator_code'],'value':old['value'],'source_url':old['source_url'],'reason':'Do not replace existing nonmissing official data with a coarser relay.'})
        keys={(r['indicator_code'],r['period']) for r in pending};signature=protected_digest(conn,keys)
        audit.update(pending=len(pending),preserved_existing=preserved,target_rows_before=before,protected_before=signature)
        (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        if args.apply:
            try:
                upsert_external_observations(conn,pending,commit=False)
                exact=all(conn.execute('SELECT value FROM china_macro_observations WHERE indicator_code=? AND period=?',(r['indicator_code'],r['period'])).fetchone()[0]==r['value'] for r in pending)
                after=protected_digest(conn,keys)
                if not exact or after!=signature:raise ValueError('Value or protected-row readback failed.')
                conn.commit();audit.update(phase='applied_readback_verified',committed_rows=len(pending),exact_value_readback=True,protected_after=after,protected_unchanged=True)
            except Exception as exc:
                conn.rollback();audit.update(phase='failed_rolled_back',committed_rows=0,error=str(exc));(output/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8');raise
            (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),'phase':audit['phase'],'pending':len(pending),'preserved_existing':len(preserved),'committed_rows':audit.get('committed_rows')},ensure_ascii=False))


if __name__=='__main__':main()
