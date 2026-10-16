#!/usr/bin/env python3
"""Exercise fiscal snapshots in a small isolated DB without production writes."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.regional_fiscal_service import (
    ensure_regional_fiscal_table,sync_reviewed_regional_fiscal,build_regional_fiscal_payload)
from scripts.activate_regional_fiscal_snapshot import protected_digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'pboc_data.db')
    parser.add_argument('--snapshot-dir',type=Path,default=ROOT/'data/regional_fiscal_reviewed')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261015')
    args=parser.parse_args()
    if not args.database.is_file():raise ValueError('Refuse to create a substitute production database.')
    output=args.output_dir/('fiscal-visual-staging-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True,exist_ok=False)
    database=output/'ISOLATED_NOT_FOR_PRODUCTION_ACTIVATION.db'
    with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        source.row_factory=sqlite3.Row
        before=protected_digest(source,set())
        rows=[dict(r) for r in source.execute('SELECT * FROM regional_fiscal_observations ORDER BY id')]
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory=sqlite3.Row;ensure_regional_fiscal_table(conn)
        columns=[r[1] for r in conn.execute('PRAGMA table_info(regional_fiscal_observations)')]
        if any(set(r)!=set(columns) for r in rows):raise ValueError('Fiscal schema changed; do not silently omit columns.')
        conn.executemany('INSERT INTO regional_fiscal_observations ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',[[r[k] for k in columns] for r in rows])
        conn.commit()
        first=sync_reviewed_regional_fiscal(conn,args.snapshot_dir);conn.commit()
        if first['errors'] or first['inserted']!=46 or first['updated']!=0:
            raise ValueError('Expected46 new keys and no revisions; current production may have changed.')
        first_digest=protected_digest(conn,set())
        payload=build_regional_fiscal_payload(conn)
        repeat=sync_reviewed_regional_fiscal(conn,args.snapshot_dir);conn.commit()
        if repeat['errors'] or repeat['inserted'] or repeat['updated'] or protected_digest(conn,set())!=first_digest:
            raise ValueError('Isolated idempotency or full-field preservation failed.')
    actual=[r for r in payload['rows'] if r['country_code']=='CN' and r['government_scope']=='province_total' and r['period']=='2025' and r['data_status']!='derived']
    coverage={code:len({r['region_code'] for r in actual if r['indicator_code']==code}) for code in
              ('general_budget_revenue','general_budget_expenditure','tax_revenue','gov_fund_revenue','gov_fund_expenditure','land_transfer_revenue','debt_outstanding','general_debt_outstanding','special_debt_outstanding')}
    if coverage!={'general_budget_revenue':30,'general_budget_expenditure':30,'tax_revenue':21,'gov_fund_revenue':12,'gov_fund_expenditure':12,'land_transfer_revenue':8,'debt_outstanding':10,'general_debt_outstanding':7,'special_debt_outstanding':31}:
        raise ValueError('The staged fiscal coverage does not match the reviewed46-observation increment.')
    for code,value in [('340000',1306.13/1629.14*100),('500000',1369/1593*100)]:
        ratio=next(r for r in payload['rows'] if r['region_code']==code and r['period']=='2025' and r['indicator_code']=='land_dependency')
        if ratio['value']!=round(value,4) or ratio['data_status']!='derived':raise ValueError('Staged land dependency mismatch.')
    with closing(sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro',uri=True)) as source:
        source.row_factory=sqlite3.Row;after=protected_digest(source,set())
    if before!=after:raise ValueError('Production fiscal table changed during isolated verification; inspect concurrent work.')
    payload.update(preview_only=True,activation_permitted=False,
                   preview_notice='隔离预演：46条候选尚未写入正式库，不是生产页面验收。')
    (output/'regional_payload.json').write_bytes((json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    audit={'checked_at':datetime.now(timezone.utc).isoformat(),'phase':'isolated_verified_production_not_applied',
           'activation_permitted':False,'production_writes':0,'copied_table':'regional_fiscal_observations',
           'baseline_rows':len(rows),'production_before':before,'production_after':after,'production_unchanged':True,
           'first_import':first,'repeat_import':repeat,'isolated_coverage_2025':coverage,
           'database':database.name,'payload':'regional_payload.json','live_ui_acceptance':False}
    (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),'phase':audit['phase'],'isolated_inserted':first['inserted'],
                      'repeat_inserted':repeat['inserted'],'production_unchanged':True,'coverage':coverage},ensure_ascii=False))


if __name__=='__main__':main()
