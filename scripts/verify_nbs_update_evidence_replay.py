#!/usr/bin/env python3
"""Offline replay of two real archived releases through the normal updater, never production writes."""
import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.china_macro_service import update_china_macro,macro_ingestion_runtime
from services.nbs_release_evidence import archive_nbs_release
from scripts.activate_bank_history_year import protected_digest


def production_digest(path):
    if not path.is_file():raise ValueError('Refuse to create a substitute production database.')
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.row_factory=sqlite3.Row
        return protected_digest(conn,set())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,default=ROOT/'data/nbs_price_metadata_review_20261015.json')
    parser.add_argument('--production-db',type=Path,default=ROOT/'pboc_data.db')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261015')
    args=parser.parse_args()
    review=json.loads(args.review.read_text(encoding='utf-8'));sources={}
    for kind in ('cpi','ppi'):
        selected=[d for d in review['documents'] if d.get('kind','ppi')==kind and d['period']=='2026-09']
        if len(selected)!=1:raise ValueError('Use one exact reviewed source per real release kind.')
        document=selected[0];found=[]
        for directory in review['source_dirs']:
            manifest=json.loads((Path(directory)/'audit.json').read_text(encoding='utf-8'))
            for record in manifest['source_manifest']:
                if record['id']==document['id']:found.append((Path(directory),record))
        if len(found)!=1:raise ValueError('The replay needs exactly one immutable original per release.')
        directory,record=found[0];path=(directory/record['raw_path']).resolve()
        if not path.is_relative_to(directory.resolve()):raise ValueError('Source path escaped the archive.')
        content=path.read_bytes()
        if hashlib.sha256(content).hexdigest()!=document['raw_sha256'] or record['raw_sha256']!=document['raw_sha256']:
            raise ValueError('Original source bytes changed.')
        sources[document['source_url']]={'kind':kind,'document':document,'record':record,
                                       'content':content,'parent_ref':str(directory/'audit.json')}
    before=production_digest(args.production_db)
    output=args.output_dir/('nbs-ingestion-replay-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True,exist_ok=False)
    database=output/'ISOLATED_REPLAY_NOT_FOR_ACTIVATION.db';raw_root=output/'raw'

    def get(url,**kwargs):
        if url not in sources:raise AssertionError('Unexpected network target in an offline replay.')
        response=requests.Response();response.status_code=200;response._content=sources[url]['content']
        response._content_consumed=True
        response.url=url;response.encoding='utf-8';return response

    def discover(kind,*arguments,**kwargs):
        source=next(s for s in sources.values() if s['kind']==kind);doc=source['document']
        return {doc['period']:(doc['source_url'],doc['source_title'])}

    def capture(content,url,**kwargs):
        source=sources[url]
        return archive_nbs_release(content,url,**kwargs,access_mode='archived_response_replay',
                    source_retrieved_at=source['record']['retrieved_at'],replay_parent_ref=source['parent_ref'])

    with patch('services.china_macro_service.requests.get',side_effect=get) as input_reader, \
         patch('services.china_macro_service.discover_releases',side_effect=discover), \
         patch('services.china_macro_service.sync_annual_macro_snapshots',return_value=0), \
         patch('services.china_macro_service.archive_nbs_release',side_effect=capture):
        first=update_china_macro(database,start_year=2026,kinds=('cpi','ppi'),sleep_seconds=0,archive_root=raw_root)
        if not first['success'] or first['errors'] or first['records_upserted']!=19:
            raise ValueError('Normal updater did not persist the19 reviewed source fields.')
        first_read_calls=input_reader.call_count
        with closing(sqlite3.connect(database)) as conn:
            conn.row_factory=sqlite3.Row
            initial_rows=[dict(r) for r in conn.execute('SELECT * FROM china_macro_observations ORDER BY id')]
        input_reader.reset_mock()
        second=update_china_macro(database,start_year=2026,kinds=('cpi','ppi'),sleep_seconds=0,archive_root=raw_root)
        if second['records_upserted']!=0 or input_reader.call_count!=0:
            raise ValueError('Replay must skip complete observations without another fetch.')
    with closing(sqlite3.connect(database)) as conn:
        conn.row_factory=sqlite3.Row
        rows=[dict(r) for r in conn.execute('SELECT * FROM china_macro_observations ORDER BY id')]
    if rows!=initial_rows:raise ValueError('Repeat update changed complete rows.')
    for source in sources.values():
        doc=source['document']
        for code,value in doc['expected_values'].items():
            row=next(r for r in rows if r['indicator_code']==code)
            if (row['value']!=value or row['raw_sha256']!=doc['raw_sha256'] or
                    row['release_date']!='2026-10-14' or row['retrieved_at']!=source['record']['retrieved_at']):
                raise ValueError('Isolated values or original evidence fields differ from the source.')
    receipts=[]
    for path in raw_root.glob('*/receipt.json'):
        record=json.loads(path.read_text(encoding='utf-8'))
        if record['access_mode']!='archived_response_replay':raise ValueError('Replay cannot claim a fresh HTTP acquisition.')
        if hashlib.sha256((path.parent/record['raw_path']).read_bytes()).hexdigest()!=record['raw_sha256']:
            raise ValueError('Replay original byte hash differs.')
        receipts.append(str(path.relative_to(output)))
    if len(receipts)!=2:raise ValueError('Expect exactly two real-source evidence captures.')
    after=production_digest(args.production_db)
    if after!=before:raise ValueError('Production macro rows changed during an isolated replay.')
    audit={'captured_at':datetime.now(timezone.utc).isoformat(),'access_mode':'archived_response_replay',
           'network_requests':0,'production_writes':0,'activation_permitted':False,
           'production_before':before,'production_after':after,'production_unchanged':True,
           'source_kinds':['cpi','ppi'],'source_fields_verified':19,'simulated_response_reads':first_read_calls,
           'normal_update':first,'repeat_update':second,'rows_identical_on_repeat':True,
           'receipts':receipts,'database':'ISOLATED_REPLAY_NOT_FOR_ACTIVATION.db',
           'loaded_runtime':macro_ingestion_runtime(),
           'scope':'Real archived bytes, parser, capture and SQL are exercised. HTTP/discovery/annual sync are controlled substitutes; not a production task or live-source acceptance.'}
    (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),'verified_fields':19,'receipts':2,'network_requests':0,
                      'production_unchanged':True,'repeat_upserts':second['records_upserted']},ensure_ascii=False))


if __name__=='__main__':main()
