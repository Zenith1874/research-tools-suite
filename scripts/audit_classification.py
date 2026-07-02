# -*- coding: utf-8 -*-
"""A* 雷达分类抽样审计：每个 broad_area 随机抽 N 篇 → DeepSeek 复核领域标注 →
输出不一致率报告。用于主动发现规则分类的系统性错误
(如 2026-06 发现的法学/统计 6,798 篇被误标 Management 事件)。

用法:
    python scripts/audit_classification.py --dry-run          # 只看抽样，不调 API
    python scripts/audit_classification.py --per-area 20      # 正式审计(需 DEEPSEEK_API_KEY)
    python scripts/audit_classification.py --areas "OB / HR,Marketing"

输出: 控制台报告 + data/audit_classification_<日期>.json(不一致清单，供人工复核)。
成本: 每篇约 500 token，20篇×12领域 ≈ 数万 token，DeepSeek 约几美分。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pboc_data.db')
DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'
AREAS_ENUM = ('OB / HR, Information Systems, Marketing, Operations / Supply Chain, Finance, '
              'Accounting, Economics, Law, Statistics / Methods, Management / Strategy, '
              'Entrepreneurship, International Business, Other')

_SYS = ('你是学术期刊领域分类审计员。给你一篇文章的期刊名/标题/摘要和当前的领域标注，'
        f'判断标注是否正确。领域枚举: {AREAS_ENUM}。'
        '注意：领域主要由期刊学科决定(如 Annals of Statistics 上的文章属 Statistics / Methods，'
        '即使内容涉及经济应用)。严格只输出 JSON：'
        '{"correct": true/false, "suggested": "领域名", "reason": "一句中文"}')


def sample_articles(conn, per_area, areas_filter):
    rows = conn.execute("""
        SELECT c.article_id, c.broad_area, a.title, a.abstract, a.journal_title
        FROM astar_article_classifications c
        JOIN astar_articles a ON a.id = c.article_id
        WHERE a.is_duplicate = 0 AND c.broad_area IS NOT NULL AND c.broad_area != ''
        ORDER BY RANDOM()""").fetchall()
    by_area, out = {}, []
    for r in rows:
        area = r['broad_area']
        if areas_filter and area not in areas_filter:
            continue
        bucket = by_area.setdefault(area, [])
        if len(bucket) >= per_area:
            continue
        # 优先有摘要的(判断更可靠)；无摘要的排在后面凑数
        bucket.append(dict(r))
    for area, bucket in by_area.items():
        withabs = [x for x in bucket if x['abstract']]
        noabs = [x for x in bucket if not x['abstract']]
        out.extend((withabs + noabs)[:per_area])
    return out


def audit_one(item, model, timeout=60):
    user = (f"期刊: {item['journal_title']}\n标题: {item['title']}\n"
            f"摘要: {(item['abstract'] or '(无摘要，按期刊和标题判断)')[:1200]}\n"
            f"当前标注: {item['broad_area']}")
    r = requests.post(DEEPSEEK_URL, headers={
        'Authorization': f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
        'Content-Type': 'application/json'},
        json={'model': model, 'max_tokens': 200, 'temperature': 0.0,
              'response_format': {'type': 'json_object'},
              'messages': [{'role': 'system', 'content': _SYS},
                           {'role': 'user', 'content': user}]},
        timeout=timeout)
    r.raise_for_status()
    text = r.json()['choices'][0]['message']['content']
    m = re.search(r'\{.*\}', text, re.DOTALL)
    return json.loads(m.group(0)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-area', type=int, default=20)
    ap.add_argument('--areas', type=str, default='', help='逗号分隔，只审计这些领域')
    ap.add_argument('--model', type=str, default=os.environ.get('LLM_MODEL', 'deepseek-chat'))
    ap.add_argument('--dry-run', action='store_true', help='只抽样不调 API')
    args = ap.parse_args()

    areas_filter = {a.strip() for a in args.areas.split(',') if a.strip()} or None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    sample = sample_articles(conn, args.per_area, areas_filter)
    by_area = {}
    for x in sample:
        by_area.setdefault(x['broad_area'], []).append(x)
    print(f'抽样: {len(sample)} 篇，{len(by_area)} 个领域(每领域≤{args.per_area})')
    for area, items in sorted(by_area.items()):
        n_abs = sum(1 for x in items if x['abstract'])
        print(f'  {area:26} {len(items)} 篇(含摘要 {n_abs})')
    if args.dry_run:
        print('\n--dry-run：不调 API。'); return

    if not os.environ.get('DEEPSEEK_API_KEY'):
        print('\n错误: 未设置 DEEPSEEK_API_KEY，无法审计。'); sys.exit(1)

    disagreements, errors, done = [], 0, 0
    stats = {a: {'n': 0, 'wrong': 0} for a in by_area}
    for item in sample:
        try:
            res = audit_one(item, args.model)
        except Exception as e:
            errors += 1
            time.sleep(1.0)
            continue
        done += 1
        area = item['broad_area']
        stats[area]['n'] += 1
        if res and res.get('correct') is False:
            stats[area]['wrong'] += 1
            disagreements.append({
                'article_id': item['article_id'], 'journal': item['journal_title'],
                'title': item['title'][:120], 'current': area,
                'suggested': res.get('suggested'), 'reason': res.get('reason')})
        if done % 20 == 0:
            print(f'  …已审 {done}/{len(sample)}')
        time.sleep(0.3)

    print(f'\n===== 审计报告({date.today()}, model={args.model}) =====')
    print(f'总审 {done} 篇，API 失败 {errors} 篇\n')
    print(f'{"领域":28} {"审计":>4} {"不一致":>5} {"不一致率":>7}')
    flagged = []
    for area, s in sorted(stats.items(), key=lambda kv: -(kv[1]['wrong'] / kv[1]['n'] if kv[1]['n'] else 0)):
        if not s['n']:
            continue
        rate = s['wrong'] / s['n']
        mark = '  ⚠️' if rate >= 0.3 else ''
        if rate >= 0.3:
            flagged.append(area)
        print(f'{area:28} {s["n"]:>4} {s["wrong"]:>5} {rate:>6.0%}{mark}')
    out_path = os.path.join(os.path.dirname(DB_PATH), 'data', f'audit_classification_{date.today().isoformat()}.json')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'date': date.today().isoformat(), 'model': args.model,
                   'audited': done, 'errors': errors,
                   'stats': stats, 'disagreements': disagreements}, f, ensure_ascii=False, indent=1)
    print(f'\n不一致 {len(disagreements)} 篇，明细已写入 {out_path}')
    if flagged:
        print(f'⚠️  以下领域不一致率≥30%，疑似系统性错误，建议人工复核: {", ".join(flagged)}')


if __name__ == '__main__':
    main()
