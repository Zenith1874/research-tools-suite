#!/usr/bin/env python3
"""Read-only source-cell, currency, frequency and accounting-identity audit."""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.safe_account_service import ACCOUNT_INDICATORS,parse_safe_workbook


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--db',type=Path,default=ROOT/'pboc_data.db')
    parser.add_argument('--output-root',type=Path,default=ROOT/'outputs'/'macro_refresh_20261012')
    args=parser.parse_args()
    out=args.output_root/('safe-audit-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    conn=sqlite3.connect(f'file:{args.db.resolve().as_posix()}?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    rows=[dict(row) for row in conn.execute("SELECT * FROM china_macro_observations WHERE indicator_code LIKE 'CN_SAFE_BOP_%' OR indicator_code LIKE 'CN_SAFE_IIP_%'")]
    stored={(row['indicator_code'],row['period']):row for row in rows}
    manifest=json.loads((args.source_dir/'audit.json').read_text(encoding='utf-8'))['source_manifest']
    source_checks=[];cell_comparisons=[];sheets=[]
    for kind in ('bop','iip'):
        record=next(row for row in manifest if row['raw_path']==kind+'.xlsx')
        content=(args.source_dir/record['raw_path']).read_bytes()
        actual=hashlib.sha256(content).hexdigest()
        source_checks.append({'kind':kind,'expected_sha256':record['raw_sha256'],'actual_sha256':actual,'match':actual==record['raw_sha256']})
        if actual!=record['raw_sha256']:raise ValueError('Source workbook hash changed.')
        parsed=parse_safe_workbook(content,kind);sheets.extend(parsed['sheets'])
        for row in parsed['observations']:
            old=stored.get((row['indicator_code'],row['period']))
            cell_comparisons.append({'code':row['indicator_code'],'period':row['period'],
                'sheet':row['sheet'],'cell':row['cell'],
                'matches':bool(old and old['value']==row['value']),
                'unit_matches':bool(old and (old['unit'],old['frequency'])==ACCOUNT_INDICATORS[row['indicator_code']][1:]),
                'source_url':old['source_url'] if old else None})
    identity=[]
    annual_quarter=[]
    def values(codes):
        periods=sorted(set.intersection(*[{period for code,period in stored if code==name} for name in codes]))
        return [(period,[stored[(name,period)]['value'] for name in codes]) for period in periods]
    for currency in ('CNY','USD'):
        for suffix in ('A','Q'):
            codes=[f'CN_SAFE_BOP_{stem}_{currency}_{suffix}' for stem in ('CA','GOODS_SERVICES','PRIMARY_INCOME','SECONDARY_INCOME')]
            diffs=[(period,round(numbers[0]-sum(numbers[1:]),10)) for period,numbers in values(codes)]
            identity.append({'name':f'CA = goods/services + primary + secondary / {currency}/{suffix}',
                'n_compared':len(diffs),'max_abs_residual':max((abs(diff) for _,diff in diffs),default=None),
                'residuals_over_one_original_unit':[(period,diff) for period,diff in diffs if abs(diff)>1]})
        for stem in ('CA','FINANCIAL','DI'):
            pairs=[]
            for (code,year),row in stored.items():
                if code!=f'CN_SAFE_BOP_{stem}_{currency}_A':continue
                quarter=[stored.get((f'CN_SAFE_BOP_{stem}_{currency}_Q',year+f'-{month:02d}')) for month in (3,6,9,12)]
                if all(quarter):pairs.append((year,round(row['value']-sum(item['value'] for item in quarter),10)))
            annual_quarter.append({'code':stem,'currency':currency,'n_complete_years':len(pairs),
                'max_abs_residual':max((abs(diff) for _,diff in pairs),default=None),
                'residuals_over_one_original_unit':[(year,diff) for year,diff in pairs if abs(diff)>1]})
    for legacy in ('','LEGACY_'):
        for suffix in ('A','Q'):
            codes=[f'CN_SAFE_IIP_{legacy}{stem}_USD_{suffix}' for stem in ('NET','ASSETS','LIABILITIES')]
            diffs=[(period,round(numbers[0]-numbers[1]+numbers[2],10)) for period,numbers in values(codes)]
            identity.append({'name':f'IIP net = assets - liabilities / {legacy or "modern"}/{suffix}',
                'n_compared':len(diffs),'max_abs_residual':max((abs(diff) for _,diff in diffs),default=None),
                'residuals_over_one_original_unit':[(period,diff) for period,diff in diffs if abs(diff)>1]})
    coverage=[{'code':code,'frequency':meta[2],'unit':meta[1],
        'n_obs':sum(key[0]==code for key in stored),
        'start':min((key[1] for key in stored if key[0]==code),default=None),
        'end':max((key[1] for key in stored if key[0]==code),default=None)} for code,meta in ACCOUNT_INDICATORS.items()]
    result={'captured_at':datetime.now().astimezone().isoformat(),'scope':'Original official source workbook cells versus current summary DB; no FX conversion or time disaggregation.',
        'n_registered':len(ACCOUNT_INDICATORS),'n_summary_observations':len(rows),
        'source_hash_checks':source_checks,'n_source_cells_compared':len(cell_comparisons),
        'all_summary_cells_match':all(row['matches'] and row['unit_matches'] for row in cell_comparisons),
        'raw_numeric_cells':conn.execute('SELECT COUNT(*) FROM safe_account_cells').fetchone()[0],
        'workbook_versions':conn.execute('SELECT COUNT(*) FROM safe_account_versions').fetchone()[0],
        'revision_records':conn.execute('SELECT COUNT(*) FROM safe_account_revisions').fetchone()[0],
        'accounting_identities':identity,'annual_vs_four_quarters':annual_quarter,'coverage':coverage,'sheet_notes':sheets,
        'tolerance_note':'Residuals are shown in each original source unit; official rounding or source vintage differences are not silently corrected.'}
    conn.close()
    (out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'source_cell_comparisons.json').write_text(json.dumps(cell_comparisons,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'output_dir':str(out),'summary_cells':len(rows),'all_summary_cells_match':result['all_summary_cells_match'],
        'identity_residuals':identity,'annual_quarter_residuals':annual_quarter},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
