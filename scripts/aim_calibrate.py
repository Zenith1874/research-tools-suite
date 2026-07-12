# -*- coding: utf-8 -*-
"""兴趣匹配校准集：抽 N 篇(高/低 semantic_relevance + 边界) → DeepSeek 结构化抽取 →
写派生表 + 导出 outputs/calibration_review.csv 供人工复核。

    python scripts/aim_calibrate.py --n 200            # 50高+50低+100边界
    python scripts/aim_calibrate.py --n 20 --smoke     # 冒烟(便宜,验证链路)

需要 DEEPSEEK_API_KEY(从 .secrets 或环境读)。
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import astar_interest_service as ais       # noqa: E402
from services.aim_extract import extract_one, prompt_hash, PROMPT_VERSION   # noqa: E402


def _load_secrets():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.secrets')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def sample_calibration(n):
    """按 semantic_relevance 高/低 + 边界抽样(优先有摘要)。"""
    hi = n // 4; lo = n // 4; mid = n - hi - lo
    conn = sqlite3.connect(ais.MAIN_DB); conn.row_factory = sqlite3.Row
    q = """SELECT a.id, cls.semantic_relevance sr
           FROM astar_articles a JOIN astar_article_classifications cls ON cls.article_id=a.id
           WHERE a.is_duplicate=0 AND a.abstract IS NOT NULL AND a.abstract!='' AND cls.semantic_relevance IS NOT NULL
           {cond} ORDER BY {order} LIMIT ?"""
    picks = []
    picks += [r['id'] for r in conn.execute(q.format(cond='', order='cls.semantic_relevance DESC'), (hi,))]
    picks += [r['id'] for r in conn.execute(q.format(cond='', order='cls.semantic_relevance ASC'), (lo,))]
    # 边界：40-70 分带随机
    picks += [r['id'] for r in conn.execute(
        """SELECT a.id FROM astar_articles a JOIN astar_article_classifications cls ON cls.article_id=a.id
           WHERE a.is_duplicate=0 AND a.abstract IS NOT NULL AND a.abstract!=''
             AND cls.semantic_relevance BETWEEN 40 AND 70
           ORDER BY RANDOM() LIMIT ?""", (mid,))]
    conn.close()
    seen, out = set(), []
    for i in picks:
        if i not in seen:
            seen.add(i); out.append(i)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=200)
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--model', default='deepseek-v4-flash')
    args = ap.parse_args()
    _load_secrets()
    if not os.environ.get('DEEPSEEK_API_KEY'):
        print('缺 DEEPSEEK_API_KEY'); sys.exit(1)

    ais.sync_profiles_to_db()
    profiles = [p for p in ais.load_profile_files() if p.get('enabled', True)]
    print(f'画像 {len(profiles)} 个: {", ".join(p["profile_id"] for p in profiles)}')

    ids = sample_calibration(args.n if not args.smoke else args.n)
    arts = ais.fetch_articles(ids)
    print(f'校准样本 {len(arts)} 篇，开始抽取(model={args.model})…')

    ph = prompt_hash(profiles)
    run_at = datetime.now().isoformat()
    conn = ais.connect(); ais.ensure_tables(conn)
    rid = conn.execute("""INSERT INTO aim_runs (stage,profile_ids,model,prompt_version,n_input,started,notes)
                          VALUES (?,?,?,?,?,?,?)""",
                       ('calibration', ",".join(p['profile_id'] for p in profiles), args.model,
                        PROMPT_VERSION, len(arts), run_at, 'calibration run')).lastrowid
    conn.commit()

    rows_csv, ok, err = [], 0, 0
    t0 = time.time()
    for i, art in enumerate(arts, 1):
        try:
            res = extract_one(art, profiles, model=args.model)
        except Exception as e:
            err += 1; print(f'  [{i}] 失败: {e}'); continue
        if not res:
            err += 1; continue
        labels = res.get('labels', {}) or {}
        meta = {'model': args.model, 'prompt_version': PROMPT_VERSION, 'prompt_hash': ph,
                'input_hash': ais.input_hash(art['title'], art['abstract']), 'run_at': run_at}
        ais.save_labels(conn, art['id'], labels, meta)
        best_pid, best_overall = None, -1
        for p in profiles:
            pd = (res.get('profiles', {}) or {}).get(p['profile_id']) or {}
            dims = {d: pd.get(d) for d in ('topic', 'theory', 'method', 'data', 'setting', 'opportunity')}
            overall = ais.overall_from_dims(dims, p.get('weights', {}))
            ais.save_scores(conn, art['id'], p['profile_id'], dims, overall,
                            pd.get('rationale'), args.model, run_at)
            if overall is not None and overall > best_overall:
                best_overall, best_pid = overall, p['profile_id']
        ok += 1
        rows_csv.append({
            'article_id': art['id'], 'title': art['title'][:120],
            'journal': art['journal_title'], 'abstract_present': bool(art['abstract']),
            'topics': "; ".join(labels.get('research_topics', [])[:5]),
            'methods': "; ".join(labels.get('methods', [])[:5]),
            'data_sources': "; ".join(labels.get('data_sources', [])[:5]),
            'uncertainty': labels.get('uncertainty'),
            'best_profile': best_pid, 'best_overall': best_overall,
            'evidence': " | ".join(labels.get('evidence_spans', [])[:2])[:300],
            'my_judgement_相关吗': '', 'my_notes': '',
        })
        if i % 20 == 0:
            conn.commit()
            print(f'  {i}/{len(arts)}  ok={ok} err={err}  {time.time()-t0:.0f}s')
    conn.execute('UPDATE aim_runs SET finished=?, n_output=?, notes=? WHERE run_id=?',
                 (datetime.now().isoformat(), ok, f'ok={ok} err={err}', rid))
    conn.commit(); conn.close()

    out_dir = os.path.join(ais._ROOT, 'outputs'); os.makedirs(out_dir, exist_ok=True)
    out_csv = os.path.join(out_dir, 'calibration_review.csv')
    with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows_csv[0].keys()) if rows_csv else ['article_id'])
        w.writeheader(); w.writerows(rows_csv)
    print(f'\n完成: ok={ok} err={err}  用时 {time.time()-t0:.0f}s')
    print(f'人工复核表: {out_csv}(填 my_judgement_相关吗 列后我据此调画像/提示词)')


if __name__ == '__main__':
    main()
