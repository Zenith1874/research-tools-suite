#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed, scan, and export the Carnegie 2025 recruitment registry.

Default scope: current Carnegie R2 plus a documented four-year
teaching-oriented proxy.  The registry is separate from the legacy IPEDS
doctoral registry and from ``faculty_jobs.db``.

Examples::

    python scripts/seed_carnegie_recruitment_registry.py --download --seed
    python scripts/seed_carnegie_recruitment_registry.py --scan --max-websites 25
    python scripts/seed_carnegie_recruitment_registry.py --status
    python scripts/seed_carnegie_recruitment_registry.py --export-csv --overwrite-output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.carnegie_recruitment_registry import (
    DEFAULT_EXPORT_CSV,
    DEFAULT_PUBLIC_FILE,
    DEFAULT_RAD_FILE,
    DEFAULT_REGISTRY_DB,
    DEFAULT_SOURCE_DB,
    download_carnegie_sources,
    export_registry_csv,
    registry_summary,
    scan_registry,
    seed_registry,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--seed", action="store_true",
                        help="seed targets from the local official XLSX files")
    action.add_argument("--scan", action="store_true",
                        help="scan a bounded batch of official websites")
    action.add_argument("--status", action="store_true",
                        help="print registry counts")
    action.add_argument("--export-csv", action="store_true",
                        help="export one row per target institution")
    parser.add_argument("--download", action="store_true",
                        help="download the two official Carnegie 2025 XLSX files before the selected action")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB))
    parser.add_argument("--public-file", default=str(DEFAULT_PUBLIC_FILE))
    parser.add_argument("--rad-file", default=str(DEFAULT_RAD_FILE))
    parser.add_argument("--registry-db", default=str(DEFAULT_REGISTRY_DB))
    parser.add_argument("--include-business-focused", action="store_true",
                        help="also include Special Focus: Business (optional extension)")
    parser.add_argument("--no-validate-release", action="store_true",
                        help="allow fixture/non-current source row counts for testing")
    parser.add_argument("--refresh-sources", action="store_true",
                        help="overwrite existing raw Carnegie XLSX files with a fresh download")
    parser.add_argument("--max-websites", type=int, default=25)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--include-checked", action="store_true",
                        help="re-observe groups already checked by this rule")
    parser.add_argument("--only-host", action="append", default=[],
                        help="recheck one website group; may be repeated or comma-separated")
    parser.add_argument("--max-portals", type=int, default=3,
                        help="maximum discovered recruitment pages per site")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.75,
                        help="minimum pause after each public page request")
    parser.add_argument("--progress-every", type=int, default=1,
                        help="print every Nth site during a scan")
    parser.add_argument("--output-csv", default=str(DEFAULT_EXPORT_CSV))
    parser.add_argument("--overwrite-output", action="store_true",
                        help="allow replacing an existing CSV")
    args = parser.parse_args(argv)

    download_result = None
    if args.download:
        download_result = download_carnegie_sources(
            public_path=args.public_file,
            rad_path=args.rad_file,
            overwrite=args.refresh_sources,
        )
    if args.seed:
        result = seed_registry(
            source_db=args.source_db,
            registry_db=args.registry_db,
            public_file=args.public_file,
            rad_file=args.rad_file,
            include_business_focused=args.include_business_focused,
            validate_release=not args.no_validate_release,
        )
    elif args.scan:
        def progress(item):
            every = max(1, int(args.progress_every))
            if item["index"] != item["total"] and item["index"] % every:
                return
            print(
                f"[{item['index']}/{item['total']}] {item['website_group_key']} "
                f"{item['status']} portals={item['portals_found']} "
                f"pages={item['pages_fetched']}",
                flush=True,
            )

        only_hosts = []
        for item in args.only_host:
            only_hosts.extend(part.strip() for part in item.split(",") if part.strip())
        result = scan_registry(
            registry_db=args.registry_db,
            max_websites=args.max_websites,
            offset=args.offset,
            include_checked=args.include_checked,
            timeout=args.timeout,
            delay=args.delay,
            max_portals=args.max_portals,
            only_hosts=only_hosts,
            progress=progress,
        )
    elif args.export_csv:
        result = export_registry_csv(
            registry_db=args.registry_db,
            output_path=args.output_csv,
            overwrite=args.overwrite_output,
        )
    elif args.status:
        result = registry_summary(args.registry_db)
    elif download_result is not None:
        result = download_result
    else:
        result = registry_summary(args.registry_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
