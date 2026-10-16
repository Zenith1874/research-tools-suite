#!/usr/bin/env python3
"""Collect and import separately checkpointed A-journal OpenAlex scope supplements."""

import argparse
import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.astar_openalex_scope_supplement import (
    SupplementCollector, import_collected, initialize,
)


@contextmanager
def exclusive_runner(directory):
    path = Path(directory) / "runner.lock"
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "collect", "import", "status"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--primary-run", type=Path, action="append")
    parser.add_argument("--import-run", type=Path)
    parser.add_argument("--expected-journals", type=int)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--openalex-reserve", type=int, default=1500)
    parser.add_argument("--sqlite-identities", action="store_true",
                        help="import with indexed SQL identity lookups instead of full-corpus caches")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.action == "init":
        if not args.primary_run:
            parser.error("init requires one or more --primary-run arguments")
        result = initialize(args.output_dir, args.primary_run, args.expected_journals, args.page_size)
    elif args.action == "status":
        collector = SupplementCollector(args.output_dir, args.openalex_reserve)
        try:
            result = collector.status()
        finally:
            collector.close()
    else:
        with exclusive_runner(args.output_dir):
            if args.action == "import":
                if not args.import_run:
                    parser.error("import requires --import-run")
                result = import_collected(args.output_dir, args.import_run, args.sqlite_identities)
            else:
                collector = SupplementCollector(args.output_dir, args.openalex_reserve)
                try:
                    result = collector.collect()
                finally:
                    collector.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
