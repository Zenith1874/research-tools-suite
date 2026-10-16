#!/usr/bin/env python3
"""Archive one bounded public NBS price-search response without writing observations."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.china_macro_service import NBS_SEARCH_API, NBS_SEARCH_SITE_CODE, UA


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--kind', choices=('cpi', 'ppi'), required=True)
    parser.add_argument('--page', type=int, choices=(1, 2), default=1)
    parser.add_argument('--key-place', choices=('0', '1'), default='1')
    parser.add_argument('--date-filtered', action='store_true',
                        help='Use public search UI fields for original publication dates.')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'outputs/macro_refresh_20261015')
    args = parser.parse_args()
    if not 2010 <= args.year <= datetime.now().year:
        parser.error('Use an in-scope historical year, not an unverified future period.')
    query = {'cpi':'居民消费价格', 'ppi':'工业生产者价格'}[args.kind]
    form = {'siteCode':NBS_SEARCH_SITE_CODE, 'qt':f'{args.year}年 {query}',
            'page':args.page, 'pageSize':20, 'keyPlace':args.key_place, 'sort':'relevance'}
    if args.date_filtered:
        form.update(timeOption=2, startDateStr=f'{args.year}-01-01',
                    endDateStr=f'{args.year+1}-02-28')
    output = args.output_dir/('price-discovery-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    output.mkdir(parents=True, exist_ok=False)
    audit = {'captured_at':datetime.now(timezone.utc).isoformat(), 'source_url':NBS_SEARCH_API,
             'request_form':form, 'network_requests':1, 'database_written':False, 'tls_verified':True}
    try:
        response = requests.post(NBS_SEARCH_API, data=form,
                                 headers={**UA, 'Referer':'https://www.stats.gov.cn/search/s'},
                                 timeout=12, stream=True)
        try:
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > 8*1024*1024:
                    raise ValueError('Public response exceeded the bounded 8-MB archive limit.')
            (output/'response.json').write_bytes(content)
            audit.update(http_status=response.status_code, raw_path='response.json',
                         raw_sha256=hashlib.sha256(content).hexdigest(), bytes=len(content))
            response.raise_for_status()
            payload = json.loads(content)
            if payload.get('ok') is not True:
                raise ValueError('The public search did not return an accepted JSON response.')
            candidates = []
            for item in payload.get('resultDocs') or []:
                doc = item.get('data', item)
                candidates.append({'source_title':BeautifulSoup(str(doc.get('title') or ''),
                                   'html.parser').get_text('', strip=True),
                                   'source_url':doc.get('url') or ''})
            audit.update(status='discovery_only_pending_article_review',
                         total_hits=payload.get('totalHits'), candidates=candidates)
        finally:
            response.close()
    except Exception as exc:
        audit.update(status='incomplete', error=str(exc))
    (output/'audit.json').write_bytes((json.dumps(audit, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps({**audit, 'output_dir':str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
