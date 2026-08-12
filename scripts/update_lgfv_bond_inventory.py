#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Update the private ChinaMoney/AKShare candidate bond inventory.

Examples (run from the repository root):
    python.exe -X utf8 scripts/update_lgfv_bond_inventory.py --max-pages 1
    python.exe -X utf8 scripts/update_lgfv_bond_inventory.py

The default run is resumable and can take a long time because the public
endpoint returns 15 rows per page. It writes only to the ignored local SQLite
database; it does not populate official fiscal-debt observations.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.lgfv_bond_service import (
    CANDIDATE_BOND_TYPES,
    build_lgfv_bond_inventory_payload,
    update_lgfv_bond_inventory,
)


DEFAULT_DB = os.path.join(ROOT, 'data', 'lgfv_bond.db')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--max-pages', type=int, default=None,
                        help='每个债券类型最多抓几页；用于 smoke test')
    parser.add_argument('--pause', type=float, default=0.15)
    parser.add_argument('--timeout', type=int, default=15)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    result = update_lgfv_bond_inventory(
        args.db, max_pages=args.max_pages, request_pause=args.pause,
        timeout=args.timeout, verbose=args.verbose)
    result['payload'] = build_lgfv_bond_inventory_payload(args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
