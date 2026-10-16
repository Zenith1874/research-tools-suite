#!/usr/bin/env python3
"""Add lookup indexes between writer transactions, with bounded lock holds."""

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

INDEXES = [
    ("idx_astar_openalex_id", "CREATE INDEX IF NOT EXISTS idx_astar_openalex_id ON astar_articles(openalex_id)"),
    ("idx_astar_publisher_raw_identity", "CREATE INDEX IF NOT EXISTS idx_astar_publisher_raw_identity ON astar_article_sources(raw_id,article_id) WHERE source_type='publisher_metadata'"),
    ("idx_astar_ejtr_publisher_urls", "CREATE INDEX IF NOT EXISTS idx_astar_ejtr_publisher_urls ON astar_articles(url,landing_page_url,id) WHERE journal_title='eJournal of Tax Research'"),
    ("idx_astar_journal_visible", "CREATE INDEX IF NOT EXISTS idx_astar_journal_visible ON astar_articles(journal_issn) WHERE is_duplicate=0"),
]


def now():
    return datetime.now(timezone.utc).isoformat()


def build_indexes(db_path, output_dir, hold_seconds=5.0):
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump({"created_at": now(), "pid": os.getpid(), "db_path": str(db_path),
                   "max_ddl_attempt_seconds": hold_seconds, "indexes": [item[0] for item in INDEXES],
                   "article_rows_modified": False, "source_rows_modified": False}, stream, indent=2)
    last_message = 0
    with (output_dir / "attempts.jsonl").open("x", encoding="utf-8") as log:
        for name, sql in INDEXES:
            while True:
                conn = sqlite3.connect(db_path, timeout=1)
                # A 2 MiB default cache repeatedly rereads a multi-GiB corpus.
                # These settings affect only this maintenance connection.
                conn.execute("PRAGMA cache_size=-65536")
                # Large sorts stay on disk while the independent semantic job runs.
                conn.execute("PRAGMA temp_store=FILE")
                started = time.monotonic()
                try:
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone():
                        break
                    conn.execute("BEGIN IMMEDIATE")
                    deadline = time.monotonic() + hold_seconds
                    conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
                    conn.execute(sql)
                    conn.set_progress_handler(None, 0)
                    conn.commit()
                    entry = {"at": now(), "index": name, "status": "CREATED", "seconds": round(time.monotonic() - started, 3)}
                    log.write(json.dumps(entry) + "\n"); log.flush()
                    print(json.dumps(entry), flush=True)
                    break
                except sqlite3.OperationalError as error:
                    conn.set_progress_handler(None, 0)
                    conn.rollback()
                    if str(error) not in ("database is locked", "database table is locked", "interrupted"):
                        raise
                    entry = {"at": now(), "index": name, "status": "DEFERRED", "reason": str(error),
                             "seconds": round(time.monotonic() - started, 3)}
                    log.write(json.dumps(entry) + "\n"); log.flush()
                    if time.monotonic() - last_message >= 120:
                        print(json.dumps(entry), flush=True); last_message = time.monotonic()
                finally:
                    conn.close()
                time.sleep(15)
    conn = sqlite3.connect(db_path)
    try:
        plan = [list(row) for row in conn.execute("EXPLAIN QUERY PLAN SELECT id,doi FROM astar_articles WHERE openalex_id IN (?,?,?) ORDER BY id", ("W1", "W1", "https://openalex.org/W1"))]
        result = {"finished_at": now(), "indexes": [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")],
                  "openalex_lookup_plan": plan, "article_rows_modified": False, "source_rows_modified": False}
        if not any("idx_astar_openalex_id" in str(row) for row in plan):
            raise RuntimeError("OpenAlex lookup does not use the new index")
        count_plan = [list(row) for row in conn.execute('''EXPLAIN QUERY PLAN
            SELECT j.id,COUNT(a.id) FROM abdc_astar_journals j
            LEFT JOIN astar_articles a ON (a.journal_issn=j.issn_print OR a.journal_issn=j.issn_online)
              AND a.is_duplicate=0 WHERE j.abdc_version=? GROUP BY j.id''', ('2025',))]
        result['journal_visible_count_plan'] = count_plan
        if not any('idx_astar_journal_visible' in str(row) for row in count_plan):
            raise RuntimeError('Journal counts do not use the visible-article index')
        with (output_dir / "verification.json").open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
        return result
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-hold-seconds", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.max_hold_seconds <= 600:
        parser.error("DDL attempts must be bounded to 1-600 seconds")
    print(json.dumps(build_indexes(args.db_path.resolve(), args.output_dir.resolve(), args.max_hold_seconds), indent=2))


if __name__ == "__main__":
    main()
