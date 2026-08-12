#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Resume official interest/redemption notice metadata collection."""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.lgfv_bond_market_service import (
    build_lgfv_market_payload,
    update_lgfv_bond_notices,
)


DEFAULT_DB = os.path.join(ROOT, 'data', 'lgfv_bond.db')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--max-pages', type=int, default=None,
                        help='本次每个债券类型最多抓多少页；不填则续跑到完成')
    parser.add_argument('--pause', type=float, default=0.15)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--snapshot-date', default=None)
    parser.add_argument('--start-date', default='2023-08-07')
    parser.add_argument('--end-date', default=None)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    result = update_lgfv_bond_notices(
        args.db, max_pages=args.max_pages, request_pause=args.pause,
        timeout=args.timeout, snapshot_date=args.snapshot_date,
        start_date=args.start_date, end_date=args.end_date,
        verbose=args.verbose,
    )
    result['payload'] = build_lgfv_market_payload(args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
