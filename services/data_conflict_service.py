# -*- coding: utf-8 -*-
"""跨来源数值分歧的持久化记录。

同一指标同一年份被多个官方来源覆盖时（例如城市统计公报的已发布值与国家统计局
在线序列的修订值），写入端会按优先级保留其中一个。被舍弃的那个值本身是有研究
价值的信息——它说明官方口径发生过修订——不能只存在于一次调用的返回值里。

本模块把这类分歧落库：保留值与候选值、各自来源与原文链接、相对差异、以及
"为什么保留了这一个"。分歧消失（两边收敛到容差内，或候选值已被采纳）时删除
对应记录，保证表里始终只有当前仍然成立的分歧。
"""
import sqlite3
from datetime import datetime

TABLE = 'data_source_conflicts'


def ensure_conflict_table(conn):
    conn.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE} (
      id INTEGER PRIMARY KEY,
      domain TEXT NOT NULL,
      region_code TEXT NOT NULL,
      region_name TEXT,
      government_scope TEXT NOT NULL DEFAULT '',
      indicator_code TEXT NOT NULL,
      period TEXT NOT NULL,
      kept_value REAL NOT NULL,
      kept_data_status TEXT,
      kept_source_name TEXT,
      candidate_value REAL NOT NULL,
      candidate_data_status TEXT,
      candidate_source_name TEXT NOT NULL,
      candidate_source_url TEXT,
      relative_diff REAL NOT NULL,
      resolution TEXT NOT NULL,
      note TEXT,
      first_seen_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(domain, region_code, government_scope, indicator_code, period,
             candidate_source_name))''')
    conn.execute(f'''CREATE INDEX IF NOT EXISTS idx_{TABLE}_lookup
                     ON {TABLE}(domain, region_name, period)''')


def _key(conflict):
    return (conflict['domain'], conflict['region_code'],
            conflict.get('government_scope') or '', conflict['indicator_code'],
            conflict['period'], conflict['candidate_source_name'])


def record_conflict(conn, conflict):
    """新分歧插入；已存在则更新数值，first_seen_at 保持首次发现时间。"""
    ensure_conflict_table(conn)
    now = datetime.now().isoformat()
    conn.execute(f'''INSERT INTO {TABLE} (
      domain,region_code,region_name,government_scope,indicator_code,period,
      kept_value,kept_data_status,kept_source_name,candidate_value,
      candidate_data_status,candidate_source_name,candidate_source_url,
      relative_diff,resolution,note,first_seen_at,updated_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(domain,region_code,government_scope,indicator_code,period,
                  candidate_source_name) DO UPDATE SET
        region_name=excluded.region_name,kept_value=excluded.kept_value,
        kept_data_status=excluded.kept_data_status,
        kept_source_name=excluded.kept_source_name,
        candidate_value=excluded.candidate_value,
        candidate_data_status=excluded.candidate_data_status,
        candidate_source_url=excluded.candidate_source_url,
        relative_diff=excluded.relative_diff,resolution=excluded.resolution,
        note=excluded.note,updated_at=excluded.updated_at''',
      (conflict['domain'], conflict['region_code'], conflict.get('region_name'),
       conflict.get('government_scope') or '', conflict['indicator_code'],
       conflict['period'], conflict['kept_value'], conflict.get('kept_data_status'),
       conflict.get('kept_source_name'), conflict['candidate_value'],
       conflict.get('candidate_data_status'), conflict['candidate_source_name'],
       conflict.get('candidate_source_url'), conflict['relative_diff'],
       conflict.get('resolution') or 'kept_existing', conflict.get('note'),
       now, now))


def clear_conflict(conn, conflict):
    """分歧不再成立（收敛或候选值已被采纳）时删除记录。"""
    ensure_conflict_table(conn)
    conn.execute(f'''DELETE FROM {TABLE} WHERE domain=? AND region_code=?
      AND government_scope=? AND indicator_code=? AND period=?
      AND candidate_source_name=?''', _key(conflict))


def list_conflicts(conn, domain=None):
    ensure_conflict_table(conn)
    sql = f'SELECT * FROM {TABLE}'
    args = ()
    if domain:
        sql += ' WHERE domain=?'
        args = (domain,)
    sql += ' ORDER BY ABS(relative_diff) DESC, region_name, period'
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, args)]
