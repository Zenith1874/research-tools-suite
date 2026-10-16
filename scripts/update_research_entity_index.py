#!/usr/bin/env python3
"""Inspect (default) or apply a bounded, audit-backed entity-input cache update."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import business_research_service as research
from services.business_index_incremental import update_index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--max-changed', type=int, default=20000)
    args = parser.parse_args()
    if not 1 <= args.max_changed <= 20000:
        parser.error('A reviewed delta may address at most 20,000 paper inputs')
    result = update_index(research, args.root / 'pboc_data.db',
                          args.root / 'data/business_research_state.db',
                          apply=args.apply, max_changed=args.max_changed)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
