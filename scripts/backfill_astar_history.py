#!/usr/bin/env python3
"""Extend the existing article corpus with a private, resumable history run."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_history_service import HistoryRunner, init_run, status_run


def load_source_settings():
    """Read only relevant source settings; never log credentials or load LLM keys."""
    path = ROOT / ".secrets"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.strip() in ("OPENALEX_API_KEY", "ASTAR_MAILTO"):
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "run", "status", "report", "replay-new-metadata"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--from-year", type=int, default=2010)
    parser.add_argument("--to-date")
    parser.add_argument("--journal-scope-file", type=Path)
    parser.add_argument("--sources", default="crossref,openalex")
    parser.add_argument("--crossref-workers", type=int, default=2)
    parser.add_argument("--crossref-page-size", type=int, default=1000)
    parser.add_argument("--openalex-page-size", type=int, default=100)
    parser.add_argument("--openalex-reserve", type=int, default=100)
    parser.add_argument("--sqlite-identities", action="store_true",
                        help="Use indexed SQL identity lookups instead of a full-corpus Python cache")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_source_settings()
    if args.action == "init":
        result = init_run(args.run_dir, args.db, args.from_year, args.to_date, args.journal_scope_file)
    elif args.action == "status":
        result = status_run(args.run_dir)
    else:
        if not 1 <= args.crossref_workers <= 3:
            parser.error("crossref workers must be between 1 and 3")
        if not 1 <= args.crossref_page_size <= 1000 or not 1 <= args.openalex_page_size <= 100:
            parser.error("invalid source page size")
        sources = tuple(source.strip() for source in args.sources.split(","))
        if not sources or any(source not in ("crossref", "openalex") for source in sources):
            parser.error("sources must be crossref and/or openalex")
        # An OS file lock releases on process exit and survives restart safely.
        lock_path = args.run_dir.resolve() / "runner.lock"
        lock_stream = None
        if args.action in ("run", "replay-new-metadata"):
            lock_stream = lock_path.open("a+b")
            lock_stream.seek(0, 2)
            if not lock_stream.tell():
                lock_stream.write(b"\0")
                lock_stream.flush()
            lock_stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock_stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock_stream.close()
                parser.error("another process owns this run's OS lock")
        runner = HistoryRunner(args.run_dir, args.crossref_page_size, args.openalex_page_size, args.openalex_reserve,
                               sqlite_identities=args.sqlite_identities)
        try:
            if args.action == "run":
                result = runner.run(sources, args.crossref_workers)
            elif args.action == "replay-new-metadata":
                result = runner.replay_new_metadata()
            else:
                result = runner.report(force=True)
        finally:
            runner.close()
            if lock_stream is not None:
                lock_stream.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
