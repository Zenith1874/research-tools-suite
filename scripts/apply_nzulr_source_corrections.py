#!/usr/bin/env python3
"""Apply audited NZULR item corrections and abstracts while retaining prior rows."""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.import_nzulr_metadata import IssueItemRunner, apply_records, load_verified
from scripts.prepare_nzulr_metadata import MONTHS
from services.astar_history_service import digest, utc_now, write_new_json
from services.astar_archive_year_service import put_year
from services import abdc_astar_research_service as radar


def apply(old_file, corrected_file, abstract_file, run_dir, output, resume_from=None):
    corrected = load_verified(corrected_file)
    old = json.loads(old_file.read_text(encoding='utf-8'))
    abstracts = json.loads(abstract_file.read_text(encoding='utf-8'))
    if len({row['source_raw_id'] for row in abstracts}) != len(abstracts):
        raise ValueError('Repeated verified abstract identities')
    for row in abstracts:
        if row['status'] not in ('VERIFIED_PUBLISHER_ABSTRACT', 'VERIFIED_PUBLISHER_TITLE_ONLY'):
            raise ValueError('An abstract candidate has not been verified')
        if digest(row['pdf_path']) != row['pdf_sha256']:
            raise ValueError('An original abstract PDF changed')
        if row.get('visual_crop') and digest(row['visual_crop']) != row['visual_crop_sha256']:
            raise ValueError('The reviewed metadata crop changed')
    new_ids = {row['source_raw_id'] for row in corrected}
    retired = [row for row in old if row['source_raw_id'] not in new_ids]
    manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8'))
    prior_metadata = None
    if resume_from is not None:
        previous = json.loads((resume_from / 'manifest.json').read_text(encoding='utf-8'))
        if previous['input_files'] != {str(path): digest(path) for path in (old_file, corrected_file, abstract_file)}:
            raise ValueError('Resume inputs differ from the saved correction checkpoint')
        prior_metadata = json.loads((resume_from / 'corrected_html_import' / 'report.json').read_text(encoding='utf-8'))
        if prior_metadata['record_count'] != len(corrected):
            raise ValueError('The completed metadata import does not cover the corrected items')
    baseline = sqlite3.connect(Path(manifest['snapshot_path']).resolve().as_uri() + '?mode=ro', uri=True)
    baseline_max = baseline.execute('SELECT MAX(id) FROM astar_articles').fetchone()[0] or 0
    baseline.close()
    output.mkdir(parents=True, exist_ok=False)
    write_new_json(output / 'manifest.json', {
        'created_at': utc_now(), 'input_files': {str(path): digest(path) for path in (old_file, corrected_file, abstract_file)},
        'script_sha256': digest(__file__), 'baseline_max_id': baseline_max,
        'corrected_HTML_items': len(corrected), 'verified_PDF_items': len(abstracts),
        'retired_parse_item_count': len(retired), 'rows_deleted': 0,
        'raw_source_files_overwritten': False, 'full_text_reviewed': False,
        'resume_from': str(resume_from) if resume_from else None})
    runner = IssueItemRunner(run_dir)
    snapshots = []
    try:
        for record in retired:
            found = runner.main.execute('''SELECT a.* FROM astar_articles a
                JOIN astar_article_sources s ON s.article_id=a.id
                WHERE s.source_type='publisher_metadata' AND s.raw_id=?''', (record['source_raw_id'],)).fetchall()
            if len(found) != 1:
                raise ValueError('A prior parse item has missing or ambiguous stored identity')
            article = dict(found[0])
            if (article['id'] <= baseline_max or article['journal_title'] != record['journal_title']
                    or article['title'] != record['title']):
                raise ValueError('A retirement would affect a baseline or changed article')
            snapshots.append({'article': article, 'original_issue_item': record,
                              'sources': [dict(row) for row in runner.main.execute('SELECT * FROM astar_article_sources WHERE article_id=?', (article['id'],))],
                              'classification': [dict(row) for row in runner.main.execute('SELECT * FROM astar_article_classifications WHERE article_id=?', (article['id'],))]})
        write_new_json(output / 'before_superseded_parse_items.json', snapshots)
    finally:
        runner.close()

    if prior_metadata is None:
        metadata_result = apply_records(corrected_file, run_dir, output / 'corrected_html_import')
    else:
        metadata_result = dict(prior_metadata, reused_completed_metadata_import=True)
    runner = IssueItemRunner(run_dir)
    counts = Counter()
    item_ids = {}
    journal = next(row for row in runner.journals.values() if row['journal_title'] == 'New Zealand Universities Law Review')
    with (output / 'abstract_changes.jsonl').open('x', encoding='utf-8') as audit:
        try:
            for record in abstracts:
                source_id = record['source_raw_id']
                article_id = runner.existing_id({'source_raw_id': source_id}, journal)
                if article_id is None:
                    if not record.get('is_new_pdf_item'):
                        raise ValueError('A matched abstract has no verified HTML item in the database')
                    month = MONTHS[record['month_label']]
                    article = {'title': record['issue_title'], 'authors': record['verified_authors'],
                        'publication_date': None, 'publication_year': record['archive_year'],
                        'publication_month': f"{record['archive_year']:04d}-{month:02d}", 'date_precision': 'month',
                        'journal_title': journal['journal_title'], 'journal_issn': journal['issn_print'],
                        'source_type': 'publisher_metadata', 'source_name': 'NZULR public abstract document',
                        'source_url': record['source_url'], 'source_raw_id': source_id,
                        'url': record['source_url'], 'landing_page_url': record['source_url'],
                        'doi': None, 'openalex_id': None, 'abstract': None,
                        'abstract_status': 'not_yet_extracted', 'concepts': [], 'keywords': []}
                    article_id, disposition = runner.ingest_article(article, journal)
                    if article_id is None:
                        raise ValueError('A verified PDF item was excluded: ' + disposition)
                    counts['new_pdf_items'] += 1
                    put_year(runner.main, article_id, record['archive_year'], 'publisher_abstract_document_issue_year',
                             article['source_name'], record['source_url'], {'pdf_sha256': record['pdf_sha256'],
                             'source_issue_heading': record['source_issue_heading']}, 30)
                item_ids[source_id] = article_id
                previous = dict(runner.main.execute('SELECT * FROM astar_articles WHERE id=?', (article_id,)).fetchone())
                abstract = record.get('abstract')
                if abstract and previous.get('abstract') and previous['abstract'] != abstract:
                    raise ValueError('A verified abstract would replace different nonempty text')
                if abstract and not previous.get('abstract'):
                    runner.main.execute("UPDATE astar_articles SET abstract=?,abstract_status='available',data_status='publisher_abstract',updated_at=? WHERE id=? AND (abstract IS NULL OR abstract='')",
                                        (abstract, utc_now(), article_id))
                    counts['abstracts_filled'] += 1
                elif not abstract:
                    counts['title_only_pdf_items'] += 1
                else:
                    counts['existing_same_abstract_preserved'] += 1
                if record.get('verified_authors') and previous.get('authors_json') in (None, '', '[]'):
                    runner.main.execute('UPDATE astar_articles SET authors_json=?,author_count=? WHERE id=?',
                                        (json.dumps(record['verified_authors'], ensure_ascii=False), len(record['verified_authors']), article_id))
                    counts['empty_author_fields_filled'] += 1
                runner.main.execute('''INSERT OR IGNORE INTO astar_article_sources
                    (article_id,source_name,source_type,source_url,raw_id,raw_json,fetched_at,parser_notes)
                    VALUES(?,?,?,?,?,?,?,?)''', (article_id, 'NZULR public abstract document', 'publisher_abstract_document',
                    record['source_url'], source_id, json.dumps(record, ensure_ascii=False), utc_now(),
                    'verified title/author/issue metadata and publisher abstract only; full_text_reviewed=false'))
                runner.main.commit()
                audit.write(json.dumps({'source_id': source_id, 'article_id': article_id,
                    'abstract_present': bool(abstract), 'source_pdf_sha256': record['pdf_sha256']}) + '\n')
                audit.flush()

            # Corrected items must exist before prior composite/heading artifacts
            # are hidden. The raw titles, source evidence and classifications stay.
            for snapshot in snapshots:
                article = snapshot['article']
                cursor = runner.main.execute('UPDATE astar_articles SET is_duplicate=1 WHERE id=? AND title=? AND is_duplicate=?',
                                            (article['id'], article['title'], article['is_duplicate']))
                if cursor.rowcount != 1:
                    raise ValueError('A prior parse item changed during the correction')
            runner.main.commit()
            result = {'finished_at': utc_now(), 'corrected_html_import': metadata_result,
                'abstract_counts': dict(counts), 'verified_pdf_item_article_ids': item_ids,
                'superseded_parse_article_ids': [row['article']['id'] for row in snapshots],
                'rows_deleted': 0, 'original_titles_and_source_rows_retained': True,
                'baseline_rows_retired': 0, 'full_text_reviewed': False,
                'final_baseline_and_semantic_generation_audits_required': True}
            write_new_json(output / 'report.json', result)
            return result
        except BaseException:
            runner.main.rollback()
            raise
        finally:
            runner.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-records', type=Path, required=True)
    parser.add_argument('--corrected-records', type=Path, required=True)
    parser.add_argument('--verified-abstracts', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--resume-from', type=Path)
    args = parser.parse_args()
    if not args.apply:
        parser.error('Database changes require the explicit --apply flag')
    result = apply(args.old_records.resolve(), args.corrected_records.resolve(), args.verified_abstracts.resolve(),
                   args.run_dir.resolve(), args.output_dir.resolve(),
                   args.resume_from.resolve() if args.resume_from else None)
    print(json.dumps({key: value for key, value in result.items() if key != 'verified_pdf_item_article_ids'}, indent=2))
