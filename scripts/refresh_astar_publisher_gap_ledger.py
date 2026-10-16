#!/usr/bin/env python3
"""Refresh source-gap counts while preserving the original probe evidence."""

import argparse
import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup


def refresh(prior_path, journals_path, db_path, cessation_path, output):
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    journals = {row['journal_title']: row for row in json.loads(journals_path.read_text(encoding='utf-8'))}
    receipt = json.loads(cessation_path.read_text(encoding='utf-8'))
    raw = Path(receipt['raw_path'])
    if not raw.is_absolute():
        raw = Path(__file__).resolve().parents[1] / raw
    import hashlib
    if hashlib.sha256(raw.read_bytes()).hexdigest() != receipt['sha256']:
        raise ValueError('The original cessation evidence changed')
    text = ' '.join(BeautifulSoup(gzip.decompress(raw.read_bytes()), 'html.parser').get_text(' ', strip=True).split())
    if receipt['explicit_cessation_year'] != 2003 or 'ceased publication in 2003' not in text.lower():
        raise ValueError('The source does not prove the asserted cessation year')
    conn = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True)
    records = []
    try:
        for original in prior['records']:
            row = dict(original)
            journal = journals[row['journal_title']]
            issns = sorted({journal.get(key) for key in ('issn_print', 'issn_online') if journal.get(key)})
            if not issns:
                raise ValueError('Missing scope ISSN')
            row['visible_records_now'] = conn.execute(
                'SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0 AND journal_issn IN (' +
                ','.join('?' for _ in issns) + ')', issns).fetchone()[0]
            row['status'] = 'PUBLIC_METADATA_IMPORTED_PARTIAL' if row['visible_records_now'] else 'PUBLIC_METADATA_GAP_REMAINS'
            if row['journal_title'] == 'Journal of the Royal Statistical Society, Series D (The Statistician)':
                row.update(status='OUTSIDE_2010_ONWARD_PERIOD_CONFIRMED',
                           explicit_cessation_year=2003, cessation_evidence_path=str(cessation_path),
                           cessation_source_url=receipt['source_url'], journal_retained_in_official_scope=True)
            records.append(row)
    finally:
        conn.close()
    result = {'created_at': datetime.now(timezone.utc).isoformat(),
        'prior_ledger_path': str(prior_path), 'prior_ledger_sha256': hashlib.sha256(prior_path.read_bytes()).hexdigest(),
        'source_gap_queries_are_not_missing_article_counts': True, 'records': records,
        'article_database_writes': 0, 'full_goal_complete': False}
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'ledger.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return {'output': str(output), 'initial_zero_source_journals': len(records),
        'partial_metadata_journals': sum(row['status'] == 'PUBLIC_METADATA_IMPORTED_PARTIAL' for row in records),
        'zero_public_metadata_journals': sum(row['status'] == 'PUBLIC_METADATA_GAP_REMAINS' for row in records),
        'outside_period_journals': sum(row['status'] == 'OUTSIDE_2010_ONWARD_PERIOD_CONFIRMED' for row in records)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior-ledger', type=Path, required=True)
    parser.add_argument('--journals', type=Path, required=True)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--cessation-evidence', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(refresh(args.prior_ledger.resolve(), args.journals.resolve(), args.db.resolve(),
                             args.cessation_evidence.resolve(), args.output_dir.resolve()), indent=2))
