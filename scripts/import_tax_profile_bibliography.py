#!/usr/bin/env python3
"""Import one verified Tax Forum citation from the observed public UNSW profiles.

The exact venue title is mapped to the frozen journal registry. Profile pages
do not report an ISSN, and that mapping is explicitly recorded rather than
attributed to the source. Only supplied citation fields are retained.
"""

import argparse
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import HistoryRunner, digest, utc_now, write_new_json
from services.abdc_astar_research_service import normalize_title
from scripts.import_tax_repository_metadata import JOURNAL_TITLES


def parse_profile_citation(soup, title, expected_year):
    matches = []
    for node in soup.select('div.pub-content p'):
        title_node = node.select_one('.rg-title')
        if title_node is None:
            continue
        raw_title = title_node.get_text(' ', strip=True)
        parsed_title = raw_title[1:-1] if raw_title.startswith("'") and raw_title.endswith("'") else raw_title
        if normalize_title(parsed_title) != normalize_title(title):
            continue
        heading = node.find_previous('h2')
        if heading is None or heading.get_text(' ', strip=True).casefold() != 'journal articles':
            raise ValueError('matching citation is not in the journal article section')
        fields = {name: node.select_one('.rg-' + selector).get_text(' ', strip=True)
                  for name, selector in (('authors', 'author'), ('year', 'year'), ('venue', 'source-title'))
                  if node.select_one('.rg-' + selector) is not None}
        if not all(fields.get(name) for name in ('authors', 'year', 'venue')):
            raise ValueError('required profile bibliography fields are missing')
        if fields['venue'] not in JOURNAL_TITLES or fields['year'] != str(expected_year):
            raise ValueError('profile venue or publication year does not match the verified target')
        citation = {'title': parsed_title, 'authors': [name.strip() for name in fields['authors'].split(';') if name.strip()],
                    'publication_year': expected_year, 'reported_journal_title': fields['venue'],
                    'publication_date': None, 'publication_month': None, 'date_precision': 'year',
                    'journal_identity_note': 'ISSN mapped from exact venue title in the frozen registry; source does not supply ISSN',
                    'citation_text': node.get_text(' ', strip=True)}
        for name in ('volume', 'page'):
            field = node.select_one('.rg-' + name)
            citation[name] = field.get_text(' ', strip=True) if field is not None else None
        matches.append(citation)
    if len(matches) != 1:
        raise ValueError('the profile does not contain one unambiguous verified target citation')
    return matches[0]


def import_citation(run_dir, source_url, title, expected_year, corroborate_url=None):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = run_dir / 'profile_supplements' / stamp
    folder.mkdir(parents=True)
    citations = []
    for position, url in enumerate([source_url] + ([corroborate_url] if corroborate_url else [])):
        parts = urlparse(url)
        if parts.scheme != 'https' or parts.hostname != 'research.unsw.edu.au' or not parts.path.startswith('/people/'):
            raise ValueError('only the observed public UNSW profile bibliography URLs are accepted')
        response = requests.get(url, headers={'User-Agent': 'ResearchTools-HistoryAudit/1.0'}, timeout=30)
        if response.status_code != 200 or urlparse(response.url).hostname != parts.hostname:
            raise ValueError(f'profile metadata unavailable: HTTP {response.status_code}')
        raw = folder / f'profile_{position + 1}.html.gz'
        with gzip.open(raw, 'wb') as stream:
            stream.write(response.content)
        citation = parse_profile_citation(BeautifulSoup(response.content, 'html.parser'), title, expected_year)
        citations.append({'source_url': url, 'raw_path': raw.name, 'raw_sha256': digest(raw), 'citation': citation})
    selected = citations[0]['citation']
    if any(item['citation'] != selected for item in citations[1:]):
        raise ValueError('the selected profile citations disagree; no article was imported')
    write_new_json(folder / 'citation.json', {'checked_at': utc_now(), 'sources': citations,
                                            'reading_scope': 'selected public bibliography citations; paper full text not read'})
    raw_id = 'unsw-profile-citation:' + hashlib.sha256(
        (source_url + '\n' + normalize_title(selected['title']) + '\n' + str(expected_year)).encode('utf-8')).hexdigest()
    article = {'doi': None, 'openalex_id': None, 'title': selected['title'], 'authors': selected['authors'],
               'publication_year': expected_year, 'publication_date': None, 'date_precision': 'year',
               'journal_title': 'Australian Tax Forum', 'journal_issn': '0812-695X',
               'abstract': None, 'abstract_status': 'missing', 'concepts': [], 'keywords': [],
               'url': source_url, 'landing_page_url': source_url, 'source_url': source_url,
               'source_name': 'UNSW public profile bibliography', 'source_type': 'publisher_metadata',
               'source_raw_id': raw_id, 'data_status': 'repository_profile_metadata', 'record_type': 'journal-article'}
    runner = HistoryRunner(run_dir)
    try:
        journal = next(j for j in runner.journals.values() if j['journal_title'] == 'Australian Tax Forum')
        runner.main.execute('BEGIN IMMEDIATE')
        aid, disposition = runner.ingest_article(article, journal)
        if aid is None:
            raise ValueError(f'verified citation was excluded: {disposition}')
        runner.main.execute('''UPDATE astar_article_sources SET raw_json=?,parser_notes=?
            WHERE article_id=? AND source_type='publisher_metadata' AND raw_id=?''',
            (json.dumps(selected, ensure_ascii=False),
             'public bibliography; full_text_fetched=false; publication_date_precision=year; ' + selected['journal_identity_note'], aid, raw_id))
        runner.main.commit()
        result = {'created_at': utc_now(), 'article_id': aid, 'disposition': disposition,
                  'publication_year': expected_year, 'publication_date': None, 'publication_month': None,
                  'date_precision': 'year', 'source_url': source_url, 'source_raw_id': raw_id,
                  'artifact_dir': str(folder), 'script_sha256': digest(__file__)}
        write_new_json(folder / 'import_result.json', result)
        runner.event('profile_bibliography_supplemented', result)
        return result
    except BaseException:
        runner.main.rollback()
        raise
    finally:
        runner.close()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--corroborate-url')
    parser.add_argument('--title', required=True)
    parser.add_argument('--expected-year', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(import_citation(args.run_dir.resolve(), args.source_url, args.title,
                                     args.expected_year, args.corroborate_url), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
