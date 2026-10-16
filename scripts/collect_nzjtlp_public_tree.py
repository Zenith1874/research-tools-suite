#!/usr/bin/env python3
"""Preserve observed public volume/issue media-tree nodes without executing JS."""

import argparse
import ast
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def literal_html(javascript):
    literals = re.findall(r"document\.write\((\'(?:\\.|[^\'\\])*\'|\"(?:\\.|[^\"\\])*\")\);", javascript)
    return ''.join(ast.literal_eval(literal) for literal in literals)


def collect(root_file, output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'root_file': str(root_file),
        'root_sha256': hashlib.sha256(root_file.read_bytes()).hexdigest(), 'root_node': '58076',
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'workers': 1, 'request_delay_seconds': 1, 'javascript_executed': False,
        'article_database_writes': 0, 'full_text_reviewed': False}
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:json.dump(manifest, stream, indent=2)
    queue = [('58076', 'New Zealand Journal of Taxation Law and Policy')]
    seen, nodes, links = set(), [], {}
    while queue:
        identifier, label = queue.pop(0)
        if identifier in seen:continue
        seen.add(identifier)
        url = 'https://livepages.thomsonreuters.com.au/mediaTree/' + identifier
        if identifier == '58076':
            raw = root_file.read_bytes();status = 200
        else:
            response = requests.get(url, headers={'User-Agent': 'ResearchTools-PublicBibliographyAudit/1.0'}, timeout=(15, 35))
            raw, status = response.content, response.status_code
        path = output / (identifier + '.js')
        with path.open('xb') as stream:stream.write(raw)
        record = {'node_id': identifier, 'observed_label': label, 'url': url, 'http_status': status,
                  'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        nodes.append(record)
        if status != 200:continue
        html = literal_html(raw.decode('utf-8-sig'))
        with (output / (identifier + '.rendered_source.html')).open('x', encoding='utf-8') as stream:stream.write(html)
        soup = BeautifulSoup(html, 'html.parser')
        for anchor in soup.select('a[href]'):
            target = urljoin('https://livepages.thomsonreuters.com.au/', anchor['href'])
            parsed = urlparse(target);text = anchor.get_text(' ', strip=True)
            tree = parse_qs(parsed.query).get('id', [''])[0]
            match = re.fullmatch(r'/mediaTree/(\d+)', tree)
            if match and text.lower().startswith('vol') and match[1] not in seen:
                queue.append((match[1], text))
            elif parsed.hostname == 'livepages.thomsonreuters.com.au' and (parsed.path.lower().endswith('.pdf') or parsed.path.startswith('/media/')):
                links.setdefault(target, {'url': target, 'label': text, 'source_node': identifier,
                    'source_path': str(path), 'source_sha256': record['sha256']})
        print(json.dumps({'node': identifier, 'seen': len(seen), 'queued': len(queue), 'document_links': len(links)}), flush=True)
        time.sleep(1)
    report = {'finished_at': datetime.now(timezone.utc).isoformat(), 'nodes': nodes,
        'observed_document_links': len(links), 'article_database_writes': 0, 'full_text_reviewed': False,
        'public_navigation_only': True, 'issue_article_census_proven': False}
    for name, value in [('report.json', report), ('document_links.json', list(links.values()))]:
        with (output / name).open('x', encoding='utf-8') as stream:json.dump(value, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root-file', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.root_file.resolve(), args.output_dir.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != 'nodes'}, indent=2))
