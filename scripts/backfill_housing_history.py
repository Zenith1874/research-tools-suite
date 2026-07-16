# -*- coding: utf-8 -*-
"""可审计的一次性房价历史回填入口。

示例：
  python scripts/backfill_housing_history.py --source nbs --start-year 2011
  python scripts/backfill_housing_history.py --source anjuke --start-year 2010 --max-requests 90
  python scripts/backfill_housing_history.py --source anjuke-yearly --no-network

安居客命令可重复执行；完整年份和本地缓存会自动跳过，单次请求硬上限为 100。
"""
import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.anjuke_listing_service import (  # noqa: E402
    DEFAULT_DB_PATH as DEFAULT_LISTING_DB,
    FOCUS_CITIES,
    update_anjuke_history,
    update_anjuke_yearly_rankings,
)
from services.housing_price_service import backfill_housing_city_history  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description='回填 2010 起挂牌价与 2011 起官方 70 城指数')
    parser.add_argument('--source', choices=('anjuke', 'anjuke-yearly', 'nbs'), required=True)
    parser.add_argument('--start-year', type=int)
    parser.add_argument('--end-year', type=int, default=datetime.now().year)
    parser.add_argument('--db-path', help='覆盖默认数据库路径')
    parser.add_argument('--cities', help='安居客城市，逗号分隔；默认用户点名十城')
    parser.add_argument('--ranking-cache', help='安居客全国历史排名页的本地 HTML 路径')
    parser.add_argument('--no-network', action='store_true',
                        help='仅复用本地缓存，不发起网络请求')
    parser.add_argument('--max-requests', type=int, default=90,
                        help='安居客单轮网络请求上限，最大 100')
    parser.add_argument('--sleep-min', type=float, default=2.0)
    parser.add_argument('--sleep-max', type=float, default=4.0)
    parser.add_argument('--nbs-sleep', type=float, default=0.5,
                        help='统计局月报请求间隔秒数')
    parser.add_argument('--nbs-workers', type=int, default=3,
                        help='统计局月报并发读取数，1--4；数据库仍单线程写入')
    return parser.parse_args()


def main():
    args = parse_args()
    if args.source == 'anjuke':
        cities = [item.strip() for item in args.cities.split(',') if item.strip()] \
            if args.cities else list(FOCUS_CITIES)
        result = update_anjuke_history(
            db_path=args.db_path or DEFAULT_LISTING_DB,
            cities=cities,
            start_year=args.start_year or 2010,
            end_year=args.end_year,
            sleep_range=(args.sleep_min, args.sleep_max),
            max_requests=args.max_requests,
            allow_network=not args.no_network,
        )
    elif args.source == 'anjuke-yearly':
        result = update_anjuke_yearly_rankings(
            db_path=args.db_path or DEFAULT_LISTING_DB,
            cached_path=args.ranking_cache,
            allow_network=not args.no_network,
        )
    else:
        result = backfill_housing_city_history(
            db_path=args.db_path or os.path.join(ROOT, 'pboc_data.db'),
            start_year=args.start_year or 2011,
            end_year=args.end_year,
            sleep_seconds=args.nbs_sleep,
            workers=args.nbs_workers,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
