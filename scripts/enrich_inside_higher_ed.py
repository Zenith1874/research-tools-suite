#!/usr/bin/env python3
"""Bounded public detail-page enrichment for existing Inside Higher Ed records."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.faculty_jobs_service import FACULTY_DB_PATH, enrich_inside_higher_ed_details
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-job-id', action='append', dest='source_job_ids',
                        help='specific public IHE job id; repeat for a small targeted repair')
    parser.add_argument('--max-records', type=int, default=25,
                        help='maximum existing detail pages to request (default: 25)')
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--delay', type=float, default=0.75,
                        help='delay after each successful detail request in seconds')
    parser.add_argument('--include-known', action='store_true',
                        help='also revisit records that already have an institution entity')
    args = parser.parse_args(argv)
    inventory = preflight(str(FACULTY_DB_PATH), "inside_higher_ed_detail_enrichment")
    with guarded_write():
        result = enrich_inside_higher_ed_details(
            source_job_ids=args.source_job_ids,
            max_records=max(0, min(1000, args.max_records)),
            timeout=max(3, min(120, args.timeout)),
            delay=max(0.25, args.delay),
            include_known=args.include_known,
        )
    postflight(str(FACULTY_DB_PATH), inventory)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
