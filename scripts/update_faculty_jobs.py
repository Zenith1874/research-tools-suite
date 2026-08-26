#!/usr/bin/env python3
"""Bounded public-source update for the Academic Career private database."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.faculty_jobs_service import update_faculty_jobs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', dest='sources', help='source name; repeat to select a subset')
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--max-pages', type=int, default=1)
    parser.add_argument('--detail-pages', type=int, default=12,
                        help='bounded public detail-page budget for adapters that support detail enrichment')
    args = parser.parse_args(argv)
    # Five pages was too small for the current public Inside Higher Ed query
    # (42 pages).  The adapter itself keeps a hard upper bound and the default
    # remains one page, so a full scan is still explicit and auditable.
    result = update_faculty_jobs(
        source_names=args.sources,
        timeout=max(3, min(120, args.timeout)),
        max_pages=max(1, min(50, args.max_pages)),
        detail_budget=max(0, min(1000, args.detail_pages)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
