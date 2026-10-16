#!/usr/bin/env python3
"""Retain publisher-linked contents PDFs, including older month-named posts."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def prepare(post_dir, journal_file):
    post_file = post_dir / 'posts.json'
    posts = json.loads(post_file.read_text(encoding='utf-8'))
    journals = json.loads(journal_file.read_text(encoding='utf-8'))
    banking = next(row['journal_title'] for row in journals if 'Banking and Finance' in row['journal_title'] and 'Law' in row['journal_title'])
    mapping = {230: ('Australian Tax Review', 'Australian Tax Review'),
               20: ('Insolvency Law Journal', 'Insolvency Law Journal'),
               37: (banking, 'Journal of Banking and Finance Law and Practice'),
               288: ('Tort Law Review', 'Tort Law Review')}
    candidates, issues, excluded = {}, [], []
    source_hash = hashlib.sha256(post_file.read_bytes()).hexdigest()
    pattern = re.compile(r'\bVol(?:ume)?\s*(\d+)\s*,?\s*(?:Pt|Part|Number|No\.?)\s*(\d+)', re.I)
    for post in posts:
        soup = BeautifulSoup(post['content']['rendered'], 'html.parser')
        title = BeautifulSoup(post['title']['rendered'], 'html.parser').get_text(' ', strip=True)
        if 'update' not in title.lower():
            excluded.append({'post_id': post['id'], 'reason': 'not_an_issue_update_title'})
            continue
        match = pattern.search(title) or pattern.search(soup.get_text(' ', strip=True)[:3000])
        selected = [category for category in mapping if category in post['categories']]
        if not match or len(selected) != 1:
            excluded.append({'post_id': post['id'], 'reason': 'review_missing_or_ambiguous_issue_identity'})
            continue
        journal, header = mapping[selected[0]]
        issue = {'post_id': post['id'], 'post_url': post['link'], 'journal_title': journal,
                 'volume': int(match[1]), 'issue': match[2], 'blog_timestamp': post['date'],
                 'blog_timestamp_used_as_issue_year': False}
        issues.append(issue)
        for link in soup.select('a[href]'):
            url = urljoin(post['link'], link['href']);parsed = urlparse(url)
            if parsed.hostname not in ('sites.thomsonreuters.com.au', 'livepages.thomsonreuters.com.au') or not parsed.path.lower().endswith('.pdf'):
                continue
            context = link.parent.get_text(' ', strip=True)
            if 'contents' not in (context + ' ' + parsed.path).lower():
                continue
            candidates.setdefault(url, dict(issue, url=url, link_text=link.get_text(' ', strip=True),
                source_link_context=context, publisher_journal_header_title=header,
                metadata_format='public_journal_issue_contents', source_html_path=str(post_file),
                source_html_sha256=source_hash))
    report = {'source_file': str(post_file), 'source_sha256': source_hash,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'source_posts': len(posts), 'classified_issue_posts': len(issues),
              'observed_contents_pdfs': len(candidates), 'excluded_posts': excluded,
              'per_journal_pdf_links': dict(Counter(row['journal_title'] for row in candidates.values())),
              'article_database_writes': 0, 'blog_date_used_as_issue_year': False}
    for name, data in [('all_years_pdf_candidates.json', list(candidates.values())),
                       ('all_years_issue_posts.json', issues), ('candidate_preparation_report.json', report)]:
        with (post_dir / name).open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--post-dir', type=Path, required=True)
    parser.add_argument('--journal-file', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.post_dir.resolve(), args.journal_file.resolve())
    print(json.dumps({key: value for key, value in report.items() if key != 'excluded_posts'}, indent=2))
