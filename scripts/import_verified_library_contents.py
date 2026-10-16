#!/usr/bin/env python3
"""Append audited institutional issue bibliographies with explicit provenance."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.import_nzulr_metadata import IssueItemRunner
from scripts.prepare_library_issue_metadata import JOURNAL, extract_post, identity_text
from services.astar_archive_year_service import ensure_tables, put_year
from services.astar_history_service import digest, utc_now, write_new_json

SOURCE_TYPE = 'institutional_library_metadata'
SOURCE_NAME = 'Law Society of Saskatchewan: public journal issue bibliography'


class LibraryItemRunner(IssueItemRunner):
    def existing_id(self, article, journal):
        prior = self.main.execute('SELECT article_id FROM astar_public_bibliographic_items WHERE source_id=?',
                                  (article['source_raw_id'],)).fetchone()
        if prior:
            return prior[0]
        publisher_id = article.get('_corroborated_publisher_source_raw_id')
        if publisher_id:
            return validate_publisher_match(self.main, article['_verified_metadata'], publisher_id)
        return None


def validate_publisher_match(conn, metadata, publisher_id):
    prior = conn.execute('''SELECT s.article_id,s.raw_json,a.title,a.authors_json,a.publication_year,
                           a.publication_month,a.journal_title,a.is_duplicate
                           FROM astar_article_sources s JOIN astar_articles a ON a.id=s.article_id
                           WHERE s.source_type='publisher_metadata' AND s.raw_id=?''', (publisher_id,)).fetchall()
    if len(prior) != 1:
        raise ValueError('Publisher identity must resolve to exactly one recorded source')
    row = prior[0]
    source = json.loads(row['raw_json'] or '{}')
    for key in ('volume', 'issue', 'publication_year', 'publication_month'):
        if source.get(key) != metadata[key]:
            raise ValueError('Publisher/library issue citation mismatch')
    if (row['journal_title'] != metadata['journal_title'] or row['is_duplicate']
            or row['publication_year'] != metadata['publication_year']
            or row['publication_month'] != metadata['publication_month']
            or identity_text(row['title']) != identity_text(metadata['title'])
            or [identity_text(value) for value in json.loads(row['authors_json'] or '[]')] !=
               [identity_text(value) for value in metadata['authors']]):
        raise ValueError('Publisher/library item transcription mismatch')
    return row['article_id']


def load_verified(path):
    records = json.loads(path.read_text(encoding='utf-8'))
    if not records or len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Missing or repeated library item identity')
    originals = {}
    for row in records:
        if row['status'] != 'VERIFIED_PUBLIC_LIBRARY_CONTENTS_ITEM' or row['journal_title'] != JOURNAL:
            raise ValueError('Unaudited or out-of-journal library record')
        if row.get('abstract') is not None or row.get('publication_date') is not None:
            raise ValueError('Library bibliography supplies neither abstract nor exact day')
        if row['date_precision'] != 'month' or not isinstance(row.get('publication_year'), int):
            raise ValueError('An explicit library issue period is required')
        source_path = row['source_json_path']
        if source_path not in originals:
            if digest(source_path) != row['source_json_sha256']:
                raise ValueError('An original library response changed')
            posts = json.loads(Path(source_path).read_text(encoding='utf-8'))
            originals[source_path] = {post['id']: post for post in posts}
        post = originals[source_path][row['post_id']]
        if post['link'] != row['source_url'] or not row['source_url'].startswith('https://www.lawsociety.sk.ca/'):
            raise ValueError('Library source URL does not match the preserved response')
        items, _ = extract_post(post, Path(source_path), row['source_json_sha256'])
        observed = next((item for item in items if item['source_raw_id'] == row['source_raw_id']), None)
        if observed is None or any(row.get(key) != value for key, value in observed.items()
                                   if key != 'status'):
            raise ValueError('Verified metadata differs from its source transcription')
    return records


def apply(path, run_dir, output):
    records = load_verified(path)
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / 'manifest.json', {'created_at': utc_now(), 'records_file': str(path),
        'records_sha256': digest(path), 'script_sha256': digest(__file__), 'record_count': len(records),
        'run_dir': str(run_dir), 'source_type': SOURCE_TYPE,
        'source_identity': 'journal_issue_period_title_supplied_byline_composite',
        'title_year_fallback_used': False, 'publisher_article_census_proven': False,
        'full_text_reviewed': False})
    state = sqlite3.connect(output / 'checkpoint.sqlite3')
    state.execute('CREATE TABLE records(source_id TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT,imported_at TEXT)')
    runner = LibraryItemRunner(run_dir)
    journal = next((item for item in runner.journals.values() if item['journal_title'] == JOURNAL), None)
    try:
        if journal is None or journal['abdc_rating'] != 'A':
            raise ValueError('Library journal is not in the frozen A-rated scope')
        for metadata in records:
            if metadata.get('corroborated_publisher_source_raw_id'):
                validate_publisher_match(runner.main, metadata, metadata['corroborated_publisher_source_raw_id'])
        runner.main.execute('''CREATE TABLE IF NOT EXISTS astar_public_bibliographic_items(
            source_id TEXT PRIMARY KEY,article_id INTEGER NOT NULL,source_type TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,recorded_at TEXT NOT NULL)''')
        ensure_tables(runner.main)
        runner.main.commit()
        for metadata in records:
            article = {'title': metadata['title'], 'doi': None, 'openalex_id': None,
                'abstract': None, 'abstract_status': 'missing', 'publication_date': None,
                'publication_year': metadata['publication_year'], 'publication_month': metadata['publication_month'],
                'date_precision': 'month', 'journal_title': journal['journal_title'],
                'journal_issn': journal['issn_print'] or journal['issn_online'], 'publisher': journal.get('publisher'),
                'authors': metadata['authors'], 'concepts': [], 'keywords': [],
                'url': metadata['source_url'], 'landing_page_url': metadata['source_url'],
                'source_url': metadata['source_url'], 'source_name': SOURCE_NAME,
                'source_type': SOURCE_TYPE, 'source_raw_id': metadata['source_raw_id'],
                'data_status': 'public_bibliographic_metadata', 'open_access_status': 'public_metadata',
                'record_type': metadata['record_type'], '_verified_metadata': metadata,
                '_corroborated_publisher_source_raw_id': metadata.get('corroborated_publisher_source_raw_id')}
            runner.main.execute('BEGIN IMMEDIATE')
            try:
                article_id, disposition = runner.ingest_article(article, journal)
                if article_id is None:
                    raise ValueError('Audited library record excluded: ' + disposition)
                runner.main.execute('''INSERT INTO astar_public_bibliographic_items VALUES(?,?,?,?,?)
                    ON CONFLICT(source_id) DO NOTHING''', (metadata['source_raw_id'], article_id,
                        SOURCE_TYPE, metadata['source_json_sha256'], utc_now()))
                runner.main.execute('''UPDATE astar_article_sources SET raw_json=?,parser_notes=?
                    WHERE article_id=? AND source_type=? AND raw_id=? AND raw_json IS NULL''',
                    (json.dumps(metadata, ensure_ascii=False),
                     'institutional issue bibliography only; supplied metadata transcribed; no abstract/full text; exact day unknown',
                     article_id, SOURCE_TYPE, metadata['source_raw_id']))
                # Publisher print-period evidence retains its higher priority.
                put_year(runner.main, article_id, metadata['publication_year'], metadata['year_basis'],
                    SOURCE_NAME, metadata['source_url'], {'volume': metadata['volume'], 'issue': metadata['issue'],
                        'observed_month': metadata['publication_month'], 'source_issue_heading': metadata['source_issue_heading'],
                        'source_json_sha256': metadata['source_json_sha256']}, 15)
                runner.main.commit()
            except BaseException:
                runner.main.rollback()
                raise
            state.execute('INSERT INTO records VALUES(?,?,?,?)',
                          (metadata['source_raw_id'], article_id, disposition, utc_now()))
            state.commit()
        result = {'finished_at': utc_now(), 'records': len(records),
            'dispositions': [list(row) for row in state.execute('SELECT disposition,COUNT(*) FROM records GROUP BY disposition')],
            'abstracts_supplied': 0, 'exact_days_imputed': 0, 'full_text_reviewed': False,
            'publisher_article_census_proven': False, 'final_preservation_and_index_audits_required': True}
        write_new_json(output / 'report.json', result)
        return result
    finally:
        runner.close()
        state.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        if args.output_dir is None:
            parser.error('--apply requires --output-dir')
        result = apply(args.records.resolve(), args.run_dir.resolve(), args.output_dir.resolve())
    else:
        result = {'verified_records': len(load_verified(args.records.resolve())), 'article_database_writes': 0}
    print(json.dumps(result, indent=2))
