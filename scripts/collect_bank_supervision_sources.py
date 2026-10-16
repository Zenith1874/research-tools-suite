#!/usr/bin/env python3
"""Archive public NFRA table metadata and images for independent cell review."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doc-ids', required=True)
    parser.add_argument('--replay-dir', type=Path, help='Reuse already archived metadata without another network request.')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'outputs' / 'macro_refresh_20261010')
    args = parser.parse_args()
    ids = [value.strip() for value in args.doc_ids.split(',')]
    if len(ids) > 12 or not all(re.fullmatch(r'\d{6,8}', value) for value in ids):
        parser.error('Supply up to 12 document IDs already discovered from public NFRA links.')
    out = args.output_dir / ('bank-sources-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    manifest, records, errors = [], [], []

    def archive(url, path):
        time.sleep(0.35)
        response = session.get(url, timeout=18)
        response.raise_for_status()
        if urlsplit(response.url).hostname != 'www.nfra.gov.cn':
            raise ValueError('Public source redirected outside the verified NFRA host.')
        path.write_bytes(response.content)
        item = {'source_url': url, 'resolved_url': response.url,
                'retrieved_at': datetime.now().astimezone().isoformat(),
                'raw_path': path.relative_to(out).as_posix(),
                'raw_sha256': hashlib.sha256(response.content).hexdigest()}
        manifest.append(item)
        with (out / 'manifest.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        return response

    for doc_id in ids:
        try:
            url = f'https://www.nfra.gov.cn/cn/static/data/DocInfo/SelectByDocId/data_docId={doc_id}.json'
            cached = args.replay_dir / f'{doc_id}.json' if args.replay_dir else None
            if cached and cached.is_file():
                previous = json.loads((args.replay_dir / 'audit.json').read_text(encoding='utf-8'))
                prior = next(item for item in previous['source_manifest'] if item['raw_path'] == cached.name)
                content = cached.read_bytes()
                if hashlib.sha256(content).hexdigest() != prior['raw_sha256']:
                    raise ValueError('Archived metadata hash changed; replay refused.')
                (out / cached.name).write_bytes(content)
                manifest.append({**prior, 'replayed_at': datetime.now().astimezone().isoformat()})
                response = requests.Response()
                response._content = content
            else:
                response = archive(url, out / f'{doc_id}.json')
            payload = response.json()
            data = payload.get('data', payload)
            if not isinstance(data, dict):
                raise ValueError('Unexpected public document schema.')
            body = data.get('docClob') or data.get('docContent') or ''
            if not body:
                raise ValueError('Official document body is absent; table review cannot proceed.')
            images = []
            for index, img in enumerate(BeautifulSoup(body, 'html.parser').find_all('img'), 1):
                target = urljoin('https://www.nfra.gov.cn/', img.get('src') or '')
                if urlsplit(target).hostname != 'www.nfra.gov.cn':
                    continue
                suffix = Path(urlsplit(target).path).suffix or '.image'
                path = out / f'{doc_id}-{index}{suffix}'
                archive(target, path)
                images.append({'source_url': target, 'path': path.relative_to(out).as_posix()})
            attachments=[]
            for index,item in enumerate(data.get('attachmentInfoVOList') or [],1):
                relative=item.get('urlOtherName')
                if not relative:
                    continue
                target=urljoin('https://www.nfra.gov.cn/',relative)
                suffix=Path(urlsplit(target).path).suffix.lower()
                if urlsplit(target).hostname!='www.nfra.gov.cn' or suffix not in ('.xls','.xlsx'):
                    continue
                path=out/f'{doc_id}-attachment-{index}{suffix}'
                archive(target,path)
                attachments.append({'source_url':target,'title':item.get('title'),
                                    'path':path.relative_to(out).as_posix()})
            record = {'doc_id': doc_id, 'title': data.get('docTitle') or data.get('docSubtitle'),
                      'publish_date': data.get('publishDate'), 'edit_date': data.get('docEditdate'),
                      'images': images, 'attachments':attachments,'metadata_keys': list(data), 'status': 'archived_not_yet_cell_reviewed'}
            records.append(record)
            print(json.dumps({key: value for key, value in record.items() if key != 'metadata_keys'}, ensure_ascii=False), flush=True)
        except Exception as exc:
            errors.append({'doc_id': doc_id, 'error': str(exc)})
    (out / 'audit.json').write_text(json.dumps({'records': records, 'source_manifest': manifest,
                                               'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output_dir': str(out), 'records': len(records), 'errors': errors}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
