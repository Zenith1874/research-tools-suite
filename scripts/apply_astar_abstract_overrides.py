#!/usr/bin/env python3
"""Apply verified public publisher abstracts to the A* research database.

The overrides file is a small, reviewable provenance record.  This command
does not scrape publisher pages or fetch paywalled full text.
"""
import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OVERRIDES = os.path.join(ROOT, 'data', 'astar_verified_abstract_overrides.json')
sys.path.insert(0, ROOT)

from services.abdc_astar_research_service import apply_verified_publisher_abstract


def load_overrides(path):
    with open(path, encoding='utf-8') as handle:
        records = json.load(handle)
    if not isinstance(records, list):
        raise ValueError('override file must contain a JSON list')
    return records


def main():
    parser = argparse.ArgumentParser(
        description='Apply source-verified publisher-page abstracts')
    parser.add_argument('--overrides', default=DEFAULT_OVERRIDES,
                        help='JSON override file')
    parser.add_argument('--doi', default=None,
                        help='Apply only this DOI (default: all records)')
    parser.add_argument('--db', default=None,
                        help='Optional SQLite database path')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate and classify, then roll back database changes')
    args = parser.parse_args()

    requested_doi = (args.doi or '').strip().lower()
    records = load_overrides(args.overrides)
    if requested_doi:
        records = [r for r in records
                   if (r.get('doi') or '').strip().lower() == requested_doi]
        if not records:
            raise SystemExit(f'No override found for DOI {requested_doi}')

    results = []
    for record in records:
        results.append(apply_verified_publisher_abstract(
            doi=record.get('doi'),
            abstract=record.get('abstract'),
            source_url=record.get('source_url'),
            source_name=record.get('source_name') or 'Publisher abstract page',
            source_id=record.get('source_id'),
            verified_at=record.get('verified_at'),
            verification_notes=record.get('verification_notes'),
            expected_title=record.get('title'),
            source_type=record.get('source_type') or 'publisher_page',
            db_path=args.db,
            dry_run=args.dry_run,
        ))
    print(json.dumps({'success': True, 'count': len(results), 'results': results},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
