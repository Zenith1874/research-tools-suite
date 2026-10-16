#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed and scan the IPEDS doctoral-university recruitment portal registry.

The registry is a local derived SQLite database.  It does not modify
``data/academic_market.db`` or ``data/faculty_jobs.db``.  Use ``--seed`` once,
then run bounded ``--scan`` batches; a later scan resumes with website groups
that do not yet have an observation under the current rule version.

Examples::

    python scripts/seed_ipeds_recruitment_registry.py --seed
    python scripts/seed_ipeds_recruitment_registry.py --scan --max-websites 10 \
        --max-portals 2 --delay 0.5
    python scripts/seed_ipeds_recruitment_registry.py --status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.ipeds_recruitment_registry import (
    DEFAULT_EXPORT_CSV,
    DEFAULT_REGISTRY_DB,
    DEFAULT_SOURCE_DB,
    export_registry_csv,
    registry_summary,
    scan_registry,
    seed_registry,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--seed", action="store_true", help="seed from IPEDS HD C21BASIC")
    action.add_argument("--scan", action="store_true", help="scan a bounded website batch")
    action.add_argument("--status", action="store_true", help="print registry counts")
    action.add_argument("--export-csv", action="store_true",
                        help="export one row per IPEDS target institution")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB))
    parser.add_argument("--registry-db", default=str(DEFAULT_REGISTRY_DB))
    parser.add_argument("--data-year", type=int, default=2023)
    parser.add_argument("--include-outlying-areas", action="store_true",
                        help="include PR, VI, GU, AS and MP in the seed")
    parser.add_argument("--max-websites", type=int, default=25)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--include-checked", action="store_true",
                        help="re-observe groups already checked by this rule")
    parser.add_argument("--only-host", action="append", default=[],
                        help="recheck one website group; may be repeated or comma-separated")
    parser.add_argument("--max-portals", type=int, default=3,
                        help="maximum discovered recruitment pages to fetch per site")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.75,
                        help="minimum pause after each public page request")
    parser.add_argument("--progress-every", type=int, default=1,
                        help="print every Nth site during a scan; final site is always printed")
    parser.add_argument("--output-csv", default=str(DEFAULT_EXPORT_CSV),
                        help="CSV output path used with --export-csv")
    parser.add_argument("--overwrite-output", action="store_true",
                        help="allow replacing an existing CSV export")
    args = parser.parse_args(argv)

    if args.seed:
        result = seed_registry(
            args.source_db, args.registry_db, data_year=args.data_year,
            include_outlying_areas=args.include_outlying_areas,
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
            args.registry_db, max_websites=args.max_websites, offset=args.offset,
            include_checked=args.include_checked, timeout=args.timeout,
            delay=args.delay, max_portals=args.max_portals, only_hosts=only_hosts,
            progress=progress,
        )
    elif args.export_csv:
        result = export_registry_csv(
            args.registry_db, args.output_csv, overwrite=args.overwrite_output,
        )
    else:
        result = registry_summary(args.registry_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
