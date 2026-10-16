#!/usr/bin/env python3
"""Bounded public-source update for the Academic Career private database."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.faculty_jobs_service import FACULTY_DB_PATH, update_faculty_jobs
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', action='append', dest='sources', help='source name; repeat to select a subset')
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--max-pages', type=int, default=1)
    parser.add_argument('--detail-pages', type=int, default=12,
                        help='bounded public detail-page budget for adapters that support detail enrichment')
    args = parser.parse_args(argv)
    # HigherEdJobs currently needs roughly 113 listing pages for its Business
    # category. The default remains one page and that adapter is opt-in, so a
    # large complete scan still requires an explicit source and page budget.
    # Integrity, inventory and a unique backup, in that order, before the
    # crawl is allowed to migrate or write anything.
    inventory = preflight(str(FACULTY_DB_PATH), 'scheduled_source_update')
    with guarded_write():
        result = update_faculty_jobs(
            source_names=args.sources,
            timeout=max(3, min(120, args.timeout)),
            max_pages=max(1, min(150, args.max_pages)),
            detail_budget=max(0, min(1000, args.detail_pages)),
        )
    # Raises if a preserved or private table lost rows, or if the schema
    # drifted from the migration ledger.
    postflight(str(FACULTY_DB_PATH), inventory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
