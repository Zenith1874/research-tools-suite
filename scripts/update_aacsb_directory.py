#!/usr/bin/env python3
"""Opt-in bounded AACSB roster import and official-school job scan."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.faculty_jobs_service import scan_aacsb_official_websites, update_aacsb_directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=110)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--max-details", type=int)
    parser.add_argument("--max-schools", type=int)
    parser.add_argument("--scan-websites", action="store_true")
    parser.add_argument("--refresh-details", action="store_true")
    parser.add_argument("--no-details", action="store_true")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.45)
    parser.add_argument("--max-jobs-per-school", type=int, default=20)
    parser.add_argument("--site-max-pages", type=int, default=2,
                        help="maximum public career pages per school; explicit bounded budget")
    parser.add_argument("--scan-existing", action="store_true", help="scan existing AACSB rows without refetching the roster")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--include-checked", action="store_true", help="allow a scan of rows already checked")
    args = parser.parse_args(argv)

    def progress(message):
        print(message, flush=True)

    if args.scan_existing:
        result = scan_aacsb_official_websites(
            max_schools=max(1, min(2000, args.max_schools or 25)),
            offset=max(0, args.offset), include_checked=args.include_checked,
            timeout=max(3, min(120, args.timeout)),
            delay=max(0.1, min(10.0, args.delay)),
            max_jobs_per_school=max(1, min(100, args.max_jobs_per_school)),
            site_max_pages=max(1, min(8, args.site_max_pages)),
            progress=progress,
        )
    else:
        result = update_aacsb_directory(
            max_pages=max(1, min(150, args.max_pages)),
            max_records=args.max_records,
            fetch_details=not args.no_details,
            refresh_details=args.refresh_details,
            scan_websites=args.scan_websites,
            max_details=args.max_details,
            max_schools=args.max_schools,
            timeout=max(3, min(120, args.timeout)),
            delay=max(0.1, min(10.0, args.delay)),
            max_jobs_per_school=max(1, min(100, args.max_jobs_per_school)),
            site_max_pages=max(1, min(8, args.site_max_pages)),
            progress=progress,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
