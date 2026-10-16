#!/usr/bin/env python3
"""Append source-verified public repository metadata with persistent identities."""

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.import_nzulr_metadata import IssueItemRunner
from scripts.prepare_repository_metadata import osgoode_record, transcribed_record
from services.astar_archive_year_service import ensure_tables, put_year
from services.astar_history_service import digest, utc_now, write_new_json

SOURCE_TYPE = 'institutional_repository_metadata'


def load_verified(path):
    records = json.loads(path.read_text(encoding='utf-8'))
    if not records or len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Missing or repeated persistent repository identity')
    for row in records:
        if row['status'] != 'VERIFIED_PUBLIC_REPOSITORY_METADATA' or row.get('full_text_reviewed') is not False:
            raise ValueError('Unverified repository metadata or unsupported reading claim')
        artifact = Path(row['source_artifact_path'])
        if digest(artifact) != row['source_artifact_sha256']:
            raise ValueError('The original repository evidence changed')
        if row['source_format'] == 'osgoode_public_html_metadata':
            if not row['source_url'].startswith('https://digitalcommons.osgoode.yorku.ca/scholarly_works/'):
                raise ValueError('Unexpected public repository surface')
            observed, reason = osgoode_record(gzip.decompress(artifact.read_bytes()),
                {'source_url': row['source_url'], 'raw_path': str(artifact), 'sha256': row['source_artifact_sha256']})
            if reason:
                raise ValueError('Unconfirmed journal publication: ' + reason)
        elif row['source_format'] == 'primary_web_metadata_transcription':
            if not row['source_url'].startswith('https://ir.canterbury.ac.nz/items/'):
                raise ValueError('Unexpected primary metadata transcription surface')
            sources = json.loads(artifact.read_text(encoding='utf-8'))
            source = next((item for item in sources if item['source_url'] == row['source_url']), None)
            if source is None:
                raise ValueError('Missing primary-page evidence transcription')
            observed = transcribed_record(source, artifact)
        else:
            raise ValueError('Unsupported repository evidence format')
        if any(row.get(key) != value for key, value in observed.items()):
            raise ValueError('Prepared repository metadata differs from its evidence')
    return records


class RepositoryRunner(IssueItemRunner):
    def existing_id(self, article, journal):
        row = self.main.execute('SELECT article_id FROM astar_public_bibliographic_items WHERE source_id=?',
                                (article['source_raw_id'],)).fetchone()
        return row[0] if row else None


def apply(path, run_dir, output):
    records = load_verified(path)
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / 'manifest.json', {'created_at': utc_now(), 'records_file': str(path),
        'records_sha256': digest(path), 'script_sha256': digest(__file__), 'record_count': len(records),
        'source_type': SOURCE_TYPE, 'source_identity': 'persistent_repository_item_URI',
        'run_dir': str(run_dir), 'title_year_fallback_used': False, 'full_text_reviewed': False})
    state = sqlite3.connect(output / 'checkpoint.sqlite3')
    state.execute('CREATE TABLE records(source_id TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT,imported_at TEXT)')
    runner = RepositoryRunner(run_dir)
    journals = {row['journal_title']: row for row in runner.journals.values()}
    try:
        if any(row['journal_title'] not in journals or journals[row['journal_title']]['abdc_rating'] != 'A' for row in records):
            raise ValueError('A metadata journal is outside the frozen A-rated scope')
        runner.main.execute('''CREATE TABLE IF NOT EXISTS astar_public_bibliographic_items(
            source_id TEXT PRIMARY KEY,article_id INTEGER NOT NULL,source_type TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,recorded_at TEXT NOT NULL)''')
        ensure_tables(runner.main)
        runner.main.commit()
        for row in records:
            journal = journals[row['journal_title']]
            article = {key: row[key] for key in ('title', 'abstract', 'publication_year', 'publication_month',
                'publication_date', 'date_precision', 'authors', 'source_raw_id', 'source_url', 'source_name', 'record_type')}
            article.update(doi=None, openalex_id=None, concepts=[], keywords=[], source_type=SOURCE_TYPE,
                journal_title=journal['journal_title'], journal_issn=journal['issn_print'] or journal['issn_online'],
                publisher=journal.get('publisher'), abstract_status='available' if row['abstract'] else 'missing',
                url=row['source_url'], landing_page_url=row['source_url'], open_access_status='public_metadata',
                data_status='public_repository_metadata')
            runner.main.execute('BEGIN IMMEDIATE')
            try:
                aid, disposition = runner.ingest_article(article, journal)
                if aid is None:
                    raise ValueError('Source-verified repository item excluded: ' + disposition)
                runner.main.execute('''INSERT INTO astar_public_bibliographic_items VALUES(?,?,?,?,?)
                    ON CONFLICT(source_id) DO NOTHING''', (row['source_raw_id'], aid, SOURCE_TYPE,
                        row['source_artifact_sha256'], utc_now()))
                runner.main.execute('''UPDATE astar_article_sources SET raw_json=?,parser_notes=?
                    WHERE article_id=? AND source_type=? AND raw_id=? AND raw_json IS NULL''',
                    (json.dumps(row, ensure_ascii=False), row['reading_scope'] + '; exact day unknown; full_text_reviewed=false',
                     aid, SOURCE_TYPE, row['source_raw_id']))
                put_year(runner.main, aid, row['publication_year'], row['year_basis'], row['source_name'], row['source_url'],
                    {'volume': row['volume'], 'issue': row['issue'], 'first_page': row['printed_start_page'],
                     'source_citation': row['source_citation'], 'evidence_artifact_sha256': row['source_artifact_sha256'],
                     'reading_scope': row['reading_scope']}, row['archive_year_priority'])
                runner.main.commit()
            except BaseException:
                runner.main.rollback()
                raise
            state.execute('INSERT INTO records VALUES(?,?,?,?)', (row['source_raw_id'], aid, disposition, utc_now()))
            state.commit()
        result = {'finished_at': utc_now(), 'records': len(records),
            'dispositions': [list(row) for row in state.execute('SELECT disposition,COUNT(*) FROM records GROUP BY disposition')],
            'supplied_descriptions': sum(bool(row['abstract']) for row in records), 'exact_days_imputed': 0,
            'publisher_census_proven': False, 'full_text_reviewed': False,
            'final_preservation_and_index_audits_required': True}
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
