# -*- coding: utf-8 -*-
"""把 A* 雷达的 uncertain 积压一次性用 LLM 判完，只在 DeepSeek 优惠时段花钱。

为什么要单独一个脚本，而不是调 /api/abdc/astar/llm-classify：
  * 那个端点把 llm_classify_articles 的返回值丢掉，十几个小时里日志不会有一行；
  * 它跑在 server 的 daemon 线程里，watchdog 一重启服务器整个任务就没了，
    而且你不知道断在哪一篇。

这里改成分块跑：每块结束就落库、打进度和 ETA、查一次余额。中断了直接重跑即可
——候选查询本身就排除 classification_method='llm' 的行，已经判过的不会重判。

用法：
    python scripts/drain_llm_backlog.py --dry-run     # 只看积压量、预估花费和时段
    python scripts/drain_llm_backlog.py               # 正式跑，撞标准时段自动暂停
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from services.abdc_astar_research_service import (  # noqa: E402
    ensure_astar_tables, get_db, llm_classify_articles)
from services.deepseek_offpeak import describe as offpeak_describe  # noqa: E402
from services.deepseek_offpeak import offpeak_seconds_left  # noqa: E402

log = logging.getLogger('drain')

BALANCE_URL = 'https://api.deepseek.com/user/balance'

# 实测值，用于预估：输入 669 token(系统提示词 342 + 正文 327)，输出 119 token，
# 1.8 秒/篇(150 篇 271s 与 265s 两次实测)。优惠时段 ¥1.5/M 输入、¥4.5/M 输出。
TOKENS_IN, TOKENS_OUT, SECONDS_EACH = 669.0, 119.0, 1.8
YUAN_IN_PER_M, YUAN_OUT_PER_M = 1.5, 4.5
YUAN_EACH = TOKENS_IN / 1e6 * YUAN_IN_PER_M + TOKENS_OUT / 1e6 * YUAN_OUT_PER_M


def load_secrets():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.secrets')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def balance_cny():
    """账户人民币余额；查询本身不计费。取不到时返回 None 而不是猜一个数。"""
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        return None
    try:
        r = requests.get(BALANCE_URL, headers={'Authorization': 'Bearer ' + key},
                         timeout=20)
        r.raise_for_status()
        for info in r.json().get('balance_infos', []):
            if info.get('currency') == 'CNY':
                return float(info['total_balance'])
    except Exception as exc:
        log.warning('余额查询失败(不影响跑): %s', exc)
    return None


def pool_size():
    conn = get_db()
    ensure_astar_tables(conn)
    try:
        return conn.execute("""
            SELECT count(*) FROM astar_articles a
            JOIN astar_article_classifications c ON c.article_id=a.id
            WHERE a.is_duplicate=0 AND c.classification_method!='llm'
              AND c.classification_status='uncertain'
              AND a.abstract IS NOT NULL AND a.abstract!=''""").fetchone()[0]
    finally:
        conn.close()


def plan(total):
    hours = total * SECONDS_EACH / 3600.0
    return {'articles': total, 'yuan': total * YUAN_EACH, 'hours': hours,
            'runway_hours': offpeak_seconds_left() / 3600.0}


def report_plan(p):
    print('积压          %d 篇' % p['articles'])
    print('预估花费      ¥%.2f（优惠时段价，实测 %.4f 元/篇）' % (p['yuan'], YUAN_EACH))
    print('预估纯跑时长  %.1f 小时（实测 %.1f 秒/篇，串行）' % (p['hours'], SECONDS_EACH))
    print('当前计费时段  %s' % offpeak_describe())
    if p['runway_hours'] >= p['hours']:
        print('不变价余量    %.1f 小时 → 够一口气跑完' % p['runway_hours'])
    else:
        print('不变价余量    %.1f 小时 → 会在标准时段暂停，之后续跑（仍是优惠价）'
              % p['runway_hours'])
    bal = balance_cny()
    if bal is not None:
        print('账户余额      ¥%.2f %s' % (bal, '✅ 够' if bal >= p['yuan'] else '⚠ 不够，会中途断'))


def parse_when(text):
    """接受 "2026-09-04 08:00" 或 "08:00"（取下一个该时刻）。本地时间。"""
    text = text.strip()
    for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M', '%m-%d %H:%M'):
        try:
            when = datetime.strptime(text, fmt)
            if fmt == '%m-%d %H:%M':
                when = when.replace(year=datetime.now().year)
            return when
        except ValueError:
            pass
    try:
        hh, mm = (int(x) for x in text.split(':'))
    except ValueError:
        raise SystemExit('--start-at 认不出来: %r（用 "2026-09-04 08:00" 或 "08:00"）' % text)
    now = datetime.now()
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return when if when > now else when + timedelta(days=1)


def wait_until(when):
    """睡到指定时刻。分段睡并按小时报一次，免得看起来像卡死。"""
    total = (when - datetime.now()).total_seconds()
    if total <= 0:
        log.info('--start-at %s 已经过了，直接开跑', when.strftime('%m-%d %H:%M'))
        return
    log.info('等到 %s 再开跑（还有 %s）',
             when.strftime('%m-%d %a %H:%M'), str(timedelta(seconds=int(total))))
    while True:
        left = (when - datetime.now()).total_seconds()
        if left <= 0:
            break
        time.sleep(min(left, 1800))
        left = (when - datetime.now()).total_seconds()
        if left > 60:
            log.info('还有 %s 开跑', str(timedelta(seconds=int(left))))
    log.info('到点，开始。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunk', type=int, default=200, help='每块处理多少篇（默认 200）')
    ap.add_argument('--max', type=int, default=0, help='本次最多处理多少篇，0 表示全部')
    ap.add_argument('--offpeak', default='wait', choices=('wait', 'stop', 'off'),
                    help="撞上标准时段怎么办：wait 等到优惠时段(默认)、stop 收工、off 不管")
    ap.add_argument('--min-balance', type=float, default=2.0,
                    help='余额低于这个数(元)就停，别跑到一半开始静默失败')
    ap.add_argument('--start-at', default='',
                    help='等到这个本地时刻再开跑，如 "2026-09-04 08:00" 或 "08:00"（下一个 08:00）')
    ap.add_argument('--dry-run', action='store_true', help='只报告，不调 API')
    args = ap.parse_args()

    # 日志走 stdout，跟 print 的计划报告落在同一个文件里；否则后台跑起来之后
    # 进度全在 stderr，得同时盯两个文件。
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(message)s',
                        datefmt='%m-%d %H:%M:%S', stream=sys.stdout)
    load_secrets()

    if args.start_at and not args.dry_run:
        wait_until(parse_when(args.start_at))

    total = pool_size()
    p = plan(total)
    report_plan(p)
    if args.dry_run:
        print('\n--dry-run：没有调用 API。')
        return 0
    if not total:
        print('\n积压已经清空，无事可做。')
        return 0
    if not os.environ.get('DEEPSEEK_API_KEY'):
        print('\n错误：未设置 DEEPSEEK_API_KEY。')
        return 1

    target = min(args.max, total) if args.max else total
    log.info('开始清积压：目标 %d 篇，每块 %d 篇，offpeak=%s', target, args.chunk, args.offpeak)
    started = time.time()
    done = failed = 0
    chunk_no = 0

    while done < target:
        chunk_no += 1
        bal = balance_cny()
        if bal is not None and bal < args.min_balance:
            log.warning('余额只剩 ¥%.2f，低于下限 ¥%.2f，停在这里（重新充值后直接重跑本脚本）',
                        bal, args.min_balance)
            break

        size = min(args.chunk, target - done)
        result = llm_classify_articles(limit=size, offpeak=args.offpeak)
        if not result.get('success'):
            log.error('停止：%s', result.get('error'))
            return 1

        got, bad = result['classified'], result['failed']
        done += got
        failed += bad

        if result.get('stopped_at_standard_rate'):
            log.info('进入标准时段，按 --offpeak=stop 收工。已判 %d 篇。', done)
            break
        if got == 0:
            # 候选池里剩下的都判不动了（比如摘要触发内容过滤）。再循环下去
            # 只会对同一批反复重试、反复付费，所以在这里停。
            log.warning('这一块 %d 篇全部失败，停止以免对同一批反复付费。', bad)
            break

        elapsed = time.time() - started
        rate = done / elapsed if elapsed else 0
        left = (target - done) / rate if rate else 0
        log.info('第 %d 块：+%d 篇（失败 %d）｜累计 %d/%d ｜已花约 ¥%.2f ｜ETA %s ｜%s',
                 chunk_no, got, bad, done, target, done * YUAN_EACH,
                 str(timedelta(seconds=int(left))),
                 '余额 ¥%.2f' % bal if bal is not None else '余额未知')

    elapsed = time.time() - started
    log.info('结束：判定 %d 篇，失败 %d 篇，用时 %s，花费约 ¥%.2f',
             done, failed, str(timedelta(seconds=int(elapsed))), done * YUAN_EACH)
    log.info('剩余积压 %d 篇', pool_size())
    return 0


if __name__ == '__main__':
    sys.exit(main())
