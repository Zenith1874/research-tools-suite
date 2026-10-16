#!/usr/bin/env python3
"""Append verified publisher contents items without title/year identity fallback."""

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.import_nzulr_metadata import IssueItemRunner
from services.astar_history_service import digest, utc_now, write_new_json
from services.astar_archive_year_service import ensure_tables, put_year


def validate_metadata_source(row):
    kind = row.get('metadata_format', 'publisher_pdf_metadata')
    if kind == 'publisher_pdf_metadata':
        path, expected = row['pdf_path'], row['pdf_sha256']
    elif kind == 'publisher_issue_html':
        path, expected = row['source_html_path'], row['source_html_sha256']
    elif kind == 'publisher_browser_readback':
        path, expected = row['browser_readback_path'], row['browser_readback_sha256']
        snapshot = json.loads(Path(path).read_text(encoding='utf-8'))
        if (snapshot.get('capture_method') != 'browser_visible_issue_page_metadata_readback'
                or snapshot.get('raw_html_saved') is not False):
            raise ValueError('Browser readback must declare its capture method and raw-HTML boundary')
        source_urls = set(snapshot.get('source_urls') or [])
        if row.get('source_url') not in source_urls or row.get('publisher_article_url') not in source_urls:
            raise ValueError('Browser readback does not include the row issue and article URLs')
        item = next((item for item in snapshot.get('items', [])
                     if str(item.get('publisher_article_id')) == str(row.get('publisher_article_id'))), None)
        if item is None:
            raise ValueError('Publisher item identity is absent from the browser readback')
        for field in ('title', 'doi', 'authors', 'publication_date', 'publication_year',
                      'publication_month', 'date_precision', 'archive_year'):
            if item.get(field) != row.get(field):
                raise ValueError('Browser readback mismatch for ' + field)
        if item.get('issue_url') != row.get('source_url'):
            raise ValueError('Browser readback mismatch for source_url')
        if item.get('article_url') != row.get('publisher_article_url'):
            raise ValueError('Browser readback mismatch for publisher_article_url')
        if str(item.get('issue')) != str(row.get('issue')):
            raise ValueError('Browser readback mismatch for issue')
    else:
        raise ValueError('Unsupported public publisher metadata format')
    if digest(path) != expected:
        raise ValueError('An original publisher metadata document changed')
    evidence = row.get('issue_year_evidence') or {}
    for path_field, hash_field in (('printed_year_document', 'printed_year_sha256'),
                                 ('repository_metadata_path', 'repository_metadata_sha256')):
        if evidence.get(path_field) and digest(evidence[path_field]) != evidence.get(hash_field):
            raise ValueError('A publication-year evidence document changed')
    priority = row.get('archive_year_priority', 30)
    if type(priority) is not int or priority not in (15, 20, 30):
        raise ValueError('Unsupported archive-year evidence priority')
    return expected


def validate_publication_fields(row):
    year = row.get('publication_year')
    if type(year) is not int or not 2010 <= year <= 2026:
        raise ValueError('An explicit in-scope publication year is required')

    precision = row.get('date_precision')
    publication_date = row.get('publication_date')
    publication_month = row.get('publication_month')
    if precision == 'year':
        if publication_date is not None or publication_month is not None:
            raise ValueError('Year precision cannot contain a more precise publication date')
    elif precision == 'month':
        if publication_date is not None or not isinstance(publication_month, str):
            raise ValueError('Month precision requires publication_month and no exact date')
        try:
            parsed_month = datetime.strptime(publication_month, '%Y-%m')
        except ValueError as error:
            raise ValueError('publication_month must be YYYY-MM') from error
        if parsed_month.strftime('%Y-%m') != publication_month or parsed_month.year != year:
            raise ValueError('publication_month must be valid and match publication_year')
    elif precision == 'day':
        if not isinstance(publication_date, str):
            raise ValueError('Day precision requires a publisher-reported publication_date')
        try:
            parsed_date = datetime.strptime(publication_date, '%Y-%m-%d')
        except ValueError as error:
            raise ValueError('publication_date must be YYYY-MM-DD') from error
        if parsed_date.strftime('%Y-%m-%d') != publication_date or parsed_date.year != year:
            raise ValueError('publication_date must be valid and match publication_year')
        if publication_month is not None and publication_month != publication_date[:7]:
            raise ValueError('publication_month must match publication_date when both are supplied')
    else:
        raise ValueError('date_precision must be year, month, or day')

    archive_year = row.get('archive_year', year)
    if type(archive_year) is not int or not 2010 <= archive_year <= 2026:
        raise ValueError('archive_year must be an explicit in-scope journal issue year')
    if archive_year != year:
        issue_evidence = row.get('issue_year_evidence') or row.get('header_evidence') or {}
        if (issue_evidence.get('archive_year') != archive_year
                or not issue_evidence.get('year_basis')
                or not issue_evidence.get('source_url')):
            raise ValueError('A distinct archive_year requires explicit issue-year evidence')
    return archive_year


def apply(records_file, run_dir, output):
    records = json.loads(records_file.read_text(encoding='utf-8'))
    if not records or len({row['source_raw_id'] for row in records}) != len(records):
        raise ValueError('Verified items require unique publisher identities')
    for row in records:
        if row['status'] != 'VERIFIED_PUBLIC_CONTENTS_ITEM' or not row.get('title'):
            raise ValueError('An unverified or empty contents item cannot be imported')
        validate_publication_fields(row)
        validate_metadata_source(row)
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / 'manifest.json', {'created_at': utc_now(), 'records_file': str(records_file),
        'records_sha256': digest(records_file), 'script_sha256': digest(__file__), 'record_count': len(records),
        'run_dir': str(run_dir), 'source_identity': 'persistent_publisher_item_identifier',
        'title_year_fallback_used': False, 'exact_days_imputed': 0,
        'publisher_publication_dates_supplied': sum(bool(row.get('publication_date')) for row in records),
        'distinct_archive_years_supplied': sum(
            row.get('archive_year', row['publication_year']) != row['publication_year'] for row in records),
        'full_text_reviewed': False})
    state = sqlite3.connect(output / 'checkpoint.sqlite3')
    state.execute('CREATE TABLE records(source_id TEXT PRIMARY KEY,article_id INTEGER,disposition TEXT,imported_at TEXT)')
    runner = IssueItemRunner(run_dir)
    journals = {row['journal_title']: row for row in runner.journals.values()}
    try:
        ensure_tables(runner.main);runner.main.commit()
        for metadata in records:
            journal = journals.get(metadata['journal_title'])
            if journal is None or journal['abdc_rating'] != 'A':
                raise ValueError('The metadata journal is absent from the frozen A-rated scope')
            article = {'title': metadata['title'], 'doi': metadata.get('doi'), 'openalex_id': metadata.get('openalex_id'),
                'abstract': metadata.get('abstract'), 'abstract_status': 'available' if metadata.get('abstract') else 'missing',
                'publication_year': metadata['publication_year'], 'publication_month': metadata.get('publication_month'),
                'publication_date': metadata.get('publication_date'), 'date_precision': metadata['date_precision'], 'journal_title': journal['journal_title'],
                'journal_issn': journal['issn_print'] or journal['issn_online'], 'publisher': journal.get('publisher'),
                'authors': metadata.get('authors') or [], 'concepts': [], 'keywords': [],
                'url': metadata.get('publisher_article_url') or metadata['source_url'],
                'landing_page_url': metadata.get('publisher_article_url') or metadata['source_url'],
                'source_url': metadata['source_url'],
                'source_name': metadata.get('source_name') or journal['journal_title'] + ': public publisher contents',
                'source_type': 'publisher_metadata', 'source_raw_id': metadata['source_raw_id'],
                'data_status': 'publisher_metadata', 'record_type': metadata.get('record_type') or 'journal-metadata-item',
                'open_access_status': 'public_metadata'}
            runner.main.execute('BEGIN IMMEDIATE')
            try:
                article_id, disposition = runner.ingest_article(article, journal)
                if article_id is None:
                    raise ValueError('A verified item was excluded: ' + disposition)
                evidence = metadata.get('issue_year_evidence') or metadata.get('header_evidence') or {}
                archive_year = metadata.get('archive_year', metadata['publication_year'])
                put_year(runner.main, article_id, archive_year,
                    evidence.get('year_basis') or 'publisher_printed_issue_year', article['source_name'],
                    evidence.get('source_url') or metadata['source_url'],
                    {'archive_year': archive_year, 'publication_year': metadata['publication_year'],
                     'publication_date': metadata.get('publication_date'),
                     'volume': metadata['volume'], 'issue': metadata['issue'],
                     'source_pdf_sha256': metadata.get('pdf_sha256'),
                     'source_document_sha256': metadata.get('pdf_sha256') or metadata.get('source_html_sha256'),
                     'year_evidence': evidence}, metadata.get('archive_year_priority', 30))
                date_note = ('publisher-reported publication_date=' + metadata['publication_date']
                             if metadata.get('publication_date') else 'exact day unknown')
                runner.main.execute('''UPDATE astar_article_sources SET raw_json=?,parser_notes=?
                    WHERE article_id=? AND source_type='publisher_metadata' AND raw_id=? AND raw_json IS NULL''',
                    (json.dumps(metadata, ensure_ascii=False),
                     (metadata.get('reading_scope') or 'public contents metadata and supplied abstract only') +
                     '; ' + date_note + '; full_text_reviewed=false',
                     article_id, metadata['source_raw_id']))
                runner.main.commit()
            except BaseException:
                runner.main.rollback();raise
            state.execute('INSERT INTO records VALUES(?,?,?,?)', (metadata['source_raw_id'], article_id, disposition, utc_now()))
            state.commit()
        result = {'finished_at': utc_now(), 'record_count': len(records),
            'dispositions': [list(row) for row in state.execute('SELECT disposition,COUNT(*) FROM records GROUP BY disposition')],
            'supplied_abstracts': sum(bool(row.get('abstract')) for row in records),
            'exact_days_imputed': 0,
            'publisher_publication_dates_supplied': sum(bool(row.get('publication_date')) for row in records),
            'distinct_archive_years_supplied': sum(
                row.get('archive_year', row['publication_year']) != row['publication_year'] for row in records),
            'raw_originals_overwritten': False, 'full_text_reviewed': False,
            'final_preservation_semantic_and_entity_audits_required': True}
        write_new_json(output / 'report.json', result)
        return result
    finally:
        runner.close();state.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:parser.error('Database writes require the explicit --apply flag')
    print(json.dumps(apply(args.records.resolve(), args.run_dir.resolve(), args.output_dir.resolve()), indent=2))
