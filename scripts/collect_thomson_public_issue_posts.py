#!/usr/bin/env python3
"""Reconcile public publisher issue posts from the observed WordPress API."""

import argparse
import gzip
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


def save(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)


def collect(navigation_dir, output):
    schema_file = navigation_dir / 'api_schema_receipt.json'
    category_file = navigation_dir / 'categories_receipt.json'
    schema = json.loads(schema_file.read_text(encoding='utf-8'))
    categories = json.loads(category_file.read_text(encoding='utf-8'))['selected']
    index = Path(schema['api_index_path'])
    if hashlib.sha256(index.read_bytes()).hexdigest() != schema['api_index_sha256']:
        raise ValueError('The observed public API schema changed')
    if '/wp/v2/posts' not in schema['observed_routes'] or not categories:
        raise ValueError('No documented public post route or selected journal categories')
    output.mkdir(parents=True, exist_ok=False)
    save(output / 'manifest.json', {'created_at': datetime.now(timezone.utc).isoformat(),
        'schema_receipt': str(schema_file), 'schema_receipt_sha256': hashlib.sha256(schema_file.read_bytes()).hexdigest(),
        'categories_receipt': str(category_file), 'categories_receipt_sha256': hashlib.sha256(category_file.read_bytes()).hexdigest(),
        'categories': categories, 'no_blog_date_used_as_issue_year': True,
        'article_database_writes': 0, 'full_text_reviewed': False,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    url = schema['url'].rstrip('/') + '/wp/v2/posts'
    rows, pages, expected, page_count = {}, [], None, None
    number = 1
    while True:
        params = {'categories': ','.join(str(row['id']) for row in categories), 'per_page': 100, 'page': number,
                  'context': 'view', '_fields': 'id,date,date_gmt,modified_gmt,link,title,content,categories'}
        response = requests.get(url, params=params,
            headers={'User-Agent': 'ResearchTools-PublicBibliographyAudit/1.0'}, timeout=(15, 45))
        response.raise_for_status()
        count, total_pages = int(response.headers['X-WP-Total']), int(response.headers['X-WP-TotalPages'])
        if expected is not None and (expected != count or page_count != total_pages):
            raise ValueError('Public post count changed during pagination')
        expected, page_count = count, total_pages
        data = response.json()
        raw = output / ('page_%06d.json.gz' % number)
        with raw.open('xb') as target:
            with gzip.GzipFile(fileobj=target, mode='wb') as stream:
                stream.write(json.dumps({'requested_at': datetime.now(timezone.utc).isoformat(),
                    'url': url, 'params': params, 'expected_count': expected, 'expected_pages': page_count,
                    'data': data}, ensure_ascii=False).encode('utf-8'))
        pages.append({'page': number, 'path': str(raw), 'sha256': hashlib.sha256(raw.read_bytes()).hexdigest(),
                      'rows': len(data)})
        for row in data:
            if row['id'] in rows:
                raise ValueError('The provider repeated a post identity')
            rows[row['id']] = row
        print(json.dumps({'page': number, 'observed_posts': len(rows), 'expected_posts': expected}), flush=True)
        if number >= page_count:
            break
        number += 1
        time.sleep(1)
    if len(rows) != expected:
        raise ValueError('The advertised public post count does not reconcile')
    save(output / 'posts.json', list(rows.values()))
    result = {'finished_at': datetime.now(timezone.utc).isoformat(), 'expected_posts': expected,
        'observed_unique_posts': len(rows), 'page_count': len(pages), 'raw_pages': pages,
        'per_category_observed': {str(category['id']): sum(category['id'] in row['categories'] for row in rows.values())
                                  for category in categories},
        'status': 'PUBLIC_POST_QUERY_COMPLETE', 'article_database_writes': 0,
        'issue_or_article_census_proven': False, 'blog_timestamp_is_publication_year': False,
        'full_text_reviewed': False}
    save(output / 'report.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--navigation-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.navigation_dir.resolve(), args.output_dir.resolve()), indent=2))
