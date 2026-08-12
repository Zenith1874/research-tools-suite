#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Enrich the private ChinaMoney candidate inventory with bond terms."""

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
)


DEFAULT_DB = os.path.join(ROOT, 'data', 'lgfv_bond.db')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=DEFAULT_DB)
    parser.add_argument('--max-rows', type=int, default=None,
                        help='本次最多请求多少条详情；不填则续跑到完成')
    parser.add_argument('--pause', type=float, default=0.15)
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('--retries', type=int, default=4,
                        help='单条详情遇到空响应/连接异常时的重试次数')
    parser.add_argument('--snapshot-date', default=None)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
    result = update_lgfv_bond_details(
        args.db, max_rows=args.max_rows, request_pause=args.pause,
        timeout=args.timeout, retries=args.retries,
        snapshot_date=args.snapshot_date,
        verbose=args.verbose,
    )
    result['payload'] = build_lgfv_market_payload(args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
