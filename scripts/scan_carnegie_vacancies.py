#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan a bounded batch of Carnegie official recruitment portals for public vacancies.

Examples::

    python scripts/scan_carnegie_vacancies.py --estimate
    python scripts/scan_carnegie_vacancies.py --scan --max-portals 100 --max-detail-pages 2
    python scripts/scan_carnegie_vacancies.py --status
    python scripts/scan_carnegie_vacancies.py --export-csv --overwrite-output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.carnegie_vacancy_scan import (
    DEFAULT_EXPORT_CSV,
    DEFAULT_REGISTRY_DB,
    DEFAULT_SCAN_DB,
    export_scan_csv,
    scan_summary,
    scan_vacancies,
    select_portals,
)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--scan", action="store_true", help="scan a bounded portal batch")
    action.add_argument("--estimate", action="store_true", help="show selection counts without network requests")
    action.add_argument("--status", action="store_true", help="print isolated scan database counts")
    action.add_argument("--export-csv", action="store_true", help="export accepted vacancy records from the latest run")
    parser.add_argument("--registry-db", default=str(DEFAULT_REGISTRY_DB))
    parser.add_argument("--scan-db", default=str(DEFAULT_SCAN_DB))
    parser.add_argument("--output-csv", default=str(DEFAULT_EXPORT_CSV))
    parser.add_argument("--max-portals", type=int, default=100,
                        help="maximum selected portal pages for this run")
    parser.add_argument("--offset", type=int, default=0,
                        help="offset within the deterministic selected-portal order")
    parser.add_argument("--include-low-signal", action="store_true",
                        help="include readable but lower-signal HR/central pages")
    parser.add_argument("--max-detail-pages", type=int, default=2,
                        help="maximum public detail pages fetched per portal")
    parser.add_argument("--max-jobs", type=int, default=40,
                        help="maximum accepted candidates retained per portal")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.75,
                        help="minimum pause after each public page request")
    parser.add_argument("--progress-every", type=int, default=1)
    parser.add_argument("--run-id", type=int, default=None,
                        help="run id to export instead of the latest run")
    parser.add_argument("--run-ids", type=int, nargs="+", default=None,
                        help="multiple run ids to export together")
    parser.add_argument("--deduplicate", action="store_true",
                        help="when exporting multiple runs, keep one row per official URL")
    parser.add_argument("--overwrite-output", action="store_true")
    args = parser.parse_args(argv)

    if args.estimate:
        result = select_portals(
            args.registry_db, max_portals=args.max_portals, offset=args.offset,
            include_low_signal=args.include_low_signal,
        )
        result = {
            "registry_db": args.registry_db,
            "selection_rule_version": result["selection_rule_version"],
            "all_active_portals": len(result["all_portals"]),
            "eligible_count": result["eligible_count"],
            "selected_count": result["selected_count"],
            "target_institutions": result["target_institutions"],
            "by_kind": result["by_kind"],
            "excluded_by_reason": result["excluded_by_reason"],
            "selected_preview": [
                {
                    "website_group_key": row["website_group_key"],
                    "portal_kind": row["portal_kind"],
                    "score": row["score"],
                    "url": row["canonical_url"],
                    "title": row.get("latest_title"),
                    "target_count": len(row["target_rows"]),
                }
                for row in result["selected"][:20]
            ],
        }
    elif args.scan:
        def progress(item):
            every = max(1, int(args.progress_every))
            if item["index"] != item["total"] and item["index"] % every:
                return
            print(
                f"[{item['index']}/{item['total']}] {item['website_group_key']} "
                f"{item['status']} jobs={item['jobs_found']} requests={item['requests']}",
                flush=True,
            )

        result = scan_vacancies(
            registry_db=args.registry_db, scan_db=args.scan_db,
            max_portals=args.max_portals, offset=args.offset,
            include_low_signal=args.include_low_signal, timeout=args.timeout,
            delay=args.delay, max_detail_pages=args.max_detail_pages,
            max_jobs=args.max_jobs, progress=progress,
        )
    elif args.export_csv:
        result = export_scan_csv(
            scan_db=args.scan_db, output_path=args.output_csv, run_id=args.run_id,
            run_ids=args.run_ids, deduplicate=args.deduplicate,
            overwrite=args.overwrite_output,
        )
    elif args.status:
        result = scan_summary(args.scan_db)
    else:
        result = scan_summary(args.scan_db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
