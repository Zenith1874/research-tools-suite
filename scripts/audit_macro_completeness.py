#!/usr/bin/env python3
"""Produce a read-only, per-series and per-module macro acceptance receipt."""
import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.macro_data_quality_service import build_macro_data_quality

TABLES=('monthly_data','financial_observations','china_macro_observations','us_macro_observations',
        'china_rates_observations','pboc_balance_sheet_observations','fiscal_debt_observations',
        'fiscal_budget_observations','housing_city_observations','housing_national_observations',
        'gdp_national_observations','gdp_region_observations','regional_fiscal_observations','city_indicator_observations')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=ROOT/'pboc_data.db')
    p.add_argument('--output-dir',type=Path,default=ROOT/'outputs'/'macro_completeness')
    p.add_argument('--skip-quick-check',action='store_true',
                   help='Profile macro tables without repeating the expensive whole-DB integrity scan.')
    args=p.parse_args()
    if not args.db.is_file():p.error('Database must exist; this is a read-only audit.')
    out=args.output_dir/('acceptance-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    quality={country:build_macro_data_quality(str(args.db),country) for country in ('china','us')}
    modules=[]
    c=sqlite3.connect(f'file:{args.db.resolve().as_posix()}?mode=ro',uri=True)
    c.row_factory=sqlite3.Row
    for table in TABLES:
        columns={row[1] for row in c.execute(f'PRAGMA table_info({table})')}
        if not columns:
            modules.append({'table':table,'status':'missing_table'})
            continue
        period=next((key for key in ('period','month','period_end','year') if key in columns),None)
        select='COUNT(*) records'+(f',MIN({period}) first,MAX({period}) last' if period else '')
        result=dict(c.execute(f'SELECT {select} FROM {table}').fetchone())
        if period and 'value' in columns:
            observed=dict(c.execute(f'SELECT COUNT(value) nonnull_records, MIN({period}) first_observed, '
                f'MAX({period}) last_observed FROM {table} WHERE value IS NOT NULL').fetchone())
            result.update(observed)
            if 'data_status' in columns:
                result['last_official_observed']=c.execute(
                    f'SELECT MAX({period}) FROM {table} WHERE value IS NOT NULL AND data_status LIKE ?',
                    ('official%',)).fetchone()[0]
        result.update(table=table,period_column=period,scope='Raw stored rows, including retained source vintages; not unique comparable periods.')
        modules.append(result)
    invalid=[dict(row) for row in c.execute("SELECT indicator_code,period,original_value,data_status,missing_reason,source_url "
                                           "FROM china_macro_observations WHERE data_status LIKE 'invalidated_%' ORDER BY indicator_code,period")]
    preserved=c.execute('SELECT COUNT(*) FROM china_macro_observations WHERE original_value IS NOT NULL').fetchone()[0]
    check='not_rerun' if args.skip_quick_check else c.execute('PRAGMA quick_check').fetchone()[0]
    duplicates=c.execute('SELECT COUNT(*) FROM (SELECT indicator_code,period FROM china_macro_observations '
                         'GROUP BY indicator_code,period HAVING COUNT(*)>1)').fetchone()[0]
    c.close()
    receipt={'captured_at':datetime.now().astimezone().isoformat(),'db_path':str(args.db.resolve()),
             'quality':quality,'module_inventory':modules,'remaining_invalid_records':invalid,
             'preserved_original_values':preserved,'duplicate_china_keys':duplicates,'quick_check':check,
             'scope_note':'Catalog coverage is not total macro-domain coverage or complete history. Module counts are raw rows, not comparable samples.'}
    (out/'audit.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[{'country':country,**row,'missing_periods':'|'.join(row['missing_periods'])}
          for country,q in quality.items() for row in q['indicators'].values()]
    with (out/'indicator_coverage.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps({'output_dir':str(out),'quick_check':check,'duplicate_china_keys':duplicates,
                      'remaining_invalid_records':len(invalid),'preserved_original_values':preserved,
                      'catalog':{k:{'registered':q['registered_series'],'with_data':q['series_with_data'],
                                    'missing':q['missing_series']} for k,q in quality.items()}},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
