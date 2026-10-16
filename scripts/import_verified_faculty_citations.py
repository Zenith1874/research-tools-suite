#!/usr/bin/env python3
"""Append explicit institutional publication citations with source-year fallback."""

import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_nyu_publication_metadata import parse_citations, public_pdf_url
from scripts.import_nzulr_metadata import IssueItemRunner
from services.astar_archive_year_service import ensure_tables, put_year
from services.astar_history_service import digest, utc_now, write_new_json

SOURCE_TYPE = 'institutional_faculty_metadata'


def make_record(observed):
    if public_pdf_url(observed['observed_article_url']):
        raise ValueError('Public published-version candidates follow the stronger metadata path')
    identity = [observed[key] for key in ('journal_title', 'volume', 'printed_start_page', 'title',
                                        'authors_in_faculty_citation')]
    return dict(observed, source_raw_id='institutional_faculty_item:' + hashlib.sha256(
        json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest(),
        publication_year=observed['institution_reported_year'], publication_date=None,
        publication_month=None, date_precision='year',
        authors=observed['authors_in_faculty_citation'], author_order='as_listed_in_faculty_bibliography',
        abstract=observed.get('faculty_abstract'), year_basis='reported_institutional_publication_citation_year',
        publisher_print_period_verified=False, status='VERIFIED_INSTITUTIONAL_PUBLICATION_CITATION',
        reading_scope='public faculty publication citation and supplied description only; protected article not requested',
        full_text_reviewed=False)


def load_verified(path):
    records = json.loads(path.read_text(encoding='utf-8'))
    if not records or len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Missing or repeated faculty citation identity')
    sources = {}
    for row in records:
        if row['status'] != 'VERIFIED_INSTITUTIONAL_PUBLICATION_CITATION':
            raise ValueError('Unverified institutional publication citation')
        raw = row['source_html_path']
        if digest(raw) != row['source_html_sha256']:
            raise ValueError('An original institutional bibliography changed')
        if raw not in sources:
            source = {key: row[key] for key in ('source_url', 'source_html_path', 'source_html_sha256')}
            source.update(raw_path=raw, sha256=row['source_html_sha256'])
            observed, _ = parse_citations(gzip.decompress(Path(raw).read_bytes()), source)
            sources[raw] = {make_record(item)['source_raw_id']: make_record(item)
                            for item in observed if not public_pdf_url(item['observed_article_url'])}
        original = sources[raw].get(row['source_raw_id'])
        if original is None or any(row.get(key) != value for key, value in original.items()):
            raise ValueError('Institutional citation differs from its preserved source')
    return records


class FacultyCitationRunner(IssueItemRunner):
    def existing_id(self, article, journal):
        row = self.main.execute('SELECT article_id FROM astar_public_bibliographic_items WHERE source_id=?',
                                (article['source_raw_id'],)).fetchone()
        return row[0] if row else None


def apply(path, run_dir, output):
    records = load_verified(path)
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / 'manifest.json', {'created_at': utc_now(), 'records_file': str(path),
        'records_sha256': digest(path), 'script_sha256': digest(__file__), 'record_count': len(records),
        'run_dir': str(run_dir), 'source_type': SOURCE_TYPE, 'archive_year_priority': 15,
        'year_basis': 'reported_institutional_publication_citation_year',
        'publisher_print_period_verified': False, 'protected_articles_requested': 0,
        'title_year_fallback_used': False, 'full_text_reviewed': False})
    state = sqlite3.connect(output / 'checkpoint.sqlite3')
    state.execute('CREATE TABLE records(source_id TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT,imported_at TEXT)')
    runner = FacultyCitationRunner(run_dir)
    journals = {item['journal_title']: item for item in runner.journals.values()}
    try:
        if any(row['journal_title'] not in journals or journals[row['journal_title']]['abdc_rating'] != 'A' for row in records):
            raise ValueError('Institutional journal is absent from the frozen A-rated scope')
        runner.main.execute('''CREATE TABLE IF NOT EXISTS astar_public_bibliographic_items(
            source_id TEXT PRIMARY KEY,article_id INTEGER NOT NULL,source_type TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,recorded_at TEXT NOT NULL)''')
        ensure_tables(runner.main)
        runner.main.commit()
        for row in records:
            journal = journals[row['journal_title']]
            article = {key: row[key] for key in ('title', 'abstract', 'publication_year', 'publication_date',
                        'publication_month', 'date_precision', 'authors', 'source_raw_id', 'source_url')}
            article.update(doi=None, openalex_id=None, concepts=[], keywords=[],
                abstract_status='available' if row['abstract'] else 'missing', journal_title=journal['journal_title'],
                journal_issn=journal['issn_print'] or journal['issn_online'], publisher=journal.get('publisher'),
                url=row['source_url'], landing_page_url=row['source_url'],
                source_type=SOURCE_TYPE, source_name='NYU School of Law: faculty publication bibliography',
                data_status='institutional_publication_citation', open_access_status='public_metadata')
            runner.main.execute('BEGIN IMMEDIATE')
            try:
                aid, disposition = runner.ingest_article(article, journal)
                if aid is None:
                    raise ValueError('Explicit institutional citation excluded: ' + disposition)
                runner.main.execute('''INSERT INTO astar_public_bibliographic_items VALUES(?,?,?,?,?)
                    ON CONFLICT(source_id) DO NOTHING''', (row['source_raw_id'], aid, SOURCE_TYPE,
                        row['source_html_sha256'], utc_now()))
                runner.main.execute('''UPDATE astar_article_sources SET raw_json=?,parser_notes=?
                    WHERE article_id=? AND source_type=? AND raw_id=? AND raw_json IS NULL''',
                    (json.dumps(row, ensure_ascii=False),
                     'explicit institutional publication citation; year fallback priority 15; publisher print period unverified; exact day unknown; full_text_reviewed=false',
                     aid, SOURCE_TYPE, row['source_raw_id']))
                put_year(runner.main, aid, row['publication_year'], row['year_basis'], article['source_name'],
                    row['source_url'], {'volume': row['volume'], 'printed_start_page': row['printed_start_page'],
                        'citation_text': row['citation_text'], 'source_html_sha256': row['source_html_sha256'],
                        'publisher_print_period_verified': False}, 15)
                runner.main.commit()
            except BaseException:
                runner.main.rollback()
                raise
            state.execute('INSERT INTO records VALUES(?,?,?,?)', (row['source_raw_id'], aid, disposition, utc_now()))
            state.commit()
        result = {'finished_at': utc_now(), 'record_count': len(records),
            'dispositions': [list(value) for value in state.execute('SELECT disposition,COUNT(*) FROM records GROUP BY disposition')],
            'supplied_abstracts': sum(bool(row['abstract']) for row in records),
            'publisher_print_period_verified': False, 'exact_days_imputed': 0, 'full_text_reviewed': False,
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
        result = {'verified_citations': len(load_verified(args.records.resolve())), 'article_database_writes': 0}
    print(json.dumps(result, indent=2))
