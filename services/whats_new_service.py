# -*- coding: utf-8 -*-
"""What's New：跨模块"新数据事件"记录 + 首页横幅数据源。

- data_events 表：每当某模块出现新一期官方数据(与上次记录不同)就记一条事件(按 module+period 去重)。
- /api/whats-new 返回：最近事件、各模块最新期数、近7天高相关 A* 文章、最近抓取失败。
- 若设置 SMTP_HOST/SMTP_USER/SMTP_PASS/NOTIFY_TO 环境变量，新事件会尝试发邮件(失败只记日志)。
"""
import json
import logging
import os
import smtplib
import sqlite3
from datetime import datetime, timedelta
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def connect(db_path):
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def ensure_events_table(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS data_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        module TEXT, title TEXT, period TEXT, detail TEXT,
        created_at TEXT,
        UNIQUE(module, period)
    )''')
    conn.commit()


# 各模块"最新期数"探针：module -> (标题, SQL)。SQL 返回单值最新期。
_PROBES = [
    ('central_government_debt', '中央政府债务余额(季度)',
     "SELECT MAX(period) FROM fiscal_debt_observations WHERE indicator_code='central_government_debt_balance'"),
    ('local_government_debt', '地方政府债务(月度)',
     "SELECT MAX(period) FROM fiscal_debt_observations WHERE indicator_code='local_debt_balance_total'"),
    ('pboc_balance_sheet', '央行资产负债表(月度)',
     'SELECT MAX(period) FROM pboc_balance_sheet_observations'),
    ('treasury_issuance', '国债发行(最新发行月)',
     "SELECT MAX(substr(issue_date,1,7)) FROM mof_treasury_bond_issuances WHERE actual_issue_amount IS NOT NULL"),
    ('fiscal_budget', '全国财政收支(YTD)',
     'SELECT MAX(period) FROM fiscal_budget_observations'),
    ('china_rates_lpr', 'LPR 报价',
     "SELECT MAX(period) FROM china_rates_observations WHERE indicator_code='LPR_1Y'"),
    ('us_macro_unrate', '美国失业率',
     "SELECT MAX(period) FROM us_macro_observations WHERE indicator_code='UNRATE'"),
    ('pboc_monthly', '央行金融统计(月度)',
     'SELECT MAX(month) FROM monthly_data'),
    ('housing_70city', '70城房价(月度)',
     'SELECT MAX(period) FROM housing_city_observations'),
    ('anjuke_listing', '安居客挂牌(月度)',
     'SELECT MAX(period) FROM anjuke_listing.anjuke_city_listings'),
]


def _maybe_send_email(subject, body):
    host, user, pw, to = (os.environ.get(k) for k in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASS', 'NOTIFY_TO'))
    if not all([host, user, pw, to]):
        return False
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = user
        msg['To'] = to
        with smtplib.SMTP_SSL(host, int(os.environ.get('SMTP_PORT', 465)), timeout=20) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        return True
    except Exception as e:
        log.warning(f'What\'s New 邮件发送失败(忽略): {e}')
        return False


def check_and_record_new_periods(db_path):
    """探各模块最新期，与 data_events 已记录的比较；有新期就记事件(去重)。返回新事件列表。"""
    new_events = []
    with connect(db_path) as conn:
        ensure_events_table(conn)
        listing_db = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'data', 'housing_listing.db')
        if os.path.exists(listing_db):
            try:
                conn.execute('ATTACH DATABASE ? AS anjuke_listing', (listing_db,))
            except sqlite3.OperationalError:
                pass
        now = datetime.now().isoformat()
        for module, title, sql in _PROBES:
            try:
                row = conn.execute(sql).fetchone()
            except sqlite3.OperationalError:
                continue    # 表尚未创建
            period = row[0] if row else None
            if not period:
                continue
            cur = conn.execute(
                'INSERT OR IGNORE INTO data_events (module,title,period,detail,created_at) VALUES (?,?,?,?,?)',
                (module, title, str(period), f'{title} 更新到 {period}', now))
            if cur.rowcount:
                new_events.append({'module': module, 'title': title, 'period': str(period)})
        conn.commit()
    # 只对"非首轮建档"的增量发邮件：首轮一次会插入全部模块，跳过通知避免刷屏
    if new_events and len(new_events) <= 4:
        body = '\n'.join(f"· {e['title']} → {e['period']}" for e in new_events)
        _maybe_send_email(f'[研究工具集] {len(new_events)} 项数据更新', body)
    return new_events


def build_whats_new_payload(db_path):
    check_and_record_new_periods(db_path)
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    with connect(db_path) as conn:
        ensure_events_table(conn)
        events = [dict(r) for r in conn.execute(
            'SELECT module,title,period,created_at FROM data_events ORDER BY created_at DESC, id DESC LIMIT 20')]
        try:
            astar_high = [dict(r) for r in conn.execute("""
                SELECT a.id, a.title, a.journal_title, a.publication_date, c.relevance_score
                FROM astar_articles a JOIN astar_article_classifications c ON c.article_id=a.id
                WHERE a.is_duplicate=0 AND a.publication_date>=? AND c.relevance_score>=60
                ORDER BY c.relevance_score DESC LIMIT 10""", (week_ago,))]
            astar_week_count = conn.execute(
                'SELECT COUNT(*) FROM astar_articles WHERE is_duplicate=0 AND publication_date>=?',
                (week_ago,)).fetchone()[0]
        except sqlite3.OperationalError:
            astar_high, astar_week_count = [], 0
        try:
            failures = [dict(r) for r in conn.execute("""
                SELECT source_type, error_message, finished_at FROM fiscal_debt_update_logs
                WHERE success=0 AND finished_at>=? ORDER BY finished_at DESC LIMIT 5""", (week_ago,))]
        except sqlite3.OperationalError:
            failures = []
    return {
        'generated_at': datetime.now().isoformat(),
        'events': events,
        'astar_recent_high': astar_high,
        'astar_week_count': astar_week_count,
        'update_failures': failures,
    }
