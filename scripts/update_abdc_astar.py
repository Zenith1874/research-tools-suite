#!/usr/bin/env python3
"""
ABDC A* 研究动态 —— 命令行更新脚本

用法：
  python scripts/update_abdc_astar.py --mode recent --days 30
  python scripts/update_abdc_astar.py --mode backfill_90_days
  python scripts/update_abdc_astar.py --mode backfill_current_year
  python scripts/update_abdc_astar.py --mode backfill_one_journal --journal "Academy of Management Journal"
  python scripts/update_abdc_astar.py --mode daily_incremental --days 14
  python scripts/update_abdc_astar.py --classify-only
  python scripts/update_abdc_astar.py --debug

Windows Task Scheduler 示例（每日增量）：
  cd D:\\claude
  python scripts\\update_abdc_astar.py --mode daily_incremental --days 14
"""
import argparse, json, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.abdc_astar_research_service import (
    ensure_astar_tables, load_astar_journals_from_abdc,
    update_astar_recent_articles, backfill_astar_articles,
    deduplicate_articles, reclassify_all, build_astar_debug_payload,
    enrich_with_semantic_scholar, run_journal_health_check,
    dedup_article_sources, llm_classify_articles,
)


def main():
    ap = argparse.ArgumentParser(description='ABDC A* Research Radar updater')
    ap.add_argument('--mode', default='recent',
                    choices=['recent', 'daily_incremental', 'weekly_incremental',
                             'backfill_90_days', 'backfill_current_year', 'backfill_one_journal',
                             'backfill_one_year', 'backfill_since'])
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--journal', default=None, help='backfill_one_journal 时指定期刊名（模糊匹配）')
    ap.add_argument('--year', type=int, default=None, help='backfill_one_year 指定年份')
    ap.add_argument('--since-year', type=int, default=None, help='backfill_since 起始年（多年深度回填）')
    ap.add_argument('--version', default='latest', help='ABDC 版本，默认最新')
    ap.add_argument('--classify-only', action='store_true', help='只重跑规则分类，不抓取')
    ap.add_argument('--enrich-abstracts', action='store_true', help='用 Semantic Scholar 补摘要/引用/学科')
    ap.add_argument('--health-check', action='store_true', help='跑期刊健康检查(逐刊查 OpenAlex)')
    ap.add_argument('--dedup-sources', action='store_true', help='来源表去重 + 建唯一索引')
    ap.add_argument('--llm-classify', action='store_true', help='用 LLM 重判(自动选 DeepSeek/Claude，需对应 API key)')
    ap.add_argument('--limit', type=int, default=100, help='--llm-classify 处理篇数上限')
    ap.add_argument('--max-relevance', type=float, default=None, help='只判规则分<该值的(找漏判，如 35)')
    ap.add_argument('--core-only', action='store_true', help='只扫核心 OB/IS 期刊(漏判最可能藏处)')
    ap.add_argument('--debug', action='store_true', help='打印 Debug 摘要后退出')
    args = ap.parse_args()

    ensure_astar_tables()

    if args.debug:
        print(json.dumps(build_astar_debug_payload(), ensure_ascii=False, indent=2))
        return

    if args.health_check:
        print('期刊健康检查（逐刊查 OpenAlex，约 1-2 分钟）…')
        print(json.dumps(run_journal_health_check(), ensure_ascii=False, indent=2))
        return

    if args.dedup_sources:
        print(json.dumps(dedup_article_sources(), ensure_ascii=False, indent=2))
        return

    if args.llm_classify:
        print(f'LLM 重新分类（最多 {args.limit} 篇）…')
        print(json.dumps(llm_classify_articles(limit=args.limit, max_relevance=args.max_relevance,
                                               core_journals_only=args.core_only),
                         ensure_ascii=False, indent=2))
        return

    if args.enrich_abstracts:
        print('Semantic Scholar 补全（缺摘要且有 DOI 的文章）…')
        print(json.dumps(enrich_with_semantic_scholar(), ensure_ascii=False, indent=2))
        return

    if args.classify_only:
        print('重新分类全部文章…')
        print(json.dumps(reclassify_all(), ensure_ascii=False, indent=2))
        return

    print(f'加载 ABDC A* 期刊（version={args.version}）…')
    jstat = load_astar_journals_from_abdc(args.version)
    print(json.dumps(jstat, ensure_ascii=False, indent=2))

    _eff_days = {'backfill_90_days': 90, 'daily_incremental': 14,
                 'weekly_incremental': 30}.get(args.mode, args.days)
    print(f'开始抓取（mode={args.mode}, days≈{_eff_days}）— 219 个 A* 期刊，请耐心等待…')
    if args.mode == 'recent':
        result = update_astar_recent_articles(days=args.days, version=args.version)
    else:
        result = backfill_astar_articles(args.mode, journal=args.journal, version=args.version,
                                         year=args.year, since_year=args.since_year)

    print('去重…')
    dedup = deduplicate_articles()

    result.pop('journal_stats', None)
    print('\n=== 抓取结果 ===')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('去重:', json.dumps(dedup, ensure_ascii=False))


if __name__ == '__main__':
    main()
