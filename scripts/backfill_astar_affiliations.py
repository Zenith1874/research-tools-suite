# -*- coding: utf-8 -*-
"""Backfill institution affiliations for the stored A* article corpus.

The radar stored only author display names, so no article carries an
institution.  This walks the corpus in bounded, resumable batches and asks
OpenAlex for the authorships of works it already has ids for.

    # See what is left to do without touching the network.
    python scripts/backfill_astar_affiliations.py --coverage

    # A bounded batch (50 ids per request; 500 articles is ~10 requests).
    python scripts/backfill_astar_affiliations.py --limit 500

    # The full corpus, resumable: rerun until pending reaches zero.
    python scripts/backfill_astar_affiliations.py --limit 20000

    # Inspect what was recovered.
    python scripts/backfill_astar_affiliations.py --top 25 --since 2020
"""

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.astar_affiliation_service import (  # noqa: E402
    affiliation_coverage,
    backfill_affiliations,
    ensure_affiliation_tables,
    top_institutions,
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'pboc_data.db')


def connect(path):
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--db', default=DB_PATH)
    parser.add_argument('--limit', type=int, default=0,
                        help='articles to check this run (0 = do not fetch)')
    parser.add_argument('--delay', type=float, default=0.15,
                        help='pause between OpenAlex requests, seconds')
    parser.add_argument('--coverage', action='store_true', help='print coverage and exit')
    parser.add_argument('--top', type=int, default=0, help='print the top N institutions')
    parser.add_argument('--since', type=int, default=None, help='restrict --top to this year onward')
    parser.add_argument('--country', default=None, help='restrict --top to an ISO country code')
    args = parser.parse_args()

    conn = connect(args.db)
    try:
        ensure_affiliation_tables(conn)
        conn.commit()

        if args.limit:
            stats = backfill_affiliations(
                conn, limit=args.limit, delay=args.delay,
                progress=lambda message: print('  ' + message, flush=True))
            print(json.dumps(stats, indent=2, ensure_ascii=False))

        if args.coverage or args.limit:
            print('\ncoverage:')
            print(json.dumps(affiliation_coverage(conn), indent=2, ensure_ascii=False))

        if args.top:
            print(f'\ntop {args.top} institutions by observed A* articles'
                  + (f' since {args.since}' if args.since else '') + ':')
            for row in top_institutions(conn, since_year=args.since, limit=args.top,
                                        country_code=args.country):
                print(f"  {row['astar_articles']:6d}  {row['display_name']} "
                      f"({row['country_code'] or '??'}, {row['ror'] or 'no ROR'})")
    finally:
        conn.close()


if __name__ == '__main__':
    main()
