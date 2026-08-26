#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a reproducible thematic index for the 老蛮频道 TXT corpus.

The index is a navigation artifact, not a fact checker. It reads the canonical
TXT files, keeps the source path, and applies overlapping keyword labels. Raw
transcripts are never modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


DEFAULT_ROOT = Path('/mnt/e/macro data/老蛮频道/transcripts')
TAXONOMY = {
    'housing': r'地产|房地产|房价|房企|万科|恒大|保交楼|楼市|住房|房屋养老金|建筑业',
    'population_labor': r'人口|失业|就业|农民工|毕业生|婚育|结婚|出生|死亡率|发病率|社保|退休',
    'money_finance_debt': r'货币|印钞|人民币|央行|贷款|社融|M2|M1|利率|LPR|银行|债务|化债|外汇|金融|资本',
    'industry_trade': r'工业|制造|产能|利润|出口|进口|关税|贸易|顺差|生产过剩|转口|汽车|比亚迪',
    'city_region': r'北京|上海|广州|深圳|厦门|杭州|成都|佛山|东莞|苏州|南京|西安|香港|河南|河北|甘肃|陕西|湛江|珠海|越南',
    'institution_policy': r'政府|财政|政策|制度|政权|社会动员|两脚羊|反内卷|美国历史|总结|入世|CPTPP',
}


def _metadata(root: Path) -> dict[str, dict[str, str]]:
    index_path = root / '索引.csv'
    if not index_path.exists():
        return {}
    with index_path.open('r', encoding='utf-8-sig', newline='') as handle:
        return {row.get('标题', '').strip(): row for row in csv.DictReader(handle)}


def build_index(root: Path) -> list[dict[str, object]]:
    metadata = _metadata(root)
    rows = []
    for path in sorted((root / 'txt').glob('*.txt')):
        text = path.read_text(encoding='utf-8')
        title = path.stem
        labels = [name for name, pattern in TAXONOMY.items()
                  if re.search(pattern, title) or re.search(pattern, text)]
        match_counts = {
            name: len(re.findall(pattern, title + '\n' + text))
            for name, pattern in TAXONOMY.items()
            if re.search(pattern, title) or re.search(pattern, text)
        }
        meta = metadata.get(title, {})
        rows.append({
            'date': meta.get('日期') or title[:8],
            'title': title,
            'source_path': str(path),
            'characters': len(text),
            'labels': labels,
            'keyword_counts': match_counts,
            'index_metadata': meta,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    rows = build_index(args.root)
    summary = {
        'canonical_root': str(args.root / 'txt'),
        'txt_count': len(rows),
        'character_count': sum(int(row['characters']) for row in rows),
        'labels': {label: sum(label in row['labels'] for row in rows)
                   for label in TAXONOMY},
        'rows': rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                               encoding='utf-8')
    else:
        print(json.dumps({key: value for key, value in summary.items() if key != 'rows'},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
