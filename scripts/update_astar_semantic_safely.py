#!/usr/bin/env python3
"""Check (default) or apply a bounded offline semantic delta; never collect papers."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_safe_semantic_update import update_embeddings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Stage, verify, back up and activate only the delta')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--max-delta-rows', type=int, default=2000)
    parser.add_argument('--backup-root', type=Path, default=None,
                        help='Store the immutable before-image outside the active data directory')
    args = parser.parse_args()
    if not 1 <= args.max_delta_rows <= 2000:
        parser.error('Automatic recovery is limited to at most 2,000 encoded rows')
    result = update_embeddings(args.root / 'pboc_data.db', args.root / 'data',
                               apply=args.apply, max_delta_rows=args.max_delta_rows,
                               backup_root=args.backup_root)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
