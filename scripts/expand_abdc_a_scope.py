#!/usr/bin/env python3
"""Plan/apply append-only A-rated tracking before resumable history acquisition."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.abdc_a_extension import apply_plan, prepare_plan


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'apply'))
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--db', type=Path, default=ROOT / 'pboc_data.db')
    parser.add_argument('--plan-dir', type=Path)
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if args.action == 'plan':
        if not args.catalog or not args.plan_dir:
            parser.error('plan requires --catalog and --plan-dir')
        result = prepare_plan(args.catalog, args.db, args.plan_dir)
        print(json.dumps({key: value for key, value in result.items() if key not in ('journals', 'already_tracked_A')}, ensure_ascii=False, indent=2))
    else:
        if not args.plan:
            parser.error('apply requires --plan')
        result = apply_plan(args.plan.resolve())
        print(json.dumps({'inserted': len(result['inserted']), 'retained': len(result['retained']),
                          'article_values_updated': result['article_values_updated']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
