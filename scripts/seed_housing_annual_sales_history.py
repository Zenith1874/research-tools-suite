# -*- coding: utf-8 -*-
"""Seed the checked-in official annual housing-sales history into SQLite.

This is a local, no-network operation.  It also copies December monthly
cumulative observations into the annual series for years not already covered
by the explicit annual source table.
"""
import argparse
import json
import os
import sys
from contextlib import closing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.housing_price_service import (  # noqa: E402
    connect, ensure_housing_tables, seed_housing_annual_sales_history,
)


def main():
    parser = argparse.ArgumentParser(description='载入统计局官方年度一手房销售面积历史')
    parser.add_argument('--db-path', default=os.path.join(ROOT, 'pboc_data.db'))
    args = parser.parse_args()
    with closing(connect(args.db_path)) as conn:
        ensure_housing_tables(conn)
        result = seed_housing_annual_sales_history(conn)
        conn.commit()
    print(json.dumps({
        'db_path': os.path.abspath(args.db_path),
        **result,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
