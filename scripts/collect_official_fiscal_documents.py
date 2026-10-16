#!/usr/bin/env python3
"""Archive a bounded, already discovered list of public official fiscal documents."""
import argparse
import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.fiscal_source_authority import official_fiscal_download_url
LIMIT=16*1024*1024


def official_url(url, source_class=None):
    return official_fiscal_download_url(url,source_class)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--replay-dir',type=Path)
    parser.add_argument('--replay-only',action='store_true')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'outputs/macro_refresh_20261013')
    args=parser.parse_args()
    config=json.loads(args.sources.read_text(encoding='utf-8'))
    if config['schema_version']!=1 or not 1<=len(config['documents'])<=6:raise ValueError('Use one to six discovered official documents per batch.')
    if args.replay_only and not args.replay_dir:parser.error('--replay-only requires --replay-dir')
    output=args.output_dir/('fiscal-documents-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True,exist_ok=False)
    cached={}
    if args.replay_dir:
        old=json.loads((args.replay_dir/'audit.json').read_text(encoding='utf-8'))
        cached={r['source_url']:r for r in old['source_manifest']}
    session=requests.Session();manifest=[];errors=[];network=0
    for document in config['documents']:
        url=document['source_url']
        source_class=document.get('source_class','government_website')
        if not official_url(url,source_class):raise ValueError('Only exact public government links or the declared primary issuer filing are accepted.')
        if document['format'] not in ('pdf','html','png') or not document['id'].replace('-','').isalnum():raise ValueError('Invalid declared format or document identity.')
        name=document['id']+'.'+document['format']
        try:
            if url in cached:
                old=cached[url];path=(args.replay_dir/old['raw_path']).resolve()
                if not path.is_relative_to(args.replay_dir.resolve()):raise ValueError('Cached path escaped its run.')
                content=path.read_bytes()
                if hashlib.sha256(content).hexdigest()!=old['raw_sha256']:raise ValueError('Cached document hash changed.')
                record={**old,'raw_path':name,'replayed_at':datetime.now(timezone.utc).isoformat()}
            else:
                if args.replay_only:raise ValueError('No cached document; zero-network replay remains incomplete.')
                network+=1
                response=session.get(url,timeout=20,stream=True,headers={'User-Agent':'Mozilla/5.0'})
                try:
                    response.raise_for_status()
                    if not official_url(response.url,source_class):raise ValueError('Unexpected source-authority redirect.')
                    data=bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data)>LIMIT:raise ValueError('Document exceeded the proposed 16-MB limit.')
                    content=bytes(data)
                    if document['format']=='pdf' and not content.startswith(b'%PDF-'):raise ValueError('Observed PDF URL returned no PDF.')
                    if document['format']=='html' and content.startswith(b'%PDF-'):raise ValueError('Unexpected PDF for declared HTML source.')
                    if document['format']=='png' and not content.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Observed PNG URL returned no PNG.')
                    record={**document,'resolved_url':response.url,'raw_path':name,'bytes':len(content),
                            'raw_sha256':hashlib.sha256(content).hexdigest(),'retrieved_at':datetime.now(timezone.utc).isoformat(),
                            'access_type':'complete_archived_'+document['format'],'tls_verified':True}
                finally:response.close()
            (output/name).write_bytes(content);manifest.append(record)
            with (output/'manifest.jsonl').open('ab') as handle:handle.write((json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8'))
            print(document['id']+': archived',flush=True)
        except Exception as exc:
            errors.append({'source_url':url,'id':document['id'],'error':str(exc)});print(document['id']+': incomplete',flush=True)
    audit={'source_manifest':manifest,'errors':errors,'network_requests':network,'status':'raw_archived_pending_review' if not errors else 'incomplete'}
    (output/'audit.json').write_bytes((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    print(json.dumps({'output_dir':str(output),'files':len(manifest),'bytes':sum(r['bytes'] for r in manifest),'errors':errors},ensure_ascii=False))


if __name__=='__main__':main()
