#!/usr/bin/env python3
"""Derive archive-year evidence from immutable collected Crossref print metadata.

Original article dates/years and classifications are never changed. Source page
hashes and every previous derived row are retained in the run-specific receipt.
"""

import argparse
import csv
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_history_service import connect, digest, utc_now, write_new_json
from services.astar_archive_year_service import ensure_tables, has_table, put_year, POLICY_VERSION


def derive(run_dir, apply=False):
    manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    state = connect(run_dir / 'checkpoint.sqlite3', readonly=True)
    try:
        pages = [dict(row) for row in state.execute("SELECT p.* FROM pages p JOIN units u ON u.unit_key=p.unit_key WHERE u.provider='crossref' ORDER BY p.unit_key,p.page")]
    finally:
        state.close()
    db = connect(manifest['db_path'], readonly=True)
    try:
        by_doi = {row['doi']: (row['id'], row['publication_year'], row['publication_date']) for row in db.execute(
            'SELECT id,doi,publication_year,publication_date FROM astar_articles WHERE is_duplicate=0 AND doi IS NOT NULL')}
        previous = [dict(row) for row in db.execute('SELECT * FROM astar_article_archive_years')] if has_table(db) else []
    finally:
        db.close()
    mapped = {}
    for page in pages:
        path = run_dir / page['path']
        if digest(path) != page['sha256']:
            raise ValueError('source page hash mismatch: ' + page['path'])
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            envelope = json.load(stream)
        for item in envelope.get('data', {}).get('message', {}).get('items', []):
            doi = (item.get('DOI') or '').lower()
            parts = ((item.get('published-print') or {}).get('date-parts') or [[]])[0]
            if doi not in by_doi or not parts or not isinstance(parts[0], int):
                continue
            identifier, original_year, original_date = by_doi[doi]
            evidence = {'doi': doi, 'source_print_date_parts': parts, 'source_volume': item.get('volume'),
                        'source_issue': item.get('issue'), 'original_publication_year': original_year,
                        'original_publication_date': original_date, 'source_page': page['path'],
                        'source_page_sha256': page['sha256'], 'source_url': 'https://doi.org/' + doi}
            if identifier in mapped and mapped[identifier]['archive_year'] != parts[0]:
                raise ValueError('conflicting deposited print years for one article')
            mapped[identifier] = {'article_id': identifier, 'archive_year': parts[0], 'evidence': evidence}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = run_dir / 'archive_year_derivations' / stamp
    folder.mkdir(parents=True)
    write_new_json(folder / 'previous_derived_rows.json', previous)
    with (folder / 'derived_years.jsonl').open('x', encoding='utf-8') as stream:
        for identifier in sorted(mapped):
            stream.write(json.dumps(mapped[identifier], ensure_ascii=False) + '\n')
    result = {'created_at': utc_now(), 'artifact_dir': str(folder), 'policy_version': POLICY_VERSION,
              'mapped_records': len(mapped), 'years_different_from_original': sum(
                  row['archive_year'] != row['evidence']['original_publication_year'] for row in mapped.values()),
              'original_fields_updated': False, 'applied': False,
              'source_pages_verified': len(pages), 'script_sha256': digest(__file__),
              'mapping_sha256': digest(folder / 'derived_years.jsonl')}
    write_new_json(folder / 'method.json', result)
    if apply:
        db = connect(manifest['db_path'])
        try:
            ensure_tables(db)
            db.commit()
            db.execute('BEGIN IMMEDIATE')
            for identifier in sorted(mapped):
                row = mapped[identifier]
                put_year(db, identifier, row['archive_year'], 'crossref_published_print_year',
                         'Crossref deposited print metadata', row['evidence']['source_page'], row['evidence'])
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        result.update(applied=True, applied_at=utc_now())
        write_new_json(folder / 'application.json', result)
    return result


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(derive(args.run_dir.resolve(), args.apply), indent=2))


if __name__ == '__main__':
    main()
