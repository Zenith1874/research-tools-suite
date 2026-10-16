# -*- coding: utf-8 -*-
"""Read the confirmed job-market and placement pages into person observations.

Discovery found the addresses; this reads them. The two steps are separate on
purpose -- confirming that a page exists is not the same as knowing who is on
it, and the panel spent a while reporting the first as though it were the
second.

Every page produces a snapshot row whatever happens, carrying the parser's
verdict. A page that could not be read stores ``candidate_count = NULL``, never
0: of the five confirmed pages, only Stanford's job-market page is machine
readable, and recording the other four as zero would say those programmes have
nobody on the market.

Names are hashed into a stable internal key and discarded. ``display_name``
stays null -- public output is aggregate only.

Usage:
    python scripts/read_phd_pages.py
    python scripts/read_phd_pages.py --apply
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import raw_archive  # noqa: E402
from datetime import date  # noqa: E402
from services.faculty_jobs_market_cycle import current_cycle  # noqa: E402
from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)
from services.phd_page_discovery import _Discovery  # noqa: E402
from services.phd_pipeline import (  # noqa: E402
    LAYER_EXPLICIT_JMC, LAYER_PLACEMENT, person_key, record_snapshot,
)
from services.phd_roster_parser import STATUS_PARSED, parse  # noqa: E402

# Column on phd_program_sources -> (page kind for the snapshot, layer for people)
PAGE_COLUMNS = (
    ("jmc_url", "jmc", LAYER_EXPLICIT_JMC),
    ("placement_url", "placement", LAYER_PLACEMENT),
)


def confirmed_pages(conn):
    rows = conn.execute("""
        SELECT id, institution_name, jmc_url, placement_url
        FROM phd_program_sources
        WHERE jmc_url IS NOT NULL OR placement_url IS NOT NULL
        ORDER BY institution_name
    """).fetchall()
    pages = []
    for row in rows:
        for column, page_kind, layer in PAGE_COLUMNS:
            if row[column]:
                pages.append({"program_source_id": row["id"],
                              "institution": row["institution_name"],
                              "url": row[column], "page_kind": page_kind,
                              "layer": layer})
    return pages


def read_page(conn, page, adapter, cycle, *, archive=True):
    """Fetch, archive, parse and record one page. Returns the outcome."""
    outcome = {**page, "status": None, "count": None, "people": 0, "note": None}
    try:
        response = adapter.request(page["url"])
    except Exception as exc:  # noqa: BLE001 - not reading a page is an outcome
        outcome.update(status="unreachable",
                       note=f"{type(exc).__name__}: {str(exc)[:200]}")
        record_snapshot(conn, page["program_source_id"], page["page_kind"], cycle,
                        page["url"], parser_status="unreachable",
                        parser_note=outcome["note"])
        return outcome

    body = response.text or ""
    http_status = getattr(response, "status_code", None)
    content_hash = None
    if archive:
        try:
            # record_observation returns a record, not a digest.
            content_hash = raw_archive.record_observation(
                conn, kind=raw_archive.KIND_JMC if page["page_kind"] == "jmc"
                else raw_archive.KIND_PLACEMENT,
                source_url=page["url"], payload=body, http_status=http_status,
                parser_version="phd_roster_parser/1")["content_hash"]
        except Exception as exc:  # noqa: BLE001 - storage must not lose the read
            outcome["note"] = f"archive failed: {exc!r}"

    parsed = parse(body, page["url"], page["page_kind"])
    outcome.update(status=parsed["status"], count=parsed["count"],
                   note=parsed["note"] or outcome["note"])

    snapshot_id = record_snapshot(
        conn, page["program_source_id"], page["page_kind"], cycle, page["url"],
        http_status=http_status, content_hash=content_hash,
        candidate_count=parsed["count"],          # None unless actually parsed
        parser_status=parsed["status"], parser_note=parsed["note"])

    if parsed["status"] == STATUS_PARSED:
        for person in parsed["people"]:
            conn.execute("""
                INSERT INTO phd_person_observations
                  (snapshot_id, person_key, display_name, layer, field, evidence,
                   confidence)
                VALUES (?,?,NULL,?,?,?,?)
            """, (snapshot_id, person_key(page["institution"], person["name"]),
                  page["layer"], person.get("field"), person.get("evidence"),
                  "observed"))
        outcome["people"] = len(parsed["people"])
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--apply", action="store_true",
                        help="actually request and write; without it nothing happens")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    conn = open_read_only(args.db)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if int(version) != int(FACULTY_JOBS_SCHEMA_VERSION):
            raise SystemExit(f"schema user_version={version}, expected "
                             f"{FACULTY_JOBS_SCHEMA_VERSION}")
        pages = confirmed_pages(conn)
    finally:
        conn.close()

    print(f"confirmed pages to read: {len(pages)}")
    for page in pages:
        print(f"  {page['institution'][:28]:30}{page['page_kind']:11}{page['url'][:52]}")
    if not args.apply:
        print("\nno --apply: nothing was requested and nothing was written")
        return

    cycle = current_cycle(date.today())[1]
    inventory = preflight(args.db, "phd_page_read")
    outcomes = []
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        conn = sqlite3.connect(str(args.db), timeout=60)
        conn.row_factory = sqlite3.Row
        adapter = _Discovery(timeout=25)
        try:
            import time
            for page in pages:
                outcome = read_page(conn, page, adapter, cycle)
                outcomes.append(outcome)
                print(f"  {outcome['institution'][:26]:28}{outcome['page_kind']:11}"
                      f"{outcome['status']:15}people={outcome['people']}", flush=True)
                if args.sleep:
                    time.sleep(args.sleep)
            conn.commit()
        finally:
            conn.close()

    print("\n" + "=" * 68)
    by_status = {}
    for outcome in outcomes:
        by_status[outcome["status"]] = by_status.get(outcome["status"], 0) + 1
    for status, count in sorted(by_status.items(), key=lambda kv: -kv[1]):
        print(f"  {status:16}{count}")
    print(f"  people recorded: {sum(o['people'] for o in outcomes)}")
    print("\nA page that could not be read stores no count. Only Stanford's "
          "job-market page is machine readable today; the others are a "
          "JavaScript shell or a landing page, which is not the same as a "
          "programme having nobody on the market.")
    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
