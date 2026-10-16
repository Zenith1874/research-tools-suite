#!/usr/bin/env python3
"""Preview Carnegie coverage, or explicitly scan and ingest one guarded batch."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.faculty_jobs_service import FACULTY_DB_PATH, update_faculty_jobs
from services.faculty_jobs_sources.carnegie import CarnegieOfficialAdapter, RecordedCarnegieAdapter, source_coverage
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Allow bounded HTTP scan and guarded production ingestion")
    parser.add_argument("--max-portals", type=int, default=5, choices=range(1, 26), metavar="1..25")
    parser.add_argument("--offset", type=int, default=None, help="Explicit eligible-list offset; default is unvisited/oldest")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--detail-pages", type=int, default=10, help="Total detail request budget (at most 2 per portal)")
    parser.add_argument("--reviewed-postings", type=Path,
                        help="Reviewed official CSU seed manifest; preview fetches and archives evidence without production writes")
    parser.add_argument("--from-archive", action="store_true", help="Import fresh archived scan observations without another network scan")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()
    if args.reviewed_postings:
        from services.faculty_jobs_sources.carnegie_reviewed import CarnegieReviewedPageUpAdapter
        adapter = CarnegieReviewedPageUpAdapter(args.reviewed_postings)
    elif args.from_archive:
        adapter = RecordedCarnegieAdapter()
    else:
        adapter = CarnegieOfficialAdapter(offset=args.offset)
    if not args.apply and args.reviewed_postings:
        response = adapter.fetch()
        print(json.dumps({"preview": [
            {"title": job.title_raw, "institution": job.institution_raw,
             "url": job.official_url, "unitid": job.extra["unitid"]}
            for job in response.jobs], "notes": response.notes}, ensure_ascii=False, indent=2))
        return 0
    if not args.apply:
        print(json.dumps(source_coverage(), ensure_ascii=False, indent=2))
        return 0
    inventory = preflight(args.db, "carnegie_source_update")
    try:
        with guarded_write():
            result = update_faculty_jobs(
                db_path=args.db,
                source_names=[adapter.name], adapters=[adapter],
                timeout=max(3, min(60, args.timeout)), max_pages=args.max_portals,
                detail_budget=max(0, min(50, args.detail_pages)))
    finally:
        postflight(args.db, inventory)
    print(json.dumps({"ingestion": result, "coverage": source_coverage()}, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
