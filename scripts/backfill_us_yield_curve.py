#!/usr/bin/env python3
"""Archive and backfill only the six missing maturities actually published in H.15."""
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.us_macro_service import update_us_macro

CODES=('DGS1MO','DGS6MO','DGS1','DGS3','DGS7','DGS20')


def main():
    out=ROOT/'outputs'/'macro_refresh_20261010'/('us-curve-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    conn=sqlite3.connect(f'file:{(ROOT/"pboc_data.db").as_posix()}?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    before=[dict(row) for row in conn.execute(
        'SELECT indicator_code,COUNT(*) n,MIN(period) first,MAX(period) last FROM us_macro_observations '
        'WHERE indicator_code IN ('+','.join('?'*len(CODES))+') GROUP BY indicator_code',CODES)]
    conn.close()
    (out/'before.json').write_text(json.dumps(before,indent=2),encoding='utf-8')
    result=update_us_macro(str(ROOT/'pboc_data.db'),codes=CODES,archive_dir=out/'raw')
    manifest=[{'source_url':f'https://fred.stlouisfed.org/series/{path.stem}',
               'raw_path':path.relative_to(out).as_posix(),
               'raw_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
              for path in (out/'raw').glob('*.csv')]
    receipt={'captured_at':datetime.now().astimezone().isoformat(),'codes':CODES,
             'result':result,'source_manifest':manifest,
             'notes':['Only newly registered tenors are fetched; existing 62 series are not repeated.',
                      'Official H.15 yields are daily percent values, not forecasts or monthly rates.']}
    (out/'audit.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output_dir':str(out),**result},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
