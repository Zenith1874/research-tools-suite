#!/usr/bin/env python3
"""Archive the latest official SAFE BOP/IIP workbook links without changing them."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin,urlsplit

import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
PAGES={'bop':'https://www.safe.gov.cn/safe/2019/0627/13519.html',
       'iip':'https://www.safe.gov.cn/safe/2019/0627/13520.html'}


def main():
    out=ROOT/'outputs'/'macro_refresh_20261010'/('safe-accounts-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True,exist_ok=False)
    session=requests.Session();manifest=[];errors=[]
    def archive(url,path):
        response=session.get(url,timeout=20,headers={'User-Agent':'Mozilla/5.0'})
        response.raise_for_status()
        if urlsplit(response.url).hostname!='www.safe.gov.cn':
            raise ValueError('Official source redirected outside SAFE; no substitute is used.')
        path.write_bytes(response.content)
        record={'source_url':url,'resolved_url':response.url,
                'retrieved_at':datetime.now().astimezone().isoformat(),
                'raw_path':path.relative_to(out).as_posix(),
                'raw_sha256':hashlib.sha256(response.content).hexdigest()}
        manifest.append(record)
        with (out/'manifest.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(record,ensure_ascii=False)+'\n')
        return response
    for kind,url in PAGES.items():
        try:
            response=archive(url,out/f'{kind}-page.html');response.encoding='utf-8'
            links=[urljoin(url,a['href']) for a in BeautifulSoup(response.text,'html.parser').find_all('a',href=True)
                   if urlsplit(urljoin(url,a['href'])).path.lower().endswith('.xlsx')]
            if len(set(links))!=1:
                raise ValueError('The official page does not expose exactly one workbook.')
            archive(links[0],out/f'{kind}.xlsx')
        except Exception as exc:
            errors.append({'kind':kind,'error':str(exc)})
    (out/'audit.json').write_text(json.dumps({'source_manifest':manifest,'errors':errors,
                'status':'raw_archived_not_yet_parsed'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'output_dir':str(out),'files':len(manifest),'errors':errors},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
