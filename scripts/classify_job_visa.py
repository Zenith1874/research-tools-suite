# -*- coding: utf-8 -*-
"""给规则法判不出签证态度的职位，用 LLM 读一遍原文，只在 DeepSeek 优惠时段花钱。

services/faculty_jobs_visa_llm.py 早就写好并有测试，但从来没有生产代码调用它，
所以 5,236 个职位里 visa_status 有 98.7% 是 unknown——而对国际候选人来说这是
第一道筛子。这个脚本就是把那个模块接上线。

安全性由被调模块保证，这里不放松：模型必须给出一句原文，那句话要逐字出现在职位
描述里，验不过整条判定作废（见 _quote_is_in_source）。pathways 也不采信模型，
而是回头用规则从原文重抽。

写回三个字段并留痕：
  * visa_status / visa_text / visa_pathways
  * job_field_provenance 一行，source_url 记 'llm:<model>'，evidence_text 存那句原文

"问过但职位没提" 与 "从没问过" 是两回事，所以判成 unknown 也会写一条 is_current=0
的留痕。候选查询据此排除已问过的，脚本因此可以随时中断重跑，不会重复付费。

用法：
    python scripts/classify_job_visa.py --dry-run       # 只看目标集和预估
    python scripts/classify_job_visa.py --limit 20      # 先跑 20 条看看
    python scripts/classify_job_visa.py                 # 全量
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from services import faculty_jobs_visa_llm as visa_llm  # noqa: E402
from services.deepseek_offpeak import describe as offpeak_describe  # noqa: E402
from services.deepseek_offpeak import is_offpeak, normalize_mode, wait_for_offpeak  # noqa: E402

log = logging.getLogger('visa')

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'faculty_jobs.db')
BALANCE_URL = 'https://api.deepseek.com/user/balance'

# 还在招的职位才值得花钱；已关闭的判出来也用不上。
OPEN_STATUSES = ('likely_open', 'open', 'closing_soon', 'unknown')

# A* 那轮 23,297 篇实测：优惠时段 + 系统提示词命中缓存后 ¥0.00087/篇。这里正文
# 长得多(平均 2,502 字符 vs 1,024)，按输入 token 比例放大，输出反而更短。
YUAN_EACH = 0.0025
SECONDS_EACH = 2.5

# 规则做召回，模型做判断。抽 60 条候选实测，只有 8% 的正文出现过签证话题，其余
# 全跑就是在为"原文根本没写"付费。而模型的判定必须逐字引用原文，所以正文里连这
# 些词都没有的职位，本来也不可能产生非 unknown 的结论。
#
# 口径故意放宽——漏掉一条真承诺的代价远大于多跑几条。真正难的那一步留给模型：
# 实测 8 条命中的里 7 条是 EEO 套话("race, color, gender... citizenship...")，
# 只有 1 条是真承诺("HVCC does not support Visas.")，这个区分关键词做不到。
VISA_VOCAB = re.compile(
    r'sponsor|visa|h-?1b|j-?1|o-?1|tn visa|work permit|right to work|work authoriz|'
    r'authoriz\w+ to work|employment authoriz|permanent resid|green card|immigration|'
    r'eligib\w+ to work|citizenship', re.I)


def load_secrets():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.secrets')
    if os.path.exists(path):
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


def balance_cny():
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        return None
    try:
        r = requests.get(BALANCE_URL, headers={'Authorization': 'Bearer ' + key}, timeout=20)
        r.raise_for_status()
        for info in r.json().get('balance_infos', []):
            if info.get('currency') == 'CNY':
                return float(info['total_balance'])
    except Exception as exc:
        log.warning('余额查询失败(不影响跑): %s', exc)
    return None


def candidates(conn, limit, include_closed=False, prefilter=True):
    """规则法判 unknown、正文够长、且还没问过 LLM 的职位。"""
    where = ["j.visa_status='unknown'",
             'length(j.description_excerpt) >= %d' % visa_llm.MIN_BODY_CHARS,
             """NOT EXISTS (SELECT 1 FROM job_field_provenance p
                            WHERE p.job_id=j.id AND p.field_name='visa_status'
                              AND p.source_url LIKE 'llm:%')"""]
    args = []
    if not include_closed:
        where.append('j.status IN (%s)' % ','.join(['?'] * len(OPEN_STATUSES)))
        args += list(OPEN_STATUSES)
    sql = ("""SELECT j.id, j.title_raw, j.description_excerpt FROM jobs j
              WHERE %s ORDER BY j.last_seen_at DESC""" % ' AND '.join(where))
    rows = conn.execute(sql, args).fetchall()
    if prefilter:
        # 按模型实际会读到的那段(正文尾部)来筛，筛它读不到的部分没有意义
        rows = [r for r in rows if VISA_VOCAB.search(visa_llm._body_for(r['description_excerpt']))]
    return rows[:int(limit)] if limit else rows


def record(conn, job_id, verdict, model):
    """写回判定并留痕。unknown 也留痕，否则重跑会再问一次、再付一次钱。"""
    marker = 'llm:%s' % model
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    actionable = verdict['status'] != 'unknown'

    if actionable:
        conn.execute("""UPDATE jobs SET visa_status=?, visa_text=?, visa_pathways=?,
                        updated_at=? WHERE id=?""",
                     (verdict['status'], verdict.get('evidence'),
                      json.dumps(verdict.get('pathways') or [], ensure_ascii=False),
                      now, job_id))
        conn.execute("UPDATE job_field_provenance SET is_current=0"
                     " WHERE job_id=? AND field_name='visa_status'", (job_id,))

    conn.execute("""INSERT INTO job_field_provenance
                      (job_id, field_name, value_text, source_id, source_job_id,
                       source_url, evidence_text, captured_at, is_current)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                 (job_id, 'visa_status', verdict['status'], None, None, marker,
                  verdict.get('evidence') or verdict.get('rejected'), now,
                  1 if actionable else 0))
    return actionable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='最多处理多少条，0 表示全部')
    ap.add_argument('--offpeak', default='wait', choices=('wait', 'stop', 'off'),
                    help='撞上标准时段怎么办：wait 等到优惠时段(默认)、stop 收工、off 不管')
    ap.add_argument('--min-balance', type=float, default=2.0, help='余额低于这个数(元)就停')
    ap.add_argument('--include-closed', action='store_true', help='连已关闭的职位也判')
    ap.add_argument('--no-prefilter', action='store_true',
                    help='不做关键词预筛，正文没提签证的也送去问（贵 10 倍，产出基本不变）')
    ap.add_argument('--dry-run', action='store_true', help='只报告，不调 API')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-7s %(message)s',
                        datefmt='%m-%d %H:%M:%S', stream=sys.stdout)
    load_secrets()
    mode = normalize_mode(args.offpeak)

    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=8000')

    rows = candidates(conn, args.limit, args.include_closed, not args.no_prefilter)
    print('目标集      %d 条（visa_status=unknown，正文 >=%d 字符，未问过 LLM%s%s）'
          % (len(rows), visa_llm.MIN_BODY_CHARS, '' if args.include_closed else '，仅在招',
             '，正文提到签证话题' if not args.no_prefilter else ''))
    print('预估花费    ¥%.2f' % (len(rows) * YUAN_EACH))
    print('预估时长    %.0f 分钟' % (len(rows) * SECONDS_EACH / 60))
    print('当前时段    %s' % offpeak_describe())
    bal = balance_cny()
    if bal is not None:
        print('账户余额    ¥%.2f' % bal)
    if args.dry_run:
        print('\n--dry-run：没有调用 API。')
        return 0
    if not rows:
        print('\n没有待判职位。')
        return 0
    if not visa_llm.available():
        print('\n错误：未设置 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY。')
        return 1

    started = time.time()
    stats = {'actionable': 0, 'unknown': 0, 'rejected': 0, 'error': 0}
    by_status, rejects = {}, {}

    for i, row in enumerate(rows, 1):
        if mode == 'wait':
            wait_for_offpeak()
        elif mode == 'stop' and not is_offpeak():
            log.info('进入标准时段，已处理 %d 条后收工。', i - 1)
            break
        if i % 50 == 1:
            bal = balance_cny()
            if bal is not None and bal < args.min_balance:
                log.warning('余额只剩 ¥%.2f，低于下限，停在这里。', bal)
                break
        try:
            verdict = visa_llm.classify(row['description_excerpt'])
        except Exception as exc:
            stats['error'] += 1
            log.debug('job %s 失败: %s', row['id'], exc)
            continue

        if verdict.get('rejected'):
            stats['rejected'] += 1
            rejects[verdict['rejected']] = rejects.get(verdict['rejected'], 0) + 1
        if record(conn, row['id'], verdict, verdict.get('model') or 'unknown'):
            stats['actionable'] += 1
            by_status[verdict['status']] = by_status.get(verdict['status'], 0) + 1
        else:
            stats['unknown'] += 1

        if i % 25 == 0:
            conn.commit()
            el = time.time() - started
            eta = (len(rows) - i) * el / i
            log.info('%d/%d ｜判出 %d ｜仍 unknown %d ｜已花约 ¥%.2f ｜ETA %s',
                     i, len(rows), stats['actionable'], stats['unknown'],
                     i * YUAN_EACH, str(timedelta(seconds=int(eta))))
    conn.commit()

    el = time.time() - started
    print('\n===== 完成 =====')
    print('用时 %s，处理 %d 条，约花 ¥%.2f'
          % (str(timedelta(seconds=int(el))), sum(stats.values()) - stats['rejected'],
             (stats['actionable'] + stats['unknown']) * YUAN_EACH))
    print('判出结论 %d 条，仍 unknown %d 条，调用失败 %d 条'
          % (stats['actionable'], stats['unknown'], stats['error']))
    if by_status:
        print('\n判出的结论：')
        for k, v in sorted(by_status.items(), key=lambda x: -x[1]):
            print('  %-34s %4d' % (k, v))
    if rejects:
        # 被拒的答案单独报：模型答了而我们不信，跟职位没提是两回事。
        print('\n答案被拒（未采信）：')
        for k, v in sorted(rejects.items(), key=lambda x: -x[1]):
            print('  %-52s %4d' % (k[:52], v))
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
