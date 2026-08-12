#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run the private candidate inventory, terms, and notice phases in order.

Each phase is independently resumable.  The default ``all`` mode is intended
for a long-running local job; use ``--phase`` when monitoring a single layer.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.lgfv_bond_market_service import (
    build_lgfv_market_payload,
    update_lgfv_bond_details,
    update_lgfv_bond_notices,
)
from services.lgfv_bond_service import update_lgfv_bond_inventory


DEFAULT_DB = os.path.join(ROOT, 'data', 'lgfv_bond.db')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--phase', choices=('inventory', 'details', 'notices', 'all'),
                        default='all')
    parser.add_argument('--max-pages', type=int, default=None)
    parser.add_argument('--max-rows', type=int, default=None)
    parser.add_argument('--pause', type=float, default=0.2)
    parser.add_argument('--timeout', type=int, default=15)
    parser.add_argument('--snapshot-date', default=None)
    parser.add_argument('--start-date', default='2023-08-07')
    parser.add_argument('--end-date', default=None)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    results = {}

    if args.phase in ('inventory', 'all'):
        results['inventory'] = update_lgfv_bond_inventory(
            args.db, max_pages=args.max_pages, request_pause=args.pause,
            timeout=args.timeout, snapshot_date=args.snapshot_date,
            verbose=args.verbose,
        )
        if not results['inventory'].get('success') and args.phase == 'all':
            print(json.dumps({
                'success': False, 'phase': 'inventory', 'results': results,
                'payload': build_lgfv_market_payload(args.db),
            }, ensure_ascii=False, indent=2))
            return 1

    if args.phase in ('details', 'all'):
        results['details'] = update_lgfv_bond_details(
            args.db, max_rows=args.max_rows, request_pause=args.pause,
            timeout=args.timeout, snapshot_date=args.snapshot_date,
            verbose=args.verbose,
        )
        if not results['details'].get('success') and args.phase == 'all':
            print(json.dumps({
                'success': False, 'phase': 'details', 'results': results,
                'payload': build_lgfv_market_payload(args.db),
            }, ensure_ascii=False, indent=2))
            return 1

    if args.phase in ('notices', 'all'):
        results['notices'] = update_lgfv_bond_notices(
            args.db, max_pages=args.max_pages, request_pause=args.pause,
            timeout=args.timeout, snapshot_date=args.snapshot_date,
            start_date=args.start_date, end_date=args.end_date,
            verbose=args.verbose,
        )

    success = all(item.get('success', False) for item in results.values())
    print(json.dumps({
        'success': success, 'phase': args.phase, 'results': results,
        'payload': build_lgfv_market_payload(args.db),
    }, ensure_ascii=False, indent=2))
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
