#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the retained-raw, idempotent Hong Kong macro remediation migration.

The caller is responsible for creating and verifying a consistent SQLite
backup before invoking this script.  No network request is made: P0 repairs
reuse the raw snapshots already recorded in the database source registry.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.hong_kong_macro_service import (
    ROOT,
    apply_hong_kong_macro_final_remediation_migration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(ROOT / 'pboc_data.db'),
                        help='SQLite database to migrate (default: project pboc_data.db)')
    parser.add_argument('--output', help='Optional JSON report path')
    args = parser.parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        parser.error(f'database does not exist: {db_path}')
    result = apply_hong_kong_macro_final_remediation_migration(str(db_path))
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + '\n', encoding='utf-8')
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
