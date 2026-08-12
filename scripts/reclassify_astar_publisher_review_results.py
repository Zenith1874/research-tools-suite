#!/usr/bin/env python3
"""Reclassify publisher-level blocked results without rewriting history.

The v1 full scan incorrectly used publisher-family access tests as an
article-level terminal status.  This command preserves the original JSONL and
writes a separate, append-only correction inventory.  Each historical blocked
row becomes either publisher-page review pending, resolved since the scan, or
article not found in the current database.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
import sqlite3


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'pboc_data.db')
DEFAULT_RUN_DIR = os.path.join(
    ROOT, 'data', 'astar_abstract_full_scan_20260803')
DEFAULT_RESULTS = os.path.join(DEFAULT_RUN_DIR, 'results.jsonl')
DEFAULT_OUTPUT = os.path.join(
    DEFAULT_RUN_DIR, 'publisher_review_reclassification_v2_1.jsonl')
DEFAULT_SUMMARY = os.path.join(
    DEFAULT_RUN_DIR, 'publisher_review_reclassification_v2_1_summary.json')

CURRENT_REVIEW_RULES = (
    ('elsevier',), ('psychological association',), ('sage',), ('wiley',),
    ('chicago',), ('academy of management',), ('public health association',),
    ('oxford university press',),
    ('operations research', 'management sciences'), ('informa uk',),
    ('routledge',), ('taylor & francis',),
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def read_blocked_results(path):
    with open(path, encoding='utf-8') as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            result = json.loads(line)
            if result.get('status') == 'publisher_route_unavailable':
                yield line_number, result


def requires_publisher_review(publisher):
    value = (publisher or '').lower()
    return any(all(needle in value for needle in needles)
               for needles in CURRENT_REVIEW_RULES)


def reclassify_result(prior, current, source=None, generated_at=None):
    corrected = {
        'article_id': prior.get('article_id'),
        'doi': prior.get('doi'),
        'title': prior.get('title'),
        'publisher': prior.get('publisher'),
        'journal_title': prior.get('journal_title'),
        'prior_status': prior.get('status'),
        'prior_policy_version': prior.get('policy_version'),
        'prior_reason': prior.get('reason'),
        'corrected_at': generated_at or utc_now(),
        'correction_policy_version': 'publisher-route-v2.1-2026-08-03',
        'historical_result_preserved': True,
    }
    if current is None:
        corrected.update(
            corrected_status='article_not_found',
            article_level_abstract_availability='unknown',
            correction_reason='article_missing_from_current_database',
        )
        return corrected

    abstract_present = bool((current.get('abstract') or '').strip())
    available = (current.get('abstract_status') != 'missing'
                 and abstract_present)
    corrected['current_abstract_status'] = current.get('abstract_status')
    corrected['current_data_status'] = current.get('data_status')
    if available:
        corrected.update(
            corrected_status='resolved_abstract_available',
            article_level_abstract_availability='available',
            correction_reason='current_database_now_has_verified_abstract',
        )
        if source:
            corrected['verified_source'] = {
                'source_name': source.get('source_name'),
                'source_type': source.get('source_type'),
                'source_url': source.get('source_url'),
                'raw_id': source.get('raw_id'),
                'fetched_at': source.get('fetched_at'),
            }
    elif requires_publisher_review(prior.get('publisher')):
        corrected.update(
            corrected_status='publisher_page_review_pending',
            article_level_abstract_availability='unknown',
            correction_reason=(
                'publisher_family_access_constraint_is_not_article_level_'
                'evidence_of_abstract_unavailability'),
            review_requirement='browser_or_authorized_publisher_api',
            source_url=('https://doi.org/' + prior['doi'])
            if prior.get('doi') else None,
        )
    else:
        corrected.update(
            corrected_status='metadata_recheck_pending',
            article_level_abstract_availability='unknown',
            correction_reason=(
                'v1_publisher_substring_false_positive_or_current_generic_'
                'adapter_route'),
            review_requirement='verified_generic_publisher_probe',
            source_url=('https://doi.org/' + prior['doi'])
            if prior.get('doi') else None,
        )
    return corrected


def _open_readonly(path):
    conn = sqlite3.connect(
        f'file:{os.path.abspath(path)}?mode=ro', uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def run(results_path, db_path, output_path, summary_path):
    generated_at = utc_now()
    status_counts = Counter()
    publisher_counts = Counter()
    total = 0
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(summary_path)), exist_ok=True)

    with _open_readonly(db_path) as conn, open(
            output_path, 'x', encoding='utf-8', newline='\n') as output:
        for line_number, prior in read_blocked_results(results_path):
            row = conn.execute(
                """SELECT id,abstract,abstract_status,data_status
                   FROM astar_articles WHERE id=?""",
                (prior.get('article_id'),),
            ).fetchone()
            current = dict(row) if row else None
            source = None
            if current and current.get('abstract_status') != 'missing':
                source_row = conn.execute(
                    """SELECT source_name,source_type,source_url,raw_id,fetched_at
                       FROM astar_article_sources
                       WHERE article_id=?
                         AND source_type IN ('publisher_page','publisher_api')
                       ORDER BY fetched_at DESC,id DESC LIMIT 1""",
                    (prior.get('article_id'),),
                ).fetchone()
                source = dict(source_row) if source_row else None
            corrected = reclassify_result(
                prior, current, source=source, generated_at=generated_at)
            corrected['prior_results_line'] = line_number
            output.write(json.dumps(corrected, ensure_ascii=False) + '\n')
            total += 1
            status_counts[corrected['corrected_status']] += 1
            publisher_counts[prior.get('publisher') or ''] += 1
        output.flush()
        os.fsync(output.fileno())

    summary = {
        'success': True,
        'generated_at': generated_at,
        'source_results': os.path.abspath(results_path),
        'db_path': os.path.abspath(db_path),
        'output': os.path.abspath(output_path),
        'historical_status_reclassified': total,
        'corrected_status_counts': dict(sorted(status_counts.items())),
        'publisher_counts': dict(sorted(
            publisher_counts.items(), key=lambda item: (-item[1], item[0]))),
        'historical_results_modified': False,
        'database_modified': False,
        'supersedes': os.path.join(
            os.path.dirname(os.path.abspath(output_path)),
            'publisher_review_reclassification_v2.jsonl'),
    }
    with open(summary_path, 'x', encoding='utf-8') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return summary


def main():
    parser = argparse.ArgumentParser(
        description='Create a v2 publisher-review correction inventory')
    parser.add_argument('--results', default=DEFAULT_RESULTS)
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    parser.add_argument('--summary', default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    summary = run(args.results, args.db, args.output, args.summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
