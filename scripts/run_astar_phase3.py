#!/usr/bin/env python3
"""一次性编排：S2 补全 → 回填 2020-2023 缺口 → 再次 S2 补全 → 去重。
串行执行，避免并发写 SQLite 锁库。后台运行用。"""
import sys, os, json
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.abdc_astar_research_service import (
    ensure_astar_tables, enrich_with_semantic_scholar, deduplicate_articles, _run_update,
)

def stamp(msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

ensure_astar_tables()

stamp("STEP 1/4 — Semantic Scholar 补全（第一轮，当前缺摘要文章）")
r1 = enrich_with_semantic_scholar()
stamp(f"  pass1: {json.dumps(r1, ensure_ascii=False)}")

stamp("STEP 2/4 — 回填 2020-01-01 → 2023-12-31 缺口（全 219 刊，分页）")
r2 = _run_update('backfill_since', 0, 'latest', per_journal_cap=1500,
                 from_date='2020-01-01', to_date='2023-12-31')
r2.pop('journal_stats', None)
stamp(f"  backfill: found={r2['articles_found']} inserted={r2['articles_inserted']} "
      f"updated={r2['articles_updated']} failed={r2['failed_journals']}")

stamp("STEP 3/4 — 去重")
stamp(f"  {json.dumps(deduplicate_articles(), ensure_ascii=False)}")

stamp("STEP 4/4 — Semantic Scholar 补全（第二轮：新回填文章 + 重试第一轮限流批次）")
r3 = enrich_with_semantic_scholar()
stamp(f"  pass2: {json.dumps(r3, ensure_ascii=False)}")

stamp("全部完成")
