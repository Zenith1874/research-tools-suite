# -*- coding: utf-8 -*-
"""One bounded batch of HigherEdJobs detail pages: collect, then import.

The board serves detail pages to an ordinary browser but rate-limits by
reputation, not by request spacing: a session gets roughly 60-90 pages before
it starts being handed interstitials, and slowing down does not buy more. What
buys more is time -- the reputation recovers over hours.

So full coverage is an incremental job, not a long run. This does one batch and
stops, and is safe to run repeatedly: the collector skips postings it has
already read and retries ones that were challenged, and the importer only
writes a body longer than what is stored.

Run it a few times a day and the backlog drains; run it in a loop and the board
will simply refuse, which the collector detects and reports rather than
pushing through.

Usage:
    python scripts/hej_detail_batch.py                 # collect + import 60
    python scripts/hej_detail_batch.py --size 40 --collect-only
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

URLS = ROOT / "outputs" / "hej_detail_urls.json"
JSONL = ROOT / "outputs" / "hej_details.jsonl"


def refresh_urls(db_path=None):
    """Rebuild the target list from the database, thinnest bodies first."""
    import sqlite3
    from services.faculty_jobs_service import FACULTY_DB_PATH
    path = db_path or FACULTY_DB_PATH
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT js.source_job_id, js.source_url,
                   LENGTH(j.description_excerpt) AS have
            FROM job_sources js JOIN sources s ON s.id = js.source_id
            JOIN jobs j ON j.id = js.job_id
            WHERE s.name = 'higheredjobs' AND js.active = 1
              AND js.source_url IS NOT NULL AND js.source_url != ''
            ORDER BY have ASC, js.source_job_id
        """).fetchall()
    finally:
        conn.close()
    URLS.parent.mkdir(parents=True, exist_ok=True)
    URLS.write_text(json.dumps(
        [{"source_job_id": r["source_job_id"], "source_url": r["source_url"]}
         for r in rows], ensure_ascii=False), encoding="utf-8")
    return len(rows)


def progress():
    """How much of the backlog has a body, from the collector's own output."""
    if not JSONL.exists():
        return {"read": 0, "challenged": 0}
    read = challenged = 0
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            status = json.loads(line).get("status")
        except json.JSONDecodeError:
            continue
        if status == "ok":
            read += 1
        elif status == "challenged":
            challenged += 1
    return {"read": read, "challenged": challenged}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=60,
                        help="postings to attempt this batch")
    parser.add_argument("--delay", type=int, default=2500,
                        help="milliseconds between pages")
    parser.add_argument("--offscreen", action="store_true",
                        help="park the browser window off-screen (for scheduled runs)")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--import-only", action="store_true")
    args = parser.parse_args()

    total = refresh_urls()
    before = progress()
    print(f"targets {total}; already read {before['read']}, "
          f"challenged-and-retryable {before['challenged']}")

    if not args.import_only:
        result = subprocess.run(
            ["node", str(ROOT / "scripts" / "collect_higheredjobs_details_cdp.mjs"),
             "--urls", str(URLS), "--out", str(JSONL),
             "--limit", str(args.size), "--delay", str(args.delay),
             *(["--offscreen"] if args.offscreen else [])],
            cwd=str(ROOT))
        if result.returncode != 0:
            print("collector exited non-zero; importing whatever it did write")
    after = progress()
    print(f"collected this batch: {after['read'] - before['read']} pages")

    if args.collect_only:
        return
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "import_hej_details.py"),
         str(JSONL), "--apply"], cwd=str(ROOT))


if __name__ == "__main__":
    main()
