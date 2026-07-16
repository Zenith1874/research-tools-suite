# -*- coding: utf-8 -*-
"""统计局 70 城官方指数与安居客二手挂牌价的双口径比较。"""
import math
import os
import sqlite3

from services.anjuke_listing_service import (
    DEFAULT_DB_PATH as DEFAULT_LISTING_DB,
    FOCUS_CITIES,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OFFICIAL_DB = os.path.join(ROOT, 'pboc_data.db')
ROW_FORMULA = ('official_new_yoy_pct = new_home_yoy_idx - 100; '
               'official_second_yoy_pct = second_home_yoy_idx - 100; '
               'divergence = listing_yoy_pct - official_second_yoy_pct')


def _read_official(db_path, period=None):
    if not os.path.exists(db_path):
        return None, {}
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if period is None:
            period = conn.execute('SELECT MAX(period) FROM housing_city_observations').fetchone()[0]
        columns = {r[1] for r in conn.execute('PRAGMA table_info(housing_city_observations)')}
        # 静态查询二选一(避免 f-string 拼 SQL 触发注入告警;此处无用户输入,period 仍参数化)
        has_src = 'source_url' in columns
        q_with = ('''SELECT city, period, indicator_code, value, source_url
            FROM housing_city_observations WHERE period=? AND indicator_code IN
            ('new_home_yoy_idx','second_home_yoy_idx')''')
        q_without = ('''SELECT city, period, indicator_code, value, NULL AS source_url
            FROM housing_city_observations WHERE period=? AND indicator_code IN
            ('new_home_yoy_idx','second_home_yoy_idx')''')
        rows = conn.execute(q_with if has_src else q_without, (period,)).fetchall() if period else []
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    by_city = {}
    for row in rows:
        item = by_city.setdefault(row['city'], {})
        item[row['indicator_code']] = row['value']
        if row['source_url']:
            item['source_url'] = row['source_url']
    return period, by_city


def _read_listing(db_path, period=None):
    if not os.path.exists(db_path):
        return period, {}
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if period is None:
            period = conn.execute('SELECT MAX(period) FROM anjuke_city_listings').fetchone()[0]
        rows = conn.execute('SELECT * FROM anjuke_city_listings WHERE period=?', (period,)).fetchall() if period else []
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return period, {r['city']: dict(r) for r in rows}


def _read_official_history(db_path):
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(housing_city_observations)')}
        has_src = 'source_url' in columns
        q_with = ('''SELECT city, period, value, source_url FROM housing_city_observations
            WHERE indicator_code='second_home_yoy_idx' ORDER BY city, period''')
        q_without = ('''SELECT city, period, value, NULL AS source_url FROM housing_city_observations
            WHERE indicator_code='second_home_yoy_idx' ORDER BY city, period''')
        rows = conn.execute(q_with if has_src else q_without).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return {(r['city'], r['period']): {'value': r['value'], 'source_url': r['source_url']}
            for r in rows}


def _read_listing_history(db_path):
    if not os.path.exists(db_path):
        return {}
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute('''SELECT city, period, yoy_pct, source_url
            FROM anjuke_city_listings WHERE yoy_pct IS NOT NULL ORDER BY city, period''').fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return {(r['city'], r['period']): dict(r) for r in rows}


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return None if dx == 0 or dy == 0 else round(numerator / (dx * dy), 4)


def _sign(value):
    return 1 if value > 0 else (-1 if value < 0 else 0)


def build_housing_compare_payload(official_db_path=None, listing_db_path=None, period=None):
    official_db = official_db_path or DEFAULT_OFFICIAL_DB
    listing_db = listing_db_path or DEFAULT_LISTING_DB
    if period is None:
        official_latest, _ = _read_official(official_db)
        listing_latest, _ = _read_listing(listing_db)
        available = [p for p in (official_latest, listing_latest) if p]
        target_period = min(available) if len(available) == 2 else (available[0] if available else None)
    else:
        target_period = period
    _, official = _read_official(official_db, target_period)
    _, listing = _read_listing(listing_db, target_period)

    comparison, not_comparable = [], []
    for city in sorted(set(official) | set(listing)):
        off = official.get(city, {})
        listed = listing.get(city)
        new_idx = off.get('new_home_yoy_idx')
        second_idx = off.get('second_home_yoy_idx')
        listing_yoy = listed.get('yoy_pct') if listed else None
        missing = []
        if new_idx is None:
            missing.append('official_new_yoy')
        if second_idx is None:
            missing.append('official_second_yoy')
        if listing_yoy is None:
            missing.append('listing_yoy')
        if missing:
            not_comparable.append({'city': city, 'period': target_period, 'missing': missing})
            continue
        new_pct = round(float(new_idx) - 100, 2)
        second_pct = round(float(second_idx) - 100, 2)
        listing_pct = round(float(listing_yoy), 2)
        comparison.append({
            'city': city, 'period': target_period,
            'official_new_yoy_pct': new_pct,
            'official_second_yoy_pct': second_pct,
            'listing_yoy_pct': listing_pct,
            'divergence': round(listing_pct - second_pct, 2),
            'data_status': 'derived', 'formula': ROW_FORMULA,
            'official_source': '国家统计局70城商品住宅销售价格指数',
            'listing_source': '安居客挂牌价（非官方口径）',
            'official_source_url': off.get('source_url'),
            'listing_source_url': listed.get('source_url'),
        })

    positive = sorted((r for r in comparison if r['divergence'] >= 0),
                      key=lambda r: r['divergence'], reverse=True)[:10]
    negative = sorted((r for r in comparison if r['divergence'] < 0),
                      key=lambda r: r['divergence'])[:10]
    xs = [r['official_second_yoy_pct'] for r in comparison]
    ys = [r['listing_yoy_pct'] for r in comparison]
    same = sum(_sign(x) == _sign(y) for x, y in zip(xs, ys))
    direction_rate = round(same / len(comparison) * 100, 2) if comparison else None

    official_history = _read_official_history(official_db)
    listing_history = _read_listing_history(listing_db)
    official_history_by_city = {}
    for (city, history_period), official_row in official_history.items():
        if city not in FOCUS_CITIES:
            continue
        official_history_by_city.setdefault(city, []).append({
            'city': city,
            'period': history_period,
            'official_second_yoy_pct': round(float(official_row['value']) - 100, 2),
            'data_status': 'official',
            'source_url': official_row['source_url'],
        })
    history_by_city = {}
    for (city, history_period), listed in listing_history.items():
        official_row = official_history.get((city, history_period))
        if not official_row:
            continue
        official_pct = round(float(official_row['value']) - 100, 2)
        listing_pct = round(float(listed['yoy_pct']), 2)
        history_by_city.setdefault(city, []).append({
            'city': city,
            'period': history_period,
            'official_second_yoy_pct': official_pct,
            'listing_yoy_pct': listing_pct,
            'divergence': round(listing_pct - official_pct, 2),
            'data_status': 'derived',
            'formula': 'divergence = listing_yoy_pct - official_second_yoy_pct',
            'official_source_url': official_row['source_url'],
            'listing_source_url': listed['source_url'],
        })
    history_points = [row for rows in history_by_city.values() for row in rows]
    history_periods = [row['period'] for row in history_points]
    return {
        'period': target_period,
        'data_status': 'derived' if comparison else 'missing',
        'comparison_table': comparison,
        'divergence_ranking': {
            'listing_more_optimistic': positive,
            'listing_more_pessimistic': negative,
        },
        'scatter_data': [{'city': r['city'], 'x': r['official_second_yoy_pct'],
                          'y': r['listing_yoy_pct']} for r in comparison],
        'official_history_by_city': official_history_by_city,
        'history_by_city': history_by_city,
        'history_summary': {
            'cities': len(history_by_city),
            'points': len(history_points),
            'earliest': min(history_periods) if history_periods else None,
            'latest': max(history_periods) if history_periods else None,
            'data_status': 'derived' if history_points else 'missing',
        },
        'summary': {
            'comparable_cities': len(comparison),
            'pearson_correlation': _pearson(xs, ys),
            'pearson_formula': 'r = sum((x-xbar)(y-ybar)) / sqrt(sum((x-xbar)^2) sum((y-ybar)^2))',
            'direction_agreement_pct': direction_rate,
            'direction_formula': 'count(sign(official_second_yoy_pct) = sign(listing_yoy_pct)) / N * 100',
            'data_status': 'derived',
        },
        'not_comparable': not_comparable,
        'notes': ['主对标为官方二手住宅同比；新房指数仅作旁证，因为限价和供给结构影响更强。',
                  '成交结构加权指数与挂牌均价定义不同；分歧是市场信号，不应解释成测量误差。'],
    }
